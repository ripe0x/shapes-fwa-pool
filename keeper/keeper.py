#!/usr/bin/env python3
"""Reference keeper for PackVault. Each pass reads live chain state, asks keeper/policy.py what
is worth doing and prints or sends those calls one at a time, re-reading state after each.
Decisions come from chain state alone; keeper/tx.py tracks the one in-flight transaction in a
state file so restarts, lost responses and stuck transactions resolve at the same nonce.

Usage:
  keeper/keeper.py <vault>                                    # print status and the plan
  keeper/keeper.py <vault> --status                           # status, in-flight tx, keeper P&L
  keeper/keeper.py <vault> --send --account <keystore-name>   # sign through a cast keystore
  keeper/keeper.py <vault> --send --from <addr> --rpc http://127.0.0.1:8545   # local rehearsal
  --loop 300 repeats every 300 s; --health-port 8788 serves GET /health; --max-loss-wei N lets
  liability work above the vault's gas ceiling cost this keeper up to N wei per call (default 0:
  wait); --burn-tokens claims and burns FWA token rewards at the operator's cost.
  Operations and recovery: docs/KEEPER.md.

This script never sees a key: cast signs (keystore password from cast's own prompt or env).
"""
import argparse
import json
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import policy  # noqa: E402
import tx as txm  # noqa: E402

RPC = "https://mainnet.gateway.tenderly.co"
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
SHAPES = "0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0"
PARAMS_T = "(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint96,uint128,uint128,uint128)"
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




def read_tokens(vault, active_ids):
    """Token entitlements from the deployed rewards and token contracts."""
    rewards = call(FWA, "rewards()(address)")
    token = call(FWA, "token()(address)")
    pend = {i: num(call(rewards, "pendingDepositorTokens(uint256)(uint256)", i)) for i in active_ids}
    return dict(token_pending=sum(pend.values()), token_ids=[i for i, v in pend.items() if v],
                token_credit=num(call(rewards, "tokenCredit(address)(uint256)", vault)),
                token_held=num(call(token, "balanceOf(address)(uint256)", vault)))


def read_state(vault, slowdown, burn=False):
    p = [num(x) for x in call(vault, f"getParams()({PARAMS_T})").strip("()").split(", ")]
    (min_edge, _buf, dist_bps, premium, share, _alloc, _mask, ceiling, tip, max_pos, res, _tvl, opcap) = p
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
    tokens = read_tokens(vault, [l.id for l in listings if l.status == policy.ACTIVE])
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
        recent_volume=(seq_now - seq_then) / 7, slowdown_volume=slowdown, burn_tokens=burn,
        reserve=res, op_gas_cap=opcap,
        **tokens,
    )


def to_cast(step):
    fn, *args = step
    if fn in ("sync", "harvest", "unlist", "burnTokens"):
        return [f"{fn}(uint256[])", "[" + ",".join(map(str, args[0])) + "]"]
    if fn == "activate":
        return ["activate(uint256[],uint256)", "[" + ",".join(map(str, args[0])) + "]", args[1]]
    if fn in ("list", "liquidate"):
        return [f"{fn}(uint256)", args[0]]
    if fn == "restock":
        return ["restock(uint256,uint256)", args[0], args[1]]
    return [f"{fn}()"]


HEALTH = dict(last_pass=0, block=0, status=[], pending=None, stats={}, errors=[], pass_errors=0)


def expected_pay(state, fn, est):
    """Reimbursement the vault would pay for `est` gas at this keeper's bid (0 for unpaid calls)."""
    if fn == "burnTokens":
        return 0
    return min(est, state.op_gas_cap) * policy.price(state) * (policy.BPS + state.premium_bps) // policy.BPS


def run_pass(a, tm):
    """One pass: settle any in-flight transaction, then plan, preflight and send one call at a
    time, waiting for each receipt and re-reading the chain before choosing the next."""
    head = num(cast("block-number"))
    errors0 = len(tm.state["errors"]) if tm else 0
    if tm:
        tm.check_reorgs(head)
    failed, skip, sent, declined = 0, set(), 0, []
    for _ in range(a.max_steps):
        state = read_state(a.vault, a.slowdown_volume, a.burn_tokens)

        def wanted(p, state=state):
            est, _why, _exp = tm.preflight(p["to"], p["args"])
            return est

        if tm and tm.wait(wanted, a.pending_timeout):
            print(f"in flight: {tm.state['pending']['label']} nonce {tm.state['pending']['nonce']}; next pass resumes it")
            break
        state = read_state(a.vault, a.slowdown_volume, a.burn_tokens)
        steps = [st for st in policy.plan(state) if st[0] not in skip]
        codes = policy.status(state)  # from the full plan: skips in this pass are this keeper's choice
        HEALTH.update(block=head, status=codes + declined)
        if sent == 0:
            print(f"gas {state.gas_price / 1e9:.3f} gwei, {len(state.listings)} open, {state.idle_packs} idle packs, "
                  f"idle {state.idle_eth / 1e18:.4f} ETH, cycle net {policy.cycle_net(state) / 1e15:.3f} mETH, "
                  f"7d volume {state.recent_volume:.0f}/day")
            for code, kind, detail in codes:
                print(f"status {code} [{kind}] {detail}")
            for n in state.notes:
                print("note:", n)
        if not steps:
            print("nothing to do" if sent == 0 else f"done: {sent} sent, {failed} failed")
            break
        if not a.send:
            for st in steps:
                print("cast send", a.vault, *map(str, to_cast(st)))
            break
        step, args = steps[0], to_cast(steps[0])
        est, why, benign = tm.preflight(a.vault, args)
        if est is None:
            skip.add(step[0])
            if benign:
                tm.state["stats"]["skipped_expected"] += 1
                print(f"skip {step[0]}: vault says {why} (state moved on)")
            else:
                failed += 1
                tm.error(f"preflight of {step[0]} reverted: {why}")
            continue
        bid = state.base_fee + state.max_tip
        pay, cost_ = expected_pay(state, step[0], est), est * bid
        if pay + a.max_loss_wei < cost_ and step[0] != "burnTokens":  # burns are the operator's opt-in cost
            skip.add(step[0])
            tm.state["stats"]["skipped_loss"] += 1
            # Liability work this keeper declined: holders wait on it, so monitoring must see it.
            declined.append(("LIABILITY_WORK_SKIPPED", "action",
                             f"{step[0]} needs --max-loss-wei >= {cost_ - pay} or lower gas"))
            print(f"skip {step[0]}: pay ~{pay} wei < cost ~{cost_} wei beyond --max-loss-wei {a.max_loss_wei}")
            continue
        tm.submit(step[0], a.vault, args, est, state.base_fee, state.max_tip, pay)
        sent += 1
        if tm.wait(wanted, a.pending_timeout):
            print(f"in flight: {step[0]}; next pass resumes it")
            break
        last = tm.state["counted"][-1] if tm.state["counted"] else None
        if last and last["label"] == step[0] and not last["status"]:
            failed += 1
            skip.add(step[0])
    if tm:
        tm.save()
        HEALTH.update(pending=tm.state["pending"], stats=tm.state["stats"], errors=tm.state["errors"][-5:],
                      pass_errors=len(tm.state["errors"]) - errors0 + failed)
    HEALTH["last_pass"] = int(time.time())
    return failed


