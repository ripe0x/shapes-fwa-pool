#!/usr/bin/env python3
"""Holder withdrawal workflow and a separate owner wind-down at the campaign's fresh fork block.

Run through rehearsal_batch.py (`--fork-block <recent> --phases rehearse_current.py`). Production
paths only: script/deploy.sh with deploy/canary.json values (a fresh test owner replaces the real
owner, who cannot sign locally), the normal keeper for routine work, and keeper/keeper.py run by
the holder (and, in the wind-down, by the owner) for the unpaid exit work, with explicit
per-call and aggregate loss limits. No oracle or fee parameter changes. Writes
sim/out/rehearsal-current.json.

1. Deposit to the cap; the keeper prices it at the blackout and builds and lists.
2. Partial redemption: the holder requests half, runs the bounded exit work at its own gas, the
   checkpoint prices it, the holder claims.
3. Complete redemption the same way; only the seed's dead shares remain.
4. From a snapshot taken after step 1: the owner starts the wind-down instead, runs the unwind
   work at its own gas, the holder redeems everything and claims.
"""
import json
import subprocess
import sys
from pathlib import Path

import rehearse_canary as rc
from rehearse_canary import FWA, ROOT, call, cast, ids, impersonate, num, send, state, warp_to

OWNER = rc.OWNER
HOLDER_LIMITS = ["--max-loss-wei", str(2 * 10**15), "--max-total-loss-wei", str(10**16)]
PROTECTED = ("pendingDepositTotal", "redemptionReserve", "distributionReserve", "claimableTotal", "processingPool")


def protected():
    return {k: num(call(rc.VAULT, f"{k}()(uint256)")) for k in PROTECTED}


def operator(who, state_file, *limits):
    """keeper/keeper.py run by `who` with its own state and index, as any holder can."""
    rc.B.load_manifest()
    for _ in range(16):
        command = ["python3", "keeper/keeper.py", rc.VAULT, "--send", "--from", who, "--rpc", rc.RPC,
                   "--state", state_file, "--index", state_file + ".sqlite", *limits]
        for attempt in range(6):
            result = subprocess.run(command, capture_output=True, text=True, cwd=ROOT)
            out = result.stdout + result.stderr
            print("  " + out.replace("\n", "\n  "), flush=True)
            # A pass that only failed to read (the public fork gateway throttles) is retried.
            if not result.returncode or "read failed" not in out:
                break
        if result.returncode:
            raise RuntimeError(f"keeper.py for {who} exited {result.returncode}: {out}")
        if "event index at block" not in out:
            saved = json.loads(Path(state_file).read_text())
            if any(not e["status"] or e["gas_limit"] > rc.B.MAX_GAS for e in saved["counted"] if not e.get("reorged")):
                raise RuntimeError("operator receipt status or gas limit mismatch")
            rc.B.append_action(dict(operation="holder-run keeper", sender=who, arguments=list(limits), output=out,
                                    tx_state=saved))
            return saved
    raise RuntimeError("index reconstruction exceeded 16 bounded passes")


def routine():
    """The normal keeper's pass, retried when it only failed to read through the fork gateway."""
    for attempt in range(6):
        try:
            return rc.keeper()
        except RuntimeError as e:
            if "read failed" not in str(e) or attempt == 5:
                raise


def redeem(holder, shares, operator_state, operator_who, limits):
    """Request, bounded exit work, checkpoint at the blackout, claim. Returns the claimed wei."""
    charge = rc.redeem_charge(shares)
    send(holder, rc.VAULT, "requestRedeem(uint256)", shares, value=charge)
    rc.expire_queue()
    for _ in range(8):
        operator(operator_who, operator_state, *limits)
        warp_to(42360)
        rc.expire_queue()
        routine()  # the normal keeper prices it; checkpoint is paid from the request charges
        if num(call(rc.VAULT, "lockedShares()(uint256)")) == 0:
            break
        warp_to(60)
    else:
        raise RuntimeError("redemption not priced after eight blackouts")
    before = num(cast("balance", holder))
    send(holder, rc.VAULT, "claim()")
    return charge, before


def ledger(holder, start_balance, phase_from):
    """Exact holder cash result from balances and the vault's own events."""
    logs = lambda sig: json.loads(rc.sh("cast", "logs", "--rpc-url", rc.RPC, "--json", "--from-block", str(phase_from),  # noqa: E731
                                        "--address", rc.VAULT, sig) or "[]")
    claims = sum(int(x["data"], 16) for x in logs("Claimed(address indexed,uint256)")
                 if x["topics"][1][-40:].lower() == holder[2:].lower())
    pay = sum(int(x["data"], 16) for x in logs("KeeperPaid(address indexed,uint256)"))
    return dict(holder_claims_wei=claims, keeper_pay_wei=pay, holder_balance_change_wei=num(cast("balance", holder)) - start_balance)


