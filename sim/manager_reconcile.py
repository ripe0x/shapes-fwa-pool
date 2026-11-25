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

FUNDED_TRACES=('manager-half-eth-float-wait-trace.jsonl','manager-sync-funding-deficit-trace.jsonl',
               'manager-renewal-reserve-deficit-trace.jsonl')


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


def replay_funded(path):
    """New deficit proof. All inputs to external accrual/admission come from actual FWA observations."""
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    first=rows[0];p=parameters(first['params']);funding=first['input']['fundingWei']
    m=Manager(seed=0,balance=first['state']['balance'],owner=first['owner'],owner_funded=funding,
        reserve=p['reserveWei'],renewal_mode=p['renewalMode'],pack_units_mask=p['packUnitsMask'],
        accepted_mint_fee=p['acceptedMintFeeWei'],live_mint_fee=first['mintFee'])
    m.routine_budget=m.routine_cap=p['routineCapWei'];m.essential_budget=m.essential_cap=p['essentialCapWei']
    m.routine_rate=p['routineRatePerDayWei'];m.essential_rate=p['essentialRatePerDayWei']
    # Actual starting public protocol cursor and any pre-existing address dust are explicit genesis inputs.
    m.acquisition_cursor=m.completed_prefix=first['state']['completedPrefix']
    if m.acquisition_cursor!=first['state']['cursor']:raise ValueError('setup journal is not current')
    m.renewal_float=policy.renewal_float(configured_state(first['baseFee'],p),p['renewalFloatCount'])
    start=first['timestamp'];packs={};external_order=[];failures=[];rejected=0;funding_checks=[];external_income=0
    expected_terminal={'manager-half-eth-float-wait-trace.jsonl':'declined','manager-sync-funding-deficit-trace.jsonl':'sync',
        'manager-renewal-reserve-deficit-trace.jsonl':'renewRejected'}
    if rows[-1]['action']!=expected_terminal[path.name]:failures.append('trace does not reach its required funding outcome')
    def check(step,name,expected,actual):
        if expected!=actual:failures.append(f'{step}.{name}: model {expected}, chain {actual}')
    def external_debt(row,identifier,known_accumulator=True):
        pos=next(pos for pos in row['state']['positions'] if pos['id']==identifier)
        debt=pos['liveFeeDebt']  # Actual FWA getter, independent of the account's cached feeDebt.
        if known_accumulator and not 0<=debt-m.fee_accumulator<=1:
            raise ValueError('external admission/claim debt differs from observed accumulator floor/ceiling')
        return debt
    def apply_sync(model,ids,state,row):
        q=state.gas_schedule;backlog=model.completed_prefix-model.acquisition_cursor
        found=[(at,identifier) for identifier,at in external_order if identifier in model.positions
               and model.positions[identifier].state==ACTIVE]
        unexposed=not(model.positions or model.receipts or model.active_count or model.active_backing or model.allocated_value)
        processed=own=scanned=resolved=0;rebased=False
        if unexposed:rebased=model.advance_unexposed()
        elif backlog:
            scan=model.scan_rebase(found,q['scan'],q['journal'])
            if scan is not None:rebased=True;scanned=scan;own=len(found)
            else:
                if backlog>128:raise ValueError('trace needs bounded explicit journal entries beyond128')
                # These fixtures consume the complete bounded prefix; foreign positions add no financial transition.
                for identifier,at in external_order:
                    if identifier in model.positions and model.positions[identifier].state==ACTIVE:
                        model.select(identifier,at);own+=1
                model.acquisition_cursor=model.completed_prefix;processed=backlog
        for identifier in ids:
            pos=model.positions.get(identifier)
            if pos and pos.state==ALLOCATED and pos.status==SETTLED:
                model.sync_owned(identifier);resolved+=1
        pruned=model.prune(16)
        if not(processed+resolved+pruned or rebased):raise RuntimeError('Nothing')
        journal_paid=processed==128 or own+resolved!=0
        gas=0
        if not(unexposed and not model.tracked_value) and (processed+scanned+resolved+pruned) and (journal_paid or own+resolved+pruned):
            gas=q['sync']+(processed*q['journal'] if journal_paid else 0)+(scanned*q['scan'] if own else 0)+own*q['selected']+resolved*q['synced']+pruned*q['pruned']
        return gas,resolved
    def compare(row):
        actual=row['state'];step=row['step']
        scalars=dict(balance=m.balance,open=len(m.positions),idle=len(m.idle_packs),trackedValue=m.tracked_value,
            idleValue=m.idle_value,activeBacking=m.active_backing,activeCount=m.active_count,feeDebtSum=m.fee_debt_sum,
            allocatedValue=m.allocated_value,idleFunding=m.idle_funding,completedPrefix=m.completed_prefix,cursor=m.acquisition_cursor,
            pendingReceipts=len(m.receipts),reservedCount=sum(pos.state!=OWED for pos in m.positions.values()),
            feeCredit=m.fee_credit,renewalEligible=len(m.renewal_eligible),keptReplacements=m.kept_replacements,
            renewalFloat=m.renewal_float_needed(),reserve=m.reserve,routineBudget=m.routine_budget,essentialBudget=m.essential_budget)
        for key,value in scalars.items():check(step,key,value,actual[key])
        check(step,'keeperCash',m.keeper_cash_after(),row['keeperCash'])
        check(step,'renewalCash',m.renewal_cash_after(),row['renewalCash'])
        check(step,'keeperDeficit',max(0,m.renewal_float-m.free()),row['keeperDeficit'])
        check(step,'renewalDeficit',max(0,m.reserve+m.owed_estimate()-m.free()),row['renewalDeficit'])
        check(step,'keeperPay',m.keeper_paid,row['keeperPayCumulativeWei'])
        check(step,'creatorFees',m.mint_fees,row['creatorFeesCumulativeWei'])
        check(step,'positionIds',set(m.positions),{pos['id'] for pos in actual['positions']})
        for pos in actual['positions']:
            model=m.positions.get(pos['id'])
            if model is None:continue
            for key,value in dict(packId=packs[pos['id']],value=model.value,backing=model.backing,feeDebt=model.fee_debt,
                                  allocatedAt=model.allocated_at,state=model.state).items():check(step,f'position{pos["id"]}.{key}',value,pos[key])
        check(step,'actualPendingFees',{pos['id']:m.positions[pos['id']].pending_fees for pos in row['feeCandidates']},
              {pos['id']:pos['fees'] for pos in row['feeCandidates']})
        physical=m.balance+sum(m.idle_packs)+sum(m.recovery_packs)+sum(pos.value for pos in m.positions.values() if pos.status in(ACTIVE,ALLOCATED) or pos.pack_owned)+sum(pos.backing for pos in m.positions.values() if pos.status in(ACTIVE,ALLOCATED))
        gap=m.owner_funded+m.external_gifts+m.fees_received-m.keeper_paid-m.mint_fees-m.backing_lost-m.settlement_fees-m.owner_withdrawn-physical
        check(step,'cashAssetLedgerGap',gap,0)
        check(step,'externalFeeLedger',m.fees_received+m.fee_credit+sum(pos.pending_fees for pos in m.positions.values()),external_income)
    for row in rows:
        step,action,data=row['step'],row['action'],row['input'];now=row['timestamp']-start
        if (row['baseFee'],row['gasPrice'])!=(150_000_000,200_000_000):raise ValueError('unexpected executed trace fee environment')
        m.sync_budget(now)
        if action!='setParams' and parameters(row['params'])!=p:raise ValueError('unrecorded parameter change')
        state=configured_state(row['baseFee'],p);state.mint_fee=row['mintFee'];q=state.gas_schedule
        offer=lambda gas,units:policy.quote(state,gas,units)
        if action=='create':pass
        elif action=='build':
            identifier=data['id'];debt=external_debt(row,identifier,False)
            m.build([identifier],data['units'],row['mintFee'],[data['backing']],debt);packs[identifier]=data['packId']
            m.pay_keeper(offer(q['build']+q['build_pack']+policy.shape_count(data['units'])*q['build_shape']+q['listed'],2))
        elif action=='request':
            m.fee_accumulator=data['accBefore']
            for pos in m.positions.values():
                if not 0<=pos.fee_debt-m.fee_accumulator<=1:raise ValueError('initial admission debt outside actual accumulator floor/ceiling')
        elif action=='acquisition':
            previous_external=m.fee_credit+sum(pos.pending_fees for pos in m.positions.values())
            m.fee_accumulator=data['accAfter'];records=data['earnedRecords']
            check(step,'actualFeeEventSum',sum(item['amount'] for item in records),data['earningsAccrued'])
            for pos in m.positions.values():
                if pos.status==ACTIVE:pos.pending_fees=max(0,m.fee_accumulator-pos.fee_debt)
            for item in records:
                pos=m.positions[item['id']];pos.pending_fees=0;pos.status=ALLOCATED
                m.fee_credit+=item['amount'];external_order.append((item['id'],item['allocatedAt']))
            external_income+=m.fee_credit+sum(pos.pending_fees for pos in m.positions.values())-previous_external
            # Public FWA completion prefix is an external environment input, not an account cash bucket.
            m.completed_prefix=row['state']['completedPrefix']
        elif action=='bid':m.bid_settled(data['id'])
        elif action=='processAcquisitions':m.completed_prefix=row['state']['completedPrefix']
        elif action in('recover','sync','syncRejected'):
            ids=data['ids'] if 'ids' in data else [data['terminal'],data['first']] if action=='syncRejected' else []
            working=copy.deepcopy(m) if action=='syncRejected' else m
            try:
                gas,units=apply_sync(working,ids,state,row)
                if action!='recover':
                    gas,credit,claimed=working.sync_fee_plan(ids,working.fee_credit,gas,units,offer,p['keeperShareBps'],q['sync_credit'],q['sync_funding'],q['harvested'])
                    received=credit+sum(working.positions[i].pending_fees for i in claimed)
                    predicted=min(offer(gas,units),working.routine_budget,working.keeper_cash_after(received))
                    if action=='syncRejected':
                        check(step,'positiveMinimumRejected',predicted<data['minimumPay'],True);rejected+=1
                    else:
                        if 'feeIdsConsumed' in data:check(step,'firstActualFundedPrefix',claimed,data['feeIdsConsumed'])
                        if 'received' in data:check(step,'actualCollectedFees',received,data['received'])
                        for identifier in claimed:working.harvest_listing(identifier,external_debt(row,identifier))
                        working.receive_fees(received);working.fee_credit-=credit
                        # A successful paid trace must not silently commit partial or zero-payment work.
                        check(step,'fullRoutineCompensation',predicted,offer(gas,units))
                        working.pay_keeper(offer(gas,units))
                        funding_checks.append(dict(step=step,claimed=claimed,receivedWei=received,paymentWei=offer(gas,units)))
            except RuntimeError as exc:
                if action!='syncRejected':raise
                check(step,'rejectionReason',str(exc),'Payment');rejected+=1
        elif action=='harvest':
            check(step,'creditWithdrawalInput',m.fee_credit,data['credit']);m.receive_fees(m.fee_credit);m.fee_credit=0
        elif action=='setParams':
            new=parameters(row['params']);m.set_budget(now,new['routineCapWei'],new['routineRatePerDayWei'],new['essentialCapWei'],new['essentialRatePerDayWei'])
            p=new;m.reserve=p['reserveWei'];m.renewal_float=policy.renewal_float(configured_state(row['baseFee'],p),p['renewalFloatCount'])
        elif action=='withdraw':m.withdraw(data['amount'],caller=m.owner)
        elif action=='renew':
            new_ids=set(pos['id'] for pos in row['state']['positions'])-set(m.positions)
            if len(new_ids)!=1:raise ValueError('renew trace must identify one actual new admission')
            identifier=new_ids.pop();old=next(i for i in m.positions if packs[i]==data['returnedPack']) if any(packs[i]==data['returnedPack'] for i in m.positions) else None
            if old is not None:raise ValueError('returned inventory still has an open listing')
            debt=external_debt(row,identifier);m.fee_accumulator=debt
            retired=m.renewal_shapes()[0];gas=q['build']+q['build_pack']+3*q['build_shape']+q['listed']+q['liquidate']+q['liq_pack']+retired*q['redeem_shape']
            m.renew([identifier],3,row['mintFee'],[data['backing']],1);m.pay_keeper(offer(gas,3),source='renewal')
            packs[identifier]=next(pos['packId'] for pos in row['state']['positions'] if pos['id']==identifier)
        elif action=='renewRejected':
            gas=q['build']+q['build_pack']+3*q['build_shape']+q['listed']+q['liquidate']+q['liq_pack']+m.renewal_shapes()[0]*q['redeem_shape']
            need=3*10**16+3*row['mintFee']+210_000_000_000_000_000
            returned=m.renewal_eligible[0]
            gas,credit,claimed=m.renewal_fee_plan(data['feeIds'],m.fee_credit,gas,3,need,offer,p['keeperShareBps'],q['sync_funding'],q['harvested'],q['sync_credit'],cash_delta=returned)
            received=credit+sum(m.positions[i].pending_fees for i in claimed)
            check(step,'reserveFundingRejected',m.renewal_cash_after(returned+received)<need+offer(gas,3),True)
            check(step,'actualAvailableFeeInput',m.fee_credit+sum(m.positions[i].pending_fees for i in data['feeIds']),data['availableFees']);rejected+=1
        elif action=='declined':
            try:apply_sync(copy.deepcopy(m),[],state,row)
            except RuntimeError as exc:check(step,'noNewVerifiedWork',str(exc),'Nothing');rejected+=1
            else:failures.append(step+': no-work call unexpectedly produced progress')
        else:raise ValueError('unrecognized funded trace action:'+action)
        compare(row)
    return dict(trace=str(path.relative_to(ROOT)),trace_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),steps=len(rows),status='FAIL' if failures else 'PASS',
        failures=failures,funding_checks=funding_checks,verified_rejections=rejected,owner_withdrawn_wei=m.owner_withdrawn,
        keeper_paid_wei=m.keeper_paid,gross_primary_fees_accrued_wei=m.mint_fees,external_fee_income_wei=m.fees_received,
        final_balance_wei=m.balance,keeper_cash_wei=m.keeper_cash_after(),renewal_cash_wei=m.renewal_cash_after(),
        actual_mint_fee_wei=first['mintFee'],scope='New current-source funding boundary proof; no billed wallet gas or return forecast')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output')
    parser.add_argument('--funded',action='store_true',help='Replay newA/B/C funding traces and preserve the historical compatibility results separately')
    args = parser.parse_args()
    traces=[ROOT/'sim/out/manager-fresh-trace.jsonl',ROOT/'sim/out/manager-reuse-trace.jsonl'];historical=[replay(path) for path in traces]
    results=[replay_funded(ROOT/'sim/out'/name) for name in FUNDED_TRACES] if args.funded else historical
    status='PASS' if all(row['status']=='PASS' for row in results) else 'FAIL'
    sources=['sim/manager.py','sim/vault.py','sim/forward.py','keeper/policy.py','keeper/config.py','sim/manager_reconcile.py']
    report=dict(status=status,command=[__import__('sys').executable,*__import__('sys').argv],
        source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources},results=results,
        limits=['Actual historical fee0.001 traces; current publicfee is separately observed0.0005.',
                'Fork state transitions and quoted payments, not billed wallet gas; owner wallet costs use the separate receipt calibration.',
                'One authenticated allocation and complete reinvestment/exit in each mode; repeated and conditional funding mechanisms have separate contract coverage.'])
    if args.funded:
        report['historical_compatibility_results']=historical
        report['historical_compatibility_scope']='Original32historicalsteps retained separately; not new funding-deficit money proof or current billed receipts.'
        report['contract_source_sha256']={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
        writer='test/fork/ForkManagerFundingDeficit.t.sol'
        report['trace_writer_sha256']={writer:hashlib.sha256((ROOT/writer).read_bytes()).hexdigest()}
        report['compiled_runtime_object_sha256']={name:hashlib.sha256(json.loads((ROOT/f'out/{name}.sol/{name}.json').read_text())['deployedBytecode']['object'].encode()).hexdigest()
            for name in ('PackManager','VaultLib','StrategyLib','ScanLib')}
        report['limits']=['NewA/B/C traces use actual historical0.001mintfee and executed0.15base/0.2gwei; no current-fee return inference.',
            'A proves actual0.5ETH opening→paidfreshrenewal→floatcashdeficit and rejection without new work; no second authenticated paid progress is supplied.',
            'B proves a positive-minimum one-claim rejection and first truly funded two-fee prefix, using explicitly cheap owner gas calibration; no keeper profitability claim.',
            'C proves genuine modest credit/fees cannot fund the enlarged reserve plus retirement/rebuild, preserving every bucket atomically; a fundable below-reserve case is not reached.',
            'External FWA earnings records, accumulator floors, live admission/claim debt and completion prefix are observed inputs; account financial buckets are replayed independently.',
            'Actual wallet billed gas remains a separate current-source receipt calibration. Idle inventory aggregate value/count are compared; per-pack custody assertions belong to the real trace writer.']
        if not all(row['status']=='PASS' for row in historical):report['status']=status='FAIL'
    output=args.output or ('docs/receipts/manager-funded-reconciliation.json' if args.funded else 'docs/receipts/manager-reconciliation.json')
    (ROOT/output).write_text(json.dumps(report,indent=1)+'\n')
    print(json.dumps(report,indent=1));return 0 if status=='PASS' else 1


if __name__=='__main__':raise SystemExit(main())
