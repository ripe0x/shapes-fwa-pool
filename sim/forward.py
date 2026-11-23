#!/usr/bin/env python3
"""Economics of PackVault, four ways, kept apart in the output (sim/out/forward.md):

1. Expectation: closed form per bid cycle, B (k - 1) less cycle gas, times cycles per year.
2. Backtest: FWA's real acquisition history replayed with a vault of n listings inserted. Every
   real acquisition's fee, total weight and active count come from the event log; the vault's
   presence changes the harmonic backing (so the fee) and the selection odds exactly as FWA's
   formulas do. Selections are drawn per acquisition.
3. Forward simulation: a year, day by day, with the vault's cash flows from sim/vault.py (the
   integer model; candidate fork reconciliation is recorded separately) and every keeper decision from
   keeper/policy.py (the live keeper's rules). FWA's pool is the live snapshot; volume, gas,
   protocol settings, purchaser behaviour and holder flows vary by scenario.
4. Realized performance: none. Nothing is deployed.

FWA mechanics (validated exactly by sim/replay.py against every historical EarningsAccrued):
fee per acquisition F = (1 + surcharge) x harmonic-mean backing; F (1 - cut)(1 - crown) split
equally over active listings; selection odds proportional to 1 / backing. FWA tokens are zero.
"""
import json
import copy
import functools
import heapq
from itertools import islice
from fractions import Fraction
from collections import deque
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "keeper"))
import policy  # noqa: E402
import bisect  # noqa: E402
from vault import ACTIVE, ALLOCATED, SETTLED, WITHDRAWN, OWED, Vault  # noqa: E402

DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
E = 10**18
GWEI = 10**9
P = 6 * 10**16  # the REF_UNITS (6) reference recipe: 0.06 ETH, one 0.05 and one 0.01 Shape (two mints)
BUILD_UNITS = 6
SUR, CUT, S_FEE, BID_RATE = 0.05, 0.01, 0.01, 0.90
ASK, PREMIUM = 0.033, 0.10
MINT_FEE = 10**15
# The backing rule (VaultLib.edge) sets each listing's backing so that keeping the pack beats taking
# FWA's best bid by MIN_KEEP_ADVANTAGE after redeem gas, so a value-aware purchaser keeps and each keep
# pays for a fresh replacement build. Scenarios override this via sc["keep"] or a response sampler.
KEEP_DEFAULT = 1.0
MARK_DAYS = 30  # operating marks interval (diagnostics may lower it)
DAY = 86_400
WORK_FEE = 2 * 10**13  # wei per unit of work, canary value (D55)
CEILING = 0.5  # gwei: canary gasCeiling; above it the keeper waits (D45, D51)
ESSENTIAL_CEILING = 2.0  # gwei: canary essentialCeiling (redemption and wind-down work)


# ---------------------------------------------------------------- history


def history():
    """Per-acquisition arrays from the event log: time, fee, total weight (sum of 1/B in 1/ETH),
    active listing count, protocol cut and crown share in force."""
    cache = OUT / "acq_history.npz"
    if cache.exists():
        return dict(np.load(cache))
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    n_active, cut, crown = 0, 100, 500
    rows = []
    q = ("SELECT ts, event, args FROM logs WHERE event IN ('ListingRewardActivated','ListingRewardRemoved',"
         "'AcquisitionRequested','ConfigSet') ORDER BY block, log_index")
    for ts, ev, a in db.execute(q):
        if ev == "ListingRewardActivated":
            n_active += 1
        elif ev == "ListingRewardRemoved":
            n_active -= 1
        elif ev == "ConfigSet":
            a = json.loads(a)
            if a["key"] == "18":
                cut = int(a["value"])
            elif a["key"] == "15":
                crown = int(a["value"])
        else:
            a = json.loads(a)
            rows.append((ts, int(a["acquisitionFee"]) / E, int(a["totalWeight"]) / E, n_active, cut, crown))
    db.close()
    h = {k: np.array(v) for k, v in zip(("ts", "fee", "w", "n", "cut", "crown"), zip(*rows))}
    np.savez(cache, **h)
    return h


def staging_delays(days_back=30, poll=600):
    """Seconds a relist waits staged (FWA queue busy) before it can be activated, measured at
    every historical relist moment in the last `days_back` days: a bid outcome's resolution plus
    one keeper poll. 0 when FWA's queue was empty then (audit E7)."""
    cache = OUT / f"staging_delays_{days_back}.npy"
    if cache.exists():
        return np.load(cache)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    times, counts, drains, relists, n = [], [], [], [], 0
    q = ("SELECT ts, event FROM logs WHERE event IN ('AcquisitionRequested','AcquisitionProcessed',"
         "'DepositorBidAccepted','DepositorBidAcceptedAsTokens') ORDER BY block, log_index")
    for ts, ev in db.execute(q):
        if ev == "AcquisitionRequested":
            n += 1
        elif ev == "AcquisitionProcessed":
            n -= 1
            if n == 0:
                drains.append(ts)
        else:
            relists.append(ts + poll)
            continue
        times.append(ts)
        counts.append(n)
    end = times[-1]
    out = []
    for t in relists:
        if t < end - days_back * DAY or t > end:
            continue
        i = bisect.bisect_right(times, t) - 1
        if i < 0 or counts[i] == 0:
            out.append(0)
            continue
        k = bisect.bisect_left(drains, t)
        out.append(drains[k] - t if k < len(drains) else end - t)
    db.close()
    arr = np.array(out, dtype=float)
    np.save(cache, arr)
    return arr


STAGING = None  # set in main(): relist waits from the last 30 days of history
REFUNDS_PER_SELECTION = 0.0  # main() reads actual completed status counts from the same history


def pool_snapshot():
    """Backings (ETH) of listings active at the end of the ingested history."""
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    value = {}
    for ev, a in db.execute("SELECT event, args FROM logs WHERE event IN ('NFTListed','BackingUpdated',"
                            "'NFTAllocated','ListingWithdrawn','ListingKicked') ORDER BY block, log_index"):
        a = json.loads(a)
        lid = int(a["listingId"])
        if ev == "NFTListed":
            value[lid] = int(a["value"]) / E
        elif ev == "BackingUpdated" and lid in value:
            value[lid] = int(a["newBacking"]) / E
        else:
            value.pop(lid, None)
    db.close()
    return np.array(list(value.values()))


