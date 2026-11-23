#!/usr/bin/env python3
"""Keeper economics assessment: the formal replay (sim/formal.py) across vault sizes and gas paths.

Same demand everywhere: the actual trailing 30 days at formal.PIN (11,604 successful and 5,090
refunded requests, recorded foreign weight and purchaser responses, in-window bids), repeated for
360 days plus a full holder exit. Values come from deploy/mainnet.json (1.96, 6.8 and 20 ETH), optionally overridden per scenario. Gas is the total price
(basefee + 0.05 gwei tip); spike paths hold a higher price over a range of operating days.

Usage: sim/keeper_assess.py [--seeds 400] [--workers 12] [--only LABEL ...] [--out PATH]
Per-scenario rows are kept in sim/data/keeper-assess-parts/ (not committed) so a run resumes.
"""
import argparse
import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import efficient_operating as C  # noqa: E402
import formal as FM  # noqa: E402
import forward as F  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
SMALL = 1_960_100_000_000_000_000  # formal.py's 1.96 ETH holder cell

# (label, config, principal wei, gas (base total gwei, spike total gwei, from day, to day), value overrides)
SCENARIOS = [(f"{name}|{gas[0]}" + (f"|spike{gas[1]}@{gas[2]}-{gas[3]}" if gas[1] else ""), config, principal, gas, {})
             for name, config, principal in (("2eth", "mainnet", SMALL), ("6.8eth", "mainnet", 68 * 10**17),
                                             ("20eth", "mainnet", 20 * 10**18))
             for gas in ((0.15, 0, 0, 0), (0.5, 0, 0, 0), (0.5, 2.0, 30, 120), (0.5, 1.0, 30, 360))]
# The refill the owner's limits assume (0.0008 ETH a day, an earlier default), against PR 2's 0.01.
SCENARIOS.append(("2eth|0.5|refill0.0008", "mainnet", SMALL, (0.5, 0, 0, 0),
                  dict(routineRatePerDayWei=800_000_000_000_000)))
# Diagnostic, not the gate: the window without its busiest day (4,916 of 11,604 successful
# acquisitions), the other 29 days tiled instead.
SCENARIOS += [(f"{name}|0.5|without-peak-day", config, principal, (0.5, 0, 0, 0), dict(_drop_peak_day=True))
              for name, config, principal in (("2eth", "mainnet", SMALL), ("6.8eth", "mainnet", 68 * 10**17),
                                              ("20eth", "mainnet", 20 * 10**18))]


def without_peak_day(w):
    """Window events with the busiest UTC day (by successful acquisitions) cut out; later times
    move back one day. Returns (events, period)."""
    k = int(np.argmax(w["daily_successful"]))
    lo, hi = k * F.DAY, (k + 1) * F.DAY
    move = lambda t: t - F.DAY if t >= hi else min(t, lo)  # noqa: E731
    pairs = [(move(r), move(c), x) for r, c, x in w["pairs"] if not lo <= c < hi]
    return FM.flatten(pairs), FM.WINDOW - F.DAY


def one(job):
    w, label, config, principal, gas, overrides, seed = job
    overrides = dict(overrides)
    drop = overrides.pop("_drop_peak_day", False)
    values = json.loads((ROOT / f"deploy/{config}.json").read_text()) | overrides
    tip = values["maxTipWei"] / F.GWEI
    base, spike, start, stop = gas
    sc = FM.scenario(w, *without_peak_day(w)) if drop else FM.scenario(w)
    sc.update(gwei=(lambda d: (spike if start <= d < stop else base) - tip) if spike else base - tip,
              deposit_wei=principal, exit_all=True, exit_days=30, user_gas_proxy=w["user_gas"])
    r = F.run(sc, 1, seed, days=360, values=values)
    r.pop("ret", None)
    r.pop("operating_budget_marks", None)
    assert r["ledger_gap_wei"] == 0 and r["unknown_user_gas_calls"] == 0
    assert r["routine_keeper_paid_wei"] <= r["routine_period_permission_upper_wei"]
    return dict(label=label, config=config, principal_wei=principal, seed=seed, **r)


OPS = ("sync", "list", "restock", "checkpoint", "harvest", "unlist", "liquidate")


