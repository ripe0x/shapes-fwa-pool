#!/usr/bin/env python3
"""Absolute economic checks against real archived receipts; no service substitutes."""
import tempfile
import json
import unittest
from pathlib import Path
from manager_closeout import ROOT, PINS, SOURCE_PINS, build_report, checked_json, verify_sources, markdown


class CloseoutTests(unittest.TestCase):
    def test_absolute_economics_and_actual_ledgers(self):
        r = build_report()
        self.assertEqual(r['standard_fresh_bid_pre_gas_break_even_fee_wei'], 384605000000000)
        self.assertEqual(len(r['comparison']['rows']), 8)
        standard = [x for x in r['comparison']['rows'] if x['backing_wei'] == 30000000000000000]
        for row in standard:
            self.assertEqual(row['bid_cycle_gross_wei'], 1153815000000000)
            self.assertEqual(row['keep_cycle_gross_after_face_wei'], 853815000000000)
            self.assertLess(row['bid_cycle_net_after_quoted_cost_wei'], 0)
            self.assertIn('IMMUTABLE_95PCT_FACE_COVERAGE', row['canonical_rejection_reasons'])
        self.assertEqual([c['ownerNetWei'] for c in r['actual_standard_round_trips']], [-1858795000000000, -2396981500000000])
        self.assertEqual([c['ownerNetWei'] for c in r['actual_manager_round_trips']], [-1940071586360229, -5198947885644295])
        self.assertEqual(r['actual_keeper']['netWei'], 191832043922585)
        self.assertEqual(r['actual_creator_gross_fees_wei'], 6000000000000000)
        self.assertEqual(r['owner_wallet_gas_sensitivity'][0]['operation_costs_wei']['create'], 121238800000000)
        self.assertIn('not monthly return', markdown(r))

    def test_revised_candidate_gas_does_not_rewrite_historical_receipt_settings(self):
        receipt=checked_json(ROOT/'docs/receipts/manager-r2-closeout.json',PINS['docs/receipts/manager-r2-closeout.json'])
        candidate=json.loads((ROOT/'deploy/manager.json').read_text())
        candidate['gasSchedule'].update(selected=225000,synced=285000,list=380000)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            # All evidence and code remain the real files; only the candidate config is isolated.
            for name in ('src','sim','keeper','docs'):
                (root/name).symlink_to(ROOT/name,target_is_directory=True)
            (root/'deploy').mkdir()
            (root/'deploy/manager.json').write_text(json.dumps(candidate))
            report=build_report(root)
        self.assertEqual(report['historical_manager_values'],receipt['managerValues'])
        self.assertEqual(report['historical_manager_values']['gasSchedule']['selected'],180000)
        self.assertEqual(report['historical_manager_values']['gasSchedule']['synced'],120000)
        self.assertEqual(report['historical_manager_values']['gasSchedule']['list'],280000)
        self.assertEqual(report['historical_manager_values_file_sha256'],receipt['managerValuesSha256'])
        self.assertNotIn('deploy/manager.json',report['input_sha256'])
        self.assertIn('Historical R2',report['kind'])
        self.assertIn('Historical R2',markdown(report))

    def test_changed_receipt_is_rejected(self):
        name, sha = next(iter(PINS.items()))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'changed.json'
            path.write_bytes((ROOT/name).read_bytes() + b' ')
            with self.assertRaisesRegex(ValueError, 'changed receipt'):
                checked_json(path, sha)

    def test_changed_real_diagnostic_or_proposal_source_is_rejected(self):
        for name in ('sim/manager_standard_backing.py', 'keeper/keeper.py'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / name
                path.parent.mkdir(parents=True)
                path.write_bytes((ROOT / name).read_bytes() + b'\n')
                with self.assertRaisesRegex(ValueError, 'stale evidence'):
                    verify_sources(root, {name: SOURCE_PINS[name]})

    def test_changed_source_is_rejected(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/'changed.py'
            path.write_text('old source')
            expected = hashlib.sha256(path.read_bytes()).hexdigest()
            path.write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'stale evidence'):
                verify_sources(root, {'changed.py': expected})


if __name__ == '__main__':
    unittest.main()
