#!/usr/bin/env python3
"""Bounded illustrative operating/complete-exit comparison, never an annual return gate."""
import argparse
import hashlib
import importlib.util
import json
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import forward as F

ROOT = Path(__file__).resolve().parent.parent
DB = F.DB
OUT = ROOT / 'docs/receipts'


def context(database):
    F.DB = database
    F.POOL, F.STAGING = F.pool_snapshot(), F.staging_delays(30)
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
    end, block = db.execute('SELECT max(ts),max(block) FROM logs').fetchone()
    statuses = [int(json.loads(a)['status']) for a, in db.execute(
        "SELECT args FROM logs WHERE event='AcquisitionProcessed' AND ts>=?", (end - 30 * F.DAY,))]
    successes = sum(s == 2 for s in statuses)
    F.REFUNDS_PER_SELECTION = (len(statuses) - successes) / successes
    db.close()
    return dict(block=block, timestamp=end, completed30d=len(statuses), successful30d=successes), receipt_gas()


def receipt_gas():
    """Explicit historical caller-cost proxies; current keeper receipts are separate evidence."""
    actions = [json.loads(line) for line in (OUT / 'review-journal-replacement-actions.jsonl').read_text().splitlines()]
    deposit = next(a['receipt'] for a in actions if a.get('function') == 'deposit()')
    old = json.loads((OUT / 'review-journal-calibration-summary.json').read_text())['exit']['rows']
    gas = {'deposit': int(deposit['gasUsed'], 16),
           'request_redeem': next(r['billed_gas'] for r in old if r['label'].startswith('exit request')),
           'claim': next(r['billed_gas'] for r in old if r['label'] == 'exit claim'),
           'checkpoint': next(r['billed_gas'] for r in old if r['label'] == 'exit checkpoint'),
           'unexposed_sync': 121_884}
    return gas


def case(values, principal, seed, volume, price, gas, days=30, exit_days=30, rescue=False, trace=None, timing=None):
    values = dict(values)
    if price == 0:
        values['maxTipWei'] = 0
    sc = F.Scenario(volume=F.const(volume), gwei=max(0, price - values['maxTipWei'] / F.GWEI), deposit_wei=principal,
                    exit_all=True, exit_days=exit_days, user_gas_proxy=gas,
                    holder_rescue_sync=rescue, trace_sink=trace, **(timing or {}))
    return F.run(sc, 1 if principal == 15 * 10**16 else 27 if principal < 2 * F.E else 100,
                 seed, days=days, values=values)


