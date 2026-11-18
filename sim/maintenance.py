#!/usr/bin/env python3
"""Exact quote/reserve lower bound from recorded global work, not a return simulation.

Own selection/terminal costs, listings, harvests and other work are additional. Maximum budget
availability is an upper bound; budgets are spending permissions, not ETH balances. No chain calls.
"""
import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'keeper'))
import policy

DAY = 86400
E = 10**18


def global_quote(entries, batch, base, per_entry):
    calls = -(-entries // batch)
    return calls, calls * base + entries * per_entry


def analyze(database, values_path):
    db = sqlite3.connect(f'file:{Path(database).resolve()}?mode=ro', uri=True)
    end, block = db.execute('SELECT max(ts),max(block) FROM logs').fetchone()
    statuses = [int(json.loads(a)['status']) for (a,) in db.execute(
        "SELECT args FROM logs WHERE event='AcquisitionProcessed' AND ts>=?", (end - 30 * DAY,))]
    db.close()
    if not statuses or any(s not in (2, 3, 4) for s in statuses):
        raise ValueError('history must contain actual terminal acquisition records')
    p = json.loads(Path(values_path).read_text())
    entries, successful = len(statuses), statuses.count(2)
    calls, gas = global_quote(entries, policy.MAX_BATCH['journal'], policy.Q['sync'], policy.Q['journal'])
    rows = []
    for basefee in (150_000_000, 450_000_000, 1_000_000_000):
        price = min(basefee + p['maxTipWei'], p['gasCeilingWei'])
        pay = gas * price  # V1, no work fee for foreign/refunded journal records
        budget = p['routineCapWei'] + 30 * p['routineRatePerDayWei']
        rows.append(dict(basefee_wei=basefee, keeper_bid_wei=basefee + p['maxTipWei'], quote_price_wei=price,
                         minimum_global_quote_30d_wei=pay, minimum_global_quote_per_day_wei=-(-pay // 30),
                         maximum_budget_30d_wei=budget, refill_per_day_wei=p['routineRatePerDayWei'],
                         shortfall_30d_wei=max(0, pay - budget),
                         steady_refill_shortfall_per_day_wei=max(0, -(-pay // 30) - p['routineRatePerDayWei'])))
    state = policy.State(now=0, gas_price=200_000_000, base_fee=150_000_000,
                         gas_ceiling=p['gasCeilingWei'], max_tip=p['maxTipWei'], markup_bps=p['payMarkupBps'],
                         share_bps=p['keeperShareBps'], k=0, backing=0, min_edge_bps=p['minEdgeBps'],
                         mint_fee=10**15, settlement_window=0, blackout=False, queue_drained=True,
                         checkpoint_done_this_interval=False, work_fee=p['workFeeWei'],
                         essential_cap=p['essentialCapWei'], essential_ceiling=p['essentialCeilingWei'])
    catchup = (policy.Q['sync'] + policy.MAX_BATCH['journal'] * policy.Q['journal']) * p['gasCeilingWei']
    return dict(history=dict(end_block=block, end_timestamp=end, start_timestamp=end - 30 * DAY,
                             completed=entries, successful=successful, refunded=entries - successful),
                values_file=str(Path(values_path).resolve().relative_to(ROOT)),
                policy_sha256=hashlib.sha256((ROOT / 'keeper/policy.py').read_bytes()).hexdigest(),
                journal_batch=policy.MAX_BATCH['journal'], minimum_calls=calls,
                baseline_quoted_gas=gas, cases=rows, reserve_wei=p['reserveWei'],
                keeper_reserve_need_wei=policy.reserve_need(state),
                one_foreign_batch_quote_at_ceiling_wei=catchup,
                one_batch_affordable_from_retained_reserve=catchup <= p['reserveWei'],
                limitations=['Optimistic fully packed calls across the whole30days; actual catchup can cost more.',
                             'All entries receive only the global component here; own selection/terminal/prune work is additional.',
                             'No claim of keeper profit, actual billed gas, ETH funding from future income, or a return-gate pass.',
                             'At gas above the routine ceiling a no-loss keeper waits; exits can still run unpaid.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', default=str(ROOT / 'sim/data/fwa.sqlite'))
    parser.add_argument('--values', default=str(ROOT / 'deploy/mainnet.json'))
    args = parser.parse_args()
    # Call boundary matters: 17 records require a second complete call, never one unbounded batch.
    assert global_quote(16, 16, 100, 20) == (1, 420)
    assert global_quote(17, 16, 100, 20) == (2, 540)
    print(json.dumps(analyze(args.database, args.values), indent=2))


if __name__ == '__main__':
    main()
