#!/usr/bin/env python3
"""Phase 0.1: re-read the plan's Part 1 live values from mainnet at one pinned block.

Uses Foundry `cast`. Internal FWA settings without getters (surcharge, min backing,
withdraw-only, protocol fees to buyback) come from the latest ConfigSet event per key;
public settings are read by eth_call and cross-checked against their events.
Exit 1 when a step 0.1 stop condition holds.

Usage: sim/snapshot.py [block]    (MAINNET_RPC_URL overrides the Tenderly default)
"""
import json
import os
import subprocess
import sys

RPC = os.environ.get("MAINNET_RPC_URL", "https://mainnet.gateway.tenderly.co")
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
REWARDS = "0xA54b44C7a894AA19C49734A753D01f9B8C5f6516"
SHAPES = "0x6fe9193276bf7abcbee44ab7afd717d637d6faf0"
PACKS = "0xf21514b090da7df4390803497d6ae673801e5ca7"
FWA_DEPLOY_BLOCK = 25_944_000  # first ConfigSet in the plan is 25,944,609
LOG_CHUNK = 100_000
BPS = 10_000
P = 3 * 10**16  # pack size under study, 0.03 ETH

# FWAV2ConfigKeys
KEYS = {
    13: "surchargeBps", 15: "topListingShareBps", 16: "topThresholdBps",
    17: "settlementDiscountBps", 18: "ownerAcquisitionFeeBps", 19: "ownerSettlementFeeBps",
    20: "settlementWindow", 21: "finalizeWindow", 22: "minBacking",
    23: "protocolFeeToTokenBps", 26: "maxOracleAge", 27: "minOracleChallengePeriod",
    28: "oracleCeilingPremiumBps", 29: "tokenSettlementDiscountBps", 40: "retainedToProtocol",
    41: "acquisitionsEnabled", 42: "withdrawOnly", 43: "whitelistEnabled",
}
PUBLIC_GETTERS = [
    "topListingShareBps", "topThresholdBps", "settlementDiscountBps", "ownerAcquisitionFeeBps",
    "ownerSettlementFeeBps", "settlementWindow", "finalizeWindow", "maxOracleAge",
    "minOracleChallengePeriod", "oracleCeilingPremiumBps", "tokenSettlementDiscountBps",
]
PACK_SELECTORS = [
    "createPack(uint256[],uint32[])", "createPackTo(uint256[],uint32[],address)",
    "redeem(uint256)", "redeemTo(uint256,address)", "open(uint256)", "valueOf(uint256)",
    "contentsOf(uint256)", "mergePacks(uint256,uint256[])",
]


def cast(*args, rpc=True):
    out = subprocess.run(["cast", *args, *(["--rpc-url", RPC] if rpc else [])],
                         capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"cast {' '.join(args)}: {out.stderr.strip()}")
    return out.stdout.strip()


def call(block, to, sig, *args):
    raw = cast("call", to, sig, *map(str, args), "--block", str(block))
    return [line.split(" ")[0] for line in raw.splitlines()]


def num(v):
    return int(v, 0) if v.startswith("0x") else int(v)


def config_events(block):
    latest = {}
    for start in range(FWA_DEPLOY_BLOCK, block + 1, LOG_CHUNK):
        end = min(start + LOG_CHUNK - 1, block)
        logs = json.loads(cast("logs", "--json", "--address", FWA, "--from-block", str(start),
                               "--to-block", str(end), "ConfigSet(uint256 indexed,uint256)"))
        for log in logs:
            key = int(log["topics"][1], 16)
            latest[key] = (int(log["data"], 16), int(log["blockNumber"], 16))
    return latest


def eth(wei):
    return f"{wei / 1e18:.6f}"


