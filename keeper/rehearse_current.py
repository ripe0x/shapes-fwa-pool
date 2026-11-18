#!/usr/bin/env python3
"""Quiet holder lifecycle on the approved batch's pinned fork, through production paths.

The filename is historical. This phase uses block26418539, not an unapproved moving current
block. No oracle or fee parameters change in this phase. Run via rehearsal_batch.py only.
"""
import json
import os
import subprocess
import sys

import rehearse_canary as rc
from rehearse_canary import FWA, ROOT, call, cast, ids, impersonate, num, send, sh, state, warp_to

OWNER = rc.OWNER
VALUES_FILE = ROOT / "deploy/rehearse-current.json"
SELF = ["--max-loss-wei", str(10**16)]  # whoever runs unpaid exit work accepts its gas


def drain_queue():
    rc.expire_queue()


def main():
    rc.B.load_manifest()
    head = num(cast("block-number"))
    for actor in rc.B.ACTORS.values():
        impersonate(actor)
    values = dict(rc.VALUES, owner=OWNER)
    rc.VAULT = rc.B.deploy(values, "quiet")
    rc.TOKEN = call(FWA, "token()(address)")
    vault = rc.VAULT
    print("block", head, "vault", vault, "basefee", num(cast("base-fee")))
    keeper_start = num(cast("balance", rc.KEEPER))
    s0 = state("deployed")

    # 1. Deposit up to the cap; priced at the next blackout.
    ck = num(call(vault, "requestCharge()(uint256)"))
    value = ck + values["tvlCapWei"] - values["seedWei"]
    send(rc.HOLDER, vault, "deposit()", value=value)
    deposited = value
    warp_to(42360)
    drain_queue()
    rc.keeper()
    state("priced")

    # 2. Deploy: the keeper builds and lists while FWA's queue is drained.
    warp_to(60)
    drain_queue()
    rc.keeper()
    built = state("deployed capital")
    staged = sum(1 for i in ids() if num(cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", i).split("\n")[-1]) == 5)

    # 3. Half redeemed: the keeper releases liquidity and prices it.
    shares = num(call(vault, "shareBalance(address)(uint256)", rc.HOLDER))
    charge = rc.redeem_charge(shares // 2)
    b0 = num(cast("balance", vault))
    send(rc.HOLDER, vault, "requestRedeem(uint256)", shares // 2, value=charge)
    deposited += num(cast("balance", vault)) - b0
    # Exit work is unpaid (no essential budget, D64): the withdrawer runs it at its own gas.
    drain_queue()
    rc.keeper(*SELF)
    warp_to(42360)
    drain_queue()
    rc.keeper(*SELF)
    send(rc.HOLDER, vault, "claim()")
    state("partial withdrawal")

    # 4. The rest redeemed, then the owner winds down.
    warp_to(60)
    shares = num(call(vault, "shareBalance(address)(uint256)", rc.HOLDER))
    charge = rc.redeem_charge(shares)
    b0 = num(cast("balance", vault))
    send(rc.HOLDER, vault, "requestRedeem(uint256)", shares, value=charge)
    deposited += num(cast("balance", vault)) - b0
    send(OWNER, vault, "startWindDown()")
    drain_queue()
    rc.keeper(*SELF)
    warp_to(42360)
    drain_queue()
    rc.keeper(*SELF)
    send(rc.HOLDER, vault, "claim()")
    end = state("wound down")

    def logs(sig):
        return json.loads(sh("cast", "logs", "--rpc-url", rc.RPC, "--json", "--address", vault, sig) or "[]")

    pay = sum(int(x["data"], 16) for x in logs("KeeperPaid(address indexed,uint256)"))
    claims = sum(int(x["data"], 16) for x in logs("Claimed(address indexed,uint256)"))
    loose = mints = 0
    for x in logs("Restocked(uint256,uint256)"):
        need = int(x["data"][2:66], 16) * int(x["data"][66:], 16)
        m = -(-(need - loose) // 10) if need > loose else 0
        mints += m
        loose += 10 * m - need
    mint_fee = num(call(rc.VALUES["shapes"], "mintFee()(uint256)"))
    ins = s0["balance"] + deposited
    outs = claims + pay + mints * mint_fee + end["balance"]
    counted = json.load(open(rc.KEEPER_STATE))["counted"]
    report = dict(block=head, positions_listed=built["open"], staged_after_listing=staged, deposited=deposited,
                  claimed=claims, holder_result=claims - deposited, keeper_pay=pay,
                  keeper_net=end["keeper"] - keeper_start, mints=mints, ledger_gap=ins - outs,
                  reverted=sum(1 for e in counted if not e["status"]), sent=len(counted), log=rc.log)
    (ROOT / "sim/out/rehearsal-current.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k != "log"}, indent=1))
    if ins != outs:
        sys.exit(f"ledger does not close: in {ins} out {outs}")
    if staged:
        sys.exit(f"{staged} keeper listings staged")
    print("ledger closes to the wei at the current block")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "keeper"))
    main()
