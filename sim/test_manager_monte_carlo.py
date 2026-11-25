#!/usr/bin/env python3
"""Pure statistics, cash partition and durable-result checks; no network substitutes."""
import math
import gzip
import tempfile
import unittest
from pathlib import Path

import manager_monte_carlo as M


def cash_partition():
    # Absolute wei example:500 funded+20 earned=470 returned+5 keeper+6 creator+39 backing.
    return dict(ledger_gap_wei=0,unpaid_routine_calls=0,keeper_compensation_wei=5,routine_keeper_paid_wei=3,
        keeper_gas_proxy_cost_wei=2,keeper_net_proxy_wei=3,keeper_unmeasured_operations=[],unknown_owner_gas_calls=0,
        essential_keeper_paid_wei=2,routine_period_permission_upper_wei=10,
        creator_primary_fees_accrued_wei=6,physical_assets_wei=0,external_fee_credit_wei=0,
        unharvested_listing_fees_wei=0,exit_complete=True,owner_net_wei=-37,
        owner_withdrawn_wei=470,owner_funded_wei=500,owner_wallet_gas_proxy_wei=7,
        fees_received_wei=20,backing_lost_wei=39,settlement_fees_wei=0,
        operating_budget_marks=[{'large':'discarded'}],waiting_observations={'RENEWAL_CASH_SHORT':2})


class StatisticsTests(unittest.TestCase):
    def test_actual_archive_keeps_exact_original_formal_response_tables_and_late_counts(self):
        from formal import PIN, window
        for end in (PIN['timestamp']-30*86400,PIN['timestamp']):
            recorded=window(M.ROOT/'sim/data/fwa.sqlite',end)
            original=list(recorded['responses'])
            cohort=M.response_cohort(M.ROOT/'sim/data/fwa.sqlite',recorded['start'],end,recorded['responses'])
            self.assertEqual(recorded['responses'],original)
            self.assertEqual(cohort['responses_sha256'],M.canonical_hash(original))
            self.assertEqual(cohort['sampled_allocations'],len(original))
            self.assertEqual(cohort['allocations_excluded'],0)
            self.assertEqual(cohort['unresolved_at_archive_cutoff'],sum(delay is None for delay,_ in original))
            self.assertEqual(cohort['responsive_after3600_seconds'],sum(delay is not None and delay>3600 for delay,_ in original))
            self.assertEqual(cohort['responsive_delays_clamped_to3480'],sum(delay is not None and delay>3480 for delay,_ in original))
            self.assertGreater(cohort['responsive_after3600_seconds'],0)

    def test_mean_median_percentiles_and_absolute_ci(self):
        result=M.distribution([0,2,4,6])
        self.assertEqual(result['mean'],3)
        self.assertEqual(result['median'],3)
        self.assertAlmostEqual(result['p05'],.3)
        self.assertAlmostEqual(result['p95'],5.7)
        se=math.sqrt(20/3)/2
        self.assertAlmostEqual(result['mean_mcse'],se)
        self.assertAlmostEqual(result['mean_ci'][0],3-1.959963984540054*se)

    def test_stratified_ci_excludes_between_window_variation(self):
        result=M.distribution([0,2,100,102],strata=['old','old','new','new'])
        self.assertEqual(result['mean'],51)
        self.assertAlmostEqual(result['mean_mcse'],math.sqrt(.5))
        self.assertLess(result['mean_mcse'],M.distribution([0,2,100,102])['mean_mcse'])

    def test_paired_contrasts_have_wider_individual_ci(self):
        ordinary=M.distribution([-2,0,2,4])
        simultaneous=M.distribution([-2,0,2,4],M.Z_PAIR)
        self.assertEqual(ordinary['mean'],simultaneous['mean'])
        self.assertAlmostEqual(M.Z_PAIR,2.241402727604947)
        self.assertGreater(simultaneous['mean_ci'][1],ordinary['mean_ci'][1])

    def test_single_or_empty_sample_never_claims_zero_uncertainty(self):
        self.assertIsNone(M.distribution([])['mean'])
        self.assertIsNone(M.distribution([42])['mean_ci'])
        self.assertIsNone(M.distribution([1,2],strata=['old','new'])['mean_ci'])
        self.assertIsNone(M.wilson(0,0)['wilson_ci'])

    def test_bad_stats_inputs_fail(self):
        for values,strata in (([1],[]),([math.nan],None),([math.inf],None)):
            with self.assertRaises(ValueError):M.distribution(values,strata=strata)
        with self.assertRaises(ValueError):M.wilson(3,2)

    def test_wilson_zero_all_and_maximum_width(self):
        zero=M.wilson(0,4096)
        self.assertAlmostEqual(zero['wilson_ci'][0],0)
        self.assertAlmostEqual(zero['wilson_ci'][1],M.Z95**2/(4096+M.Z95**2))
        all_events=M.wilson(4096,4096)
        self.assertAlmostEqual(all_events['wilson_ci'][0],1-zero['wilson_ci'][1])
        self.assertAlmostEqual(all_events['wilson_ci'][1],1)
        half=M.wilson(4096,8192)
        self.assertLess((half['wilson_ci'][1]-half['wilson_ci'][0])/2,.01083)

    def test_two_window_mixture_probability_retains_simultaneous_bounds(self):
        rows=[dict(window=window,loss=loss) for window,loss in [('old',True),('old',True),('new',False),('new',False)]]
        result=M.probability(rows,lambda row:row['loss'])
        self.assertEqual(result['probability'],.5)
        bounds=result['stratified_simultaneous_wilson_ci']
        self.assertLess(bounds[0],.5)
        self.assertGreater(bounds[1],.5)
        self.assertNotIn('wilson_ci',result)


