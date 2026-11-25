#!/usr/bin/env python3
"""Frozen, resumable manager counterfactual Monte Carlo; never sends a transaction."""
import argparse
import fcntl
import gzip
import hashlib
import json
import math
import os
import statistics
import sqlite3
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from fractions import Fraction
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
Z95 = statistics.NormalDist().inv_cdf(.975)
Z_PAIR = statistics.NormalDist().inv_cdf(.9875)
CELLS = tuple(dict(id=f"b{bps}-g{gas}", backing_bps=bps, total_gas_gwei=gas)
              for bps in (70000, 50000) for gas in (.2, .5))
SOURCE_FILES = ('sim/manager_monte_carlo.py', 'sim/test_manager_monte_carlo.py', 'sim/test_forward_randomness.py',
                'sim/test_funding_holds.py', 'sim/forward.py', 'sim/manager.py', 'sim/vault.py',
                'sim/manager_reconcile.py', 'keeper/test_policy.py', 'keeper/rehearse_manager_r2.py',
                'sim/formal.py', 'sim/replay.py', 'keeper/policy.py', 'keeper/config.py', 'keeper/keeper.py',
                'deploy/manager.json',
                'deploy/mint-fee-observation.json')
WORKER = None


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def distribution(values, confidence_z=Z95, strata=None):
    """Normal-approximation Monte Carlo mean interval; percentiles use linear interpolation."""
    if (strata is not None and len(strata) != len(values)) or any(not math.isfinite(x) for x in values):
        raise ValueError('finite observations and one stratum per value are required')
    if not values:
        return dict(n=0, mean=None, median=None, mean_mcse=None, mean_ci=None, p05=None, p95=None)
    def quantile(q):
        at = (len(ordered) - 1) * q
        left = math.floor(at)
        return ordered[left] + (ordered[math.ceil(at)] - ordered[left]) * (at - left)
    ordered = sorted(values)
    mean = statistics.fmean(values)
    if strata is None:
        se = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
    else:
        groups = [[x for x, label in zip(values, strata) if label == key] for key in sorted(set(strata))]
        se = math.sqrt(sum((len(group) / len(values)) ** 2 * statistics.variance(group) / len(group)
                           for group in groups)) if all(len(group) > 1 for group in groups) else None
    return dict(n=len(values), mean=mean, median=statistics.median(values), mean_mcse=se,
                mean_ci=[mean-confidence_z*se, mean+confidence_z*se] if se is not None else None,
                p05=quantile(.05), p95=quantile(.95))


def wilson(successes, n, z=Z95):
    if not 0 <= successes <= n:
        raise ValueError('invalid binomial counts')
    if not n:
        return dict(events=0, n=0, probability=None, wilson_ci=None)
    p = successes / n
    divisor = 1 + z*z/n
    center = (p + z*z/(2*n)) / divisor
    radius = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / divisor
    return dict(events=successes, n=n, probability=p, wilson_ci=[max(0, center-radius), min(1, center+radius)])


def probability(rows, predicate):
    groups = {key: [row for row in rows if row['window'] == key] for key in sorted({r['window'] for r in rows})}
    total = len(rows)
    if len(groups) <= 1:
        return wilson(sum(bool(predicate(row)) for row in rows), total)
    # Simultaneous per-stratum intervals imply a conservative interval for the fixed mixture.
    z = statistics.NormalDist().inv_cdf(1-.025/len(groups))
    bounds = [0., 0.]
    for group in groups.values():
        interval = wilson(sum(bool(predicate(row)) for row in group), len(group), z)['wilson_ci']
        for side in (0, 1):
            bounds[side] += len(group)/total*interval[side]
    return dict(events=sum(bool(predicate(row)) for row in rows), n=total,
                probability=sum(bool(predicate(row)) for row in rows)/total,
                stratified_simultaneous_wilson_ci=bounds,
                method='Weighted per-window Bonferroni Wilson bounds; fixed archive-window mixture')


