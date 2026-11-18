import unittest
from mint_policy_research import (
    candidate, choose, expected_year, mint_fees, outcome_margins,
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

    def test_full_allocation_applies_limit(self):
        c = candidate(66, 0.03, max_share=0.25)
        self.assertIsNone(c)

if __name__ == "__main__":
    unittest.main()
