#!/usr/bin/env python3
"""Fixed, paired manager operating assessment over actual archived request windows."""
import argparse
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from contextlib import contextmanager
from fractions import Fraction
import json
from pathlib import Path
import sqlite3
import statistics
import time

import forward as F
from formal import PIN, WINDOW, window
from manager_assessment import feasible_burst
import manager_monte_carlo as MC
import manager_standard_backing as S

ROOT = Path(__file__).resolve().parent.parent
CAPITAL = 5 * 10**17
REQUIRED_GAS = ('create', 'setExiting', 'withdraw', 'unlist', 'liquidate', 'recover_sync',
                'processAcquisitions', 'build', 'renew', 'list', 'sync', 'harvest')
CELLS = tuple(dict(id=f'm{mode}-b{backing}-f{fee}-g{gas}', renewal_mode=mode,
                  backing_bps=backing, mint_fee_wei=fee, total_gas_gwei=gas)
              for mode in (0, 1) for backing in (70000, 10000)
              for fee in (25*10**13, 5*10**14, 10**15) for gas in (.2, .5))
WORKER = None


def sha(path):
    return MC.digest(path)


def check_sources(expected):
    for name, digest in expected.items():
        if sha(ROOT/name) != digest:
            raise ValueError('stale source/receipt binding: ' + name)


def qualify_costs(costs, final):
    if any(not isinstance(costs.get('gas_proxy', {}).get(op), int) or costs['gas_proxy'][op] <= 0 for op in REQUIRED_GAS):
        raise ValueError('positive measured/proxy gas required for all owner and operating operations')
    if final and costs.get('unmeasured_operations') != []:
        raise ValueError('final evaluation requires no unmeasured required operations')
    if final:
        owner_operations=('setExiting','withdraw','unlist','liquidate','recover_sync','processAcquisitions','harvest')
        if any(not isinstance(costs.get('gas_estimate_proxy',{}).get(op),int) or costs['gas_estimate_proxy'][op]<=0 for op in owner_operations):
            raise ValueError('final evaluation requires separate signed/estimated owner gas envelope')
        aliases = {'recover_sync': 'recover', 'unlist': 'recoverUnlist', 'liquidate': 'recoverLiquidate'}
        measurements = costs.get('measurements', {})
        for op in REQUIRED_GAS:
            samples = measurements.get(op, measurements.get(aliases.get(op, ''), []))
            if not samples or any(not isinstance(sample.get('gasUsed'), int) or sample['gasUsed'] <= 0 for sample in samples):
                raise ValueError('final evaluation missing billed receipt samples: ' + op)



def verify_measurement_receipts(costs, packets):
    def integer(value):
        return int(value, 0) if isinstance(value, str) else value
    actual = {}
    estimates = {}
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            receipt=value.get('receipt',{})
            transaction=value.get('transaction',{})
            if isinstance(receipt,dict) and receipt.get('transactionHash'):
                estimate=value.get('gasEstimate',value.get('signedGasLimit',transaction.get('gas') if isinstance(transaction,dict) else None))
                if estimate is not None:
                    estimates[receipt['transactionHash'].lower()]=integer(estimate)
            if 'transactionHash' in value and 'gasUsed' in value and 'status' in value:
                if integer(value['status']) == 1:
                    actual[value['transactionHash'].lower()] = integer(value['gasUsed'])
            for item in value.values(): visit(item)
    for packet in packets: visit(packet)
    for operation, samples in costs['measurements'].items():
        for sample in samples:
            tx = sample.get('hash', sample.get('transactionHash', ''))
            if actual.get(tx.lower()) != sample.get('gasUsed'):
                raise ValueError('measurement lacks matching successful billed receipt: ' + operation)
    aliases={'recover_sync':'recover','unlist':'recoverUnlist','liquidate':'recoverLiquidate'}
    for operation, proxy in costs.get('gas_estimate_proxy',{}).items():
        samples=costs['measurements'].get(operation,costs['measurements'].get(aliases.get(operation,''),[]))
        if not samples:
            raise ValueError('signed/estimated gas proxy lacks receipt samples: '+operation)
        proven=[estimates.get(sample.get('hash',sample.get('transactionHash','')).lower()) for sample in samples]
        if any(value is None for value in proven) or proxy<max(proven):
            raise ValueError('signed/estimated gas proxy understates receipt estimate/upper: '+operation)


