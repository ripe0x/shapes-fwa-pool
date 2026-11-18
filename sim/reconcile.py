#!/usr/bin/env python3
"""Replay the fork trace from test/fork/ForkReconcile.t.sol through sim/vault.py and require
every vault number to match the chain.

Tolerance: zero wei for everything the vault computes. FWA's per-listing fee share is checked
against FWA's formula within 1 wei per listing (its accumulator floors per listing and ceils
each listing's starting debt); the model then takes the fee amounts FWA actually paid.

Run: forge test --match-path test/fork/ForkReconcile.t.sol ... && python3 sim/reconcile.py
"""
import json
import sys
from pathlib import Path

from vault import BPS, Vault

TRACE = Path(__file__).parent / "out/reconcile-trace.jsonl"
MINT_FEE = 10**15  # Shapes mintFee at the fork block (0.001 ETH per 0.1 ETH mint)


def main():
    rows = [json.loads(line) for line in TRACE.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    s = by["setup"]
    v = Vault(seed=3 * 10**18, balance=s["deployBalance"], reserve=0)
    failures = []

    def check(step, field, model, chain):
        if model != chain:
            failures.append(f"{step}.{field}: model {model} chain {chain} (diff {model - chain})")

    # _select: restock 30 packs of 3 units, list all 30 at the cap, then the real acquisition.
    v.restock(s["count"], s["units"], MINT_FEE)
    for i in range(s["count"]):
        v.list(i, s["backing"])
    v.pay_keeper(s["selectPay"])
    check("setup", "balance", v.balance, s["balance"])

    # FWA's flat share per listing for that acquisition, from its own formula.
    fee = s["acqFee"]
    distributable = fee - fee * s["acqCutBps"] // BPS
    distributable -= distributable * s["acqCrownBps"] // BPS
    share = distributable // s["acqActive"]
    sel = by["selected"]
    paid_by_fwa = sel["pendingFeesSum"] + sel["feeCredit"]
    if abs(paid_by_fwa - share * s["count"]) > s["count"]:
        failures.append(f"fee share: chain {paid_by_fwa} vs formula {share * s['count']}")
    selected = 0
    for i in range(1, s["count"]):
        v.accrue(i, sel["pendingFeesSum"] // (s["count"] - 1))
    credit = sel["feeCredit"]

    def compare(step):
        r = by[step]
        v.pay_keeper(r["pay"])
        check(step, "balance", v.balance, r["balance"])
        check(step, "totalShares", v.total_shares, r["totalShares"])
        check(step, "lastNav", v.last_nav, r["lastNav"])
        check(step, "pendingDepositTotal", v.pending_total, r["pendingDepositTotal"])
        check(step, "redemptionReserve", v.redemption_reserve, r["redemptionReserve"])
        check(step, "lockedShares", v.locked_shares, r["lockedShares"])
        check(step, "open", len(v.positions), r["open"])
        check(step, "idle", len(v.idle_packs), r["idle"])
        check(step, "loose", v.loose_shapes, r["loose"])
        check(step, "aliceShares", v.share_balance("alice"), r["aliceShares"])
        check(step, "bobShares", v.share_balance("bob"), r["bobShares"])

    compare("selected")
    compare("bid")  # purchaser takes the bid: no vault ETH moves
    ch = by["charges"]
    v.deposit("alice", 10**18, ch["ckA"], ch["chargeA"])
    v.deposit("bob", 5 * 10**17, ch["ckB"], ch["chargeB"])
    compare("deposits")
    v.resolve_bid(selected)
    compare("sync")
    for p in v.positions.values():
        p.pending_fees = 0
    v.receive_fees(sel["pendingFeesSum"] + credit)
    compare("harvest")
    v.list("relist", by["relistBacking"]["backing"])  # listed with FWA's queue drained: active
    compare("list")
    v.checkpoint()
    compare("checkpoint1")
    rc = by["redeemCharge"]
    v.request_redeem("alice", v.share_balance("alice"), rc["ck"], rc["total"] - rc["ck"])
    compare("redeem")
    v.checkpoint()
    compare("checkpoint2")
    got = v.claim("alice")
    compare("claim")
    check("claim", "aliceReceived", got, by["aliceReceived"]["amount"])

    # The ledger: every wei in equals every wei out plus what the vault still holds.
    held = (v.balance + sum(p.backing + p.units * 10**16 for p in v.positions.values())
            + sum(v.idle_packs) * 10**16 + v.loose_shapes * 10**16)
    ins = s["deployBalance"] + 15 * 10**17 + ch["ckA"] + ch["ckB"] + rc["total"] + v.fees_received
    outs = v.keeper_paid + v.mint_fees + got + v.backing_lost
    check("ledger", "held + out == in", held + outs, ins)
    steps = [r["step"] for r in rows]
    print(f"steps: {', '.join(steps)}")
    print(f"ledger: fees received {v.fees_received}, keeper paid {v.keeper_paid}, mint fees {v.mint_fees}, "
          f"backing lost {v.backing_lost}")
    if failures:
        print("MISMATCH")
        print("\n".join(failures))
        return 1
    print("reconciled: every vault number matches the fork run to the wei")
    return 0


if __name__ == "__main__":
    sys.exit(main())
