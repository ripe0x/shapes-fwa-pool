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


SALE_TOLERANCE_BPS = 50  # minOut sits 0.5% under the simulated fill: room for block-to-block drift


def read_tokens(vault, active_ids, interval, sender, ref_price, slip_bps, clip, disabled):
    """Token entitlements and a sale estimate from the deployed rewards and token contracts.
    The estimate simulates the exact convert call (claims, clipMax, pool fee, price impact,
    hook, transfer rules) from the keeper's address; the reference price only sets the floor."""
    rewards = call(FWA, "rewards()(address)")
    token = call(FWA, "token()(address)")
    pending = sum(num(call(rewards, "pendingDepositorTokens(uint256)(uint256)", i)) for i in active_ids)
    credit = num(call(rewards, "tokenCredit(address)(uint256)", vault))
    held = num(call(token, "balanceOf(address)(uint256)", vault))
    out = dict(token_pending=pending, token_credit=credit, token_held=held)
    total = pending + credit + held
    if not total:
        return out
    amount = min(total, clip)
    out["token_sale_amount"] = amount
    if disabled:
        out["token_wait"] = "conversion disabled by the guardian"
    elif ref_price == 0:
        out["token_wait"] = "no reference price set (admin sets one through the parameter delay)"
    elif num(call(vault, "conversionInterval()(uint256)")) == interval:
        out["token_wait"] = "already sold once this 12 h interval"
    else:
        floor = amount * ref_price // 10**18 * (10_000 - slip_bps) // 10_000
        args = ["convert(uint256[],uint256,uint256)(uint256)", "[" + ",".join(map(str, active_ids)) + "]",
                amount, floor]
        try:
            eth = num(cast("call", vault, *args, "--from", sender))
            gas = int(cast("estimate", vault, "convert(uint256[],uint256,uint256)", *args[1:], "--from", sender).split()[0])
            out.update(token_sale_eth=eth, token_sale_gas=gas,
                       token_sale_min_out=max(floor, eth * (10_000 - SALE_TOLERANCE_BPS) // 10_000))
        except subprocess.CalledProcessError as e:
            msg = (e.output or "").strip()
            out["token_wait"] = ("pool price below the reference floor" if "Slippage" in msg or "0x7dd37f70" in msg
                                 else f"sale simulation reverted: {msg[:120]}")
    return out


def read_state(vault, slowdown, sender="0x000000000000000000000000000000000000dEaD", subsidize=False):
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
        num(call(vault, "distributionReserve()(uint256)")) + num(call(vault, "claimableTotal()(uint256)"))
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
    tokens = read_tokens(vault, [l.id for l in listings if l.status == policy.ACTIVE], interval, sender,
                         ref_price, _slip, _clip, call(vault, "conversionDisabled()(bool)") == "true")
    return policy.State(
        # The keeper bids basefee + maxTip (run_pass), so that is its price.
        now=now, gas_price=num(cast("base-fee")) + tip, base_fee=num(cast("base-fee")), gas_ceiling=ceiling,
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
        recent_volume=(seq_now - seq_then) / 7, slowdown_volume=slowdown, subsidize_tokens=subsidize,
        **tokens,
    )


def to_cast(step):
    fn, *args = step
    if fn in ("sync", "harvest", "unlist", "harvestTokens"):
        return [f"{fn}(uint256[])", "[" + ",".join(map(str, args[0])) + "]"]
    if fn == "activate":
        return ["activate(uint256[],uint256)", "[" + ",".join(map(str, args[0])) + "]", args[1]]
    if fn in ("list", "liquidate"):
        return [f"{fn}(uint256)", args[0]]
    if fn == "restock":
        return ["restock(uint256,uint256)", args[0], args[1]]
    if fn == "convert":
        return ["convert(uint256[],uint256,uint256)", "[" + ",".join(map(str, args[0])) + "]", args[1], args[2]]
    return [f"{fn}()"]


def run_pass(a):
    """Send one call at a time and re-read the chain before choosing the next, so each decision
    sees the effect of the last (a sync frees a pack to list, a harvest frees ETH, a claim feeds
    a sale). A call that fails is not retried in the same pass; the next pass reads afresh."""
    sender = a.sender or (cast("wallet", "address", "--account", a.account) if a.account else
                          "0x000000000000000000000000000000000000dEaD")
    failed, skip, sent = 0, set(), 0
    for _ in range(a.max_steps):
        state = read_state(a.vault, a.slowdown_volume, sender, a.subsidize_tokens)
        steps = [st for st in policy.plan(state) if st[0] not in skip]
        if sent == 0:
            print(f"gas {state.gas_price / 1e9:.3f} gwei, {len(state.listings)} open, {state.idle_packs} idle packs, "
                  f"idle {state.idle_eth / 1e18:.4f} ETH, cycle net {policy.cycle_net(state) / 1e15:.3f} mETH, "
                  f"7d volume {state.recent_volume:.0f}/day")
            for n in state.notes:
                print("note:", n)
        if not steps:
            print("nothing to do" if sent == 0 else f"done: {sent} sent, {failed} failed")
            return failed
        if not a.send:
            for st in steps:
                print("cast send", a.vault, *map(str, to_cast(st)))
            return 0
        step, args = steps[0], to_cast(steps[0])
        auth = ["--account", a.account] if a.account else ["--unlocked", "--from", a.sender]
        # Bid what the vault reimburses: basefee plus at most maxTip. A higher tip is the
        # keeper's own cost (the vault caps the price at basefee + maxTip).
        fees = ["--priority-gas-price", str(state.max_tip), "--gas-price", str(2 * state.base_fee + state.max_tip)]
        try:
            est = int(cast("estimate", a.vault, *args, "--from", sender).split()[0])
            receipt = json.loads(cast("send", a.vault, *args, *auth, *fees, "--gas-limit", est * 5 // 4, "--json"))
            status = int(str(receipt.get("status", "0x0")), 16)
            gas_used = int(receipt["gasUsed"], 16)
            price = int(receipt.get("effectiveGasPrice", "0x0"), 16)
            print(f"sent {step[0]} status {status} gas {gas_used} cost {gas_used * price / 1e18:.8f} ETH")
            sent += 1
            if status != 1:
                failed += 1
                skip.add(step[0])
                print(f"  reverted: {receipt['transactionHash']}")
        except subprocess.CalledProcessError as e:
            failed += 1
            skip.add(step[0])
            print(f"  {step[0]} not sent: {(e.output or str(e)).strip()[:200]}")
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
    ap.add_argument("--max-steps", type=int, default=40, help="calls per pass, each after a fresh read")
    ap.add_argument("--subsidize-tokens", action="store_true",
                    help="sell tokens even when the vault will not reimburse the gas (operator pays)")
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
