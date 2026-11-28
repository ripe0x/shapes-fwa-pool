"""Pure simulator/index projection checks. No external service responses are fabricated."""
import tempfile
import unittest
from pathlib import Path

from forward import bounded_policy_positions, policy
from keeper import plan_key
from index import EventIndex
from vault import ACTIVE, ALLOCATED, OWED, SETTLED, WITHDRAWN, Position, Vault


class CandidateProjectionTest(unittest.TestCase):
    def test_exact_preflight_reaches_two_claims_after_shorter_syncs_cannot_pay(self):
        state = policy.State(now=10_000, gas_price=1, base_fee=1, gas_ceiling=1,
            max_tip=0, markup_bps=0, share_bps=2500, k=10**18, backing=0,
            min_edge_bps=100, mint_fee=10**15, settlement_window=3600,
            blackout=False, queue_drained=True, checkpoint_done_this_interval=False,
            listings=[policy.Listing(i, ACTIVE, pending_fees=500_000) for i in (1, 2)],
            own_journal_pending=True, completed_prefix=2, open_positions=100, routine_budget=1_000_000)
        alternatives = [step for step in policy.plan(state) if step[0] == 'sync']
        v = Vault(seed=0, balance=0, routine_budget=1_000_000)
        v.positions = {i: Position(3, 1, pending_fees=500_000) for i in (1, 2)}
        base = policy.Q['sync'] + 2 * policy.Q['journal'] + 2 * policy.Q['selected']
        failed = set()
        for step in alternatives:
            gas, credit, claims = v.sync_fee_plan(step[1], 0, base, 0,
                                                 lambda g, u: policy.quote(state, g, u), 2500)
            if sum(v.positions[i].pending_fees for i in claims) + credit < policy.quote(state, gas):
                failed.add(plan_key(step))
            else:
                break
        self.assertEqual([step for step in alternatives if plan_key(step) not in failed], [('sync', [1, 2], 0)])
        self.assertEqual((gas, claims), (729_000, [1, 2]))

    def test_model_uses_the_index_bounds_order_and_owed_rotation(self):
        v = Vault(seed=1, balance=1)
        returned, selected = {}, {}
        with tempfile.TemporaryDirectory() as directory:
            index = EventIndex(Path(directory) / 'book.sqlite', 1, '0x' + '11' * 20, 1)
            for i in range(1, 701):
                state, status, allocated_at, owned = ACTIVE, ACTIVE, 0, False
                if 201 <= i <= 225:
                    status = ALLOCATED
                    selected[i] = 1000 + i
                    index.db.execute('INSERT INTO selected VALUES (?,?,?)', (str(i), selected[i], i))
                elif 301 <= i <= 325:
                    state = status = ALLOCATED
                    allocated_at = 1000 + i
                elif 401 <= i <= 425:
                    state, status = OWED, SETTLED
                elif 501 <= i <= 525:
                    state, status, owned = ALLOCATED, SETTLED, True
                    returned[i] = (1000 + i, i)
                    index.db.execute('INSERT INTO returned VALUES (?,?,?,?)', (str(i), 1000 + i, i, 1))
                elif 601 <= i <= 625:
                    status = WITHDRAWN
                    v.receipts[i] = (2, 1, 0)
                    index.db.execute('INSERT INTO receipts VALUES (?,?,?)', (str(i), 2, '1'))
                debt = i % 5
                v.positions[i] = Position(3, 1, status, state=state, allocated_at=allocated_at,
                                          fee_debt=debt, pack_owned=owned)
                index.db.execute('INSERT INTO positions VALUES (?,?,?,?,?,?,?)',
                    (str(i), str(i), '1', '1', str(debt).zfill(78), allocated_at, state))
            index.db.commit()
            cursor = ''
            seen_owed = set()
            for _ in range(3):
                ids, cursor = bounded_policy_positions(v, 10_000, 3600, returned, selected, cursor)
                active, terminal = index.candidates(16, 16, 10_000, 3600)
                self.assertEqual(ids, list(dict.fromkeys(terminal + active)))
                self.assertEqual(cursor, index.meta('owed_after', ''))
                self.assertLessEqual(len(ids), 16 * 5)
                seen_owed.update(i for i in ids if v.positions[i].state == OWED)
            self.assertEqual(seen_owed, set(range(401, 426)))
            self.assertGreater(len(v.positions), len(ids))
            index.db.close()


if __name__ == '__main__':
    unittest.main()
