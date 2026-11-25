"""Pure manager adapter accounting; real protocol agreement is manager_reconcile.py."""
import copy
import json
import unittest
from pathlib import Path
from manager import Manager
from vault import E, UNIT


class ManagerAccountingTest(unittest.TestCase):
    def account(self, **changes):
        return Manager(**dict(seed=0,balance=E,reserve=5*10**15,renewal_float=2141275*10**11) | changes)

    def test_entire_balance_owner_no_dead_shares_or_pool_apis(self):
        m=self.account()
        self.assertEqual((m.total_shares,m.free(),m.owner_funded),(0,E,E))
        for method,args in [('deposit',('h',E)),('checkpoint',()),('request_redeem',('h',1)),('claim',('h',))]:
            with self.assertRaisesRegex(RuntimeError,'NoHolderAccounting'):
                getattr(m,method)(*args)

    def test_owner_can_withdraw_cash_while_allocated_without_pool_pricing_gate(self):
        m=self.account();m.build([1],3,10**15,[21*10**16]);m.select(1)
        self.assertEqual(m.unresolved_keep_uplift,18*10**16)
        available=m.balance
        self.assertEqual(m.withdraw(available),available)
        self.assertEqual((m.balance,m.owner_withdrawn),(0,available))
        self.assertEqual(m.tracked_value,3*UNIT)

    def test_factory_or_stranger_cannot_control_owner_money(self):
        m=self.account()
        for caller in ('factory','stranger'):
            m.fund(1,caller)
            with self.assertRaisesRegex(RuntimeError,'Unauthorized'):m.withdraw(1,caller)
            with self.assertRaisesRegex(RuntimeError,'Unauthorized'):m.set_exiting(True,caller)

    def test_required_exit_queue_processing_is_not_free(self):
        from manager import owner_processing_reserve
        calls,cost=owner_processing_reserve(17,100_000,200_000_000)
        self.assertEqual((calls,cost),(2,340_000_000_000_000))
        self.assertEqual(owner_processing_reserve(0,100_000,200_000_000),(0,0))

    def test_budget_views_do_not_lose_fractional_refill_or_refill_on_capacity_increase(self):
        m=self.account(routine_budget=0,routine_cap=1000,routine_rate=7,essential_budget=0,essential_cap=1000,essential_rate=7)
        for now in (1,2,3,86399,86400):m.sync_budget(now)
        self.assertEqual(m.routine_budget,7)
        m.pay_keeper(2)
        m.set_budget(86401,2000,14,2000,14)
        self.assertEqual(m.routine_budget,5)
        m.sync_budget(2*86400+1)
        self.assertEqual(m.routine_budget,19)

    def test_growth_and_keeper_sources_are_separate_from_owner_withdrawal(self):
        m=self.account();self.assertEqual(m.idle(),E-m.reserve-m.renewal_float)
        m.routine_budget=E
        paid=m.pay_keeper(E)
        self.assertEqual(paid,E-m.renewal_float)
        self.assertEqual(m.balance,m.renewal_float)
        self.assertEqual(m.withdraw(m.balance),m.renewal_float)

    def test_exit_releases_float_not_inventory_and_owner_can_resume(self):
        m=self.account();float_before=m.renewal_float;m.kept_replacements=2
        m.set_exiting(True)
        self.assertEqual((m.renewal_float,m.kept_replacements,m.listing_paused),(0,0,True))
        self.assertEqual(m.renewal_float_needed(),float_before)
        self.assertEqual(m.idle(),max(0,m.balance-m.reserve-float_before))
        m.set_exiting(False)
        self.assertEqual(m.renewal_float,float_before)
        self.assertTrue(m.listing_paused)

    def test_exit_does_not_create_new_returned_or_keep_replacement_permissions(self):
        m=self.account();m.build([1,2],3,10**15,[21*10**16,21*10**16+10_000]);m.select(1);m.select(2)
        m.set_exiting(True);m.bid_settled(1);m.sync_owned(1);m.resolve_keep(2)
        self.assertEqual((m.renewal_eligible,m.kept_replacements,m.idle_acquired),([],0,[False]))

    def test_fresh_return_is_retired_once_with_three_more_paid_mints(self):
        m=self.account();m.build([1],3,10**15,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        before=m.balance;m.renew([2],3,10**15,[21*10**16],1)
        self.assertEqual(m.balance,before+3*UNIT-(3*UNIT+3*10**15+21*10**16))
        self.assertEqual(m.mint_fees,6*10**15)
        snap=copy.deepcopy(m.__dict__)
        with self.assertRaisesRegex(RuntimeError,'RenewalUnavailable'):m.renew([3],3,10**15,[21*10**16],1)
        self.assertEqual(m.__dict__,snap)

    def test_reuse_return_keeps_the_original_mints_and_face(self):
        m=self.account(renewal_mode=1,renewal_float=0);m.build([1],3,10**15,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        m.list(2,21*10**16)
        self.assertEqual((m.mint_fees,m.tracked_value,m.renewal_eligible),(3*10**15,3*UNIT,[]))

    def test_lower_live_fee_preserves_accepted_maximum(self):
        m=self.account();m.build([1],3,5*10**14,[21*10**16]);self.assertEqual(m.mint_fees,15*10**14)
        self.assertEqual(m.accepted_mint_fee,10**15)


    def test_shared_executor_finishes_a_manager_without_pool_methods(self):
        import forward as F
        values=json.loads((Path(__file__).resolve().parent.parent/'deploy/manager.json').read_text())
        # Recorded same-contract receipts are cost inputs, not fabricated RPC responses.
        gas=dict(create=606172,setExiting=53214,withdraw=38904,unlist=1351041,liquidate=787106,recover_sync=188900)
        sc=F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=1795521275,poll_seconds=60,
            receipt_seconds=36,replay_events=[],replay_period_seconds=3*F.DAY,foreign_pool_weight=1.0,
            exempt=True,gwei=.15,deposit_wei=5*10**17,mint_fee_wei=10**15,exit_all=True,exit_days=1,
            user_gas_proxy=gas,holder_rescue_sync=True,self_serve_exits=True)
        result=F.run(sc,1,1,days=1,values=values)
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['ledger_gap_wei'],0)
        self.assertEqual(result['keeper_calls_checkpoint'],0)
        self.assertEqual(result['essential_keeper_paid_wei'],0)
        self.assertGreater(result['owner_calls_unlist'],0)
        self.assertGreater(result['owner_wallet_gas_proxy_wei'],gas['create']*200_000_000)

    def quiet_with_costs(self, **overrides):
        import forward as F
        root=Path(__file__).resolve().parent.parent
        values=json.loads((root/'deploy/manager.json').read_text())
        costs=json.loads((root/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        receipts=json.loads((root/costs['receipts']).read_text())
        signed_limits={t['transaction']['hash']:int(t['transaction']['gas'],0) for t in receipts['transactions']}
        estimates={op:max(signed_limits[row['hash']] for row in samples) for op,samples in costs['measurements'].items()}
        for op,alias in {'recover_sync':'recover','unlist':'recoverUnlist','liquidate':'recoverLiquidate'}.items():
            estimates[op]=estimates[alias]
        sc=F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=1795521275,
            poll_seconds=60,receipt_seconds=36,replay_events=[],replay_period_seconds=3*F.DAY,
            foreign_pool_weight=1.,exempt=True,gwei=.15,deposit_wei=5*10**17,mint_fee_wei=10**15,
            exit_all=True,exit_days=1,user_gas_proxy=costs['gas_proxy'],holder_rescue_sync=True,
            self_serve_exits=True,user_gas_estimate_proxy=estimates)
        operating_days=overrides.pop('operating_days',1)
        sc.update(overrides)
        return F.run(sc,1,1,days=operating_days,values=values)

    def test_count_aware_receipt_floor_prices_one_and_eight_items_separately(self):
        import forward as F
        # Pure gas arithmetic, not a successful response from any external service.
        curves={'list':dict(single_billed_gas=300000,single_estimate_gas=400000,
            billed_per_extra_work=100000,estimate_per_extra_work=150000)}
        self.assertEqual(F.receipt_gas(curves,'list',1,250000,legacy_floor=1000000),300000)
        self.assertEqual(F.receipt_gas(curves,'list',8,250000,legacy_floor=1000000),1000000)
        self.assertEqual(F.receipt_gas(curves,'list',1,estimate=True),400000)
        self.assertEqual(F.receipt_gas(curves,'list',8,estimate=True),1450000)
        self.assertEqual(F.receipt_gas(curves,'list',8,2000000),2000000)
        self.assertEqual(F.receipt_gas({},'list',1,250000,legacy_floor=1000000),1000000)
        for count in (0,9,True,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):F.receipt_gas(curves,'list',count)
        with self.assertRaises(ValueError):F.receipt_gas(curves,'build',1)

    def test_unpaid_foreign_tail_costs_physical_reads_and_preflights_owner_cap(self):
        import forward as F
        from formal import window, PIN, flatten
        root=Path(__file__).resolve().parent.parent
        recorded=window(root/'sim/data/fwa.sqlite',PIN['timestamp'])
        days={}
        for request,completion,payload in recorded['pairs']:
            day=request//F.DAY
            if request-day*F.DAY>60 and not payload[0] and completion-request<F.DAY:
                days.setdefault(day,[]).append((request,completion,payload))
        day,pairs=next((day,pairs[:127]) for day,pairs in sorted(days.items()) if len(pairs)>=127)
        events=flatten([(request-day*F.DAY,completion-day*F.DAY,payload) for request,completion,payload in pairs])
        operating_days=max(completion-day*F.DAY for _,completion,_ in pairs)//F.DAY+1
        values=json.loads((root/'deploy/manager.json').read_text())
        values['gasSchedule']['scan']=10000000
        # Explicitly fund the estimate-based single-build quote; the unpaid tail remains rewardless.
        values['workFeeWei']=100000000000000
        values['routineCapWei']=575000000000000
        values['routineRatePerDayWei']=0
        costs=json.loads((root/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        actual=json.loads((root/costs['receipts']).read_text())
        signed={t['transaction']['hash']:int(t['transaction']['gas'],0) for t in actual['transactions']}
        estimates={op:max(signed[s['hash']] for s in samples) for op,samples in costs['measurements'].items()}
        for op,alias in {'recover_sync':'recover','unlist':'recoverUnlist','liquidate':'recoverLiquidate'}.items():
            estimates[op]=estimates[alias]
        estimates['build']=signed[costs['measurements']['build'][0]['hash']]
        # Only single-item calls occur here; these are actual receipt baselines, not batch extrapolations.
        curves={op:dict(single_billed_gas=costs['gas_proxy'][op],single_estimate_gas=estimates[op],
            billed_per_extra_work=0,estimate_per_extra_work=0) for op in
            ('create','build','setExiting','recover_sync','unlist','liquidate','withdraw')}
        def run(cap):
            trace=[]
            sc=F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=recorded['start']+day*F.DAY,
                poll_seconds=60,receipt_seconds=36,replay_events=events,replay_period_seconds=(operating_days+3)*F.DAY,
                foreign_pool_weight=1.,exempt=True,gwei=.15,deposit_wei=5*10**17,mint_fee_wei=10**15,
                exit_all=True,exit_days=1,user_gas_proxy=costs['gas_proxy'],gas_curves=curves,
                holder_rescue_sync=True,self_serve_exits=True,manager_keeper_zero_loss=True,
                owner_exit_spend_limit_wei=cap,trace_sink=trace)
            return F.run(sc,1,1,days=operating_days,values=values),trace
        result,trace=run(10**16)
        self.assertEqual(result['selections'],0)
        self.assertEqual(result['keeper_paid_build_wei'],575000000000000)
        self.assertEqual(result['operation_end_routine_budget_wei'],0)
        self.assertEqual(result['operation_end_backlog'],127)
        sync=next(t for t in trace if t['action']=='sync')
        self.assertEqual(sync['sync_payment_gas'],0)
        self.assertEqual(sync['sync_physical_work_gas'],2919000)
        self.assertEqual(result['keeper_paid_sync_wei'],0)
        self.assertEqual(result['owner_zero_quote_sync_calls'],1)
        self.assertEqual(result['owner_exit_spent_wei'],779232400000000)
        self.assertTrue(result['exit_complete'])
        stopped,_=run(5*10**14)
        self.assertEqual(stopped['owner_calls_sync'],0)
        self.assertEqual(stopped['journal_backlog'],127)
        self.assertEqual(stopped['end_open_positions'],1)
        self.assertFalse(stopped['exit_complete'])
        wait=stopped['first_wait_observation']['EXIT_SPEND_LIMIT']
        self.assertEqual(wait['operation'],'sync')
        self.assertEqual(wait['next_signed_bound_wei'],1277062500000000)
        self.assertEqual(stopped['owner_exit_reserved_wei'],32663750000000)

    def test_acceptance_covers_billed_curve_when_affine_estimates_cross(self):
        import forward as F
        from keeper import profitability_gate
        # Envelopes from n1(100/150), n2(300/301), n8(800/801) billed/estimated gas.
        curves={'list':dict(single_billed_gas=100,single_estimate_gas=150,
            billed_per_extra_work=200,estimate_per_extra_work=151)}
        self.assertEqual(F.receipt_gas(curves,'list',3),500)
        self.assertEqual(F.receipt_gas(curves,'list',3,estimate=True),452)
        acceptance=F.receipt_acceptance_gas(curves,'list',3)
        self.assertEqual(acceptance,500)
        self.assertFalse(profitability_gate(acceptance,1,475,0,0,0,ratio=1.)[2])
        self.assertTrue(profitability_gate(acceptance,1,510,0,0,0,ratio=1.)[2])
        self.assertEqual(F.receipt_acceptance_gas(curves,'list',3,600),600)

    def test_estimated_acceptance_can_decline_a_profitable_billed_build(self):
        root=Path(__file__).resolve().parent.parent
        costs=json.loads((root/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        actual=json.loads((root/costs['receipts']).read_text())
        signed={t['transaction']['hash']:int(t['transaction']['gas'],0) for t in actual['transactions']}
        estimates={op:max(signed[s['hash']] for s in samples) for op,samples in costs['measurements'].items()}
        for op,alias in {'recover_sync':'recover','unlist':'recoverUnlist','liquidate':'recoverLiquidate'}.items():
            estimates[op]=estimates[alias]
        # The single-pack signed gas limit is a conservative upper for its unavailable raw estimate.
        estimates['build']=signed[costs['measurements']['build'][0]['hash']]
        curves={op:dict(single_billed_gas=costs['gas_proxy'][op],single_estimate_gas=estimates[op],
            billed_per_extra_work=0,estimate_per_extra_work=0) for op in
            ('create','build','setExiting','recover_sync','unlist','liquidate','withdraw')}
        result=self.quiet_with_costs(gas_curves=curves,manager_keeper_zero_loss=True,
            owner_exit_spend_limit_wei=10**16)
        payment=415000000000000
        self.assertEqual(costs['gas_proxy']['build']*200000000,384983200000000)
        self.assertLess(costs['gas_proxy']['build']*200000000,payment)
        self.assertGreater(estimates['build']*200000000,payment)
        self.assertEqual(result['keeper_calls_build'],0)
        self.assertEqual(result['creator_primary_fees_accrued_wei'],0)
        self.assertEqual(result['keeper_gas_proxy_cost_wei'],0)
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertGreater(result['keeper_loss_waits'],0)
        # At an explicit0basefee/0.05gwei tip the same estimate fits; ledger charges the actual bill.
        accepted=self.quiet_with_costs(gwei=0,gas_curves=curves,manager_keeper_zero_loss=True,
            owner_exit_spend_limit_wei=10**16)
        self.assertEqual(accepted['keeper_calls_build'],1)
        self.assertEqual(accepted['keeper_compensation_wei'],133750000000000)
        self.assertEqual(accepted['keeper_gas_proxy_cost_wei'],96245800000000)
        self.assertEqual(accepted['keeper_net_proxy_wei'],37504200000000)
        self.assertTrue(accepted['exit_complete'])

    def test_runtime_receipt_history_accepts_actual_cold_build_calibration(self):
        from keeper import profitability_gate, billed_ratio
        root=Path(__file__).resolve().parent.parent
        costs=json.loads((root/'docs/receipts/manager-operating-cost-calibration.json').read_text())
        build=costs['gas_curves']['build']
        self.assertEqual(build['single_billed_gas'],1924916)
        self.assertEqual(build['single_estimate_gas'],2107326)
        price,payment=200000000,415000000000000
        self.assertEqual(build['single_billed_gas']*price,384983200000000)
        self.assertFalse(profitability_gate(build['single_estimate_gas'],price,payment,0,0,0,1.)[2])
        self.assertTrue(profitability_gate(build['single_estimate_gas'],price,payment,0,0,0,billed_ratio(None,'build'))[2])
        conservative=self.quiet_with_costs(gas_curves=costs['gas_curves'],manager_keeper_zero_loss=True,
            owner_exit_spend_limit_wei=10**16)
        self.assertEqual(conservative['keeper_calls_build'],0)
        self.assertEqual(conservative['creator_primary_fees_accrued_wei'],0)
        accepted=self.quiet_with_costs(gas_curves=costs['gas_curves'],manager_keeper_zero_loss=True,
            manager_keeper_receipt_history=True,owner_exit_spend_limit_wei=10**16)
        self.assertEqual(accepted['keeper_calls_build'],1)
        self.assertEqual(accepted['keeper_compensation_wei'],415000000000000)
        self.assertEqual(accepted['keeper_gas_proxy_cost_wei'],384983200000000)
        self.assertEqual(accepted['keeper_net_proxy_wei'],30016800000000)
        self.assertEqual(accepted['keeper_receipt_history_counts']['build'],1)
        self.assertEqual(accepted['keeper_receipt_history_ratios']['build'],.92)
        self.assertTrue(accepted['exit_complete'])

    def test_runtime_billed_ratio_threshold_last20_and_cap(self):
        from types import SimpleNamespace
        from keeper import billed_ratio, BILLED_PER_ESTIMATE
        # Pure proxy-receipt arithmetic using the production function, not an external service.
        history=SimpleNamespace(state={'counted':[]})
        self.assertEqual(billed_ratio(history,'build'),BILLED_PER_ESTIMATE['build'])
        self.assertEqual(billed_ratio(history,'build'),.92)
        history.state['counted']=[dict(label='build',est=100,gas_used=90),dict(label='build',est=100,gas_used=80)]
        self.assertEqual(billed_ratio(history,'build'),.92)
        history.state['counted'].append(dict(label='sync',est=100,gas_used=20))
        self.assertEqual(billed_ratio(history,'build'),.92)
        history.state['counted'].append(dict(label='build',est=100,gas_used=70))
        self.assertEqual(billed_ratio(history,'build'),.8)
        history.state['counted']=[dict(label='build',est=100,gas_used=i) for i in range(1,26)]
        self.assertEqual(billed_ratio(history,'build'),310/2000)
        history.state['counted']=[dict(label='build',est=100,gas_used=150) for _ in range(3)]
        self.assertEqual(billed_ratio(history,'build'),1.)

    def test_runtime_signed_exit_cap_completes_quiet_round_trip(self):
        result=self.quiet_with_costs(owner_exit_spend_limit_wei=10**16,manager_keeper_zero_loss=True)
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['owner_calls_setExiting'],1)
        self.assertEqual(result['owner_exit_spent_wei'],195432400000000)
        self.assertEqual(result['owner_exit_reserved_wei'],1217071100000000)
        self.assertLessEqual(result['owner_exit_spent_wei'],result['owner_exit_reserved_wei'])
        self.assertLessEqual(result['owner_exit_reserved_wei'],10**16)
        self.assertEqual(result['owner_exit_spend_limit_waits'],0)
        self.assertEqual(result['creator_primary_fees_accrued_wei'],3000000000000000)
        # Clone creation is outside the exit cap and still charged once to the owner.
        self.assertEqual(result['owner_wallet_gas_proxy_wei'],195432400000000+606194*200000000)

    def test_unsent_exit_intent_does_not_pause_strategy_after_gas_drops(self):
        result=self.quiet_with_costs(gwei=lambda day:.6 if day<1 else .15,
            owner_exit_spend_limit_wei=0,manager_keeper_zero_loss=True)
        self.assertEqual(result['operation_end_cash_wei'],5*10**17)
        self.assertEqual(result['owner_calls_setExiting'],0)
        self.assertGreater(result['keeper_calls_build'],0)
        self.assertLess(result['end_cash_wei'],result['operation_end_cash_wei'])
        self.assertEqual(result['owner_exit_spent_wei'],0)
        self.assertFalse(result['exit_complete'])

    def test_zero_exit_cap_preserves_unsent_exit_and_inventory(self):
        result=self.quiet_with_costs(owner_exit_spend_limit_wei=0)
        self.assertFalse(result['exit_complete'])
        self.assertEqual(result['owner_calls_setExiting'],0)
        self.assertEqual(result['owner_exit_spent_wei'],0)
        self.assertEqual(result['owner_exit_reserved_wei'],0)
        self.assertEqual(result['owner_withdrawn_wei'],0)
        self.assertEqual(result['end_open_positions'],1)
        self.assertEqual(result['end_cash_wei'],result['operation_end_cash_wei'])
        self.assertGreater(result['waiting_observations']['EXIT_SPEND_LIMIT'],0)
        self.assertEqual(result['owner_wallet_gas_proxy_wei'],606194*200000000)

    def test_keeper_loss_gate_refuses_work_before_mutating_account(self):
        root=Path(__file__).resolve().parent.parent
        costs=json.loads((root/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        gas=dict(costs['gas_proxy'])
        # This is the actual three-pack bill, a conservative floor rather than a one-pack curve.
        gas['build']=max(row['gasUsed'] for row in costs['measurements']['build'])
        result=self.quiet_with_costs(user_gas_proxy=gas,manager_keeper_zero_loss=True,
                                    owner_exit_spend_limit_wei=10**16)
        self.assertEqual(result['keeper_calls_build'],0)
        self.assertEqual(result['creator_primary_fees_accrued_wei'],0)
        self.assertEqual(result['keeper_compensation_wei'],0)
        self.assertEqual(result['keeper_gas_proxy_cost_wei'],0)
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertGreater(result['keeper_loss_waits'],0)
        self.assertTrue(result['exit_complete'])

    def test_empty_manager_does_not_pay_pending_foreign_requests(self):
        import forward as F
        from formal import window, PIN
        root=Path(__file__).resolve().parent.parent
        recorded=window(root/'sim/data/fwa.sqlite',PIN['timestamp'])
        request,completion,payload=next(p for p in recorded['pairs'] if p[0]>0 and p[1]>p[0]+1)
        costs=json.loads((root/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        gas=dict(costs['gas_proxy'])
        gas['build']=max(row['gasUsed'] for row in costs['measurements']['build'])
        # The actual recorded request straddles cutoff; no fulfilled service answer is fabricated.
        result=self.quiet_with_costs(user_gas_proxy=gas,manager_keeper_zero_loss=True,
            owner_exit_spend_limit_wei=10**16,start_timestamp=recorded['start']+request+1-F.DAY,
            replay_events=[(F.DAY-1,'request',None),(F.DAY-1+completion-request,'acquisition',payload)])
        self.assertEqual(result['keeper_calls_build'],0)
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertEqual(result['owner_processing_calls'],0)
        self.assertEqual(result['owner_processing_proxy_cost_wei'],0)
        self.assertEqual(result['owner_exit_spent_wei'],(53236+38926)*200000000)
        self.assertEqual(result['owner_exit_reserved_wei'],(93325+69075)*350000000)

    def test_recorded_callback_unblocks_exit_after_processing_reserve_is_denied(self):
        import forward as F
        from formal import window, PIN
        root=Path(__file__).resolve().parent.parent
        recorded=window(root/'sim/data/fwa.sqlite',PIN['timestamp'])
        request,completion,payload=next(p for p in recorded['pairs'] if p[0]>0 and 1<p[1]-p[0]<F.DAY)
        result=self.quiet_with_costs(manager_keeper_zero_loss=True,owner_exit_spend_limit_wei=10**15,
            exit_days=2,gwei=lambda day:.15 if day<1 else 2 if day<2 else 0,
            start_timestamp=recorded['start']+request+1-F.DAY,
            replay_events=[(F.DAY-1,'request',None),(F.DAY-1+completion-request,'acquisition',payload)])
        self.assertEqual(result['keeper_calls_build'],1)
        self.assertEqual(result['owner_calls_setExiting'],1)
        self.assertEqual(result['owner_processing_pending_at_exit'],1)
        self.assertGreater(result['waiting_observations']['EXIT_SPEND_LIMIT'],0)
        self.assertEqual(result['first_wait_observation']['EXIT_SPEND_LIMIT']['operation'],'processAcquisitions')
        # Only the recorded external callback drains the queue; no owner prefix is paid twice.
        self.assertEqual(result['owner_processing_calls'],0)
        self.assertEqual(result['owner_processing_proxy_cost_wei'],0)
        self.assertGreater(result['owner_calls_unlist']+result['owner_calls_liquidate'],0)
        self.assertTrue(result['exit_complete'])
        self.assertLessEqual(result['owner_exit_reserved_wei'],10**15)
        self.assertLessEqual(result['owner_exit_spent_wei'],result['owner_exit_reserved_wei'])
        self.assertEqual((result['physical_assets_wei'],result['external_fee_credit_wei'],result['end_cash_wei']),(0,0,0))
        self.assertEqual(result['ledger_gap_wei'],0)

    def test_foreign_journal_does_not_lock_an_empty_managers_owner_cash(self):
        import forward as F
        values=json.loads((Path(__file__).resolve().parent.parent/'deploy/manager.json').read_text())
        values['packUnitsMask']=0
        gas=dict(create=606172,setExiting=53214,withdraw=38904)
        sc=F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=1795521275,poll_seconds=60,
            receipt_seconds=36,replay_events=[(60,'request',False),(90,'acquisition',False)],
            replay_period_seconds=3*F.DAY,foreign_pool_weight=1.0,exempt=True,gwei=.15,
            deposit_wei=5*10**17,mint_fee_wei=10**15,exit_all=True,exit_days=1,
            user_gas_proxy=gas,holder_rescue_sync=True,self_serve_exits=True)
        result=F.run(sc,1,1,days=1,values=values)
        self.assertEqual(result['journal_backlog'],1)
        self.assertEqual((result['end_open_positions'],result['end_idle_packs'],result['pending_receipts']),(0,0,0))
        self.assertTrue(result['exit_complete'])
        self.assertEqual(result['owner_withdrawn_wei'],5*10**17)
        self.assertEqual(result['end_cash_wei'],0)
        self.assertEqual(result['ledger_gap_wei'],0)
        self.assertEqual(result['owner_net_wei'],-sum(gas.values())*200_000_000)


if __name__=='__main__':unittest.main()
