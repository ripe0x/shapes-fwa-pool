#!/usr/bin/env python3
"""Current factory-only keeper start, discovery, restart and owner exit on an owned fork."""
import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak, to_checksum_address
from config import PARAMS_T, guarded_call, tuple_arg
from rehearse_manager_r2 import PUBLIC, FWA, SHAPES, PACKS, ROOT, integer, request, sha, sources


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--port', type=int, default=18741)
    a = ap.parse_args()
    if not a.execute or os.environ.get('CANDIDATE_RUN') != '1':
        raise SystemExit('Plan: owned Tenderly mainnet fork31337; factory-only deployment; clean actors; '
                         '0.5ETH manager; production entrypoint discovery/build/restart; zero-budget '
                         'owner exit with0.01ETH wallet cap. Requires --execute and CANDIDATE_RUN=1.')
    path = ROOT / 'docs/receipts/manager-keeper-readiness.json'
    assert not path.exists(), 'preserve an existing readiness attempt instead of overwriting it'
    for port in (a.port, a.port + 1):
        with socket.socket() as available:
            available.bind(('127.0.0.1', port))
    live = json.loads((ROOT / 'docs/receipts/manager-final-live-observation.json').read_text())
    work = Path(tempfile.mkdtemp(prefix='shapes-manager-operations-'))
    url = f'http://127.0.0.1:{a.port}'
    env = dict(os.environ, PATH=str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH'], PYTHONUNBUFFERED='1')
    for key in list(env):
        if key == 'VAULT' or key.startswith('KEEPER_KEYSTORE') or key.startswith('KEEPER_PASSWORD'):
            env.pop(key)
    frozen = sources()
    keeper_paths = ['keeper/' + p for p in ('keeper.py', 'policy.py', 'config.py', 'tx.py', 'index.py', 'entrypoint.sh', 'Dockerfile', 'requirements.txt')]
    keeper_hashes = {p: sha(ROOT / p) for p in keeper_paths}
    report = dict(status='RUNNING', command=[sys.executable, *sys.argv], rpc=url, chainId=31337,
                  forkBlock=live['block'], forkHash=live['blockHash'], workDirectory=str(work),
                  contractSourceSha256=frozen, keeperSourceSha256=keeper_hashes,
                  scriptSha256=sha(__file__), helperSha256=sha(ROOT / 'keeper/rehearse_manager_r2.py'),
                  transactions=[], steps=[], publicTransactions=0,
                  sharedVaultDeployed=False, additionalManagerFundingWei=0,
                  productionEnvironmentTemplate=dict(FACTORY='<postflight-confirmed deployed manager factory>', RPC_URL=PUBLIC,
                      KEEPER_KEYSTORE_PATH='<existing read-only encrypted keystore mount>',
                      KEEPER_PASSWORD_FILE='<existing read-only password mount>', POLL_SECONDS='60', HEALTH_PORT='8788'),
                  limits=['Local unlocked actors only; encrypted-keystore/hardware transport is untested.',
                          'Production Fly launch and public factory deployment are not performed.',
                          'Unselected one-pack lifecycle; authenticated VRF renewal and gas curves retain existing gaps.',
                          'Container compatibility is reused at its original revision, not rerun here.'])
    started = time.monotonic()
    worker = None

    def save():
        path.write_text(json.dumps(report, indent=1) + '\n')

    def command(*args, environment=None):
        r = subprocess.run(list(map(str, args)), cwd=ROOT, env=environment or env, text=True, capture_output=True)
        if r.returncode:
            raise RuntimeError(' '.join(map(str, args[:3])) + ': ' + r.stdout[-2500:] + r.stderr[-2500:])
        return r.stdout.strip()

    def cast(*args):
        return command('cast', *args, '--rpc-url', url)

    def rpc(method, *args):
        return request(url, method, *args)

    def call(target, sig, *args):
        return cast('call', target, sig, *args)

    def number(target, sig, *args):
        return integer(call(target, sig, *args))

    def boundary():
        assert integer(cast('chain-id')) == 31337 and rpc('web3_clientVersion').lower().startswith('anvil/')
        info = rpc('anvil_nodeInfo')['forkConfig']
        assert info['forkUrl'] == PUBLIC and int(info['forkBlockNumber']) == live['block']

    def record(operation, tx_hash):
        tx = rpc('eth_getTransactionByHash', tx_hash)
        receipt = rpc('eth_getTransactionReceipt', tx_hash)
        assert receipt and int(receipt['status'], 16) == 1, operation + ' failed'
        assert int(tx['chainId'], 16) == 31337 and int(tx['gas'], 16) <= 16_777_216
        header = rpc('eth_getBlockByHash', receipt['blockHash'], False)
        item = dict(operation=operation, transaction=tx, receipt=receipt,
                    blockBaseFeeWei=int(header['baseFeePerGas'], 16),
                    gasCostWei=int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16))
        if not any(t['transaction']['hash'] == tx_hash for t in report['transactions']):
            report['transactions'].append(item)
            save()
        return item

    def send(sender, target, sig, *args, value=0):
        boundary()
        sig, args = guarded_call(sig, args, lambda view, *vals: call(target, view, *vals).split()[0])
        fee = int(rpc('eth_getBlockByNumber', 'pending', False)['baseFeePerGas'], 16)
        flags = ['--gas-price', 2 * fee + 50_000_000, '--priority-gas-price', 50_000_000]
        estimate = integer(cast('estimate', target, sig, *args, '--from', sender, '--value', value, *flags))
        gas = (estimate * 5 + 3) // 4
        assert gas <= 16_777_216
        if sender == actors['owner'] and not sig.startswith('create('):
            report['ownerDirectSignedUpperWei'] += gas * (2 * fee + 50_000_000) + value
            assert report['ownerDirectSignedUpperWei'] < 10**16
        receipt = json.loads(cast('send', target, sig, *args, '--from', sender, '--unlocked', '--value', value,
                                  '--gas-limit', gas, *flags, '--json'))
        return record(sig.split('(')[0], receipt.get('data', receipt)['transactionHash'])

    def account():
        return dict(cashWei=integer(cast('balance', manager)), feeCreditWei=number(FWA, 'feeCredit(address)(uint256)', manager),
                    **{k: number(manager, k + '()(uint256)') for k in ('openListingCount', 'idlePackCount', 'recoveryPackCount', 'pendingReceipts')})

    data = work / 'keeper'; data.mkdir()
    state_path = data / 'keeper-state.json'

    def stored():
        return json.loads(state_path.read_text()) if state_path.exists() else None

    def health():
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{a.port + 1}/health', timeout=3) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            return json.load(error)
        except OSError:
            return None

    def start_keeper(label):
        nonlocal worker
        log = open(work / (label + '.log'), 'w')
        keeper_env = env | dict(FACTORY=factory, KEEPER_FROM=actors['keeper'], RPC_URL=url,
                               POLL_SECONDS='2', HEALTH_PORT=str(a.port + 1),
                               KEEPER_ARGS=f'--state {state_path} --index {data} --max-steps 1 --pending-timeout 30')
        assert 'VAULT' not in keeper_env
        worker = subprocess.Popen(['sh', 'keeper/entrypoint.sh'], cwd=ROOT, env=keeper_env, stdout=log, stderr=subprocess.STDOUT)
        report['steps'].append(dict(step=label, pid=worker.pid, factoryOnly=True, log=str(work / (label + '.log'))))

    def stop_keeper():
        nonlocal worker
        if worker is not None:
            worker.terminate(); worker.wait(30); worker = None

    def wait_for(label, check, seconds=900):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if worker is not None and worker.poll() is not None:
                raise RuntimeError('owned keeper exited: ' + label)
            if check():
                return
            rpc('evm_mine'); time.sleep(2)
        raise RuntimeError('timed out: ' + label)

    node = subprocess.Popen(['anvil', '--host', '127.0.0.1', '--port', str(a.port), '--chain-id', '31337', '--accounts', '0', '--silent',
                             '--fork-url', PUBLIC, '--fork-block-number', str(live['block']), '--retries', '30', '--fork-retry-backoff', '5000',
                             '--base-fee', '150000000', '--gas-limit', '16777216', '--enable-tx-gas-limit'],
                            stdout=open(work / 'anvil.log', 'w'), stderr=subprocess.STDOUT, start_new_session=True)
    report['ownedNodePid'] = node.pid
    actors = {k: to_checksum_address(keccak(text=f'manager-operations-{live["block"]}-{k}')[-20:]) for k in ('deployer', 'owner', 'keeper', 'queue-payer')}
    report.update(actors=actors, ownerDirectSignedUpperWei=0)
    save()
    try:
        for _ in range(180):
            assert node.poll() is None, 'owned Anvil exited'
            try:
                boundary(); break
            except (RuntimeError, OSError):
                time.sleep(1)
        else:
            raise RuntimeError('owned fork startup timed out')
        assert rpc('eth_getBlockByNumber', hex(live['block']), False)['hash'] == live['blockHash']
        for name, target in [('FWA', FWA), ('Shapes', SHAPES), ('ShapePacks', PACKS)]:
            import hashlib
            assert hashlib.sha256(bytes.fromhex(rpc('eth_getCode', target, hex(live['block']))[2:])).hexdigest() == live['dependencies'][name]['runtimeSha256']
        initial = {}
        for name, actor in actors.items():
            assert cast('code', actor) == '0x' and integer(cast('nonce', actor)) == 0 and integer(cast('balance', actor)) == 0
            rpc('anvil_setBalance', actor, hex(10 * 10**18)); rpc('anvil_impersonateAccount', actor)
            initial[name] = integer(cast('balance', actor))
        report['initialActorBalancesWei'] = initial
        # A separate external actor owns historical queue timeout setup, before any manager exists.
        for _ in range(64):
            if number(FWA, 'unsettledAcquisitionCount()(uint256)') == 0:
                break
            seq = number(FWA, 'nextSequenceToProcess()(uint64)')
            req = number(FWA, 'requestIdAtSequence(uint64)(uint256)', seq)
            metadata = call(FWA, 'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)', req).splitlines()
            needed = max(0, integer(metadata[1]) + 1 - integer(cast('block-number')))
            assert needed <= 7201
            while needed:
                count = min(32, needed); rpc('anvil_mine', hex(count)); needed -= count
            send(actors['queue-payer'], FWA, 'processAcquisitions(uint256)', 16)
        assert number(FWA, 'unsettledAcquisitionCount()(uint256)') == 0
        report['deploymentOutput'] = command('script/deploy.sh', 'deploy/manager-factory.json', '--target', 'manager', '--broadcast',
                                            environment=env | dict(RPC_URL=url, FORGE_WALLET_ARGS='--unlocked --sender ' + actors['deployer']))
        deployment = json.loads((ROOT / 'broadcast/Deploy.s.sol/31337/run-latest.json').read_text())
        assert not any(t.get('contractName') == 'PackVault' for t in deployment['transactions'])
        factory = next(t['contractAddress'] for t in deployment['transactions'] if t.get('contractName') == 'PackManagerFactory')
        report['factory'] = factory
        for receipt in deployment['receipts']:
            record('deployment', receipt['transactionHash'])
        report['factoryPostflight'] = command(sys.executable, 'script/release.py', 'postflight-manager', factory, 'deploy/manager-factory.json', environment=env | dict(RPC_URL=url))
        start_keeper('factory-only start before creation')
        wait_for('empty factory healthy', lambda: bool(health() and health()['ok'] and health()['policy_count'] == 0))
        report['emptyFactoryHealth'] = health()
        stop_keeper()
        values = json.loads((ROOT / 'deploy/manager.json').read_text())
        funding = 5 * 10**17
        send(actors['owner'], factory, f'create(address,{PARAMS_T})', actors['owner'], tuple_arg(values), value=funding)
        manager = call(factory, 'managerAt(uint256)(address)', 0).split()[0]
        report['manager'] = manager
        assert account()['cashWei'] == funding
        report['managerPostflight'] = command(sys.executable, 'script/release.py', 'postflight-manager', factory, 'deploy/manager-factory.json', manager, actors['owner'], funding, environment=env | dict(RPC_URL=url))
        fee = number(SHAPES, 'mintFee()(uint256)')
        creator_before = number(SHAPES, 'pendingFees()(uint256)')
        now = int(rpc('eth_getBlockByNumber', 'latest', False)['timestamp'], 16)
        if now % 43200 >= 39600:
            rpc('evm_setNextBlockTimestamp', now + 43200 - now % 43200 + 60); rpc('evm_mine')
        start_keeper('factory-only discovery after creation')
        wait_for('factory discovery and paid build', lambda: bool(stored() and not stored()['pending'] and stored()['stats']['mined'] >= 1 and account()['openListingCount'] == 1))
        before = stored(); report['beforeRestart'] = before; report['firstBuildHealth'] = health()
        stop_keeper()
        discovery = data / f'discovered-{factory.lower()}.json'
        assert [x.lower() for x in json.loads(discovery.read_text())] == [manager.lower()]
        for entry in before['counted']:
            assert not entry.get('reorged')
            record(entry.get('function', entry['label']), entry['hash'])
        restart_at = int(time.time())
        start_keeper('persistent factory-only restart')
        wait_for('restarted keeper recognizes manager', lambda: bool(health() and health()['ok'] and health()['last_pass'] >= restart_at and health()['policy_count'] == 1))
        after = stored(); report['afterRestart'] = after; report['restartHealth'] = health()
        assert after['counted'] == before['counted'] and after['pending'] is None
        assert all(not v['pooled'] for v in report['restartHealth']['accounts'].values())
        stop_keeper()
        creator = number(SHAPES, 'pendingFees()(uint256)') - creator_before
        assert creator == 3 * fee
        mint_topic = '0x' + keccak(text='ShapeMinted(uint256,address,uint256,bytes32,uint256)').hex()
        minted = [log for item in report['transactions'] for log in item['receipt']['logs']
                  if log['address'].lower() == SHAPES.lower() and log['topics'] and log['topics'][0] == mint_topic]
        assert len(minted) == 3 and all(decode(['uint256', 'bytes32', 'uint256'], bytes.fromhex(log['data'][2:]))[0] == 10**16 for log in minted)
        report['paidPrimaryShapeMints'] = len(minted)
        send(actors['owner'], manager, f'setParams({PARAMS_T})', tuple_arg(values | dict(routineCapWei=0, routineRatePerDayWei=0)))
        assert call(manager, 'budget()(uint256)').strip() == '0'
        now = int(rpc('eth_getBlockByNumber', 'latest', False)['timestamp'], 16)
        rpc('evm_setNextBlockTimestamp', now + 13 * 3600); rpc('evm_mine')
        owner_state = work / 'owner-exit.json'
        owner_index = work / 'owner-index'; owner_index.mkdir()
        for attempt in range(12):
            reserved = json.loads(owner_state.read_text()).get('signed_upper_wei', 0) if owner_state.exists() else 0
            output = command(sys.executable, 'keeper/keeper.py', manager, '--send', '--from', actors['owner'], '--rpc', url,
                             '--state', owner_state, '--index', owner_index, '--caller-funded-exit', '--exit-spend-limit-wei',
                             10**16 - report['ownerDirectSignedUpperWei'] - reserved, '--max-steps', 32, '--confirmations', 1, '--pending-timeout', 30)
            (work / f'owner-exit-{attempt}.log').write_text(output)
            if not any(account().values()):
                break
            rpc('evm_mine')
        else:
            raise RuntimeError('bounded owner exit incomplete')
        owner_state = json.loads(owner_state.read_text()); report['ownerExitState'] = owner_state
        for entry in owner_state['counted']:
            assert not entry.get('reorged')
            record(entry.get('function', entry['label']), entry['hash'])
        assert owner_state['stats']['paid_wei'] == 0 and owner_state['pending'] is None
        assert owner_state['signed_upper_wei'] + report['ownerDirectSignedUpperWei'] <= 10**16
        report['finalAccount'] = account()
        topic = '0x' + keccak(text='Withdrawn(address,uint256)').hex()
        withdrawn = sum(int(log['data'], 16) for item in report['transactions'] for log in item['receipt']['logs']
                        if log['address'].lower() == manager.lower() and log['topics'] and log['topics'][0] == topic)
        pay_topic = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()
        paid = sum(int(log['data'], 16) for item in report['transactions'] for log in item['receipt']['logs']
                   if log['address'].lower() == manager.lower() and log['topics'] and log['topics'][0] == pay_topic)
        assert paid == after['stats']['paid_wei'] > 0 and funding - withdrawn == creator + paid
        ledgers = {}
        for name, actor in actors.items():
            receipts = [x for x in report['transactions'] if x['transaction']['from'].lower() == actor.lower()]
            gas = sum(x['gasCostWei'] for x in receipts)
            end = integer(cast('balance', actor))
            expected = withdrawn - funding - gas if name == 'owner' else paid - gas if name == 'keeper' else -gas
            assert end - initial[name] == expected, name + ' ledger gap'
            ledgers[name] = dict(initialWei=initial[name], finalWei=end, walletGasWei=gas, netWei=end-initial[name], gapWei=0)
        assert frozen == sources() and keeper_hashes == {p: sha(ROOT / p) for p in keeper_paths}
        report.update(status='PASS', ledgers=ledgers, fundingWei=funding, withdrawnWei=withdrawn,
                      creatorPrimaryFeesAccruedWei=creator, keeperCompensationWei=paid, liveMintFeeWei=fee,
                      accountLedgerGapWei=0, elapsedSeconds=round(time.monotonic()-started, 3), finalBlock=integer(cast('block-number')))
        save()
        print(json.dumps({k: report[k] for k in ('status', 'factory', 'manager', 'fundingWei', 'withdrawnWei', 'creatorPrimaryFeesAccruedWei', 'keeperCompensationWei', 'ledgers', 'elapsedSeconds')}, indent=1))
    except Exception as error:
        report.update(status='FAIL', error=str(error), elapsedSeconds=round(time.monotonic()-started, 3)); save()
        raise
    finally:
        stop_keeper()
        # Retain this owned fork and logs for independent readback; never touch another node.
        report['ownedNodeRetained'] = node.poll() is None
        save()


if __name__ == '__main__':
    main()
