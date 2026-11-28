#!/usr/bin/env python3
"""Hypothetical1:1 backing supplement; current manager contracts reject this admission."""
import argparse
import copy
import json
import sqlite3
import statistics
import sys
from pathlib import Path

import manager_monte_carlo as MC
import forward as F
from keeper import proposal_limits as canonical_limits

ROOT=MC.ROOT
STANDARD_CELLS=tuple(dict(id=f'b10000-g{gas}',backing_bps=10000,total_gas_gwei=gas) for gas in (.2,.5))
ORIGINAL_INIT=MC.worker_init
ORIGINAL_SUMMARIZE=MC.summarize
CANONICAL_EDGE=F.policy.edge_backing
MIN_BACKING=None


def archived_minimum(archive):
    with sqlite3.connect(f'file:{archive}?mode=ro',uri=True) as db:
        for block,index,args in db.execute("SELECT block,log_index,args FROM logs WHERE event='ConfigSet' ORDER BY block DESC,log_index DESC"):
            values=json.loads(args)
            if int(values['key'])==22:
                return dict(value_wei=int(values['value']),block=block,log_index=index,
                    method='Latest archived actual FWA ConfigSet key22; not a fresh public-state read')
    raise ValueError('archive lacks actual FWA minimum-backing configuration')


def relaxed_edge(k,cap,s_bps,units,gas_ceiling,markup_bps,work_fee,buffer_bps=0,min_edge_bps=100,
                 discount_bps=9150,price=None,mint_fee=10**15,backing_ratio_bps=10000,
                 gas_schedule=None,renewal_mode=0,newly_built=True,reference_units=None,retirement_shapes=None):
    desired=units*F.policy.UNIT*backing_ratio_bps//10000//10000*10000
    if cap is not None:desired=min(desired,cap*(10000-buffer_bps)//10000//10000*10000)
    return desired if desired>=MIN_BACKING else 0


def relaxed_limits(state,value,settlement_fee,discount,cap,build=False,units=3,retirement_shapes=None):
    if not 0<discount<=10000 or not 0<=settlement_fee<10000 or cap<MIN_BACKING:
        return 1,0
    return -(-MIN_BACKING//10000)*10000,cap//10000*10000


def relaxed_build_net(state):
    return int(state.backing>=MIN_BACKING)


def worker_init(manifest):
    global MIN_BACKING
    ORIGINAL_INIT(manifest)
    MIN_BACKING=manifest['standard_backing_regime']['protocol_minimum']['value_wei']
    import keeper
    F.policy.edge_backing=relaxed_edge
    keeper.proposal_limits=relaxed_limits
    F.policy.build_net=relaxed_build_net


def diagnostic(parent):
    values=parent['manager_values'];observation=parent['mint_fee_observation']
    k=parent['model_gross_multiplier_1e18']
    foreign=observation['protocol']['totalWeight']
    rows=[]
    for fee in sorted({parent['mint_fee_wei'],10**15}):
      for gas in (.2,.5):
       for backing in (3*10**16,15*10**16,21*10**16):
        ratio=backing*10000//(3*10**16)
        s=F.configured_state(round((gas-.05)*10**9),values|dict(backingRatioBps=ratio,renewalMode=0))
        s.k=k;s.backing=backing;s.mint_fee=fee;s.settlement_fee_bps=100
        q=s.gas_schedule
        common={name:q[name] for name in ('sync','journal','selected','synced','pruned','sync_funding','harvested','sync_credit')}
        retirement=dict(liquidate=q['liquidate'],pack=q['liq_pack'],three_shapes=3*q['redeem_shape'])
        construction=dict(build=q['build'],pack=q['build_pack'],three_shapes=3*q['build_shape'],listed=q['listed'])
        cycle_quote=F.policy.quote(s,sum(common.values())+sum(retirement.values()),2)
        keep_maintenance_quote=F.policy.quote(s,sum(common.values()),1)
        build_quote=F.policy.quote(s,sum(construction.values()),2)
        cost=cycle_quote+build_quote+3*fee
        keep_cost=keep_maintenance_quote+build_quote+3*fee
        bid=backing*(k-10**18)//10**18
        keep=backing*(k-10**16)//10**18-3*10**16
        minimum,_=canonical_limits(s,3*10**16,100,9000,2**256-1,build=True,units=3)
        edge=CANONICAL_EDGE(k,None,100,3,s.gas_ceiling,s.markup_bps,s.work_fee,
            price=F.policy.price(s),mint_fee=fee,backing_ratio_bps=ratio,gas_schedule=q,renewal_mode=0)
        reasons=[]
        if backing<-(-(3*10**16)*10000//9500):reasons.append('IMMUTABLE_95PCT_FACE_COVERAGE')
        if bid<=cost:reasons.append('BID_CYCLE_NOT_PROFITABLE')
        if keep<cost:reasons.append('KEEP_CYCLE_NOT_PROFITABLE')
        own_weight=10**36//backing
        rows.append(dict(backing_wei=backing,pack_principal_wei=3*10**16,mint_count=3,mint_fee_per_shape_wei=fee,
            total_gas_gwei=gas,k_1e18=k,bid_cycle_gross_wei=bid,keep_cycle_gross_after_face_wei=keep,
            primary_mint_fees_wei=3*fee,construction_quote_wei=build_quote,
            bid_maintenance_and_retirement_quote_wei=cycle_quote,keep_maintenance_quote_wei=keep_maintenance_quote,
            canonical_admission_conservative_cost_wei=cost,bid_cycle_quoted_cost_wei=cost,keep_cycle_quoted_cost_wei=keep_cost,
            bid_cycle_net_after_quoted_cost_wei=bid-cost,keep_cycle_net_after_quoted_cost_wei=keep-keep_cost,
            quote_gas_components=dict(construction=construction,maintenance=common,retirement=retirement),
            work_units=dict(construction=2,bid_maintenance_and_retirement=2,keep_maintenance=1),
            conditional_collection_included_once=['sync_funding','harvested','sync_credit'],
            canonical_admission_backing_wei=edge,canonical_rejection_reasons=reasons,
            canonical_minimum_backing_quantized_wei=-(-minimum//10000)*10000,
            initial_pack_and_backing_capital_wei=backing+3*10**16,
            first_productive_account_funding_wei=F.policy.position_value(s)+F.policy.build_cost(s)+values['reserveWei']+F.policy.renewal_float(s,values['renewalFloatCount']),
            own_selection_weight_1e18=own_weight,selection_probability_against_same_live_foreign_pool=own_weight/(foreign+own_weight)))
    return dict(kind='Unmodified current manager admission and per-outcome quoted single-cycle screens',rows=rows,
        limitations=['Both outcome screens count one fresh construction/listing and three paid mints. Bid maintenance includes returned-pack retirement and four total service units; keep has no retirement and three total service units. The canonical admission screen separately retains the conservative bid/retirement cost for both outcome guards.',
          'Conditional fee collection is included once as a conservative allowance, not a claim it occurs every cycle. These are quoted cost screens, not billed actual costs; per-path canonical calls remain the operating cost source.',
          'This screen is not a full-period return. Initial startup and final exit wallet gas are counted by the operating simulation, not invented from this single-cycle screen.',
          'Selection probabilities use one listing against the same observed live foreign weight; operating position counts and selection probabilities vary with cash and archived request weights.'])


def campaign_manifest(parent_path,args):
    raise RuntimeError('Historical fixed/Fresh financial generator requires its pinned revision')
    parent=json.loads(parent_path.read_text())
    if args.paths!=parent['paths_per_cell'] or args.seed_start!=parent['windows'][0]['seed_start'] or args.window_end:
        raise ValueError('standard supplement retains every frozen parent path ID and window')
    if not 1<=args.workers<=8:raise ValueError('workers must be1..8')
    for name,expected in parent['source_sha256'].items():
        if MC.digest(ROOT/name)!=expected:raise ValueError('parent input changed: '+name)
    for name,expected in parent['contract_source_sha256'].items():
        if MC.digest(ROOT/name)!=expected:raise ValueError('parent contract changed: '+name)
    result=copy.deepcopy(parent)
    result['cells']=list(STANDARD_CELLS)
    result['parent_campaign_hash']=MC.canonical_hash(parent)
    result['parent_manifest']=str(parent_path.relative_to(ROOT))
    result['parent_manifest_sha256']=MC.digest(parent_path)
    result['source_sha256'][result['parent_manifest']]=result['parent_manifest_sha256']
    for name in ('sim/manager_standard_backing.py','sim/test_manager_standard_backing.py'):
        result['source_sha256'][name]=MC.digest(ROOT/name)
    minimum=archived_minimum(ROOT/parent['archive'])
    minimum_path='docs/receipts/manager-r2-min-backing-continuity.json'
    confirmation=json.loads((ROOT/minimum_path).read_text())
    if (confirmation.get('readOnly') is not True or confirmation.get('retainedToProtocol') is not True
        or confirmation.get('rpc')!='https://mainnet.gateway.tenderly.co'
        or confirmation.get('configKey')!=22 or confirmation.get('subsequentLogs')!=[]
        or confirmation.get('fromBlock')!=parent['archive_coverage']['top_block']+1
        or confirmation.get('toBlock')!=parent['mint_fee_observation']['block']
        or confirmation.get('blockHash')!=parent['mint_fee_observation']['blockHash']
        or confirmation.get('archiveLastChange')!=dict(block=minimum['block'],valueWei=minimum['value_wei'])):
        raise ValueError('minimum backing live confirmation does not bind the frozen archive and observation')
    minimum['live_confirmation']=confirmation
    result['source_sha256'][minimum_path]=MC.digest(ROOT/minimum_path)
    if minimum['value_wei']>3*10**16:raise ValueError('standard .03backing is below archived FWA admission minimum')
    result['standard_backing_regime']=dict(label='RELAXED_ADMISSION_FORCED_BID_REFERENCE_NOT_CURRENT_CONTRACT',
        protocol_minimum=minimum,overrides=['policy.edge_backing: requested ratio, positive protocol minimum/cap and quantization retained; manager coverage/profit admission omitted',
            'keeper.proposal_limits: protocol minimum/cap, quantization and valid settlement/discount inputs retained; manager coverage/profit floors omitted',
            'policy.build_net: permit negative-edge ordinary construction when otherwise funded'],
        unchanged=['Actual protocol k, fees and settlement outcomes','Three paid primary mints, recipe and fresh renewal',
            'Canonical integer account ledger, funding/reserves, budget/permission, payment and gas-cost logic',
            'Canonical bounded planner, unique backing proposals, request tape, buyer stress, actor and owner-paid exit behavior'],
        parent_interpretation='Only .03backing is hypothetical. Parent .15/.21 results retain unmodified manager admission.',
        limits=['Not deployable through current manager contracts; no claim of fork integration for relaxed admission.',
            'Uses manager-batched wallet/keeper gas proxies, not receipts proving a manual operator can reproduce these costs.',
            'Forced responsive bids are not a worst-case buyer choice at .03backing: keep is worse by .0003ETH per-cycle before gas. Bid and keep screens are both reported.',
            'The same .5ETH funding supports different position counts at each backing; this changes selection exposure and cash use, not just loss per acquisition.',
            'Finite cash and spending permission can prevent construction or renewal; no hidden topup or positive-return filter is added.'])
    result['assumptions']+=result['standard_backing_regime']['limits']
    result['inference']['standard_comparisons']='Four standard-minus-parent contrasts (.15/.21 at two gas levels), each two-sided98.75%; Bonferroni family95%'
    result['unmodified_admission_diagnostic']=diagnostic(parent)
    return result


def summarize(rows,manifest):
    report=ORIGINAL_SUMMARIZE(rows,manifest)
    report.pop('paired_backing_differences',None)
    report['standard_backing_regime']=manifest['standard_backing_regime']
    report['position_exposure']={cell['id']:dict(
        time_average_positions=MC.distribution([r['mean_positions'] for r in rows if r['cell']==cell['id']]),
        maximum_positions=MC.distribution([r['maximum_positions'] for r in rows if r['cell']==cell['id']]))
        for cell in manifest['cells']}
    report['standard_vs_manager_paired_differences']=[]
    parent_path=ROOT/manifest['parent_manifest']
    parent_summary=parent_path.parent/'summary.json'
    if not parent_summary.exists() or not json.loads(parent_summary.read_text()).get('finished'):
        report['parent_comparison_status']='Awaiting complete immutable parent campaign; standard results remain separately available'
        return report
    parent=json.loads(parent_path.read_text())
    if json.loads(parent_summary.read_text())['campaign_hash']!=manifest['parent_campaign_hash']:
        raise ValueError('parent summary belongs to another frozen campaign')
    parent_rows,_=MC.read_rows(parent_path.parent/'paths.jsonl',parent)
    if len(parent_rows)!=parent['paths_per_cell']*len(parent['cells']):
        raise ValueError('parent result file is incomplete')
    indexed={(r['window'],r['seed'],r['cell']):r for r in rows+parent_rows}
    z=statistics.NormalDist().inv_cdf(1-.05/(2*4))
    for gas in (.2,.5):
      for ratio in (50000,70000):
        deltas=[];labels=[];missing=0
        for w in manifest['windows']:
          for seed in range(w['seed_start'],w['seed_end_exclusive']):
            standard=indexed.get((w['id'],seed,f'b10000-g{gas}'))
            comparison=indexed.get((w['id'],seed,f'b{ratio}-g{gas}'))
            if standard is None or comparison is None or not standard['exit_complete'] or not comparison['exit_complete']:
                missing+=1;continue
            if standard['request_events_sha256']!=comparison['request_events_sha256']:raise ValueError('paired request tapes differ')
            deltas.append((standard['owner_net_wei']-comparison['owner_net_wei'])/10**18);labels.append(w['id'])
        diagnostic=MC.distribution(deltas,z,labels)
        primary=diagnostic if not missing else dict(**MC.distribution([]),suppressed=True,reason='Missing or incomplete paired exits')
        report['standard_vs_manager_paired_differences'].append(dict(total_gas_gwei=gas,parent_backing_bps=ratio,
            direction='Hypothetical .03 minus current-admission parent owner realized net ETH',paired=primary,
            completed_pair_diagnostic=diagnostic,unavailable_pairs=missing,individual_confidence=.9875,family_confidence=.95))
    report['parent_comparison_status']='Paired by exact frozen window/pathID/request tape; incomplete pairs suppress primary inference'
    return report


def main():
    raise SystemExit('Historical fixed/Fresh study: use its pinned revision; active evaluations require manager_operating_assessment.py with a current measured profile')
    parser=argparse.ArgumentParser(add_help=False)
    parser.add_argument('--parent-manifest',default='sim/out/manager-monte-carlo-funded/manifest.json')
    args,remaining=parser.parse_known_args()
    parent_path=ROOT/args.parent_manifest
    MC.CELLS=STANDARD_CELLS
    MC.input_manifest=lambda options:campaign_manifest(parent_path,options)
    MC.worker_init=worker_init
    MC.summarize=summarize
    if '--out' not in remaining:remaining+=['--out','sim/out/manager-standard-funded']
    sys.argv=[sys.argv[0],*remaining]
    MC.main()


if __name__=='__main__':main()
