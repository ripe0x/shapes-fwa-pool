#!/usr/bin/env python3
"""Prepare the exact measured-work amendment; execute only after its explicit owner approval."""
import argparse
import fcntl
import importlib.util
import json
from pathlib import Path
import re
import tempfile
import time

if not __debug__:
    raise RuntimeError('Optimized Python disables the batch assertions; refuse preparation or execution')

import efficient_journal_rehearsal as batch
import policy

ROOT = Path(__file__).resolve().parent.parent
AMENDMENT = ROOT / 'docs/receipts/efficient-journal-candidate-amendment.json'
BASELINE = Path('/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-journal-baseline-eqm_12s8/results.json')
BASE_HASH = '1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd'
RECOVERY = ROOT / 'docs/receipts/efficient-journal-recovery-review.py'


def prepare():
    assert batch.digest(batch.PLAN) == BASE_HASH
    plan = json.loads(batch.PLAN.read_text())
    baseline = batch.load_baseline(str(BASELINE), BASE_HASH)
    sources = {p: batch.digest(ROOT / p) for p in batch.SOURCE_PATHS}
    for path, expected in plan['source_sha256'].items():
        if path not in ('src/VaultLib.sol', 'keeper/policy.py'):
            assert sources[path] == expected, path
    sources['keeper/efficient_journal_candidate.py'] = batch.digest(__file__)
    sources[str(RECOVERY.relative_to(ROOT))] = batch.digest(RECOVERY)
    values = dict(sync=85_000, journal=22_000, journal_tail=110_000, distribution_proof=80_000, pack=325_000)
    names = dict(sync='SYNC', journal='JOURNAL', journal_tail='REQUIRED_TAIL',
                 distribution_proof='DISTRIBUTION_PROOF', pack='PACK')
    lib = (ROOT / 'src/VaultLib.sol').read_text()
    for name, value in values.items():
        assert policy.Q[name] == value
        matched = re.search(r'Q_' + names[name] + r'\s*=\s*([\d_]+)', lib)
        assert matched and int(matched[1].replace('_', '')) == value, name
    artifacts = batch.artifact_templates()
    assert set(artifacts) == set(plan['artifact_templates_sha256'])
    greedy = 'out/ForkKeeperPolicy.t.sol/PolicyGreedy.json'
    assert artifacts[greedy] == plan['artifact_templates_sha256'][greedy]
    versions = {tool: batch.raw(tool, '--version') for tool in ('forge', 'cast', 'anvil')}
    assert versions == plan['tool_versions'], 'approved toolchain changed'
    for path in artifacts:
        runtime = json.loads((ROOT / path).read_text())['deployedBytecode']['object'].removeprefix('0x')
        assert len(runtime) // 2 <= batch.MAX_CODE
    return dict(status='PREPARED; NEEDS EXACT OWNER AMENDMENT BEFORE BROADCAST',
                original_approved_plan_sha256=BASE_HASH, baseline_results=str(BASELINE),
                baseline_results_sha256=batch.digest(BASELINE), baseline_broadcasts=baseline['broadcasts'],
                baseline_external_value_wei=baseline['external_value_wei'],
                source_sha256=sources, artifact_templates_sha256=artifacts,
                tool_versions=versions,
                quotes=values, one_candidate_only=True, owned_pid=baseline['pid'], endpoint=batch.RPC,
                maximum_total_broadcast_transactions=540, maximum_total_external_value_wei=32 * batch.E,
                initial_funding_wei=83 * batch.E // 10, added_funding_wei=0, topups=0,
                candidate_planned_transactions=199, included_repair_transactions=20,
                amendment='One 80k fixed component for the actual qualified distribution-only proof; otherwise the original candidate actions, actors, endpoint, funding and total limits stay the same. Holder tails use 110k; full/own work 85k; each completed record 22k; pack 325k.',
                predicate_effect='No eligibility predicate, storage, Params or ABI change. Higher proof expense can disqualify marginal distributions; lower cycle quote changes numerical edge/backing floors. Request/deployment/unwind charges are unchanged.',
                operating_adapters='Pin pending timestamp to parent+1; observe genuine zero-offer candidate/preflight decline; log existing snapshots; at most 3 read-only retries for the recorded HTTP2 transport error. No false service answers or send-check overrides.',
                limitations=['Successful foreign paid receipts remain unmeasured.',
                             'Current supported quotes are a candidate, not universal keeper profit or acceptable holder return.',
                             'O2, sustained funding and repeated active-fee harvest expense remain acceptance blockers.'])