def manifest(args):
    costs = json.loads((ROOT/args.costs).read_text())
    reconciliation = json.loads((ROOT/args.reconciliation).read_text())
    observation = json.loads((ROOT/args.live_observation).read_text())
    values = json.loads((ROOT/'deploy/manager.json').read_text())
    if reconciliation.get('status') != 'PASS':
        raise ValueError('current reconciliation must PASS')
    check_sources(reconciliation['source_sha256'])
    contracts = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'src').rglob('*.sol'))}
    if contracts != costs['contract_source_sha256']:
        raise ValueError('gas calibration belongs to another runtime source candidate')
    qualify_costs(costs, args.final)
    receipt_inputs = costs.get('receipt_inputs') or [dict(path=costs['receipts'], sha256=costs['receipts_sha256'])]
    bindings = {item['path']: item['sha256'] for item in receipt_inputs}
    check_sources(bindings)
    if not bindings:
        raise ValueError('gas envelope has no immutable billed receipt packet')
    if args.final:
        packets = [json.loads((ROOT/name).read_text()) for name in bindings]
        for packet in packets:
            recorded = packet.get('contractSourceSha256', packet.get('contract_source_sha256'))
            if recorded is not None and recorded != contracts:
                raise ValueError('billed receipt runtime source mismatch')
        verify_measurement_receipts(costs, packets)
    if observation.get('readOnly') is not True or observation.get('oracleExempt') is not True or observation.get('rpc') != 'https://mainnet.gateway.tenderly.co':
        raise ValueError('verified Tenderly oracle/fee observation required')
    if observation['mintFeeWei'] != 5*10**14 or values['acceptedMintFeeWei'] != 10**15:
        raise ValueError('observed/accepted fees changed; rescope the declared fee comparison')
    protocol = observation['protocol']
    constants = dict(surchargeBps=round(F.SUR*10000), ownerAcquisitionFeeBps=round(F.CUT*10000),
                     ownerSettlementFeeBps=round(F.S_FEE*10000), settlementDiscountBps=round(F.BID_RATE*10000),
                     settlementWindow=F.OperatingClock.SETTLEMENT, topListingShareBps=10, retainedToProtocol=True)
    if any(protocol.get(k) != v for k, v in constants.items()):
        raise ValueError('observed deployed protocol differs from canonical model')
    exact_k = int((1+Fraction(str(F.SUR)))*(1-Fraction(str(F.CUT)))*Fraction(999,1000)*F.E)
    if abs(protocol['inferredGrossMultiplier1e18']-exact_k) > protocol['inferredGrossMultiplierRoundingBound']:
        raise ValueError('deployed fee multiplier mismatch')
    archive = ROOT/args.archive
    with sqlite3.connect(f'file:{archive}?mode=ro', uri=True) as db:
        first, last, top = db.execute('SELECT min(ts),max(ts),max(block) FROM logs').fetchone()
    minimum = S.archived_minimum(archive)
    if minimum['value_wei'] > 3*10**16:
        raise ValueError('hypothetical standard backing violates actual FWA minimum')
    continuity_name = args.minimum_continuity
    continuity = json.loads((ROOT/continuity_name).read_text())
    if (continuity.get('readOnly') is not True or continuity.get('rpc')!='https://mainnet.gateway.tenderly.co' or
        continuity.get('configKey')!=22 or continuity.get('retainedToProtocol') is not True or
        observation.get('minBackingWei')!=minimum['value_wei'] or
        continuity.get('subsequentLogs') != [] or continuity.get('fromBlock') != top+1 or
        continuity.get('toBlock') != observation['block'] or continuity.get('blockHash') != observation['blockHash'] or
        continuity.get('archiveLastChange') != dict(block=minimum['block'], valueWei=minimum['value_wei'])):
        raise ValueError('minimum-backing continuity is stale')
    windows = []
    for index, end in enumerate((PIN['timestamp']-WINDOW, PIN['timestamp'])):
        w = window(archive, end)
        if w['start'] < first or not w['responses']:
            raise ValueError('archive must cover both full recorded months and responses')
        burst, metadata = feasible_burst(w)
        windows.append(dict(id=f'w{end}', start=w['start'], end=end,
            month_events_sha256=MC.canonical_hash(w['events']), burst_events_sha256=MC.canonical_hash(burst),
            burst=metadata, successful=w['successful'], refunded=w['refunded'],
            response_cohort=MC.response_cohort(archive, w['start'], end, w['responses']),
            seeds=list(range(200000+index*args.paths_per_window, 200000+(index+1)*args.paths_per_window))))
    names = set(MC.SOURCE_FILES) | {'sim/manager_operating_assessment.py', 'sim/test_manager_operating_assessment.py',
        'sim/manager_assessment.py', 'sim/manager_standard_backing.py', args.costs, args.reconciliation,
        args.live_observation, args.archive, continuity_name} | set(bindings)
    if (ROOT/(args.archive+'-wal')).exists():
        names.add(args.archive+'-wal')
    hashes = {name: sha(ROOT/name) for name in sorted(names)}
    return dict(schema=1, design='Fixed paired descriptive cohort; agent-chosen size, no owner return hurdle',
        source_sha256=hashes, contract_source_sha256=contracts, archive=args.archive,
        archive_coverage=dict(first_timestamp=first,last_timestamp=last,top_block=top), windows=windows,
        cells=list(CELLS), paths_per_window=args.paths_per_window, operating_days=30, exit_days=7,
        initial_funding_wei=CAPITAL, owner_exit_spend_limit_wei=args.owner_exit_spend_limit_wei,
        final_gas_qualification=args.final, gas_proxy=costs['gas_proxy'],
        gas_estimate_proxy=costs.get('gas_estimate_proxy',{}),
        unmeasured_operations=costs.get('unmeasured_operations', []), manager_values=values,
        mint_fee_observation=observation, protocol_minimum_backing=minimum,
        fee_cases={str(25*10**13):'Agent-chosen fork-only half-current sensitivity; not approved baseline',
                   str(5*10**14):'Observed current mint fee',str(10**15):'Historical/accepted maximum comparison'},
        expected_rows=2*(2*args.paths_per_window+4)*len(CELLS),
        buyer_regimes=['observed-choices','forced-responsive-bid-stress'],
        keeper_policy='Zero-loss preflight, max(work allowance, billed receipt floor), ratio1, failure/minimum-return/max-loss all zero',
        response_method='Paired request-keyed response cohort. Observed choices retain first archived keep/bid and delay; stress forces every archived eventual responder to bid within3480seconds. Unresolved stays silent in both.',
        assumptions=[
            'Thirty operating days and at most seven exit days. Recorded-month requests repeat during exit; quiet has no requests; early burst repeats the busiest actual day twice at whole-day offsets then has no requests.',
            'The fixed path count is an agent choice for bounded descriptive evaluation; no sample-size threshold or future-return confidence is claimed. No outcome-dependent stopping or exclusion.',
            'Foreign request timing, recorded success/refund and weights are fixed. Added manager listings dilute allocation/fees; external market participants do not react.',
            'Response cohorts have unequal follow-up/right censoring. Observed choices preserve archived keeps and late delays; the second regime forces every eventual responder to bid by3480seconds, including late/archive-after-window responses. Neither is a forecast or exact VRF replay.',
            'Current protocol fee rules and oracle exemption are applied to historical requests. Historical configuration changes are not individually replayed. The .00025ETH fee is an agent-chosen fork-only half-current sensitivity, not a production recommendation or approval of baseline economics; no public fee changes.',
            'Standard .03 backing relaxes only admission in an isolated worker. Current manager rejects it; it is not an executable candidate configuration.',
            'Fresh/Reuse use canonical cash holds, reserves, spending budgets, and strict fully paid ordinary work. No account topups or volunteer keeper subsidy.',
            'Gas is max(measured sample, canonical work allowance), not exact billed gas for every batch. Creator amounts are gross accrual; global deployment/service costs are outside per-clone owner returns.',
            'Owner recovery and pending processing are paid from the owner wallet. Each call must fit the cumulative signed maximum:125percent of max(work allowance,actual estimate or signed-limit upper proxy,21000gas) at2basefee+tip. The default .01ETH exit cap excludes clone creation, stops before unaffordable mutations, and can leave incomplete assets.',
            'Unfinished exits retain returned cash, unresolved cash/inventory/credit, and future-cost uncertainty. No monthly-to-annual extrapolation, APR, production viability or release authority follows.'])


