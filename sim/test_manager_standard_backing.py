#!/usr/bin/env python3
"""Pure standard-backing arithmetic and actual frozen-archive/input qualification."""
import argparse
import json
import unittest

import manager_standard_backing as S


class StandardBackingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parent_path=S.ROOT/'sim/out/manager-monte-carlo-funded/manifest.json'
        cls.parent=json.loads(cls.parent_path.read_text())

    def test_actual_minimum_is_archived025_and_live_confirmation_bound(self):
        minimum=S.archived_minimum(S.ROOT/self.parent['archive'])
        self.assertEqual(minimum['value_wei'],25*10**15)
        self.assertEqual(minimum['block'],25944617)
        proof=json.loads((S.ROOT/'docs/receipts/manager-r2-min-backing-continuity.json').read_text())
        self.assertEqual(proof['archiveLastChange']['valueWei'],minimum['value_wei'])
        self.assertEqual(proof['toBlock'],self.parent['mint_fee_observation']['block'])
        self.assertEqual(proof['subsequentLogs'],[])

    def test_only_isolated_worker_installation_changes_admission(self):
        self.assertIs(S.F.policy.edge_backing,S.CANONICAL_EDGE)
        self.assertIsNot(S.F.policy.build_net,S.relaxed_build_net)

    def test_relaxed_admission_retains_minimum_cap_and_quantization(self):
        previous=S.MIN_BACKING
        try:
            S.MIN_BACKING=25*10**15
            edge=lambda cap,ratio:S.relaxed_edge(10**18,cap,100,3,0,0,0,backing_ratio_bps=ratio)
            self.assertEqual(edge(None,10000),3*10**16)
            self.assertEqual(edge(29*10**15+1,10000),29*10**15)
            self.assertEqual(edge(24*10**15,10000),0)
            self.assertEqual(S.relaxed_limits(None,3*10**16,100,9000,10**18),(25*10**15,10**18))
            self.assertEqual(S.relaxed_limits(None,3*10**16,100,0,10**18),(1,0))
        finally:S.MIN_BACKING=previous

    def test_current_cycle_costs_and_bid_keep_losses_are_absolute(self):
        rows=json.loads((S.ROOT/'docs/receipts/manager-closeout-economics.json').read_text())['comparison']['rows']
        current=[r for r in rows if r['backing_wei']==3*10**16 and r['mint_fee_per_shape_wei']==5*10**14]
        self.assertEqual(len(current),2)
        for row in current:
            self.assertEqual(row['primary_mint_fees_wei'],15*10**14)
            self.assertEqual(row['canonical_admission_backing_wei'],0)
            self.assertIn('IMMUTABLE_95PCT_FACE_COVERAGE',row['canonical_rejection_reasons'])
            self.assertEqual(row['bid_cycle_gross_wei'],1153815000000000)
            self.assertEqual(row['keep_cycle_gross_after_face_wei'],853815000000000)
            self.assertEqual(row['bid_cycle_gross_wei']-row['keep_cycle_gross_after_face_wei'],3*10**14)
            expected=2137400000000000 if row['total_gas_gwei']==.2 else 2973500000000000
            keep_expected=2065400000000000 if row['total_gas_gwei']==.2 else 2823500000000000
            self.assertEqual(row['canonical_admission_conservative_cost_wei'],expected)
            self.assertEqual(row['bid_cycle_quoted_cost_wei'],expected)
            self.assertEqual(row['keep_cycle_quoted_cost_wei'],keep_expected)
            self.assertEqual(row['bid_cycle_net_after_quoted_cost_wei'],1153815000000000-expected)
            self.assertEqual(row['keep_cycle_net_after_quoted_cost_wei'],853815000000000-keep_expected)
            self.assertEqual(row['work_units'],dict(construction=2,bid_maintenance_and_retirement=2,keep_maintenance=1))
            self.assertLess(row['keep_cycle_net_after_quoted_cost_wei'],row['bid_cycle_net_after_quoted_cost_wei'])
        historical=[r for r in rows if r['mint_fee_per_shape_wei']==10**15]
        self.assertTrue(historical)
        self.assertTrue(all(r['primary_mint_fees_wei']==3*10**15 for r in historical))

    def test_frozen_paths_are_preserved_and_recomputation_is_explicitly_retired(self):
        before=self.parent_path.read_bytes()
        self.assertEqual(self.parent['paths_per_cell'],8192)
        options=argparse.Namespace(paths=8192,seed_start=100000,window_end=None,workers=8)
        with self.assertRaisesRegex(RuntimeError,'pinned revision'):S.campaign_manifest(self.parent_path,options)
        self.assertEqual(self.parent_path.read_bytes(),before)


if __name__=='__main__':unittest.main()
