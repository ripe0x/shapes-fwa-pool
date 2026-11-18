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
PARAMS_T = "(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint96,uint128,uint128)"
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
    (min_edge, _buf, dist_bps, premium, share, _alloc, mask, ceiling, ess_ceiling, tip, wfee, _rc, _rr, _ec, _er, max_pos, res,
     _tvl) = p
    rbud, ebud = lines(call(vault, "budget()(uint256,uint256)"))
    try:  # FWA's owner can make its economics unreadable; exits do not need them
        k, backing, _ok = lines(call(vault, "edge(uint256)(uint256,uint256,bool)", 3))
    except subprocess.CalledProcessError:
        k, backing = "0", "0"
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
        num(call(vault, "distributionReserve()(uint256)")) + num(call(vault, "claimableTotal()(uint256)")) + \
        num(call(vault, "processingPool()(uint256)"))  # request charges: reserved like _free() (audit E4)
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
    # A distribution-only checkpoint is due when simulating it succeeds (the vault reverts a
    # checkpoint that would neither settle flows nor distribute; audit E2, E3).
    due = False
    if dist_bps and not pending and not locked:
        try:
            cast("call", vault, "checkpoint(uint256)(uint256)", "0")
            due = True
        except subprocess.CalledProcessError:
            pass
    return policy.State(
        # The keeper bids basefee + maxTip (run_pass), so that is its price.
        now=now, gas_price=num(cast("base-fee")) + tip, base_fee=num(cast("base-fee")), gas_ceiling=ceiling,
        max_tip=tip, markup_bps=premium, share_bps=share, k=num(k), backing=num(backing), min_edge_bps=min_edge,
        mint_fee=num(call(SHAPES, "mintFee()(uint256)")), settlement_window=window,
        blackout=call(FWA, "isPurchaseBlackout()(bool)") == "true",
        queue_drained=num(call(FWA, "unsettledAcquisitionCount()(uint256)")) == 0,
        checkpoint_done_this_interval=num(call(vault, "lastCheckpointInterval()(uint256)")) == interval,
        listings=listings, idle_packs=len(ids_of(call(vault, "idlePacks()(uint256[])"))),
        loose_shapes=num(call(vault, "looseShapeCount()(uint256)")),
        free=max(0, balance - reserves), idle_eth=num(call(vault, "idleEth()(uint256)")), owed_estimate=owed,
        pending_deposits=pending, locked_shares=locked, distribution_due=due, pack_units_mask=mask,
        essential_ceiling=ess_ceiling, essential_cap=_ec, processing_pool=num(call(vault, "processingPool()(uint256)")),
        fee_credit=num(call(FWA, "feeCredit(address)(uint256)", vault)),
        open_positions=len(listings), max_positions=max_pos,
        winding_down=call(vault, "windingDown()(bool)") == "true",
        listing_paused=call(vault, "listingPaused()(bool)") == "true", distribution_bps=dist_bps,
        recent_volume=(seq_now - seq_then) / 7, slowdown_volume=slowdown, burn_tokens=burn,
        reserve=res, work_fee=wfee, routine_budget=num(rbud), essential_budget=num(ebud),
        **tokens,
    )


def to_cast(step, min_pay=0):
    """Signature and arguments of a planned call. Every paid call takes `minPay` last (D56)."""
    fn, *args = step
    if fn == "burnTokens":
        return ["burnTokens(uint256[])", "[" + ",".join(map(str, args[0])) + "]"]
    if fn in ("sync", "harvest", "unlist"):
        return [f"{fn}(uint256[],uint256)", "[" + ",".join(map(str, args[0])) + "]", min_pay]
    if fn == "activate":
        return ["activate(uint256[],uint256,uint256)", "[" + ",".join(map(str, args[0])) + "]", args[1], min_pay]
    if fn in ("list", "liquidate"):
        return [f"{fn}(uint256,uint256)", args[0], min_pay]
    if fn == "restock":
        return ["restock(uint256,uint256,uint256)", args[0], args[1], min_pay]
    return [f"{fn}(uint256)", min_pay]


HEALTH = dict(last_pass=0, block=0, status=[], pending=None, stats={}, errors=[], pass_errors=0)


def fee_args(base_fee, tip):
    """The fee fields the keeper signs with (tx.submit: max fee 2 x basefee + tip), so a simulation
    sees the same tx.gasprice as inclusion; a policy may price on it (audit E1)."""
    return ["--gas-price", str(2 * base_fee + tip), "--priority-gas-price", str(tip)]


def compensation(vault, args, sender, fees=()):
    """What the vault promises for this exact call now: every paid function returns its payment,
    so simulating it from the keeper's address reads the contract's own quote (0 for burnTokens)."""
    if args[0].startswith("burnTokens"):
        return 0
    sig = args[0].replace(")", ")(uint256)", 1) if args[0].endswith(")") else args[0]
    return num(cast("call", vault, sig, *args[1:], "--from", sender, *fees))


# Billed gas / eth_estimateGas per call, from canary-rehearsal receipts (docs/GAS.md). The estimate
# sets the gas limit; billed gas sets the cost. Replaced by this keeper's own receipts once it has
# three of a kind.
BILLED_PER_ESTIMATE = dict(restock=0.92, list=0.98, sync=0.93, unlist=0.80, liquidate=0.80, checkpoint=0.97,
                           harvest=0.95, activate=0.95, burnTokens=0.95)