def normalized_runtime(path, address, executor):
    artifact = json.loads((ROOT / path).read_text())['deployedBytecode']
    expected = artifact['object'].removeprefix('0x')
    actual = executor.cast('code', address).removeprefix('0x')
    assert len(actual) == len(expected)
    ranges = [r for refs in artifact.get('immutableReferences', {}).values() for r in refs]
    ranges += [r for names in artifact.get('linkReferences', {}).values() for refs in names.values() for r in refs]
    for r in ranges:
        a, b = 2 * r['start'], 2 * (r['start'] + r['length'])
        expected, actual = expected[:a] + '0' * (b-a) + expected[b:], actual[:a] + '0' * (b-a) + actual[b:]
    assert actual.lower() == expected.lower(), 'deployed runtime differs from frozen compiler artifact'


def execute(amendment):
    with (BASELINE.parent / 'candidate-execution.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('The single approved candidate is already running') from exc
        _execute_locked(amendment)


def _execute_locked(amendment):
    plan = json.loads(batch.PLAN.read_text())
    baseline = batch.load_baseline(str(BASELINE), BASE_HASH)
    baseline['_path'] = str(BASELINE)
    work = Path(tempfile.mkdtemp(prefix='efficient-journal-amended-candidate-'))
    spec = importlib.util.spec_from_file_location('reviewed_recovery', RECOVERY)
    recovery = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(recovery)
    runner = batch.LocalBatch(plan, work, candidate=amendment, baseline=baseline)
    runner.pid = baseline['pid']
    runner.state['approved_amendment_sha256'] = batch.digest(AMENDMENT)
    original = runner.inclusion
    def pinned():
        parent = runner.rpc('eth_getBlockByNumber', 'latest', False)
        runner.rpc('evm_setNextBlockTimestamp', hex(batch.num(parent['timestamp']) + 1))
        return original()
    runner.inclusion = pinned
    recovery.install_zero_offer_decline_observation(runner, batch)
    recovery.install_future_snapshot_id_log(runner)
    dispatch = runner.ordinary_dispatch
    def retry_transport(sig, args, absent=False):
        for attempt in range(3):
            counters = (runner.broadcasts, runner.external_value, len(runner.actions))
            old = len(runner.state.get('ordinary_dispatches', []))
            try:
                return dispatch(sig, args, absent=absent)
            except RuntimeError:
                recent = runner.state.get('ordinary_dispatches', [])[old:]
                if attempt == 2 or 'too_many_data_frames' not in str(recent):
                    raise
                assert counters == (runner.broadcasts, runner.external_value, len(runner.actions))
                runner.state.setdefault('transport_retries', []).append(dict(case=len(runner.actions), attempt=attempt + 1, counters_unchanged=True))
                runner.save()
                time.sleep(2 * (attempt + 1))
    runner.ordinary_dispatch = retry_transport
    deploy = runner.deploy
    def checked_deploy():
        deploy()
        normalized_runtime('out/PackVault.sol/PackVault.json', runner.vault, runner)
        runner.state['deployed_vault_normalized_runtime_matches'] = True
        runner.save()
    runner.deploy = checked_deploy
    print('Approved amended candidate evidence ' + str(work), flush=True)
    try:
        runner.run()
    except BaseException as exc:
        runner.state.update(status='failed', global_phase='candidate_failed', failure=str(exc), node_preserved=True)
        runner.save()
        raise


def main():
    p = argparse.ArgumentParser(description=__doc__)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument('--prepare', action='store_true')
    group.add_argument('--execute-approved-amendment', action='store_true')
    p.add_argument('--approved-amendment-sha256')
    args = p.parse_args()
    current = prepare()
    if args.prepare:
        if AMENDMENT.exists():
            assert json.loads(AMENDMENT.read_text()) == current, 'preserve and reconcile a changed descriptor'
        AMENDMENT.write_text(json.dumps(current, indent=2) + '\n')
        print(str(AMENDMENT) + ' sha256=' + batch.digest(AMENDMENT))
        return
    assert args.approved_amendment_sha256 and batch.digest(AMENDMENT) == args.approved_amendment_sha256
    assert json.loads(AMENDMENT.read_text()) == current
    execute(current)


if __name__ == '__main__':
    main()
