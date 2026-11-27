"""Reuse-only manager accounting and current measured-profile execution, no service substitutes."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
import forward as F
from manager import Manager
from vault import E,UNIT
from manager_operating_assessment import qualify_costs,operation_samples,METERED_OPERATIONS,supported_work,owner_curves

ROOT=Path(__file__).resolve().parent.parent
PROFILE=ROOT/'docs/receipts/manager-measured-cost-calibration.json'


def current_profile():
    costs=json.loads(PROFILE.read_text())
    qualify_costs(costs,True)
    sources={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    if costs['contract_source_sha256']!=sources:raise ValueError('meter profile is not bound to current runtime sources')
    return costs


def current_scenario(**changes):
    costs=current_profile()
    sc=F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=1795521275,poll_seconds=60,
        receipt_seconds=36,replay_events=[],replay_period_seconds=4*F.DAY,foreign_pool_weight=1.,exempt=True,
        gwei=.15,deposit_wei=5*10**17,mint_fee_wei=5*10**14,exit_all=True,exit_days=1,
        user_gas_proxy=costs['gas_proxy'],user_gas_estimate_proxy=costs['gas_estimate_proxy'],gas_curves=costs['gas_curves'],
        gas_meter_proxy=costs['gas_meter_proxy'],gas_meter_max_work=supported_work(costs),
        owner_gas_curves=costs['owner_gas_curves'],owner_gas_max_work=supported_work(costs,owner=True),
        full_gas_schedule=costs['fullGasSchedule'],sync_contexts=costs['sync_contexts'],owner_sync_contexts=costs['owner_sync_contexts'],
        holder_rescue_sync=True,self_serve_exits=True,manager_keeper_zero_loss=True,manager_keeper_receipt_history=True,
        owner_exit_spend_limit_wei=10**16)
    sc.update(changes)
    return sc


class ManagerAccountingTest(unittest.TestCase):
    def account(self,**changes):
        return Manager(**dict(seed=0,balance=E,reserve=5*10**15)|changes)

    def run_quiet(self,**changes):
        values=changes.pop('values',json.loads((ROOT/'deploy/manager.json').read_text()))
        days=changes.pop('operating_days',1)
        return F.run(current_scenario(**changes),1,1,days=days,values=values)

    def test_entire_balance_owner_no_dead_shares_or_pool_apis(self):
        m=self.account()
        self.assertEqual((m.total_shares,m.free(),m.owner_funded),(0,E,E))
        for method,args in [('deposit',('h',E)),('checkpoint',()),('request_redeem',('h',1)),('claim',('h',))]:
            with self.assertRaisesRegex(RuntimeError,'NoHolderAccounting'):getattr(m,method)(*args)

    def test_owner_can_withdraw_cash_while_allocated(self):
        m=self.account();m.build([1],3,10**15,[21*10**16]);m.select(1)
        self.assertEqual(m.unresolved_keep_uplift,18*10**16)
        available=m.balance
        self.assertEqual(m.withdraw(available),available)
        self.assertEqual((m.balance,m.owner_withdrawn,m.tracked_value),(0,available,3*UNIT))

    def test_factory_or_stranger_cannot_control_owner_money(self):
        m=self.account()
        for caller in ('factory','stranger'):
            m.fund(1,caller)
            with self.assertRaisesRegex(RuntimeError,'Unauthorized'):m.withdraw(1,caller)
            with self.assertRaisesRegex(RuntimeError,'Unauthorized'):m.set_exiting(True,caller)

    def test_required_exit_queue_processing_is_not_free(self):
        from manager import owner_processing_reserve
        self.assertEqual(owner_processing_reserve(17,100000,200000000),(2,340000000000000))
        self.assertEqual(owner_processing_reserve(0,100000,200000000),(0,0))

    def test_budget_anchor_keeps_fractional_refill_and_old_capacity(self):
        m=self.account(routine_budget=0,routine_cap=1000,routine_rate=7)
        for now in (1,2,3,86399,86400):m.sync_budget(now)
        self.assertEqual(m.routine_budget,7)
        m.pay_keeper(2);m.set_budget(86401,2000,14)
        self.assertEqual(m.routine_budget,5)
        m.sync_budget(2*86400+1)
        self.assertEqual(m.routine_budget,19)

    def test_reserve_bounds_growth_but_is_not_a_removed_float(self):
        m=self.account()
        self.assertEqual(m.idle(),E-m.reserve)
        m.routine_budget=E
        self.assertEqual(m.pay_keeper(E),E)
        self.assertEqual(m.balance,0)
        self.assertFalse(hasattr(m,'renewal_float'))

    def test_exit_only_pauses_growth_owner_can_resume_intact_inventory(self):
        m=self.account();m.build([1],3,10**15,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        before=m.mint_fees
        m.set_exiting(True)
        self.assertTrue(m.listing_paused)
        self.assertEqual(m.idle_packs,[3*UNIT])
        m.set_exiting(False)
        self.assertTrue(m.listing_paused)
        m.listing_paused=False;m.list(2,21*10**16)
        self.assertEqual(m.mint_fees,before)
        self.assertEqual(m.positions[2].shapes,3)

    def test_return_reuses_exact_principal_without_fresh_mints(self):
        m=self.account();m.build([1],3,5*10**14,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        before=m.balance;m.list(2,21*10**16)
        self.assertEqual(m.balance,before-21*10**16)
        self.assertEqual((m.mint_fees,m.tracked_value),(15*10**14,3*UNIT))
        for removed in ('renew','renewal_float','renewal_mode','renewal_eligible','kept_replacements'):
            self.assertFalse(hasattr(m,removed))

    def test_lower_live_fee_does_not_change_accepted_maximum(self):
        m=self.account();m.build([1],3,5*10**14,[21*10**16])
        self.assertEqual((m.mint_fees,m.accepted_mint_fee),(15*10**14,10**15))

    def test_historical_fixed_receipt_money_remains_historical(self):
        path=ROOT/'docs/receipts/manager-r2-closeout.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),'51f824ae75c58bfdb46875cf72cdf63ea944d583d80dea2278930e4d141522a8')
        receipt=json.loads(path.read_text())
        self.assertEqual([c['ownerNetWei'] for c in receipt['cases']],[-1940071586360229,-5198947885644295])
        self.assertEqual(receipt['keeper']['netWei'],191832043922585)
        self.assertEqual(receipt['creatorPrimaryFeesAccruedWei'],6000000000000000)

    def test_payment_requires_independent_meter_and_caps_it_before_overhead(self):
        policy=F.policy
        values=json.loads((ROOT/'deploy/manager.json').read_text());state=F.configured_state(200000000,values)
        state.base_fee=150000000
        self.assertEqual((state.base_fee,state.gas_price),(150000000,200000000))
        with self.assertRaises(TypeError):policy.payment(state,100000,1)
        # Explicit arithmetic:100k workcap+100k namedoverhead, .2gwei, one20e12workfee.
        state.work_fee=20000000000000;state.gas_schedule['overhead']=100000
        self.assertEqual(policy.payment(state,100000,1,measured_gas=900000),60000000000000)
        self.assertEqual(policy.payment(state,100000,1,measured_gas=50000),50000000000000)
        self.assertEqual(policy.payment(state,100000,1,measured_gas=50000,tx_gas_price=100000000),35000000000000)

    def test_missing_or_unsupported_meter_never_uses_operation_allowance(self):
        with self.assertRaisesRegex(ValueError,'missing independently measured'):F.metered_work_gas({}, {},'build')
        curves={'build':dict(single_billed_gas=100,single_estimate_gas=150,single_meter_gas=75,
            billed_per_extra_work=20,estimate_per_extra_work=25,meter_per_extra_work=10)}
        self.assertEqual(F.metered_work_gas(curves,{},'build',2,{'build':3}),85)
        with self.assertRaisesRegex(ValueError,'receipt support'):F.metered_work_gas(curves,{},'build',4,{'build':3})
        self.assertEqual(F.receipt_gas(curves,'build',2),120)
        self.assertEqual(F.receipt_gas(curves,'build',2,estimate=True),175)

    def test_current_measured_quiet_exit_reconciles_independent_cash_partitions(self):
        result=self.run_quiet()
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['compensation_mode'],'bounded-measured-v1')
        self.assertEqual(result['unpaid_routine_calls'],0)
        self.assertEqual(result['creator_primary_fees_accrued_wei'],3000000000000000)
        self.assertEqual(result['owner_funded_wei']-result['owner_withdrawn_wei'],
            result['creator_primary_fees_accrued_wei']+result['keeper_compensation_wei'])
        self.assertEqual(result['owner_net_wei'],result['owner_withdrawn_wei']-5*10**17-result['owner_wallet_gas_proxy_wei'])
        self.assertEqual(result['keeper_net_proxy_wei'],result['keeper_compensation_wei']-result['keeper_gas_proxy_cost_wei'])
        self.assertGreater(result['keeper_net_proxy_wei'],0)
        self.assertLessEqual(result['owner_exit_spent_wei'],result['owner_exit_reserved_wei'])
        self.assertLessEqual(result['owner_exit_reserved_wei'],10**16)
        self.assertEqual(result['ledger_gap_wei'],0)

    def test_zero_exit_cap_keeps_owner_intent_unsent(self):
        result=self.run_quiet(owner_exit_spend_limit_wei=0)
        self.assertFalse(result['exit_complete'])
        self.assertEqual(result['owner_calls_setExiting'],0)
        self.assertEqual(result['owner_exit_spent_wei'],0)
        self.assertEqual(result['owner_exit_reserved_wei'],0)
        self.assertEqual(result['owner_withdrawn_wei'],0)
        self.assertEqual(result['end_open_positions'],2)
        self.assertGreater(result['waiting_observations']['EXIT_SPEND_LIMIT'],0)

    def test_unsent_exit_does_not_pause_after_gas_drops(self):
        result=self.run_quiet(gwei=lambda day:.6 if day<1 else .15,owner_exit_spend_limit_wei=0)
        self.assertEqual(result['operation_end_cash_wei'],5*10**17)
        self.assertEqual(result['owner_calls_setExiting'],0)
        self.assertGreater(result['keeper_calls_build'],0)
        self.assertLess(result['end_cash_wei'],result['operation_end_cash_wei'])

    def test_known_billed_loss_is_refused_before_minting(self):
        values=json.loads((ROOT/'deploy/manager.json').read_text())
        values=copy.deepcopy(values);values['workFeeWei']=0
        values['gasSchedule'].update(build=0,buildPack=0,buildShape=0,listed=1,overhead=0)
        result=self.run_quiet(values=values)
        self.assertEqual(result['keeper_calls_build'],0)
        self.assertEqual(result['creator_primary_fees_accrued_wei'],0)
        self.assertEqual(result['keeper_gas_proxy_cost_wei'],0)
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertGreater(result['keeper_loss_waits'],0)

    def test_empty_account_never_pays_pending_foreign_queue(self):
        from formal import window,PIN
        recorded=window(ROOT/'sim/data/fwa.sqlite',PIN['timestamp'])
        request,completion,payload=next(p for p in recorded['pairs'] if p[0]>0 and 1<p[1]-p[0]<F.DAY)
        values=json.loads((ROOT/'deploy/manager.json').read_text());values['packUnitsMask']=0
        trace=[]
        result=self.run_quiet(values=values,trace_sink=trace,start_timestamp=recorded['start']+request+1-F.DAY,
            replay_events=[(F.DAY-1,'request',None),(F.DAY-1+completion-request,'acquisition',payload)])
        self.assertEqual(next(row for row in trace if row['action']=='set-exiting')['market_pending'],1)
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertEqual(result['owner_processing_calls'],0)
        self.assertEqual(result['owner_processing_proxy_cost_wei'],0)

    def test_actual_callback_unblocks_denied_processing_reserve(self):
        from formal import window,PIN
        from keeper import wallet_debit_bound
        recorded=window(ROOT/'sim/data/fwa.sqlite',PIN['timestamp'])
        request,completion,payload=next(p for p in recorded['pairs'] if p[0]>0 and not p[2][0] and 1<p[1]-p[0]<F.DAY)
        costs=current_profile();curves=owner_curves(costs)
        set_bound=wallet_debit_bound(F.receipt_acceptance_gas(curves,'setExiting',1),2000000000,50000000)
        process_bound=wallet_debit_bound(F.receipt_acceptance_gas(curves,'processAcquisitions',1),2000000000,50000000)
        cap=set_bound+process_bound-1
        self.assertGreaterEqual(cap,set_bound)
        result=self.run_quiet(exit_days=2,deposit_wei=3*10**17,owner_exit_spend_limit_wei=cap,
            gwei=lambda day:.15 if day<1 else 2 if day<2 else 0,
            start_timestamp=recorded['start']+request+1-F.DAY,
            replay_events=[(F.DAY-1,'request',None),(F.DAY-1+completion-request,'acquisition',payload)])
        self.assertEqual(result['owner_processing_pending_at_exit'],1)
        self.assertEqual(result['first_wait_observation']['EXIT_SPEND_LIMIT']['operation'],'processAcquisitions')
        self.assertEqual(result['owner_processing_calls'],0)
        self.assertEqual(result['owner_processing_proxy_cost_wei'],0)
        self.assertTrue(result['exit_complete'])
        self.assertEqual((result['physical_assets_wei'],result['external_fee_credit_wei'],result['end_cash_wei']),(0,0,0))
        self.assertLessEqual(result['owner_exit_reserved_wei'],cap)

    def test_unmeasured_127_foreign_tail_cannot_produce_financial_result(self):
        from formal import window,PIN,flatten
        recorded=window(ROOT/'sim/data/fwa.sqlite',PIN['timestamp']);days={}
        for request,completion,payload in recorded['pairs']:
            day=request//F.DAY
            if request-day*F.DAY>60 and not payload[0] and completion-request<F.DAY:
                days.setdefault(day,[]).append((request,completion,payload))
        day,pairs=next((day,pairs[:127]) for day,pairs in sorted(days.items()) if len(pairs)>=127)
        events=flatten([(r-day*F.DAY,c-day*F.DAY,p) for r,c,p in pairs])
        operating=max(c-day*F.DAY for _,c,_ in pairs)//F.DAY+1
        costs=current_profile();values=json.loads((ROOT/'deploy/manager.json').read_text())
        values=copy.deepcopy(values);values['gasSchedule']['scan']=10000000
        state=F.configured_state(200000000,values);state.base_fee=150000000;q=state.gas_schedule
        self.assertEqual(state.gas_price,200000000)
        build_allowance=q['build']+q['build_pack']+3*q['build_shape']+q['listed']
        meter=F.metered_work_gas(costs['gas_curves'],costs['gas_meter_proxy'],'build')
        initial_pay=F.policy.payment(state,build_allowance,2,measured_gas=meter)
        values['routineCapWei']=initial_pay;values['routineRatePerDayWei']=0
        trace=[]
        with self.assertRaisesRegex(ValueError,'sync context calibration gas schedule differs'):
            self.run_quiet(values=values,operating_days=operating,deposit_wei=3*10**17,
                start_timestamp=recorded['start']+day*F.DAY,replay_events=events,
                replay_period_seconds=(operating+3)*F.DAY,owner_exit_spend_limit_wei=10**16,trace_sink=trace)
        opening=next(row for row in trace if row['action']=='build')
        self.assertEqual(opening['routine_budget'],0)
        # Zero payable work does not mean zero journal work or justify a terminal-only receipt.
        physical_allowance=q['sync']+127*q['journal']
        self.assertEqual(physical_allowance,2919000)
        self.assertEqual(F.policy.payment(state,0,0,measured_gas=0),0)
        with self.assertRaisesRegex(ValueError,'unmeasured sync context'):
            F.sync_context_gas(costs['owner_sync_contexts'],physical_allowance,0)

    def test_runtime_billed_ratio_matches_exact_threshold_last20_and_cap(self):
        from keeper import billed_ratio,BILLED_PER_ESTIMATE
        history=SimpleNamespace(state={'counted':[]})
        self.assertEqual(billed_ratio(history,'build'),BILLED_PER_ESTIMATE['build'])
        history.state['counted']=[dict(label='build',est=100,gas_used=90),dict(label='build',est=100,gas_used=80)]
        self.assertEqual(billed_ratio(history,'build'),.92)
        history.state['counted'].append(dict(label='build',est=100,gas_used=70))
        self.assertEqual(billed_ratio(history,'build'),.8)
        history.state['counted']=[dict(label='build',est=100,gas_used=i) for i in range(1,26)]
        self.assertEqual(billed_ratio(history,'build'),310/2000)
        history.state['counted']=[dict(label='build',est=100,gas_used=150) for _ in range(3)]
        self.assertEqual(billed_ratio(history,'build'),1.)


if __name__=='__main__':unittest.main()
