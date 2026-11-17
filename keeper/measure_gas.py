#!/usr/bin/env python3
"""Billed gas per keeper operation and execution path, from real receipts on a local mainnet fork
(the canary values, the production deploy script, the real FWA, Shapes, ShapePacks and oracle).
Feeds the vault's quoted-gas schedule (D56). Start the fork as for keeper/rehearse_canary.py:
  anvil --fork-url https://mainnet.gateway.tenderly.co --fork-block-number 26418539 \
    --port 8547 --base-fee 150000000
Then: python3 keeper/measure_gas.py   (writes sim/out/gas-quotes.json)
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import rehearse_canary as R  # noqa: E402

OUT = R.ROOT / "sim/out/gas-quotes.json"
rows = []


def tx(label, sig, *args, frm=None, value=None, **meta):
    """Send from the keeper (or `frm`) and record the receipt's billed gas."""
    frm = frm or R.KEEPER
    extra = ["--value", str(value)] if value is not None else []
    r = subprocess.run(["cast", "send", R.VAULT, sig, *map(str, args), *extra, "--from", frm, "--unlocked",
                        "--rpc-url", R.RPC, "--json", "--gas-limit", "16000000"], capture_output=True, text=True)
    rec = json.loads(r.stdout) if r.returncode == 0 else {}
    if rec.get("status") != "0x1":
        sys.exit(f"{label}: {sig} failed\n{r.stdout}{r.stderr}")
    gas = int(rec["gasUsed"], 16)
    rows.append(dict(label=label, sig=sig, gas=gas, **meta))
    print(f"{label:34} {gas:>10,}  {meta}")
    return gas


def open_n():
    return len(R.ids())


def drain_queue():
    if R.num(R.call(R.FWA, "unsettledAcquisitionCount()(uint256)")):
        for _ in range(8):
            R.cast("rpc", "anvil_mine", hex(1000))
        R.send(R.KICKER, R.FWA, "processAcquisitions(uint256)", 50)


def main():
    if R.num(R.cast("chain-id")) != 1:
        sys.exit("expects a local mainnet fork")
    R.sh("forge", "build")
    for a in (R.DEPLOYER, R.HOLDER, R.HOLDER2, R.KEEPER, R.KICKER):
        if R.cast("code", a) != "0x" or R.num(R.cast("nonce", a)) != 0:
            sys.exit(f"actor {a} is not a clean address on this chain")
        R.impersonate(a)
    r = subprocess.run(["forge", "script", "script/Deploy.s.sol", "--rpc-url", R.RPC, "--broadcast", "--unlocked",
                        "--sender", R.DEPLOYER], capture_output=True, text=True, cwd=R.ROOT,
                       env={**__import__("os").environ, "DEPLOY_VALUES": "deploy/canary.example.json"})
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    run = json.loads((R.ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
    R.VAULT = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault")
    drain_queue()

    ck = R.num(R.call(R.VAULT, "requestCharge()(uint256)"))
    R.send(R.HOLDER, R.VAULT, "deposit()", value=ck + R.VALUES["tvlCapWei"] - R.VALUES["seedWei"])
    R.warp_to(42360)
    tx("checkpoint, 0 positions, 1 deposit", "checkpoint(uint256)", 0, positions=0)
    R.warp_to(60)
    tx("restock 1 (1 mint, no loose)", "restock(uint256,uint256,uint256)", 1, 3, 0, packs=1, mints=1)
    tx("restock 1 (0 mints, from loose)", "restock(uint256,uint256,uint256)", 1, 3, 0, packs=1, mints=0)
    tx("restock 2 (1 mint, 4 loose)", "restock(uint256,uint256,uint256)", 2, 3, 0, packs=2, mints=1)
    tx("restock 10 (3 mints)", "restock(uint256,uint256,uint256)", 10, 3, 0, packs=10, mints=3)
    tx("list 1", "list(uint256,uint256)", 1, 0, units=1)
    tx("list 2", "list(uint256,uint256)", 2, 0, units=2)
    tx("list 10", "list(uint256,uint256)", 10, 0, units=10)
    tx("restock 10 (3 mints)", "restock(uint256,uint256,uint256)", 10, 3, 0, packs=10, mints=3)
    tx("list 10", "list(uint256,uint256)", 10, 0, units=10)
    n = open_n()
    # A tiny redemption request is a holder flow: it makes the checkpoint payable.
    R.send(R.HOLDER, R.VAULT, "requestRedeem(uint256)", 10**15, value=10**16)  # excess charge refunded
    R.warp_to(42360)
    tx(f"checkpoint, {n} positions, 1 redemption", "checkpoint(uint256)", 0, positions=n)

    # Kicks: the oracle owner lowers the ask, anyone kicks in the blackout, the keeper syncs.
    oracle = R.call(R.FWA, "floorOracle()(address)")
    owner = R.call(oracle, "owner()(address)")
    R.impersonate(owner)
    R.send(owner, oracle, "setFloor(address,uint256)", R.PACKS, 3 * 10**16)
    listed = R.ids()
    R.warp_to(42360)
    R.impersonate(R.KICKER)
    for i in listed[:6]:
        R.send(R.KICKER, R.FWA, "kickListing(uint256)", i)
    R.warp_to(60)
    tx("sync 1 (kicked)", "sync(uint256[],uint256)", f"[{listed[0]}]", 0, units=1)
    tx("sync 2 (kicked)", "sync(uint256[],uint256)", f"[{listed[1]},{listed[2]}]", 0, units=2)
    tx("sync 3 (kicked)", "sync(uint256[],uint256)", "[" + ",".join(map(str, listed[3:6])) + "]", 0, units=3)

    # Redemption shortfall: liquidate idle packs, then unlist positions.
    shares = R.num(R.call(R.VAULT, "shareBalance(address)(uint256)", R.HOLDER))
    R.send(R.HOLDER, R.VAULT, "requestRedeem(uint256)", shares * 9 // 10, value=10**17)
    tx("liquidate 1 pack", "liquidate(uint256,uint256)", 1, 0, units=1)
    tx("liquidate 2 packs", "liquidate(uint256,uint256)", 2, 0, units=2)
    tx("liquidate 3 packs", "liquidate(uint256,uint256)", 3, 0, units=3)
    drain_queue()
    listed = R.ids()
    tx("unlist 1", "unlist(uint256[],uint256)", f"[{listed[0]}]", 0, units=1)
    tx("unlist 2", "unlist(uint256[],uint256)", f"[{listed[1]},{listed[2]}]", 0, units=2)
    tx("unlist 8", "unlist(uint256[],uint256)", "[" + ",".join(map(str, listed[3:11])) + "]", 0, units=8)
    tx("liquidate 10 packs", "liquidate(uint256,uint256)", 10, 0, units=10)
    loose = R.num(R.call(R.VAULT, "looseShapeCount()(uint256)"))
    if loose:
        tx(f"liquidate loose ({loose} Shapes)", "liquidate(uint256,uint256)", loose, 0, units=loose, loose=True)
    n = open_n()
    R.warp_to(42360)
    tx(f"checkpoint, {n} positions, redemption fill", "checkpoint(uint256)", 0, positions=n)
    OUT.write_text(json.dumps(dict(fork_block=26418539, basefee_wei=150_000_000, rows=rows), indent=1))
    print(f"wrote {OUT.relative_to(R.ROOT)}")


if __name__ == "__main__":
    main()
