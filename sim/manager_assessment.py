#!/usr/bin/env python3
"""Bounded personal-manager counterfactuals; no pooled-vault hurdle or pool evidence mutation."""
import argparse
import hashlib
import json
import statistics
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import forward as F
from formal import window, flatten, PIN, WINDOW

ROOT=Path(__file__).resolve().parent.parent
SOURCES=['sim/manager.py','sim/forward.py','sim/manager_assessment.py','sim/manager_reconcile.py','sim/vault.py','keeper/policy.py','keeper/config.py','deploy/manager.json','deploy/mint-fee-observation.json','deploy/manager-mint-fee-observation.json']


def feasible_burst(w):
    """Repeat the busiest actual 24h request cohort twice; preserve latency and blackout phase."""
    cohorts={}
    for request,completion,payload in w['pairs']:
        if request==0:continue  # Opening carryovers are not new requests.
        cohorts.setdefault(request//F.DAY,[]).append((request,completion,payload))
    day,events=max(cohorts.items(),key=lambda item:sum(int(p[2][0]) for p in item[1]))
    pairs=[(r-day*F.DAY+repeat*F.DAY,c-day*F.DAY+repeat*F.DAY,payload)
           for repeat in (0,1) for r,c,payload in events]
    assert all((w['start']+r)%F.OperatingClock.INTERVAL<F.OperatingClock.BLACKOUT_START for r,_,_ in pairs)
    assert all(c>=r for r,c,_ in pairs)
    return flatten(pairs),dict(actual_day_index=day,requests=len(pairs),successful=sum(p[0] for _,_,p in pairs),
        method='Actual busy-day pairs repeated at whole-day offsets; original request-to-completion delays and blackout phase retained. No new requests after day2.')


def scenario(w,events,period,price,capital,fee,gas):
    def purchaser(rng):
        delay,_=w['responses'][int(rng.integers(len(w['responses'])))]
        return (None,None) if delay is None else (min(delay,F.OperatingClock.SETTLEMENT-120),False)
    return F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=w['start'],poll_seconds=60,
        receipt_seconds=36,replay_events=events,replay_period_seconds=period,response_sampler=purchaser,
        foreign_pool_weight=1.0,exempt=True,gwei=price-.05,deposit_wei=capital,mint_fee_wei=fee,
        exit_all=True,exit_days=7,user_gas_proxy=gas,holder_rescue_sync=True,self_serve_exits=True)


def jobs(w,gas):
    values=json.loads((ROOT/'deploy/manager.json').read_text());out=[]
    for mode in (0,1):
      for fee in (10**15,5*10**14):
       for price in (.2,.5):
        for capital in (5*10**17,2*F.E):
         for seed in (1,2):out.append(('recorded-month',mode,fee,price,capital,seed,w['events'],WINDOW,{}))
        out.append(('zero-demand',mode,fee,price,5*10**17,1,[],38*F.DAY,{}))
    burst,metadata=feasible_burst(w)
    for mode in (0,1):
     for price in (.2,.5):
      for tight in (False,True):
       override={'routineCapWei':4*10**15,'routineRatePerDayWei':0} if tight else {}
       out.append(('early-burst-low-permission' if tight else 'early-burst-then-zero',mode,5*10**14,price,2*F.E,1,burst,38*F.DAY,override))
    assert len(out)==48
    return [(w,gas,values,*job) for job in out],metadata


def one(job):
    w,gas,values,label,mode,fee,price,capital,seed,events,period,override=job
    values=values|{'renewalMode':mode}|override
    sc=scenario(w,events,period,price,capital,fee,gas)
    sc['unmeasured_gas_operations']=w.get('unmeasured_gas_operations',[])
    result=F.run(sc,1,seed,days=30,values=values)
    assert result['ledger_gap_wei']==0
    assert result['routine_keeper_paid_wei']<=result['routine_period_permission_upper_wei']
    return dict(label=label,renewal_mode=mode,mint_fee_wei=fee,total_price_gwei=price,
        seed=seed,fee_case='current' if fee==5*10**14 else 'historical-higher-fee',parameter_overrides=override,**result)


