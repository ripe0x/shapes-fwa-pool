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
import hashlib
from itertools import islice
from fractions import Fraction
from collections import deque
from types import SimpleNamespace
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "keeper"))
import policy  # noqa: E402
from config import gas_schedule
import bisect  # noqa: E402
from vault import ACTIVE, ALLOCATED, SETTLED, WITHDRAWN, OWED, Vault  # noqa: E402

DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
E = 10**18
GWEI = 10**9
P = 3 * 10**16  # three paid 0.01 ETH primary mints
BUILD_UNITS = 3
SUR, CUT, S_FEE, BID_RATE = 0.05, 0.01, 0.01, 0.90
ASK, PREMIUM = 0.033, 0.10
MINT_FEE = 10**15
# Backing follows the account ratio. Purchaser choices are separate explicit scenarios.
KEEP_DEFAULT = 0.0  # no favorable purchaser behavior assumed
POOL = None
MARK_DAYS = 30  # operating marks interval (diagnostics may lower it)
DAY = 86_400
WORK_FEE = 2 * 10**13  # wei per unit of work, canary value (D55)
CEILING = 0.5  # gwei: canary gasCeiling; above it the keeper waits (D45, D51)
ESSENTIAL_CEILING = 2.0  # gwei: canary essentialCeiling (redemption and wind-down work)


# ---------------------------------------------------------------- history


def archive_revision():
    with sqlite3.connect(f'file:{DB}?mode=ro', uri=True) as db:
        return int(db.execute('SELECT max(block) FROM logs').fetchone()[0])


def history():
    """Per-acquisition arrays from the event log: time, fee, total weight (sum of 1/B in 1/ETH),
    active listing count, protocol cut and crown share in force."""
    cache = OUT / f"acq_history-{archive_revision()}.npz"
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
    cache = OUT / f"staging_delays_{days_back}-{archive_revision()}.npy"
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


def expectation(n, volume, gwei, B=None, crown=0.001, premium=0.0):
    st = configured_state(int(gwei * GWEI))
    B = policy.position_value(st) / E - st.build_units * policy.UNIT / E if B is None else B
    pool = POOL if POOL is not None else pool_snapshot()
    W = np.sum(1 / pool) + n / B
    cycles = 365 * volume * (1 / B) / W
    # A bid cycle's keeper pay as the vault quotes it (D56): quoted gas at basefee + 0.05 gwei tip,
    # capped at the ceiling, with the configured routine markup and verified service fees.
    gas = policy.quote(st, policy.cycle_gas(st), 2) / E
    net = B * (k_of(crown) - 1) - gas
    capital = n * (B + P / E)
    return dict(cycle_days=365 / cycles, net_meth=net * 1e3, apr=cycles * net / (B + P / E),
                share=(n / B) / W, capital=capital)


# ---------------------------------------------------------------- 2. backtest


def backtest(h, n, gwei, t0, t1, B=None, runs=400, seed=1, premium=0.0):
    """Vault of n listings at backing B inside the real history between t0 and t1 (unix s).
    Positions are relisted the same day after a bid outcome (cycle gas charged per selection)."""
    st = configured_state(int(gwei * GWEI))
    B = policy.position_value(st) / E - st.build_units * policy.UNIT / E if B is None else B
    m = (h["ts"] >= t0) & (h["ts"] < t1)
    fee, w, N, cut, crown = h["fee"][m], h["w"][m], h["n"][m], h["cut"][m] / 1e4, h["crown"][m] / 1e4
    if len(fee) == 0:
        return None
    k_hist = (1 + SUR) * (1 - cut) * (1 - crown)
    H, H2 = N / w, (N + n) / (w + n / B)
    fee2 = fee * H2 / H  # the vault's listings move the harmonic backing, so the fee
    vault_fees = fee2 * (1 - cut) * (1 - crown) * n / (N + n)
    p_sel = (n / B) / (w + n / B)
    cycle_cost = B + policy.quote(st, policy.cycle_gas(st), 2) / E
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


def configured_state(base_fee, values=None):
    values = values or json.loads((ROOT.parent / 'deploy/mainnet.json').read_text())
    s = charge_state(base_fee, 0)
    s.gas_schedule = gas_schedule(values)
    if 'renewalMode' in values or 'renewalFloatCount' in values:
        raise ValueError('historical Fresh settings require their pinned revision; active strategy is reuse-only')
    s.backing_ratio_bps = values['backingRatioBps']
    s.gas_ceiling, s.essential_ceiling = values['gasCeilingWei'], values['essentialCeilingWei']
    s.max_tip, s.work_fee, s.markup_bps = values['maxTipWei'], values['workFeeWei'], values['payMarkupBps']
    s.pack_units_mask, s.accepted_mint_fee = values['packUnitsMask'], values['acceptedMintFeeWei']
    s.build_units = next((u for u in range(3,31) if s.pack_units_mask >> u & 1), 3)
    s.routine_budget, s.essential_budget, s.essential_cap = values['routineCapWei'], values['essentialCapWei'], values['essentialCapWei']
    s.share_bps = values['keeperShareBps']
    return s


def backing_proposals(target, positions, minimum=0, maximum=2**256 - 1, count=policy.MAX_BATCH["list"]):
    """Bounded offchain identifier proposals, using current outstanding identifiers."""
    if not target:
        return []
    return list(_proposals(target, frozenset(p.backing for p in positions.values() if p.state != OWED), minimum, maximum, count))


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
        self.request_draws = None
        if sc.get('request_randomness'):
            acquisitions = [(at, payload) for at, _, serial, kind, payload in sorted(self.events) if kind == 'acquisition']
            self.request_events_sha256 = hashlib.sha256(json.dumps(acquisitions,separators=(',',':')).encode()).hexdigest()
            # Independent pre-generated domains keep conditional account choices out of later requests.
            self.request_draws = np.column_stack([np.random.default_rng(np.random.SeedSequence([seed,domain])).random(len(acquisitions))
                                                  for domain in (0x53454C,0x525350,0x4B4545)])

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
    if not v.positions and not v.receipts:
        return [], owed_after
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


RECEIPT_WORK_LIMITS = dict(create=1,setExiting=1,withdraw=1,processAcquisitions=16,
    build=4,list=8,sync=16,recover_sync=16,unlist=16,liquidate=16,harvest=16)


def receipt_gas(curves, operation, work_count, work_gas=0, *, estimate=False, legacy_floor=0):
    if not curves:
        return max(work_gas, legacy_floor)
    if operation not in curves or type(work_count) is not int or not 1<=work_count<=RECEIPT_WORK_LIMITS.get(operation,0):
        raise ValueError(('unsupported receipt work count/operation',operation,work_count))
    curve=curves[operation]
    base='single_estimate_gas' if estimate else 'single_billed_gas'
    slope='estimate_per_extra_work' if estimate else 'billed_per_extra_work'
    if type(curve.get(base)) is not int or curve[base]<=0 or type(curve.get(slope)) is not int or curve[slope]<0:
        raise ValueError(('invalid receipt gas curve',operation))
    return curve[base]+curve[slope]*(work_count-1)