def init_worker(frozen):
    global WORKER
    windows = {item['id']: window(ROOT/frozen['archive'], item['end']) for item in frozen['windows']}
    for item in frozen['windows']:
        if MC.canonical_hash(windows[item['id']]['events']) != item['month_events_sha256']:
            raise ValueError('worker archive changed after freeze')
    WORKER = frozen, windows


@contextmanager
def admission(hypothetical, minimum):
    import keeper
    originals = F.policy.edge_backing, keeper.proposal_limits, F.policy.build_net, S.MIN_BACKING
    try:
        if hypothetical:
            S.MIN_BACKING = minimum
            F.policy.edge_backing, keeper.proposal_limits, F.policy.build_net = S.relaxed_edge, S.relaxed_limits, S.relaxed_build_net
        yield
    finally:
        F.policy.edge_backing, keeper.proposal_limits, F.policy.build_net, S.MIN_BACKING = originals


def qualify_result(result, fee, cap, final):
    row = MC.compact_result(result, fee)
    if row['initial_funding_wei'] != CAPITAL or row['owner_funded_wei'] != CAPITAL:
        raise ValueError('hidden account topup or changed capital')
    if row.get('randomness_mode') != 'request-keyed-v1':
        raise ValueError('request-keyed matching missing')
    # Compare actual holdings separately from earned but unclaimed external rights.
    pending_keep = (row['owner_funded_wei'] + row['fees_received_wei'] - row['owner_withdrawn_wei'] -
        row['keeper_compensation_wei'] - row['creator_primary_fees_accrued_wei'] -
        row['backing_lost_wei'] - row['settlement_fees_wei'] - row['physical_assets_wei'])
    if pending_keep < 0 or (row['exit_complete'] and pending_keep):
        raise ValueError('independent physical cash partition failed')
    if row['owner_total_value_before_gas_wei'] != (row['physical_assets_wei'] + row['external_fee_credit_wei'] + row['unharvested_listing_fees_wei'] + row['owner_withdrawn_wei']):
        raise ValueError('owner total-value partition failed')
    row['settled_keep_face_not_yet_consumed_wei'] = pending_keep
    row['external_total_earned_wei'] = row['fees_received_wei'] + row['external_fee_credit_wei'] + row['unharvested_listing_fees_wei']
    if final and (not row.get('keeper_zero_loss_enabled') or row.get('owner_exit_spend_limit_wei') != cap):
        raise ValueError('final assessment requires zero-loss keeper and runtime owner exit cap')
    if row['keeper_net_proxy_wei'] < 0 and row.get('keeper_zero_loss_enabled'):
        raise ValueError('keeper subsidy escaped its zero-loss gate')
    row['within_exit_spend_limit'] = row['owner_exit_reserved_wei'] <= cap
    if row['owner_exit_spent_wei'] > row['owner_exit_reserved_wei'] or row['owner_exit_reserved_wei'] > cap:
        raise ValueError('owner exit spending escaped its signed maximum')
    row['qualified_exit'] = row['exit_complete'] and row['within_exit_spend_limit']
    if final and (row['unknown_owner_gas_calls'] or row['keeper_unmeasured_operations'] or row.get('owner_exit_estimate_fallback_operations')):
        raise ValueError('executed operation lacks billed gas calibration')
    return row


