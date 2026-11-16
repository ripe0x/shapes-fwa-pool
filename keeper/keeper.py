#!/usr/bin/env python3
"""Reference keeper for PackVault: one pass that decides which maintenance calls are worth
making now, using live reads only. Prints the calls by default; `--send` broadcasts them with
`cast send --account <name>` (a Foundry keystore account; this script never sees a key).

Usage:
  keeper/keeper.py <vault> [--send --account <keystore-name>] [--max-gwei 1.5]

Order of a pass: resolve positions FWA has moved on, harvest fees, checkpoint when the window
is open and there is work, then build and list inventory when the live edge gate passes.
A call is skipped when its gas at the current price exceeds the value it realizes.
"""
import argparse
import json
import subprocess
import sys

RPC = "https://mainnet.gateway.tenderly.co"  # --rpc overrides (for a local fork rehearsal)
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
ALLOCATED, SETTLED, WITHDRAWN = 2, 4, 3
GAS = {"sync": 60_000, "harvest": 80_000, "checkpoint_base": 300_000, "checkpoint_per_position": 25_000,
       "list": 730_000, "restock_per_pack": 1_010_000}


def call(to, sig, *args):
    out = subprocess.check_output(["cast", "call", to, sig, *map(str, args), "--rpc-url", RPC], text=True)
    return [line.split(" ")[0] for line in out.strip().splitlines()]


def ids_of(to, sig):
    out = subprocess.check_output(["cast", "call", to, sig, "--rpc-url", RPC], text=True).strip()
    return [int(x.strip().split(" ")[0]) for x in out.strip("[]").split(",") if x.strip()]


def num(v):
    return int(v, 0) if v.startswith("0x") else int(v)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vault")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--account")
    ap.add_argument("--max-gwei", type=float, default=1.5)
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--from", dest="sender", help="sender for an unlocked local node (rehearsal)")
    a = ap.parse_args()
    globals()["RPC"] = a.rpc
    if a.send and not (a.account or a.sender):
        sys.exit("--send needs --account (a cast keystore name) or --from on an unlocked local node")

    gas_price = num(subprocess.check_output(["cast", "gas-price", "--rpc-url", RPC], text=True).strip())
    if gas_price > a.max_gwei * 1e9:
        print(f"gas {gas_price / 1e9:.2f} gwei above {a.max_gwei}: nothing this pass")
        return
    cost = lambda g: g * gas_price  # noqa: E731
    plan = []

    ids = ids_of(a.vault, "openListings()(uint256[])")
    window = num(call(FWA, "settlementWindow()(uint256)")[0])
    now = num(subprocess.check_output(["cast", "block", "latest", "--field", "timestamp", "--rpc-url", RPC], text=True))
    resolvable = []
    for i in ids:
        f = call(FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", i)
        status, allocated_at = int(f[10]), int(f[9])
        if status in (SETTLED, WITHDRAWN) or (status == ALLOCATED and now >= allocated_at + window):
            resolvable.append(i)
    if resolvable:
        # Each resolution frees at least a pack (0.03 ETH) or backing: always worth its gas.
        plan.append(("sync(uint256[])", "[" + ",".join(map(str, resolvable)) + "]"))

    credit = num(call(FWA, "feeCredit(address)(uint256)", a.vault)[0])
    if credit > cost(GAS["harvest"]):
        plan.append(("harvest()",))

    blackout = call(FWA, "isPurchaseBlackout()(bool)")[0] == "true"
    drained = num(call(FWA, "unsettledAcquisitionCount()(uint256)")[0]) == 0
    pending = num(call(a.vault, "pendingDepositTotal()(uint256)")[0])
    locked = num(call(a.vault, "lockedShares()(uint256)")[0])
    if blackout and drained and (pending or locked):
        plan.append(("checkpoint()",))

    _, backing, ok = call(a.vault, "edge(uint256)(uint256,uint256,bool)", 3)
    idle_eth = num(call(a.vault, "idleEth()(uint256)")[0])
    idle_packs = len(ids_of(a.vault, "idlePacks()(uint256[])"))
    if ok == "true" and not blackout:
        backing = num(backing)
        if idle_packs:
            n = min(idle_packs, idle_eth // backing, 5)  # listNFT is about 730k gas each
            if n:
                plan.append(("list(uint256)", n))
        elif idle_eth > backing + 0.101e18:
            # One 0.1 ETH mint and split makes three packs: about 3.3M gas per batch of three.
            n = min(int((idle_eth - 0.101e18) // (backing + 0.03e18)), 3)
            if n:
                plan.append(("restock(uint256,uint256)", n, 3))

    for step in plan:
        cmd = ["cast", "send", a.vault, *map(str, step), "--rpc-url", RPC]
        if a.send:
            auth = ["--account", a.account] if a.account else ["--unlocked", "--from", a.sender]
            # Keeper pay depends on gasleft(), so a bare estimate lands just short: pad it 25%.
            sender = a.sender or subprocess.check_output(
                ["cast", "wallet", "address", "--account", a.account], text=True).strip()
            est = int(subprocess.check_output(
                ["cast", "estimate", a.vault, *map(str, step), "--from", sender, "--rpc-url", RPC], text=True))
            # cast send exits 0 on a reverted transaction: read the receipt status.
            receipt = json.loads(subprocess.check_output(
                cmd + auth + ["--gas-limit", str(est * 5 // 4), "--json"], text=True))
            status = int(str(receipt.get("status", "0x0")), 16)
            print("sent", " ".join(map(str, step)), "status", status, "gas", int(receipt["gasUsed"], 16))
            if status != 1:
                sys.exit(f"transaction failed: {receipt['transactionHash']}")
        else:
            print(" ".join(cmd))
    if not plan:
        print("nothing to do")


if __name__ == "__main__":
    main()
