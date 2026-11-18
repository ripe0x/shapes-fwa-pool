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

from vault import ACTIVE, OWED, BPS, Vault

TRACE = Path(__file__).parent / "out/reconcile-trace.jsonl"
MINT_FEE = 10**15  # Shapes mintFee at the fork block (0.001 ETH per 0.1 ETH mint)


def compare_snapshot(v, r, failures):
    def check(field, model, chain):
        if model != chain:
            failures.append(f"{r['step']}.{field}: model {model} chain {chain} (diff {model - chain})")

    v.pay_keeper(r["pay"])
    for field, amount in (("balance", v.balance), ("totalShares", v.total_shares), ("lastNav", v.last_nav),
                          ("pendingDepositTotal", v.pending_total), ("redemptionReserve", v.redemption_reserve),
                          ("lockedShares", v.locked_shares), ("open", len(v.positions)),
                          ("idle", len(v.idle_packs)), ("loose", v.loose_shapes),
                          ("aliceShares", v.share_balance("alice")), ("bobShares", v.share_balance("bob")),
                          ("trackedValue", v.tracked_value), ("idleValue", v.idle_value),
                          ("activeBacking", v.active_backing), ("activeCount", v.active_count),
                          ("idleFunding", v.idle_funding),
                          ("feeDebtSum", v.fee_debt_sum), ("allocatedValue", v.allocated_value),
                          ("pendingReceipts", len(v.receipts)), ("cursor", v.acquisition_cursor),
                          ("reservedCount", sum(p.state != OWED for p in v.positions.values())),
                          ("feeCredit", v.fee_credit), ("processingPool", v.processing_pool),
                          ("distributionReserve", v.distribution_reserve), ("claimableTotal", v.claimable_total)):
        check(field, amount, r[field])
    check("aliceClaimable", v.claimable.get("alice", 0), r["aliceClaimable"])
    redemption = v.redemptions.get("alice")
    check("aliceLocked", redemption.shares if redemption else 0, r["aliceLocked"])
    if set(v.positions) != {p["id"] for p in r["positions"]}:
        failures.append(f"{r['step']}: position identity sets differ")
    for live in r["positions"]:
        p = v.positions[live["id"]]
        for field, amount in (("value", p.value), ("backing", p.backing), ("feeDebt", p.fee_debt),
                              ("allocatedAt", p.allocated_at), ("state", p.state)):
            check(f"position[{live['id']}].{field}", amount, live[field])