def billed_ratio(tm, label):
    rows = [e for e in (tm.state["counted"] if tm else []) if e["label"] == label and e.get("est")]
    if len(rows) >= 3:
        return min(1.0, sum(e["gas_used"] for e in rows[-20:]) / sum(e["est"] for e in rows[-20:]))
    return BILLED_PER_ESTIMATE.get(label, 1.0)


def execution_cost(est, bid, fail_rate_bps, ratio=1.0):
    """What the keeper expects to spend: billed gas (the estimate calibrated by receipts) at its
    bid, grossed up for competing transactions it expects to lose."""
    return int(est * ratio) * bid * (10_000 + fail_rate_bps) // 10_000


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

        def wanted(p, prio=None, max_fee=None, state=state):
            """Preflight again; on a replacement also re-check profit at the bumped tip."""
            est, _why, _exp = tm.preflight(p["to"], p["args"])
            if est is None or prio is None or p["label"] == "burnTokens":
                return est
            pay = compensation(a.vault, p["args"], tm.sender, fee_args(state.base_fee, prio))
            if pay + a.max_loss_wei < execution_cost(est, state.base_fee + prio, a.fail_rate_bps,
                                                     billed_ratio(tm, p["label"])):
                return None
            return est

        if tm and tm.wait(wanted, a.pending_timeout):
            print(f"in flight: {tm.state['pending']['label']} nonce {tm.state['pending']['nonce']}; next pass resumes it")
            break
        state = read_state(a.vault, a.slowdown_volume, a.burn_tokens)
        steps = [st for st in policy.plan(state) if st[0] not in skip]
        codes = policy.status(state)  # from the full plan: skips in this pass are this keeper's choice
        HEALTH.update(block=head, status=codes + declined, policy=policy_info(a.vault))
        if sent == 0:
            print(HEALTH["policy"])
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
        pay = 0
        if est is None:
            skip.add(step[0])
            if benign:
                tm.state["stats"]["skipped_expected"] += 1
                print(f"skip {step[0]}: vault says {why} (state moved on)")
            else:
                failed += 1
                tm.error(f"preflight of {step[0]} reverted: {why}")
            continue
        st = tm.state["stats"]
        max_loss = a.max_loss_wei
        if max_loss and st.get("spent_wei", 0) - st.get("paid_wei", 0) > a.max_total_loss_wei:
            # Past the cumulative limit the keeper accepts no further loss; paid work goes on.
            max_loss = 0
            declined.append(("KEEPER_LOSS_LIMIT", "action", "cumulative loss limit reached: only paid work; operator review"))
        # Cost at the next block's highest basefee (+12.5%): inclusion can land there (audit B).
        bid = state.base_fee * 9 // 8 + state.max_tip
        fees = fee_args(state.base_fee, state.max_tip)
        pay = compensation(a.vault, args, tm.sender, fees)
        cost_ = execution_cost(est, bid, a.fail_rate_bps, billed_ratio(tm, step[0]))
        need = cost_ * (10_000 + a.min_return_bps) // 10_000
        if pay + max_loss < need and step[0] != "burnTokens":  # burns are the operator's opt-in cost
            skip.add(step[0])
            tm.state["stats"]["skipped_loss"] += 1
            # Liability work this keeper declined: holders wait on it, so monitoring must see it.
            declined.append(("LIABILITY_WORK_SKIPPED", "action",
                             f"{step[0]} needs --max-loss-wei >= {cost_ - pay} or lower gas"))
            print(f"skip {step[0]}: pay {pay} wei < cost ~{need} wei beyond --max-loss-wei {max_loss}")
            continue
        # minPay: pay and this keeper's gas both move with basefee, so the floor is relative: 80% of
        # the simulated quote (basefee falls at most 12.5% a block). A larger drop means less work
        # was left to do; the whole call reverts instead of paying less.
        args = to_cast(step, pay * 8 // 10 if step[0] != "burnTokens" and max_loss == 0 else 0)
        # Re-check the exact signed call, minPay included, at the signed fees: a call that would
        # revert is not sent. A state change between this check and inclusion can still revert it.
        est2, why2, _ = tm.preflight(a.vault, args, fees)
        if est2 is None:
            skip.add(step[0])
            tm.state["stats"]["skipped_expected"] += 1
            print(f"skip {step[0]}: the signed call would revert ({why2})")
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


def policy_info(vault):
    """Active keeper payment policy (D57). Pay itself is read by simulating each call, so a swap
    needs no keeper change; this is for operators."""
    active = call(vault, "keeperPolicy()(address)")
    return f"policy {active} v{num(call(active, 'policyVersion()(uint256)'))}"


def print_status(a):
    state = read_state(a.vault, a.slowdown_volume, a.burn_tokens)
    print(policy_info(a.vault))
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
    ap.add_argument("--max-total-loss-wei", type=int, default=5 * 10**15,
                    help="stop sending once spent minus paid exceeds this (default 0.005 ETH)")
    ap.add_argument("--max-loss-wei", type=int, default=0,
                    help="loss this keeper accepts per call (liability work above the gas ceiling)")
    ap.add_argument("--max-fee-gwei", type=float, help="never bid a max fee above this")
    ap.add_argument("--fail-rate-bps", type=int, default=0,
                    help="share of sent calls expected to lose to a competing keeper (adds to cost)")
    ap.add_argument("--min-return-bps", type=int, default=0, help="required return over expected cost")
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
