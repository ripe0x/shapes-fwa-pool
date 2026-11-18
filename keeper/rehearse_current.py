#!/usr/bin/env python3
"""Launch step D: the canary lifecycle on a local fork of the CURRENT mainnet block, through the
production deploy script and the production keeper, with real signed transactions and real gas
fields. Nothing on the fork is altered except funding fresh actors and moving time forward to
FWA's purchase blackouts (checkpoints only run there). No oracle, basefee or protocol state is
changed; FWA's live queue, fees and gas market are whatever the block holds.

  anvil --fork-url https://mainnet.gateway.tenderly.co --port 8547
  python3 keeper/rehearse_current.py        (writes sim/out/rehearsal-current.json)

Local only; never a public network. Owner is a fresh address impersonated as its test signer.
"""
import json
import os
import subprocess
import sys

import rehearse_canary as rc
from rehearse_canary import FWA, ROOT, call, cast, ids, impersonate, num, send, sh, state, warp_to

OWNER = "0x" + sh("cast", "keccak", "pack-vault-rehearsal-owner")[-40:]
VALUES_FILE = ROOT / "deploy/rehearse-current.json"
SELF = ["--max-loss-wei", str(10**16)]  # whoever runs unpaid exit work accepts its gas


def drain_queue():
    """FWA's queue holds live requests whose VRF words never arrive on a fork; FWA's own
    permissionless processor expires them after their deadline (up to 7,200 blocks)."""
    if num(call(FWA, "unsettledAcquisitionCount()(uint256)")):
        for _ in range(8):
            cast("rpc", "anvil_mine", hex(1000))
        send(rc.KICKER, FWA, "processAcquisitions(uint256)", 50)
    if num(call(FWA, "unsettledAcquisitionCount()(uint256)")):
        sys.exit("FWA queue did not drain")


def main():
    if num(cast("chain-id")) != 1:
        sys.exit("expects a local mainnet fork")
    head = num(cast("block-number"))
    sh("forge", "build", "--force")
    actors = (rc.DEPLOYER, rc.HOLDER, rc.KEEPER, rc.KICKER, OWNER)
    for a in actors:
        if cast("code", a) != "0x" or num(cast("nonce", a)) != 0:
            sys.exit(f"actor {a} is not a clean address on this chain")
        impersonate(a)
    values = dict(rc.VALUES, owner=OWNER)
    VALUES_FILE.write_text(json.dumps(values, indent=1))
    try:
        r = subprocess.run(["forge", "script", "script/Deploy.s.sol", "--rpc-url", rc.RPC, "--broadcast", "--unlocked",
                            "--sender", rc.DEPLOYER], capture_output=True, text=True, cwd=ROOT,
                           env={**os.environ, "DEPLOY_VALUES": "deploy/rehearse-current.json"})
    finally:
        VALUES_FILE.unlink()
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    run = json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
    rc.VAULT = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault")
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
