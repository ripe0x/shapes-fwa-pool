#!/usr/bin/env python3
"""Replay actual manager fork operations through the shared book and personal-account adapter."""
import argparse
import hashlib
import json
from pathlib import Path
from eth_abi import decode
from manager import Manager
from vault import ACTIVE, ALLOCATED, OWED, SETTLED, BPS
from forward import configured_state, policy
from config import PARAMS_T, PARAMS_ORDER, GAS_FIELDS

ROOT=Path(__file__).resolve().parent.parent


def parameters(encoded):
    raw=decode([PARAMS_T],bytes.fromhex(encoded.removeprefix('0x')))[0]
    return dict(zip(PARAMS_ORDER,raw[:-1]))|{'gasSchedule':dict(zip(GAS_FIELDS,raw[-1]))}


def replay(path):
    rows=[json.loads(line) for line in path.read_text().splitlines()];setup=rows[0];p=parameters(setup['params']);data=setup['input']
    m=Manager(seed=0,balance=data['deployBalance'],owner=setup['owner'],owner_funded=data['fundingWei'],reserve=p['reserveWei'],
        renewal_mode=p['renewalMode'],pack_units_mask=p['packUnitsMask'],accepted_mint_fee=p['acceptedMintFeeWei'],live_mint_fee=setup['liveMintFee'])
    m.routine_budget=m.routine_cap=p['routineCapWei'];m.essential_budget=m.essential_cap=p['essentialCapWei']
    m.routine_rate=p['routineRatePerDayWei'];m.essential_rate=p['essentialRatePerDayWei']
    m.acquisition_cursor=m.completed_prefix=data['initialCursor'];start=setup['timestamp'];pack_ids={};idle_ids=[];allocation_times={};request=None
    state0=configured_state(setup['baseFee'],p);m.renewal_float=policy.renewal_float(state0,p['renewalFloatCount'])
    failures=[]
    def check(step,field,model,actual):
        if model!=actual:failures.append(f'{step}.{field}: model {model}, chain {actual}')
    def compare(row):
        actual=row['state'];step=row['step']
        amounts={'balance':m.balance,'open':len(m.positions),'idle':len(m.idle_packs),'trackedValue':m.tracked_value,'idleValue':m.idle_value,
            'activeBacking':m.active_backing,'activeCount':m.active_count,'feeDebtSum':m.fee_debt_sum,'allocatedValue':m.allocated_value,
            'idleFunding':m.idle_funding,'completedPrefix':m.completed_prefix,'cursor':m.acquisition_cursor,'pendingReceipts':len(m.receipts),
            'reservedCount':sum(pos.state!=OWED for pos in m.positions.values()),'feeCredit':m.fee_credit,'renewalEligible':len(m.renewal_eligible),
            'keptReplacements':m.kept_replacements,'renewalFloat':m.renewal_float_needed(),'reserve':m.reserve,
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
        inventory=[dict(id=identifier,value=value,shapes=shapes,quote=quote,acquired=acquired) for identifier,value,shapes,quote,acquired in zip(idle_ids,m.idle_packs,m.idle_shapes,m.idle_quotes,m.idle_acquired)]
        check(step,'idlePacks',inventory,row['idlePacks'])
        physical=m.balance+sum(m.idle_packs)+sum(m.recovery_packs)+sum(pos.value for pos in m.positions.values() if pos.status in (ACTIVE,ALLOCATED) or pos.pack_owned)+sum(pos.backing for pos in m.positions.values() if pos.status in (ACTIVE,ALLOCATED))
        unresolved_keep=sum(pos.value for pos in m.positions.values() if pos.status==SETTLED and not pos.pack_owned)
        gap=m.owner_funded+m.external_gifts+m.fees_received-m.keeper_paid-m.mint_fees-m.backing_lost-m.settlement_fees-unresolved_keep-m.owner_withdrawn-physical
        check(step,'physicalLedgerGap',gap,0)

    for row in rows:
        now=row['timestamp']-start;m.sync_budget(now);action=row['action'];data=row['input'];state=configured_state(row['baseFee'],p);q=state.gas_schedule
        offer=lambda gas,units=0,essential=False:policy.quote(state,gas,units,essential)
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
        elif action in ('renew','list'):
            if len(data['ids'])!=1:raise ValueError('fixture must enumerate all new pack identities')
            shapes=policy.shape_count(data['units'])
            if action=='renew':
                check(row['step'],'returnedPack',idle_ids[-1],data['returnedPack']);retired=m.idle_shapes[-1];idle_ids.pop()
                if not 0<=data['feeDebt']-m.fee_accumulator<=1:raise ValueError('new FWA admission debt exceeds its observed floor/ceiling interval')
                m.fee_accumulator=data['feeDebt']
                m.renew(data['ids'],data['units'],row['liveMintFee'],data['backings'],1)
                gas=q['build']+q['build_pack']+shapes*q['build_shape']+q['listed']+q['liquidate']+q['liq_pack']+retired*q['redeem_shape']
                m.pay_keeper(offer(gas,3),source='renewal')
            else:
                check(row['step'],'reusedPack',idle_ids.pop(),data['packId']);m.list(data['ids'][0],data['backings'][0],fee_debt=data['feeDebt'])
                m.pay_keeper(offer(q['list']+q['listed'],1))
            pack_ids[data['ids'][0]]=data['packId']
        elif action=='setParams':
            new=parameters(row['params']);m.set_budget(now,new['routineCapWei'],new['routineRatePerDayWei'],new['essentialCapWei'],new['essentialRatePerDayWei']);p=new;m.reserve=p['reserveWei']
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
        final_balance_wei=m.balance,renewal_mode=m.renewal_mode,actual_mint_fee_wei=setup['liveMintFee'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='docs/receipts/manager-reconciliation.json')
    args = parser.parse_args()
    traces=[ROOT/'sim/out/manager-fresh-trace.jsonl',ROOT/'sim/out/manager-reuse-trace.jsonl'];results=[replay(path) for path in traces]
    status='PASS' if all(row['status']=='PASS' for row in results) else 'FAIL'
    sources=['sim/manager.py','sim/vault.py','sim/forward.py','keeper/policy.py','keeper/config.py','sim/manager_reconcile.py']
    report=dict(status=status,command=[__import__('sys').executable,*__import__('sys').argv],
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},results=results,
        limits=['Actual historical fee0.001 traces; current publicfee is separately observed0.0005.',
                'Fork state transitions and quoted payments, not billed wallet gas; owner wallet costs use the separate receipt calibration.',
                'One authenticated allocation and complete reinvestment/exit in each mode; repeated and conditional funding mechanisms have separate contract coverage.'])
    (ROOT/args.output).write_text(json.dumps(report,indent=1)+'\n')
    print(json.dumps(report,indent=1));return 0 if status=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