class FinancialControlsTests(unittest.TestCase):
    def test_absolute_owner_keeper_creator_cash_partition(self):
        result=M.compact_result(cash_partition(),1)
        self.assertEqual(result['owner_realized_cash_net_so_far_wei'],-37)
        self.assertEqual(result['remaining_assets_wei'],0)
        self.assertTrue(result['ever_renewal_cash_short'])
        self.assertIsNone(result['cash_short_duration_seconds'])
        self.assertNotIn('operating_budget_marks',result)

    def test_unexplained_wei_and_double_charging_fail(self):
        for field,delta in (('fees_received_wei',1),('keeper_compensation_wei',1),
                            ('owner_net_wei',1),('creator_primary_fees_accrued_wei',1),('ledger_gap_wei',1),
                            ('keeper_gas_proxy_cost_wei',1),('keeper_net_proxy_wei',1),('unpaid_routine_calls',1)):
            bad=cash_partition();bad[field]+=delta
            with self.subTest(field=field),self.assertRaises(ValueError):M.validate_finances(bad,1)

    def test_economic_incomplete_path_is_retained_without_invented_profit(self):
        row=cash_partition()|dict(exit_complete=False,owner_net_wei=None,physical_assets_wei=10,external_fee_credit_wei=2)
        result=M.compact_result(row,1)
        self.assertEqual(result['remaining_assets_wei'],12)
        self.assertIsNone(result['owner_net_wei'])
        self.assertEqual(result['owner_realized_cash_net_so_far_wei'],-37)
        row['owner_net_wei']=1
        with self.assertRaises(ValueError):M.validate_finances(row,1)

    def test_incomplete_exits_suppress_final_population_and_paired_inference(self):
        rows=[]
        for seed in (100000,100001):
            for cell in M.CELLS:
                raw=cash_partition()
                if seed==100001 and cell['id']=='b70000-g0.2':
                    raw.update(exit_complete=False,owner_net_wei=None,physical_assets_wei=10)
                rows.append(M.compact_result(raw,1)|dict(window='old',seed=seed,cell=cell['id']))
        manifest=dict(cells=list(M.CELLS),paths_per_cell=2,assumptions=[],
            windows=[dict(id='old',seed_start=100000,seed_end_exclusive=100002)])
        report=M.summarize(rows,manifest)
        cell=report['cells']['b70000-g0.2']
        self.assertTrue(cell['owner_realized_net_eth']['suppressed'])
        self.assertIsNone(cell['owner_realized_net_eth']['mean_ci'])
        self.assertEqual(cell['completed_exit_owner_net_diagnostic_eth']['n'],1)
        self.assertEqual(cell['cash_flows_eth']['owner_realized_cash_net_so_far_wei']['n'],2)
        first,second=report['paired_backing_differences']
        self.assertTrue(first['paired']['suppressed'])
        self.assertEqual(first['unavailable_pairs'],1)
        self.assertEqual(second['paired']['n'],2)
        self.assertEqual(second['paired']['mean'],0)
        partial=M.summarize(rows[:4],manifest)
        self.assertTrue(partial['cells']['b70000-g0.2']['owner_realized_net_eth']['suppressed'])
        self.assertTrue(partial['paired_backing_differences'][0]['paired']['suppressed'])


