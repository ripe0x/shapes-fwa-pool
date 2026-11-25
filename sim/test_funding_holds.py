"""Pure integer funding boundaries; actual protocol agreement needs the real fork trace."""
import copy
import unittest

from manager import Manager
from vault import Vault,Position,E


class FundingHoldTest(unittest.TestCase):
    def test_keeper_cash_clamps_after_proceeds_below_equal_and_above_float(self):
        for cash in (900,1000,1100):
            v=Vault(seed=0,balance=cash,renewal_float=1000)
            for proceeds in (0,50,100,200,-100):
                self.assertEqual(v.keeper_cash_after(proceeds),max(0,cash+proceeds-1000))
        v=Vault(seed=0,balance=10**17,renewal_float=214_127_500_000_000_000)
        self.assertEqual(v.keeper_cash_after(10**15),0)
        self.assertEqual(v.keeper_cash_after(115_127_500_000_000_000),10**15)

    def test_renewal_cash_preserves_reserve_and_owed_after_incoming_principal(self):
        for cash in (900,1000,1100):
            v=Vault(seed=0,balance=cash,reserve=1000)
            for proceeds in (0,50,100,200,-100):
                self.assertEqual(v.renewal_cash_after(proceeds),max(0,cash+proceeds-1000))
        v=Vault(seed=0,balance=60,reserve=40,total_shares=100,last_nav=300,locked_shares=10)
        self.assertEqual(v.owed_estimate(),30)
        self.assertEqual(v.renewal_cash_after(20),10)

    def test_primary_liabilities_stay_outside_both_sources(self):
        v=Vault(seed=0,balance=1000,pending_total=300,processing_pool=100,
            charge_refund_reserve=100,renewal_float=600,reserve=550)
        self.assertEqual(v.free(),500)
        self.assertEqual(v.keeper_cash_after(100),0)
        self.assertEqual(v.renewal_cash_after(100),50)

    def test_credit_sweep_can_be_economic_without_filling_float(self):
        quote=lambda gas,units:gas*200_000_000+units*20_000_000_000_000
        v=Vault(seed=0,balance=10**17,renewal_float=214_127_500_000_000_000)
        snapshot=copy.deepcopy(v.__dict__)
        insufficient=10**15
        self.assertEqual(v.sync_fee_plan([],insufficient,327_000,0,quote,2500),(367_000,insufficient,[]))
        self.assertEqual(v.keeper_cash_after(insufficient),0)
        sufficient=115_127_500_000_000_000
        self.assertEqual(v.sync_fee_plan([],sufficient,327_000,0,quote,2500),(367_000,sufficient,[]))
        self.assertEqual(v.keeper_cash_after(sufficient),10**15)
        self.assertEqual(v.__dict__,snapshot)
        v.receive_fees(sufficient)
        self.assertEqual(v.pay_keeper(quote(367_000,0)),73_400_000_000_000)
        self.assertGreaterEqual(v.balance,v.renewal_float)

    def test_terminal_cash_and_credit_jointly_fill_full_hold_before_compensation(self):
        v=Vault(seed=0,balance=100,renewal_float=1000)
        v.positions={1:Position(3,1,pending_fees=500),2:Position(3,2,pending_fees=400)}
        quote=lambda gas,units:gas
        self.assertEqual(v.sync_fee_plan([1,2],50,10,0,quote,10_000,10,10,10),
                         (50,50,[1,2]))
        self.assertEqual(v.keeper_cash_after(50+500+400),50)
        self.assertEqual(v.sync_fee_plan([],0,10,0,quote,10_000,cash_delta=600),(10,0,[]))
        self.assertEqual(v.keeper_cash_after(600),0)

    def test_multiple_claims_reach_first_true_cash_covering_prefix(self):
        v=Vault(seed=0,balance=100,renewal_float=1000)
        v.positions={1:Position(3,1,pending_fees=500),2:Position(3,2,pending_fees=600),
                     3:Position(3,3,pending_fees=5000)}
        self.assertEqual(v.sync_fee_plan([1,2,3],0,10,0,lambda gas,units:gas,10_000,10,10,10),
                         (40,0,[1,2]))
        self.assertEqual(v.keeper_cash_after(500),0)
        self.assertEqual(v.keeper_cash_after(1100),200)

    def test_first_cash_covering_prefix_share_or_permission_failure_stops_sync(self):
        v=Vault(seed=0,balance=100,renewal_float=1000)
        v.positions={1:Position(3,1,pending_fees=950),2:Position(3,2,pending_fees=100_000)}
        quote=lambda gas,units:gas
        self.assertEqual(v.sync_fee_plan([1,2],0,10,0,quote,10,10,10,10),(10,0,[]))
        v.routine_budget=20
        self.assertEqual(v.sync_fee_plan([1,2],0,10,0,quote,10_000,10,10,10),(10,0,[]))

    def test_renewal_prefix_clamps_retirement_credit_and_fees_after_reserve(self):
        v=Vault(seed=0,balance=100,reserve=1000)
        v.positions={1:Position(3,1,pending_fees=400),2:Position(3,2,pending_fees=200)}
        quote=lambda gas,units:gas
        # Principal600+credit600 does not refill the900 deficit and fund need1000.
        self.assertEqual(v.renewal_fee_plan([1,2],600,10,0,1000,quote,10_000,10,10,10,cash_delta=600),
                         (10,0,[]))
        # Principal600+credit1000+fees400 leaves1100; the first sufficient prefix is one claim.
        self.assertEqual(v.renewal_fee_plan([1,2],1000,10,0,1000,quote,10_000,10,10,10,cash_delta=600),
                         (40,1000,[1]))

    def test_legacy_return_cannot_bypass_reserve_before_fresh_replacement(self):
        m=Manager(seed=0,balance=E//2,reserve=10**16,renewal_float=0,pack_units_mask=1<<8)
        m.build([1],8,5*10**14,[21*10**16]);m.select(1);m.bid_settled(1);m.sync_owned(1)
        m.pack_units_mask=8
        m.withdraw(m.balance)
        snapshot=copy.deepcopy(m.__dict__)
        # Returning .08 funds a .071502 replacement only if the .01 reserve is omitted.
        backing=40_002_000_000_000_000
        with self.assertRaisesRegex(RuntimeError,'RenewalCashShort'):
            m.renew([2],3,5*10**14,[backing],1)
        self.assertEqual(m.__dict__,snapshot)
        m.fund(2*10**15)
        m.renew([2],3,5*10**14,[backing],1)
        self.assertEqual(m.mint_fees,35*10**14)  # Four legacy Shapes, then three launch Shapes.
        self.assertEqual(m.balance,10_498_000_000_000_000)
        self.assertEqual(m.pay_keeper(498_000_000_000_000,source='renewal'),498_000_000_000_000)
        self.assertEqual(m.balance,m.reserve)


if __name__=='__main__':unittest.main()
