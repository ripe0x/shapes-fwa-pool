#!/usr/bin/env python3
"""Pure arithmetic/control checks plus actual archive cohort qualification, no services."""
import json
import unittest

import manager_operating_assessment as O
from formal import window, PIN


def partition():
    # Independent wei example:500+20 earned=470 returned+5keeper+6creator+39backing.
    return dict(initial_funding_wei=O.CAPITAL,owner_funded_wei=O.CAPITAL,owner_withdrawn_wei=O.CAPITAL-30,
        owner_wallet_gas_proxy_wei=7,owner_net_wei=-37,exit_complete=True,ledger_gap_wei=0,
        unpaid_routine_calls=0,keeper_compensation_wei=5,routine_keeper_paid_wei=3,essential_keeper_paid_wei=2,
        keeper_gas_proxy_cost_wei=2,keeper_net_proxy_wei=3,routine_period_permission_upper_wei=10,
        creator_primary_fees_accrued_wei=6,physical_assets_wei=0,external_fee_credit_wei=0,
        unharvested_listing_fees_wei=0,fees_received_wei=20,backing_lost_wei=39,settlement_fees_wei=0,
        waiting_observations={},randomness_mode='request-keyed-v1',request_events_sha256='pure-accounting-example',
        unknown_owner_gas_calls=0,keeper_unmeasured_operations=[],owner_total_value_before_gas_wei=O.CAPITAL-30,
        owner_exit_reserved_wei=10,owner_exit_spent_wei=7,owner_exit_spend_limit_wei=100,keeper_zero_loss_enabled=True,
        count_aware_gas_curves_enabled=True,physical_sync_cost_basis_enabled=True,keeper_estimate_acceptance_enabled=True,keeper_receipt_history_enabled=True,compensation_mode='bounded-measured-v1')


