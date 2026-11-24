"""Real entrypoint/argparse contract; no signer secrets, successful RPC substitutions or transactions."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
ACTOR = '0x1111111111111111111111111111111111111111'


def launch(**settings):
    env = {k: v for k, v in os.environ.items() if not k.startswith('KEEPER_') and k not in ('VAULT', 'FACTORY')}
    env.update(PATH=str(Path(sys.executable).parent) + os.pathsep + env['PATH'], KEEPER_ARGS='--help', **settings)
    return subprocess.run(['sh', 'keeper/entrypoint.sh'], cwd=ROOT, env=env, capture_output=True, text=True)


class EntrypointTests(unittest.TestCase):
    def test_factory_alone_reaches_real_argument_parser(self):
        result = launch(FACTORY=ACTOR, KEEPER_FROM=ACTOR)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--factory', result.stdout)

    def test_both_products_still_reach_parser(self):
        self.assertEqual(launch(VAULT=ACTOR, FACTORY=ACTOR, KEEPER_FROM=ACTOR).returncode, 0)

    def test_existing_mount_paths_are_forwarded_without_reading_or_creating_signing_material(self):
        # --help exits before signing. Public existing text supplies only readable-path validation.
        path = str(ROOT / 'keeper/requirements.txt')
        result = launch(FACTORY=ACTOR, KEEPER_KEYSTORE_PATH=path, KEEPER_PASSWORD_FILE=path)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_secret_environment_materialization_is_rejected(self):
        result = launch(FACTORY=ACTOR, KEEPER_FROM=ACTOR, KEEPER_KEYSTORE_JSON='{}')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('materialization is disabled', result.stderr)
        self.assertNotIn('{}', result.stderr)

    def test_missing_zero_or_malformed_accounts_fail_before_startup(self):
        self.assertNotEqual(launch(KEEPER_FROM=ACTOR).returncode, 0)
        for address in ['0x' + '0' * 40, '0x12', '0x' + 'z' * 40]:
            self.assertNotEqual(launch(FACTORY=address, KEEPER_FROM=ACTOR).returncode, 0)

    def test_unreadable_or_conflicting_signer_inputs_fail(self):
        self.assertNotEqual(launch(FACTORY=ACTOR, KEEPER_KEYSTORE_PATH='/nonexistent', KEEPER_PASSWORD_FILE='/nonexistent').returncode, 0)
        self.assertNotEqual(launch(FACTORY=ACTOR, KEEPER_FROM=ACTOR, KEEPER_KEYSTORE_PATH='keeper/requirements.txt').returncode, 0)


if __name__ == '__main__':
    unittest.main()
