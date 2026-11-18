"""Pure accounting regressions. Real counterparty evidence is ForkReconcile, not these inputs."""
import random
import copy
import unittest

from vault import ACTIVE, ALLOCATED, OWED, BPS, E, UNIT, Vault


class VaultAccountingTest(unittest.TestCase):
    def test_journal_stops_before_seventeenth_own_transition(self):
        v = Vault(seed=100 * E, balance=100 * E, reserve=0)
        v.restock(10, 3, 10**15); v.restock(10, 3, 10**15)
        for i in range(1, 18):
            v.list(i, 363 * 10**14 + i * 10_000)
        v.completed_prefix = 18
        self.assertEqual(v.process_journal(list(range(1, 17)) + [None, 17]), 17)
        self.assertEqual(v.acquisition_cursor, 17)
        self.assertEqual(v.positions[17].state, ACTIVE)
        self.assertEqual(v.process_journal([17]), 1)
        self.assertEqual(v.acquisition_cursor, 18)
        self.assertEqual(v.positions[17].state, ALLOCATED)
        self.assert_book(v)

    def test_distribution_tail_needs_real_gain_after_maintenance(self):
        v = Vault(seed=E, balance=E, reserve=5 * 10**15, distribution_bps=5000)
        v.deposit('h', E); v.checkpoint()
        v.restock(1, 3, 10**15); v.list(1, 363 * 10**14)
        self.assertFalse(v.distribution_tail(10**14))
        v.balance += E
        self.assertTrue(v.distribution_tail(10**14))
        self.assertFalse(v.distribution_tail(2 * E))

    def test_distribution_credit_cannot_skip_the_unfunded_reserve(self):
        v = Vault(seed=10**16, balance=10**16, reserve=0, distribution_bps=5000)
        v.deposit('h', 1_004_200_000_000_910_000); v.checkpoint()
        v.restock(10, 3, 10**15); v.restock(4, 3, 10**15)
        for i in range(14):
            v.list(i, 363 * 10**14 + i * 10_000)
        self.assertEqual(v.free(), 10**15)
        v.reserve = 3 * 10**16
        self.assertFalse(v.distribution_tail(23_000_000_000_000, 3 * 10**16))
        v.receive_fees(3 * 10**16)
        self.assertEqual(v.idle(), 10**15)
        with self.assertRaisesRegex(RuntimeError, 'Nothing'):
            v.checkpoint()

    def test_unexposed_history_preserves_seed_and_first_deposit_prices(self):
        v = Vault(seed=10**16, balance=10**16, reserve=5 * 10**15)
        v.completed_prefix = 576
        v.deposit("alice", E, 100_000_000_000_000)
        self.assertTrue(v.checkpoint())
        self.assertEqual(v.acquisition_cursor, 576)
        self.assertGreater(v.share_balance("alice"), 0)
        self.assertEqual(v.keeper_paid, 0)
        v.pay_keeper(100_000_000_000_000, cap=100_000_000_000_000)
        self.assertEqual(v.balance, E + 10**16)

    def vault(self):
        return Vault(seed=E, balance=E, reserve=0)

    def assert_book(self, v):
        positions = list(v.positions.values())
        self.assertEqual(v.tracked_value, sum(v.idle_packs) + sum(v.recovery_packs) + v.loose_shapes * UNIT
                         + sum(p.value for p in positions))
        self.assertEqual(v.idle_value, sum(v.idle_packs) + sum(v.recovery_packs) + v.loose_shapes * UNIT)
        self.assertEqual(len(v.idle_quotes), len(v.idle_packs))
        self.assertEqual(v.idle_funding, sum(v.idle_quotes))
        active = [p for p in positions if p.state == ACTIVE]
        self.assertEqual(v.active_backing, sum(p.backing for p in active))
        self.assertEqual(v.active_count, len(active))
        self.assertEqual(v.fee_debt_sum, sum(p.fee_debt for p in active))
        self.assertEqual(v.allocated_value, sum(p.value for p in positions if p.state == ALLOCATED))
        for debt, count in v.count_by_debt.items():
            self.assertEqual(count, sum(p.fee_debt == debt for p in active))

    def test_paid_mint_loose_inventory_bid_and_redemption(self):
        v = self.vault()
        self.assertEqual(v.restock(1, 3, 10**15), 1)
        self.assertEqual(v.loose_shapes, 7)
        self.assertEqual(v.tracked_value, 10**17)
        self.assertEqual(v.mint_fees, 10**15)
        v.list(1, 363 * 10**14)
        self.assertEqual(v.nav_now(), E - 10**15)
        self.assert_book(v)
        v.select(1)
        v.bid_settled(1)
        self.assertEqual(v.allocated_value, 3 * UNIT)
        v.sync_owned(1)
        v.prune(1)
        self.assert_book(v)
        for _ in range(8):
            v.liquidate_one()
            self.assert_book(v)
        self.assertEqual(v.tracked_value, 0)
        self.assertEqual(v.balance, E - 10**15 - 363 * 10**14)

    def test_waiting_inventory_funding_is_not_reused_for_another_build(self):
        v = Vault(seed=15 * 10**16, balance=15 * 10**16, reserve=0)
        backing = 4 * UNIT
        v.restock(1, 3, 10**15, [backing])
        self.assertEqual(v.balance, 49 * 10**15)
        before = copy.deepcopy(v.__dict__)
        with self.assertRaisesRegex(RuntimeError, "InsufficientBacking"):
            v.restock(1, 3, 10**15, [backing])
        self.assertEqual(v.__dict__, before)
        v.list(1, backing)
        self.assertEqual(v.idle_funding, 0)
        v.unlist(1)
        self.assertEqual(v.idle_funding, backing)
        v.liquidate_one()
        self.assertEqual(v.idle_funding, 0)
        self.assert_book(v)

    def test_keep_removes_old_principal_then_adopts_current_gift_once(self):
        v = self.vault()
        v.restock(1, 3, 10**15)
        v.list(1, 363 * 10**14)
        v.select(1)
        v.resolve_keep(1)
        self.assertEqual(v.tracked_value, 7 * UNIT)
        self.assertEqual(v.settlement_fees, 363 * 10**12)
        v.adopt(4 * UNIT)
        self.assertEqual(v.tracked_value, 11 * UNIT)
        self.assertEqual(v.nav_now(), E - 10**15 - 3 * UNIT - 363 * 10**12 + 4 * UNIT)
        self.assert_book(v)

    def test_owed_return_cannot_be_spent_until_recovered(self):
        v = self.vault()
        v.restock(1, 3, 10**15)
        v.list(1, 363 * 10**14)
        v.select(1)
        v.bid_settled(1)
        v.sync_owned(1, owned=False)
        self.assertEqual(v.positions[1].state, OWED)
        self.assertEqual(v.idle_value, 7 * UNIT)
        self.assertEqual(v.tracked_value, 10 * UNIT)
        self.assert_book(v)
        v.sync_owned(1)
        self.assertEqual(v.idle_value, 10 * UNIT)
        self.assert_book(v)

    def test_fee_histogram_zero_witness_and_harvest_rounding(self):
        v = self.vault()
        v.restock(2, 3, 10**15)
        v.list(1, 363 * 10**14, fee_debt=4)
        v.list(2, 363 * 10**14 + 10_000, fee_debt=5)
        v.accrue(1, 1)
        self.assertEqual(v.pending_active_fees(1), 1)
        with self.assertRaisesRegex(RuntimeError, 'BadWitness'):
            v.pending_active_fees(2)
        v.harvest_listing(1, 5)
        self.assertEqual(v.pending_active_fees(2), 0)
        self.assert_book(v)

    def test_partial_holder_exit_protects_escrow_and_claims(self):
        v = Vault(seed=10**16, balance=10**16, reserve=0)
        v.deposit('alice', E)
        v.checkpoint()
        v.restock(10, 3, 10**15)
        for i in range(10):
            v.list(i, 363 * 10**14 + i * 10_000)
        v.request_redeem('alice', v.share_balance('alice'))
        v.checkpoint()
        self.assertGreater(v.locked_shares, 0)
        self.assertLessEqual(v.redemption_reserve, v.balance)
        v.deposit('bob', 10**17, ck=10**12)
        protected = v.pending_total + v.redemption_reserve + v.processing_pool
        self.assertEqual(v.free(), v.balance - protected)
        v.claim('alice')
        self.assertEqual(v.free(), v.balance - v.pending_total - v.processing_pool - v.redemption_reserve)
        self.assert_book(v)

    def test_randomized_book_transitions(self):
        rng = random.Random(818)
        v = Vault(seed=100 * E, balance=100 * E, reserve=0)
        for _ in range(10):
            v.restock(10, 3, 10**15)
        for i in range(100):
            v.list(i, 363 * 10**14 + i * 10_000)
        ids = list(v.positions)
        rng.shuffle(ids)
        for i in ids:
            if rng.randrange(3) == 0:
                v.unlist(i)
            else:
                v.select(i)
                if rng.randrange(2):
                    v.resolve_keep(i)
                else:
                    v.bid_settled(i)
                    v.sync_owned(i)
            v.prune(16)
            self.assert_book(v)

    def test_receipt_precedes_selection_and_retains_payment_fee(self):
        v = self.vault()
        v.restock(1, 3, 10**15)
        v.list(1, 363 * 10**14)
        v.record_keep(1, 100)
        v.settlement_fee_bps = 500
        v.deposit('holder', 10**17)
        v.completed_prefix = 2
        with self.assertRaisesRegex(RuntimeError, 'CatchUpFirst'):
            v.checkpoint()
        v.process_journal([None, 1])
        with self.assertRaisesRegex(RuntimeError, 'PendingReceipts'):
            v.checkpoint()
        v.consume_keep(1)
        v.prune(1)
        self.assertEqual(v.settlement_fees, 363 * 10**12)
        self.assert_book(v)
        v.checkpoint()

    def test_oversized_gift_recovery_preserves_exact_remaining_value(self):
        v = self.vault()
        v.adopt(40 * UNIT)
        v.recover_pack(30 * UNIT)
        self.assertEqual(v.recovery_packs, [10 * UNIT])
        self.assert_book(v)
        v.recover_pack(10 * UNIT, complete=True)
        self.assertEqual(v.tracked_value, 0)
        self.assertEqual(v.balance, E + 40 * UNIT)
        self.assert_book(v)

    def test_rejected_checkpoint_cannot_duplicate_harvested_credit(self):
        v = self.vault()
        v.restock(1, 3, 10**15)
        v.list(1, 363 * 10**14)
        v.select(1)
        v.deposit('holder', 10**17)
        v.allocated_bound_bps = 0
        v.fee_credit = 10**15
        before = copy.deepcopy(v.__dict__)
        for _ in range(2):
            with self.assertRaisesRegex(RuntimeError, 'AllocatedExposure'):
                v.checkpoint(v.fee_credit)
            self.assertEqual(v.__dict__, before)


if __name__ == '__main__':
    unittest.main()
