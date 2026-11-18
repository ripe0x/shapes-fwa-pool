#!/usr/bin/env python3
"""Execute only the owner-approved review-journal-local-plan.json local batch."""
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
import rehearsal_batch as B
import rehearse_canary as R
import measure_gas as M
import tx as T

OUT = R.ROOT / 'docs/receipts/review-journal-local-results.json'
EXPECTED = {'src/PackVault.sol': '1dc1ddb5d4c09057f34797efdff5d87929898c51bda671423de23625e7687af2',
            'src/VaultLib.sol': '259d85003ff2392be404ead8d067edc92b1277044ee905e4f3640235bc760aae'}
if OUT.exists():
    prior = json.loads(OUT.read_text())
    if prior.get('broadcast_transactions', 0) and not prior.get('entry_snapshot_restored'):
        raise RuntimeError('prior batch has un-restored transactions; reconcile before rerunning')
report = {'scope': 'approved local-only 8557 batch; actual refunded journal receipts; no manufactured success',
          'source_sha256': EXPECTED, 'rows': [], 'broadcast_transactions': 0, 'external_value_wei': 0,
          'status': 'started'}
original_send = R.send

def save():
    OUT.write_text(json.dumps(report, indent=2) + '\n')

def freeze():
    for path, expected in EXPECTED.items():
        if hashlib.sha256((R.ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError('frozen source changed: ' + path)

def reserve(count, value):
    if report['broadcast_transactions'] + count > 80 or report['external_value_wei'] + value > 3 * R.E:
        raise RuntimeError('approved aggregate transaction/value bound would be exceeded')
    report['broadcast_transactions'] += count
    report['external_value_wei'] += value
    save()

def bounded_send(frm, to, sig, *args, value=None, expect=True):
    freeze()
    reserve(1, value or 0)
    return original_send(frm, to, sig, *args, value=value, expect=expect)

R.send = bounded_send

def fee():
    # Mine an empty parent whose EIP-1559 child base fee is exactly 0.15 gwei.
    R.cast('rpc', 'anvil_setNextBlockBaseFeePerGas', hex(171428571))
    R.cast('rpc', 'evm_mine')
    base, fees = B.pending_fees()
    if base != 150000000:
        raise RuntimeError('unexpected next-block fee context: ' + str(base))
    return fees

def measure(label, sig, *args, frm=None, value=None, **meta):
    fees = fee()
    frm = frm or R.KEEPER
    estimate = R.num(R.cast('estimate', R.VAULT, sig, *args, '--from', frm,
                            '--value', value or 0, '--block', 'pending', *fees))
    start = R.num(R.call(R.VAULT, 'acquisitionCursor()(uint64)'))
    R.send(frm, R.VAULT, sig, *args, value=value)
    block = json.loads(R.cast('rpc', 'eth_getBlockByNumber', 'latest', 'true'))
    if len(block['transactions']) != 1:
        raise RuntimeError('receipt block was not isolated')
    transaction = block['transactions'][0]
    receipt = json.loads(R.cast('rpc', 'eth_getTransactionReceipt', transaction['hash']))
    paid = sum(int(log['data'], 16) for log in receipt['logs'] if log.get('topics')
               and log['topics'][0].lower() == T.KEEPER_PAID and log['address'].lower() == R.VAULT.lower())
    gas, price = R.num(receipt['gasUsed']), R.num(receipt['effectiveGasPrice'])
    if R.num(block['baseFeePerGas']) != 150000000 or price != 200000000:
        raise RuntimeError('executed fee context differs from asserted regime')
    row = dict(label=label, function=sig, arguments=list(args), sender=frm, estimate=estimate,
               signed_gas_limit=R.num(transaction['gas']), billed_gas=gas, basefee_wei=150000000,
               effective_price_wei=price, caller_gas_cost_wei=gas * price, keeper_paid_wei=paid,
               cursor_before=start, cursor_after=R.num(R.call(R.VAULT, 'acquisitionCursor()(uint64)')),
               completed_prefix=R.num(R.call(R.FWA, 'nextSequenceToProcess()(uint64)')),
               transaction=transaction, receipt=receipt, **meta)
    report['rows'].append(row)
    save()
    print(json.dumps({k: row[k] for k in ('label', 'estimate', 'billed_gas', 'keeper_paid_wei')}), flush=True)
    return row

def snapshot():
    return json.loads(R.cast('rpc', 'evm_snapshot'))

def restore(snap):
    if not json.loads(R.cast('rpc', 'evm_revert', snap)):
        raise RuntimeError('snapshot restoration failed')
    return snapshot()

def main():
    freeze(); manifest = B.load_manifest()
    if manifest.get('approval') != 'owner-approved-review-journal-replacement-3ETH':
        raise RuntimeError('missing exact replacement approval manifest marker')
    if sum(v['funded'] for v in manifest['funding'].values()) != 3 * R.E:
        raise RuntimeError('replacement initial funding allocation changed')
    report['manifest'] = {k: manifest[k] for k in ('endpoint', 'pid', 'fork_block', 'fork_hash')}
    report['entry_head'] = json.loads(R.cast('rpc', 'eth_getBlockByNumber', 'latest', 'false'))
    report['actors_before'] = {k: dict(address=a, balance=R.num(R.cast('balance', a)),
                                      nonce=R.num(R.cast('nonce', a)), code=R.cast('code', a))
                               for k, a in B.ACTORS.items()}
    if any(a['code'] != '0x' for a in report['actors_before'].values()):
        raise RuntimeError('named actor acquired code')
    if json.loads(R.cast('rpc', 'txpool_status')) != {'pending': '0x0', 'queued': '0x0'}:
        raise RuntimeError('nonempty transaction pool')
    entry = snapshot(); save()
    for actor in B.ACTORS.values(): R.impersonate(actor)
    # Reserve worst-case three deployments; reconcile actual broadcast count immediately.
    reserve(3, B.values()['seedWei'])
    R.VAULT = B.deploy(B.values(), 'review-journal')
    deployment = json.loads((R.ROOT / 'broadcast/Deploy.s.sol/1/run-latest.json').read_text())
    actual = len(deployment['transactions'])
    if actual > 3: raise RuntimeError('deployment exceeded approved three-transaction reservation')
    report['broadcast_transactions'] -= 3 - actual
    report['deployment'] = B.CURRENT_DEPLOYMENT
    report['vault'] = R.VAULT; save()
    R.expire_queue()
    charge = R.num(R.call(R.VAULT, 'requestCharge()(uint256)'))
    R.send(R.HOLDER, R.VAULT, 'deposit()', value=8 * R.E // 10 + charge)
    R.warp_to(42360)
    measure('price first deposit', 'checkpoint(uint256,uint256)', 0, 0)
    R.warp_to(60)
    measure('real three-unit restock', 'restock(uint256,uint256[],uint256)', 3, M.quote(3, 1, True), 0)
    measure('real active listing', 'list(uint256[],uint256)', M.quote(3, 1), 0)
    listings = R.ids()
    if len(listings) != 1: raise RuntimeError('expected exactly one active listing')
    listing = listings[0]
    first = R.num(R.call(R.FWA, 'lastIssuedSequence()(uint64)')) + 1
    cursor = R.num(R.call(R.VAULT, 'acquisitionCursor()(uint64)'))
    if first != cursor: raise RuntimeError('preexisting unmatched journal prefix')
    escrow = 0
    for _ in range(16):
        price = R.num(R.pricing(R.FWA, 'quoteAcquisitionPrice()(uint256,uint256,uint256)').splitlines()[2])
        escrow += price
        if escrow > 15 * R.E // 10: raise RuntimeError('approved simultaneous acquisition escrow exceeded')
        R.send(R.KICKER, R.FWA, 'acquire(address,uint256,uint256,uint256,uint256)',
               R.KICKER, 1, 0, 0, 10000, value=price)
    R.expire_queue()
    statuses = []
    for sequence in range(first, first + 16):
        request = R.num(R.call(R.FWA, 'requestIdAtSequence(uint64)(uint256)', sequence))
        status = R.num(R.cast('call', R.FWA, 'acquisitions(uint256)(address,uint256,uint256,uint256,uint8)', request).splitlines()[-1])
        if status not in (3, 4): raise RuntimeError('request was not genuinely refunded')
        statuses.append(dict(sequence=sequence, request=request, status=status))
    R.send(R.KICKER, R.FWA, 'withdrawAcquisitionRefund()')
    if R.num(R.call(R.FWA, 'nextSequenceToProcess()(uint64)')) != first + 16:
        raise RuntimeError('completed prefix differs from exactly sixteen requests')
    report.update(refunded_requests=statuses, acquisition_escrow_wei=escrow, active_listing=listing)
    branch = snapshot(); save()
    for n in range(1, 17):
        branch = restore(branch)
        row = measure(f'prefix {n}', 'sync(uint256,uint256[],uint256,uint256)', n, '[]', 0, 0, entries=n)
        if row['cursor_after'] != first + n or row['keeper_paid_wei'] <= 0:
            raise RuntimeError('paid exposed journal prefix mismatch')
    for n in range(1, 16):
        branch = restore(branch)
        measure(f'tail {n} preparation', 'sync(uint256,uint256[],uint256,uint256)', 16-n, '[]', 0, 0, entries=16-n)
        row = measure(f'tail {n} completion', 'sync(uint256,uint256[],uint256,uint256)', n, '[]', 0, 0, entries=n)
        if row['cursor_after'] != row['completed_prefix'] or row['keeper_paid_wei'] <= 0:
            raise RuntimeError('paid completion mismatch')
    branch = restore(branch)
    shares = R.num(R.call(R.VAULT, 'shareBalance(address)(uint256)', R.HOLDER))
    fee()
    charge = R.num(R.call(R.VAULT, 'requestCharge()(uint256)'))
    measure('exit request all holder shares', 'requestRedeem(uint256)', shares, frm=R.HOLDER, value=charge)
    budgets = R.cast('call', R.VAULT, 'budget()(uint256,uint256)').splitlines()
    if R.num(budgets[0]) <= 0 or R.num(budgets[1]) != 0: raise RuntimeError('exit budget regime mismatch')
    row = measure('exit unpaid sixteen-record backlog', 'sync(uint256,uint256[],uint256,uint256)', 16, '[]', 0, 0, frm=R.HOLDER, entries=16)
    if row['keeper_paid_wei'] != 0: raise RuntimeError('essential zero-budget work was paid')
    R.warp_to(42360)
    measure('exit unlist real position', 'unlist(uint256[],uint256)', M.array([listing]), 0, frm=R.HOLDER)
    measure('exit liquidate real pack and loose Shapes', 'liquidate(uint256,uint256)', 16, 0, frm=R.HOLDER)
    measure('exit checkpoint', 'checkpoint(uint256,uint256)', 0, 0, frm=R.HOLDER)
    before = R.num(R.cast('balance', R.HOLDER))
    row = measure('exit claim', 'claim()', frm=R.HOLDER)
    report['holder_claim_wei'] = R.num(R.cast('balance', R.HOLDER)) - before + row['caller_gas_cost_wei']
    for sig in ('shareBalance(address)(uint256)', 'claimableEth(address)(uint256)'):
        if R.num(R.call(R.VAULT, sig, R.HOLDER)) != 0: raise RuntimeError('holder entitlement remains')
    if R.num(R.call(R.VAULT, 'lockedShares()(uint256)')) != 0: raise RuntimeError('locked shares remain')
    report['final_vault_balance_wei'] = R.num(R.cast('balance', R.VAULT))
    report['status'] = 'passed'; save()
    restore(entry)
    report['entry_snapshot_restored'] = True
    report['restored_head'] = json.loads(R.cast('rpc', 'eth_getBlockByNumber', 'latest', 'false'))
    if report['restored_head']['hash'] != report['entry_head']['hash']: raise RuntimeError('entry head not restored')
    save()

def start_replacement():
    if os.environ.get(B.ENV_MANIFEST):
        raise RuntimeError('refusing inherited/nested replacement batch')
    freeze()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 8557))
    work = Path(tempfile.mkdtemp(prefix='pack-vault-review-journal-replacement-'))
    command = B.plan()['node_command']
    allocation = dict(deployer=R.E // 10, holder=9 * R.E // 10, holder2=R.E // 5,
                      keeper=R.E // 5, kicker=15 * R.E // 10, owner=R.E // 10)
    if sum(allocation.values()) != 3 * R.E:
        raise RuntimeError('initial funding allocation exceeds approval')
    node_log = open(work / 'anvil.log', 'w')
    proc = subprocess.Popen(command, cwd=R.ROOT, stdout=node_log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    for _ in range(150):
        if proc.poll() is not None:
            raise RuntimeError('replacement Anvil stopped; inspect ' + str(work))
        try:
            header = B.rpc('eth_getBlockByNumber', hex(B.FORK_BLOCK), False)
            if header: break
        except (RuntimeError, json.JSONDecodeError):
            pass
        time.sleep(.2)
    else:
        raise RuntimeError('replacement Anvil did not become readable')
    manifest = work / 'manifest.json'
    m = dict(endpoint=B.RPC, fork_block=B.FORK_BLOCK, max_gas=B.MAX_GAS, pid=proc.pid,
             fork_hash=header['hash'], actions=str(work / 'actions.jsonl'), funding={},
             approval='owner-approved-review-journal-replacement-3ETH', node_command=command)
    manifest.write_text(json.dumps(m, indent=2)+'\n')
    os.environ[B.ENV_MANIFEST] = str(manifest)
    B.load_manifest()
    if R.num(R.cast('block-number')) != B.FORK_BLOCK:
        raise RuntimeError('fresh replacement node is not at approved fork block')
    clean = {}
    for role, addr in B.ACTORS.items():
        clean[role] = dict(address=addr, code=R.cast('code', addr), nonce=R.num(R.cast('nonce', addr)),
                           balance=R.num(R.cast('balance', addr)))
        if clean[role]['code'] != '0x' or clean[role]['nonce'] or clean[role]['balance']:
            raise RuntimeError('replacement actor not clean: '+role)
    for role, addr in B.ACTORS.items():
        B.rpc('anvil_impersonateAccount', addr)
        B.rpc('anvil_setBalance', addr, hex(allocation[role]))
        if R.num(R.cast('balance', addr)) != allocation[role]:
            raise RuntimeError('one-time initial funding readback mismatch')
        m['funding'][addr.lower()] = dict(before_code='0x',before_nonce=0,before_balance=0,
                                         funded=allocation[role])
        manifest.write_text(json.dumps(m, indent=2)+'\n')
    evidence = dict(manifest=m, manifest_path=str(manifest), clean_actor_readbacks=clean,
                    initial_funding_wei=sum(allocation.values()), additional_funding_authorized=False,
                    source_sha256=EXPECTED)
    (R.ROOT / 'docs/receipts/review-journal-replacement-startup.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('REPLACEMENT_STARTED '+json.dumps(dict(pid=proc.pid,manifest=str(manifest),funding_wei=3*R.E)),flush=True)
    node_log.close()

if __name__ == '__main__':
    try:
        if sys.argv[1:] == ['--start-approved-replacement']:
            start_replacement()
        elif sys.argv[1:]:
            raise RuntimeError('unknown executor arguments')
        main()
    except BaseException as exc:
        report['status'] = 'failed'; report['failure'] = str(exc); save(); raise
