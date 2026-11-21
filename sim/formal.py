#!/usr/bin/env python3
"""Formal holder-return assessment (owner requirements A.3, A.8, A.10; B2 outcome "holder return").

Gate: at least 10% a year net to holders at trailing-30-day successful acquisition volume, tokens
at zero, every expense included, at the 0.5 gwei routine gas ceiling; a positive bid outcome after
gas; at least one usable exit window a day. Capacity is reported separately.

Method. The archive (sim/ingest.py, validated by sim/replay.py) is pinned to one block. The actual
30 days ending at that block's timestamp are replayed through the timed model in sim/forward.py
(the sim/vault.py integer mirror of PackVault, keeper decisions from keeper/policy.py, the same
bounded candidate projection as the event index). Every recorded request keeps its time, outcome
(successful or refunded) and recorded foreign totalWeight; purchaser responses are drawn from the
window's recorded allocation responses. The holder deposits at the window start, holds for twelve
consecutive repeats of the window (360 days), requests a full exit and the run ends only when the
claim completes or the exit allowance runs out. No annualization: the return is claimed cash after
one year of operation. Which vault listing a request selects is a seeded counterfactual draw.

Usage: sim/formal.py [--seeds 16] [--workers 12] [--quick]
"""
import argparse
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import forward as F  # noqa: E402
import replay  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs/receipts"
PIN = dict(block=26_450_200, hash="0xda7052eb890b621f2ed635feb0af056e155f801305427af666aa7930d4baabc5",
           timestamp=1_795_104_215)
WINDOW = 30 * F.DAY
INTERVAL, BLACKOUT = F.OperatingClock.INTERVAL, F.OperatingClock.BLACKOUT_START
HURDLE_BPS = 1_000
SOURCES = ["sim/formal.py", "sim/forward.py", "sim/vault.py", "sim/replay.py", "sim/ingest.py",
           "keeper/policy.py", "deploy/canary.json", "deploy/mainnet.json"]