def metered_work_gas(curves, meters, operation, work_count=1, max_work=None):
    if max_work is not None and (operation not in max_work or work_count>max_work[operation]):
        raise ValueError('metered batch exceeds actual receipt support: '+operation)
    curve=curves.get(operation,{})
    if 'single_meter_gas' in curve and 'meter_per_extra_work' in curve:
        receipt_gas(curves,operation,work_count)  # enforce verified operation/count bounds
        base,slope=curve['single_meter_gas'],curve['meter_per_extra_work']
        if type(base) is not int or base<0 or type(slope) is not int or slope<0:
            raise ValueError('invalid measured work-span curve: '+operation)
        return base+slope*(work_count-1)
    if work_count!=1 or type(meters.get(operation)) is not int or meters[operation]<0:
        raise ValueError('missing independently measured work span: '+operation)
    return meters[operation]


def sync_context_gas(contexts, allowance, units, work_count=1):
    key=f'{allowance}:{units}:{work_count}'
    if key not in contexts:
        raise ValueError('unmeasured sync context: '+key+f' count={work_count}')
    context=contexts[key]
    if any(type(context.get(name)) is not int or context[name]<=0
           for name in ('billed_gas','estimate_gas')):
        raise ValueError('invalid sync receipt context: '+key)
    return context


