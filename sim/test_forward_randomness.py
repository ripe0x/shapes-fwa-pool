"""Pure model randomness and cached canonical economics; no fabricated service answers."""
import json
import unittest
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import forward as F


ROOT=Path(__file__).resolve().parent.parent


def scenario(**changes):
    # Counterfactual request outcomes are model inputs, not successful RPC fixtures.
    events=[]
    for i in range(12):
        successful=i%4!=0
        events += [(120+i*500,'request',None),(156+i*500,'acquisition',(successful,1.0))]
    sc=F.Scenario(volume=F.const(0),timed=True,start_timestamp=1795521275,
        replay_events=events,replay_period_seconds=3*F.DAY)
    sc.update(changes)
    return sc



def keyed_path(seed):
    clock=F.OperatingClock(scenario(request_randomness=True),seed,1,1)
    return clock.request_events_sha256,clock.request_draws.tolist()


def quiet_scenario(**changes):
    from test_manager import current_scenario
    return current_scenario(deposit_wei=3*10**17,**changes)


class RequestRandomnessTest(unittest.TestCase):
    def test_request_draws_are_domain_separated_seeded_and_cover_refunds(self):
        a=F.OperatingClock(scenario(request_randomness=True),7,1,1)
        b=F.OperatingClock(scenario(request_randomness=True),7,1,1)
        c=F.OperatingClock(scenario(request_randomness=True),8,1,1)
        self.assertEqual(a.request_draws.shape,(12,3))
        self.assertTrue(np.array_equal(a.request_draws,b.request_draws))
        self.assertFalse(np.array_equal(a.request_draws,c.request_draws))
        self.assertFalse(np.array_equal(a.request_draws[:,0],a.request_draws[:,1]))
        self.assertFalse(np.array_equal(a.request_draws[:,1],a.request_draws[:,2]))
        self.assertEqual(a.request_events_sha256,c.request_events_sha256)

    def test_path_is_independent_of_process_and_submission_order(self):
        alone=keyed_path(7)
        with ProcessPoolExecutor(2) as workers:
            reverse=list(workers.map(keyed_path,(8,7)))
        self.assertEqual(alone,reverse[1])

    def test_conditional_selections_do_not_move_later_request_or_response_draws(self):
        clocks=[F.OperatingClock(scenario(request_randomness=True),7,1,1) for _ in range(3)]
        sinks=[];responses=[]
        for clock,select in zip(clocks,(lambda i:False,lambda i:i%2==0,lambda i:True)):
            sink=[];selected=[]
            for i,draws in enumerate(clock.request_draws):
                sink.append((i,*map(float,draws)))
                if select(i):selected.append(float(draws[2]))
            sinks.append(sink);responses.append(selected)
        self.assertEqual(sinks[0],sinks[1]);self.assertEqual(sinks[1],sinks[2])
        self.assertEqual(len(sinks[0]),12)
        self.assertEqual(responses[0],[])
        self.assertEqual(responses[1],responses[2][::2])
        self.assertEqual([c.request_events_sha256 for c in clocks],[clocks[0].request_events_sha256]*3)

    def test_keyed_mode_rejects_conditional_legacy_response_rng(self):
        with self.assertRaisesRegex(ValueError,'request_response_sampler'):
            F.run(quiet_scenario(request_randomness=True,response_sampler=lambda rng:(120,False)),1,7,days=1)

    def test_cached_pure_economics_preserves_every_result_and_financial_trace(self):
        values=json.loads((ROOT/'deploy/manager.json').read_text())
        plain_trace=[];cached_trace=[]
        common=quiet_scenario()
        plain=F.run(common|{'cache_economics':False,'trace_sink':plain_trace},1,7,days=1,values=values)
        cached=F.run(common|{'cache_economics':True,'trace_sink':cached_trace},1,7,days=1,values=values)
        self.assertEqual(plain,cached)
        self.assertEqual(plain_trace,cached_trace)
        self.assertEqual(cached['ledger_gap_wei'],0)

    def test_price_changes_preserve_cached_and_uncached_execution(self):
        values=json.loads((ROOT/'deploy/manager.json').read_text())
        sc=quiet_scenario(gwei=lambda day:.15 if day==0 else .45)
        plain=F.run(sc|{'cache_economics':False},1,7,days=2,values=values)
        cached=F.run(sc|{'cache_economics':True},1,7,days=2,values=values)
        self.assertEqual(plain,cached)

    def test_removed_fresh_configuration_cannot_be_silently_reinterpreted(self):
        historical=json.loads((ROOT/'docs/receipts/manager-r2-closeout.json').read_text())['managerValues']
        with self.assertRaisesRegex(ValueError,'pinned revision'):F.configured_state(150000000,historical)
        from manager_operating_assessment import qualify_costs
        old=json.loads((ROOT/'docs/receipts/manager-r2-cost-calibration.json').read_text())
        with self.assertRaisesRegex(ValueError,'measured-compensation'):qualify_costs(old,True)


if __name__=='__main__':unittest.main()
