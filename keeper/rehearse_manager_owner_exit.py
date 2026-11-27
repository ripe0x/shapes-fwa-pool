#!/usr/bin/env python3
"""Owner-unpaid recoverUnlist/recoverLiquidate curves on the retained main-run fork.

Reverts to the post-setup snapshot the main measured run (and sync-contexts) left on the
node, creates a fresh funded manager, lists eight packs, then measures the owner exit calls
recoverUnlist(uint256[]) and recoverLiquidate(uint256) at batch sizes 1/3/8. These owner calls
are caller-funded and pay the caller 0, so no work meter is asserted; only billed gas and the
rpc estimate feed write_profile's owner unlist/liquidate gas curves. No public transaction.
"""
import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak, to_checksum_address

from config import GAS_FIELDS, PARAMS_T, full_design, params_values
from rehearse_manager_measured import data, rpc_at
from rehearse_manager_r2 import ROOT, FWA, SHAPES, PACKS, sources

URL = 'http://127.0.0.1:8545'
BASE = ROOT / 'docs/receipts/manager-measured-50k-receipts-current.json'
SYNC = ROOT / 'docs/receipts/manager-measured-sync-contexts-current.json'
OUT = ROOT / 'docs/receipts/manager-measured-owner-exit-current.json'
CROWN_WINDOW = 12 * 3600
COUNTS = (1, 3, 8)


def rpc(method, *params):
    return rpc_at(URL, method, params)


def read(target, signature, kinds=(), values=(), returns=('uint256',)):
    raw = rpc('eth_call', {'to': target, 'data': data(signature, kinds, values)}, 'latest')
    return decode(returns, bytes.fromhex(raw[2:]))


def number(target, signature, kinds=(), values=()):
    return read(target, signature, kinds, values)[0]


def config(account):
    return read(account, 'configurationHash()', returns=('bytes32',))[0]