def run_path(task):
    frozen, windows = WORKER
    window_id, seed, regime, buyer_regime = task
    w = windows[window_id]
    if regime == 'recorded-month':
        events, period = w['events'], WINDOW
    elif regime == 'quiet':
        events, period = [], 38*F.DAY
    else:
        events, _ = feasible_burst(w)
        period = 38*F.DAY
    responses = w['responses']
    def response(uniform):
        delay, kept = responses[min(int(uniform*len(responses)), len(responses)-1)]
        return (delay, kept) if buyer_regime=='observed-choices' or delay is None else (min(delay,3480),False)
    rows = []
    for cell in frozen['cells']:
        values = frozen['manager_values'] | dict(renewalMode=cell['renewal_mode'],backingRatioBps=cell['backing_bps'])
        sc = F.Scenario(manager=True, volume=F.const(0), timed=True, start_timestamp=w['start'],
            poll_seconds=60, receipt_seconds=36, replay_events=events,replay_period_seconds=period,
            request_randomness=True, request_response_sampler=response, foreign_pool_weight=1.,exempt=True,
            gwei=cell['total_gas_gwei']-.05, deposit_wei=CAPITAL,mint_fee_wei=cell['mint_fee_wei'],
            exit_all=True,exit_days=frozen['exit_days'], user_gas_proxy=frozen['gas_proxy'],
            holder_rescue_sync=True,self_serve_exits=True,unmeasured_gas_operations=frozen['unmeasured_operations'],
            user_gas_estimate_proxy=frozen['gas_estimate_proxy'],
            manager_keeper_zero_loss=True, owner_exit_spend_limit_wei=frozen['owner_exit_spend_limit_wei'])
        started = time.monotonic()
        with admission(cell['backing_bps']==10000, frozen['protocol_minimum_backing']['value_wei']):
            raw = F.run(sc,1,seed,days=30,values=values)
        row = qualify_result(raw,cell['mint_fee_wei'],frozen['owner_exit_spend_limit_wei'],frozen['final_gas_qualification'])
        rows.append(dict(window=window_id,seed=seed,regime=regime,buyer_regime=buyer_regime,cell=cell['id'],runtime_seconds=time.monotonic()-started,**row))
    if len({r['request_events_sha256'] for r in rows}) != 1:
        raise ValueError('paired configurations saw different request tapes')
    return rows