def summarize(rows):
    groups={}
    for row in rows:
        key=(row['label'],row['renewal_mode'],row['mint_fee_wei'],row['total_price_gwei'],row['initial_funding_wei'])
        groups.setdefault(key,[]).append(row)
    output=[]
    for (label,mode,fee,price,capital),cell in groups.items():
        net=[r['owner_net_wei']/F.E for r in cell if r['owner_net_wei'] is not None]
        median=statistics.median(net) if net else None
        output.append(dict(label=label,renewal_mode=mode,mint_fee_wei=fee,total_price_gwei=price,initial_funding_wei=capital,
            draws=len(cell),complete_exits=sum(r['exit_complete'] for r in cell),standard_median_owner_net_eth=median,
            standard_median_owner_return_pct=median/(capital/F.E)*100 if median is not None else None,
            worst_owner_net_eth=min(net) if net else None,loss_draws=sum(x<0 for x in net),
            median_owner_wallet_gas_eth=statistics.median(r['owner_wallet_gas_proxy_wei']/F.E for r in cell),
            median_keeper_compensation_eth=statistics.median(r['keeper_compensation_wei']/F.E for r in cell),
            median_keeper_gas_proxy_eth=statistics.median(r['keeper_gas_proxy_cost_wei']/F.E for r in cell),
            median_keeper_net_proxy_eth=statistics.median(r['keeper_net_proxy_wei']/F.E for r in cell),
            median_creator_gross_primary_fees_eth=statistics.median(r['creator_primary_fees_accrued_wei']/F.E for r in cell),
            waiting_observations={k:sum(r['waiting_observations'].get(k,0) for r in cell) for k in sorted({k for r in cell for k in r['waiting_observations']})},
            maximum_unresolved_assets_wei=max(r['physical_assets_wei']+r['external_fee_credit_wei']+r['unharvested_listing_fees_wei'] for r in cell),
            unmeasured_keeper_operations=sorted({k for r in cell for k in r['keeper_unmeasured_operations']}),
            unknown_owner_gas_calls=sum(r['unknown_owner_gas_calls'] for r in cell)))
    return output


