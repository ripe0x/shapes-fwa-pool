#!/usr/bin/env python3
"""Replay actual manager fork operations through the shared book and personal-account adapter."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from eth_abi import decode
from manager import Manager
from vault import ACTIVE, ALLOCATED, OWED, SETTLED, BPS
from forward import configured_state, policy
from config import PARAMS_T, PARAMS_ORDER, GAS_FIELDS

ROOT=Path(__file__).resolve().parent.parent

TRACE_MODE='bounded-measured-v1'


def parameters(encoded):
    payload=bytes.fromhex(encoded.removeprefix('0x'))
    if len(payload)!=32*(len(PARAMS_ORDER)+len(GAS_FIELDS)):
        raise ValueError('historical Params layout requires its pinned revision')
    raw=decode([PARAMS_T],payload)[0]
    return dict(zip(PARAMS_ORDER,raw[:-1]))|{'gasSchedule':dict(zip(GAS_FIELDS,raw[-1]))}



def measured_offer(row,state,gas,units=0,essential=False):
    frames=row['state'].get('measuredWork')
    if isinstance(frames,dict):frames=[frames]
    if not frames or len(frames)!=1:
        raise ValueError('paid atomic manager step requires one actual work-meter frame')
    frame=frames[0]
    expected=dict(gasAllowance=gas,workUnits=units,essential=essential,
        overhead=state.gas_schedule['overhead'],markupBps=state.markup_bps,
        baseFee=row['baseFee'],txGasPrice=row['gasPrice'])
    if any(frame.get(key)!=value for key,value in expected.items()):
        raise ValueError('actual work-meter context differs from independently derived operation')
    paid_price=min(row['gasPrice'],policy.price(state,essential))
    if frame['gasPrice']!=paid_price:
        raise ValueError('actual metered payment price differs from transaction/ceiling context')
    return policy.payment(state,gas,units,essential,measured_gas=frame['measuredGas'],tx_gas_price=row['gasPrice'])


def replay(path):
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    if not rows or any(row.get('compensationMode')!=TRACE_MODE for row in rows):
        raise ValueError('only new measured/reuse traces may be replayed; historical evidence stays pinned')
    setup=rows[0];p=parameters(setup['params']);data=setup['input']
    m=Manager(seed=0,balance=data['deployBalance'],owner=setup['owner'],owner_funded=data['fundingWei'],reserve=p['reserveWei'],
        pack_units_mask=p['packUnitsMask'],accepted_mint_fee=p['acceptedMintFeeWei'],live_mint_fee=setup['liveMintFee'])
    m.routine_budget=m.routine_cap=p['routineCapWei'];m.essential_budget=m.essential_cap=p['essentialCapWei']
    m.routine_rate=p['routineRatePerDayWei'];m.essential_rate=p['essentialRatePerDayWei']
    m.acquisition_cursor=m.completed_prefix=data['initialCursor'];start=setup['timestamp'];pack_ids={};idle_ids=[];allocation_times={};request=None
    failures=[]
    def check(step,field,model,actual):
        if model!=actual:failures.append(f'{step}.{field}: model {model}, chain {actual}')
    def compare(row):
        actual=row['state'];step=row['step']
        amounts={'balance':m.balance,'open':len(m.positions),'idle':len(m.idle_packs),'trackedValue':m.tracked_value,'idleValue':m.idle_value,
            'activeBacking':m.active_backing,'activeCount':m.active_count,'feeDebtSum':m.fee_debt_sum,'allocatedValue':m.allocated_value,
            'idleFunding':m.idle_funding,'completedPrefix':m.completed_prefix,'cursor':m.acquisition_cursor,'pendingReceipts':len(m.receipts),
            'reservedCount':sum(pos.state!=OWED for pos in m.positions.values()),'feeCredit':m.fee_credit,'reserve':m.reserve,
            'routineBudget':m.routine_budget,'essentialBudget':m.essential_budget}
        for field,value in amounts.items():check(step,field,value,actual[field])
        check(step,'keeperPay',m.keeper_paid,row['keeperPayCumulativeWei']);check(step,'creatorFees',m.mint_fees,row['creatorFeesCumulativeWei'])
        check(step,'ownerReceived',m.owner_withdrawn,row['ownerReceivedWei']);check(step,'exiting',m.exiting,row['windingDown']);check(step,'paused',m.listing_paused,row['listingPaused'])
        check(step,'pendingFees',sum(pos.pending_fees for pos in m.positions.values() if pos.status==ACTIVE),row['pendingFeesSum'])
        check(step,'positionIds',set(m.positions),{pos['id'] for pos in actual['positions']})
        for pos in actual['positions']:
            model=m.positions.get(pos['id'])
            if model is None:failures.append(f'{step}: missing listing {pos["id"]}');continue
            for field,value in [('packId',pack_ids[pos['id']]),('value',model.value),('backing',model.backing),('feeDebt',model.fee_debt),('allocatedAt',model.allocated_at),('state',model.state)]:check(step,'position.'+field,value,pos[field])
        inventory=[dict(id=identifier,value=value,shapes=shapes,quote=quote) for identifier,value,shapes,quote in zip(idle_ids,m.idle_packs,m.idle_shapes,m.idle_quotes)]
        check(step,'idlePacks',inventory,row['idlePacks'])
        physical=m.balance+sum(m.idle_packs)+sum(m.recovery_packs)+sum(pos.value for pos in m.positions.values() if pos.status in (ACTIVE,ALLOCATED) or pos.pack_owned)+sum(pos.backing for pos in m.positions.values() if pos.status in (ACTIVE,ALLOCATED))
        unresolved_keep=sum(pos.value for pos in m.positions.values() if pos.status==SETTLED and not pos.pack_owned)
        gap=m.owner_funded+m.external_gifts+m.fees_received-m.keeper_paid-m.mint_fees-m.backing_lost-m.settlement_fees-unresolved_keep-m.owner_withdrawn-physical
        check(step,'physicalLedgerGap',gap,0)

    for row in rows:
        now=row['timestamp']-start;m.sync_budget(now);action=row['action'];data=row['input'];state=configured_state(row['baseFee'],p);q=state.gas_schedule
        if (row['baseFee'],row['gasPrice'])!=(150_000_000,200_000_000):
            raise ValueError('unexpected executed trace fee environment')
        state.gas_price=row['gasPrice']
        offer=lambda gas,units=0,essential=False:measured_offer(row,state,gas,units,essential)
        if action=='create':pass
        elif action=='build':
            count=len(data['ids']);shapes=policy.shape_count(data['units']);m.build(data['ids'],data['units'],row['liveMintFee'],data['backings'],data['feeDebt'])
            if count!=1:raise ValueError('fixture must enumerate pack IDs for a multi-pack build')
            pack_ids[data['ids'][0]]=data['packId']
            m.pay_keeper(offer(q['build']+count*(q['build_pack']+shapes*q['build_shape']+q['listed']),2*count))
        elif action=='request':
            request=data;m.fee_accumulator=data['accBefore']
        elif action=='acquisition':
            # This is externally observed FWA accumulator input, not manager cash/state assignment.
            m.fee_accumulator=data['accAfter']
            for pos in m.positions.values():
                if pos.status==ACTIVE:pos.pending_fees=max(0,m.fee_accumulator-pos.fee_debt)
            selected=data['selectedListing'];position=m.positions[selected];m.fee_credit+=position.pending_fees;position.pending_fees=0;position.status=ALLOCATED
            allocation_times[selected]=data['allocatedAt'];m.completed_prefix+=1
            fee=request['acqFee']-request['acqFee']*request['acqCutBps']//BPS;fee-=fee*request['acqCrownBps']//BPS
            expected=fee//request['acqActive']
            if abs(m.fee_credit-expected)>1:failures.append('actual FWA fee credit differs from independent acquisition formula')
            check(row['step'],'externalEarningsAccrued',m.fee_credit,data['earningsAccrued'])
        elif action=='allocated':
            selected=data['selectedListing'];backlog=m.completed_prefix-m.acquisition_cursor;scanned=0
            if len(m.positions)<=policy.MAX_SCAN and len(m.positions)*q['scan']<=min(backlog,128)*q['journal']:
                scanned=m.scan_rebase([(allocation_times[selected],selected)],q['scan'],q['journal']);journal_reads=0
            else:
                m.select(selected,allocation_times[selected]);m.acquisition_cursor+=1;journal_reads=1
            pruned=m.prune(16);m.pay_keeper(offer(q['sync']+journal_reads*q['journal']+(scanned or 0)*q['scan']+q['selected']+pruned*q['pruned']))
        elif action=='bid':m.bid_settled(data['selectedListing'])
        elif action=='returned':
            for identifier in data['ids']:idle_ids.append(pack_ids[identifier]);m.sync_owned(identifier)
            m.prune(16)  # Explicit unpaid recover: no pay call and no budget-anchor commit.
        elif action=='drained':
            # CompletedPrefix is the FWA environment view after real foreign timeouts.
            m.completed_prefix=row['state']['completedPrefix']
        elif action=='list':
            if len(data['ids'])!=1:raise ValueError('fixture must enumerate all reused pack identities')
            check(row['step'],'reusedPack',idle_ids.pop(),data['packId'])
            m.list(data['ids'][0],data['backings'][0],fee_debt=data['feeDebt'])
            m.pay_keeper(offer(q['list']+q['listed'],1))
            pack_ids[data['ids'][0]]=data['packId']
        elif action=='setParams':
            new=parameters(row['params']);m.set_budget(now,new['routineCapWei'],new['routineRatePerDayWei'],new['essentialCapWei'],new['essentialRatePerDayWei']);p=new;m.reserve=p['reserveWei']
        elif action=='recover':
            found=[]
            backlog=m.completed_prefix-m.acquisition_cursor
            if backlog:
                scan=m.scan_rebase(found,q['scan'],q['journal'])
                if scan is None:
                    if backlog>128:raise ValueError('trace requires explicit bounded foreign journal prefix')
                    m.process_journal([None]*backlog)
            m.prune(16)
        elif action=='setExiting':m.set_exiting(data['exiting'],caller=m.owner)
        elif action=='wait':pass
        elif action=='unlist':
            for identifier in data['ids']:
                m.fee_credit+=m.positions[identifier].pending_fees;idle_ids.append(pack_ids[identifier]);m.unlist(identifier)
        elif action=='liquidate':
            for _ in range(data['count']):idle_ids.pop();m.liquidate_one()
        elif action=='harvest':
            check(row['step'],'harvestCreditInput',m.fee_credit,data['credit']);m.receive_fees(m.fee_credit);m.fee_credit=0
        elif action=='withdraw':m.withdraw(data['amount'],caller=m.owner)
        else:raise ValueError('unrecognized manager trace operation:'+action)
        compare(row)
    return dict(trace=str(path.relative_to(ROOT)),trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),steps=len(rows),
        status='FAIL' if failures else 'PASS',failures=failures,owner_withdrawn_wei=m.owner_withdrawn,keeper_paid_wei=m.keeper_paid,
        gross_primary_fees_accrued_wei=m.mint_fees,external_fee_income_wei=m.fees_received,backing_lost_wei=m.backing_lost,
        final_balance_wei=m.balance,compensation_mode=TRACE_MODE,actual_mint_fee_wei=setup['liveMintFee'])



def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--trace',default='sim/out/manager-measured-final-reuse-trace.jsonl')
    parser.add_argument('--output',default='docs/receipts/manager-measured-reconciliation.json')
    parser.add_argument('--funded',action='store_true',help='Retired historical Fresh campaign; use current reuse trace')
    args=parser.parse_args()
    if args.funded:raise SystemExit('Historical Fresh funding traces require their pinned revision; current reuse proof uses --trace')
    result=replay(ROOT/args.trace)
    sources=['sim/manager.py','sim/vault.py','sim/forward.py','keeper/policy.py','keeper/config.py','sim/manager_reconcile.py']
    contracts={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    report=dict(status=result['status'],compensation_mode=TRACE_MODE,command=[__import__('sys').executable,*__import__('sys').argv],
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},contract_source_sha256=contracts,
        trace_writer_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in
            ('test/fork/ForkManagerCloseout.t.sol','test/utils/ReconcileTrace.sol')},results=[result],
        limits=['New real authenticated reuse transitions only; old Fresh/fixed receipts remain historical.',
            'Compensation derives from genuine measured-work events and transaction prices, then independent cash/budget limits.',
            'Measured work spans are not billed wallet gas; external owner/keeper gas uses a separate current-runtime receipt profile.'])
    output=ROOT/args.output
    if output.exists():raise ValueError('preserve existing evidence; choose a new --output filename')
    output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