def prime(base):
    rpc('anvil_setNextBlockBaseFeePerGas', hex(base * 8 // 7))
    rpc('evm_mine')
    from tx import next_base_fee
    assert next_base_fee(rpc('eth_getBlockByNumber', 'latest', False)) == base


def send(sender, target, signature, kinds, values, operation, base, price, workCount=1, value=0):
    prime(base)
    payload = {'from': sender, 'to': to_checksum_address(target), 'data': data(signature, kinds, values),
               'value': hex(value), 'maxFeePerGas': hex(2 * base + 50000000), 'maxPriorityFeePerGas': hex(50000000)}
    estimate = int(rpc('eth_estimateGas', payload), 16)
    gas_limit = (estimate * 5 + 3) // 4
    assert 0 < gas_limit <= 16777216
    h = rpc('eth_sendTransaction', payload | {'gas': hex(gas_limit)})
    receipt = None
    for _ in range(120):
        receipt = rpc('eth_getTransactionReceipt', h)
        if receipt:
            break
        time.sleep(.5)
    assert receipt and int(receipt['status'], 16) == 1, (operation, h)
    tx = rpc('eth_getTransactionByHash', h)
    block = rpc('eth_getBlockByHash', receipt['blockHash'], False)
    assert int(receipt['effectiveGasPrice'], 16) == price and int(block['baseFeePerGas'], 16) == base
    return dict(branch='owner-exit', operation=operation, workCount=workCount, targetAccount=target,
                gasEstimate=estimate, estimateKind='rpc-estimate', signedGasLimit=gas_limit,
                gasUsed=int(receipt['gasUsed'], 16), effectiveGasPrice=price, blockBaseFeeWei=base,
                gasCostWei=int(receipt['gasUsed'], 16) * price, compensationWei=0, transaction=tx, receipt=receipt)


def main():
    global URL, BASE, SYNC, OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--port', type=int, default=8545, help='Retained main-run node port (anvil only runs on 8545)')
    ap.add_argument('--base', default=str(BASE), help='Fresh main measured packet')
    ap.add_argument('--sync', default=str(SYNC), help='Fresh sync-contexts packet (records the surviving post-setup snapshot)')
    ap.add_argument('--output', default=str(OUT), help='Fresh output packet; existing packets are never overwritten')
    ap.add_argument('--starting-snapshot', default=None, help='Post-setup snapshot on the retained node; defaults to the sync packet record')
    a = ap.parse_args()
    URL = f'http://127.0.0.1:{a.port}'
    BASE = Path(a.base).resolve(); SYNC = Path(a.sync).resolve(); OUT = Path(a.output).resolve()
    assert not OUT.exists(), 'preserve existing immutable receipt packet'
    base_packet = json.loads(BASE.read_text())
    sync_packet = json.loads(SYNC.read_text())
    assert base_packet['status'] == 'PASS' and base_packet['contractSourceSha256'] == sources()
    assert sync_packet['status'] == 'PASS' and sync_packet['contractSourceSha256'] == sources()
    snapshot = a.starting_snapshot or sync_packet['postSetupSnapshot']
    settings = json.loads((ROOT / 'deploy/manager.json').read_text())
    assert list(settings['gasSchedule']) == GAS_FIELDS
    values = params_values(settings)
    owner = to_checksum_address(base_packet['owner'])
    keeper = to_checksum_address(base_packet['keeper'])
    factory = to_checksum_address(base_packet['factory'])

    assert rpc('eth_chainId') == '0x7a69' and rpc('anvil_nodeInfo')['hardFork'] == 'Osaka'
    assert rpc('evm_revert', snapshot), 'post-setup snapshot missing; do not substitute state'
    for actor in (owner, keeper):
        rpc('anvil_impersonateAccount', actor)
        assert int(rpc('eth_getBalance', actor, 'latest'), 16) > 4 * 10**18 if actor == owner else True
    packet = dict(status='RUNNING', chainId=31337, rpc=URL, executionHardfork='Osaka',
                  command=[sys.executable, *sys.argv], scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  contractSourceSha256=sources(), sourceReceipt=str(BASE.relative_to(ROOT)),
                  sourceReceiptSha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
                  syncPacket=str(SYNC.relative_to(ROOT)), startingSnapshot=snapshot,
                  fullGasSchedule=settings['gasSchedule'], factory=factory, owner=owner, keeper=keeper,
                  managerValues=settings, publicTransactions=0, transactions=[],
                  limitations=['Owner recoverUnlist/recoverLiquidate are caller-funded and pay 0; only billed gas and rpc estimate are used.',
                               'Fresh funded manager built on the authenticated post-setup fork; not one economic portfolio.',
                               'All transactions are local chain 31337; public transactions zero.'])
    OUT.write_text(json.dumps(packet, indent=1) + '\n')
    base, price = 150000000, 200000000

    def drain():
        # The authenticated checkpoint leaves one unsettled FWA acquisition; _requireListing blocks
        # all building until the global queue drains. Process it, advancing to its real deadline.
        for _ in range(32):
            if number(FWA, 'unsettledAcquisitionCount()') == 0:
                break
            seq = number(FWA, 'nextSequenceToProcess()')
            request = number(FWA, 'requestIdAtSequence(uint64)', ['uint64'], [seq])
            fields = read(FWA, 'acquisitionMeta(uint256)', ['uint256'], [request],
                          ('uint64', 'uint64', 'uint64', 'uint16', 'uint16', 'uint256'))
            gap = max(0, fields[1] + 1 - int(rpc('eth_blockNumber'), 16))
            assert gap <= 7201, 'real protocol deadline exceeds bounded setup'
            if gap:
                rpc('anvil_mine', hex(gap), hex(12))
            packet['transactions'].append(send(owner, FWA, 'processAcquisitions(uint256)', ['uint256'], [32], 'setupDrain', base, price))
            assert number(FWA, 'nextSequenceToProcess()') > seq
        assert number(FWA, 'unsettledAcquisitionCount()') == 0
        now = int(rpc('eth_getBlockByNumber', 'latest', False)['timestamp'], 16)
        rpc('evm_setNextBlockTimestamp', now - now % 43200 + 43200 + 60); rpc('evm_mine')

    try:
        drain()
        post_setup = rpc('evm_snapshot')
        # Fresh funded manager, eight listed packs (two build(4) calls, owner-driven at minPay 0).
        index = number(factory, 'managerCount()')
        expected = read(factory, f'configHashFor({PARAMS_T})', [PARAMS_T], [values], ('bytes32',))[0]
        packet['transactions'].append(send(owner, factory, f'create(address,{PARAMS_T},uint256,bytes32)',
            ['address', PARAMS_T, 'uint256', 'bytes32'], [owner, values, full_design(settings), expected], 'setupCreate', base, price, value=3 * 10**18))
        target = read(factory, 'managerAt(uint256)', ['uint256'], [index], ('address',))[0]
        target = to_checksum_address(target)
        # Canonical backing for the current config: the account owns the ratio, so proposals must equal
        # preview().backing within one BPS; +i*BPS offsets give the per-listing uniqueness required.
        backing = read(factory, f'preview({PARAMS_T})', [PARAMS_T], [values],
            ('uint256', 'uint256', 'uint256', 'uint256', 'uint256', 'bytes32'))[2]
        for offset in (0, 4):
            proposals = [backing + i * 10000 for i in range(offset, offset + 4)]
            packet['transactions'].append(send(owner, target, 'build(uint256,uint256[],uint256,bytes32)',
                ['uint256', 'uint256[]', 'uint256', 'bytes32'], [3, proposals, 0, config(target)], 'setupBuild', base, price, workCount=4))
        assert number(target, 'openListingCount()') == 8
        ids = [number(target, 'openListingAt(uint256)', ['uint256'], [i]) for i in range(8)]
        # Advance past the crown-exit window so no fresh listing is the locked top listing.
        now = int(rpc('eth_getBlockByNumber', 'latest', False)['timestamp'], 16)
        rpc('evm_setNextBlockTimestamp', now + CROWN_WINDOW + 60); rpc('evm_mine')
        OUT.write_text(json.dumps(packet, indent=1) + '\n')
        listed = rpc('evm_snapshot')
        for count in COUNTS:
            assert rpc('evm_revert', listed); listed = rpc('evm_snapshot')
            packet['transactions'].append(send(owner, target, 'setExiting(bool)', ['bool'], [True], 'setupExiting', base, price))
            assert read(target, 'windingDown()', returns=('bool',))[0]
            selected = ids[:count]
            open_before = number(target, 'openListingCount()')
            idle_before = number(target, 'idlePackCount()')
            unlist = send(owner, target, 'recoverUnlist(uint256[])', ['uint256[]'], [selected], 'recoverUnlist', base, price, workCount=count)
            assert number(target, 'openListingCount()') == open_before - count, ('recoverUnlist moved != count', count)
            assert number(target, 'idlePackCount()') == idle_before + count
            packet['transactions'].append(unlist)
            idle_now = number(target, 'idlePackCount()')
            liquidate = send(owner, target, 'recoverLiquidate(uint256)', ['uint256'], [count], 'recoverLiquidate', base, price, workCount=count)
            assert number(target, 'idlePackCount()') == idle_now - count, ('recoverLiquidate count mismatch', count)
            packet['transactions'].append(liquidate)
            packet.setdefault('contexts', []).append(dict(count=count, manager=target,
                recoverUnlistGasUsed=unlist['gasUsed'], recoverUnlistGasEstimate=unlist['gasEstimate'],
                recoverLiquidateGasUsed=liquidate['gasUsed'], recoverLiquidateGasEstimate=liquidate['gasEstimate']))
            OUT.write_text(json.dumps(packet, indent=1) + '\n')
        # Leave the post-setup snapshot re-created on the node in case another packet follows.
        assert rpc('evm_revert', post_setup); packet['postSetupSnapshot'] = rpc('evm_snapshot')
        packet['status'] = 'PASS'
    except Exception as e:
        packet['status'] = 'FAIL'; packet['error'] = str(e)
        raise
    finally:
        OUT.write_text(json.dumps(packet, indent=1) + '\n')
    print(json.dumps(dict(status=packet['status'], contexts=packet.get('contexts', [])), indent=1))


if __name__ == '__main__':
    main()