def window(db_path, end):
    """Recorded requests, completions and purchaser responses in [end - 30 days, end]."""
    start = end - WINDOW
    db = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    top = db.execute("SELECT max(block) FROM logs").fetchone()[0]
    request = {}
    for ts, a in db.execute("SELECT ts, args FROM logs WHERE event='AcquisitionRequested' AND ts<=?", (end,)):
        a = json.loads(a)
        request[a["requestId"]] = (ts, int(a["totalWeight"]) / F.E)
    events, statuses = [], {}
    for ts, a in db.execute("SELECT ts, args FROM logs WHERE event='AcquisitionProcessed' AND ts>=? AND ts<=?"
                            " ORDER BY block, log_index", (start, end)):
        a = json.loads(a)
        status = int(a["status"])
        statuses[status] = statuses.get(status, 0) + 1
        requested_at, weight = request[a["requestId"]]
        # A request made before the window opens is placed at the opening so the queue balances.
        events.append((max(requested_at, start) - start, ts - start, (status == 2, weight)))
    assert set(statuses) <= {2, 4}, statuses  # 2 settled, 4 refunded (slippage)
    responses, kinds = [], {}
    first = {}
    for ts, ev, a in db.execute("SELECT ts, event, args FROM logs WHERE event IN ('DepositorBidAccepted',"
                                "'DepositorBidAcceptedAsTokens','NFTKept') AND ts>=? ORDER BY block, log_index", (start,)):
        first.setdefault(int(json.loads(a)["listingId"]), []).append((ts, ev))
    for ts, a in db.execute("SELECT ts, args FROM logs WHERE event='NFTAllocated' AND ts>=? AND ts<=?", (start, end)):
        later = [r for r in first.get(int(json.loads(a)["listingId"]), []) if r[0] >= ts]
        kind = later[0][1] if later else "silent"
        kinds[kind] = kinds.get(kind, 0) + 1
        responses.append((later[0][0] - ts, kind == "NFTKept") if later else (None, None))
    db.close()
    pairs = events
    events = flatten(pairs)
    successful = statuses.get(2, 0)
    daily = np.bincount([int(at // F.DAY) for at, k, p in events if k == "acquisition" and p[0]], minlength=30)[:30]
    return dict(start=start, end=end, archive_top_block=top, events=events, pairs=pairs, successful=successful,
                refunded=statuses.get(4, 0), successful_per_day=successful / 30, daily_successful=daily.tolist(),
                responses=responses, response_kinds=kinds)


def flatten(pairs):
    """(request offset, completion offset, payload) pairs as timed clock events."""
    events = [(r, "request", None) for r, _, _ in pairs] + [(c, "acquisition", x) for _, c, x in pairs]
    return sorted(events, key=lambda e: (e[0], e[1] != "request"))


def exit_windows(events):
    """Blackouts (the last 900 s of each 12 h interval) in which FWA's request queue is empty at
    some moment, so a checkpoint can price redemptions. Counted per window day from the record."""
    usable_days = set()
    pending, cursor = 0, 0
    order = sorted(events, key=lambda e: (e[0], e[1] != "acquisition"))
    # Walk every blackout of the 30 days.
    first = (BLACKOUT - (PIN["timestamp"] - WINDOW) % INTERVAL) % INTERVAL
    blackouts = [(a, a + INTERVAL - BLACKOUT) for a in range(first, WINDOW, INTERVAL)]
    usable = []
    for a, b in blackouts:
        while cursor < len(order) and order[cursor][0] < a:
            pending += 1 if order[cursor][1] == "request" else -1
            cursor += 1
        drained, j, q = pending == 0, cursor, pending
        while not drained and j < len(order) and order[j][0] < b:
            q += 1 if order[j][1] == "request" else -1
            drained = q == 0
            j += 1
        usable.append(drained)
        if drained:
            usable_days.add(int(a // F.DAY))
    return dict(blackouts=len(blackouts), usable_blackouts=sum(usable), days_with_usable_window=len(usable_days),
                days=30, minimum_per_day_met=len(usable_days) >= 30)


def scenario(w, events=None, period=None, timing="in-window", exempt=True):
    """Timed replay with purchaser responses drawn from the window's recorded responses.

    Since D80 backing makes keeping the pack the purchaser's best choice, and a keep (or the
    account's reclaim after FWA's settlement window) pays the account more per cycle than a bid.
    The formal case ("in-window") is kept unchanged as the conservative gate: every responder
    bids, at the recorded delay or just inside the window if the recorded answer was later; silent
    purchasers stay silent (and the account reclaims, a keep). Diagnostics:
    "recorded-timing" keeps late answers late (they then lose to the vault's reclaim) and
    "recorded-choice" also keeps recorded keeps as keeps."""
    responses = w["responses"]
    last = F.OperatingClock.SETTLEMENT - 120

    def sampler(rng):
        delay, kept = responses[int(rng.integers(len(responses)))]
        if delay is None:
            return None, None
        if timing == "in-window":
            return min(delay, last), False
        return delay, kept if timing == "recorded-choice" else False
    return F.Scenario(volume=F.const(0), timed=True, start_timestamp=w["start"], poll_seconds=60, receipt_seconds=36,
                      replay_events=w["events"] if events is None else events,
                      replay_period_seconds=WINDOW if period is None else period,
                      response_sampler=sampler, foreign_pool_weight=1.0, exempt=exempt)


def one(job):
    """One seeded run. Returns the model's result fields plus the job identity."""
    w, label, config, principal, price, seed, days, exit_days, events, period, options = job
    values = json.loads((ROOT / f"deploy/{config}.json").read_text())
    sc = scenario(w, events, period, **options)
    sc.update(gwei=max(0.0, price - values["maxTipWei"] / F.GWEI), deposit_wei=principal, exit_all=True,
              exit_days=exit_days, user_gas_proxy=w["user_gas"])
    r = F.run(sc, 1, seed, days=days, values=values)
    r.pop("ret", None)
    assert r["ledger_gap_wei"] == 0 and r["unknown_user_gas_calls"] == 0
    assert r["routine_keeper_paid_wei"] <= r["routine_period_permission_upper_wei"]
    return dict(label=label, config=config, principal_wei=principal, total_price_gwei=price, seed=seed, **r)


def bid_outcome(price_gwei, values):
    """Closed-form bid cycle at the current backing rule: B (k - 1) less the cycle's keeper quote."""
    k = int(F.k_of() * F.E)
    st = F.charge_state(int((price_gwei - values["maxTipWei"] / F.GWEI) * F.GWEI), 0)
    st.gas_ceiling, st.max_tip, st.work_fee = values["gasCeilingWei"], values["maxTipWei"], values["workFeeWei"]
    backing = F.policy.edge_backing(k, None, int(F.S_FEE * 1e4), F.BUILD_UNITS, values["gasCeilingWei"], values["payMarkupBps"],
                                    values["workFeeWei"], price=min(int(price_gwei * F.GWEI), values["gasCeilingWei"]),
                                    mint_fee=F.MINT_FEE, buffer_bps=values["bufferBps"], min_edge_bps=values["minEdgeBps"])
    cycle = F.policy.quote(st, F.policy.CYCLE_GAS, 2)
    edge = backing * (k - F.E) // F.E
    return dict(total_price_gwei=price_gwei, backing_wei=backing, k=k / F.E, edge_before_gas_wei=edge,
                cycle_quote_wei=cycle, net_wei=edge - cycle, positive=edge > cycle)


def summarize(rows):
    out = {}
    for key in dict.fromkeys((r["label"], r["config"], r["principal_wei"], r["total_price_gwei"]) for r in rows):
        group = [r for r in rows if (r["label"], r["config"], r["principal_wei"], r["total_price_gwei"]) == key]
        done = [r for r in group if r["exit_complete"]]
        bps = sorted(r["holder_net_realized_wei"] * 10_000 // r["holder_paid_in_wei"] for r in done)
        out["|".join(map(str, key))] = dict(
            label=key[0], config=key[1], principal_eth=key[2] / F.E, total_price_gwei=key[3], runs=len(group),
            completed_claims=len(done), blocked_exits=len(group) - len(done),
            mean_return_bps=int(np.mean(bps)) if bps else None, median_return_bps=bps[len(bps) // 2] if bps else None,
            p10_return_bps=bps[len(bps) // 10] if bps else None, worst_return_bps=bps[0] if bps else None,
            best_return_bps=bps[-1] if bps else None, loss_runs=sum(b < 0 for b in bps),
            below_hurdle_runs=sum(b < HURDLE_BPS for b in bps),
            mean_creator_mint_fees_eth=float(np.mean([r["creator_mint_fees_wei"] for r in group])) / F.E,
            mean_routine_keeper_eth=float(np.mean([r["routine_keeper_paid_wei"] for r in group])) / F.E,
            mean_request_funded_keeper_eth=float(np.mean([r["request_funded_keeper_paid_wei"] for r in group])) / F.E,
            mean_holder_gas_eth=float(np.mean([r["holder_gas_proxy_cost_wei"] for r in group])) / F.E,
            mean_fees_received_eth=float(np.mean([r["fees_received_wei"] for r in group])) / F.E,
            mean_backing_lost_eth=float(np.mean([r["backing_lost_wei"] for r in group])) / F.E,
            mean_positions=float(np.mean([r["pos_mean"] for r in group])),
            unfunded_routine_attempts=sum(r["routine_unfunded_attempts"] for r in group),
            mean_exit_days=float(np.mean([r["exit_days_elapsed"] for r in done])) if done else None,
            mean_selections=float(np.mean([r["journal_own"] for r in group])))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=16)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--quick", action="store_true", help="one seed, 30 operating days (smoke test, not the gate)")
    a = ap.parse_args()
    db = F.ROOT / "data/fwa.sqlite"
    assert replay.main() == 0, "archive fails exact fee replay or sequence continuity"
    sha = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
    frozen = {p: sha(p) for p in SOURCES}
    w = window(db, PIN["timestamp"])
    assert w["archive_top_block"] <= PIN["block"]
    import efficient_operating as C  # historical holder transaction receipt proxies
    w["user_gas"] = C.receipt_gas()
    windows = exit_windows(w["events"])
    days, exit_days = (30, 30) if a.quick else (360, 30)
    seeds = range(1, 2 if a.quick else a.seeds + 1)
    canary = 1_960_100_000_000_000_000
    jobs = []
    for price in (0.5, 0.2):
        for label, config, principal in [("formal", "canary", canary), ("formal", "mainnet", 68 * 10**17),
                                         ("formal", "mainnet", 20 * F.E)]:
            jobs += [(w, label, config, principal, price, s, days, exit_days, None, None, {}) for s in seeds]
    # Diagnostics, never the gate: the window's last ten days tiled, and zero demand.
    recent_start = WINDOW - 10 * F.DAY
    recent = flatten([(max(0, r - recent_start), c - recent_start, x) for r, c, x in w["pairs"] if c >= recent_start])
    jobs += [(w, "recent-10-days", "canary", canary, 0.5, s, days, exit_days, recent, 10 * F.DAY, {}) for s in seeds]
    jobs += [(w, "zero-demand", "canary", canary, 0.5, 1, days, exit_days, [], WINDOW, {})]
    for timing in ("recorded-timing", "recorded-choice"):
        jobs += [(w, timing, "canary", canary, 0.5, s, days, exit_days, None, None, dict(timing=timing))
                 for s in seeds]
    # FWA's owner set the pack oracle exemption inside the window and can remove it again.
    jobs += [(w, "oracle-capped", "canary", canary, 0.5, s, days, exit_days, None, None,
              dict(exempt=False)) for s in seeds]
    print(f"{len(jobs)} runs, {a.workers} workers", flush=True)
    rows = []
    with ProcessPoolExecutor(a.workers) as pool:
        for r in pool.map(one, jobs):
            rows.append(r)
            print(f"{r['label']} {r['config']} {r['principal_wei'] / F.E:g}eth {r['total_price_gwei']}gwei seed{r['seed']}: "
                  f"claim={r['exit_complete']} net={r['holder_net_realized_wei'] / F.E:+.6f}", flush=True)
    assert frozen == {p: sha(p) for p in SOURCES}, "source changed during the run"
    summary = summarize(rows)
    values = {c: json.loads((ROOT / f"deploy/{c}.json").read_text()) for c in ("canary", "mainnet")}
    bids = [bid_outcome(p, values["canary"]) for p in (0.2, 0.5)]
    gate = {k: s for k, s in summary.items() if s["label"] == "formal" and s["total_price_gwei"] == 0.5}
    formal = dict(
        hurdle_bps=HURDLE_BPS,
        holder_return=all(s["completed_claims"] == s["runs"] and s["median_return_bps"] is not None
                          and s["median_return_bps"] >= HURDLE_BPS for s in gate.values()),
        holder_return_at_canary=summary.get(f"formal|canary|{canary}|0.5"),
        bid_outcome_positive_at_ceiling=bids[1]["positive"],
        usable_exit_window_every_day=windows["minimum_per_day_met"])
    report = dict(
        pin=PIN, command=[sys.executable, *sys.argv], source_sha256=frozen,
        database=dict(path="sim/data/fwa.sqlite (generated by sim/ingest.py; not committed)",
                      replay="0 mismatches; acquisition sequences contiguous"),
        window=dict(start=w["start"], end=w["end"], successful=w["successful"], refunded=w["refunded"],
                    successful_per_day=w["successful_per_day"], daily_successful=w["daily_successful"],
                    purchaser_responses=w["response_kinds"]),
        exit_windows=windows, bid_outcome=bids, formal=formal, summary=summary,
        user_gas_proxy=w["user_gas"], configuration=values, operating_days=days, maximum_exit_days=exit_days,
        rows=[{k: v for k, v in r.items() if k != "operating_budget_marks"} for r in rows],
        method=__doc__.split("Usage:")[0].strip(),
        limits=[
            "Which vault listing each recorded request selects is a seeded counterfactual draw; FWA's real VRF words selected foreign listings.",
            "Recorded foreign totalWeight is used per request; the foreign pool does not react to the vault's presence.",
            "Purchaser responses are sampled from the window's recorded responses to all allocations, not this vault's. The formal case moves recorded late answers just inside the settlement window and treats recorded keeps as bids (the conservative lower bound since D80, when a value-aware purchaser keeps); recorded-timing and recorded-choice diagnostics show the upside if purchasers behave as recorded.",
            "Holder deposit, request, claim and checkpoint gas use historical billed receipts at the scenario price; variable unpaid exit work uses its quoted gas.",
            "Gas price is held constant per scenario. Effects are atomic at the modeled read; reverted races and inclusion latency are not charged.",
            "Tokens are valued at zero. Creator mint fees are an expense to holders and reported separately.",
            "The return counts only cash claimed after the exit completes; incomplete exits report no return."])
    target = OUT / ("formal-assessment-quick.json" if a.quick else "formal-assessment.json")
    target.write_text(json.dumps(report, indent=1) + "\n")
    print(json.dumps(dict(formal=formal, exit_windows=windows, bid=bids), indent=1))
    for k, s in summary.items():
        print(k, {x: s[x] for x in ("runs", "completed_claims", "median_return_bps", "p10_return_bps",
                                    "worst_return_bps", "loss_runs", "mean_creator_mint_fees_eth", "mean_positions")})
    print(f"saved {target}")


if __name__ == "__main__":
    main()
