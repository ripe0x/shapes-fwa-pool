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
        sc.update(overrides)
        return F.run(sc,1,1,days=1,values=values)

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