def validate_finances(result, mint_fee):
    if result.get('unpaid_routine_calls') != 0:
        raise ValueError('unaccepted unpaid or partially paid keeper work cannot support manager returns')
    if result['ledger_gap_wei'] != 0:
        raise ValueError('account ledger does not reconcile')
    if result['keeper_compensation_wei'] != result['routine_keeper_paid_wei'] + result['essential_keeper_paid_wei']:
        raise ValueError('keeper payment classification does not reconcile')
    if result['keeper_net_proxy_wei'] != result['keeper_compensation_wei']-result['keeper_gas_proxy_cost_wei']:
        raise ValueError('keeper net does not reconcile to compensation and gas')
    if result['routine_keeper_paid_wei'] > result['routine_period_permission_upper_wei']:
        raise ValueError('routine permission exceeded')
    if result['creator_primary_fees_accrued_wei'] % (3*mint_fee):
        raise ValueError('creator fees are not three actual configured paid mints')
    remaining = sum(result[key] for key in ('physical_assets_wei', 'external_fee_credit_wei', 'unharvested_listing_fees_wei'))
    if result['exit_complete']:
        if remaining or result['owner_net_wei'] != result['owner_withdrawn_wei']-result['owner_funded_wei']-result['owner_wallet_gas_proxy_wei']:
            raise ValueError('owner realized cash does not reconcile')
        gap = (result['owner_funded_wei'] + result['fees_received_wei'] - result['owner_withdrawn_wei']
               - result['keeper_compensation_wei'] - result['creator_primary_fees_accrued_wei']
               - result['backing_lost_wei'] - result['settlement_fees_wei'])
        if gap:
            raise ValueError('independent owner/keeper/creator cash partition does not reconcile')
    elif result['owner_net_wei'] is not None:
        raise ValueError('incomplete exit must not report realized net')
    return remaining


def compact_result(result, mint_fee):
    remaining = validate_finances(result, mint_fee)
    result = {key: value for key, value in result.items() if key != 'operating_budget_marks'}
    result['remaining_assets_wei'] = remaining
    result['owner_realized_cash_net_so_far_wei'] = result['owner_withdrawn_wei']-result['owner_funded_wei']-result['owner_wallet_gas_proxy_wei']
    result['ever_renewal_cash_short'] = result.get('waiting_observations', {}).get('RENEWAL_CASH_SHORT', 0) > 0
    result['cash_short_duration_seconds'] = None
    result['cash_short_duration_limitation'] = 'Planner observations do not measure full-period duration'
    return result


def response_cohort(db_path, start, end, responses):
    """Describe the original formal.window response table without filtering or changing it."""
    with sqlite3.connect(f'file:{db_path}?mode=ro',uri=True) as db:
        last=db.execute('SELECT max(ts) FROM logs').fetchone()[0]
        allocations=db.execute("SELECT ts, args FROM logs WHERE event='NFTAllocated' AND ts>=? AND ts<=?",(start,end)).fetchall()
    if len(allocations)!=len(responses):raise ValueError('formal response table lost an allocation')
    records=[];followups=[];unresolved_followups=[];late=clamped=after_window=0
    for (allocated_at,args),(delay,kept) in zip(allocations,responses):
        followup=last-allocated_at
        if followup<0 or (delay is not None and not 0<=delay<=followup):
            raise ValueError('formal response lies beyond actual archived follow-up')
        followups.append(followup)
        if delay is None:unresolved_followups.append(followup)
        else:
            late+=int(delay>3600)
            clamped+=int(delay>3480)
            after_window+=int(allocated_at+delay>end)
        records.append((int(json.loads(args)['listingId']),allocated_at,delay,kept))
    def horizon(values):
        return dict(minimum=min(values),median=statistics.median(values),maximum=max(values)) if values else None
    return dict(method='original-formal-eventual-response-adverse-v1',observed_until=last,
        allocations_in_window=len(allocations),sampled_allocations=len(responses),
        responsive_allocations=len(responses)-len(unresolved_followups),unresolved_at_archive_cutoff=len(unresolved_followups),
        allocations_excluded=0,responsive_after3600_seconds=late,responsive_delays_clamped_to3480=clamped,
        responses_observed_after_window_end=after_window,allocation_followup_seconds=horizon(followups),
        unresolved_allocation_followup_seconds=horizon(unresolved_followups),
        cohort_sha256=canonical_hash(records),responses_sha256=canonical_hash(responses))