def serve_health(port, stale_after):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            fresh = time.time() - HEALTH["last_pass"] < stale_after
            ok = fresh and HEALTH["pass_errors"] == 0
            body = json.dumps(dict(HEALTH, ok=ok, fresh=fresh,
                                   attention=[c for c in HEALTH["status"] if c[1] == "action"])).encode()
            self.send_response(200 if ok or self.path != "/health" else 503)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def print_status(a):
    state = read_state(a.vault, a.slowdown_volume, a.burn_tokens)
    for code, kind, detail in policy.status(state):
        print(f"{code:28} {kind:7} {detail}")
    try:
        saved = json.load(open(a.state))
    except FileNotFoundError:
        print(f"no keeper state file at {a.state}")
        return
    p, st = saved.get("pending"), saved.get("stats", {})
    print("in flight:", f"{p['label']} nonce {p['nonce']} hashes {p['hashes']}" if p else "none")
    print(f"sent {st.get('sent', 0)} mined {st.get('mined', 0)} reverted {st.get('reverted', 0)} replaced "
          f"{st.get('replaced', 0)} dropped {st.get('dropped', 0)} reorged {st.get('reorged', 0)}; "
          f"spent {st.get('spent_wei', 0) / 1e18:.6f} ETH, paid {st.get('paid_wei', 0) / 1e18:.6f} ETH, "
          f"net {(st.get('paid_wei', 0) - st.get('spent_wei', 0)) / 1e18:+.6f} ETH")
    for e in saved.get("errors", [])[-5:]:
        print("recent error:", e["msg"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vault")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--status", action="store_true", help="print status and keeper accounting, send nothing")
    ap.add_argument("--account")
    ap.add_argument("--from", dest="sender", help="sender for an unlocked local node (rehearsal)")
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--state", help="keeper state file (default keeper/state-<vault>.json)")
    ap.add_argument("--loop", type=int, default=0, help="seconds between passes; 0 runs once")
    ap.add_argument("--slowdown-volume", type=float, default=0.0)
    ap.add_argument("--max-steps", type=int, default=40, help="calls per pass, each after a fresh read")
    ap.add_argument("--burn-tokens", action="store_true",
                    help="claim and burn FWA token rewards; unpaid, the operator pays the gas")
    ap.add_argument("--max-loss-wei", type=int, default=0,
                    help="loss this keeper accepts per call (liability work above the gas ceiling)")
    ap.add_argument("--max-fee-gwei", type=float, help="never bid a max fee above this")
    ap.add_argument("--confirmations", type=int, default=1, help="blocks before a receipt counts (2+ on mainnet)")
    ap.add_argument("--replace-after", type=int, default=3, help="blocks pending before a same-nonce replacement")
    ap.add_argument("--max-replacements", type=int, default=5)
    ap.add_argument("--pending-timeout", type=float, default=120, help="seconds a pass waits for a receipt")
    ap.add_argument("--health-port", type=int, default=0)
    a = ap.parse_args()
    globals()["RPC"] = a.rpc
    a.state = a.state or str(Path(__file__).parent / f"state-{a.vault.lower()}.json")
    if a.status:
        print_status(a)
        return
    if a.send and not (a.account or a.sender):
        sys.exit("--send needs --account (a cast keystore name) or --from on an unlocked local node")
    tm = None
    if a.send:
        sender = a.sender or cast("wallet", "address", "--account", a.account)
        auth = ["--account", a.account] if a.account else ["--unlocked", "--from", a.sender]
        try:
            tm = txm.TxManager(a.rpc, a.state, sender, auth, a.confirmations, a.replace_after, a.max_replacements,
                               int(a.max_fee_gwei * 1e9) if a.max_fee_gwei else None)
        except txm.Locked as e:
            sys.exit(str(e))
    if a.health_port:
        serve_health(a.health_port, 3 * max(a.loop, 60))
    while True:
        try:
            failed = run_pass(a, tm)
        except subprocess.CalledProcessError as e:  # RPC hiccup: read again next pass
            failed = 1
            HEALTH["pass_errors"] = 1
            print(f"read failed: {(e.output or str(e)).strip()[:200]}")
        if not a.loop:
            sys.exit(1 if failed else 0)
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