def load_baseline(ref, directory):
    """Load the recorded implementation with only an aggregate-input adapter.

    The old timed driver used the foreign position array solely for sum(1/backing).
    Replacing that initialization with the identical authenticated sum does not invent
    foreign records or alter policy, accounting, event order or transaction eligibility.
    """
    commit = subprocess.check_output(['git', 'rev-parse', ref], cwd=ROOT, text=True).strip()
    hashes = {}
    for relative in ('sim/forward.py', 'sim/vault.py', 'keeper/policy.py', 'deploy/mainnet.json'):
        contents = subprocess.check_output(['git', 'show', f'{commit}:{relative}'], cwd=ROOT)
        hashes[relative] = hashlib.sha256(contents).hexdigest()
        if relative == 'sim/forward.py':
            old = ('    others = POOL\n'
                   '    if sc.get("pool_scale", 1.0) != 1.0:\n'
                   '        others = rng.choice(POOL, int(len(POOL) * sc["pool_scale"]))\n'
                   '    W_o, N_o = float(np.sum(1 / others)), len(others)\n')
            assert contents.decode().count(old) == 1, 'baseline aggregate adapter no longer matches'
            contents = contents.decode().replace(old, '    W_o = float(sc["foreign_pool_weight"])\n').encode()
        target = directory / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(contents)
    saved = {name: sys.modules.get(name) for name in ('policy', 'vault')}
    old_path = list(sys.path)
    try:
        for name in saved:
            sys.modules.pop(name, None)
        spec = importlib.util.spec_from_file_location('complete_pass_baseline', directory / 'sim/forward.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = old_path
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return module, dict(commit=commit, source_sha256=hashes,
                        adapter='Foreign aggregate initialization only: W_o=float(sc[foreign_pool_weight]).')


def complete_pass(args):
    """Timed operating and actually claimed exit comparisons with no historical DB dependency."""
    source = json.loads(args.aggregate_context.read_text())
    snapshot = source['snapshots'][args.snapshot]
    assert snapshot['settlementWindow'] == F.OperatingClock.SETTLEMENT
    gas = receipt_gas()
    timing = dict(timed=True, start_timestamp=snapshot['timestamp'], poll_seconds=60,
                  receipt_seconds=36, vrf_seconds=60, purchaser_response_seconds=120,
                  foreign_pool_weight=snapshot['totalWeight'] / F.E,
                  refunds_per_selection=5090 / 13191, exempt=snapshot['oracleExemptPacks'])
    paths = ['sim/forward.py', 'sim/vault.py', 'sim/efficient_operating.py', 'keeper/policy.py',
             'deploy/canary.json', 'deploy/canary.example.json', 'deploy/mainnet.json']
    frozen = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    sizes = [('larger', 'mainnet', 68 * 10**17),
             ('canary', 'canary.example', 1_960_100_000_000_000_000),
             ('first-position', 'canary.example', 15 * 10**16)]
    rows = []
    short_regression = []
    diagnostics = []
    seeds = [int(seed) for seed in args.seeds.split(',')]
    cache_path = ROOT / 'sim/out/complete-operating-cache.json'
    cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    with tempfile.TemporaryDirectory(prefix='shapes-complete-baseline-') as temp:
        baseline, baseline_source = load_baseline(args.baseline_ref, Path(temp))
        previous_configs = {name: json.loads(subprocess.check_output(
            ['git', 'show', f'{baseline_source["commit"]}:deploy/{name}.json'], cwd=ROOT))
            for name in ('canary.example', 'mainnet')}

        def execute(implementation, version, params, principal, volume, price, seed, days, exit_days, clock):
            params = dict(params)
            if price == 0:
                params['maxTipWei'] = 0
            core = baseline_source if version == 'baseline' else {p: frozen[p] for p in ('sim/forward.py', 'sim/vault.py', 'keeper/policy.py')}
            inputs = dict(core=core, params=params, principal=principal, volume=volume, price=price,
                          seed=seed, days=days, exit_days=exit_days, timing=clock, gas=gas)
            key = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
            if key not in cache:
                scenario = implementation.Scenario(volume=implementation.const(volume),
                    gwei=max(0, price - params['maxTipWei'] / F.GWEI), deposit_wei=principal,
                    exit_all=True, exit_days=exit_days, user_gas_proxy=gas, **clock)
                result = implementation.run(scenario, 1, seed, days=days, values=params)
                assert result['ledger_gap_wei'] == 0 and result['unknown_user_gas_calls'] == 0
                assert result['routine_keeper_paid_wei'] <= result['routine_period_permission_upper_wei']
                result.pop('ret', None)
                cache[key] = dict(inputs=inputs, result=result)
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix('.tmp')
                temporary.write_text(json.dumps(cache, indent=2) + '\n')
                temporary.replace(cache_path)
            return dict(cache[key]['result'])

        historical = source['snapshots']['recorded']
        regression_timing = dict(timing, start_timestamp=historical['timestamp'],
                                 foreign_pool_weight=historical['totalWeight'] / F.E, exempt=True)
        for version, implementation in [('baseline', baseline), ('candidate', F)]:
            params = json.loads((ROOT / 'deploy/mainnet.json').read_text())
            params.update(routineCapWei=3 * 10**17, routineRatePerDayWei=10**16)
            result = execute(implementation, version, params, 68 * 10**17, 609, .2, 8, 2, 2, regression_timing)
            short_regression.append(dict(version=version, **result))
            print(f'short {version}: exit={result["exit_complete"]} funded={result["fully_paid_routine"]} '
                  f'harvest={result["keeper_paid_harvest_wei"] / F.E:.6f}eth', flush=True)
        cases = [(size, config, principal, price, volume, seed)
                 for size, config, principal in sizes for price in (.2, .5, 0)
                 for volume in (71, 439.7) for seed in seeds]
        priority = {('larger', .5, 439.7): 0, ('canary', .2, 439.7): 1}
        cases.sort(key=lambda row: priority.get((row[0], row[3], row[4]), 2))
        for size, config, principal, price, volume, seed in cases:
            values = previous_configs[config]
            versions = [('baseline', baseline), ('candidate', F)] if args.paired_matrix else [('candidate', F)]
            for version, implementation in versions:
                params = dict(values)
                result = execute(implementation, version, params, principal, volume, price, seed,
                                 args.days, args.exit_days, timing)
                rows.append(dict(version=version, size=size, config=config, permissions='previous-default',
                                 seed=seed, total_price_gwei=price, successful_volume_per_day=volume,
                                 holder_realized_return_bps=(result['holder_net_realized_wei'] * 10_000
                                     / result['holder_paid_in_wei'] if result['exit_complete'] else None),
                                 **result))
                print(f'{version} {size} {price}gwei {volume}/day seed{seed}: '
                      f'exit={result["exit_complete"]} funded={result["fully_paid_routine"]} '
                      f'creator={result["creator_mint_fees_wei"] / F.E:.6f}eth', flush=True)
                if (version == 'candidate' and volume == 439.7 and ((size == 'larger' and price == .5) or (size == 'canary' and price in (.2, .5)))):
                    proposals = [('previous-limit-comparison', 3 * 10**17, 10**16, args.days),
                                 ('applied-refill', 10**17 if size == 'larger' else 3 * 10**16,
                                  2 * 10**16 if size == 'larger' else 10**16, args.days)]
                    if size == 'larger':
                        proposals += [('applied-refill-90days', 10**17, 2 * 10**16, 90)]
                    for label, cap, rate, operating_days in proposals:
                        maximum = dict(params, routineCapWei=cap, routineRatePerDayWei=rate)
                        stress = execute(F, version, maximum, principal, volume, price, seed,
                                         operating_days, args.exit_days, timing)
                        diagnostics.append(dict(size=size, seed=seed, config=config,
                            permissions=label, total_price_gwei=price,
                            successful_volume_per_day=volume, **stress))
                        print(f'diagnostic {size} {label}: exit={stress["exit_complete"]} '
                              f'funded={stress["fully_paid_routine"]} '
                              f'budget={stress["operation_end_routine_budget_wei"] / F.E:.6f}eth', flush=True)
    assert frozen == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
    report = dict(source_sha256=frozen, baseline=baseline_source, aggregate_context=source,
                  configuration_inputs={name: json.loads((ROOT / f'deploy/{name}.json').read_text())
                                        for name in ('canary', 'canary.example', 'mainnet')},
                  previous_configuration_inputs=previous_configs,
                  selected_snapshot=args.snapshot, timing=timing, user_gas_proxy=gas,
                  command=[sys.executable, *sys.argv], rows=rows, short_regression=short_regression,
                  short_regression_timing=regression_timing, permission_diagnostics=diagnostics,
                  source_of_funds='Initial seed, holder principal and actually collected FWA fees only. No topups, forecast fee credits, operator losses or creator fee recycling.',
                  limits=[
                      'Generated acquisition and purchaser events are conditional counterfactual scenarios, not authenticated VRF replay or observed future volume.',
                      'The static authenticated foreign totalWeight is sufficient for this model. No foreign listing distribution was reconstructed or fabricated; the external pool does not react to the vault.',
                      '5090 refunded /13191 successful completions is the previously archived30day ratio, held constant as an explicit scenario input.',
                      'The two-day comparison retains the prior conditional exemption assumption with the recorded pool weight for comparability. Packs were not actually oracle-exempt at that recorded block; the primary matrix uses the independently authenticated current exemption and current weight.',
                      'The18comparison rows explicitly load the previous default configurations from the baseline commit. Applied refill diagnostics match current mainnet0.1ETH/0.02ETH per day and canary0.03ETH/0.01ETH per day; the former0.3ETH cap/0.01ETH per day limit is retained as a separate comparison. No permission setting adds cash.',
                      'Candidate policy receives the same16-ID indexed active and terminal classes as the keeper, including text-ID ordering and persistent owed rotation. This fixes the prior model\'s unrestricted policy projection; the historical baseline remains the recorded implementation.',
                      'Transaction effects occur atomically on the fresh modeled read. The36second receipt delay spaces subsequent reads; inclusion races and reverted transaction costs are absent.',
                      'Keeper expenses are full quoted actual eligible work, not receipt-derived actual operator profit. Holder deposit/request/claim/checkpoint costs use historical receipt proxies and variable exit work uses its quoted gas component.',
                      'Zero gas removes both basefee and tip while retaining protocol mint fees and configured flat work fees.',
                      'A holder return is reported only after a complete actual modeled claim; any residual mark on an incomplete exit is kept separately. No annualization or expected return is claimed.'])
    target = OUT / f'complete-operating-{args.label}.json'
    target.write_text(json.dumps(report, indent=2) + '\n')
    print(f'Saved {target}: {len(rows)} timed scenario cases', flush=True)
    return report


def focused_checks(gas):
    values = json.loads((ROOT / 'deploy/canary.example.json').read_text())
    values.update(routineCapWei=3 * 10**17, routineRatePerDayWei=10**16)
    zero = case(values, 15 * 10**16, 8, 0, .2, gas, days=3, exit_days=10)
    assert zero['exit_complete'] and zero['journal_backlog'] == 0
    assert zero['holder_claimed_wei'] > 0 and zero['holder_net_realized_wei'] < 0
    assert zero['fees_received_wei'] == zero['backing_lost_wei'] == 0
    assert zero['mint_fees_wei'] == zero['creator_mint_fees_wei'] >= 10**15
    assert zero['keeper_paid_unlist_wei'] == zero['keeper_paid_liquidate_wei'] == 0
    assert zero['holder_calls_unlist'] > 0 and zero['holder_calls_liquidate'] > 0
    assert zero['ledger_gap_wei'] == zero['unknown_user_gas_calls'] == 0
    assert zero['physical_assets_wei'] + zero['holder_claimed_wei'] + zero['keeper_paid_wei'] + zero['mint_fees_wei'] == 10**16 + zero['holder_paid_in_wei']
    busy = case(values, 15 * 10**16, 8, 439.7, .2, gas, days=5, exit_days=10)
    assert busy['ledger_gap_wei'] == 0 and busy['unpaid_routine_calls'] == 0
    limited = dict(values, routineCapWei=3 * 10**15, routineRatePerDayWei=0)
    blocked = case(limited, 15 * 10**16, 8, 20_000, .2, gas, days=4, exit_days=5)
    assert blocked['routine_unfunded_attempts'] > 0 and not blocked['uninterrupted_routine_funding']
    assert blocked['routine_keeper_paid_wei'] <= limited['routineCapWei'] and blocked['unpaid_routine_calls'] == 0
    assert blocked['ledger_gap_wei'] == 0
    rescued = case(limited, 15 * 10**16, 8, 20_000, .2, gas, days=4, exit_days=5, rescue=True)
    assert rescued['exit_complete'] and rescued['holder_calls_sync'] > 0 and rescued['unpaid_routine_calls'] > 0
    assert rescued['ledger_gap_wei'] == 0 and not rescued['fully_paid_routine']
    assert rescued['operation_end_cash_wei'] == blocked['operation_end_cash_wei']
    assert rescued['operation_end_keeper_paid_wei'] == blocked['operation_end_keeper_paid_wei']
    return dict(zero_demand_roundtrip=zero, busy_roundtrip=busy, permission_shortfall=blocked,
                explicit_holder_rescue=rescued)


def timed_checks(history, gas):
    """Conditional scenarios plus authentic fixture clock/accounting evidence, no RPC stubs."""
    values = json.loads((ROOT / 'deploy/mainnet.json').read_text())
    values.update(routineCapWei=3 * 10**17, routineRatePerDayWei=10**16)
    timing = dict(timed=True, start_timestamp=history['timestamp'], poll_seconds=60,
                  receipt_seconds=36, vrf_seconds=60)
    rows, traces = {}, {}
    for name, response, volume in [('zero', 120, 0), ('timely', 120, 609),
                                    ('silent', None, 609), ('late', 7200, 609)]:
        trace = []
        rows[name] = case(values, 68 * 10**17, 8, volume, .2, gas, days=2, exit_days=2,
                          trace=trace, timing=dict(timing, purchaser_response_seconds=response))
        traces[name] = trace
        r = rows[name]
        assert r['ledger_gap_wei'] == 0 and not r['unknown_user_gas_calls']
        assert r['routine_keeper_paid_wei'] <= r['routine_period_permission_upper_wei']
        assert all(t['timestamp'] % F.OperatingClock.INTERVAL >= F.OperatingClock.BLACKOUT_START
                   for t in trace if t['action'] == 'checkpoint')
        intervals = [t['timestamp'] // F.OperatingClock.INTERVAL for t in trace if t['action'] == 'checkpoint']
        assert len(intervals) == len(set(intervals))
        assert all(t['timestamp'] >= history['timestamp'] + 2 * F.DAY for t in trace if t['action'] == 'request-redeem')
        assert all(t['timestamp'] >= history['timestamp'] for t in trace if t['action'] == 'claim')
    assert rows['zero']['exit_complete'] and rows['zero']['holder_claimed_wei'] > 0
    assert rows['zero']['fees_received_wei'] == rows['zero']['backing_lost_wei'] == 0
    assert rows['timely']['exit_complete'] and rows['timely']['purchaser_responses'] > 0
    assert rows['timely']['expired_backing_reclaims'] == rows['timely']['late_purchaser_responses'] == 0
    assert rows['silent']['expired_backing_reclaims'] > 0 and not rows['silent']['purchaser_responses']
    assert rows['late']['expired_backing_reclaims'] > 0
    assert rows['late']['late_purchaser_responses'] == rows['late']['purchaser_responses']
    # The driver does not postpone every return/relisting until the next daily step.
    trace = traces['timely']
    response_times = [t['timestamp'] for t in trace if t['action'] == 'purchaser-response']
    assert any(a < b['timestamp'] < (a // F.DAY + 1) * F.DAY
               for a in response_times for b in trace if b['action'] == 'list')
    # Real allocation times distinguish an allocation that can reach the next blackout
    # before expiry from one that cannot. These are recorded events, not invented RPC results.
    fixtures = json.loads((ROOT / 'test/fixtures/selection.json').read_text())
    phases = {}
    for block, fixture in fixtures.items():
        at = fixture['fulTimestamp']
        until = (F.OperatingClock.BLACKOUT_START - at % F.OperatingClock.INTERVAL) % F.OperatingClock.INTERVAL
        phases[block] = dict(allocated_at=at, seconds_to_blackout=until, expiry=at + 3600)
    assert sorted(v['seconds_to_blackout'] for v in phases.values()) == [1429, 37213]
    # The same recorded position projection crosses the policy's exact eligibility edge.
    source_trace = [json.loads(line) for line in (OUT / 'current-three-arg-reconcile-trace.jsonl').read_text().splitlines()]
    selected = next(r for r in source_trace if r['step'] == 'selected')['positions'][0]
    state = F.charge_state(150_000_000, 1)
    state.listings = [F.policy.Listing(selected['id'], F.ALLOCATED, allocated_at=selected['liveAllocatedAt'])]
    state.settlement_window = 3600
    state.now = selected['liveAllocatedAt'] + 3599
    assert not any(a[0] == 'sync' for a in F.policy.plan(state))
    state.now += 1
    assert any(a[0] == 'sync' and selected['id'] in a[1] for a in F.policy.plan(state))
    # Legacy half-redemption still uses the archived daily path, with exact share arithmetic.
    legacy = F.run(F.Scenario(volume=F.const(15), gwei=.15, redeem=[(10, .5)]), 30, 8, days=20)
    assert legacy['checkpoints'] == 2 and legacy['external_exit_gas_proxy_wei'] > 0 and legacy['ledger_gap_wei'] == 0
    return dict(timing=timing, rows=rows, traces=traces, authentic_fixture_phases=phases,
                legacy_partial_redemption=legacy,
                limits=['Conditional generated request/completion times and purchaser choices are scenario assumptions, not real VRF replay or observed purchaser response behavior.',
                        'Effects occur atomically at the fresh modeled read;36seconds delay the next receipt-confirmed read. This optimistic inclusion assumption does not model fees, reverted races, variable block time or transaction latency across a boundary.',
                        'At exact timestamp ties, market events precede keeper reads. Purchasers may respond after3600seconds until reclaim wins; expiry itself does not transfer assets.',
                        'Static recorded foreign pool and per-completion fee/selection approximation remain. Successful journal compensation and keeper profitability still require separate actual receipts/preflight.',
                        'NFT-reclaim expiry branch is implemented but not reached by these accepted-backing scenarios; no fabricated low-backing protocol fixture is supplied.',
                        'These short conditional paths validate clock/accounting interactions. They do not reproduce the prepriced-holder cash-cycle or establish recommended budget, expected returns or annual acceptance.'])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--label', default='baseline')
    ap.add_argument('--db', type=Path, default=DB)
    ap.add_argument('--self-check-only', action='store_true')
    ap.add_argument('--timed-checks', action='store_true', help='focused opt-in timestamp scenarios only; never runs the matrix')
    ap.add_argument('--seeds', default='3,8,19')
    ap.add_argument('--complete-pass', action='store_true', help='matched timed baseline/candidate operating and complete-exit comparison')
    ap.add_argument('--aggregate-context', type=Path, default=OUT / 'complete-operating-context.json')
    ap.add_argument('--snapshot', choices=('recorded', 'current'), default='current')
    ap.add_argument('--baseline-ref', default='e9cee61')
    ap.add_argument('--paired-matrix', action='store_true', help='also run historical baseline for every long scenario')
    ap.add_argument('--days', type=int, default=30)
    ap.add_argument('--exit-days', type=int, default=30)
    a = ap.parse_args()
    if a.complete_pass:
        complete_pass(a)
        return
    history, gas = context(a.db.resolve())
    if a.timed_checks:
        paths = ['sim/forward.py', 'sim/efficient_operating.py', 'sim/vault.py', 'keeper/policy.py']
        frozen = {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
        result = timed_checks(history, gas)
        assert frozen == {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in paths}
        result.update(context=history, source_sha256=frozen, command=[sys.executable, *sys.argv], exit_status=0)
        (OUT / 'efficient-operating-timed-checks.json').write_text(json.dumps(result, indent=2) + '\n')
        print('PASS four conditional timed scenarios, exact fixture expiry boundary, blackout/interval/claim checks and legacy partial-redemption compatibility')
        return
    checks = focused_checks(gas)
    paths = ['sim/forward.py', 'sim/vault.py', 'sim/efficient_operating.py', 'keeper/policy.py',
             'src/PackVault.sol', 'src/VaultLib.sol', 'deploy/mainnet.json', 'deploy/canary.example.json']
    sha = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
    frozen = {p: sha(p) for p in paths}
    rows, rescue_rows, cash_cycle_traces = [], [], []
    if not a.self_check_only:
        sizes = [('first-position', 'canary.example', 15 * 10**16),
                 ('canary', 'canary.example', 1_960_100_000_000_000_000), ('larger', 'mainnet', 68 * 10**17)]
        for size, config, principal in sizes:
            for permission in ('configured', 'existing-hard-max-proposal'):
                values = json.loads((ROOT / f'deploy/{config}.json').read_text())
                if permission != 'configured':
                    values.update(routineCapWei=3 * 10**17, routineRatePerDayWei=10**16)
                for price in (.2, .5):
                    for volume in (history['successful30d'] / 30, 71, 0):
                        seeds = [8] if volume == 0 else [int(s) for s in a.seeds.split(',')]
                        for seed in seeds:
                            r = case(values, principal, seed, volume, price, gas)
                            rows.append(dict(size=size, config=config, permissions=permission, total_price_gwei=price,
                                             successful_volume_per_day=volume, seed=seed, **r))
                            if not r['exit_complete']:
                                trace = [] if (size, permission, price, volume, seed) == ('larger', 'existing-hard-max-proposal', .2, 71, 3) else None
                                rescued = case(values, principal, seed, volume, price, gas, rescue=True, trace=trace)
                                for field in ('operation_end_backlog', 'operation_end_cash_wei', 'operation_end_keeper_paid_wei', 'operation_end_fees_received_wei'):
                                    assert rescued[field] == r[field], ('rescue changed prior operation', field)
                                assert rescued['unpaid_routine_calls'] > 0 or not rescued['exit_complete']
                                rescue_rows.append(dict(size=size, config=config, permissions=permission, total_price_gwei=price,
                                                        successful_volume_per_day=volume, seed=seed, **rescued))
                                if trace is not None:
                                    strict_trace = []
                                    case(values, principal, seed, volume, price, gas, trace=strict_trace)
                                    cash_cycle_traces.append(dict(size=size, price=price, seed=seed, strict=strict_trace, holder_rescue=trace))
                        print(f'{len(rows)} cases completed: {size}/{permission}/{price}gwei/{volume:g}perday', flush=True)
    assert frozen == {p: sha(p) for p in paths}, 'source/config changed during model batch'
    result = dict(context=history, source_sha256=frozen, database_path=str(a.db.resolve()),
                  database_sha256=hashlib.sha256(a.db.read_bytes()).hexdigest(),
                  command=[sys.executable, *sys.argv], quote_schedule=F.policy.Q,
                  job_bounds=F.policy.MAX_BATCH, self_checks=checks, user_gas_proxy=gas, rows=rows,
                  holder_rescue_diagnostics=rescue_rows, cash_reconciliation_cycle_trace=cash_cycle_traces,
                  source_of_funds='Vault unencumbered ETH from initial seed/holder capital and received FWA income. No sponsor, donation, mint revenue recycling or minimum-TVL rule.',
                  permission_proposal='0.3ETH initial routine cap and0.01ETH/day refill use existing hard maxima only; diagnostic model values, not deployed or owner-approved settings.',
                  limits=['Stochastic external events approximate daily timing and are not fork replay or a forecast. Current core must separately reconcile to fresh fork traces before interpreting these scenarios.',
                          'Primary comparison requires full quoted routine sync pay. Other necessary exit calls may be holder-executed with explicit gas cost and actual clipped pay. Real keeper can sometimes accept clipped pay if its actual preflight costs remain covered. This conservative quote model is not an exact availability forecast.',
                          'Only primary incomplete cases receive a separate opt-in final-holder minPay0 sync rescue diagnostic. Rescued exits are not reported as fully funded routine operation; the prior operating prefix is asserted identical.',
                          'User deposit/request/claim and any unpaid checkpoint gas use historical Q400 actual billed-gas counts scaled to matched scenario prices; unexposed sync uses historical caller-meter-plus-intrinsic121884gas proxy, not true gross or billed gas. Other unpaid variable-size maintenance uses its gas-component quote as a proxy. No25percent gas-limit padding is treated as billed gas.',
                          'D64 unlist/liquidate caller costs reduce holder cash return. Creator mint fees remain separate expenses and are never treated as operating subsidies.',
                          'Reported complete exits actually claim and clear their last modeled backlog; blocked cases retain explicit entitlements and are not realized return observations.',
                          'Three fixed seeds are illustrative sensitivity, not confidence intervals or the signed annual-return hurdle.'],
                  things_that_do_not_make_sense=['Available spending permission cannot rescue exhausted free cash. A small vault can still fail economically while every wei reconciles.',
                                               'A positive end mark with unclaimed/locked assets is not a completed holder return.',
                                               'The old caller liquidation quote omitted packed Shape burn work; this model now includes it.'])
    (OUT / f'efficient-operating-{a.label}.json').write_text(json.dumps(result, indent=2) + '\n')
    if rows:
        all_cases = rows + rescue_rows
        md = ['# Operating costs and complete holder exits\n', 'Thirty operating days plus at most thirty exit days, with foreign activity continuing until the modeled claim completes. All amounts are ETH. Three seeds per active-volume regime; one zero-demand seed. No subsidy or minimum TVL. Permission changes below are model proposals only.\n',
              '| Outcome | Bounded result |', '|---|---|',
              f'| Exact model asset ledger | {len(all_cases)}/{len(all_cases)} zero-gap cases |',
              f'| Primary complete exits | {sum(r["exit_complete"] for r in rows)}/{len(rows)}; incomplete cases retain explicit rights/assets |',
              f'| Primary fully paid routine work without funding stalls | {sum(r["fully_paid_routine"] for r in rows)}/{len(rows)} |',
              f'| Separate final-holder rescue | {sum(r["exit_complete"] for r in rescue_rows)}/{len(rescue_rows)} finish; these are not funded-operation passes |',
              '| Creator operating subsidy | 0 in every case; mint fees remain expenses |',
              '| Annual return/release acceptance | Not established; caller gas proxies and stochastic timing remain limitations |\n',
              '| Size | Permission | Price gwei | Successful/day | Complete exits | Claimed-return range | Routine spend range ETH |', '|---|---|---:|---:|---:|---:|---:|']
        for keys in dict.fromkeys((r['size'], r['permissions'], r['total_price_gwei'], r['successful_volume_per_day']) for r in rows):
            group = [r for r in rows if (r['size'], r['permissions'], r['total_price_gwei'], r['successful_volume_per_day']) == keys]
            complete = [r for r in group if r['exit_complete'] and not r['unknown_user_gas_calls']]
            returns = [100 * r['holder_net_realized_wei'] / r['holder_paid_in_wei'] for r in complete]
            label = f'{min(returns):+.2f}% to {max(returns):+.2f}%' if returns else 'incomplete'
            spend = [r['routine_keeper_paid_wei'] / F.E for r in group]
            md.append(f'| {keys[0]} | {keys[1]} | {keys[2]} | {keys[3]:g} | {len(complete)}/{len(group)} | {label} | {min(spend):.6f} to {max(spend):.6f} |')
        md += ['\nInitial-cap versus steady refill: configured canary 0.03 ETH / 0.0008 ETH per day; mainnet 0.1 ETH / 0.005 ETH per day. Proposed comparison 0.3 ETH / 0.01 ETH per day for both. No new ETH enters the vault. Per-run permission upper bounds use actual elapsed modeled time, independently of cash.\n',
               'Caller gas figures are labeled historical/quote proxies, not current standalone receipts. Raw results retain modeled claim payments, remaining entitlements, every operation expense, creator fees, sampled cash, budget stalls and exact zero-gap asset ledgers. No annual-return or launch acceptance is claimed.\n',
               "## Things that don't make sense\n", '- A generous allowance can pay expenses from depositor principal; that does not make the strategy profitable.\n', '- Successful bookkeeping can end in a blocked exit or a loss.\n', '- Actual receipt profitability and the current fork reconciliation remain separate evidence requirements.\n']
        md.insert(-4, f'\nSeparate holder-rescue diagnostics: {sum(r["exit_complete"] for r in rescue_rows)}/{len(rescue_rows)} primary incomplete cases finish by allowing holder-paid zero-minimum-pay sync after exit is requested. These are rescued exits, not fully funded operating passes. Their full caller gas proxy and actual clipped pay remain in the raw results.\n')
        (OUT / f'efficient-operating-{a.label}.md').write_text('\n'.join(md))
    print(f'PASS focused roundtrips, {len(rows)} primary cases and {len(rescue_rows)} explicit holder-rescue diagnostics; creator subsidy0', flush=True)


if __name__ == '__main__':
    main()