def worker_init(manifest):
    global WORKER
    import forward as F
    from formal import window
    windows={}
    for item in manifest['windows']:
        w=window(ROOT/manifest['archive'],item['end'])
        cohort=response_cohort(ROOT/manifest['archive'],w['start'],item['end'],w['responses'])
        if cohort!=item['response_cohort']:raise ValueError('worker response cohort changed from frozen manifest')
        windows[item['id']]=w
    WORKER = manifest, windows, F


def run_path(task):
    """One path ID uses the same request-keyed uniforms in every configuration."""
    window_id, seed = task
    manifest, windows, F = WORKER
    w = windows[window_id]
    responses = w['responses']
    def response(uniform):
        delay, _ = responses[min(int(uniform*len(responses)), len(responses)-1)]
        return (None, None) if delay is None else (min(delay, F.OperatingClock.SETTLEMENT-120), False)
    rows = []
    for cell in manifest['cells']:
        values = manifest['manager_values'] | dict(backingRatioBps=cell['backing_bps'], renewalMode=0)
        sc = F.Scenario(manager=True, volume=F.const(0), timed=True, start_timestamp=w['start'],
            poll_seconds=60, receipt_seconds=36, replay_events=w['events'], replay_period_seconds=30*F.DAY,
            request_randomness=True, request_response_sampler=response, foreign_pool_weight=1., exempt=True,
            gwei=cell['total_gas_gwei']-.05, deposit_wei=5*10**17, mint_fee_wei=manifest['mint_fee_wei'],
            exit_all=True, exit_days=7, user_gas_proxy=manifest['gas_proxy'], holder_rescue_sync=True,
            self_serve_exits=True, unmeasured_gas_operations=manifest['unmeasured_operations'])
        result = compact_result(F.run(sc, 1, seed, days=30, values=values), manifest['mint_fee_wei'])
        if result['owner_funded_wei'] != 5*10**17 or result['initial_funding_wei'] != 5*10**17:
            raise ValueError('path changed the declared .5ETH owner capital or added a hidden topup')
        if result.get('randomness_mode') != 'request-keyed-v1':
            raise ValueError('forward model did not use request-keyed randomness')
        rows.append(dict(window=window_id, seed=seed, cell=cell['id'], **result))
    if len({row['request_events_sha256'] for row in rows}) != 1:
        raise ValueError('paired configurations did not share the canonical request event stream')
    return rows


