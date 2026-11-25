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
from keeper import BILLED_PER_ESTIMATE
from eth_utils import keccak

ROOT = Path(__file__).resolve().parent.parent
CAPITAL = 5 * 10**17
REQUIRED_GAS = ('create', 'setExiting', 'withdraw', 'unlist', 'liquidate', 'recover_sync',
                'processAcquisitions', 'build', 'list', 'sync', 'harvest')
METERED_OPERATIONS=('build','list','sync','unlist','liquidate')
OWNER_OPERATIONS=('create','setExiting','withdraw','unlist','liquidate','recover_sync','processAcquisitions','harvest')
OWNER_SAMPLE_ALIASES={'recover_sync':'recover','unlist':'recoverUnlist','liquidate':'recoverLiquidate'}
KNOWN_UNSUPPORTED=('larger sync batches',)
CELLS = tuple(dict(id=f'b{backing}-f{fee}-g{gas}',backing_bps=backing,
                  mint_fee_wei=fee,total_gas_gwei=gas)
              for backing in (70000,10000) for fee in (25*10**13,5*10**14,10**15) for gas in (.2,.5))
WORKER = None


def sha(path):
    return MC.digest(path)


def check_sources(expected):
    for name, digest in expected.items():
        if sha(ROOT/name) != digest:
            raise ValueError('stale source/receipt binding: ' + name)



def operation_samples(costs, operation, owner=False):
    name=OWNER_SAMPLE_ALIASES.get(operation,operation) if owner else operation
    if not owner and operation=='recover_sync':
        return costs['measurements'].get(operation,costs['measurements'].get('recover',[]))
    return costs['measurements'].get(name,[])


def owner_curves(costs):
    return costs.get('gas_curves',{}) | costs.get('owner_gas_curves',{})


def supported_work(costs, owner=False):
    operations=OWNER_OPERATIONS if owner else METERED_OPERATIONS
    return {op:max(s['workCount'] for s in operation_samples(costs,op,owner)) for op in operations}



def estimate_samples(samples):
    if any(sample.get('estimateKind') not in ('rpc-estimate','signed-limit-upper') for sample in samples):
        raise ValueError('curve samples require explicit estimateKind')
    rpc=[sample for sample in samples if sample['estimateKind']=='rpc-estimate']
    selected=rpc or samples
    if not any(sample['workCount']==1 for sample in selected):
        raise ValueError('selected estimate kind lacks single-work baseline')
    return selected


