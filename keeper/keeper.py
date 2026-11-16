#!/usr/bin/env python3
"""Reference keeper for PackVault. Each pass reads live chain state, asks keeper/policy.py what
is worth doing, and prints or sends those calls. Stateless: an interrupted keeper resumes from
chain state alone.

Usage:
  keeper/keeper.py <vault>                                   # print the plan
  keeper/keeper.py <vault> --send --account <keystore-name>  # sign through a cast keystore
  keeper/keeper.py <vault> --send --from <addr> --rpc http://127.0.0.1:8545   # local rehearsal
  add --loop 300 to repeat every 300 s; --slowdown-volume N to stop building new packs while
  trailing 7-day acquisitions per day are below N (relisting continues).

This script never sees a key. Each call is estimated, padded 25% (keeper pay depends on
gasleft()), sent, and its receipt status checked: `cast send` exits 0 on a revert. A failed call
is reported and the pass continues with the next one.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import policy  # noqa: E402

RPC = "https://mainnet.gateway.tenderly.co"
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
SHAPES = "0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0"
PARAMS_T = "(uint16,uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint96,uint128,uint128,uint128,uint128,uint128)"
LISTING_T = "(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)"


def cast(*args):
    return subprocess.check_output(["cast", *map(str, args), "--rpc-url", RPC], text=True).strip()


def call(to, sig, *args, block=None):
    extra = ["--block", str(block)] if block else []
    return cast("call", to, sig, *args, *extra)


def num(v):
    v = v.split(" ")[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def lines(out):
    return [x for x in out.splitlines() if x]


def ids_of(out):
    out = out.strip("[]")
    return [num(x.strip()) for x in out.split(",") if x.strip()]


def read_state(vault, slowdown):
    p = [num(x) for x in call(vault, f"getParams()({PARAMS_T})").strip("()").split(", ")]
    (min_edge, _buf, dist_bps, premium, share, _alloc, _slip, _mask, ceiling, tip, max_pos, _res, _tvl,
     _opcap, _clip, ref_price) = p
    k, backing, _ok = lines(call(vault, "edge(uint256)(uint256,uint256,bool)", 3))
    now = num(cast("block", "latest", "--field", "timestamp"))
    window = num(call(FWA, "settlementWindow()(uint256)"))
    top = num(call(FWA, "topListingId()(uint256)"))
    top_since = num(call(FWA, "topListingSince()(uint64)"))
    listings = []
    for i in ids_of(call(vault, "openListings()(uint256[])")):
        f = call(FWA, f"listings(uint256)({LISTING_T})", i).strip("()").split(", ")
        status, allocated_at = num(f[10]), num(f[9])
        pend = num(call(FWA, "pendingFees(uint256)(uint256)", i)) if status == policy.ACTIVE else 0
        owed = status in (policy.SETTLED, policy.WITHDRAWN) and \
            call(FWA, "stuckNFTRecipient(uint256)(address)", i).lower() == vault.lower()
        listings.append(policy.Listing(i, status, allocated_at, pend, owed,
                                       crown_locked=(i == top and now < top_since + 12 * 3600)))
    balance = num(cast("balance", vault))
    pending = num(call(vault, "pendingDepositTotal()(uint256)"))
    reserves = pending + num(call(vault, "redemptionReserve()(uint256)")) + \
        num(call(vault, "distributionReserve()(uint256)"))
    locked = num(call(vault, "lockedShares()(uint256)"))
    owed = 0
    if locked:
        last_nav, supply = num(call(vault, "lastNav()(uint256)")), num(call(vault, "totalShares()(uint256)"))
        owed = -(-locked * last_nav // supply)
    interval = now // (12 * 3600)
    # Trailing 7-day volume from FWA's monotonic request sequence.
    head = num(cast("block-number"))
    seq_now = num(call(FWA, "lastIssuedSequence()(uint64)"))
    seq_then = num(call(FWA, "lastIssuedSequence()(uint64)", block=max(head - 7 * 7200, 1)))
    token_ok = ref_price > 0 and call(vault, "conversionDisabled()(bool)") == "false"
    token = call(FWA, "token()(address)")
    held = num(call(token, "balanceOf(address)(uint256)", vault))
    return policy.State(
        now=now, gas_price=num(cast("gas-price")), base_fee=num(cast("base-fee")), gas_ceiling=ceiling,
        max_tip=tip, premium_bps=premium, share_bps=share, k=num(k), backing=num(backing), min_edge_bps=min_edge,
        mint_fee=num(call(SHAPES, "mintFee()(uint256)")), settlement_window=window,
        blackout=call(FWA, "isPurchaseBlackout()(bool)") == "true",
        queue_drained=num(call(FWA, "unsettledAcquisitionCount()(uint256)")) == 0,
        checkpoint_done_this_interval=num(call(vault, "lastCheckpointInterval()(uint256)")) == interval,
        listings=listings, idle_packs=len(ids_of(call(vault, "idlePacks()(uint256[])"))),
        loose_shapes=num(call(vault, "looseShapeCount()(uint256)")),
        free=max(0, balance - reserves), idle_eth=num(call(vault, "idleEth()(uint256)")), owed_estimate=owed,
        pending_deposits=pending, locked_shares=locked,
        fee_credit=num(call(FWA, "feeCredit(address)(uint256)", vault)),
        open_positions=len(listings), max_positions=max_pos,
        winding_down=call(vault, "windingDown()(bool)") == "true",
        listing_paused=call(vault, "listingPaused()(bool)") == "true", distribution_bps=dist_bps,
        token_held=held, token_held_eth=held * ref_price // 10**18, token_ref_ok=token_ok,
        token_sale_open=num(call(vault, "conversionInterval()(uint256)")) != interval,
        recent_volume=(seq_now - seq_then) / 7, slowdown_volume=slowdown,
    ), ref_price, _slip


def to_cast(step, ref_price, slip_bps):
    fn, *args = step
    if fn in ("sync", "harvest", "unlist", "harvestTokens"):
        return [f"{fn}(uint256[])", "[" + ",".join(map(str, args[0])) + "]"]
    if fn in ("list", "liquidate"):
        return [f"{fn}(uint256)", args[0]]
    if fn == "restock":
        return ["restock(uint256,uint256)", args[0], args[1]]
    if fn == "convert":
        amount = args[0]
        return ["convert(uint256,uint256)", amount, amount * ref_price // 10**18 * (10_000 - slip_bps) // 10_000]
    return [f"{fn}()"]


def run_pass(a):
    state, ref_price, slip = read_state(a.vault, a.slowdown_volume)
    steps = policy.plan(state)
    print(f"gas {state.gas_price / 1e9:.3f} gwei, {len(state.listings)} open, {state.idle_packs} idle packs, "
          f"idle {state.idle_eth / 1e18:.4f} ETH, cycle net {policy.cycle_net(state) / 1e15:.3f} mETH, "
          f"7d volume {state.recent_volume:.0f}/day")
    if not steps:
        print("nothing to do")
    failed = 0
    for step in steps:
        args = to_cast(step, ref_price, slip)
        if not a.send:
            print("cast send", a.vault, *map(str, args))
            continue
        auth = ["--account", a.account] if a.account else ["--unlocked", "--from", a.sender]
        sender = a.sender or cast("wallet", "address", "--account", a.account)
        try:
            est = int(cast("estimate", a.vault, *args, "--from", sender))
            receipt = json.loads(cast("send", a.vault, *args, *auth, "--gas-limit", est * 5 // 4, "--json"))
            status = int(str(receipt.get("status", "0x0")), 16)
            print("sent", step[0], "status", status, "gas", int(receipt["gasUsed"], 16))
            if status != 1:
                failed += 1
                print(f"  reverted: {receipt['transactionHash']}")
        except subprocess.CalledProcessError as e:
            failed += 1
            print(f"  {step[0]} not sent: {e.output.strip()[:200] if e.output else e}")
    return failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vault")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--account")
    ap.add_argument("--from", dest="sender", help="sender for an unlocked local node (rehearsal)")
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--loop", type=int, default=0, help="seconds between passes; 0 runs once")
    ap.add_argument("--slowdown-volume", type=float, default=0.0)
    a = ap.parse_args()
    globals()["RPC"] = a.rpc
    if a.send and not (a.account or a.sender):
        sys.exit("--send needs --account (a cast keystore name) or --from on an unlocked local node")
    while True:
        try:
            failed = run_pass(a)
        except subprocess.CalledProcessError as e:  # RPC hiccup: read again next pass
            failed = 1
            print(f"read failed: {e}")
        if not a.loop:
            sys.exit(1 if failed else 0)
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