class OperatingAssessmentTests(unittest.TestCase):
    def test_fixed_design_covers_requested_cross_product_and_stress_cases(self):
        self.assertEqual(len(O.CELLS),8)
        self.assertEqual({c['mint_fee_wei'] for c in O.CELLS},{500000000000000,1000000000000000})
        self.assertEqual({c['backing_bps'] for c in O.CELLS},{70000})
        self.assertEqual({c['reserve_wei'] for c in O.CELLS},{5000000000000000,6000000000000000})
        self.assertTrue(all('renewal_mode' not in cell for cell in O.CELLS))
        frozen=dict(buyer_regimes=['observed-choices','forced-responsive-bid-stress'],
            windows=[dict(id='first',seeds=[10,11]),dict(id='second',seeds=[12,13])])
        tasks=O.tasks(frozen)
        self.assertEqual(len(tasks),16)
        self.assertEqual(sum(t[2]=='recorded-month' for t in tasks),8)
        self.assertEqual(sum(t[2]=='quiet' for t in tasks),4)
        self.assertEqual(sum(t[2]=='early-burst-then-zero' for t in tasks),4)
        self.assertEqual(len(set(tasks)),len(tasks))

    def test_absolute_owner_keeper_creator_backing_cash_partition(self):
        r=O.qualify_result(partition(),1,100,True)
        self.assertEqual(r['owner_net_wei'],-37)
        self.assertEqual(r['keeper_net_proxy_wei'],3)
        self.assertEqual(r['creator_primary_fees_accrued_wei'],6)
        self.assertEqual(r['backing_lost_wei'],39)
        self.assertEqual(r['settled_keep_face_not_yet_consumed_wei'],0)
        self.assertEqual(r['external_total_earned_wei'],20)
        self.assertTrue(r['qualified_exit'])
        for key in ('owner_funded_wei','owner_net_wei','fees_received_wei','keeper_compensation_wei','owner_total_value_before_gas_wei'):
            bad=partition();bad[key]+=1
            with self.subTest(key=key),self.assertRaises(ValueError):O.qualify_result(bad,1,100,True)

    def test_no_unpaid_subsidy_or_unmeasured_final_calls(self):
        for values in ({'unpaid_routine_calls':1},{'unknown_owner_gas_calls':1},{'keeper_unmeasured_operations':['renew']}):
            with self.subTest(values=values),self.assertRaises(ValueError):
                O.qualify_result(partition()|values,1,100,True)

    def test_incomplete_and_over_cap_exits_remain_explicit(self):
        with self.assertRaises(ValueError):O.qualify_result(partition(),1,6,True)
        # Ten wei retained in physical assets, two still claimable externally.
        incomplete=partition()|dict(exit_complete=False,owner_net_wei=None,physical_assets_wei=10,
            owner_withdrawn_wei=O.CAPITAL-40,external_fee_credit_wei=2,owner_total_value_before_gas_wei=O.CAPITAL-28)
        r=O.qualify_result(incomplete,1,100,True)
        self.assertEqual(r['remaining_assets_wei'],12)
        self.assertEqual(r['external_total_earned_wei'],22)
        self.assertIsNone(r['owner_net_wei'])
        self.assertFalse(r['qualified_exit'])

    def test_only_isolated_admission_changes_then_restores_even_on_error(self):
        import keeper
        before=(O.F.policy.edge_backing,keeper.proposal_limits,O.F.policy.build_net,O.S.MIN_BACKING)
        with self.assertRaisesRegex(RuntimeError,'intentional'):
            with O.admission(True,25*10**15):
                self.assertIs(O.F.policy.edge_backing,O.S.relaxed_edge)
                self.assertIs(keeper.proposal_limits,O.S.relaxed_limits)
                self.assertEqual(O.S.MIN_BACKING,25*10**15)
                raise RuntimeError('intentional')
        self.assertEqual((O.F.policy.edge_backing,keeper.proposal_limits,O.F.policy.build_net,O.S.MIN_BACKING),before)

    def test_real_archive_response_choices_and_burst_phase_are_preserved(self):
        w=window(O.ROOT/'sim/data/fwa.sqlite',PIN['timestamp'])
        responses=list(w['responses'])
        events,meta=O.feasible_burst(w)
        self.assertEqual(w['responses'],responses)
        self.assertTrue(any(delay is not None and delay>3600 for delay,_ in responses))
        self.assertTrue(any(keep is True for _,keep in responses))
        self.assertEqual(meta['requests'],sum(kind=='request' for _,kind,_ in events))
        self.assertTrue(all(at<2*O.F.DAY for at,kind,_ in events if kind=='request'))
        self.assertTrue(all((w['start']+at)%O.F.OperatingClock.INTERVAL<O.F.OperatingClock.BLACKOUT_START
                            for at,kind,_ in events if kind=='request'))

    def test_complete_curve_envelope_covers_each_recorded_work_count(self):
        # Independent integer examples for packet qualification; no RPC response is fabricated.
        samples={op:[dict(workCount=1,gasUsed=100,gasEstimate=150,estimateKind='rpc-estimate')] for op in O.REQUIRED_GAS}
        curves={op:dict(single_billed_gas=100,single_estimate_gas=150,
            billed_per_extra_work=0,estimate_per_extra_work=0) for op in O.REQUIRED_GAS}
        samples['list'].append(dict(workCount=8,gasUsed=800,gasEstimate=1000,estimateKind='rpc-estimate'))
        curves['list'].update(billed_per_extra_work=100,estimate_per_extra_work=122)
        packet=dict(measurements=samples,gas_curves=curves)
        samples['list'].append(dict(workCount=1,gasUsed=99,gasEstimate=10000,estimateKind='signed-limit-upper'))
        O.verify_gas_curves(packet)
        self.assertEqual(len(O.estimate_samples(samples['list'])),2)
        self.assertEqual(O.F.receipt_gas(curves,'list',1),100)
        self.assertEqual(O.F.receipt_gas(curves,'list',8),800)
        self.assertEqual(O.F.receipt_gas(curves,'list',8,estimate=True),1004)
        curves['list']['estimate_per_extra_work']=121
        with self.assertRaisesRegex(ValueError,'complete recorded sample envelope'):O.verify_gas_curves(packet)
        curves['list']['estimate_per_extra_work']=122
        samples['list'][1]['workCount']=9
        with self.assertRaises(ValueError):O.verify_gas_curves(packet)

    def test_rpc_estimate_requires_rpc_single_baseline_and_real_raw_field(self):
        with self.assertRaisesRegex(ValueError,'single-work baseline'):
            O.estimate_samples([dict(workCount=1,estimateKind='signed-limit-upper'),
                                dict(workCount=8,estimateKind='rpc-estimate')])
        costs=json.loads((O.ROOT/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        actual=json.loads((O.ROOT/costs['receipts']).read_text())
        signed={t['transaction']['hash']:int(t['transaction']['gas'],0) for t in actual['transactions']}
        costs['gas_curves']={'create':{}}
        for sample in costs['measurements']['create']:
            sample['estimateKind']='signed-limit-upper'
            sample['gasEstimate']=signed[sample['hash']]
        O.verify_measurement_receipts(costs,[actual])
        costs['measurements']['create'][0]['estimateKind']='rpc-estimate'
        with self.assertRaisesRegex(ValueError,'raw RPC estimate'):
            O.verify_measurement_receipts(costs,[actual])

    def test_paid_and_owner_curve_envelopes_use_distinct_arithmetic_inputs(self):
        # Pure envelope arithmetic, not a successful response from any service.
        import copy
        samples={op:[dict(workCount=1,gasUsed=100,gasEstimate=150,estimateKind='rpc-estimate')]
                 for op in O.REQUIRED_GAS if op!='recover_sync'}
        samples['recover']=[dict(workCount=1,gasUsed=200,gasEstimate=250,estimateKind='rpc-estimate')]
        for op in O.METERED_OPERATIONS:samples[op][0]['measuredGas']=80
        for op in ('recoverUnlist','recoverLiquidate'):
            samples[op]=[dict(workCount=1,gasUsed=200,gasEstimate=250,estimateKind='rpc-estimate')]
        curves={op:dict(single_billed_gas=100,single_estimate_gas=150,
                       billed_per_extra_work=0,estimate_per_extra_work=0) for op in O.REQUIRED_GAS}
        for op in O.METERED_OPERATIONS:curves[op].update(single_meter_gas=80,meter_per_extra_work=0)
        unpaid=dict(single_billed_gas=200,single_estimate_gas=250,
                    billed_per_extra_work=0,estimate_per_extra_work=0)
        curves['recover_sync']=unpaid.copy()
        costs=dict(compensation_mode='bounded-measured-v1',measurements=samples,gas_curves=curves,
                   owner_gas_curves={op:unpaid.copy() for op in ('unlist','liquidate')},
                   gas_proxy={op:100 for op in O.REQUIRED_GAS},
                   gas_estimate_proxy={op:250 for op in O.OWNER_OPERATIONS},
                   gas_meter_proxy={op:80 for op in O.METERED_OPERATIONS},
                   unmeasured_operations=['larger sync batches'])
        samples['sync'][0].update(gasAllowance=372000,workUnits=0)
        samples['recover'][0]['verifiedContext']=dict(gasAllowance=372000,workUnits=0,pairedPaidHash='arithmetic-only')
        costs.update(fullGasSchedule={'sync':1},
            sync_contexts={'372000:0:1':dict(billed_gas=100,estimate_gas=150,measured_gas=80)},
            owner_sync_contexts={'372000:0:1':dict(billed_gas=200,estimate_gas=250)})
        O.qualify_costs(costs,True)
        self.assertEqual(O.F.receipt_gas(curves,'unlist',1,999999),100)
        self.assertEqual(O.F.receipt_gas(O.owner_curves(costs),'unlist',1),200)
        self.assertEqual(O.supported_work(costs)['sync'],1)
        self.assertEqual(O.supported_work(costs,owner=True)['recover_sync'],1)
        with self.assertRaisesRegex(ValueError,'actual receipt support'):
            O.F.metered_work_gas(curves,costs['gas_meter_proxy'],'sync',2,O.supported_work(costs))
        bad=copy.deepcopy(costs);bad['unmeasured_operations'].append('harvest')
        with self.assertRaisesRegex(ValueError,'unknown or unmeasured'):O.qualify_costs(bad,True)
        bad=copy.deepcopy(costs);bad['owner_gas_curves']['unlist']['single_billed_gas']=100
        with self.assertRaisesRegex(ValueError,'complete recorded sample envelope'):O.qualify_costs(bad,True)
        bad=copy.deepcopy(costs);bad['measurements']['sync'][0].pop('measuredGas')
        with self.assertRaisesRegex(ValueError,'actual work meter'):O.qualify_costs(bad,True)

    def test_sync_contexts_cannot_reuse_terminal_receipts_for_foreign_tails(self):
        contexts={'455000:1:1':dict(billed_gas=100,estimate_gas=150,measured_gas=80),
                  '1005000:1:2':dict(billed_gas=350,estimate_gas=400,measured_gas=300)}
        self.assertEqual(O.F.sync_context_gas(contexts,455000,1)['measured_gas'],80)
        self.assertEqual(O.F.sync_context_gas(contexts,1005000,1,2)['billed_gas'],350)
        for allowance,units,count in ((2919000,0,1),(455000,1,2),(455000,0,1)):
            with self.subTest(allowance=allowance,units=units,count=count),self.assertRaisesRegex(ValueError,'unmeasured sync context'):
                O.F.sync_context_gas(contexts,allowance,units,count)

    def test_current_meter_profile_is_bound_to_actual_five_field_events(self):
        import copy
        costs=json.loads((O.ROOT/'docs/receipts/manager-measured-cost-calibration.json').read_text())
        O.qualify_costs(costs,True)
        refs=costs.get('receipt_inputs') or [dict(path=costs['receipts'],sha256=costs['receipts_sha256'])]
        packets=[json.loads((O.ROOT/ref['path']).read_text()) for ref in refs]
        O.verify_measurement_receipts(costs,packets)
        changed=copy.deepcopy(costs)
        context=O.operation_samples(changed,'recover_sync',owner=True)[0]['verifiedContext']
        context['gasAllowance']+=1
        with self.assertRaisesRegex(ValueError,'paired-state provenance'):O.verify_measurement_receipts(changed,packets)
        changed=copy.deepcopy(costs)
        first=next(iter(changed['sync_contexts']))
        changed['sync_contexts'][first]['billed_gas']+=1
        with self.assertRaisesRegex(ValueError,'sync context envelope'):O.qualify_costs(changed,True)
        for op in ('unlist','liquidate'):
            self.assertTrue(O.operation_samples(costs,op,owner=True))
            self.assertTrue(all('measuredGas' not in row and 'measuredWork' not in row
                                for row in O.operation_samples(costs,op,owner=True)))
        self.assertEqual(O.supported_work(costs)['sync'],2)
        with self.assertRaisesRegex(ValueError,'actual receipt support'):
            O.F.metered_work_gas(costs['gas_curves'],costs['gas_meter_proxy'],'sync',3,O.supported_work(costs))
        changed=copy.deepcopy(costs)
        sample=O.operation_samples(changed,'build')[0]
        meter=sample.get('measuredWork',sample)
        meter['measuredGas']+=1
        with self.assertRaisesRegex(ValueError,'work meter differs'):O.verify_measurement_receipts(changed,packets)

    def test_old_cost_packet_cannot_be_promoted_to_final_operating_evidence(self):
        costs=json.loads((O.ROOT/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        with self.assertRaises(ValueError):O.qualify_costs(costs,True)

    def test_measurement_gas_is_bound_to_real_successful_receipts(self):
        costs=json.loads((O.ROOT/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        actual=json.loads((O.ROOT/costs['receipts']).read_text())
        O.verify_measurement_receipts(costs,[actual])
        costs['gas_estimate_proxy']={'setExiting':74659}
        with self.assertRaisesRegex(ValueError,'understates receipt estimate'):
            O.verify_measurement_receipts(costs,[actual])
        costs.pop('gas_estimate_proxy')
        costs['measurements']['create'][0]['gasUsed']+=1
        with self.assertRaisesRegex(ValueError,'matching successful billed receipt'):
            O.verify_measurement_receipts(costs,[actual])

    def test_incomplete_or_over_cap_paths_suppress_group_return(self):
        cell=O.CELLS[0]
        frozen=dict(cells=[cell],paths_per_window=1,expected_rows=6,buyer_regimes=['observed-choices'])
        good=O.qualify_result(partition(),1,100,True)|dict(cell=cell['id'],regime='recorded-month',buyer_regime='observed-choices',window='first',seed=1)
        incomplete=partition()|dict(exit_complete=False,owner_net_wei=None,physical_assets_wei=10,
            owner_withdrawn_wei=O.CAPITAL-40,owner_total_value_before_gas_wei=O.CAPITAL-30)
        over=O.qualify_result(incomplete,1,100,True)|dict(cell=cell['id'],regime='recorded-month',buyer_regime='observed-choices',window='second',seed=2)
        summary=O.summarize([good,over],frozen)['cells'][0]
        self.assertEqual(summary['paths'],2)
        self.assertEqual(summary['qualified_exits'],1)
        self.assertIsNone(summary['owner_net_mean_wei'])
        self.assertEqual(summary['exit_limit_violations'],0)
        self.assertEqual(summary['mean_wei']['creator_primary_fees_accrued_wei'],6)


if __name__=='__main__':unittest.main()