def reconcile_cycle():
    rows = [json.loads(line) for line in TRACE.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    s = by["setup"]
    v = Vault(seed=3 * 10**18, balance=s["deployBalance"], reserve=0)
    failures = []

    def check(step, field, model, chain):
        if model != chain:
            failures.append(f"{step}.{field}: model {model} chain {chain} (diff {model - chain})")

    # Only the selected listing belongs to this vault. Real third-party filler preserves
    # the historical VRF weight; it is neither vault capital nor simulated inventory.
    sel = by["selected"]
    selected = s["selectedListing"]
    v.acquisition_cursor = s["initCursor"]
    # Admissions precede the real selection. Do not expose its future journal prefix
    # to the legitimate unexposed advance performed by the first admission.
    v.completed_prefix = s["initCursor"]
    v.restock(s["count"], s["units"], MINT_FEE, s["backings"])
    for live, backing in zip(sel["positions"], s["backings"], strict=True):
        v.list(live["id"], backing, fee_debt=s["activationDebt"])
    v.completed_prefix = sel["completedPrefix"]
    v.pay_keeper(s["selectPay"])
    check("setup", "balance", v.balance, s["balance"])

    fee = s["acqFee"]
    distributable = fee - fee * s["acqCutBps"] // BPS
    distributable -= distributable * s["acqCrownBps"] // BPS
    share = distributable // s["acqActive"]
    paid_by_fwa = sel["pendingFeesSum"] + sel["feeCredit"]
    if abs(paid_by_fwa - share * s["count"]) > s["count"]:
        failures.append(f"fee share: chain {paid_by_fwa} vs formula {share * s['count']}")
    credit = sel["feeCredit"]
    v.fee_credit = credit

    def compare(step):
        compare_snapshot(v, by[step], failures)

    compare("selected")
    v.bid_settled(selected)
    compare("bid")  # purchaser takes the bid: no vault ETH moves
    ch = by["charges"]
    v.deposit("alice", 10**18, ch["ckA"], ch["chargeA"])
    v.deposit("bob", 5 * 10**17, ch["ckB"], ch["chargeB"])
    compare("deposits")
    v.select(selected, sel["positions"][0]["liveAllocatedAt"])
    v.acquisition_cursor += 1
    v.sync_owned(selected)
    v.prune(16)
    compare("sync")
    for i in v.positions:
        v.harvest_listing(i)
    v.receive_fees(sel["pendingFeesSum"] + credit)
    v.fee_credit = 0
    compare("harvest")
    # FWA expires the remaining real request. Its external completed prefix is an input;
    # these entries are foreign/refunded and cannot change vault principal or membership.
    v.completed_prefix = by["catchup"]["completedPrefix"]
    while v.acquisition_cursor < v.completed_prefix:
        v.process_journal([None] * min(16, v.completed_prefix - v.acquisition_cursor))
    compare("catchup")
    live = by["list"]["positions"][0]
    v.list(live["id"], by["relistBacking"]["backing"], fee_debt=live["liveFeeDebt"])
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
    held = (v.balance + sum(p.backing + p.value for p in v.positions.values())
            + sum(v.idle_packs) + v.loose_shapes * 10**16)
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


def reconcile_partial():
    trace = TRACE.with_name("reconcile-partial-trace.jsonl")
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    setup = by["setup"]
    v = Vault(seed=10**16, balance=setup["deployBalance"], reserve=5 * 10**15)
    v.acquisition_cursor = v.completed_prefix = setup["initCursor"]
    failures = []

    def compare(step):
        compare_snapshot(v, by[step], failures)

    charges = by["depositCharge"]
    v.deposit("alice", 10**18, charges["ck"], charges["charge"])
    compare("deposit")
    v.checkpoint()
    compare("checkpoint1")
    build = by["restockInputs"]
    v.restock(build["count"], build["units"], setup["mintFee"], build["proposals"])
    compare("restock")
    proposals = by["listInputs"]
    live = {p["id"]: p for p in by["list"]["positions"]}
    for id_, backing in zip(proposals["ids"], proposals["backings"], strict=True):
        v.list(id_, backing, fee_debt=live[id_]["liveFeeDebt"])
    compare("list")
    rc = by["redeemCharge"]
    v.request_redeem("alice", v.share_balance("alice"), rc["ck"], rc["total"] - rc["ck"])
    compare("redeem")
    v.checkpoint()
    if not 0 < v.locked_shares < v.redemptions["alice"].shares:
        failures.append("partial: real first fill must leave some, but not all, shares locked")
    compare("partial")
    compare("windDown")  # owner flag changes no financial bucket
    for id_ in list(v.positions):
        v.unlist(id_)
    compare("unlist")
    while v.idle_packs or v.loose_shapes:
        v.liquidate_one()
    compare("liquidate")
    v.checkpoint()
    compare("checkpoint2")
    got = v.claim("alice")
    compare("claim")
    if got != by["aliceReceived"]["amount"]:
        failures.append(f"claim: model {got} vs actual {by['aliceReceived']['amount']}")
    ins = setup["deployBalance"] + 10**18 + charges["ck"] + rc["total"]
    outs = v.balance + got + v.keeper_paid + v.mint_fees
    if ins != outs:
        failures.append(f"partial ledger: in {ins} vs held+out {outs}")
    print(f"partial/wind-down: claim {got}, keeper pay {v.keeper_paid}, mint fees {v.mint_fees}, "
          f"remaining redemption-rounding reserve {v.redemption_reserve} wei")
    if failures:
        print("MISMATCH\n" + "\n".join(failures))
        return 1
    print("reconciled: partial fill, wind-down, full exit and every bucket match to the wei")
    return 0


def main():
    cycle = reconcile_cycle()
    partial = reconcile_partial()
    return max(cycle, partial)


if __name__ == "__main__":
    sys.exit(main())