def receipt_acceptance_gas(curves, operation, work_count, work_gas=0, legacy_floor=0):
    return max(receipt_gas(curves,operation,work_count,work_gas,estimate=True,legacy_floor=legacy_floor),
               receipt_gas(curves,operation,work_count,work_gas,legacy_floor=legacy_floor))


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
        others = POOL if POOL is not None else pool_snapshot()
        if sc.get("pool_scale", 1.0) != 1.0:
            others = rng.choice(POOL, int(len(POOL) * sc["pool_scale"]))
        W_o = float(np.sum(1 / others))
    g_of = sc.get("gwei", 0.15)  # scenario basefee; the actual bid also includes maxTip
    manager = bool(sc.get('manager', False))
    values = values or json.loads((ROOT.parent / ('deploy/manager.json' if manager else 'deploy/mainnet.json')).read_text())
    ceiling, tip = values["gasCeilingWei"], values["maxTipWei"]
    essential_ceiling = values["essentialCeilingWei"]
    work_fee, mint_fee = values["workFeeWei"], int(sc.get("mint_fee_wei", MINT_FEE))
    schedule = gas_schedule(values)
    cached_economics = sc.get('cache_economics', True)
    from keeper import proposal_limits as canonical_proposal_limits
    limits_cache, edge_cache, construction_cache = {}, {}, {}
    def proposal_limits(state,value,settlement,discount,cap,build=False,units=policy.REF_UNITS,retirement_shapes=None):
        key=(state.k,state.base_fee,value,settlement,discount,cap,build,units,retirement_shapes)
        if not cached_economics or key not in limits_cache:
            result=canonical_proposal_limits(state,value,settlement,discount,cap,build,units,retirement_shapes)
            if not cached_economics:return result
            limits_cache[key]=result
        return limits_cache[key]
    def edge_for(units,newly_built=True,retirement_shapes=None):
        limit=None if sc.get('exempt',True) else cap
        key=(k,gas,limit,units,newly_built,retirement_shapes)
        if not cached_economics or key not in edge_cache:
            result=policy.edge_backing(k,limit,int(S_FEE*10_000),units,ceiling,values['payMarkupBps'],work_fee,
                price=min(gas+tip,ceiling),mint_fee=mint_fee,buffer_bps=values['bufferBps'],min_edge_bps=values['minEdgeBps'],
                backing_ratio_bps=values['backingRatioBps'],gas_schedule=schedule,
                newly_built=newly_built,reference_units=build_units,retirement_shapes=retirement_shapes)
            if not cached_economics:return result
            edge_cache[key]=result
        return edge_cache[key]
    build_units = next((u for u in range(policy.MIN_PACK_UNITS, policy.MAX_PACK_UNITS + 1) if (values['packUnitsMask'] >> u) & 1), policy.REF_UNITS)
    face_value = build_units * policy.UNIT
    opening = configured_state(int((g_of(0) if callable(g_of) else g_of) * GWEI), values)
    opening.mint_fee = mint_fee
    deposit = sc.get('deposit_wei', n_target * (policy.position_value(opening) + policy.shape_count(build_units) * mint_fee) + values['reserveWei'] + policy.build_cost(opening))
    if not manager and deposit > values["tvlCapWei"]:
        raise ValueError("model deposit exceeds configured TVL cap")
    account_type = Vault
    if manager:
        from manager import Manager
        account_type = Manager
    v = account_type(seed=0 if manager else 10**16, balance=deposit if manager else 10**16, reserve=values["reserveWei"],
              distribution_bps=values["distributionBps"], uplift_bound_bps=values["upliftBoundBps"], pack_units_mask=values["packUnitsMask"],
              accepted_mint_fee=values["acceptedMintFeeWei"],
              live_mint_fee=mint_fee, min_distribution=values["minDistributionWei"])
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
    st0.mint_fee = mint_fee
    st0.gas_schedule = schedule
    st0.build_units, st0.pack_units_mask = build_units, values["packUnitsMask"]
    st0.backing_ratio_bps = values['backingRatioBps']
    st0.accepted_mint_fee = values['acceptedMintFeeWei']
    ck0, d0 = policy.request_charge(st0), policy.deploy_charge(st0)
    v.construction_cost, v.reference_capital = d0, policy.position_value(st0)
    if not manager:
        v.deposit("h", deposit, ck0)
    paid_in = deposit if manager else deposit + ck0
    exit_all = sc.get("exit_all", False)
    exit_days = sc.get("exit_days", 30) if exit_all else 0
    user_gas = sc.get("user_gas_proxy", {})
    gas_curves = sc.get("gas_curves", {}) if manager else {}
    owner_gas_curves = gas_curves | sc.get("owner_gas_curves", {})
    owner_gas_max_work = sc.get("owner_gas_max_work")
    gas_meter_proxy = sc.get("gas_meter_proxy", {})
    gas_meter_max_work = sc.get("gas_meter_max_work")
    def sync_context(allowance, units, count=1, owner=False):
        if sc.get('full_gas_schedule')!=values['gasSchedule']:
            raise ValueError('sync context calibration gas schedule differs from current settings')
        return sync_context_gas(sc.get('owner_sync_contexts' if owner else 'sync_contexts',{}),allowance,units,count)
    def work_meter(operation,count=1,allowance=None,units=0):
        if operation=='sync':
            context=sync_context(allowance,units,count)
            meter=context.get('measured_gas')
            if type(meter) is not int or meter<0:raise ValueError('sync context lacks measured span')
            return meter
        return metered_work_gas(gas_curves,gas_meter_proxy,operation,count,gas_meter_max_work)
    def operation_gas(operation,count,allowance,units=0,estimate=False):
        if operation=='sync':
            return sync_context(allowance,units,count)['estimate_gas' if estimate else 'billed_gas']
        return receipt_gas(gas_curves,operation,count,allowance,estimate=estimate,legacy_floor=user_gas.get(operation,0))
    meter_censored_calls = 0
    user_estimates = sc.get("user_gas_estimate_proxy", {})
    owner_estimate_fallback = set()
    entry_method = 'create' if manager else 'deposit'
    holder_gas = (int(g0 * GWEI) + tip) * receipt_gas(owner_gas_curves,entry_method,1,legacy_floor=user_gas.get(entry_method,0))
    unknown_user_gas = int(exit_all and entry_method not in user_gas)
    keeper_gas_proxy_cost = 0
    keeper_unmeasured = set()
    manager_waits = {}
    manager_wait_examples = {}
    owner_processing_calls = owner_processing_cost = owner_processing_pending = 0
    owner_harvest_calls = owner_withdraw_calls = owner_set_exiting_calls = 0
    owner_exit_limit = sc.get('owner_exit_spend_limit_wei') if manager else None
    if owner_exit_limit is not None and (not isinstance(owner_exit_limit, int) or owner_exit_limit < 0):
        raise ValueError('owner exit signed spending limit must be a nonnegative integer')
    owner_exit_reserved = owner_exit_spent = 0
    owner_processing_blocked = False
    keeper_zero_loss = manager and bool(sc.get('manager_keeper_zero_loss', False))
    from keeper import profitability_gate, wallet_debit_bound, billed_ratio
    keeper_receipt_history_enabled = manager and bool(sc.get('manager_keeper_receipt_history',False))
    keeper_executed_gas = manager and bool(sc.get('manager_keeper_executed_gas', False))
    if keeper_receipt_history_enabled and (not keeper_zero_loss or not gas_curves):
        raise ValueError('keeper receipt history requires calibrated curves and zero-loss admission')
    keeper_receipt_history=SimpleNamespace(state={'counted':[]})
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
    keyed_randomness = bool(sc.get('request_randomness'))
    if keyed_randomness and (not timed or ('response_sampler' in sc and 'request_response_sampler' not in sc)):
        raise ValueError('request_randomness requires timed mode and request_response_sampler(U) in place of response_sampler(rng)')
    request_ordinal = 0
    response_draws = {}
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
    op_names = ("syncCheckpoint", "sync", "harvest", "unlist", "liquidate", "checkpoint", "build", "list")
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
                              protected=v.redemption_reserve + v.distribution_reserve + v.claimable_total + v.processing_pool + v.charge_refund_reserve,
                              locked=locked_holder(), global_locked=v.locked_shares, positions=len(v.positions),
                              returned_value=sum(p.value for p in v.positions.values() if p.status == SETTLED and p.pack_owned),
                              journal=len(journal), claimed=holder_claimed,market_pending=market_pending))

    def owner_gas(estimate):
        return max(21_000, estimate) if owner_exit_limit is not None else estimate

    def owner_supported(operation, work_count):
        if owner_gas_max_work is not None and work_count > owner_gas_max_work.get(operation,0):
            raise ValueError("owner batch exceeds actual receipt support: " + operation)

    def owner_billed(operation, work_gas=0, work_count=1, units=0):
        owner_supported(operation,work_count)
        if operation=='recover_sync':
            return sync_context(work_gas,units,work_count,owner=True)['billed_gas']
        return owner_gas(receipt_gas(owner_gas_curves,operation,work_count,work_gas,legacy_floor=user_gas.get(operation,0)))

    def owner_estimate(operation, work_gas, work_count=1, units=0):
        owner_supported(operation,work_count)
        if operation=='recover_sync':
            context=sync_context(work_gas,units,work_count,owner=True)
            return max(context['billed_gas'],context['estimate_gas'])
        if owner_gas_curves:
            return max(21_000,receipt_acceptance_gas(owner_gas_curves,operation,work_count,work_gas))
        if operation not in user_estimates:
            owner_estimate_fallback.add(operation)
        return max(21_000, work_gas, user_estimates.get(operation, user_gas.get(operation, 0)))

    def owner_preflight(estimates, base_fee, operation):
        nonlocal owner_exit_reserved
        bound = sum(wallet_debit_bound(max(21_000, estimate), base_fee, tip) for estimate in estimates)
        if owner_exit_limit is not None and owner_exit_reserved + bound > owner_exit_limit:
            manager_waits['EXIT_SPEND_LIMIT'] = manager_waits.get('EXIT_SPEND_LIMIT', 0) + 1
            manager_wait_examples.setdefault('EXIT_SPEND_LIMIT', dict(time=now,operation=operation,
                reserved_wei=owner_exit_reserved,next_signed_bound_wei=bound,limit_wei=owner_exit_limit))
            return False
        owner_exit_reserved += bound
        return True

    def owner_charge(cost):
        nonlocal owner_exit_spent, holder_gas
        owner_exit_spent += cost
        holder_gas += cost

    def claim_available(gas_price, day):
        nonlocal holder_claimed, holder_gas, unknown_user_gas
        nonlocal credit,owner_harvest_calls,owner_withdraw_calls
        if manager:
            if not exit_requested or owner_processing_blocked:
                return
            if credit and not (v.positions or v.idle_packs or v.recovery_packs or v.receipts):
                # Collect once after retirement; no needless intermediate exit sweeps.
                gas = owner_billed('harvest',st0.gas_schedule['harvest'])
                if not owner_preflight([owner_estimate('harvest', gas)], max(0, gas_price-tip), 'harvest'):
                    return
                v.receive_fees(credit)
                credit = 0
                owner_charge(gas * gas_price)
                unknown_user_gas += int('harvest' not in user_gas or 'harvest' in sc.get('unmeasured_gas_operations',[]))
                owner_harvest_calls+=1
                trace_state('owner-harvest-credit', day)
            if not (v.positions or v.idle_packs or v.recovery_packs or v.receipts) and v.balance:
                withdraw_gas = owner_billed('withdraw')
                if not owner_preflight([owner_estimate('withdraw', withdraw_gas)], max(0, gas_price-tip), 'withdraw'):
                    return
                holder_claimed += v.withdraw(v.balance)
                owner_charge(withdraw_gas * gas_price)
                unknown_user_gas += int('withdraw' not in user_gas)
                owner_withdraw_calls+=1
                trace_state('owner-withdraw', day)
            return
        refund_ids = [i for i, c in enumerate(v.contributions) if c[0] == 'h' and v.checkpoint_refund(i)]
        for start in range(0, len(refund_ids), 16):
            holder_claimed += v.claim_checkpoint_refund('h', refund_ids[start:start+16])
            holder_gas += user_gas.get('claim_refund', 0) * gas_price
            unknown_user_gas += int('claim_refund' not in user_gas)
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
        if d <= days and (d % MARK_DAYS == 0 or d in (1,2,3,7,14)) and str(d) not in operating_budget_marks:
            operating_budget_marks[str(d)] = dict(elapsed_seconds=now, routine_budget_wei=v.routine_budget,
                routine_paid_wei=routine_paid, free_wei=v.free(), positions=len(v.positions),
                fees_wei=v.fees_received, lost_wei=v.backing_lost, selections=selected, cash_wei=v.balance,
                keeper_cash_wei=v.keeper_cash_after(),
                mint_fees_wei=v.mint_fees,fee_credit_wei=credit,protected_refund_wei=v.charge_refund_reserve)
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
        backing = edge_for(build_units)
        relist_backing = edge_for(build_units,False)

        if timed:
            A = 0
            if event_kind == "request":
                market_pending += 1
            elif event_kind == "acquisition":
                draws=clock.request_draws[request_ordinal] if keyed_randomness else None
                if keyed_randomness and sc.get('randomness_sink') is not None:
                    sc['randomness_sink'].append((request_ordinal,*map(float,draws)))
                request_ordinal+=1
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
                    draw = (draws[0] if keyed_randomness else rng.random()) * W
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
                            if keyed_randomness:trace[-1]['request_ordinal']=request_ordinal-1
                        delay, kept = clock.response_delay, None
                        if keyed_randomness:
                            response_draws[chosen]=draws[2]
                            if 'request_response_sampler' in sc:
                                delay,kept=sc['request_response_sampler'](float(draws[1]))
                                response_keep[chosen]=kept
                        elif "response_sampler" in sc:
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
                    keep_draw=response_draws.pop(payload,None) if keyed_randomness else None
                    if kept if kept is not None else (keep_draw if keyed_randomness else rng.random()) < sc.get("keep", KEEP_DEFAULT):
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
        if manager and owner_processing_blocked and market_pending == 0:
            owner_processing_blocked = False  # Actual archived callbacks removed the global queue lock.
        if manager and owner_processing_blocked:
            phases = []
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
                recent = vol_hist[max(0, d - 6):d + 1] if timed else vol_hist[-7:]
                recent_total = sum(map(int, recent))
                recent_volume = recent_total / len(recent) if len(recent) and 0 <= recent_total <= 2**53 else float(np.mean(recent))
                st = policy.State(
                    now=absolute_now, gas_price=gas + tip, base_fee=gas, gas_ceiling=ceiling, max_tip=tip,
                    markup_bps=values["payMarkupBps"], share_bps=values["keeperShareBps"], k=k, backing=backing,
                    pooled=not manager, winding_down=bool(manager and v.exiting), listing_paused=bool(manager and v.listing_paused),
                    min_edge_bps=values["minEdgeBps"], settlement_fee_bps=int(S_FEE * 10_000), mint_fee=mint_fee,
                    settlement_window=clock.SETTLEMENT if timed else 10**12,
                    blackout=blackout, queue_drained=(market_pending == 0 if timed else (blackout_ok or not blackout) and d >= listing_ready_day),
                    checkpoint_done_this_interval=checkpoint_done, caller_funded_exit=self_serve and exit_all and exit_requested, listings=listings, idle_packs=len(v.idle_packs),
                    relistable_idle=len(v.idle_packs),
                    recovery_packs=len(v.recovery_packs),
                    free=v.free(), keeper_cash=v.keeper_cash_after(), idle_eth=v.idle(), owed_estimate=v.owed_estimate(),
                    pending_deposits=v.pending_total, locked_shares=v.locked_shares,
                    total_shares=v.total_shares, fee_credit=credit,
                    open_positions=len(v.positions), active_count=v.active_count, idle_value=v.idle_value,
                    book_pack_count=len(v.positions)+len(v.idle_packs),
                    book_shape_count=sum(p.shapes or policy.shape_count(p.units) for p in v.positions.values())+sum(v.idle_shapes),
                    book_capital=v.tracked_value+v.active_backing,
                    book_recovery_count=len(v.recovery_packs),book_recovery_value=sum(v.recovery_packs),
                    book_max_units=max([p.units for p in v.positions.values()]+[value//policy.UNIT for value in v.idle_packs],default=0),
                    idle_funding=v.idle_funding,
                    journal_cursor=v.acquisition_cursor, completed_prefix=v.completed_prefix,
                    pending_receipts=len(v.receipts), routine_budget=v.routine_budget,
                    essential_budget=v.essential_budget, essential_cap=values["essentialCapWei"],
                    recent_volume=recent_volume, work_fee=work_fee,
                    slowdown_volume=sc.get("slowdown", 0.0), essential_ceiling=essential_ceiling,
                    pack_units_mask=values["packUnitsMask"], build_units=build_units,
                    gas_schedule=schedule, backing_ratio_bps=values['backingRatioBps'],
                    accepted_mint_fee=values['acceptedMintFeeWei'], operating_reserve=v.reserve,
                    reserve=values["reserveWei"],
                    processing_pool=v.processing_pool, distribution_bps=0 if manager else v.distribution_bps,
                    checkpoint_proof_entries=min(32,len(v.allocation_queue)-v.allocation_head) + (len(v.positions) if not sc.get("exempt",True) and len(v.positions)<=32 and v.active_count else 0),
                    allocation_stale=(v.allocation_head < len(v.allocation_queue) and
                                      (v.allocation_queue[v.allocation_head] not in v.positions or
                                       v.positions[v.allocation_queue[v.allocation_head]].state != ALLOCATED)),
                    own_journal_pending=any(v.positions[i].state == ACTIVE and v.positions[i].status in (ALLOCATED, SETTLED)
                                            for i in hydrated))
                if backing or relist_backing:
                    maximum = 2**256-1 if sc.get('exempt',True) else cap*(10_000-values['bufferBps'])//10_000
                    minimum, maximum = proposal_limits(st,face_value,int(S_FEE*10_000),int(BID_RATE*10_000),maximum,units=build_units)
                    # Speed only: with no idle pack and idle ETH below one backing, the planner can
                    # use neither list nor build proposals, so skipping them changes no decision.
                    if v.idle_packs or st.idle_eth >= minimum:
                        chosen = []
                        for value, old_shapes in zip(reversed(v.idle_packs), reversed(v.idle_shapes)):
                            if len(chosen) == policy.MAX_BATCH['list']:
                                break
                            old_units = value // policy.UNIT
                            target = edge_for(old_units,False,old_shapes)
                            lo, hi = proposal_limits(st,value,int(S_FEE*10_000),int(BID_RATE*10_000),maximum,
                                                     units=old_units,retirement_shapes=old_shapes)
                            proposal = list(_proposals(target, frozenset(p.backing for p in v.positions.values() if p.state != OWED) | frozenset(chosen), lo, hi, 1))
                            if not proposal:
                                break
                            chosen += proposal
                        st.backing_proposals = chosen
                        # A newly built pack repays its build from the keep outcome B(k-s), not the bid
                        # outcome B(k-1): backing >= (value + cycle + build) / (k - s) (VaultLib._profitable).
                        build_minimum, _ = proposal_limits(st,face_value,int(S_FEE*10_000),int(BID_RATE*10_000),maximum,build=True,units=build_units)
                        build_quote = backing_proposals(backing, v.positions, build_minimum, maximum, policy.MAX_BATCH["build"])
                        st.build_proposals = build_quote
                # Other quote inputs are fixed for this run; price changes still get a fresh quote.
                construction_key = st.base_fee, st.gas_price
                if not cached_economics or construction_key not in construction_cache:
                    construction = policy.deploy_charge(st)
                    if cached_economics:
                        construction_cache[construction_key] = construction
                else:
                    construction = construction_cache[construction_key]
                v.construction_cost, v.reference_capital = construction, policy.position_value(st)
                planned = policy.plan(st)
                if manager and not v.exiting:
                    for code,kind,detail in policy.status(st,planned):
                        if code not in ('ROUTINE_BUDGET_EMPTY','MAINTENANCE_UNFUNDED'):
                            continue
                        manager_waits[code]=manager_waits.get(code,0)+1
                        manager_wait_examples.setdefault(code,dict(time=now,free=v.free(),keeper_cash=v.keeper_cash_after(),
                            fee_credit=credit,routine_budget=v.routine_budget,reserve=v.reserve,detail=detail))
                if timed and calls == 0 and d < days:
                    waiting = v.idle_packs or any(l.status in (SETTLED, WITHDRAWN) or (l.status == ALLOCATED and
                                                  absolute_now >= l.allocated_at + clock.SETTLEMENT) for l in listings)
                    if waiting and st.gas_price > st.gas_ceiling:
                        gas_wait_seconds += clock.poll
                    elif any(l.status in (SETTLED, WITHDRAWN) for l in listings) and not any(a[0] == "sync" for a in planned):
                        deferred_seconds += clock.poll
                Q = st.gas_schedule
                essential = bool(manager and v.exiting) or v.locked_shares != 0
                executed = False

                def affordable(gas_q, units=0, ess=False, funding_cap=None, cash_delta=0, liability=False, final_candidate=True, work_count=1, physical_gas=None):
                    nonlocal skipped_funding, routine_unfunded
                    nonlocal last_unfunded_offer, last_cash_shortfall, last_permission_shortfall
                    if fn == 'syncCheckpoint':
                        ess, funding_cap = True, v.processing_pool
                    cost_basis = physical_gas if gas_curves and physical_gas is not None else gas_q
                    recovery = self_serve and exit_all and exit_requested and liability and fn in ('sync','syncCheckpoint','unlist','liquidate','checkpoint')
                    offer = 0 if recovery or fn=='harvest' else policy.payment(st,gas_q,units,ess,measured_gas=0 if gas_q==0 and units==0 else work_meter(fn,work_count,gas_q,units))
                    funds = funding_cap if funding_cap is not None else (v.essential_budget if ess else v.routine_budget)
                    cash = max(0, v.free() + cash_delta) if ess else v.keeper_cash_after(cash_delta)
                    paid = min(offer, funds) if fn == 'syncCheckpoint' else min(offer, funds, cash)
                    holder_fallback = self_serve and liability and (not exit_all or fn != "sync"
                        or (rescue_sync and exit_requested and (v.locked_shares or manager)))
                    if manager and recovery:
                        gas_key = 'recover_checkpoint' if fn=='checkpoint' else 'recover_sync' if fn in ('sync','syncCheckpoint') else fn
                        estimate = owner_estimate(gas_key, cost_basis, work_count, units)
                        # An owner recovery pays no keeper; acceptance is the final pre-mutation check.
                        return owner_preflight([estimate], st.base_fee, fn)
                    if keeper_zero_loss:
                        estimate_gas=operation_gas(fn,work_count,gas_q,units,estimate=True)
                        billed_gas=operation_gas(fn,work_count,gas_q,units)
                        ratio=billed_ratio(keeper_receipt_history,fn) if keeper_receipt_history_enabled else 1.
                        cost,need,accepted=profitability_gate(estimate_gas,st.gas_price,paid,
                            sc.get('keeper_fail_rate_bps',0),sc.get('keeper_min_return_bps',0),0,ratio=ratio)
                        billed_cost,billed_need,billed_accepted=profitability_gate(billed_gas,st.gas_price,paid,
                            sc.get('keeper_fail_rate_bps',0),sc.get('keeper_min_return_bps',0),0,ratio=1.)
                        if keeper_executed_gas:  # keeper bills the simulated signed call: estimate only sets the limit
                            cost,need,accepted=billed_cost,billed_need,billed_accepted
                        else:
                            cost,need,accepted=max(cost,billed_cost),max(need,billed_need),accepted and billed_accepted
                        if not accepted:
                            if final_candidate:
                                manager_waits['KEEPER_LOSS'] = manager_waits.get('KEEPER_LOSS', 0) + 1
                                manager_wait_examples.setdefault('KEEPER_LOSS', dict(time=now,operation=fn,cost_wei=cost,need_wei=need,pay_wei=paid))
                            return False
                    if paid < offer and not holder_fallback:
                        if not final_candidate:
                            return False  # A shorter preflight prefix is not an operating stall.
                        skipped_funding += 1
                        last_unfunded_offer = offer
                        last_cash_shortfall = max(0, offer - cash)
                        last_permission_shortfall = max(0, offer - funds)
                        if not ess and fn != "checkpoint":
                            routine_unfunded += 1
                        if exit_requested:
                            trace_state("unfunded-" + fn, d)
                        return False
                    return True

                def pay(gas_q, units=0, ess=False, funding_cap=None, liability=False, work_count=1, physical_gas=None):
                    nonlocal self_serve_cost, holder_gas, holder_keeper_pay, holder_maintenance_gas, keeper_gas_proxy_cost
                    nonlocal routine_paid, essential_paid, request_paid, unpaid_routine_calls, unknown_user_gas, zero_quote_sync_calls, meter_censored_calls
                    if fn == 'syncCheckpoint':
                        ess, funding_cap = True, v.processing_pool
                    cost_basis = physical_gas if gas_curves and physical_gas is not None else gas_q
                    recovery = self_serve and exit_all and exit_requested and liability and fn in ('sync','syncCheckpoint','unlist','liquidate','checkpoint')
                    offer = 0 if recovery or fn=='harvest' else policy.payment(st,gas_q,units,ess,measured_gas=0 if gas_q==0 and units==0 else work_meter(fn,work_count,gas_q,units))
                    paid = 0 if recovery or fn=='harvest' else v.pay_keeper(offer, essential=ess, cap=funding_cap, source='processing' if fn == 'syncCheckpoint' else None)
                    if manager and not recovery and fn!='harvest':
                        meter_censored_calls += int(work_meter(fn,work_count,gas_q,units)>gas_q)
                        keeper_gas_proxy_cost += operation_gas(fn,work_count,gas_q,units) * st.gas_price
                        if fn not in user_gas or fn in sc.get('unmeasured_gas_operations',[]):
                            keeper_unmeasured.add(fn)
                        if paid < offer or paid == 0:
                            raise RuntimeError(('ordinary keeper payment fell below its reviewed envelope', fn, paid, offer))
                        if keeper_receipt_history_enabled:
                            keeper_receipt_history.state['counted'].append(dict(label=fn,
                                est=operation_gas(fn,work_count,gas_q,units,estimate=True),
                                gas_used=operation_gas(fn,work_count,gas_q,units)))
                    op_paid[fn] += paid
                    op_calls[fn] += 1
                    if fn in ("checkpoint", "syncCheckpoint") and funding_cap is not None:
                        request_paid += paid
                    elif ess:
                        essential_paid += paid
                    else:
                        routine_paid += paid
                        unpaid_routine_calls += int(paid < offer and fn != "harvest" and not recovery)
                    if self_serve and liability:
                        if not manager:
                            self_serve_cost += max(0, gas_q * st.gas_price - paid)
                        if exit_all and (recovery or fn=='harvest' or paid < offer):
                            # Owner recovery uses its own receipts, with no keeper meter or pay.
                            gas_key = 'recover_checkpoint' if recovery and fn=='checkpoint' else 'recover_sync' if recovery and fn in ('sync','syncCheckpoint') else fn
                            measured=user_gas.get(gas_key,0)
                            cost=owner_billed(gas_key,cost_basis,work_count,units)*st.gas_price if manager else owner_gas(max(gas_q,measured))*st.gas_price
                            if manager:
                                owner_charge(cost)
                                self_serve_cost += cost
                            else:
                                holder_gas += cost
                            holder_maintenance_gas += cost
                            holder_keeper_pay += paid
                            holder_calls[fn] += 1
                            unknown_user_gas += int(gas_key not in user_gas)
                            zero_quote_sync_calls += int(gas_q == 0)
                    return paid

                for action_index, action in enumerate(planned):
                    fn = action[0]
                    action_meta = {}
                    if fn in ("sync", "syncCheckpoint"):
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
                        if (not unexposed and journal and len(v.positions) <= policy.MAX_SCAN and len(v.positions) * Q["scan"] <= min(len(journal), policy.MAX_BATCH["journal"]) * Q["journal"]
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
                        physical_gas = (base_q + len(entries)*Q['journal'] + scanned*Q['scan']
                            + len(own_ids)*Q['selected'] + len(resolved)*Q['synced'] + pruned*Q['pruned'])
                        if ((unexposed and not v.tracked_value) or (rebase_count and not pruned)
                                or (not journal_paid_work and not own_ids and not resolved and not pruned)):
                            gas_q = 0
                        base_gas_q = gas_q
                        funding_probe = distribution_probe if required_tail and st.distribution_bps \
                            and not (st.pending_deposits or st.locked_shares) else v
                        take_credit, fee_ids = 0, []
                        if fn == 'sync' and not (self_serve and exit_all and exit_requested and essential):
                            gas_q, take_credit, fee_ids = funding_probe.sync_fee_plan(
                                action[1], credit, gas_q, len(resolved),
                                lambda g, u: policy.quote(st, g, u), st.share_bps,
                                Q["sync_credit"], Q["sync_funding"], Q["harvested"],
                                cash_delta=reclaim_cash,
                                distribution_tail=bool(required_tail and st.distribution_bps
                                                       and not (st.pending_deposits or st.locked_shares)))
                        physical_gas += (Q['sync_credit'] if take_credit else 0) + (
                            Q['sync_funding'] + len(fee_ids)*Q['harvested'] if fee_ids else 0)
                        fee_receipts = take_credit + sum(v.positions[i].pending_fees for i in fee_ids)
                        if (exit_all or manager) and gas_q == 0 and not (exit_requested and (v.locked_shares or manager)):
                            continue
                        if not affordable(gas_q, len(resolved), False,
                                          cash_delta=reclaim_cash + fee_receipts, liability=essential,
                                          final_candidate=not any(a[0] == "sync" for a in planned[action_index + 1:]),
                                          work_count=max(1,len(own_ids),len(resolved)),physical_gas=physical_gas):
                            continue
                        if rebase_count:
                            assert v.advance_unexposed()
                            journal.clear()
                            journal_rebased += rebase_count
                        if scan_now:
                            assert v.scan_rebase(found,Q["scan"],Q["journal"]) == scanned
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
                                               sync_collection_gas=gas_q - base_gas_q,sync_payment_gas=gas_q,
                                               sync_physical_work_gas=physical_gas)
                        journal_paid += pay(gas_q, len(resolved), False, liability=essential,work_count=max(1,len(own_ids),len(resolved)),physical_gas=physical_gas)
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
                        liability = essential and v.owed_estimate() > v.free()
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
                        if not affordable(gas_q, len(ids), essential, cash_delta=cash, liability=essential,work_count=len(ids)):
                            continue
                        for i in ids:
                            credit += v.positions[i].pending_fees
                            v.unlist(i)
                        pay(gas_q, len(ids), essential, liability=essential,work_count=len(ids))
                    elif fn == "liquidate":
                        # Redeem idle packs to ETH at exact backing; burn each pack's Shapes (no loose
                        # Shapes exist). At most MAX_LIQUIDATE_UNITS (60) 0.01-units of packs per call.
                        packs = units = burned = 0
                        inventory = reversed(v.idle_packs)
                        cash = 0
                        while packs < action[1] and units < 60 and \
                                ((manager and v.exiting) or v.owed_estimate() > v.free() + cash):
                            value = next(inventory, None)
                            if value is None:
                                break
                            u = value // policy.UNIT
                            if units + u > 60:
                                break
                            packs += 1
                            units += u
                            burned += v.idle_shapes[-packs]
                            cash += value
                        if not packs:
                            continue
                        gas_q = Q["liquidate"] + Q["liq_pack"] * packs + Q["redeem_shape"] * burned
                        if not affordable(gas_q, packs, True, cash_delta=cash, liability=True,work_count=packs):
                            continue
                        for _ in range(packs):
                            v.liquidate_one()
                        pay(gas_q, packs, True, liability=True,work_count=packs)
                    elif fn == "checkpoint":
                        pool = v.processing_pool
                        flows = v.pending_total != 0 or v.locked_shares != 0
                        try:
                            proof_entries,proof_reads=v.checkpoint_proof_counts(sc.get("exempt",True))
                        except RuntimeError:
                            missed_alloc += 1
                            continue
                        gas_q = Q["checkpoint"] + proof_entries*Q["allocation_entry"] + proof_reads*Q["allocation_read"]
                        funding_cap = pool if flows else None
                        if not affordable(gas_q, 1, essential, funding_cap, cash_delta=pool, liability=essential):
                            continue
                        snap = copy.deepcopy(v.__dict__)
                        try:
                            if self_serve and exit_all and exit_requested and v.locked_shares:
                                v.recover_checkpoint(credit)
                            else:
                                v.checkpoint(credit, keeper_payment=min(policy.payment(st,gas_q,1,True,measured_gas=work_meter(fn,1)), pool) if flows else 0)
                        except RuntimeError:
                            v.__dict__.update(snap)
                            missed_alloc += 1
                            continue
                        credit = 0
                        checkpoints += 1
                        recovering = self_serve and exit_all and exit_requested and snap["locked_shares"]
                        checkpoint_done = not recovering
                        if timed and not recovering:
                            last_checkpoint_interval = absolute_now // clock.INTERVAL
                            timed_checkpoint_times.append(absolute_now)
                        if self_serve and exit_all and exit_requested and snap['locked_shares']:
                            pay(gas_q,1,True,liability=True)
                        elif flows:
                            paid = v.keeper_paid - snap['keeper_paid']
                            request_paid += paid
                            op_paid[fn] += paid
                            op_calls[fn] += 1
                        else:
                            pay(gas_q, 1, False, liability=essential)
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
                        if v.idle() < cash + sum(proposals) \
                                or not affordable(gas_q, 2 * count, cash_delta=-(cash + sum(proposals)),work_count=count):
                            continue
                        v.build(list(range(next_id, next_id + count)), units, mint_fee, proposals)
                        next_id += count
                        pay(gas_q, 2 * count,work_count=count)
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
                        if not proposals or not affordable(gas_q, len(proposals), cash_delta=-cash,work_count=len(proposals)):
                            continue
                        for proposal in proposals:
                            v.list(next_id, proposal)
                            next_id += 1
                        pay(gas_q, len(proposals),work_count=len(proposals))
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
        if manager and ((event_kind == 'cutoff') if timed else d == days - 1):
            set_exit_gas = owner_billed('setExiting')
            if owner_preflight([owner_estimate('setExiting', set_exit_gas)], gas, 'setExiting'):
                exit_requested = True
                v.set_exiting(True)
                owner_set_exiting_calls += 1
                owner_charge(set_exit_gas * (gas + tip))
                unknown_user_gas += int('setExiting' not in user_gas)
                trace_state('set-exiting', d)
                if market_pending and (v.positions or v.receipts):
                    from manager import owner_processing_reserve
                    owner_processing_pending=market_pending
                    single_gas=owner_billed('processAcquisitions')
                    single_estimate=owner_estimate('processAcquisitions', single_gas)
                    estimates=[min(16,market_pending-start)*single_estimate for start in range(0,market_pending,16)]
                    if owner_preflight(estimates, gas, 'processAcquisitions'):
                        owner_processing_calls,owner_processing_cost=owner_processing_reserve(market_pending,single_gas,gas+tip)
                        owner_charge(owner_processing_cost)
                        unknown_user_gas+=int('processAcquisitions' not in user_gas)
                        # Archived ready times remain; the owner pays the pending prefix reserve.
                        trace_state('owner-processing-reserve',d)
                    else:
                        owner_processing_blocked=True
        if timed:
            redemptions = [(d, 1.0)] if event_kind == "cutoff" and exit_all else ([(d, payload)] if event_kind == "redemption" else [])
        elif exit_all:
            redemptions.append((days - 1, 1.0))
        for day, frac in ([] if manager else redemptions):
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
                st1 = configured_state(gas, values)
                st1.processing_pool = v.processing_pool
                st1.mint_fee = mint_fee
                st1.active_count = v.active_count
                st1.book_pack_count = len(v.positions)+len(v.idle_packs)
                st1.book_shape_count = sum(p.shapes or policy.shape_count(p.units) for p in v.positions.values()) + sum(v.idle_shapes)
                st1.book_capital = v.tracked_value + v.active_backing
                st1.book_recovery_count,st1.book_recovery_value = len(v.recovery_packs),sum(v.recovery_packs)
                st1.book_max_units = max([p.units for p in v.positions.values()]+[value//policy.UNIT for value in v.idle_packs],default=0)
                st1.checkpoint_proof_entries = min(32, len(v.allocation_queue)-v.allocation_head) + (len(v.positions) if not sc.get('exempt',True) and len(v.positions)<=32 and v.active_count else 0)
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
            if manager and not (v.positions or v.idle_packs or v.recovery_packs or v.receipts or credit or v.balance):
                break
            if not manager and (not v.share_balance("h") and not locked_holder()
                    and not v.claimable.get("h", 0) and not v.pending_total and not journal and not v.receipts
                    and not v.locked_shares):
                break

    if manager:
        physical = (v.balance + sum(v.idle_packs) + sum(v.recovery_packs)
            + sum(p.value for p in v.positions.values() if p.status in (ACTIVE, ALLOCATED) or p.pack_owned)
            + sum(p.backing for p in v.positions.values() if p.status in (ACTIVE, ALLOCATED)))
        unreconciled_keep = sum(p.value for p in v.positions.values() if p.status == SETTLED and not p.pack_owned)
        gap = paid_in + v.fees_received - v.keeper_paid - v.mint_fees - v.backing_lost - v.settlement_fees - unreconciled_keep - holder_claimed - physical
        assert gap == 0, ('manager cash/assets ledger', gap)
        assert accrued == v.fees_received + credit + sum(p.pending_fees for p in v.positions.values()), 'manager external fee ledger'
        complete = exit_requested and not (v.positions or v.idle_packs or v.recovery_packs or v.receipts or credit or v.balance)
        result = dict(account_kind='manager', initial_funding_wei=deposit, owner_funded_wei=paid_in,
            owner_withdrawn_wei=holder_claimed, owner_wallet_gas_proxy_wei=holder_gas,
            owner_net_wei=holder_claimed-holder_gas-paid_in if complete else None,
            owner_total_value_before_gas_wei=physical+credit+sum(p.pending_fees for p in v.positions.values())+holder_claimed,
            keeper_compensation_wei=v.keeper_paid, keeper_gas_proxy_cost_wei=keeper_gas_proxy_cost,
            keeper_net_proxy_wei=v.keeper_paid-keeper_gas_proxy_cost, keeper_unmeasured_operations=sorted(keeper_unmeasured),
            unpaid_routine_calls=unpaid_routine_calls,
            creator_primary_fees_accrued_wei=v.mint_fees, fees_received_wei=v.fees_received,
            backing_lost_wei=v.backing_lost, settlement_fees_wei=v.settlement_fees,
            ledger_gap_wei=gap, physical_assets_wei=physical, external_fee_credit_wei=credit,
            unharvested_listing_fees_wei=sum(p.pending_fees for p in v.positions.values()),
            exit_complete=complete, elapsed_days=now/DAY if timed else d+1,
            exit_days_elapsed=max(0,now/DAY-days) if timed else max(0,d+1-days),
            selections=selected, mean_positions=float(np.mean(open_days)), maximum_positions=max(open_days,default=0),
            routine_keeper_paid_wei=routine_paid, essential_keeper_paid_wei=essential_paid,
            operation_end_cash_wei=operation_end_cash, operation_end_routine_budget_wei=operation_end_routine_budget,
            operation_end_backlog=operation_end_backlog, operating_budget_marks=operating_budget_marks,
            unknown_owner_gas_calls=unknown_user_gas, owner_exit_work=self_serve,
            routine_unfunded_attempts=routine_unfunded, routine_budget_wei=v.routine_budget,
            routine_period_permission_upper_wei=values['routineCapWei']+now*values['routineRatePerDayWei']//DAY,
            pending_receipts=len(v.receipts), journal_backlog=len(journal),
            end_open_positions=len(v.positions),end_idle_packs=len(v.idle_packs),end_recovery_packs=len(v.recovery_packs),end_cash_wei=v.balance,
            waiting_observations=manager_waits, first_wait_observation=manager_wait_examples,
            owner_processing_calls=owner_processing_calls,owner_processing_proxy_cost_wei=owner_processing_cost,
            owner_processing_pending_at_exit=owner_processing_pending,
            owner_exit_spend_limit_wei=owner_exit_limit,owner_exit_reserved_wei=owner_exit_reserved,
            owner_exit_spent_wei=owner_exit_spent,owner_exit_spend_limit_waits=manager_waits.get('EXIT_SPEND_LIMIT',0),
            owner_exit_estimate_fallback_operations=sorted(owner_estimate_fallback),
            count_aware_gas_curves_enabled=bool(gas_curves),physical_sync_cost_basis_enabled=bool(sc.get("sync_contexts")),sync_contexts_enabled=bool(sc.get("sync_contexts")),
            owner_zero_quote_sync_calls=zero_quote_sync_calls,
            compensation_mode='bounded-measured-v1',meter_censored_calls=meter_censored_calls,
            keeper_estimate_acceptance_enabled=bool(gas_curves and keeper_zero_loss),
            keeper_receipt_history_enabled=keeper_receipt_history_enabled,
            keeper_receipt_history_counts={name:sum(e['label']==name for e in keeper_receipt_history.state['counted']) for name in op_names},
            keeper_receipt_history_ratios={name:billed_ratio(keeper_receipt_history,name) for name in op_names} if keeper_receipt_history_enabled else {},
            keeper_zero_loss_enabled=keeper_zero_loss,keeper_loss_waits=manager_waits.get('KEEPER_LOSS',0),
            ordinary_completion_actor='Recorded external VRF/processor; historical requesters fund it',
            exit_processing_assumption='Owner reserve for pending prefix, <=16 records per call, full measured single-request call gas charged per pending record; archived ready times retained')
        for name in op_names:
            result['keeper_calls_'+name]=op_calls[name]-holder_calls[name]
            result['keeper_paid_'+name+'_wei']=op_paid[name]
            result['owner_calls_'+name]=holder_calls[name]
        result['owner_calls_harvest']+=owner_harvest_calls
        result['owner_calls_withdraw']=owner_withdraw_calls
        result['owner_calls_setExiting']=owner_set_exiting_calls
        if keyed_randomness:result.update(randomness_mode='request-keyed-v1',request_events_sha256=clock.request_events_sha256,requests_seen=request_ordinal)
        return result

    end_nav = economic_nav(v, credit)
    unexposed = not v.positions and not v.receipts and not v.active_count and not v.active_backing and not v.allocated_value
    end_blocked = bool((journal and not unexposed) or v.receipts or (v.allocation_head < len(v.allocation_queue) and
                       (v.allocation_queue[v.allocation_head] not in v.positions or
                        v.positions[v.allocation_queue[v.allocation_head]].state != ALLOCATED))
                       or v.unresolved_keep_uplift * 10_000 > end_nav * v.uplift_bound_bps)
    assert len(journal) == v.completed_prefix - v.acquisition_cursor
    assert journal_own + journal_foreign + journal_rebased + journal_skipped == v.acquisition_cursor
    supply = v.total_shares
    d_ = v.pending.get("h", [0, 0])
    unpriced = d_[0] if d_[1] >= v.epoch else 0
    # With only this holder and no locked exit, cancelling the unpriced deposit also refunds
    # its checkpoint charge. No work was performed, so do not invent an entry loss.
    unpriced_refund = unpriced + (v.processing_pool if unpriced and not v.locked_shares else 0)
    claimed = v.claimable.get("h", 0) + v.redemption_reserve + unpriced_refund + sum(v.checkpoint_refund(i) for i, c in enumerate(v.contributions) if c[0] == "h")
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
                physical_assets_wei=physical, vault_cash_wei=v.balance, holder_liability_wei=v.redemption_reserve + v.distribution_reserve + v.claimable_total + v.charge_refund_reserve,
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
    if keyed_randomness:result.update(randomness_mode='request-keyed-v1',request_events_sha256=clock.request_events_sha256,requests_seen=request_ordinal)
    return result


def const(value):
    return lambda day, rng: value


def main():
    from formal import main as assess
    assess()


if __name__ == '__main__':
    main()