def input_manifest(args):
    import forward as F
    from formal import PIN, window
    ends = sorted(args.window_end or [PIN['timestamp']-30*86400, PIN['timestamp']])
    if len(set(ends)) != 2 or ends[1]-ends[0] < 30*86400 or args.paths != 8192:
        raise ValueError('preregistered campaign requires 8192 paths/cell, split4096 each across two nonoverlapping30day windows')
    if args.seed_start < 100000 or args.workers < 1 or args.workers > 8:
        raise ValueError('seed range starts at least 100000; workers must be 1..8')
    files = list(SOURCE_FILES) + [args.costs, args.reconciliation, args.archive, args.live_observation]
    if (ROOT/(args.archive+'-wal')).exists():
        files.append(args.archive+'-wal')
    hashes = {name: digest(ROOT/name) for name in files}
    costs = json.loads((ROOT/args.costs).read_text())
    reconciliation = json.loads((ROOT/args.reconciliation).read_text())
    if reconciliation['status'] != 'PASS':
        raise ValueError('manager reconciliation is not PASS')
    for name, expected in reconciliation['source_sha256'].items():
        if digest(ROOT/name) != expected:
            raise ValueError('stale reconciliation: '+name)
    contracts = {str(path.relative_to(ROOT)): digest(path) for path in sorted((ROOT/'src').rglob('*.sol'))}
    if contracts != costs['contract_source_sha256']:
        raise ValueError('gas receipts refer to other contracts')
    receipts = costs.get('receipts')
    if not receipts or digest(ROOT/receipts) != costs['receipts_sha256']:
        raise ValueError('gas receipt content changed')
    hashes[receipts] = costs['receipts_sha256']
    for name in ('create','setExiting','withdraw','unlist','liquidate','recover_sync','processAcquisitions'):
        if costs['gas_proxy'].get(name, 0) <= 0:
            raise ValueError('missing measured owner operation: '+name)
    observation = json.loads((ROOT/args.live_observation).read_text())
    values = json.loads((ROOT/'deploy/manager.json').read_text())
    if not 0 < observation['mintFeeWei'] <= values['acceptedMintFeeWei']:
        raise ValueError('observed fee is outside accepted mint limit')
    if observation.get('oracleExempt') is not True or observation.get('readOnly') is not True or observation.get('rpc') != 'https://mainnet.gateway.tenderly.co':
        raise ValueError('live observation does not confirm read-only Tenderly state and oracle exemption')
    protocol = observation['protocol']
    if protocol.get('surchargeBps') != round(F.SUR*10000) or protocol.get('retainedToProtocol') is not True:
        raise ValueError('observed surcharge/retained settlement routing differs from the model')
    constants = dict(ownerAcquisitionFeeBps=round(F.CUT*10000), topListingShareBps=10,
        ownerSettlementFeeBps=round(F.S_FEE*10000), settlementDiscountBps=round(F.BID_RATE*10000),
        settlementWindow=F.OperatingClock.SETTLEMENT)
    for key,expected in constants.items():
        if protocol.get(key) != expected:raise ValueError('live protocol differs from model: '+key)
    exact_k = int((1+Fraction(str(F.SUR)))*(1-Fraction(str(F.CUT)))*Fraction(999,1000)*F.E)
    expected_value=protocol['weightedBackingTotal']//protocol['totalWeight']
    rounding_bound=(F.E+expected_value-1)//expected_value+2
    if abs(protocol['inferredGrossMultiplier1e18']-exact_k)>rounding_bound:
        raise ValueError('live gross fee multiplier exceeds the acquisition-fee rounding bound')
    windows = []
    per_window = args.paths//len(ends)
    with sqlite3.connect(f'file:{ROOT/args.archive}?mode=ro', uri=True) as db:
        first_ts, last_ts, top = db.execute('SELECT min(ts), max(ts), max(block) FROM logs').fetchone()
    for index, end in enumerate(sorted(ends)):
        w = window(ROOT/args.archive, end)
        cohort=response_cohort(ROOT/args.archive,w['start'],end,w['responses'])
        if w['start'] < first_ts:
            raise ValueError('archive does not cover the complete requested window')
        if not w['responses']:
            raise ValueError('archive window has no observed buyer response distribution')
        windows.append(dict(id=f'w{end}', start=w['start'], end=end, successful=w['successful'],
            refunded=w['refunded'], response_kinds=w['response_kinds'], archive_top_block=w['archive_top_block'],
            events_sha256=canonical_hash(w['events']), responses_sha256=canonical_hash(w['responses']),
            response_cohort=cohort,
            gap_from_last_archived_event_seconds=max(0,end-last_ts),
            paths=per_window, seed_start=args.seed_start+index*per_window,
            seed_end_exclusive=args.seed_start+(index+1)*per_window))
    return dict(schema=1, paths_per_cell=args.paths, cells=list(CELLS), windows=windows,
        archive=args.archive, source_sha256=hashes, contract_source_sha256=contracts,
        archive_coverage=dict(first_timestamp=first_ts,last_timestamp=last_ts,top_block=top),
        manager_values=values, mint_fee_wei=observation['mintFeeWei'], mint_fee_observation=observation,
        verified_model_protocol_constants=constants, model_gross_multiplier_1e18=exact_k,
        gas_proxy=costs['gas_proxy'], unmeasured_operations=['harvest' if x=='standalone-harvest' else x for x in costs.get('unmeasured_operations',[])],
        randomness='request_randomness v1: request ordinal includes refunded/repeated events; paired across cells',
        inference=dict(sample_size='Fixed in advance; no outcome-dependent stopping or sample-size change',
            probability_precision='4096 paths/window gives maximum Wilson95 halfwidth about1.53percentage points;8192 pooled iid paths would give1.083points, but the two-window mixture uses simultaneous stratum bounds instead',
            mean_interval='Normal-approximation conditional Monte Carlo CI, stratified across archive windows',
            paired_interval='Two gas-level backing contrasts, each two-sided97.5%; Bonferroni family95%',
            probability_interval='Wilson95% per window; simultaneous conservative bounds for fixed mixture'),
        assumptions=['30 operating days, at most7 exit days, .5ETH owner funding, FreshAfterAcquisition, mask8.',
            'Ordinary modeled keeper jobs require their complete reviewed quoted payment; a shorter or zero post-execution payment is a fatal invariant. Explicit owner exits pay wallet gas. The live keeper can separately accept a smaller profitable payment; that behavior is not assumed here.',
            'Response samples are the exact original formal.window tables: first archived ETH bid/token bid/keep after each window allocation, through the common archive cutoff. No allocation or late response is excluded.',
            'Every observed responder is forced to take the depositor bid with delay min(observed delay,3480seconds), including responses observed after3600seconds. Unresolved allocations at the archive cutoff remain None. This restores the original adverse stress, not empirical buyer-choice or timing replay.',
            'The older month has longer available follow-up; unresolved responses are right-censored at the archive cutoff. Per-window follow-up horizons and late/clamped counts are disclosed. Silence frequencies are not comparable empirical behavior estimates or forecasts.',
            'Archive request times/outcomes/foreign weights are fixed; no competitive or behavioral market response to the manager.',
            'Fresh observed protocol fee/crown/settlement rules are applied to historical arrivals and weights; historical per-event fee configurations are not replayed.',
            'The30day archive repeats during the exit tail, including later requests; this is an explicit continuation assumption.',
            'Owner and keeper gas are receipt-calibrated proxies, including declared unmeasured operations; creator fees are gross accrual, not creator net profit.',
            'Modeled exits assume the owner elects to fund the computed wallet gas; no per-path wallet-spend cap is simulated. The actual CLI/app requires an explicit caller cap and stops before exceeding it. A completed model exit does not prove completion within the rehearsal cap of .01ETH.',
            'Cash-short probability is ever observed at planner reads; full-period duration is unavailable.',
            'Incomplete exits retain realized cash net so far and unresolved assets separately; future recovery gas is unknown, so that cash figure is not a guaranteed final-return lower bound.',
            'Intervals measure conditional simulation noise, not future market uncertainty. No APR or personal-manager production return hurdle is inferred.'])