def tasks(frozen):
    buyers = frozen['buyer_regimes']
    return [(w['id'],seed,'recorded-month',buyer) for w in frozen['windows'] for seed in w['seeds'] for buyer in buyers] + [
        (w['id'],w['seeds'][0],regime,buyer) for w in frozen['windows'] for regime in ('quiet','early-burst-then-zero') for buyer in buyers]


def summarize(rows, frozen):
    cells = []
    for buyer in frozen['buyer_regimes']:
     for regime in ('recorded-month','quiet','early-burst-then-zero'):
      for cell in frozen['cells']:
        group = [r for r in rows if r['buyer_regime']==buyer and r['regime']==regime and r['cell']==cell['id']]
        all_qualified = bool(group) and all(r['qualified_exit'] for r in group)
        expected = 2*frozen['paths_per_window'] if regime=='recorded-month' else 2
        numbers = ('owner_withdrawn_wei','owner_wallet_gas_proxy_wei','fees_received_wei','external_total_earned_wei',
            'backing_lost_wei','settlement_fees_wei','creator_primary_fees_accrued_wei','keeper_compensation_wei',
            'keeper_gas_proxy_cost_wei','keeper_net_proxy_wei','remaining_assets_wei','settled_keep_face_not_yet_consumed_wei','owner_exit_reserved_wei','owner_exit_spent_wei')
        cells.append(dict(regime=regime,buyer_regime=buyer,**cell,paths=len(group),expected_paths=expected,
            complete_exits=sum(r['exit_complete'] for r in group),qualified_exits=sum(r['qualified_exit'] for r in group),
            exit_limit_violations=sum(not r['within_exit_spend_limit'] for r in group),
            spend_limit_stops=sum(r.get('owner_exit_spend_limit_waits',0)>0 for r in group),
            keeper_loss_paths=sum(r.get('keeper_loss_waits',0)>0 for r in group),
            owner_net_mean_wei=statistics.fmean(r['owner_net_wei'] for r in group) if all_qualified and len(group)==expected else None,
            owner_net_min_wei=min((r['owner_net_wei'] for r in group),default=None) if all_qualified else None,
            maximum_unresolved_assets_wei=max((r['remaining_assets_wei'] for r in group),default=None),
            mean_wei={name:statistics.fmean(r[name] for r in group) if group else None for name in numbers},
            wait_observations={k:sum(r['waiting_observations'].get(k,0) for r in group) for k in sorted({k for r in group for k in r['waiting_observations']})}))
    paired = []
    indexed = {(r['window'],r['seed'],r['regime'],r['buyer_regime'],r['cell']):r for r in rows}
    for c in cells:
        if c['backing_bps'] != 10000:
            continue
        parent = next(other for other in frozen['cells'] if other['backing_bps']==70000 and
            all(other[k]==c[k] for k in ('renewal_mode','mint_fee_wei','total_gas_gwei')))
        differences=[]
        for row in rows:
            if row['buyer_regime']!=c['buyer_regime'] or row['regime']!=c['regime'] or row['cell']!=c['id']:
                continue
            other=indexed.get((row['window'],row['seed'],row['regime'],row['buyer_regime'],parent['id']))
            if other and row['qualified_exit'] and other['qualified_exit']:
                if row['request_events_sha256'] != other['request_events_sha256']:
                    raise ValueError('paired backing contrast request tape differs')
                differences.append(row['owner_net_wei']-other['owner_net_wei'])
        paired.append(dict(regime=c['regime'],buyer_regime=c['buyer_regime'],standard_cell=c['id'],
            manager_cell=parent['id'],qualified_pairs=len(differences),expected_pairs=c['expected_paths'],
            mean_standard_minus_manager_net_wei=statistics.fmean(differences) if len(differences)==c['expected_paths'] else None))
    return dict(expected_rows=frozen['expected_rows'],rows=len(rows),finished=len(rows)==frozen['expected_rows'],cells=cells,
        paired_backing_differences=paired,
        claim='Descriptive conditional cohort only; missing/incomplete/over-cap exits suppress owner-return means. No APR or future-market inference.')


