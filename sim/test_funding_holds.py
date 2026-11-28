"""Reuse-only cash boundaries; real protocol agreement uses the new measured fork trace."""
import copy
import unittest
from manager import Manager
from vault import Vault,Position,E


class FundingHoldTest(unittest.TestCase):
    def test_keeper_cash_has_no_removed_float_and_growth_still_holds_reserve(self):
        v=Vault(seed=0,balance=1000,reserve=700)
        self.assertEqual(v.keeper_cash_after(),1000)
        self.assertEqual(v.keeper_cash_after(-1100),0)
        self.assertEqual(v.idle(),300)
        self.assertEqual(v.pay_keeper(800),800)
        self.assertEqual(v.balance,200)
        self.assertEqual(v.idle(),0)

    def test_reserve_and_real_holder_liabilities_still_protect_new_exposure(self):
        v=Vault(seed=0,balance=60,reserve=40,total_shares=100,last_nav=300,locked_shares=10)
        self.assertEqual(v.owed_estimate(),30)
        self.assertEqual(v.idle(),0)
        v.receive_fees(20)
        self.assertEqual(v.idle(),10)

    def test_primary_liabilities_stay_outside_keeper_source(self):
        v=Vault(seed=0,balance=1000,pending_total=300,processing_pool=100,charge_refund_reserve=100,reserve=550)
        self.assertEqual(v.free(),500)
        self.assertEqual(v.keeper_cash_after(100),600)
        self.assertEqual(v.idle(),0)
        v.receive_fees(100)
        self.assertEqual(v.idle(),50)

    def test_credit_sweep_is_atomic_and_does_not_invent_a_float(self):
        v=Vault(seed=0,balance=0)
        before=copy.deepcopy(v.__dict__)
        self.assertEqual(v.sync_fee_plan([],50,10,0,lambda g,u:g,10000,10,10,10),(20,50,[]))
        self.assertEqual(v.__dict__,before)
        v.receive_fees(50)
        self.assertEqual(v.pay_keeper(20),20)
        self.assertEqual(v.balance,30)

    def test_terminal_principal_can_fund_work_without_extra_fee_claims(self):
        v=Vault(seed=0,balance=0)
        self.assertEqual(v.sync_fee_plan([],0,10,0,lambda g,u:g,10000,cash_delta=20),(10,0,[]))
        self.assertEqual(v.keeper_cash_after(20),20)

    def test_multiple_claims_stop_at_first_cash_covering_prefix(self):
        v=Vault(seed=0,balance=0)
        v.positions={1:Position(3,1,pending_fees=20),2:Position(3,2,pending_fees=80),3:Position(3,3,pending_fees=5000)}
        self.assertEqual(v.sync_fee_plan([1,2,3],0,10,0,lambda g,u:g,10000,10,10,10),(40,0,[1,2]))
        self.assertEqual(v.keeper_cash_after(100),100)

    def test_first_covering_prefix_share_or_permission_failure_stops_sync(self):
        v=Vault(seed=0,balance=0)
        v.positions={1:Position(3,1,pending_fees=40),2:Position(3,2,pending_fees=100000)}
        self.assertEqual(v.sync_fee_plan([1,2],0,10,0,lambda g,u:g,10,10,10,10),(10,0,[]))
        v.routine_budget=20
        self.assertEqual(v.sync_fee_plan([1,2],0,10,0,lambda g,u:g,10000,10,10,10),(10,0,[]))

    def test_return_waits_for_backing_cash_then_reuses_without_minting(self):
        m=Manager(seed=0,balance=E//2,reserve=10**16,pack_units_mask=8)
        m.build([1],3,5*10**14,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        m.withdraw(m.balance)
        before=copy.deepcopy(m.__dict__)
        with self.assertRaisesRegex(RuntimeError,'InsufficientBacking'):m.list(2,21*10**16)
        self.assertEqual(m.__dict__,before)
        m.fund(22*10**16)
        m.list(2,21*10**16)
        self.assertEqual(m.mint_fees,15*10**14)
        self.assertEqual(m.tracked_value,3*10**16)
        self.assertEqual(m.balance,10**16)
        self.assertFalse(hasattr(m,'renew'))


if __name__=='__main__':unittest.main()