def read_rows(path, manifest):
    expected = {(w['id'], seed, cell['id']) for w in manifest['windows']
                for seed in range(w['seed_start'], w['seed_end_exclusive']) for cell in manifest['cells']}
    rows, seen = [], set()
    source=path if path.exists() else Path(str(path)+'.gz')
    if not source.exists():
        return rows, seen
    with (gzip.open(source,'rt') if source.suffix=='.gz' else source.open()) as stream:
        for number, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except ValueError as exc:
                raise ValueError(f'corrupt/incomplete JSONL line{number}; preserve the file and repair explicitly') from exc
            key = row['window'], row['seed'], row['cell']
            if key not in expected or key in seen or row.get('campaign_hash') != canonical_hash(manifest):
                raise ValueError(f'foreign or duplicate result at line{number}')
            validate_finances(row, manifest['mint_fee_wei'])
            rows.append(row)
            seen.add(key)
    return rows, seen


def save_batch(stream, batch, manifest, rows, seen):
    for row in batch:
        key=row['window'],row['seed'],row['cell']
        if key in seen:continue
        row['campaign_hash']=canonical_hash(manifest)
        stream.write(json.dumps(row,separators=(',',':'))+'\n')
        stream.flush();os.fsync(stream.fileno())
        rows.append(row);seen.add(key)