def markdown(report):
    lines = ['# Manager recorded operating assessment','',report['summary']['claim'],'',
        f"Observed mint fee .0005 ETH; historical/accepted baseline .001 ETH; .00025 ETH is an agent-chosen fork-only half-current sensitivity. {report['summary']['rows']} / {report['summary']['expected_rows']} rows. Wall time {report['runtime_seconds']:.1f} seconds.",
        '', '| Buyer regime / demand | Mode | Backing | Fee | Gas | Qualified exits | Owner mean net ETH | Earned ETH | Keeper pay / gas ETH | Creator ETH | Unresolved max ETH |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    def money(value):return 'suppressed' if value is None else f'{value/F.E:.8f}'
    for c in report['summary']['cells']:
        m=c['mean_wei']
        lines.append(f"| {c['buyer_regime']} / {c['regime']} | {'Fresh' if c['renewal_mode']==0 else 'Reuse'} | {'.03 hypothetical' if c['backing_bps']==10000 else '.21'} | {c['mint_fee_wei']/F.E:g} | {c['total_gas_gwei']} | {c['qualified_exits']}/{c['expected_paths']} | {money(c['owner_net_mean_wei'])} | {money(m['external_total_earned_wei'])} | {money(m['keeper_compensation_wei'])} / {money(m['keeper_gas_proxy_cost_wei'])} | {money(m['creator_primary_fees_accrued_wei'])} | {money(c['maximum_unresolved_assets_wei'])} |")
    lines += ['', 'JSON retains each path and owner/keeper/creator/physical-asset partitions. Owner exit calls stop before cumulative signed maxima exceed the exit cap, excluding clone creation. Unfinished exits retain cash/inventory; the cap does not guarantee completion.', '']
    lines += [paragraph for item in report['manifest']['assumptions'] for paragraph in (item,'')]
    lines += ["Things that don't make sense: a positive conditional mean cannot establish future profitability; an exit-spend cap can stop recovery with assets still held; isolated .03 admission cannot be deployed through this manager.",'']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--final',action='store_true',help='Reject any unmeasured required/executed operation')
    parser.add_argument('--costs',default='docs/receipts/manager-r2-cost-calibration.json')
    parser.add_argument('--reconciliation',default='docs/receipts/manager-funded-reconciliation.json')
    parser.add_argument('--live-observation',default='docs/receipts/manager-r2-live-observation.json')
    parser.add_argument('--minimum-continuity',default='docs/receipts/manager-r2-min-backing-continuity.json')
    parser.add_argument('--archive',default='sim/data/fwa.sqlite')
    parser.add_argument('--paths-per-window',type=int,default=8)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--owner-exit-spend-limit-wei','--wallet-cap-wei',dest='owner_exit_spend_limit_wei',type=int,default=10**16)
    parser.add_argument('--out',default='sim/out/manager-operating-assessment')
    args=parser.parse_args()
    if args.paths_per_window<1 or not 1<=args.workers<=4 or args.owner_exit_spend_limit_wei<=0:
        parser.error('positive fixed path count/cap and one to four workers required')
    frozen=manifest(args)
    if not args.execute:
        print(json.dumps(dict(expected_rows=frozen['expected_rows'],paths_per_window=args.paths_per_window,
            windows=[w['id'] for w in frozen['windows']],qualification='final' if args.final else 'provisional'),indent=2))
        return
    import os
    if os.environ.get('CANDIDATE_RUN')!='1':
        raise SystemExit('frozen operating execution requires CANDIDATE_RUN=1')
    out=ROOT/args.out
    out.mkdir(parents=True,exist_ok=True)
    with (out/'manifest.json').open('x') as stream:
        json.dump(frozen,stream,indent=2);stream.write('\n')
    started=time.monotonic();rows=[]
    try:
        planned=tasks(frozen)
        if len(set(planned))!=len(planned) or len(planned)*len(frozen['cells'])!=frozen['expected_rows']:
            raise ValueError('frozen task list has duplicate/missing paths')
        with (out/'paths.jsonl').open('x') as journal, ProcessPoolExecutor(args.workers,initializer=init_worker,initargs=(frozen,)) as pool:
            remaining=iter(planned)
            pending={}
            def fill():
                while len(pending)<args.workers:
                    task=next(remaining,None)
                    if task is None:break
                    pending[pool.submit(run_path,task)]=task
            fill()
            try:
                while pending:
                    completed,_=wait(pending,return_when=FIRST_COMPLETED)
                    failure=None
                    for future in sorted(completed,key=lambda f:pending[f]):
                        task=pending.pop(future)
                        try:
                            batch=future.result()
                        except Exception as error:
                            failure=failure or RuntimeError(f'path {task} failed: {error!r}')
                            continue
                        for row in batch:
                            journal.write(json.dumps(row,separators=(',',':'))+'\n');rows.append(row)
                        journal.flush();os.fsync(journal.fileno())
                        print(f'{len(rows)}/{frozen["expected_rows"]} rows persisted',flush=True)
                    if failure is not None:raise failure
                    fill()
            except BaseException:
                for future in pending:future.cancel()
                raise
        check_sources(frozen['source_sha256'])
        report=dict(manifest=frozen,runtime_seconds=time.monotonic()-started,summary=summarize(rows,frozen),paths='paths.jsonl')
        (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        (out/'report.md').write_text(markdown(report))
    except Exception as error:
        (out/'failure.json').write_text(json.dumps(dict(error=repr(error),persisted_rows=len(rows),runtime_seconds=time.monotonic()-started),indent=2)+'\n')
        raise


if __name__=='__main__':main()
