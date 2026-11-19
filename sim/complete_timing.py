#!/usr/bin/env python3
"""Compact current-context operating/exit timing regressions with explicit scenario assumptions."""
import hashlib
import json
import sys
from pathlib import Path

import efficient_operating as C

ROOT, F = C.ROOT, C.F


def main():
    context = json.loads((C.OUT / 'complete-operating-context.json').read_text())
    snapshot = context['snapshots']['current']
    params = json.loads((ROOT / 'deploy/mainnet.json').read_text())
    params.update(routineCapWei=10**17, routineRatePerDayWei=2 * 10**16)
    sources = ['sim/complete_timing.py', 'sim/efficient_operating.py', 'sim/forward.py',
               'sim/vault.py', 'keeper/policy.py']
    frozen = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
    timing = dict(timed=True, start_timestamp=snapshot['timestamp'], poll_seconds=60,
                  receipt_seconds=36, vrf_seconds=60, foreign_pool_weight=snapshot['totalWeight'] / F.E,
                  refunds_per_selection=5090 / 13191, exempt=snapshot['oracleExemptPacks'])
    rows = []
    for name, response, volume, keep in [('timely', 120, 609, 0), ('late', 7200, 609, 0),
                                       ('silent', None, 609, 0), ('zero', 120, 0, 0),
                                       ('keep', 120, 609, 1)]:
        scenario = dict(timing, purchaser_response_seconds=response, keep=keep)
        result = C.case(params, 68 * 10**17, 8, volume, .2, C.receipt_gas(),
                        days=2, exit_days=2, timing=scenario)
        assert result['ledger_gap_wei'] == result['unknown_user_gas_calls'] == 0
        assert result['creator_mint_fees_wei'] == result['mint_fees_wei']
        assert result['routine_keeper_paid_wei'] <= result['routine_period_permission_upper_wei']
        result.pop('ret', None)
        row = dict(name=name, purchaser_response_seconds=response, keep_probability=keep,
                   successful_volume_per_day=volume, **result)
        if not result['exit_complete']:
            trace = []
            repeated = C.case(params, 68 * 10**17, 8, volume, .2, C.receipt_gas(),
                              days=2, exit_days=2, timing=scenario, trace=trace)
            assert repeated['holder_net_realized_wei'] == result['holder_net_realized_wei']
            row['final_events'] = trace[-20:]
        rows.append(row)
        print(f'{name}: exit={result["exit_complete"]} funded={result["fully_paid_routine"]} '
              f'creator={result["creator_mint_fees_wei"] / F.E:.6f}eth '
              f'net={result["holder_net_realized_wei"] / F.E:+.6f}eth', flush=True)
    regimes = {row['name']: row for row in rows}
    assert regimes['zero']['fees_received_wei'] == regimes['zero']['backing_lost_wei'] == 0
    assert regimes['timely']['purchaser_responses'] > 0 and regimes['timely']['expired_backing_reclaims'] == 0
    assert regimes['silent']['expired_backing_reclaims'] > 0 and regimes['silent']['purchaser_responses'] == 0
    assert regimes['late']['expired_backing_reclaims'] > 0
    assert regimes['late']['late_purchaser_responses'] == regimes['late']['purchaser_responses']
    assert regimes['keep']['creator_mint_fees_wei'] > regimes['timely']['creator_mint_fees_wei']
    assert all(row['exit_complete'] and row['fully_paid_routine'] and row['positions'] == 0
               and row['physical_assets_wei'] == row['vault_cash_wei'] for row in rows)
    assert frozen == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources}
    report = dict(command=[sys.executable, *sys.argv], source_sha256=frozen, snapshot=snapshot,
                  params=params, timing=timing, principal_wei=68 * 10**17, seed=8,
                  operating_days=2, maximum_exit_days=2, total_price_gwei=.2,
                  user_gas_proxy=C.receipt_gas(), rows=rows,
                  limits=['Conditional generated acquisitions and purchaser decisions, not authenticated VRF replay or forecasts.',
                          'Current authenticated aggregate pool weight and oracle exemption are fixed throughout each case.',
                          'Full fixed routine quotes are paid from actual unprotected vault cash and permission. Holders pay explicit exit gas proxies; no loss-making operator is assumed.',
                          'A positive net is a completely claimed conditional result after the recorded gas proxies, with no annualization. Incomplete cases retain explicit assets and liabilities.',
                          'The keep case models immediate purchaser retention; silent/late cases exercise expiry and real settlement-window ordering in the integer model. Separate fork tests provide protocol evidence.'])
    (C.OUT / 'complete-timing-regressions.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__':
    main()
