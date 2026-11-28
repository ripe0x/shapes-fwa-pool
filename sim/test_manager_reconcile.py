"""Current real trace reconciliation and rejection of historical fixed/Fresh inputs."""
import copy
import json
from pathlib import Path
import unittest
import manager_reconcile as R

ROOT=Path(__file__).resolve().parent.parent
TRACE=ROOT/'sim/out/manager-measured-final-reuse-trace.jsonl'


class ManagerMeasuredReconcileTest(unittest.TestCase):
    def test_actual_meter_event_derives_first_build_payment(self):
        rows=[json.loads(line) for line in TRACE.read_text().splitlines()]
        row=next(row for row in rows if row['action']=='build')
        params=R.parameters(row['params']);state=R.configured_state(row['baseFee'],params)
        q=state.gas_schedule
        count=len(row['input']['ids']);units=row['input']['units']
        allowance=q['build']+count*(q['build_pack']+R.policy.shape_count(units)*q['build_shape']+q['listed'])
        frames=row['state']['measuredWork'];frame=frames[0] if isinstance(frames,list) else frames
        measured=min(frame['measuredGas'],allowance)
        expected=(measured+params['gasSchedule']['overhead'])*frame['gasPrice']*(10000+params['payMarkupBps'])//10000+2*count*params['workFeeWei']
        self.assertGreater(frame['measuredGas'],0)
        self.assertEqual(R.measured_offer(row,state,allowance,2*count),expected)
        self.assertEqual(frame['paid'],expected)
        altered=copy.deepcopy(row)
        fake=altered['state']['measuredWork'];fake=fake[0] if isinstance(fake,list) else fake
        fake['gasAllowance']-=1
        with self.assertRaisesRegex(ValueError,'independently derived'):R.measured_offer(altered,state,allowance,2*count)

    def test_real_reuse_owner_cycle_closes_every_wei_without_remint(self):
        rows=[json.loads(line) for line in TRACE.read_text().splitlines()]
        result=R.replay(TRACE)
        self.assertEqual(result['status'],'PASS',result['failures'])
        self.assertEqual(result['compensation_mode'],'bounded-measured-v1')
        self.assertEqual(result['gross_primary_fees_accrued_wei'],3000000000000000)
        self.assertEqual(result['backing_lost_wei'],210000000000000000)
        self.assertEqual(result['owner_withdrawn_wei'],rows[0]['input']['deployBalance']-
            3000000000000000-210000000000000000-result['keeper_paid_wei']+result['external_fee_income_wei'])
        self.assertEqual(result['final_balance_wei'],0)
        self.assertTrue({'acquisition','bid','returned','list','unlist','withdraw'}<={row['action'] for row in rows})

    def test_old_fixed_fresh_trace_is_not_reinterpreted(self):
        with self.assertRaisesRegex(ValueError,'historical evidence stays pinned'):
            R.replay(ROOT/'sim/out/manager-fresh-trace.jsonl')


if __name__=='__main__':unittest.main()