def summarize(rows, manifest):
    def summarize_group(group, expected_count):
        complete = [r for r in group if r['exit_complete']]
        net = distribution([r['owner_net_wei']/10**18 for r in complete], strata=[r['window'] for r in complete])
        metrics = {key: distribution([r[key]/10**18 for r in group], strata=[r['window'] for r in group])
            for key in ('owner_wallet_gas_proxy_wei','keeper_compensation_wei','keeper_gas_proxy_cost_wei',
                        'keeper_net_proxy_wei','creator_primary_fees_accrued_wei','fees_received_wei','remaining_assets_wei',
                        'owner_realized_cash_net_so_far_wei')}
        population_net = net if len(complete)==len(group)==expected_count else dict(**distribution([]),suppressed=True,
            reason='Missing paths or incomplete exits prevent a final owner-return population estimate')
        return dict(paths=len(group), planned_paths=expected_count, complete_exits=len(complete), incomplete_exits=len(group)-len(complete),
            owner_realized_net_eth=population_net, completed_exit_owner_net_diagnostic_eth=net,
            owner_net_condition='Final owner-return estimate suppressed if any exit is incomplete; completed-only diagnostic is conditional',
            owner_loss_probability_among_complete=probability(complete, lambda r: r['owner_net_wei']<0),
            all_path_loss_fraction_bounds=[sum(r['owner_net_wei']<0 for r in complete)/len(group),
                (sum(r['owner_net_wei']<0 for r in complete)+len(group)-len(complete))/len(group)],
            ever_renewal_cash_short_probability=probability(group, lambda r:r['ever_renewal_cash_short']),
            cash_short_duration_seconds=None, completion_failure_probability=probability(group, lambda r:not r['exit_complete']),
            maximum_remaining_assets_wei=max(r['remaining_assets_wei'] for r in group), cash_flows_eth=metrics,
            unknown_owner_gas_calls=sum(r['unknown_owner_gas_calls'] for r in group),
            unmeasured_keeper_operations=sorted({op for r in group for op in r['keeper_unmeasured_operations']}),
            account_ledger_gap_wei_max=max(abs(r['ledger_gap_wei']) for r in group))
    cells = {cell['id']: summarize_group([r for r in rows if r['cell']==cell['id']], manifest['paths_per_cell']) for cell in manifest['cells'] if any(r['cell']==cell['id'] for r in rows)}
    by_window = {w['id']: {cell['id']: summarize_group([r for r in rows if r['window']==w['id'] and r['cell']==cell['id']], w['seed_end_exclusive']-w['seed_start'])
                    for cell in manifest['cells'] if any(r['window']==w['id'] and r['cell']==cell['id'] for r in rows)} for w in manifest['windows']}
    indexed = {(r['window'],r['seed'],r['cell']):r for r in rows}
    contrasts=[]
    for gas in (.2,.5):
        deltas=[]; labels=[]; unavailable=0
        for w in manifest['windows']:
            for seed in range(w['seed_start'],w['seed_end_exclusive']):
                low=indexed.get((w['id'],seed,f'b50000-g{gas}')); high=indexed.get((w['id'],seed,f'b70000-g{gas}'))
                if low is None or high is None or not low['exit_complete'] or not high['exit_complete']:
                    unavailable+=1;continue
                deltas.append((low['owner_net_wei']-high['owner_net_wei'])/10**18);labels.append(w['id'])
        diagnostic=distribution(deltas,Z_PAIR,labels)
        primary=diagnostic if unavailable==0 else dict(**distribution([]),suppressed=True,
            reason='Missing or incomplete pairs prevent a final paired owner-return estimate')
        contrasts.append(dict(total_gas_gwei=gas,direction='B.15 minus B.21 owner realized net ETH',
            paired=primary,complete_pair_diagnostic=diagnostic,unavailable_pairs=unavailable,individual_confidence=.975,family_confidence=.95))
        contrasts[-1]['window_diagnostics95']={key:distribution([value for value,label in zip(deltas,labels) if label==key]) for key in sorted(set(labels))}
    return dict(campaign_hash=canonical_hash(manifest), expected_rows=manifest['paths_per_cell']*len(manifest['cells']),
        rows=len(rows), finished=len(rows)==manifest['paths_per_cell']*len(manifest['cells']), cells=cells,
        windows=by_window, paired_backing_differences=contrasts, assumptions=manifest['assumptions'],
        pooled_interpretation='Equal-weight fixed archive-window mixture; window-specific results are primary',
        things_that_do_not_make_sense=['A precise conditional Monte Carlo mean does not establish future market returns.',
            'One finite renewal float cannot cover arbitrary early acquisition bursts.',
            'Unmeasured renewal/standalone-harvest gas remains a proxy limitation, not new measured receipt evidence.'])


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute',action='store_true');ap.add_argument('--summarize-only',action='store_true')
    ap.add_argument('--check',action='store_true',help='Validate all expected saved paths and regenerate the summary without running paths')
    ap.add_argument('--paths',type=int,default=8192);ap.add_argument('--seed-start',type=int,default=100000)
    ap.add_argument('--window-end',type=int,action='append');ap.add_argument('--workers',type=int,default=8)
    ap.add_argument('--archive',default='sim/data/fwa.sqlite');ap.add_argument('--costs',default='docs/receipts/manager-r2-cost-calibration.json')
    ap.add_argument('--reconciliation',default='docs/receipts/manager-funded-reconciliation.json')
    ap.add_argument('--live-observation',default='docs/receipts/manager-r2-live-observation.json')
    ap.add_argument('--out',default='sim/out/manager-monte-carlo-funded')
    args=ap.parse_args(); manifest=input_manifest(args)
    if not args.execute and not args.summarize_only and not args.check:
        print(json.dumps(manifest,indent=2));return
    if os.environ.get('CANDIDATE_RUN')!='1':
        raise ValueError('frozen execution requires CANDIDATE_RUN=1')
    out=ROOT/args.out;out.mkdir(parents=True,exist_ok=True)
    with (out/'writer.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        manifest_path=out/'manifest.json'
        if manifest_path.exists():
            if json.loads(manifest_path.read_text())!=manifest:
                raise ValueError('campaign inputs or declared sample changed; use a new output directory')
        else:
            if args.summarize_only or args.check:raise ValueError('campaign manifest does not exist')
            manifest_path.write_text(json.dumps(manifest,indent=2)+'\n')
        rows,seen=read_rows(out/'paths.jsonl',manifest)
        if args.execute and not args.summarize_only and not args.check:
            pending=[(w['id'],seed) for w in manifest['windows'] for seed in range(w['seed_start'],w['seed_end_exclusive'])
                     if any((w['id'],seed,c['id']) not in seen for c in manifest['cells'])]
            if pending and not (out/'paths.jsonl').exists() and (out/'paths.jsonl.gz').exists():
                raise ValueError('decompress saved results before appending additional paths')
            if not pending:
                args.summarize_only=True
        if args.execute and not args.summarize_only and not args.check:
            with (out/'paths.jsonl').open('a') as stream, ProcessPoolExecutor(args.workers,initializer=worker_init,initargs=(manifest,)) as pool:
                tasks=iter(pending)
                inflight={}
                def submit():
                    task=next(tasks,None)
                    if task is not None:inflight[pool.submit(run_path,task)]=task
                for _ in range(args.workers*2):submit()
                while inflight:
                    done,_=wait(inflight,return_when=FIRST_COMPLETED)
                    for future in done:
                        task=inflight.pop(future)
                        try:batch=future.result()
                        except Exception as exc:
                            failure=dict(campaign_hash=canonical_hash(manifest),window=task[0],seed=task[1],
                                exception=type(exc).__name__,detail=str(exc),completed_rows=len(rows),status='STOPPED_TECHNICAL_FAILURE')
                            with (out/'technical-failures.jsonl').open('a') as errors:errors.write(json.dumps(failure)+'\n')
                            for queued in inflight:queued.cancel()
                            raise
                        save_batch(stream,batch,manifest,rows,seen)
                        if len(seen)%128==0:print(f'{len(seen)}/{args.paths*len(CELLS)} cell paths saved',flush=True)
                        submit()
        for name,expected in manifest['source_sha256'].items():
            if digest(ROOT/name)!=expected:raise ValueError('input changed during campaign: '+name)
        report=summarize(rows,manifest)
        failures=out/'technical-failures.jsonl'
        report['technical_failures_recorded']=len(failures.read_text().splitlines()) if failures.exists() else 0
        if args.check and not report['finished']:raise ValueError('campaign has missing paths')
        temporary=out/'summary.json.tmp';temporary.write_text(json.dumps(report,indent=2)+'\n');temporary.replace(out/'summary.json')
        print(json.dumps(dict(output=str(out),rows=report['rows'],finished=report['finished'])))


if __name__=='__main__':
    main()
