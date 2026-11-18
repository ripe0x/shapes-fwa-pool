import unittest
from mint_policy_research import (
    candidate, choose, expected_year, mint_fees, outcome_margins,
    fresh_mint_count, first_build_cost,
)


class ResearchTests(unittest.TestCase):
    def test_ladder_is_bounded(self):
        self.assertLessEqual(choose(66).pack_value, 0.20)

    def test_small_capital_uses_small_packs(self):
        self.assertEqual(choose(0.66).pack_value, 0.03)

    def test_full_budget_changes_size_at_large_capital(self):
        self.assertEqual(choose(66).pack_value, 0.05)

    def test_strict_share_limit_waits(self):
        self.assertIsNone(choose(6.6, max_share=0.000001))

    def test_mint_revenue_scales_with_fresh_backing(self):
        self.assertAlmostEqual(mint_fees(0.2), 2 * mint_fees(0.1))

    def test_returned_pack_mints_nothing(self):
        e = expected_year(choose(2), keep_rate=0)
        self.assertEqual(e["primary_mints_replacement_eth"], 0)

    def test_keep_outcome_mints_replacement(self):
        e = expected_year(choose(2), keep_rate=0.25)
        self.assertGreater(e["primary_mints_replacement_eth"], 0)

    def test_outcomes_both_explicit(self):
        bid, keep = outcome_margins(0.03, 0.03 / 0.9)
        self.assertIsInstance(bid, float)
        self.assertIsInstance(keep, float)

    def test_paid_mints_are_whole(self):
        self.assertEqual(fresh_mint_count(0.03, 1), 1)
        self.assertEqual(fresh_mint_count(0.03, 4), 2)
        self.assertEqual(fresh_mint_count(0.10, 5), 5)
        self.assertEqual(fresh_mint_count(0.20, 5), 10)

    def test_initial_cost_is_nonzero_and_counted(self):
        choice = choose(2)
        fees, op = first_build_cost(choice.pack_value, choice.count, 0.5)
        self.assertEqual(choice.initial_mint_fees, fees)
        self.assertEqual(choice.initial_gas_and_keeper_cost, op)
        self.assertGreater(fees, 0)
        self.assertGreater(op, 0)

    def test_zero_draws_still_cost_mints(self):
        e = expected_year(choose(2), acquisitions_per_day=0)
        self.assertLess(e["net_annual_eth"], 0)
        self.assertLess(e["apr"], 0)
        self.assertEqual(e["primary_mints_replacement_eth"], 0)

    def test_capital_includes_initial_execution_and_seeds(self):
        c = choose(2)
        cost = (c.count * (c.pack_value + c.backing)
                + c.initial_mint_fees + c.initial_gas_and_keeper_cost
                + c.vault_count * 0.01)
        self.assertLessEqual(cost, 2 + 1e-12)

    def test_more_than_three_hundred_requires_separate_vaults(self):
        c = choose(66)
        self.assertGreater(c.count, 300)
        self.assertGreater(c.vault_count, 1)

    def test_full_allocation_applies_limit(self):
        c = candidate(66, 0.03, max_share=0.25)
        self.assertIsNone(c)

if __name__ == "__main__":
    unittest.main()