def summarize(rows):
    E = F.E
    done = [r for r in rows if r["exit_complete"]]
    ret = np.array(sorted(r["holder_net_realized_wei"] / r["holder_paid_in_wei"] for r in done))
    mean = lambda k: float(np.mean([r[k] for r in rows]))  # noqa: E731
    q = lambda p: float(np.quantile(ret, p)) if len(ret) else None  # noqa: E731
    return dict(
        runs=len(rows), completed_exits=len(done),
        mean_return=float(ret.mean()) if len(ret) else None, median_return=q(0.5), p10_return=q(0.10),
        p5_return=q(0.05), p_loss=float((ret < 0).mean()) if len(ret) else None,
        p_below_10pct=float((ret < 0.10).mean()) if len(ret) else None,
        fees_received_eth=mean("fees_received_wei") / E, backing_lost_eth=mean("backing_lost_wei") / E,
        routine_keeper_eth=mean("routine_keeper_paid_wei") / E,
        checkpoint_routine_eth=mean("keeper_paid_checkpoint_wei") / E - mean("request_funded_keeper_paid_wei") / E,
        checkpoint_request_funded_eth=mean("request_funded_keeper_paid_wei") / E,
        essential_keeper_eth=mean("essential_keeper_paid_wei") / E, mint_fees_eth=mean("creator_mint_fees_wei") / E,
        settlement_fees_eth=mean("settlement_fees_wei") / E,
        unreimbursed_holder_gas_eth=mean("holder_gas_proxy_cost_wei") / E,
        unreimbursed_exit_work_eth=mean("external_exit_gas_proxy_wei") / E,
        keeper_calls={op: mean(f"keeper_calls_{op}") for op in OPS},
        keeper_paid_eth={op: mean(f"keeper_paid_{op}_wei") / E for op in OPS},
        holder_calls={op: mean(f"holder_calls_{op}") for op in OPS},
        own_selections=mean("own_selections"), scans=mean("journal_scans"),
        listings_read_per_scan=mean("journal_scanned") / max(1e-9, mean("journal_scans")),
        global_records_read=mean("journal_foreign") + mean("journal_own"),
        global_records_skipped_by_scan=mean("journal_skipped"), global_records_rebased=mean("journal_rebased"),
        unfunded_routine_attempts=mean("routine_unfunded_attempts"),
        gas_wait_hours=mean("gas_wait_seconds") / 3600, deferred_terminal_hours=mean("deferred_terminal_seconds") / 3600,
        settlement_wait_hours=mean("settlement_wait_seconds") / 3600,
        avg_positions=mean("pos_mean"), avg_deployed_eth=mean("avg_deployed_wei") / E,
        utilization=mean("avg_deployed_wei") / max(1, mean("avg_book_wei")),
        holder_claimed_eth=mean("holder_claimed_wei") / E, holder_net_eth=mean("holder_net_realized_wei") / E,
        exit_days=float(np.mean([r["exit_days_elapsed"] for r in done])) if done else None,
        operating_end_backlog=mean("operation_end_backlog"))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=400)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 4))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--out", default=str(ROOT / "docs/receipts/keeper-economics.json"))
    a = ap.parse_args()
    out = Path(a.out)
    parts = ROOT / "sim/data/keeper-assess-parts"  # gitignored; per-row results
    parts.mkdir(parents=True, exist_ok=True)
    w = FM.window(F.ROOT / "data/fwa.sqlite", FM.PIN["timestamp"])
    w["user_gas"] = C.receipt_gas()
    for label, config, principal, gas, overrides in SCENARIOS:
        if a.only and label not in a.only:
            continue
        part = parts / (label.replace("|", "_") + f"_{a.seeds}.json")
        if part.exists():
            continue
        jobs = [(w, label, config, principal, gas, overrides, s) for s in range(1, a.seeds + 1)]
        with ProcessPoolExecutor(a.workers) as pool:
            rows = list(pool.map(one, jobs, chunksize=4))
        part.write_text(json.dumps(dict(label=label, config=config, principal_wei=principal, gas=gas,
                                        overrides=overrides, summary=summarize(rows), rows=rows)))
        s = summarize(rows)
        print(f"{label}: median {s['median_return']:+.1%} mean {s['mean_return']:+.1%} p10 {s['p10_return']:+.1%} "
              f"P(loss) {s['p_loss']:.1%} keeper {s['routine_keeper_eth']:.3f} ETH", flush=True)
    results = {p.stem: json.loads(p.read_text()) for p in sorted(parts.glob(f"*_{a.seeds}.json"))}
    out.write_text(json.dumps(dict(
        pin=FM.PIN, seeds=a.seeds, command=[sys.executable, *sys.argv], method=__doc__.split("Usage:")[0].strip(),
        scenarios={k: {x: v[x] for x in ("label", "config", "principal_wei", "gas", "overrides", "summary")}
                   for k, v in results.items()}), indent=1) + "\n")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