def daily_volume(h):
    days = (h["ts"] // DAY).astype(int)
    first, last = days.min(), days.max()
    return np.bincount(days - first, minlength=last - first + 1).astype(float), first


# ---------------------------------------------------------------- 1. expectation


def k_of(crown=0.001, cut=CUT, sur=SUR):
    return (1 + sur) * (1 - cut) * (1 - crown)


def expectation(n, volume, gwei, B=0.0363, crown=0.001, premium=0.0):
    pool = POOL
    W = np.sum(1 / pool) + n / B
    cycles = 365 * volume * (1 / B) / W
    # A bid cycle's keeper pay as the vault quotes it (D56): quoted gas at basefee + 0.05 gwei tip,
    # capped at the ceiling (V1: no premium), plus two work units (resolve and relist).
    gas = policy.CYCLE_GAS * min(gwei + 0.05, CEILING) * 1e-9 * (1 + premium) + 2 * WORK_FEE / E
    net = B * (k_of(crown) - 1) - gas
    capital = n * (B + P / E)
    return dict(cycle_days=365 / cycles, net_meth=net * 1e3, apr=cycles * net / (B + P / E),
                share=(n / B) / W, capital=capital)


# ---------------------------------------------------------------- 2. backtest


def backtest(h, n, gwei, t0, t1, B=0.0363, runs=400, seed=1, premium=0.0):
    """Vault of n listings at backing B inside the real history between t0 and t1 (unix s).
    Positions are relisted the same day after a bid outcome (cycle gas charged per selection)."""
    m = (h["ts"] >= t0) & (h["ts"] < t1)
    fee, w, N, cut, crown = h["fee"][m], h["w"][m], h["n"][m], h["cut"][m] / 1e4, h["crown"][m] / 1e4
    if len(fee) == 0:
        return None
    k_hist = (1 + SUR) * (1 - cut) * (1 - crown)
    H, H2 = N / w, (N + n) / (w + n / B)
    fee2 = fee * H2 / H  # the vault's listings move the harmonic backing, so the fee
    vault_fees = fee2 * (1 - cut) * (1 - crown) * n / (N + n)
    p_sel = (n / B) / (w + n / B)
    cycle_cost = B + policy.CYCLE_GAS * min(gwei + 0.05, CEILING) * 1e-9 * (1 + premium) + 2 * WORK_FEE / E
    days = (t1 - t0) / DAY
    capital = n * (B + P / E)
    exp_pnl = vault_fees.sum() - p_sel.sum() * cycle_cost
    rng = np.random.default_rng(seed)
    sel = (rng.random((runs, len(p_sel))) < p_sel).sum(axis=1)
    pnl = vault_fees.sum() - sel * cycle_cost
    ann = pnl / capital * 365 / days
    return dict(days=days, acq=len(fee), per_day=len(fee) / days, k=float(np.mean(k_hist)),
                exp_apr=exp_pnl / capital * 365 / days, p5=np.percentile(ann, 5), p50=np.median(ann),
                p95=np.percentile(ann, 95), ploss=float(np.mean(pnl < 0)), selections=float(p_sel.sum()))


# ---------------------------------------------------------------- 3. forward simulation


class Scenario(dict):
    """volume(day, rng) -> acquisitions; gas gwei; crown/ask changes by day; keep rate;
    elasticity; checkpoint miss rate; holder flows."""


def charge_state(gas, open_positions, pool=0):
    """Minimal policy state for the request charges at `gas` wei basefee (canary parameters)."""
    return policy.State(now=0, gas_price=gas, base_fee=gas, gas_ceiling=int(CEILING * GWEI), max_tip=5 * 10**7,
                        markup_bps=0, share_bps=2_500, k=0, backing=0, min_edge_bps=100, mint_fee=MINT_FEE,
                        settlement_window=0, blackout=False, queue_drained=True, checkpoint_done_this_interval=False,
                        open_positions=open_positions, work_fee=WORK_FEE,
                        essential_ceiling=int(ESSENTIAL_CEILING * GWEI), processing_pool=pool)


def backing_proposals(target, positions, minimum=0, maximum=2**256 - 1, count=policy.MAX_BATCH["list"]):
    """Bounded offchain identifier proposals, using current outstanding identifiers."""
    if not target:
        return []
    return list(_proposals(target, frozenset(p.backing for p in positions.values()), minimum, maximum, count))


@functools.lru_cache(maxsize=65_536)
def _proposals(target, reserved, minimum, maximum, count):
    # Speed only: the proposals are a pure function of these arguments.
    return tuple(policy.propose_backings(target, len(reserved), count, reserved.__contains__,
                                         minimum=minimum, maximum=maximum))


def economic_nav(v, credit):
    """Independent end-of-run mark, including known outcomes still awaiting bookkeeping.

    A blocked checkpoint never prices from this reference. It only reports what the modeled
    external assets hold when journal or receipt processing is behind.
    """
    value = v.free() + sum(v.idle_packs) + sum(v.recovery_packs) + credit
    for p in v.positions.values():
        if p.status == ACTIVE:
            value += p.value + p.backing + p.pending_fees
        elif p.status == ALLOCATED or p.pack_owned:
            value += p.value
    return value


class OperatingClock:
    """Opt-in scenario calendar; external events are hypotheses, never RPC answers.

    Requests stop during the real blackout. Fixed response/VRF delays are explicit
    scenario inputs. A keeper pass waits for each conditional receipt before its next
    read; after at most40calls (or no affordable action) it waits the configured poll.
    """
    INTERVAL, BLACKOUT_START, SETTLEMENT = 43_200, 42_300, 3_600

    def __init__(self, sc, seed, days, exit_days):
        self.start = int(sc["start_timestamp"])
        self.end = (days + exit_days) * DAY
        self.poll = int(sc.get("poll_seconds", 60))
        self.receipt_delay = int(sc.get("receipt_seconds", 36))
        self.response_delay = sc.get("purchaser_response_seconds", 120)
        self.events, self.serial = [], 0
        if self.poll <= 0 or self.receipt_delay <= 0:
            raise ValueError("timed polling and receipt delay must be positive")
        market_rng = np.random.default_rng(seed ^ 0xF00D)
        replay = sc.get("replay_events")
        if replay is not None:
            # Recorded FWA activity, repeated end to end until the horizon. The caller supplies
            # (offset seconds, kind, payload) from one authenticated window of the event log.
            period = int(sc["replay_period_seconds"])
            for repeat in range(-(-self.end // period)):
                for at, kind, payload in replay:
                    self.push(repeat * period + at, kind, payload)
        for day in range(days + exit_days if replay is None else 0):
            volume = sc["volume"](day, market_rng)
            successes = int(market_rng.poisson(max(0, volume)))
            refunds = int(market_rng.poisson(successes * sc.get("refunds_per_selection", REFUNDS_PER_SELECTION)))
            for successful in [True] * successes + [False] * refunds:
                at = day * DAY + int(market_rng.integers(DAY))
                # Preserve the sampled count while moving blackout requests to the next opening.
                phase = (self.start + at) % self.INTERVAL
                if phase >= self.BLACKOUT_START:
                    at += self.INTERVAL - phase
                self.push(at, "request", successful)
                self.push(at + int(sc.get("vrf_seconds", 60)), "acquisition", successful)
        self.push(0, "keeper", 40)
        self.push(days * DAY, "cutoff")
        for day, fraction in sc.get("redeem", []):
            self.push(day * DAY, "redemption", fraction)

    def push(self, at, kind, payload=None):
        if at > self.end:
            return
        # Explicit tie convention: market completion/response before the keeper's fresh read.
        priority = 1 if kind == "keeper" else 0
        self.serial += 1
        heapq.heappush(self.events, (at, priority, self.serial, kind, payload))

    def __iter__(self):
        while self.events:
            at, _, _, kind, payload = heapq.heappop(self.events)
            yield at, kind, payload


def bounded_policy_positions(v, now, settlement_window, returned_order, selected_times, owed_after=""):
    """Model the event index's fixed candidate classes, without an omniscient policy input.

    The simulator owns external state so it can project these classes in memory. Production
    obtains the identical bounded classes from indexed SQL queries, then hydrates their IDs.
    Text ID ordering matches keeper/index.py's TEXT primary keys.
    """
    limit = policy.MAX_BATCH["sync"]  # keeper.keeper.MAX_CANDIDATES
    positions = v.positions
    returned = sorted((i for i, p in positions.items()
                       if p.status == SETTLED and p.pack_owned and p.state != OWED),
                      key=lambda i: returned_order.get(i, (selected_times.get(i, 0), i)))[:limit]
    due = list(returned)
    for i in sorted(v.receipts, key=str)[:limit]:
        if len(due) == limit:
            break
        if i not in due:
            due.append(i)
    selected = sorted((i for i, p in positions.items()
                       if p.state == ACTIVE and p.status in (ALLOCATED, SETTLED)),
                      key=lambda i: (selected_times.get(i, 0), i))[:limit]
    due += selected
    due += sorted((i for i, p in positions.items()
                   if p.state == ALLOCATED and p.allocated_at <= now - settlement_window),
                  key=lambda i: (positions[i].allocated_at, str(i)))[:limit]
    owed = sorted((i for i, p in positions.items() if p.state == OWED), key=str)
    rotation = [i for i in owed if str(i) > owed_after][:limit]
    rotation += [i for i in owed if str(i) <= owed_after][:limit - len(rotation)]
    if rotation:
        owed_after = str(rotation[-1])
    due += rotation
    active = sorted((i for i, p in positions.items() if p.state == ACTIVE),
                    key=lambda i: (positions[i].fee_debt, str(i)))[:limit]
    return list(dict.fromkeys(due + active)), owed_after


def run(sc, n_target, seed, days=365, values=None):
    rng = np.random.default_rng(seed)
    if "foreign_pool_weight" in sc:
        # Timed scenarios need only the authenticated aggregate inverse-backing weight.
        # Do not invent per-listing records when the historical SQLite archive is absent.
        if sc.get("pool_scale", 1.0) != 1.0:
            raise ValueError("aggregate snapshot cannot sample individual foreign listings")
        W_o = float(sc["foreign_pool_weight"])
        if W_o <= 0 or not np.isfinite(W_o):
            raise ValueError("foreign pool weight must be positive and finite")
    else:
        others = POOL
        if sc.get("pool_scale", 1.0) != 1.0:
            others = rng.choice(POOL, int(len(POOL) * sc["pool_scale"]))
        W_o = float(np.sum(1 / others))
    g_of = sc.get("gwei", 0.15)  # scenario basefee; the actual bid also includes maxTip
    deposit = sc.get("deposit_wei", int((n_target * (0.0363 + 0.03) + 0.06 + 0.11) * E))
    values = values or json.loads((ROOT.parent / "deploy/mainnet.json").read_text())
    ceiling, tip = values["gasCeilingWei"], values["maxTipWei"]
    essential_ceiling = values["essentialCeilingWei"]
    work_fee, mint_fee = values["workFeeWei"], MINT_FEE
    if deposit > values["tvlCapWei"]:
        raise ValueError("model deposit exceeds configured TVL cap")
    v = Vault(seed=10**16, balance=10**16, reserve=values["reserveWei"],
              distribution_bps=values["distributionBps"], allocated_bound_bps=values["allocatedBoundBps"])
    v.routine_budget = v.routine_cap = values["routineCapWei"]
    v.essential_budget = v.essential_cap = values["essentialCapWei"]
    v.routine_rate, v.essential_rate = values["routineRatePerDayWei"], values["essentialRatePerDayWei"]
    journal = deque()  # (our listing ID or None, actual selection time)
    journal_paid = journal_own = journal_foreign = journal_pruned = terminal_work = 0
    journal_rebased = journal_scans = journal_scanned = journal_skipped = 0
    # Operating-period diagnostics (timed mode): time-weighted deployed capital and book value, and
    # keeper passes that left due work waiting for gas or deferred it.
    last_tick = deployed_int = book_int = gas_wait_seconds = deferred_seconds = settlement_wait_seconds = 0
    self_serve_cost = skipped_funding = call_limit_days = 0
    g0 = g_of(0) if callable(g_of) else g_of
    st0 = charge_state(int(g0 * GWEI), 0)
    st0.gas_ceiling, st0.essential_ceiling, st0.max_tip = ceiling, essential_ceiling, tip
    st0.work_fee, st0.essential_cap = work_fee, values["essentialCapWei"]
    ck0, d0 = policy.request_charge(st0), policy.deploy_charge(st0)
    v.deposit("h", deposit, ck0, deposit * d0 // (policy.position_value(st0) + d0))
    paid_in = deposit + ck0
    exit_all = sc.get("exit_all", False)
    exit_days = sc.get("exit_days", 30) if exit_all else 0
    user_gas = sc.get("user_gas_proxy", {})
    holder_gas = (int(g0 * GWEI) + tip) * user_gas.get("deposit", 0)
    unknown_user_gas = int(exit_all and "deposit" not in user_gas)
    holder_claimed = holder_cancelled = holder_keeper_pay = holder_maintenance_gas = 0
    exit_requested = False
    operation_end_backlog = 0
    operation_end_cash = operation_end_keeper_paid = operation_end_fees = 0
    operation_end_routine_paid = operation_end_routine_budget = 0
    operating_budget_marks = {}
    operation_end_idle = operation_end_funding = operation_end_loose = operating_active_days = 0
    rescue_sync = sc.get("holder_rescue_sync", False)
    trace = sc.get("trace_sink")
    timed = sc.get("timed", False)
    clock = OperatingClock(sc, seed, days, exit_days) if timed else None
    now = absolute_now = 0
    event_kind = "day"
    market_pending = last_checkpoint_interval = 0
    selected_times, returned_order, applied_changes, active_days_seen = {}, {}, set(), set()
    response_keep = {}
    expected_selections = 0.0
    owed_after, event_order = "", 0
    expired_backing = expired_nft = purchaser_returns = late_purchaser_returns = 0
    timed_checkpoint_times = []
    timed_pass_limits = 0
    routine_paid = essential_paid = request_paid = 0
    routine_unfunded = unpaid_routine_calls = zero_quote_sync_calls = 0
    sync_credit_sweeps = sync_active_fee_claims = sync_fee_receipts = sync_collection_quote = 0
    last_unfunded_offer = last_cash_shortfall = last_permission_shortfall = 0
    op_names = ("sync", "harvest", "unlist", "liquidate", "checkpoint", "build", "list")
    op_paid = dict.fromkeys(op_names, 0)
    op_calls = dict.fromkeys(op_names, 0)
    holder_calls = dict.fromkeys(op_names, 0)
    min_free = v.free()
    next_id, credit = 1, 0

    def locked_holder():
        r = v.redemptions.get("h")
        return (r.shares * v.redeem_g // r.g0) if r and r.shares and r.era == v.redeem_era else 0

    def trace_state(action, day):
        if trace is not None:
            trace.append(dict(day=day, action=action, **(dict(timestamp=absolute_now, event=event_kind) if timed else {}), cash=v.balance, free=v.free(), routine_budget=v.routine_budget,
                              protected=v.redemption_reserve + v.distribution_reserve + v.claimable_total + v.processing_pool,
                              locked=locked_holder(), global_locked=v.locked_shares, positions=len(v.positions),
                              returned_value=sum(p.value for p in v.positions.values() if p.status == SETTLED and p.pack_owned),
                              journal=len(journal), claimed=holder_claimed))

    def claim_available(gas_price, day):
        nonlocal holder_claimed, holder_gas, unknown_user_gas
        r = v.redemptions.get("h")
        redemption_pay = 0
        if r and r.shares:
            q = v.era_final_q[r.era] if r.era < v.redeem_era else v.redeem_q
            redemption_pay = r.shares * (q - r.q0) // r.g0
        distribution_pay = v.shares.get("h", 0) * v.dist_per_share // E - v.dist_debt.get("h", 0)
        if v.claimable.get("h", 0) + redemption_pay + distribution_pay <= 0:
            return
        received = v.claim("h")
        assert received > 0
        holder_claimed += received
        holder_gas += user_gas.get("claim", 0) * gas_price
        unknown_user_gas += int("claim" not in user_gas)
        trace_state("claim", day)
    allocated_day = {}
    ask, crown = ASK, 0.001
    vol_hist, open_days = [], []
    if timed:
        vol_hist = [0] * (days + exit_days + 1)
    checkpoints = accrued = selected = selected_backing = missed_alloc = 0
    listing_ready_day = 0
    waits = sc.get("staging", STAGING)
    max_calls = sc.get("max_keeper_calls_per_day", 512)
    self_serve = sc.get("self_serve_exits", True)  # D64: the withdrawing holder executes unpaid exit work

    ticks = clock if timed else ((d * DAY, "day", None) for d in range(days + exit_days))
    for now, event_kind, payload in ticks:
        if timed and now // DAY < days and now > last_tick:
            deployed_int += (now - last_tick) * (v.active_backing + v.active_count * 3 * policy.UNIT)
            book_int += (now - last_tick) * (v.free() + v.tracked_value + v.active_backing)
        last_tick = max(last_tick, now)
        event_order += 1
        d = now // DAY
        absolute_now = (clock.start if timed else 0) + now
        v.sync_budget(now)
        if d <= days and d % MARK_DAYS == 0 and str(d) not in operating_budget_marks:
            operating_budget_marks[str(d)] = dict(elapsed_seconds=now, routine_budget_wei=v.routine_budget,
                routine_paid_wei=routine_paid, free_wei=v.free(), positions=len(v.positions),
                fees_wei=v.fees_received, lost_wei=v.backing_lost, selections=selected)
        gas = int((g_of(d) if callable(g_of) else g_of) * GWEI)
        for day, key, val in sc.get("changes", []):
            if day != d or (timed and (day, key) in applied_changes):
                continue
            applied_changes.add((day, key))
            if key == "crown":
                crown = val
            elif key == "ask":
                ask = val
                cap = int(ask * (1 + PREMIUM) * E)
                for i, p in list(v.positions.items()):
                    if not sc.get("exempt", True) and p.status == ACTIVE and p.backing > cap:
                        credit += p.pending_fees
                        v.kicked(i)
        cap = int(ask * (1 + PREMIUM) * E)
        k = int(k_of(crown) * E)
        backing = policy.edge_backing(k, None if sc.get("exempt", True) else cap, int(S_FEE * 1e4), BUILD_UNITS,
                                      ceiling, values["payMarkupBps"], work_fee,
                                      price=min(gas + tip, ceiling), mint_fee=mint_fee,
                                      buffer_bps=values["bufferBps"], min_edge_bps=values["minEdgeBps"])

        if timed:
            A = 0
            if event_kind == "request":
                market_pending += 1
            elif event_kind == "acquisition":
                market_pending -= 1
                assert market_pending >= 0
                # A replayed acquisition carries its recorded foreign totalWeight (1/ETH).
                successful, foreign_weight = payload if isinstance(payload, tuple) else (payload, W_o)
                A = int(successful)
                chosen = None
                if successful:
                    act = [i for i, p in v.positions.items() if p.status == ACTIVE]
                    weights = [E / v.positions[i].backing for i in act]
                    W = foreign_weight + sum(weights)
                    expected_selections += sum(weights) / W
                    # Conditional counterfactual selection, not replay of a real VRF word.
                    draw = rng.random() * W
                    for i, weight in zip(act, weights):
                        draw -= weight
                        if draw < 0:
                            chosen = i
                            break
                    fee = int((1 + SUR) * (1 - CUT) * (1 - crown) / W * E)
                    for i in act:
                        v.accrue(i, fee)
                        accrued += fee
                    if chosen is not None:
                        p = v.positions[chosen]
                        credit += p.pending_fees
                        p.pending_fees = 0
                        p.status = ALLOCATED
                        selected_times[chosen] = absolute_now
                        selected_backing += p.backing
                        selected += 1
                        trace_state("selection", d)
                        if trace is not None:
                            trace[-1]["listing_id"] = chosen
                        delay, kept = clock.response_delay, None
                        if "response_sampler" in sc:
                            # Empirical purchaser behaviour: (seconds or None for silence, kept).
                            delay, kept = sc["response_sampler"](rng)
                            response_keep[chosen] = kept
                        settlement_wait_seconds += clock.SETTLEMENT if delay is None else min(int(delay), clock.SETTLEMENT)
                        if delay is not None:
                            clock.push(now + int(delay), "response", chosen)
                journal.append((chosen, absolute_now if chosen is not None else 0))
                v.completed_prefix += 1
            elif event_kind == "response":
                p = v.positions.get(payload)
                if p and p.status == ALLOCATED:
                    late_purchaser_returns += int(absolute_now >= selected_times[payload] + clock.SETTLEMENT)
                    kept = response_keep.pop(payload, None)
                    if kept if kept is not None else rng.random() < sc.get("keep", KEEP_DEFAULT):
                        v.record_keep(payload, v.settlement_fee_bps)
                    else:
                        v.bid_settled(payload)
                        returned_order[payload] = (absolute_now, event_order)
                    purchaser_returns += 1
                    trace_state("purchaser-response", d)
            for i, p in v.positions.items():
                p.expired = p.status == ALLOCATED and absolute_now >= selected_times.get(i, absolute_now) + clock.SETTLEMENT
            if event_kind == "acquisition":
                vol_hist[d] += A
            if event_kind == "keeper":
                open_days.append(len(v.positions))
                if d < days and any(p.status == ACTIVE for p in v.positions.values()):
                    active_days_seen.add(d)
                operating_active_days = len(active_days_seen)
        else:
            for i, d0 in list(allocated_day.items()):
                if d >= d0 + 1:
                    del allocated_day[i]
                    if rng.random() < sc.get("keep", KEEP_DEFAULT):
                        v.record_keep(i, v.settlement_fee_bps)
                    else:
                        v.bid_settled(i)

            # Daily sampling approximates selection timing, but each position uses its actual B.
            # Clamp the sampled set to A so the approximation cannot invent journal records.
            act = [i for i, p in v.positions.items() if p.status == ACTIVE]
            n = len(act)
            if d < days:
                operating_active_days += int(n > 0)
            weights = np.array([E / v.positions[i].backing for i in act])
            W = W_o + float(weights.sum())
            share = float(weights.sum()) / W if n else 0
            vol = sc["volume"](d, rng) * max(0.0, 1 - sc.get("elasticity", 0) * share)
            A = int(rng.poisson(vol)) if vol > 0 else 0
            vol_hist.append(A)
            chosen = []
            if n and A:
                per_listing = int((1 + SUR) * (1 - CUT) * (1 - crown) / W * E)
                qs = weights / W
                p_days = 1 - (1 - qs) ** A
                chosen = [i for i, hit in zip(act, rng.random(n) < p_days) if hit]
                if len(chosen) > A:
                    chosen = rng.choice(chosen, A, replace=False).tolist()
                chosen_set = set(chosen)
                for i, q_i, p_day in zip(act, qs, p_days):
                    p = v.positions[i]
                    if i in chosen_set:
                        before_sel = int(per_listing * (1 / q_i - A * (1 - q_i) ** A / p_day))
                        credit += p.pending_fees + before_sel
                        accrued += before_sel
                        p.pending_fees = 0
                        p.status = ALLOCATED  # FWA changed; the vault's book changes only in sync below
                        allocated_day[i] = d
                        selected_backing += p.backing
                    else:
                        v.accrue(i, per_listing * A)
                        accrued += per_listing * A
                selected += len(chosen)
            refunds = int(rng.poisson(A * sc.get("refunds_per_selection", REFUNDS_PER_SELECTION)))
            journal.extend((i, d * DAY) for i in chosen)
            journal.extend((None, 0) for _ in range(A - len(chosen) + refunds))
            v.completed_prefix += A + refunds

        blackout_ok = True if timed else rng.random() >= sc.get("checkpoint_miss", 0.0)
        congested = sc.get("congested") and sc["congested"](d)
        if not timed:
            open_days.append(len(v.positions))
        calls = 0
        checkpoint_done = timed and last_checkpoint_interval == absolute_now // OperatingClock.INTERVAL
        holder_finished = False
        phases = ([absolute_now % clock.INTERVAL >= clock.BLACKOUT_START] if event_kind == "keeper" else []) if timed else (False, True)
        for blackout in phases:
            while not congested and not holder_finished and calls < (1 if timed else max_calls):
                hydrated = list(v.positions)
                if timed:
                    hydrated, owed_after = bounded_policy_positions(v, absolute_now, clock.SETTLEMENT,
                                                                     returned_order, selected_times, owed_after)
                listings = [policy.Listing(i, p.status, allocated_at=selected_times.get(i, p.allocated_at) if timed else p.allocated_at, pending_fees=p.pending_fees,
                                           value=p.value, backing=p.backing,
                                           unapplied=p.state == ACTIVE and p.status in (ALLOCATED, SETTLED))
                            for i in hydrated for p in [v.positions[i]]]
                st = policy.State(
                    now=absolute_now, gas_price=gas + tip, base_fee=gas, gas_ceiling=ceiling, max_tip=tip,
                    markup_bps=values["payMarkupBps"], share_bps=values["keeperShareBps"], k=k, backing=backing,
                    min_edge_bps=values["minEdgeBps"], settlement_fee_bps=int(S_FEE * 10_000), mint_fee=mint_fee,
                    settlement_window=clock.SETTLEMENT if timed else 10**12,
                    blackout=blackout, queue_drained=(market_pending == 0 if timed else (blackout_ok or not blackout) and d >= listing_ready_day),
                    checkpoint_done_this_interval=checkpoint_done, listings=listings, idle_packs=len(v.idle_packs),
                    recovery_packs=len(v.recovery_packs),
                    free=v.free(), idle_eth=v.idle(), owed_estimate=v.owed_estimate(),
                    pending_deposits=v.pending_total, locked_shares=v.locked_shares,
                    total_shares=v.total_shares, fee_credit=credit,
                    open_positions=len(v.positions), active_count=v.active_count, idle_value=v.idle_value,
                    idle_funding=v.idle_funding,
                    journal_cursor=v.acquisition_cursor, completed_prefix=v.completed_prefix,
                    pending_receipts=len(v.receipts), routine_budget=v.routine_budget,
                    essential_budget=v.essential_budget, essential_cap=values["essentialCapWei"],
                    recent_volume=float(np.mean(vol_hist[max(0, d - 6):d + 1] if timed else vol_hist[-7:])), work_fee=work_fee,
                    slowdown_volume=sc.get("slowdown", 0.0), essential_ceiling=essential_ceiling,
                    pack_units_mask=values["packUnitsMask"] | (1 << BUILD_UNITS), build_units=BUILD_UNITS,
                    reserve=values["reserveWei"],
                    processing_pool=v.processing_pool, distribution_bps=v.distribution_bps,
                    allocation_stale=(v.allocation_head < len(v.allocation_queue) and
                                      (v.allocation_queue[v.allocation_head] not in v.positions or
                                       v.positions[v.allocation_queue[v.allocation_head]].state != ALLOCATED)),
                    own_journal_pending=any(v.positions[i].state == ACTIVE and v.positions[i].status in (ALLOCATED, SETTLED)
                                            for i in hydrated))
                if backing:
                    up = lambda a, b: -(-a // b)
                    keep_bps = int(S_FEE * 10_000)
                    cycle = policy.quote(st, policy.CYCLE_GAS, 2)
                    # VaultLib floors for a valid listing near the edge's desired backing: the keep
                    # never loses at FWA's 5% settlement-fee cap (P/0.95), the bid outcome clears the
                    # cycle (B(k-1) > cycle), and the keep outcome clears value plus cycle (B(k-s) >= P + cycle).
                    minimum = max(up(P * 10_000, 9500), cycle * E // (k - E) + 1,
                                  up((P + cycle) * E, k - keep_bps * 10**14))
                    maximum = 2**256 - 1 if sc.get("exempt", True) else cap * (10_000 - values["bufferBps"]) // 10_000
                    # Speed only: with no idle pack and idle ETH below one backing, the planner can
                    # use neither list nor build proposals, so skipping them changes no decision.
                    if v.idle_packs or st.idle_eth >= minimum:
                        st.backing_proposals = backing_proposals(backing, v.positions, minimum, maximum)
                        # A newly built pack repays its build from the keep outcome B(k-s), not the bid
                        # outcome B(k-1): backing >= (value + cycle + build) / (k - s) (VaultLib._profitable).
                        build_minimum = max(minimum, up((P + cycle + policy.build_cost(st, BUILD_UNITS)) * E,
                                                        k - keep_bps * 10**14))
                        build_quote = backing_proposals(backing, v.positions, build_minimum, maximum, 1)
                        st.build_proposals = build_quote * policy.MAX_BATCH["build"]
                planned = policy.plan(st)
                if timed and calls == 0 and d < days:
                    waiting = v.idle_packs or any(l.status in (SETTLED, WITHDRAWN) or (l.status == ALLOCATED and
                                                  absolute_now >= l.allocated_at + clock.SETTLEMENT) for l in listings)
                    if waiting and st.gas_price > st.gas_ceiling:
                        gas_wait_seconds += clock.poll
                    elif any(l.status in (SETTLED, WITHDRAWN) for l in listings) and not any(a[0] == "sync" for a in planned):
                        deferred_seconds += clock.poll
                Q = policy.Q
                essential = v.locked_shares != 0
                executed = False

                def affordable(gas_q, units=0, ess=False, funding_cap=None, cash_delta=0, liability=False, final_candidate=True):
                    nonlocal skipped_funding, routine_unfunded
                    nonlocal last_unfunded_offer, last_cash_shortfall, last_permission_shortfall
                    offer = policy.pay_v1(st, gas_q, units, ess)
                    funds = funding_cap if funding_cap is not None else (v.essential_budget if ess else v.routine_budget)
                    paid = min(offer, funds, max(0, v.free() + cash_delta))
                    holder_fallback = self_serve and liability and (not exit_all or fn != "sync"
                        or (rescue_sync and exit_requested and v.locked_shares))
                    if paid < offer and not holder_fallback:
                        if not final_candidate:
                            return False  # A shorter preflight prefix is not an operating stall.
                        skipped_funding += 1
                        last_unfunded_offer = offer
                        last_cash_shortfall = max(0, offer - max(0, v.free() + cash_delta))
                        last_permission_shortfall = max(0, offer - funds)
                        if not ess and fn != "checkpoint":
                            routine_unfunded += 1
                        if exit_requested:
                            trace_state("unfunded-" + fn, d)
                        return False
                    return True

                def pay(gas_q, units=0, ess=False, funding_cap=None, liability=False):
                    nonlocal self_serve_cost, holder_gas, holder_keeper_pay, holder_maintenance_gas
                    nonlocal routine_paid, essential_paid, request_paid, unpaid_routine_calls
                    offer = policy.pay_v1(st, gas_q, units, ess)
                    paid = v.pay_keeper(offer, essential=ess, cap=funding_cap)
                    op_paid[fn] += paid
                    op_calls[fn] += 1
                    if fn == "checkpoint" and funding_cap is not None:
                        request_paid += paid
                    elif ess:
                        essential_paid += paid
                    else:
                        routine_paid += paid
                        unpaid_routine_calls += int(paid < offer and fn != "harvest")
                    if self_serve and liability:
                        # Proxy from the operation quote, not a measured gas claim. Kept outside
                        # vault NAV because the withdrawing holder pays this gas personally.
                        self_serve_cost += max(0, gas_q * st.gas_price - paid)
                        if exit_all and paid < offer:
                            # Variable-size unpaid maintenance retains the explicitly labeled
                            # operation-quote gas proxy until matching receipt curves exist.
                            cost = user_gas.get(fn, gas_q) * st.gas_price
                            holder_gas += cost
                            holder_maintenance_gas += cost
                            holder_keeper_pay += paid
                            holder_calls[fn] += 1
                    return paid

                for action_index, action in enumerate(planned):
                    fn = action[0]
                    action_meta = {}
                    if fn == "sync":
                        unexposed = not v.positions and not v.receipts and not v.active_count and not v.active_backing and not v.allocated_value
                        rebase_count = len(journal) if unexposed else 0
                        entries = []
                        own = 0
                        for entry in islice(journal, policy.MAX_BATCH["journal"]):
                            if entry[0] is not None:
                                if own == policy.MAX_BATCH["selected"]:
                                    break
                                own += 1
                            entries.append(entry)
                        if rebase_count:
                            assert all(i is None for i, _ in journal)
                            entries = []
                        own_ids = [i for i, _ in entries if i is not None]
                        # ScanLib.rebase: read the open positions instead of the journal when cheaper.
                        found = [(at, i) for i, at in journal if i is not None]
                        scanned, scan_now = 0, False
                        if (not unexposed and journal and len(v.positions) * Q["scan"] <= min(len(journal), policy.MAX_BATCH["journal"]) * Q["journal"]
                                and len(found) <= policy.MAX_BATCH["selected"]):
                            entries, scan_now = [], True
                            own_ids = [i for _, i in sorted(found)]
                            scanned = sum(p.state == ACTIVE for p in v.positions.values())
                        expired_ids = [i for i in action[1] if timed and i in v.positions
                                       and v.positions[i].status == ALLOCATED and v.positions[i].expired
                                       and (v.positions[i].state == ALLOCATED or i in own_ids)]
                        resolved = [i for i in action[1] if i in v.positions and
                                    (v.positions[i].status == WITHDRAWN or
                                     (v.positions[i].status == SETTLED and
                                      (v.positions[i].state == ALLOCATED or i in own_ids)) or i in expired_ids)]
                        reclaim_cash = sum(v.positions[i].backing * (10_000 - v.settlement_fee_bps) // 10_000
                                           for i in expired_ids if v.positions[i].backing * (10_000 - v.settlement_fee_bps) // 10_000 >= v.positions[i].value)
                        prospective = [v.allocation_queue[j] for j in range(v.allocation_head,
                                      min(len(v.allocation_queue), v.allocation_head + policy.MAX_BATCH["prune"]))] + own_ids
                        pruned = 0
                        for i in prospective[:policy.MAX_BATCH["prune"]]:
                            p = v.positions.get(i)
                            if i not in resolved and (i in own_ids or (p and p.state == ALLOCATED)):
                                break
                            pruned += 1
                        if not entries and not scan_now and not resolved and not pruned and not rebase_count:
                            continue
                        checkpoint_due = (st.blackout and st.queue_drained and not st.checkpoint_done_this_interval
                                          and (st.pending_deposits or st.locked_shares or st.distribution_bps))
                        tail_base = Q["journal_tail"] + (Q["distribution_proof"]
                            if st.distribution_bps and not (st.pending_deposits or st.locked_shares) else 0)
                        tail_q = tail_base + len(entries) * Q["journal"] + scanned * Q["scan"] + pruned * Q["pruned"]
                        distribution_probe = v
                        if pruned and st.distribution_bps and not (st.pending_deposits or st.locked_shares):
                            distribution_probe = copy.deepcopy(v)
                            distribution_probe.prune(policy.MAX_BATCH["prune"])
                        tail_paid = checkpoint_due and (st.pending_deposits or st.locked_shares
                            or distribution_probe.distribution_tail(policy.quote(st, tail_q), credit))
                        journal_paid_work = (len(entries) == policy.MAX_BATCH["journal"] or own_ids or resolved
                                             or ((entries or scanned) and tail_paid))
                        required_tail = bool((entries or scanned) and len(entries) < policy.MAX_BATCH["journal"]
                                             and not own_ids and not resolved and tail_paid)
                        base_q = tail_base if required_tail else Q["sync"]
                        gas_q = base_q + (len(entries) * Q["journal"] if journal_paid_work else 0) \
                            + (scanned * Q["scan"] if own_ids or required_tail else 0) + len(own_ids) * Q["selected"] \
                            + len(resolved) * Q["synced"] + pruned * Q["pruned"]
                        if ((unexposed and not v.tracked_value) or (rebase_count and not pruned)
                                or (not journal_paid_work and not own_ids and not resolved and not pruned)):
                            gas_q = 0
                        base_gas_q = gas_q
                        funding_probe = distribution_probe if required_tail and st.distribution_bps \
                            and not (st.pending_deposits or st.locked_shares) else v
                        gas_q, take_credit, fee_ids = funding_probe.sync_fee_plan(
                            action[1], credit, gas_q, len(resolved),
                            lambda g, u: policy.quote(st, g, u), st.share_bps,
                            Q["sync_credit"], Q["sync_funding"], Q["harvested"],
                            cash_delta=reclaim_cash,
                            distribution_tail=bool(required_tail and st.distribution_bps
                                                   and not (st.pending_deposits or st.locked_shares)))
                        fee_receipts = take_credit + sum(v.positions[i].pending_fees for i in fee_ids)
                        if exit_all and gas_q == 0:
                            if not (exit_requested and v.locked_shares):
                                continue  # No operator gratuity is invented for an unpaid job.
                            cost = user_gas.get("unexposed_sync", 0) * st.gas_price
                            holder_gas += cost
                            holder_maintenance_gas += cost
                            unknown_user_gas += int("unexposed_sync" not in user_gas)
                            holder_calls["sync"] += 1
                            zero_quote_sync_calls += 1
                        if not affordable(gas_q, len(resolved), False,
                                          cash_delta=reclaim_cash + fee_receipts, liability=essential,
                                          final_candidate=not any(a[0] == "sync" for a in planned[action_index + 1:])):
                            continue
                        if rebase_count:
                            assert v.advance_unexposed()
                            journal.clear()
                            journal_rebased += rebase_count
                        if scan_now:
                            assert v.scan_rebase(found) == scanned
                            journal_scans += 1
                            journal_scanned += scanned
                            journal_skipped += len(journal) - len(found)
                            journal.clear()
                        for i, at in entries:
                            journal.popleft()
                            if i is not None:
                                v.select(i, at)
                            v.acquisition_cursor += 1
                        for i in resolved:
                            if i in expired_ids:
                                p = v.positions[i]
                                if p.backing * (10_000 - v.settlement_fee_bps) // 10_000 >= p.value:
                                    v.record_keep(i, v.settlement_fee_bps)
                                    expired_backing += 1
                                    trace_state("expiry-backing", d)
                                else:
                                    v.bid_settled(i)
                                    expired_nft += 1
                                    trace_state("expiry-nft", d)
                            if v.receipts.get(i, (0,))[0] == 1:
                                v.consume_keep(i)
                            else:
                                v.sync_owned(i)
                        assert v.prune(policy.MAX_BATCH["prune"]) == pruned
                        for i in fee_ids:
                            v.harvest_listing(i)
                        if fee_receipts:
                            v.receive_fees(fee_receipts)
                        credit -= take_credit
                        sync_credit_sweeps += int(take_credit != 0)
                        sync_active_fee_claims += len(fee_ids)
                        sync_fee_receipts += fee_receipts
                        sync_collection_quote += policy.quote(st, gas_q, len(resolved)) - policy.quote(st, base_gas_q, len(resolved))
                        if timed:
                            action_meta = dict(sync_credit=take_credit, sync_fee_ids=fee_ids,
                                               sync_fee_receipts=fee_receipts,
                                               sync_collection_gas=gas_q - base_gas_q)
                        journal_paid += pay(gas_q, len(resolved), False, liability=essential)
                        journal_own += len(own_ids)
                        journal_foreign += 0 if scan_now else len(entries) - len(own_ids)
                        journal_pruned += pruned
                        terminal_work += len(resolved)
                    elif fn == "harvest":
                        ids = action[1]
                        amt = credit + sum(v.positions[i].pending_fees for i in ids)
                        if timed:
                            action_meta = dict(harvest_amount=amt, harvested_credit=credit,
                                               harvested_pending={i: v.positions[i].pending_fees for i in ids})
                        gas_q = Q["harvest"] + Q["harvested"] * len(ids)
                        funding_cap = 0  # Standalone fee collection never earns keeper compensation.
                        liability = essential and v.owed_estimate() > v.free() + v.pending_total
                        if not affordable(gas_q, funding_cap=funding_cap, cash_delta=amt, liability=liability):
                            continue
                        for i in ids:
                            v.harvest_listing(i)
                        v.receive_fees(amt)
                        credit = 0
                        pay(gas_q, funding_cap=funding_cap, liability=liability)
                    elif fn == "unlist":
                        ids = action[1]
                        cash = sum(v.positions[i].backing for i in ids)
                        gas_q = Q["unlist"] + Q["unlisted"] * len(ids)
                        if not affordable(gas_q, len(ids), essential, cash_delta=cash, liability=essential):
                            continue
                        for i in ids:
                            credit += v.positions[i].pending_fees
                            v.unlist(i)
                        pay(gas_q, len(ids), essential, liability=essential)
                    elif fn == "liquidate":
                        # Redeem idle packs to ETH at exact backing; burn each pack's Shapes (no loose
                        # Shapes exist). At most MAX_LIQUIDATE_UNITS (60) 0.01-units of packs per call.
                        packs = units = burned = 0
                        inventory = reversed(v.idle_packs)
                        cash = 0
                        while packs < action[1] and units < 60 and \
                                v.owed_estimate() > v.free() + v.pending_total + cash:
                            value = next(inventory, None)
                            if value is None:
                                break
                            u = value // policy.UNIT
                            if units + u > 60:
                                break
                            packs += 1
                            units += u
                            burned += policy.shape_count(u)
                            cash += value
                        if not packs:
                            continue
                        gas_q = Q["liquidate"] + Q["liq_pack"] * packs + Q["redeem_shape"] * burned
                        if not affordable(gas_q, packs, True, cash_delta=cash, liability=True):
                            continue
                        for _ in range(packs):
                            v.liquidate_one()
                        pay(gas_q, packs, True, liability=True)
                    elif fn == "checkpoint":
                        pool = v.processing_pool
                        flows = v.pending_total != 0 or v.locked_shares != 0
                        gas_q = Q["checkpoint"]
                        funding_cap = pool if flows else None
                        if not affordable(gas_q, 1, essential, funding_cap, cash_delta=pool, liability=essential):
                            continue
                        snap = copy.deepcopy(v.__dict__)
                        try:
                            v.checkpoint(credit)
                        except RuntimeError:
                            v.__dict__.update(snap)
                            missed_alloc += 1
                            continue
                        credit = 0
                        checkpoints += 1
                        checkpoint_done = True
                        if timed:
                            last_checkpoint_interval = absolute_now // clock.INTERVAL
                            timed_checkpoint_times.append(absolute_now)
                        pay(gas_q, 1, essential, funding_cap, liability=essential)
                    elif fn == "build":
                        # Build-and-list: each pack mints its Shapes straight into ShapePacks (no loose
                        # Shapes) and lists at once. Capital must cover pending idle funding, every
                        # pack's mint cost and every backing; a keep later triggers a fresh build.
                        units, proposals = action[1], action[2]
                        n = policy.shape_count(units)
                        price = units * policy.UNIT + n * mint_fee
                        count = len(proposals)
                        cash = count * price
                        gas_q = Q["build"] + count * (Q["build_pack"] + n * Q["build_shape"] + Q["listed"])
                        if v.idle() < v.idle_funding + cash + sum(proposals) \
                                or not affordable(gas_q, 2 * count, cash_delta=-(cash + sum(proposals))):
                            continue
                        v.build(list(range(next_id, next_id + count)), units, mint_fee, proposals)
                        next_id += count
                        pay(gas_q, 2 * count)
                    elif fn == "list":
                        if not timed:
                            if d < listing_ready_day:
                                continue
                            wait = waits[rng.integers(len(waits))] / DAY if waits is not None and len(waits) else 0.0
                            first = d + int(np.ceil(rng.random() + wait))
                            if first > d + 1:
                                listing_ready_day = first - 1
                                continue
                        proposals = []
                        cash = 0
                        for proposal in action[1]:
                            if len(proposals) >= len(v.idle_packs) or cash + proposal > v.idle():
                                break
                            proposals.append(proposal)
                            cash += proposal
                        gas_q = Q["list"] + Q["listed"] * len(proposals)
                        if not proposals or not affordable(gas_q, len(proposals), cash_delta=-cash):
                            continue
                        for proposal in proposals:
                            v.list(next_id, proposal)
                            next_id += 1
                        pay(gas_q, len(proposals))
                    else:
                        continue
                    rebased_now = v.acquisition_cursor - journal_own - journal_foreign - journal_rebased - journal_skipped
                    for _ in range(rebased_now):
                        skipped_id, _at = journal.popleft()
                        assert skipped_id is None, "unexposed proof cannot hide an own selection"
                    journal_rebased += rebased_now
                    min_free = min(min_free, v.free())
                    executed = True
                    calls += 1
                    trace_state(fn, d)
                    if timed and trace is not None:
                        trace[-1].update(action_meta)
                    if exit_all and exit_requested and fn == "checkpoint":
                        claim_available(gas + tip, d)
                        holder_finished = not v.share_balance("h") and not locked_holder() and not v.locked_shares
                    break  # The real keeper re-reads state after every successful transaction.
                if not executed:
                    break
        if timed and event_kind == "keeper":
            remaining = payload - calls
            timed_pass_limits += int(calls and not remaining)
            delay = clock.receipt_delay if calls else 0
            clock.push(now + delay + (0 if calls and remaining else clock.poll), "keeper", remaining if calls and remaining else 40)
        if calls == max_calls:
            call_limit_days += 1
        redemptions = list(sc.get("redeem", []))
        if (event_kind == "cutoff") if timed else (d == days - 1):
            operation_end_backlog = len(journal)
            operation_end_cash, operation_end_keeper_paid, operation_end_fees = v.balance, v.keeper_paid, v.fees_received
            operation_end_routine_paid, operation_end_routine_budget = routine_paid, v.routine_budget
            operation_end_idle, operation_end_funding, operation_end_loose = v.idle_value, v.idle_funding, 0
        if timed:
            redemptions = [(d, 1.0)] if event_kind == "cutoff" and exit_all else ([(d, payload)] if event_kind == "redemption" else [])
        elif exit_all:
            redemptions.append((days - 1, 1.0))
        for day, frac in redemptions:
            if day == d:
                fraction = Fraction(str(frac))
                sh = v.share_balance("h") * fraction.numerator // fraction.denominator
                if exit_all and frac == 1.0:
                    exit_requested = True
                if sh == 0:
                    if exit_requested and v.pending_total:
                        holder_cancelled += v.cancel("h")
                        holder_gas += user_gas.get("cancel", 0) * (gas + tip)
                        unknown_user_gas += int("cancel" not in user_gas)
                    continue
                st1 = charge_state(gas, len(v.positions), v.processing_pool)
                st1.gas_ceiling, st1.essential_ceiling, st1.max_tip = ceiling, essential_ceiling, tip
                st1.work_fee, st1.essential_cap = work_fee, values["essentialCapWei"]
                ck = policy.request_charge(st1)
                unwind = (sh * v.last_nav // v.total_shares) * policy.unwind_charge(st1) // policy.position_value(st1)
                v.request_redeem("h", sh, ck, unwind)
                trace_state("request-redeem", d)
                paid_in += ck + unwind
                holder_gas += user_gas.get("request_redeem", 0) * (gas + tip)
                unknown_user_gas += int(exit_all and "request_redeem" not in user_gas)
        if exit_all and exit_requested:
            claim_available(gas + tip, d)
            if (not v.share_balance("h") and not locked_holder()
                    and not v.claimable.get("h", 0) and not v.pending_total and not journal and not v.receipts
                    and not v.locked_shares):
                break

    end_nav = economic_nav(v, credit)
    unexposed = not v.positions and not v.receipts and not v.active_count and not v.active_backing and not v.allocated_value
    end_blocked = bool((journal and not unexposed) or v.receipts or (v.allocation_head < len(v.allocation_queue) and
                       (v.allocation_queue[v.allocation_head] not in v.positions or
                        v.positions[v.allocation_queue[v.allocation_head]].state != ALLOCATED))
                       or v.allocated_value * 10_000 > end_nav * v.allocated_bound_bps)
    assert len(journal) == v.completed_prefix - v.acquisition_cursor
    assert journal_own + journal_foreign + journal_rebased + journal_skipped == v.acquisition_cursor
    supply = v.total_shares
    d_ = v.pending.get("h", [0, 0])
    unpriced = d_[0] if d_[1] >= v.epoch else 0
    # With only this holder and no locked exit, cancelling the unpriced deposit also refunds
    # its checkpoint charge. No work was performed, so do not invent an entry loss.
    unpriced_refund = unpriced + (v.processing_pool if unpriced and not v.locked_shares else 0)
    claimed = v.claimable.get("h", 0) + v.redemption_reserve + unpriced_refund
    holder = v.share_balance("h") * end_nav // supply + claimed
    locked_val = v.locked_shares * end_nav // supply
    value_end = (holder + locked_val + holder_claimed + holder_cancelled + holder_keeper_pay - holder_gas
                 if exit_all else holder + locked_val - self_serve_cost)
    ret = value_end / paid_in - 1
    deployed = sum(p.backing + p.value for p in v.positions.values() if p.status == ACTIVE)
    remaining_locked = locked_holder()
    exit_complete = (exit_requested and not v.share_balance("h") and not remaining_locked
                     and not v.claimable.get("h", 0) and not unpriced and not journal and not v.receipts
                     and not v.locked_shares and not end_blocked)
    physical = (v.balance + sum(v.idle_packs) + sum(v.recovery_packs)
                + sum(p.value for p in v.positions.values() if p.status in (ACTIVE, ALLOCATED) or p.pack_owned)
                + sum(p.backing for p in v.positions.values() if p.status in (ACTIVE, ALLOCATED)))
    unreconciled_keep = sum(p.value for p in v.positions.values() if p.status == SETTLED and not p.pack_owned)
    ledger_gap = (v.seed + paid_in + v.fees_received - v.keeper_paid - v.mint_fees - v.backing_lost
                  - v.settlement_fees - unreconciled_keep - holder_claimed - holder_cancelled - physical)
    assert ledger_gap == 0, ("operating asset ledger", ledger_gap)
    assert routine_paid + essential_paid + request_paid == v.keeper_paid
    if timed:
        assert accrued == v.fees_received + credit + sum(p.pending_fees for p in v.positions.values()), "external fee conservation"
    if exit_complete:
        assert not v.locked_shares and not v.receipts
        value_end = holder_claimed + holder_cancelled + holder_keeper_pay - holder_gas
        ret = value_end / paid_in - 1
    elapsed = now / DAY if timed else d + 1
    result = dict(ret=ret * 365 / (elapsed if exit_all else days), keeper=v.keeper_paid / deposit, mint=v.mint_fees / deposit,
                fees=v.fees_received / deposit, lost=v.backing_lost / deposit, util=deployed / max(1, end_nav),
                positions=len(v.positions), pos_mean=float(np.mean(open_days)), pos_max=max(open_days, default=0),
                checkpoints=checkpoints, journal_paid=journal_paid / deposit, journal_backlog=len(journal),
                journal_own=journal_own, journal_foreign=journal_foreign, journal_pruned=journal_pruned, journal_rebased=journal_rebased,
                journal_scans=journal_scans, journal_scanned=journal_scanned, journal_skipped=journal_skipped,
                avg_deployed_wei=deployed_int // max(1, days * DAY) if timed else 0,
                avg_book_wei=book_int // max(1, days * DAY) if timed else 0,
                gas_wait_seconds=gas_wait_seconds, deferred_terminal_seconds=deferred_seconds,
                settlement_wait_seconds=settlement_wait_seconds,
                terminal_work=terminal_work, pending_receipts=len(v.receipts), end_pricing_blocked=end_blocked,
                skipped_unfunded=skipped_funding, call_limit_days=call_limit_days,
                self_serve_gas_proxy=(holder_maintenance_gas - holder_keeper_pay if exit_all else self_serve_cost) / deposit,
                k_eff=accrued / selected_backing if selected_backing else 0.0, missed_alloc=missed_alloc,
                keeper_unpaid=(holder_maintenance_gas - holder_keeper_pay if exit_all else self_serve_cost) / deposit,
                issued_entries=v.completed_prefix, processed_entries=v.acquisition_cursor,
                routine_budget_wei=v.routine_budget, essential_budget_wei=v.essential_budget,
                economic_nav_wei=end_nav, free_wei=v.free(), keeper_paid_wei=v.keeper_paid,
                principal_deposit_wei=deposit, holder_paid_in_wei=paid_in,
                holder_end_value_before_external_gas_wei=(0 if exit_complete else holder + locked_val)
                    + holder_claimed + holder_cancelled + holder_keeper_pay,
                min_free_wei=min_free, fees_received_wei=v.fees_received,
                mint_fees_wei=v.mint_fees, backing_lost_wei=v.backing_lost,
                journal_paid_wei=journal_paid, elapsed_days=elapsed,
                external_exit_gas_proxy_wei=holder_maintenance_gas - holder_keeper_pay if exit_all else self_serve_cost,
                vol=float(np.mean(vol_hist[:d + 1] if timed else vol_hist)), operating_days=days, exit_requested=exit_requested,
                exit_complete=exit_complete, exit_days_elapsed=max(0, elapsed - days),
                holder_claimed_wei=holder_claimed, holder_cancelled_wei=holder_cancelled,
                holder_keeper_pay_wei=holder_keeper_pay, holder_gas_proxy_cost_wei=holder_gas,
                holder_maintenance_gas_proxy_wei=holder_maintenance_gas,
                unknown_user_gas_calls=unknown_user_gas, holder_remaining_shares=v.share_balance("h"),
                holder_remaining_locked_shares=remaining_locked, holder_remaining_claimable_wei=v.claimable.get("h", 0),
                holder_net_realized_wei=holder_claimed + holder_cancelled + holder_keeper_pay - holder_gas - paid_in,
                routine_keeper_paid_wei=routine_paid, essential_keeper_paid_wei=essential_paid,
                request_funded_keeper_paid_wei=request_paid, routine_unfunded_attempts=routine_unfunded,
                unpaid_routine_calls=unpaid_routine_calls, zero_quote_holder_sync_calls=zero_quote_sync_calls,
                uninterrupted_routine_funding=routine_unfunded == 0,
                fully_paid_routine=routine_unfunded == 0 and unpaid_routine_calls == 0,
                operation_end_backlog=operation_end_backlog,
                operation_end_cash_wei=operation_end_cash, operation_end_keeper_paid_wei=operation_end_keeper_paid,
                operation_end_fees_received_wei=operation_end_fees, holder_rescue_sync_enabled=rescue_sync,
                operating_active_days=operating_active_days, operation_end_idle_value_wei=operation_end_idle,
                operation_end_idle_funding_wei=operation_end_funding, operation_end_loose_value_wei=operation_end_loose,
                exit_stall_journal=bool(journal and not unexposed), exit_stall_receipts=bool(v.receipts),
                exit_stall_pending_deposit=bool(unpriced), exit_stall_locked=bool(v.locked_shares),
                exit_stall_free_cash=bool(not exit_complete and last_cash_shortfall),
                exit_stall_routine_budget=bool(not exit_complete and last_permission_shortfall),
                last_unfunded_offer_wei=last_unfunded_offer, last_unfunded_cash_shortfall_wei=last_cash_shortfall,
                last_unfunded_permission_shortfall_wei=last_permission_shortfall,
                end_unreconciled_returned_value_wei=sum(p.value for p in v.positions.values() if p.status == SETTLED and p.pack_owned),
                end_allocated_book_value_wei=v.allocated_value,
                creator_mint_fees_wei=v.mint_fees, settlement_fees_wei=v.settlement_fees,
                physical_assets_wei=physical, vault_cash_wei=v.balance, holder_liability_wei=v.redemption_reserve + v.distribution_reserve + v.claimable_total,
                ledger_gap_wei=ledger_gap, routine_initial_cap_wei=values["routineCapWei"],
                routine_refill_per_day_wei=values["routineRatePerDayWei"],
                routine_period_permission_upper_wei=values["routineCapWei"] + now * values["routineRatePerDayWei"] // DAY,
                timed_mode=timed, elapsed_seconds=now if timed else (d + 1) * DAY,
                expired_backing_reclaims=expired_backing, expired_nft_reclaims=expired_nft,
                purchaser_responses=purchaser_returns, late_purchaser_responses=late_purchaser_returns,
                timed_checkpoint_count=len(timed_checkpoint_times), timed_pass_limit_hits=timed_pass_limits)
    result.update(expected_own_selections=expected_selections, own_selections=selected,
                  sync_credit_sweeps=sync_credit_sweeps, sync_active_fee_claims=sync_active_fee_claims,
                  sync_fee_receipts_wei=sync_fee_receipts, sync_collection_quote_wei=sync_collection_quote,
                  operation_end_routine_paid_wei=operation_end_routine_paid,
                  operation_end_routine_budget_wei=operation_end_routine_budget,
                  operating_budget_marks=operating_budget_marks)
    if timed:
        result.update(external_fees_generated_wei=accrued, unharvested_fee_credit_wei=credit,
                      unharvested_listing_fees_wei=sum(p.pending_fees for p in v.positions.values()))
    for name in op_names:
        result[f"keeper_paid_{name}_wei"] = op_paid[name]
        result[f"keeper_calls_{name}"] = op_calls[name]
        result[f"holder_calls_{name}"] = holder_calls[name]
    return result


def self_check():
    """Focused model regressions using the caller's recorded pool and wait inputs."""
    rows = {}
    rows["zero"] = run(Scenario(volume=const(0), gwei=0.15), 10, 8, days=20)
    assert rows["zero"]["mint"] > 0 and rows["zero"]["fees"] == 0
    rows["keeps"] = run(Scenario(volume=const(609), gwei=0.15, keep=1.0), 30, 8, days=20)
    assert rows["keeps"]["journal_own"] > 0 and rows["keeps"]["terminal_work"] > 0
    assert rows["keeps"]["pending_receipts"] == 0
    rows["at_bid_ceiling"] = run(Scenario(volume=const(100), gwei=0.45), 10, 8, days=20)
    assert rows["at_bid_ceiling"]["positions"] > 0
    rows["above_bid_ceiling"] = run(Scenario(volume=const(100), gwei=0.5), 10, 8, days=20)
    assert rows["above_bid_ceiling"]["positions"] == 0
    assert rows["above_bid_ceiling"]["checkpoints"] == 0
    assert rows["above_bid_ceiling"]["ret"] == 0  # unpriced deposit and charge remain refundable
    values = json.loads((ROOT.parent / "deploy/mainnet.json").read_text())
    values.update(routineCapWei=0, routineRatePerDayWei=0)
    rows["empty_budget"] = run(Scenario(volume=const(609), gwei=0.15), 10, 8, days=10, values=values)
    assert rows["empty_budget"]["keeper_paid_wei"] == policy.checkpoint_cost(charge_state(150_000_000, 0))
    assert rows["empty_budget"]["checkpoints"] == 1
    # Later foreign history can wait until the next real checkpoint/admission without
    # requiring standalone unpaid calls or blocking a cash-only vault's pricing.
    assert rows["empty_budget"]["journal_rebased"] > 0
    assert not rows["empty_budget"]["end_pricing_blocked"]
    assert rows["empty_budget"]["positions"] == 0
    values.update(routineCapWei=5 * 10**15)
    rows["depleted_budget"] = run(Scenario(volume=const(100), gwei=0.15), 10, 8, days=20, values=values)
    assert rows["depleted_budget"]["checkpoints"] == 1
    assert rows["depleted_budget"]["journal_backlog"] > 0
    assert rows["depleted_budget"]["keeper_paid_wei"] <= 5 * 10**15 + policy.checkpoint_cost(charge_state(150_000_000, 0))
    rows["partial_redemption"] = run(Scenario(volume=const(15), gwei=0.15, redeem=[(10, 0.5)]),
                                     30, 8, days=20)
    assert rows["partial_redemption"]["checkpoints"] == 2
    assert rows["partial_redemption"]["external_exit_gas_proxy_wei"] > 0
    for row in rows.values():
        assert row["processed_entries"] == row["journal_own"] + row["journal_foreign"] + row["journal_rebased"]
        assert row["issued_entries"] == row["processed_entries"] + row["journal_backlog"]
    return rows


def wilson(k, n, z=1.96):
    """95% interval for a proportion k / n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    c = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    m = (p + z * z / (2 * n)) / (1 + z * z / n)
    return (max(0.0, m - c), min(1.0, m + c))


def summarize(sc, n, runs, days=365):
    rs = [run(sc, n, seed, days=days) for seed in range(runs)]
    r = np.array([x["ret"] for x in rs])
    mean = {k: float(np.mean([x[k] for x in rs])) for k in rs[0]}
    k = int(np.sum(r < 0))
    lo, hi = wilson(k, len(r))
    return dict(mean=float(r.mean()), se=float(r.std() / np.sqrt(len(r))), p5=float(np.percentile(r, 5)),
                p50=float(np.median(r)), p95=float(np.percentile(r, 95)), ploss=k / len(r), ploss_lo=lo, ploss_hi=hi,
                runs=len(r), worst=float(r.min()), **{f"m_{k_}": v for k_, v in mean.items()})


# ---------------------------------------------------------------- scenarios


def boot(series):
    s = np.asarray(series, float)
    return lambda d, rng: float(rng.choice(s))


def const(x):
    return lambda d, rng: x


def decline(start, end, days=365):
    return lambda d, rng: start * (end / start) ** (d / days)


def stop_after(series, day):
    b = boot(series)
    return lambda d, rng: b(d, rng) if d < day else 0.0


def pct(x):
    return f"{100 * x:+.1f}%"


def successful_daily():
    """Acquisitions per UTC day that reached a selection (fees were distributed). Requests that
    were refunded or expired distributed nothing (sim/backtest_audit.py)."""
    import backtest_audit
    sel = backtest_audit.load()["sel"]
    days = (sel[:, 0] // DAY).astype(int)
    return np.bincount(days - days.min()).astype(float), int(days.min())


def ci(s):
    return f"{100 * s['ploss']:.0f}% [{100 * s['ploss_lo']:.0f}-{100 * s['ploss_hi']:.0f}]"


def main():
    global POOL, STAGING, REFUNDS_PER_SELECTION
    OUT.mkdir(exist_ok=True)
    POOL = pool_snapshot()
    STAGING = staging_delays(30)
    db = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    end, end_block = db.execute("SELECT max(ts),max(block) FROM logs").fetchone()
    statuses = [json.loads(a)["status"] for (a,) in db.execute(
        "SELECT args FROM logs WHERE event='AcquisitionProcessed' AND ts>=?", (end - 30 * DAY,))]
    successes = sum(int(status) == 2 for status in statuses)
    REFUNDS_PER_SELECTION = (len(statuses) - successes) / successes if successes else 0.0
    db.close()
    if len(sys.argv) > 1 and sys.argv[1] == "--self-check":
        results = self_check()
        print(json.dumps(dict(block=end_block, end_timestamp=end, pool_listings=len(POOL),
                              completed30d=len(statuses), successful30d=successes,
                              context="model scenarios; gwei is basefee, bid includes maxTip; no return gate claim",
                              results=results), indent=1))
        print(f"PASS: {len(results)} focused forward model scenarios")
        return
    vol, first = successful_daily()
    last30, last14, last7 = vol[-30:], vol[-14:], vol[-7:]
    spike = int(np.argmax(last30))
    last30_ex = np.delete(last30, spike)
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    md = ["# PackVault economics: gate, expectation, forward simulation\n",
          "Generated by `python3 sim/forward.py " + str(runs) + "`. Data: `sim/data/fwa.sqlite`, FWA, rewards and oracle "
          f"events through block {end_block:,}, timestamp {end} (`python3 sim/ingest.py`); pool snapshot at the end of that history; "
          "volume = acquisitions per UTC day that reached a selection (refunded requests distributed no fees). "
          "The historical replay and its reconciliation with these numbers are in `sim/out/backtest_audit.md`.\n",
          f"Pool: {len(POOL):,} listings, harmonic backing {len(POOL) / np.sum(1 / POOL):.4f} ETH. Successful acquisitions "
          f"per day: last 7 d {last7.mean():.0f}, last 14 d {last14.mean():.0f}, last 30 d {last30.mean():.0f} "
          f"({last30_ex.mean():.0f} without the {last30.max():.0f} of Oct 31), 30-day median {np.median(last30):.0f}.",
          "Forward fixture: 3-unit packs (P = 0.03 ETH), with backing proposed from the current policy; the research pack size does not change production sizing rules. The closed form uses fixed B = 0.0363 ETH as a theoretical comparison. Keeper pay V1 uses quoted gas + work fee, no premium; maxTip 0.05 gwei; "
          f"gas ceiling {CEILING} gwei; scenario gwei is basefee and actual bid is basefee + maxTip. FWA tokens have zero value; purchasers take the bid unless stated. Gas quotes require candidate calibration; this report alone does not validate the return or launch gate.\n",
          f"FWA staging (audit E7): the keeper lists only when FWA's queue is drained, so a relist never stages; each "
          f"listing first waits the queue's historical drain time, sampled from {len(STAGING)} relist moments in the last "
          f"30 days ({100 * np.mean(STAGING > 0):.1f}% found the queue busy; waits up to {STAGING.max() / 3600:.1f} h). "
          f"The forward simulation assumes this; the closed form does not.\n"]

    # 1. The formal gate, as approved: trailing 30-day volume, tokens at zero.
    md += ["## 1. Formal economic gate (owner's definition)\n",
           f"Gate: 10%/yr net of gas at trailing-30-day volume, tokens at zero, at the {CEILING} gwei gas ceiling (D42); "
           "bid outcome positive at the ceiling; a usable exit window each day. The ceiling row uses 0.45 gwei basefee plus the 0.05 gwei tip. The closed form omits global journal overhead and is a theoretical comparison. 0.15 gwei is basefee at the pinned block. "
           "Above the ceiling the keeper waits; calls are still accepted, paid at the ceiling price (D51).\n",
           "| basefee / bid | net per bid cycle (mETH) | closed form, 100 positions | forward sim mean, 100 positions | 10% comparison |",
           "|---|---|---|---|---|"]
    gate = {}
    for g in (0.15, max(0, CEILING - 0.05)):
        x = expectation(100, last30.mean(), g)
        sm = summarize(Scenario(volume=boot(last30), gwei=g), 100, runs)
        gate[min(g + 0.05, CEILING)] = (x, sm)
        comparison = (f"not established: {100 * sm['m_end_pricing_blocked']:.0f}% end with pricing blocked"
                      if sm["m_end_pricing_blocked"] else "above threshold" if sm["mean"] >= 0.10 else "below threshold")
        md.append(f"| {g:.2f} / {g + 0.05:.2f} gwei | {x['net_meth']:+.3f} | {pct(x['apr'])} | {pct(sm['mean'])} (p5 {pct(sm['p5'])}) | "
                  f"{comparison}; candidate validation separate |")
        print(md[-1], flush=True)
    md.append(f"\nBid outcome at the {CEILING} gwei ceiling: {gate[CEILING][0]['net_meth']:+.3f} mETH per cycle. New packs "
              "must repay their build from one bid cycle under the current policy; the closed form assumes positions already "
              "exist. Exit windows: 59 of the last 60 blackouts had a drained queue (Phase 0.2).\n")

    md += ["## 2. Expectation (closed form, per position, no variance)\n",
           "| volume/day | gas gwei | positions | cycle days | net per cycle mETH | APR | selection share |",
           "|---|---|---|---|---|---|---|"]
    for v_ in (15, last7.mean(), last30_ex.mean(), last30.mean()):
        for g in (0.15, CEILING, 1.0):
            for n in (30, 300):
                x = expectation(n, v_, g)
                md.append(f"| {v_:.0f} | {g} | {n} | {x['cycle_days']:.1f} | {x['net_meth']:+.3f} | {pct(x['apr'])} | "
                          f"{100 * x['share']:.1f}% |")
    gross = 0.0363 * (k_of() - 1)
    fee = WORK_FEE / E
    build_g = policy.Q["build_pack"] + policy.shape_count(BUILD_UNITS) * policy.Q["build_shape"] + policy.Q["listed"]
    mint_share = policy.shape_count(BUILD_UNITS) * MINT_FEE / E  # mints for one REF_UNITS pack
    md.append(f"\nBreak-even quoted price for a bid cycle (D56: quoted gas {policy.CYCLE_GAS:,}, including own journal, selection, terminal, cleanup, relist and harvest components, plus 2 work fees; V1 pays no markup): {(gross - 2 * fee) / policy.CYCLE_GAS * 1e9:.2f} gwei. "
              f"New packs (build {build_g:,} quoted gas, mint fee share {mint_share} ETH and two additional work fees): "
              f"below {(gross - mint_share - 4 * fee) / (policy.CYCLE_GAS + build_g) * 1e9:.2f} gwei quoted price "
              "(basefee + 0.05 gwei tip).\n")

    def g_path(base, high, start, stop=10**9):
        return lambda d: high if start <= d < stop else base

    def cheap_windows(base, cheap, every):
        return lambda d: cheap if d % every == 0 else base

    scen = [
        ("trailing 30 d (gate window)", dict(volume=boot(last30), gwei=0.15), (30, 100, 300)),
        ("trailing 30 d without Oct 31", dict(volume=boot(last30_ex), gwei=0.15), (100,)),
        ("last 14 d", dict(volume=boot(last14), gwei=0.15), (30, 100, 300)),
        ("last 7 d", dict(volume=boot(last7), gwei=0.15), (100,)),
        ("15/day", dict(volume=const(15), gwei=0.15), (100,)),
        ("decline 97 -> 10/day over the year", dict(volume=decline(97, 10), gwei=0.15), (100,)),
        ("inactive after 60 days", dict(volume=stop_after(last14, 60), gwei=0.15), (100,)),
        ("last 14 d at 0.5 gwei bid ceiling (0.45 basefee)", dict(volume=boot(last14), gwei=0.45), (100,)),
        ("enter at 0.15 gwei, 0.4 gwei from day 30 on", dict(volume=boot(last14), gwei=g_path(0.15, 0.4, 30)), (100,)),
        ("enter at 0.15 gwei, 1.0 gwei (above ceiling) from day 30 on", dict(volume=boot(last14), gwei=g_path(0.15, 1.0, 30)), (100,)),
        ("enter at 0.15 gwei, 2.0 gwei (above ceiling) days 30-120", dict(volume=boot(last14), gwei=g_path(0.15, 2.0, 30, 120)), (100,)),
        ("1.2 gwei with a 0.1 gwei day every 7", dict(volume=boot(last14), gwei=cheap_windows(1.2, 0.1, 7)), (100,)),
        ("50% redemption at day 120 during 7 congested days", dict(volume=boot(last14), gwei=0.15, redeem=[(120, 0.5)],
                                                                    congested=lambda d: 120 <= d < 127), (100,)),
        ("50% redemption at day 120", dict(volume=boot(last14), gwei=0.15, redeem=[(120, 0.5)]), (100,)),
        ("crown share to 5% at day 90", dict(volume=boot(last14), gwei=0.15, changes=[(90, "crown", 0.05)]), (100,)),
        ("ask cut 0.033 -> 0.0275 at day 90", dict(volume=boot(last14), gwei=0.15, changes=[(90, "ask", 0.0275)]), (100,)),
        ("11% of purchasers keep", dict(volume=boot(last14), gwei=0.15, keep=0.11), (100,)),
        ("demand elasticity 1", dict(volume=boot(last14), gwei=0.15, elasticity=1.0), (100,)),
        ("pool shrinks to half", dict(volume=boot(last14), gwei=0.15, pool_scale=0.5), (100,)),
        ("half of checkpoints missed", dict(volume=boot(last14), gwei=0.15, checkpoint_miss=0.5), (100,)),
    ]
    md += ["## 3. Forward simulation (one year, daily integer vault model + live keeper policy)\n",
           f"{runs} runs per row. One year, so the raw return is the annual return. Every expense is included: keeper gas "
           "pay, mint fees, FWA settlement fees, backing lost to purchasers. The simulation holds real cash: a relist "
           "needs backing the vault has, a pack waits for its purchaser's settlement, and redemptions are paid before "
           "anything is redeployed. Positions: the initial target / mean held / most held; capital and transaction "
           "work limits bound deployment, with no total position cap. Global journal processing includes foreign "
           "and refunded records, at the historical completed/refunded ratio. Routine calls wait when budget or free cash cannot fund their full quote. "
           "Self-serve exits use a separate quoted-gas cost proxy paid by the withdrawing holder, outside vault NAV. "
           "Selection timing is a daily approximation. End values use an independent mark when pricing is blocked; "
           "the reported blocked flag must not be treated as a completed redemption. Calls are capped at512 per modeled day, "
           "with any remaining journal retained. P(loss) with a 95% interval.\n",
           "| scenario | positions (target/mean/max) | mean (± s.e.) | p5 | median | p95 | worst run | P(loss) | fees/dep | "
           "lost/dep | keeper/dep | mint/dep | pricing blocked | journal backlog |", "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    results = {}
    for name, sc, sizes in scen:
        for n in sizes:
            sm = summarize(Scenario(sc), n, runs)
            results[f"{name}|{n}"] = sm
            md.append(f"| {name} | {n}/{sm['m_pos_mean']:.0f}/{sm['m_pos_max']:.0f} | {pct(sm['mean'])} ± {100 * sm['se']:.1f} | "
                      f"{pct(sm['p5'])} | {pct(sm['p50'])} | {pct(sm['p95'])} | {pct(sm['worst'])} | {ci(sm)} | "
                      f"{100 * sm['m_fees']:.0f}% | {100 * sm['m_lost']:.0f}% | {100 * sm['m_keeper']:.2f}% | "
                      f"{100 * sm['m_mint']:.2f}% | {100 * sm['m_end_pricing_blocked']:.0f}% | {sm['m_journal_backlog']:.0f} |")
            print(md[-1], flush=True)

    md += ["\n## 4. Deployment slowdown (keeper stops building new packs while 7-day volume is low)\n",
           "| scenario | slowdown below | mean | p5 | P(loss) | mint/dep | keeper/dep |", "|---|---|---|---|---|---|---|"]
    for name, sc in (("decline 97 -> 10/day", dict(volume=decline(97, 10), gwei=0.15)),
                     ("inactive after 60 days", dict(volume=stop_after(last14, 60), gwei=0.15))):
        for sl in (0, 30, 60):
            sm = summarize(Scenario({**sc, "slowdown": sl}), 100, runs)
            md.append(f"| {name} | {sl}/day | {pct(sm['mean'])} | {pct(sm['p5'])} | {ci(sm)} | "
                      f"{100 * sm['m_mint']:.2f}% | {100 * sm['m_keeper']:.2f}% |")
            print(md[-1], flush=True)

    md += ["\n## 5. FWA tokens (burned, never sold; D43)\n",
           "Holders get no token value by design: the vault claims FWA token rewards and burns them, at the operator's gas cost (`burnTokens`, unpaid). Measured in `keeper/rehearse_canary.py`: one real buyback paid the canary's 28 listings 4.87 FWA tokens (a pool sale would have realized about 8.2e12 wei), all claimed and burned.\n"]
    (OUT / "forward.md").write_text("\n".join(md) + "\n")
    json.dump(results, open(OUT / "forward.json", "w"), indent=1)
    print("wrote sim/out/forward.md")


if __name__ == "__main__":
    main()
