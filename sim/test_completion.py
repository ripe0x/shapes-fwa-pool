"""Canonical arithmetic regressions. Contract agreement requires the separate fork reconciler."""
import unittest
import copy
from vault import Vault, E


class CompletionAccountingTest(unittest.TestCase):
    def test_build_respects_disabled_recipe_and_fee_acceptance_atomically(self):
        for mask, units, fee, error in ((0, 3, 10**15, 'BadBatch'),
                (8, 6, 10**15, 'BadBatch'), (8, 3, 10**15 + 1, 'MintFeeNotAccepted')):
            v = Vault(seed=E, balance=E, reserve=0, pack_units_mask=mask)
            before = copy.deepcopy(v.__dict__)
            with self.assertRaisesRegex(RuntimeError, error):
                v.build([1], units, fee, [21 * 10**16])
            self.assertEqual(v.__dict__, before)
        v = Vault(seed=E, balance=E, reserve=0, accepted_mint_fee=10**15)
        v.build([1], 3, 5 * 10**14, [21 * 10**16])
        self.assertEqual(v.mint_fees, 15 * 10**14)
        self.assertEqual(v.balance, E - 3 * 10**16 - 15 * 10**14 - 21 * 10**16)

    def test_zero_quote_and_restored_topup_never_close_live_era(self):
        v = Vault(seed=E, balance=E, reserve=0)
        v.deposit('alice', E, 11)
        v.deposit('bob', E)
        v.cancel('bob')  # The quote can be zero; live Alice keeps the same era.
        self.assertEqual(v.charge_era, 0)
        v.deposit('carol', E, 7)
        v.cancel('carol')
        self.assertEqual(v.processing_pool, 18)
        v.cancel('alice')
        self.assertEqual((v.processing_pool, v.charge_refund_reserve, v.free()), (0, 18, E))
        self.assertEqual(v.claim_checkpoint_refund('carol', [1]), 7)
        self.assertEqual(v.claim_checkpoint_refund('alice', [0]), 11)
        self.assertEqual(v.balance, E)

    def test_paid_checkpoint_refunds_partition_every_wei_any_order(self):
        v = Vault(seed=E, balance=E, reserve=0)
        v.deposit('alice', E, 7)
        self.assertEqual(v.fund_checkpoint('bob', 16, 18), 5)
        v.checkpoint(keeper_payment=5)
        self.assertEqual(v.charge_refund_reserve, 13)
        self.assertEqual(v.checkpoint_refund(0), 5)
        self.assertEqual(v.checkpoint_refund(1), 8)
        self.assertEqual(v.claim_checkpoint_refund('bob', [1]), 8)
        self.assertEqual(v.claim_checkpoint_refund('alice', [0]), 5)
        self.assertEqual(v.balance, 2 * E)
        self.assertEqual(v.keeper_paid, 5)

    def test_construction_at_commit_and_aggregate_issuance_rounding(self):
        v = Vault(seed=E, balance=E, reserve=0)
        v.deposit('alice', E + 1)
        v.deposit('bob', E + 2)
        # Request-time estimates never lock fees; the committing configuration does.
        v.construction_cost, v.reference_capital = 3 * 10**15, 24 * 10**16
        gross = 2 * E + 3
        charge = gross * (3 * 10**15) // (243 * 10**15)
        expected = (gross - charge) * v.total_shares // E
        v.checkpoint()
        v._settle_holder('alice')
        v._settle_holder('bob')
        self.assertEqual(v.shares['alice'] + v.shares['bob'], expected)
        self.assertEqual(v.issuances[0][2:], [0, 0])
        self.assertEqual(v.last_nav, 3 * E + 3)

    def test_caller_checkpoint_keeps_pending_escrow_cancellable_and_refunds_contributions(self):
        v=Vault(seed=E,balance=E,reserve=0)
        v.deposit('alice',E)
        v.checkpoint()
        v.request_redeem('alice',v.share_balance('alice'),11)
        v.deposit('bob',E,7)
        epoch=v.epoch
        v.recover_checkpoint()
        self.assertEqual((v.epoch,v.pending_total,v.processing_pool,v.charge_refund_reserve),(epoch,E,18,0))
        self.assertEqual(v.keeper_paid,0)
        self.assertEqual(v.cancel('bob'),E)
        self.assertEqual(v.claim('alice'),E)
        self.assertEqual(v.claim_checkpoint_refund('alice',[0]),11)
        self.assertEqual(v.claim_checkpoint_refund('bob',[1]),7)
        self.assertEqual(v.balance,E)

    def test_caller_recovery_retains_new_depositor_checkpoint_sponsorship(self):
        v=Vault(seed=E,balance=E,reserve=0)
        v.deposit('alice',E)
        v.checkpoint()
        v.request_redeem('alice',1,11)
        v.deposit('bob',E,7)
        v.recover_checkpoint()
        self.assertEqual((v.processing_pool,v.charge_era),(18,0))
        v.checkpoint(keeper_payment=5)
        self.assertEqual((v.processing_pool,v.keeper_paid,v.charge_refund_reserve),(0,5,13))
        self.assertEqual(v.share_balance('bob'),10**15)
        self.assertEqual(v.checkpoint_refund(0)+v.checkpoint_refund(1),13)

    def test_caller_recovery_preserves_remaining_holder_distribution_gain(self):
        v=Vault(seed=E,balance=E,reserve=0,distribution_bps=1000)
        v.deposit('alice',E)
        v.deposit('bob',E)
        v.checkpoint()
        high=v.high_water_mark
        v.receive_fees(3*10**17)
        v.request_redeem('alice',v.share_balance('alice'),0)
        v.recover_checkpoint()
        self.assertEqual(v.high_water_mark,high)
        v.checkpoint()
        self.assertEqual(v.claim('bob'),2*10**16)

    def test_capacity_increase_does_not_refill_and_old_rate_accrues(self):
        v = Vault(seed=E, balance=E, routine_cap=100, routine_budget=10, routine_rate=20,
                  essential_cap=30, essential_budget=5, essential_rate=2)
        v.set_budget(86400, 1000, 100, 3, 200)
        self.assertEqual(v.routine_budget, 30)
        self.assertEqual(v.essential_budget, 3)
        v.sync_budget(2 * 86400)
        self.assertEqual(v.routine_budget, 130)
        self.assertEqual(v.essential_budget, 3)

    def test_unresolved_allocation_proof_bound_precedes_large_nav_uplift_check(self):
        from vault import Position, ALLOCATED
        v = Vault(seed=3000*E, balance=3000*E)
        v.positions = {i: Position(3, 21*10**16, state=ALLOCATED) for i in range(33)}
        v.allocated_value = 33*3*10**16
        v.allocation_queue = list(range(33))
        v.deposit('alice', E)
        with self.assertRaisesRegex(RuntimeError, 'CatchUpFirst'):
            v.checkpoint()

    def test_renewal_funding_collects_only_needed_prefix(self):
        from vault import Position
        v = Vault(seed=0, balance=0, reserve=0, routine_budget=1_000_000)
        v.positions = {1: Position(3,21*10**16,pending_fees=500_000),2: Position(3,21*10**16+10_000,pending_fees=500_000)}
        quote = lambda gas, units: gas
        self.assertEqual(v.renewal_fee_plan([1,2],200_000,85_000,2,100_000,quote,2500,40_000,80_000,40_000), (245_000,200_000,[1]))
        v.balance = 1_000_000
        self.assertEqual(v.renewal_fee_plan([1,2],200_000,85_000,2,100_000,quote,2500,40_000,80_000,40_000), (85_000,0,[]))

    def test_checkpoint_compensation_counts_only_actual_allocation_reads(self):
        from vault import Position,ALLOCATED
        v=Vault(seed=E,balance=E)
        v.positions={1:Position(3,21*10**16,state=ALLOCATED)}
        v.allocated_value=3*10**16
        v.allocation_queue=[99,1]
        self.assertEqual(v.checkpoint_proof_counts(),(2,1))
        v.allocated_value=0
        self.assertEqual(v.checkpoint_proof_counts(),(0,0))

    def test_scan_bound_is_independent_of_mutable_prices(self):
        from vault import Position
        v = Vault(seed=E, balance=E)
        v.positions = {i: Position(3, 21 * 10**16) for i in range(301)}
        v.completed_prefix = 10**9
        self.assertIsNone(v.scan_rebase([]))


if __name__ == '__main__':
    unittest.main()