class ResumeTests(unittest.TestCase):
    def manifest(self):
        return dict(windows=[dict(id='old',seed_start=100000,seed_end_exclusive=100001)],
                    cells=[dict(id='cell')],mint_fee_wei=1)

    def write_row(self,path,manifest,**override):
        import json
        row=cash_partition()|dict(window='old',seed=100000,cell='cell',campaign_hash=M.canonical_hash(manifest))|override
        with path.open('a') as stream:stream.write(json.dumps(row)+'\n')

    def test_completed_records_resume_and_duplicates_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paths.jsonl';manifest=self.manifest()
            self.write_row(path,manifest)
            rows,seen=M.read_rows(path,manifest)
            self.assertEqual(len(rows),1)
            self.assertEqual(seen,{('old',100000,'cell')})
            self.write_row(path,manifest)
            with self.assertRaisesRegex(ValueError,'duplicate'):M.read_rows(path,manifest)

    def test_gzip_result_roundtrip_and_raw_precedence(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paths.jsonl';manifest=self.manifest()
            self.write_row(path,manifest)
            expected=M.read_rows(path,manifest)
            with gzip.open(str(path)+'.gz','wb') as stream:stream.write(path.read_bytes())
            self.assertEqual(M.read_rows(path,manifest),expected)
            path.unlink()
            self.assertEqual(M.read_rows(path,manifest),expected)

    def test_foreign_seed_or_changed_manifest_fails(self):
        for override in (dict(seed=100001),dict(campaign_hash='another')):
            with tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'paths.jsonl';manifest=self.manifest()
                self.write_row(path,manifest,**override)
                with self.assertRaises(ValueError):M.read_rows(path,manifest)

    def test_partial_final_line_is_preserved_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'paths.jsonl';path.write_text('{"unfinished":')
            before=path.read_bytes()
            with self.assertRaisesRegex(ValueError,'repair explicitly'):M.read_rows(path,self.manifest())
            self.assertEqual(path.read_bytes(),before)

    def test_manifest_hash_is_key_order_independent(self):
        self.assertEqual(M.canonical_hash(dict(a=1,b=2)),M.canonical_hash(dict(b=2,a=1)))
        self.assertNotEqual(M.canonical_hash(dict(a=1)),M.canonical_hash(dict(a=2)))


class ArchiveCompletionTest(unittest.TestCase):
    @unittest.skipUnless((M.ROOT/'sim/data/fwa.sqlite').exists(), 'real FWA archive unavailable')
    def test_older_real_month_includes_actual_expired_request_refunds(self):
        from formal import window
        observed = window(M.ROOT/'sim/data/fwa.sqlite', 1792929275)
        self.assertEqual(observed['successful'], 47553)
        self.assertEqual(observed['refunded'], 6)
        completions = [payload for _, kind, payload in observed['events'] if kind == 'acquisition']
        self.assertEqual(sum(not successful for successful, _ in completions), 6)
        self.assertEqual(len(completions), 47559)


if __name__=='__main__':unittest.main()
