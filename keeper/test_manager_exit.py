"""Pure observed-state/encoding checks; real contract execution is in the focused fork/UI batch."""
import unittest
from types import SimpleNamespace

from keeper import FWA, local_actor_rpc, manager_exit_steps, operation_target, to_cast, validate_manager_exit_pending

OWNER = '0x1111111111111111111111111111111111111111'
OTHER = '0x2222222222222222222222222222222222222222'


def state(**changes):
    return SimpleNamespace(**(dict(account_owner=OWNER, winding_down=False, open_positions=1,
        idle_packs=0, recovery_packs=0, pending_receipts=0, fee_credit=0, free=10**18) | changes))


class ManagerExitTests(unittest.TestCase):
    def test_pending_growth_foreign_calls_and_ownership_changes_cannot_gain_exit_replacements(self):
        bad = [(OTHER, ['build(uint256,uint256[],uint256,bytes32)', '3', '[1]', '0', '0x'+'00'*32]),
               (OWNER, ['recoverLiquidate(uint256)', '1']),
               (OTHER, ['withdraw(address,uint256)', OTHER, '1']),
               (FWA, ['processAcquisitions(uint256)', '17']),
               (OTHER, ['setExiting(bool)', 'false']),
               (OTHER, ['recoverUnlist(uint256[])', '['+','.join(map(str, range(17)))+']']),
               (OTHER, ['harvest(uint256[],uint256)', '[]', '1']),
               (OTHER, ['recoverLiquidate(uint256)', '1', '--value', '1'])]
        for target, args in bad:
            pending = {'to': target, 'args': args, 'hashes': ['already-signed'], 'nonce': 4}
            before = repr(pending)
            with self.assertRaisesRegex(ValueError, 'outside this owner-paid'):
                validate_manager_exit_pending(state(), OTHER, OWNER, pending)
            self.assertEqual(repr(pending), before)
        with self.assertRaisesRegex(ValueError, 'current owner'):
            validate_manager_exit_pending(state(account_owner=OTHER), OTHER, OWNER, None)

    def test_pending_bounded_owner_exit_calls_can_resume(self):
        steps = [('setExiting', True), ('sync', [7], 0), ('unlist', [7]), ('liquidate', 16),
                 ('harvest', []), ('withdraw', OWNER, 17), ('processAcquisitions', 16)]
        for step in steps:
            pending = {'to': operation_target(OTHER, step),
                       'args': list(map(str, to_cast(step, caller_funded=True)))}
            validate_manager_exit_pending(state(), OTHER, OWNER, pending)

    def test_wrong_owner_cannot_start_or_withdraw(self):
        for exiting in (False, True):
            with self.assertRaisesRegex(ValueError, 'current owner'):
                manager_exit_steps(state(winding_down=exiting, open_positions=0), OTHER, [])

    def test_owner_pauses_reinvestment_before_any_exit_work(self):
        self.assertEqual(manager_exit_steps(state(), OWNER, [('unlist', [7])]), [('setExiting', True)])
        self.assertEqual(to_cast(('setExiting', True), caller_funded=True), ['setExiting(bool)', 'true'])

    def test_exit_never_mints_relists_checkpoints_or_burns_tokens(self):
        maintenance = [('build', 3, [21]), ('renew', [], [], []), ('list', [21]), ('checkpoint', 0),
                       ('burnTokens', []), ('sync', [4], 0), ('unlist', [7]), ('liquidate', 16)]
        steps = manager_exit_steps(state(winding_down=True), OWNER, maintenance)
        self.assertEqual(steps, maintenance[-3:])
        self.assertEqual(to_cast(steps[0], caller_funded=True), ['recover(uint256[],uint256)', '[4]', 0])
        self.assertEqual(to_cast(steps[1], caller_funded=True), ['recoverUnlist(uint256[])', '[7]'])
        self.assertEqual(to_cast(steps[2], caller_funded=True), ['recoverLiquidate(uint256)', 16])

    def test_recovery_inventory_and_pending_receipts_prevent_premature_completion(self):
        for changes in ({'idle_packs': 1}, {'recovery_packs': 1}, {'pending_receipts': 1}):
            s = state(winding_down=True, open_positions=0, **changes)
            self.assertNotIn('withdraw', [x[0] for x in manager_exit_steps(s, OWNER, [('sync', [], 0)])])

    def test_collects_credit_then_withdraws_exact_actual_cash_to_owner(self):
        self.assertEqual(manager_exit_steps(state(winding_down=True, open_positions=0, fee_credit=72), OWNER, []), [('harvest', [])])
        s = state(winding_down=True, open_positions=0, free=10**18 + 17)
        final = manager_exit_steps(s, OWNER, [])
        self.assertEqual(final, [('withdraw', OWNER, 10**18 + 17)])
        self.assertEqual(to_cast(final[0], caller_funded=True), ['withdraw(address,uint256)', OWNER, 10**18 + 17])

    def test_empty_account_needs_no_foreign_journal_or_checkpoint_work(self):
        self.assertEqual(manager_exit_steps(state(winding_down=True, open_positions=0, free=0), OWNER,
                                           [('sync', [], 0), ('checkpoint', 0)]), [])

    def test_protocol_processing_has_one_fixed_target_and_bounded_call(self):
        step = ('processAcquisitions', 16)
        self.assertEqual(operation_target(OTHER, step), FWA)
        self.assertEqual(to_cast(step, caller_funded=True), ['processAcquisitions(uint256)', 16])
        self.assertEqual(operation_target(OTHER, ('withdraw', OWNER, 1)), OTHER)
        for bad in [('processAcquisitions', 0), ('processAcquisitions', 17)]:
            with self.assertRaises(ValueError):
                to_cast(bad, caller_funded=True)
        with self.assertRaises(ValueError):
            to_cast(step)

    def test_unlocked_actor_urls_are_only_local_http(self):
        for url in ['http://127.0.0.1:18661', 'http://localhost:8545', 'http://[::1]:8545']:
            self.assertTrue(local_actor_rpc(url))
        for url in ['https://mainnet.gateway.tenderly.co', 'http://localhost.evil:8545', 'https://127.0.0.1:8545']:
            self.assertFalse(local_actor_rpc(url))


if __name__ == '__main__':
    unittest.main()