def verify_gas_curves(costs, owner=False):
    curves=owner_curves(costs) if owner else costs.get('gas_curves',{})
    for operation in (OWNER_OPERATIONS if owner else REQUIRED_GAS):
        samples=operation_samples(costs,operation,owner)
        if operation not in curves or not samples:
            raise ValueError('missing count-aware gas curve: '+operation)
        for sample in samples:
            if type(sample.get('gasUsed')) is not int or sample['gasUsed']<=0:
                raise ValueError('sample lacks billed gas: '+operation)
            # The same runtime helper enforces each operation's actual batch bound.
            F.receipt_gas(curves,operation,sample.get('workCount'))
            estimate=sample.get('gasEstimate')
            if type(estimate) is not int or estimate<=0:
                raise ValueError('sample lacks genuine estimate/signed-limit upper: '+operation)
        singles=[sample for sample in samples if sample['workCount']==1]
        if not singles:
            raise ValueError('gas curve lacks single-work baseline: '+operation)
        billed=max(sample['gasUsed'] for sample in singles)
        selected=estimate_samples(samples)
        estimate=max(sample.get('gasEstimate') for sample in selected if sample['workCount']==1)
        bill_slope=max([0]+[-(-(sample['gasUsed']-billed)//(sample['workCount']-1)) for sample in samples if sample['workCount']>1])
        est_slope=max([0]+[-(-(sample.get('gasEstimate')-estimate)//(sample['workCount']-1)) for sample in selected if sample['workCount']>1])
        expected=dict(single_billed_gas=billed,single_estimate_gas=estimate,
            billed_per_extra_work=bill_slope,estimate_per_extra_work=est_slope)
        if costs.get('compensation_mode')=='bounded-measured-v1' and not owner and operation in METERED_OPERATIONS:
            meter_samples=[sample for sample in samples if 'measuredGas' in sample or isinstance(sample.get('measuredWork'),dict)]
            if len(meter_samples)!=len(samples):
                raise ValueError('paid operation sample lacks actual work meter: '+operation)
            meters=[(sample['workCount'],sample.get('measuredWork',sample)['measuredGas']) for sample in meter_samples]
            if any(type(value) is not int or value<0 for _,value in meters):
                raise ValueError('invalid recorded work span: '+operation)
            single=max(value for count,value in meters if count==1)
            slope=max([0]+[-(-(value-single)//(count-1)) for count,value in meters if count>1])
            expected.update(single_meter_gas=single,meter_per_extra_work=slope)
        if curves[operation]!=expected:
            raise ValueError('gas curve does not match complete recorded sample envelope: '+operation)
        for sample in samples:
            count=sample['workCount']
            if F.receipt_gas(curves,operation,count)<sample['gasUsed']:
                raise ValueError('gas curve understates measured work: '+operation)
        for sample in selected:
            if F.receipt_gas(curves,operation,sample['workCount'],estimate=True)<sample.get('gasEstimate'):
                raise ValueError('gas curve understates selected estimate work: '+operation)


def verify_sync_contexts(costs):
    if not isinstance(costs.get('fullGasSchedule'),dict) or not costs['fullGasSchedule']:
        raise ValueError('sync contexts require recorded full gas schedule')
    for owner,key in ((False,'sync_contexts'),(True,'owner_sync_contexts')):
        expected={}
        for sample in operation_samples(costs,'sync' if not owner else 'recover_sync',owner):
            context=sample.get('verifiedContext') if owner else sample.get('measuredWork',sample)
            if not isinstance(context,dict) or any(type(context.get(n)) is not int or context[n]<0 for n in ('gasAllowance','workUnits')):
                raise ValueError('sync sample lacks verified allowance/units context')
            if sample['workCount']!=1:
                raise ValueError('larger sync contexts are unmeasured')
            if owner and not context.get('pairedPaidHash'):
                raise ValueError('owner sync context lacks paired paid receipt')
            name=f"{context['gasAllowance']}:{context['workUnits']}"
            row=dict(single_billed_gas=sample['gasUsed'],single_estimate_gas=sample['gasEstimate'])
            if not owner:row['measured_gas']=context['measuredGas']
            expected[name]={field:max(value,expected.get(name,{}).get(field,0)) for field,value in row.items()}
        if not expected or costs.get(key)!=expected:
            raise ValueError('sync context envelope differs from actual recorded samples: '+key)


def qualify_costs(costs, final):
    if final:
        if costs.get('compensation_mode')!='bounded-measured-v1':
            raise ValueError('current assessment requires new measured-compensation receipts, not historical fixed quotes')
        if any(type(costs.get('gas_meter_proxy',{}).get(op)) is not int or costs['gas_meter_proxy'][op]<0 for op in METERED_OPERATIONS):
            raise ValueError('paid operations require independently recorded work meters')
    if any(not isinstance(costs.get('gas_proxy', {}).get(op), int) or costs['gas_proxy'][op] <= 0 for op in REQUIRED_GAS):
        raise ValueError('positive measured/proxy gas required for all owner and operating operations')
    if final and any(op not in KNOWN_UNSUPPORTED for op in costs.get('unmeasured_operations', [])):
        raise ValueError('final evaluation has unknown or unmeasured required operations')
    if final:
        verify_gas_curves(costs)
        if any(costs['gas_meter_proxy'][op]!=costs['gas_curves'][op]['single_meter_gas'] for op in METERED_OPERATIONS):
            raise ValueError('work meter proxy differs from recorded single-work envelope')
        if any(op not in costs.get('owner_gas_curves',{}) for op in ('unlist','liquidate')):
            raise ValueError('owner recovery requires separate unpaid gas curves')
        verify_gas_curves(costs,owner=True)
        verify_sync_contexts(costs)
        if any(type(costs.get('gas_estimate_proxy',{}).get(op)) is not int or costs['gas_estimate_proxy'][op]<=0 for op in OWNER_OPERATIONS):
            raise ValueError('final evaluation requires separate signed/estimated owner gas envelope')



def verify_measurement_receipts(costs, packets):
    def integer(value):
        return int(value, 0) if isinstance(value, str) else value
    actual = {}
    estimates = {}
    rpc_estimates = {}
    signed_limits = {}
    actual_counts = {}
    actual_meters = {}
    raw_contexts = {}
    raw_prestates = {}
    meter_topic="0x"+keccak(text="KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)").hex()
    def visit(value):
        if isinstance(value, list):
            for item in value: visit(item)
        elif isinstance(value, dict):
            receipt=value.get('receipt',{})
            transaction=value.get('transaction',{})
            if isinstance(receipt,dict) and receipt.get('transactionHash'):
                tx_hash=receipt['transactionHash'].lower()
                if isinstance(value.get('verifiedContext'),dict):raw_contexts[tx_hash]=value['verifiedContext']
                if value.get('prestateSha256'):raw_prestates[tx_hash]=value['prestateSha256']
                signed=value.get('signedGasLimit',transaction.get('gas') if isinstance(transaction,dict) else None)
                if signed is not None:
                    signed_limits[tx_hash]=integer(signed)
                    if isinstance(transaction,dict) and transaction.get('gas') is not None and integer(transaction['gas'])!=integer(signed):
                        raise ValueError('signed gas metadata differs from actual transaction gas')
                estimate=value.get('gasEstimate')
                if estimate is not None and value.get('estimateKind')!='signed-limit-upper':
                    rpc_estimates[tx_hash]=integer(estimate)
                legacy=estimate if estimate is not None else signed
                if legacy is not None:
                    estimates[tx_hash]=integer(legacy)
                if 'workCount' in value:
                    actual_counts[receipt['transactionHash'].lower()]=value['workCount']
            if 'transactionHash' in value and 'gasUsed' in value and 'status' in value:
                if integer(value['status']) == 1:
                    actual[value['transactionHash'].lower()] = integer(value['gasUsed'])
                    frames=[]
                    for log in value.get('logs',[]):
                        if log.get('topics') and log['topics'][0].lower()==meter_topic.lower():
                            data=bytes.fromhex(log['data'].removeprefix('0x'))
                            if len(data)!=160:raise ValueError('malformed actual work meter event')
                            frames.append(tuple(int.from_bytes(data[i:i+32],'big') for i in range(0,160,32)))
                    actual_meters[value['transactionHash'].lower()]=frames
            for item in value.values(): visit(item)
    if costs.get('compensation_mode')=='bounded-measured-v1':
        schedules=[packet['fullGasSchedule'] for packet in packets if 'fullGasSchedule' in packet]
        if not schedules or any(schedule!=costs.get('fullGasSchedule') for schedule in schedules):
            raise ValueError('raw sync context gas schedule differs from calibration')
    for packet in packets: visit(packet)
    for operation, samples in costs['measurements'].items():
        for sample in samples:
            tx = sample.get('hash', sample.get('transactionHash', ''))
            if actual.get(tx.lower()) != sample.get('gasUsed'):
                raise ValueError('measurement lacks matching successful billed receipt: ' + operation)
            if tx.lower() in actual_counts and sample.get('workCount')!=actual_counts[tx.lower()]:
                raise ValueError('measurement workCount differs from receipt: '+operation)
            curve_operation={'recover':'recover_sync','recoverUnlist':'unlist','recoverLiquidate':'liquidate'}.get(operation,operation)
            if costs.get('compensation_mode')=='bounded-measured-v1' and operation in METERED_OPERATIONS:
                meter=sample.get('measuredWork',sample)
                names=('measuredGas','gasAllowance','gasPrice','workUnits','essential')
                if any(name not in meter for name in names):
                    raise ValueError('sample lacks genuine five-field work meter: '+operation)
                frames=actual_meters.get(tx.lower(),[])
                expected=tuple(int(meter[name]) for name in names)
                if len(frames)!=1 or frames[0]!=expected:
                    raise ValueError('sample work meter differs from actual receipt event: '+operation)
            if costs.get('compensation_mode')=='bounded-measured-v1' and operation in OWNER_SAMPLE_ALIASES.values():
                if isinstance(sample.get('measuredWork'),dict) or 'measuredGas' in sample or actual_meters.get(tx.lower()):
                    raise ValueError('unpaid owner recovery cannot supply a paid work meter: '+operation)
            if costs.get('compensation_mode')=='bounded-measured-v1' and operation=='recover':
                context=sample.get('verifiedContext')
                if not isinstance(context,dict) or context!=raw_contexts.get(tx.lower()):
                    raise ValueError('owner sync context differs from raw paired-state provenance')
                paired=context.get('pairedPaidHash','').lower()
                frames=actual_meters.get(paired,[])
                digest=context.get('prestateSha256')
                if (len(frames)!=1 or (frames[0][1],frames[0][3])!=(context.get('gasAllowance'),context.get('workUnits'))
                        or not digest or digest!=raw_prestates.get(paired) or digest!=raw_prestates.get(tx.lower())):
                    raise ValueError('owner sync context lacks matching paid event and identical prestate')
            if curve_operation in owner_curves(costs):
                kind=sample.get('estimateKind')
                if kind not in ('rpc-estimate','signed-limit-upper'):
                    raise ValueError('measurement requires explicit estimateKind: '+operation)
                proven=(rpc_estimates if kind=='rpc-estimate' else signed_limits).get(tx.lower())
                if proven is None or sample.get('gasEstimate')!=proven:
                    raise ValueError('measurement estimate kind lacks matching raw RPC estimate/signed gas: '+operation)
    if costs.get('gas_curves'):
        return  # Count-aware curves replace op-wide estimate floors and are checked per sample.
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
    F.configured_state(0,values)  # Reject removed Fresh parameters before any financial evaluation.
    if reconciliation.get('status') != 'PASS':
        raise ValueError('current reconciliation must PASS')
    check_sources(reconciliation['source_sha256'])
    contracts = {str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'src').rglob('*.sol'))}
    if contracts != costs['contract_source_sha256']:
        raise ValueError('gas calibration belongs to another runtime source candidate')
    if args.final:
        if not isinstance(costs.get('source_sha256'),dict) or not costs['source_sha256']:
            raise ValueError('final gas packet requires writer/helper source bindings')
        check_sources(costs['source_sha256'])
    qualify_costs(costs, args.final)
    if costs.get("fullGasSchedule")!=values["gasSchedule"]:
        raise ValueError("sync context calibration gas schedule differs from current settings")
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
        full_gas_schedule=costs['fullGasSchedule'],sync_contexts=costs['sync_contexts'],owner_sync_contexts=costs['owner_sync_contexts'],
        compensation_mode='bounded-measured-v1',gas_meter_proxy=costs.get('gas_meter_proxy',{}),
        gas_meter_max_work=supported_work(costs),owner_gas_max_work=supported_work(costs,owner=True),
        owner_gas_curves=costs.get('owner_gas_curves',{}),
        archive_coverage=dict(first_timestamp=first,last_timestamp=last,top_block=top), windows=windows,
        cells=list(CELLS), paths_per_window=args.paths_per_window, operating_days=30, exit_days=7,
        initial_funding_wei=CAPITAL, owner_exit_spend_limit_wei=args.owner_exit_spend_limit_wei,
        final_gas_qualification=args.final, gas_proxy=costs['gas_proxy'],
        gas_estimate_proxy=costs.get('gas_estimate_proxy',{}),gas_curves=costs.get('gas_curves',{}),
        estimate_curve_sources={op:estimate_samples(operation_samples(costs,op))[0]['estimateKind'] for op in costs.get('gas_curves',{})},
        unmeasured_operations=costs.get('unmeasured_operations', []), manager_values=values,
        mint_fee_observation=observation, protocol_minimum_backing=minimum,
        fee_cases={str(25*10**13):'Agent-chosen fork-only half-current sensitivity; not approved baseline',
                   str(5*10**14):'Observed current mint fee',str(10**15):'Historical/accepted maximum comparison'},
        expected_rows=2*(2*args.paths_per_window+4)*len(CELLS),
        buyer_regimes=['observed-choices','forced-responsive-bid-stress'],
        physical_sync_cost_basis='Exact verified allowance/units context under recorded full GasSchedule; paid event spans and separately billed paired unpaid recovery receipts. Unknown contexts refuse; quote coefficients are not actual gas expense',
        keeper_policy='Production billed_ratio defaults then same-label receipt history, with additional independently billed cost floor; actual cost ledger uses billed curve; failure/minimum-return/max-loss all zero',
        keeper_initial_billed_ratios=dict(BILLED_PER_ESTIMATE),keeper_receipt_history_start='Fresh keeper, empty per scenario; no other account receipts',
        response_method='Paired request-keyed response cohort. Observed choices retain first archived keep/bid and delay; stress forces every archived eventual responder to bid within3480seconds. Unresolved stays silent in both.',
        assumptions=[
            'Thirty operating days and at most seven exit days. Recorded-month requests repeat during exit; quiet has no requests; early burst repeats the busiest actual day twice at whole-day offsets then has no requests.',
            'The fixed path count is an agent choice for bounded descriptive evaluation; no sample-size threshold or future-return confidence is claimed. No outcome-dependent stopping or exclusion.',
            'Foreign request timing, recorded success/refund and weights are fixed. Added manager listings dilute allocation/fees; external market participants do not react.',
            'Response cohorts have unequal follow-up/right censoring. Observed choices preserve archived keeps and late delays; the second regime forces every eventual responder to bid by3480seconds, including late/archive-after-window responses. Neither is a forecast or exact VRF replay.',
            'Current protocol fee rules and oracle exemption are applied to historical requests. Historical configuration changes are not individually replayed. The .00025ETH fee is an agent-chosen fork-only half-current sensitivity, not a production recommendation or approval of baseline economics; no public fee changes.',
            'Standard .03 backing relaxes only admission in an isolated worker. Current manager rejects it; it is not an executable candidate configuration.',
            'Reuse-only strategy: returned packs are relisted intact, no fresh renewal eligibility or float. Canonical reserves, cash and spending permissions remain; no account topups or volunteer keeper subsidy. Compensation uses independently recorded work-span proxies bounded by operation allowances, plus named overhead; it is not billed gas or a fixed quote. Censored spans remain explicit.',
            'Keeper acceptance reuses production billed_ratio: initial per-operation defaults, then after3 same-label receipts min(1,sum billed gas / sum estimates across the last20). Each path starts with a fresh keeper and no other-account history. Accepted ordinary calls add calibrated proxy bill/estimate pairs; owner recovery does not. A separate calibrated billed cost floor forbids assumed losses. Replacement/minPay-specific estimate changes, failed inclusion and external-account history are not modeled. Estimate curves prefer genuine RPC samples with an RPC single-work baseline, otherwise explicit historical signed-limit uppers; billed curves cover all samples. The25percent signing pad belongs only to the owner cap.',
            'Paid meter curves and unpaid owner recovery bill/estimate curves use separate actual samples. Modeled paid and owner work counts above actual receipt support are refused, including larger sync batches. Non-sync gas uses count-aware receipt curves independently of mutable quote allowances. Sync requires an exact recorded allowance/units context under the same full GasSchedule; unknown journal, scan, fee-claim or multiple-position patterns are refused. These are calibrated proxies, not actual receipts for simulated calls. Creator amounts are gross accrual; global deployment/service costs are outside per-clone owner returns.',
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
    remaining=MC.validate_finances(result,fee)
    row={key:value for key,value in result.items() if key!='operating_budget_marks'}
    row['remaining_assets_wei']=remaining
    row['owner_realized_cash_net_so_far_wei']=row['owner_withdrawn_wei']-row['owner_funded_wei']-row['owner_wallet_gas_proxy_wei']
    if final and row.get('compensation_mode')!='bounded-measured-v1':
        raise ValueError('final model did not use measured compensation')
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
    if final and not row.get('keeper_receipt_history_enabled'):
        raise ValueError('final assessment requires production receipt-history keeper acceptance')
    if final and not row.get('keeper_estimate_acceptance_enabled'):
        raise ValueError('final assessment requires estimated-gas keeper acceptance')
    if final and not row.get('physical_sync_cost_basis_enabled'):
        raise ValueError('final assessment requires verified sync context costing')
    if final and not row.get('count_aware_gas_curves_enabled'):
        raise ValueError('final assessment requires count-aware gas curves')
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
        values = frozen['manager_values'] | dict(backingRatioBps=cell['backing_bps'])
        sc = F.Scenario(manager=True, volume=F.const(0), timed=True, start_timestamp=w['start'],
            poll_seconds=60, receipt_seconds=36, replay_events=events,replay_period_seconds=period,
            request_randomness=True, request_response_sampler=response, foreign_pool_weight=1.,exempt=True,
            gwei=cell['total_gas_gwei']-.05, deposit_wei=CAPITAL,mint_fee_wei=cell['mint_fee_wei'],
            exit_all=True,exit_days=frozen['exit_days'], user_gas_proxy=frozen['gas_proxy'],
            holder_rescue_sync=True,self_serve_exits=True,unmeasured_gas_operations=frozen['unmeasured_operations'],
            user_gas_estimate_proxy=frozen['gas_estimate_proxy'],gas_curves=frozen['gas_curves'],gas_meter_proxy=frozen['gas_meter_proxy'],gas_meter_max_work=frozen['gas_meter_max_work'],
            owner_gas_curves=frozen['owner_gas_curves'],owner_gas_max_work=frozen['owner_gas_max_work'],
            full_gas_schedule=frozen['full_gas_schedule'],sync_contexts=frozen['sync_contexts'],owner_sync_contexts=frozen['owner_sync_contexts'],
            manager_keeper_zero_loss=True,manager_keeper_receipt_history=True, owner_exit_spend_limit_wei=frozen['owner_exit_spend_limit_wei'])
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
            all(other[k]==c[k] for k in ('mint_fee_wei','total_gas_gwei')))
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
        lines.append(f"| {c['buyer_regime']} / {c['regime']} | {'Reuse'} | {'.03 hypothetical' if c['backing_bps']==10000 else '.21'} | {c['mint_fee_wei']/F.E:g} | {c['total_gas_gwei']} | {c['qualified_exits']}/{c['expected_paths']} | {money(c['owner_net_mean_wei'])} | {money(m['external_total_earned_wei'])} | {money(m['keeper_compensation_wei'])} / {money(m['keeper_gas_proxy_cost_wei'])} | {money(m['creator_primary_fees_accrued_wei'])} | {money(c['maximum_unresolved_assets_wei'])} |")
    lines += ['', 'JSON retains each path and owner/keeper/creator/physical-asset partitions. Owner exit calls stop before cumulative signed maxima exceed the exit cap, excluding clone creation. Unfinished exits retain cash/inventory; the cap does not guarantee completion.', '']
    lines += [paragraph for item in report['manifest']['assumptions'] for paragraph in (item,'')]
    lines += ["Things that don't make sense: a positive conditional mean cannot establish future profitability; an exit-spend cap can stop recovery with assets still held; isolated .03 admission cannot be deployed through this manager.",'']
    return '\n'.join(lines)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--final',action='store_true',help='Reject any unmeasured required/executed operation')
    parser.add_argument('--costs',default='docs/receipts/manager-measured-cost-calibration.json')
    parser.add_argument('--reconciliation',default='docs/receipts/manager-measured-reconciliation.json')
    parser.add_argument('--live-observation',default='docs/receipts/manager-r2-live-observation.json')
    parser.add_argument('--minimum-continuity',default='docs/receipts/manager-r2-min-backing-continuity.json')
    parser.add_argument('--archive',default='sim/data/fwa.sqlite')
    parser.add_argument('--paths-per-window',type=int,default=8)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--owner-exit-spend-limit-wei','--wallet-cap-wei',dest='owner_exit_spend_limit_wei',type=int,default=10**16)
    parser.add_argument('--out',default='sim/out/manager-measured-operating-assessment')
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