def write_economics(report,costs):
    defaults=report['manager_defaults'];opening=[]
    for mode in (0,1):
      for fee in (5*10**14,10**15):
       for price in (.2,.5):
        state=F.configured_state(round((price-.05)*F.GWEI),defaults|{'renewalMode':mode});state.mint_fee=fee
        float_need=F.policy.renewal_float(state,defaults['renewalFloatCount'])
        opening.append(dict(renewal_mode=mode,mint_fee_wei=fee,total_price_gwei=price,
            reference_capital_wei=F.policy.position_value(state),mint_fees_and_build_quote_wei=F.policy.build_cost(state),
            renewal_float_wei=float_need,reserve_wei=defaults['reserveWei'],
            first_pack_funding_wei=F.policy.position_value(state)+F.policy.build_cost(state)+float_need+defaults['reserveWei']))
    report['opening_funding']=opening
    def money(x):return 'incomplete' if x is None else f'{x:.8f}'
    lines=['# Personal manager economics','',
        '**Candidate evaluation, not a production recommendation or realized return.** Recipe: three paid 0.01 ETH Shapes per 0.03 ETH pack; backing 0.21 ETH. No personal-manager return hurdle has been approved.',
        '',f"Current mint fee: **0.0005 ETH** at block **{report['mint_fee_observation']['block']}**. The 0.001 ETH cells are the historical higher-fee comparison. Activity remains the separately pinned 30-day study ending at block {PIN['block']}. No public fee transaction was sent.",
        '',f"{len(report['rows'])} bounded runs: 32 recorded-month, eight zero-demand and eight feasible early-burst cases. Recorded-month cells have two draws. Standard medians average the middle pair; downside and incomplete exits remain visible. All owner amounts include clone creation, owner exit and required pending-queue processing wallet gas. Operating keeper payments and fresh-mint fees are charged once to account cash.",
        '', '## Recorded month: owner, keeper and creator in the same cells','',
        'Amounts are ETH over 30 operating days plus at most seven exit days. Keeper gas is a calibrated proxy. Creator amounts are gross paid primary-fee accrual, not withdrawn cash or profit after startup costs.','',
        '| Mode | Fee | Gas gwei | Funding | Exit | Owner median net | Worst | Losses | Keeper paid / gas / net | Creator gross |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for s in report['summary']:
        if s['label']!='recorded-month':continue
        lines.append(f"| {'Fresh' if s['renewal_mode']==0 else 'Reuse'} | {s['mint_fee_wei']/F.E:g} | {s['total_price_gwei']:g} | {s['initial_funding_wei']/F.E:g} | {s['complete_exits']}/{s['draws']} | {money(s['standard_median_owner_net_eth'])} | {money(s['worst_owner_net_eth'])} | {s['loss_draws']}/{s['draws']} | {money(s['median_keeper_compensation_eth'])} / {money(s['median_keeper_gas_proxy_eth'])} / {money(s['median_keeper_net_proxy_eth'])} | {money(s['median_creator_gross_primary_fees_eth'])} |")
    lines+=['','## Quiet use and feasible early burst','','The burst repeats the busiest actual request day twice at whole-day offsets, retains authentic completion delays and blackout phase, and then stops requests. Tight permission uses a 0.004 ETH routine cap with zero refill. Wait counts are planner observations, not distinct transactions or an elapsed-time claim.','',
        '| Regime | Mode | Fee | Gas | Owner median net | Worst | Exit | Keeper paid / gas / net | Creator gross | Wait observations |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---|']
    for s in report['summary']:
        if s['label']=='recorded-month':continue
        waits=', '.join(f'{k}: {v}' for k,v in s['waiting_observations'].items() if v) or 'none'
        lines.append(f"| {s['label']} | {'Fresh' if s['renewal_mode']==0 else 'Reuse'} | {s['mint_fee_wei']/F.E:g} | {s['total_price_gwei']:g} | {money(s['standard_median_owner_net_eth'])} | {money(s['worst_owner_net_eth'])} | {s['complete_exits']}/{s['draws']} | {money(s['median_keeper_compensation_eth'])} / {money(s['median_keeper_gas_proxy_eth'])} / {money(s['median_keeper_net_proxy_eth'])} | {money(s['median_creator_gross_primary_fees_eth'])} | {waits} |")
    lines+=['','## First productive opening','','Account cash needed for the first pack includes 0.24 ETH face plus backing, actual paid mint fees, the quoted build payment, maintenance reserve and conservative renewal float. Owner clone-creation wallet gas is additional. Accepted maximum remains 0.001 ETH per mint in both fee cases; lower actual fees do not silently release the conservative float.','',
        '| Mode | Actual fee | Gas gwei | Account funding | Float included |','|---|---:|---:|---:|---:|']
    lines += [f"| {'Fresh' if p['renewal_mode']==0 else 'Reuse'} | {p['mint_fee_wei']/F.E:g} | {p['total_price_gwei']:g} | {p['first_pack_funding_wei']/F.E:.8f} | {p['renewal_float_wei']/F.E:.8f} |" for p in opening]
    lines+=['','## Interpretation and limits','',
        'Retain manager.json as a candidate. Two paths per baseline cell cannot establish an expected return or justify changing the owner’s settings. Fresh renewal pays for three new mints after each acquisition and retains its designated float; reuse relists returned inventory. A manager has one owner and no share-pricing uncertainty gate, checkpoint charges, dead shares or depositor refunds.',
        '', 'Owner-funded final maintenance bypasses keeper-profit selection, pays no keeper reward and is charged to the owner wallet. Cash availability and spending permission remain separate. Recorded ordinary VRF/processing is funded by historical external actors; pending queue work required at exit carries a conservative owner reserve, charging a full measured single-request processing call per pending record in batches of at most 16. This is a gas reserve, not a claim those archived events were replayed as new owner receipts.',
        '',f"Unmeasured gas operations: {', '.join(costs.get('unmeasured_operations',[])) or 'none declared'}. Where a quoted allowance substitutes for a billed receipt, keeper net is a proxy and may differ from inclusion costs. Global factory deployment and production service costs are one-time operator costs outside per-clone owner returns. Primary fees accrue to the Shapes creator and are not creator net profit.",
        '', 'All numerical scenario results are conditional on the matched real-fork manager transitions and the frozen receipt/proxy inputs. The archive’s foreign weights and buyer behavior do not react to the manager. Fee and gas cases can follow different paths, so differences across two draws are not causal estimates of a fee change. Prior pooled-vault evidence is preserved separately.',
        '', 'Things that don’t make sense: a profitable keeper quote or a fully balanced ledger does not establish positive owner returns; unresolved gas measurements and the two-draw sample limit any stronger conclusion.','']
    (ROOT/'docs/receipts/manager-economics.md').write_text('\n'.join(lines))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--execute',action='store_true');ap.add_argument('--workers',type=int,default=4)
    ap.add_argument('--costs',default='docs/receipts/manager-cost-calibration.json');ap.add_argument('--reconciliation',default='docs/receipts/manager-reconciliation.json');a=ap.parse_args()
    if not a.execute:raise SystemExit('Plan:48 runs; execution follows root freeze and one batched manager verification pass.')
    import os
    if os.environ.get('CANDIDATE_RUN')!='1':raise SystemExit('frozen candidate requires CANDIDATE_RUN=1')
    reconciliation=json.loads((ROOT/a.reconciliation).read_text());assert reconciliation['status']=='PASS'
    for name in ('sim/manager.py','sim/vault.py','sim/forward.py','keeper/policy.py','keeper/config.py'):
        assert reconciliation['source_sha256'][name]==hashlib.sha256((ROOT/name).read_bytes()).hexdigest(),'stale manager reconciliation:'+name
    costs=json.loads((ROOT/a.costs).read_text());gas=costs['gas_proxy']
    contract_sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    assert costs['contract_source_sha256']==contract_sources,'cost receipts name another contract candidate'
    for operation in ('create','setExiting','withdraw','unlist','liquidate','recover_sync','processAcquisitions'):
        assert gas.get(operation,0)>0,'missing owner gas calibration:'+operation
    frozen={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in SOURCES+[a.costs,a.reconciliation]}
    w=window(ROOT/'sim/data/fwa.sqlite',PIN['timestamp']);w['unmeasured_gas_operations']=['harvest' if name=='standalone-harvest' else name for name in costs.get('unmeasured_operations',[])]
    campaign,burst=jobs(w,gas);rows=[]
    with ProcessPoolExecutor(a.workers) as executor:
      for row in executor.map(one,campaign):
        rows.append(row);print(row['label'],row['renewal_mode'],row['mint_fee_wei'],row['total_price_gwei'],row['initial_funding_wei'],row['seed'],'exit',row['exit_complete'],'net',row['owner_net_wei'],flush=True)
    assert frozen=={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in frozen},'manager inputs changed during campaign'
    report=dict(command=['python',*__import__('sys').argv],source_sha256=frozen,pin=PIN,operating_days=30,maximum_exit_days=7,
        manager_hurdle=None,activity_study_pin=PIN,mint_fee_observation=json.loads((ROOT/'deploy/manager-mint-fee-observation.json').read_text()),manager_defaults=json.loads((ROOT/'deploy/manager.json').read_text()),rows=rows,burst=burst,
        limits=['Two counterfactual draws per recorded-month cell are not confidence bounds or realized returns.',
          'Recorded foreign pool weights and fees do not react to the candidate; purchaser responses are conservative bid/silence counterfactuals.',
          'No shares, checkpoints, dead-share seed, contribution refunds or pooled uncertainty gate applies.',
          'Owner wallet and keeper gas are calibrated proxies; unmeasured operations remain explicitly identified.',
          'Gross primary-mint fee accrual is not creator wallet profit after deployment or withdrawal costs.'])
    report['summary']=summarize(rows)
    write_economics(report,costs)
    (ROOT/'docs/receipts/manager-assessment.json').write_text(json.dumps(report,indent=1)+'\n')
    print('saved manager-assessment.json',len(rows),'rows',sum(row['exit_complete'] for row in rows),'complete exits')


if __name__=='__main__':main()