def main():
    block = int(sys.argv[1]) if len(sys.argv) > 1 else int(cast("block-number"))
    ts = num(cast("block", str(block), "--field", "timestamp"))
    print(f"block {block}  timestamp {ts}  rpc {RPC}\n")
    stops = []

    print("== FWA settings (latest ConfigSet; getter cross-check)")
    events = config_events(block)
    cfg = {name: events[k][0] for k, name in KEYS.items() if k in events}
    for k, name in KEYS.items():
        if k not in events:
            print(f"  {name:28} never set")
            continue
        value, at = events[k]
        note = ""
        if name in PUBLIC_GETTERS:
            live = num(call(block, FWA, f"{name}()(uint256)")[0])
            note = "getter ok" if live == value else f"GETTER MISMATCH {live}"
            cfg[name] = live
        print(f"  {name:28} {value:>22}  at {at}  {note}")
    # Constructor defaults for keys never emitted (source defaults).
    cfg.setdefault("surchargeBps", 500)
    cfg.setdefault("withdrawOnly", 0)
    cfg.setdefault("protocolFeeToTokenBps", BPS)

    print("\n== Pool state")
    acq_fee = num(call(block, FWA, "acquisitionFee()(uint256)")[0])
    total_w = num(call(block, FWA, "totalWeight()(uint256)")[0])
    wbt = num(call(block, FWA, "weightedBackingTotal()(uint256)")[0])
    active = num(call(block, FWA, "activeListingCount()(uint256)")[0])
    unsettled = num(call(block, FWA, "unsettledAcquisitionCount()(uint256)")[0])
    blackout = call(block, FWA, "isPurchaseBlackout()(bool)")[0]
    harmonic = wbt // total_w if total_w else 0
    derived_sur = (acq_fee * BPS // harmonic - BPS) if harmonic else None
    print(f"  acquisitionFee {eth(acq_fee)}  harmonic backing {eth(harmonic)}  active {active}")
    print(f"  surcharge derived {derived_sur} bps vs event {cfg['surchargeBps']}")
    print(f"  unsettledAcquisitionCount {unsettled}  isPurchaseBlackout {blackout}")

    top_id = num(call(block, FWA, "topListingId()(uint256)")[0])
    top_since = num(call(block, FWA, "topListingSince()(uint64)")[0])
    top = call(block, FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,"
                           "uint256,uint256,uint256,uint64,uint8)", top_id) if top_id else None
    if top:
        print(f"  top listing {top_id}  backing {eth(num(top[5]))}  since {top_since}"
              f"  collection {top[0]}  status {top[10]}")

    print("\n== Shape packs on main pool")
    can_deposit = call(block, FWA, "canDeposit(address)(bool)", PACKS)[0] == "true"
    exempt = call(block, FWA, "oracleExemptCollections(address)(bool)", PACKS)[0] == "true"
    oracle = call(block, FWA, "floorOracle()(address)")[0]
    bid, ask, observed, period = map(num, call(
        block, oracle, "getFloorRange(address)(uint256,uint256,uint48,uint48)", PACKS))
    age = ts - observed if observed else None
    print(f"  canDeposit {can_deposit}  oracleExempt {exempt}")
    print(f"  floor bid {eth(bid)}  ask {eth(ask)}  observedAt {observed}  age {age}s  periodUsed {period}")
    floor_ok = (bid != 0 and bid < ask and 0 < observed <= ts and age <= cfg["maxOracleAge"]
                and period >= cfg["minOracleChallengePeriod"])
    print(f"  passes _validatedFloorCap: {floor_ok}"
          + ("" if floor_ok else "  (bid/ask/age/period check failed)"))
    if age is not None:
        print(f"  quote expires in {(cfg['maxOracleAge'] - age) / 3600:.1f} h")
    cap = ask * (BPS + cfg["oracleCeilingPremiumBps"]) // BPS
    print(f"  backing cap {eth(cap)}  minBacking {eth(cfg['minBacking'])}")

    print("\n== Economics (P = 0.03 ETH)")
    k = ((BPS + cfg["surchargeBps"]) * (BPS - cfg["ownerAcquisitionFeeBps"])
         * (BPS - cfg["topListingShareBps"])) / BPS**3
    s = cfg["ownerSettlementFeeBps"] / BPS
    gate = P / (k - s) if k > s else float("inf")
    print(f"  k {k:.6f}  s {s}  listing gate B >= {gate / 1e18:.6f}")
    for b in sorted({int(cfg["minBacking"]), int(P), int(ask), int(cap)}):
        bid_out = b * (k - 1)  # plan Part 1.4 closed form; validated against history in 0.3
        keep_out = b * (k - s) - P
        print(f"  B {eth(b)}  r {b / P:.2f}  bid {bid_out / 1e18:+.5f}  keep {keep_out / 1e18:+.5f}")

    print("\n== Shapes and ShapePacks")
    print(f"  Shapes.mintFee {eth(num(call(block, SHAPES, 'mintFee()(uint256)')[0]))}")
    code = cast("code", PACKS, "--block", str(block)).lower()
    for sig in PACK_SELECTORS:
        sel = cast("sig", sig, rpc=False)[2:].lower()
        print(f"  {sig:45} {sel}  {'present' if sel in code else 'ABSENT'}")

    if not can_deposit:
        stops.append("packs not admitted (canDeposit false)")
    if k < 1:
        stops.append(f"k {k:.4f} < 1")
    if not exempt and cap < gate:
        stops.append(f"cap {eth(cap)} below gate {gate / 1e18:.6f}")
    if not exempt and not floor_ok:
        stops.append("floor quote fails _validatedFloorCap: new listings revert")
    print("\nSTOP: " + "; ".join(stops) if stops else "\nNo stop condition.")
    sys.exit(1 if stops else 0)


if __name__ == "__main__":
    main()