def main():
    rc.B.load_manifest()
    for actor in rc.B.ACTORS.values():
        impersonate(actor)
    values = json.loads((ROOT / "deploy/canary.json").read_text())
    real_owner, values["owner"] = values["owner"], OWNER
    rc.VALUES = values
    rc.VAULT = rc.B.deploy(values, "current")
    rc.TOKEN = call(FWA, "token()(address)")
    vault, holder = rc.VAULT, rc.HOLDER
    head = num(cast("block-number"))
    report = dict(fork_block=rc.B.FORK_BLOCK, fork_hash=rc.B.load_manifest()["fork_hash"], vault=vault,
                  values=values, real_owner_replaced=real_owner, phases={})
    tmp = Path(rc.KEEPER_STATE).parent
    print("block", head, "vault", vault)

    # 1. Deposit to the cap, price, build and list.
    start = num(cast("balance", holder))
    ck = num(call(vault, "requestCharge()(uint256)"))
    deposit = ck + values["tvlCapWei"] - values["seedWei"]
    send(holder, vault, "deposit()", value=deposit)
    warp_to(42360)
    rc.expire_queue()
    routine()
    warp_to(60)
    rc.expire_queue()
    routine()
    built = state("listed")
    listed = ids()
    assert listed, "nothing listed"
    snapshot = rc.B.rpc("evm_snapshot")
    phase_block = num(cast("block-number"))
    guard0 = protected()

    # 2. Partial redemption run by the holder.
    shares = num(call(vault, "shareBalance(address)(uint256)", holder))
    holder_state = str(tmp / "holder-state.json")
    charge1, _ = redeem(holder, shares // 2, holder_state, holder, HOLDER_LIMITS)
    partial = state("partial withdrawal claimed")
    remaining = num(call(vault, "shareBalance(address)(uint256)", holder))
    report["phases"]["partial"] = dict(shares_requested=shares // 2, shares_remaining=remaining, charge_wei=charge1,
                                       protected=protected(), open=partial["open"], idle=partial["idle"])

    # 3. Complete redemption run by the holder.
    charge2, _ = redeem(holder, remaining, holder_state, holder, HOLDER_LIMITS)
    done = state("complete withdrawal claimed")
    held = json.loads(Path(holder_state).read_text())
    result = ledger(holder, start, phase_block - 1)
    result.update(deposit_wei=deposit, charges_wei=charge1 + charge2,
                  holder_tx_gas_wei=-(result["holder_balance_change_wei"] + deposit + charge1 + charge2
                                     - result["holder_claims_wei"]),
                  holder_operator_spent_wei=held["stats"]["spent_wei"], holder_operator_paid_wei=held["stats"]["paid_wei"],
                  holder_operator_calls=[dict(label=e["label"], gas_used=e["gas_used"], cost=e["cost"], pay=e["pay"])
                                         for e in held["counted"]],
                  shares_remaining=num(call(vault, "shareBalance(address)(uint256)", holder)),
                  total_shares=num(call(vault, "totalShares()(uint256)")), dead_shares=num(call(vault, "DEAD_SHARES()(uint256)")),
                  vault_balance_wei=done["balance"], open=done["open"], idle=done["idle"], loose=done["loose"],
                  protected=protected())
    assert result["shares_remaining"] == 0 and result["total_shares"] == result["dead_shares"]
    # The redemption index rounds each claim down; the remainder (a few wei) stays reserved.
    assert all(v == 0 for k, v in result["protected"].items() if k not in ("processingPool", "redemptionReserve"))
    assert result["protected"]["redemptionReserve"] <= 16, result["protected"]
    report["phases"]["holder_workflow"] = result

    # 4. Separate owner wind-down from the listed state.
    assert rc.B.rpc("evm_revert", snapshot)
    assert protected() == guard0
    owner_state = str(tmp / "owner-state.json")
    send(OWNER, vault, "startWindDown()")
    shares = num(call(vault, "shareBalance(address)(uint256)", holder))
    redeem(holder, shares, owner_state, OWNER, HOLDER_LIMITS)
    for _ in range(4):  # the owner finishes unwinding the seed's positions
        if not ids() and not ids("idle"):
            break
        operator(OWNER, owner_state, *HOLDER_LIMITS)
    end = state("wound down")
    owner_ops = json.loads(Path(owner_state).read_text())
    report["phases"]["owner_wind_down"] = dict(
        ledger(holder, start, phase_block - 1), owner_spent_wei=owner_ops["stats"]["spent_wei"],
        owner_paid_wei=owner_ops["stats"]["paid_wei"], open=end["open"], idle=end["idle"], loose=end["loose"],
        vault_balance_wei=end["balance"], winding_down=cast("call", vault, "windingDown()(bool)") == "true",
        total_shares=num(call(vault, "totalShares()(uint256)")), protected=protected())
    keeper_saved = json.loads(Path(rc.KEEPER_STATE).read_text())
    report["keeper"] = dict(stats=keeper_saved["stats"], reverted=sum(1 for e in keeper_saved["counted"] if not e["status"]))
    report["senders"] = {
        "deposit, requestRedeem, claim": "holder, own gas",
        "unlist, liquidate, sync during exit (keeper.py --max-loss-wei)": "holder in steps 2-3; owner in step 4; own gas, pay clipped to zero",
        "checkpoint": "normal keeper; paid from the request charges (processingPool)",
        "restock, list, routine sync": "normal keeper; paid from free vault ETH within the routine budget",
        "startWindDown": "owner, own gas"}
    (ROOT / "sim/out/rehearsal-current.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "values"}, indent=1, default=str))


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "keeper"))
    main()
