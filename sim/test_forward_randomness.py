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
    return F.Scenario(manager=True,volume=F.const(0),timed=True,start_timestamp=1795521275,poll_seconds=60,
        receipt_seconds=36,replay_events=events,replay_period_seconds=3*F.DAY,foreign_pool_weight=1.0,
        exempt=True,gwei=.15,deposit_wei=10**18,mint_fee_wei=5*10**14,exit_all=True,exit_days=1,
        user_gas_proxy=dict(create=606172,setExiting=53214,withdraw=38904,unlist=1085668,
            liquidate=593594,recover_sync=199047,processAcquisitions=115941,harvest=300000),
        holder_rescue_sync=True,self_serve_exits=True,**changes)


def keyed_path(seed):
    return F.run(scenario(request_randomness=True,request_response_sampler=lambda u:(120,False)),
        1,seed,days=1,values=json.loads((ROOT/'deploy/manager.json').read_text()))


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
        values=json.loads((ROOT/'deploy/manager.json').read_text())
        sinks=[];response_uniforms=[];results=[]
        # Different account configurations deliberately consume different selected responses.
        for mask in (0,8):
            sink=[];responses=[]
            def response(u):
                responses.append(u)
                return 120,False
            results.append(F.run(scenario(request_randomness=True,randomness_sink=sink,
                request_response_sampler=response),1,7,days=1,values=values|{'packUnitsMask':mask}))
            sinks.append(sink);response_uniforms.append(responses)
        self.assertEqual(sinks[0],sinks[1])
        self.assertEqual(len(sinks[0]),12)
        self.assertEqual(response_uniforms[0],[])
        self.assertGreater(len(response_uniforms[1]),0)
        self.assertEqual(results[0]['request_events_sha256'],results[1]['request_events_sha256'])
        expected={row[2] for row in sinks[1]}
        self.assertTrue(all(u in expected for u in response_uniforms[1]))
        # A path repeated after another configuration is exactly the same path.
        repeated=F.run(scenario(request_randomness=True,request_response_sampler=lambda u:(120,False)),
            1,7,days=1,values=values|{'packUnitsMask':8})
        self.assertEqual(results[1],repeated)

    def test_keyed_mode_rejects_conditional_legacy_response_rng(self):
        with self.assertRaisesRegex(ValueError,'request_response_sampler'):
            F.run(scenario(request_randomness=True,response_sampler=lambda rng:(120,False)),1,7,days=1)

    def test_cached_pure_economics_preserves_every_result_and_financial_trace(self):
        values=json.loads((ROOT/'deploy/manager.json').read_text())
        for mode in (0,1):
            plain_trace=[];cached_trace=[]
            common=scenario(response_sampler=lambda rng:(120,bool(rng.integers(2))))
            plain=F.run(common|{'cache_economics':False,'trace_sink':plain_trace},1,7,days=1,
                values=values|{'renewalMode':mode})
            cached=F.run(common|{'cache_economics':True,'trace_sink':cached_trace},1,7,days=1,
                values=values|{'renewalMode':mode})
            self.assertEqual(plain,cached)
            self.assertEqual(plain_trace,cached_trace)
            self.assertEqual(cached['ledger_gap_wei'],0)


if __name__=='__main__':unittest.main()
