#!/usr/bin/env python3
"""Measure a two-position scan, fee sweep, and paired owner recovery on a real FWA fork."""
import argparse
import hashlib
import json
import subprocess
import tempfile
import time
from urllib.error import HTTPError
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak, to_checksum_address

from config import PARAMS_T, params_values
from rehearse_manager_measured import data, rpc_at
from rehearse_manager_r2 import ROOT, PUBLIC, FWA, PACKS, SHAPES, sources

BASE = ROOT / 'docs/receipts/manager-measured-50k-receipts.json'
DEFAULT_OUT = ROOT / 'docs/receipts/manager-measured-sync-scan.json'
METER = '0x' + keccak(text='KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)').hex()
PAID = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_read(method, params):
    for attempt in range(30):
        try:
            return rpc_at(PUBLIC, method, params)
        except HTTPError as error:
            if error.code != 429 or attempt == 29:
                raise
            time.sleep(5)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', default=str(DEFAULT_OUT))
    ap.add_argument('--port', type=int, default=18827)
    ap.add_argument('--scan-positions', type=int, choices=(1,2,3), default=2)
    ap.add_argument('--multi', action='store_true', help='Use the real five-proof fixture with two selected manager listings')
    ap.add_argument('--preselected', action='store_true', help='Use the five-proof fixture after one unpaid intermediate selection sync')
    ap.add_argument('--resolve-later-first', action='store_true', help='Settle the later of two selected listings first, leaving the earlier allocation in the prune queue')
    ap.add_argument('--no-fee-sweep-calibration', action='store_true')
    ap.add_argument('--block-fork', action='store_true', help='Fork immediately before the recorded request, then verify every exported state field')
    args = ap.parse_args()
    if args.preselected:
        args.multi = True
    if args.resolve_later_first and not args.multi:
        ap.error('--resolve-later-first requires --multi')
    out = Path(args.output).resolve()
    if out.exists():
        raise SystemExit('preserve the existing scan packet; choose a fresh output')
    base_packet = json.loads(BASE.read_text())
    assert base_packet['status'] == 'PASS' and base_packet['contractSourceSha256'] == sources()
    stem = ROOT / ('sim/out/manager-measured-preselected-checkpoint' if args.preselected else
                   'sim/out/manager-measured-multi-checkpoint-v2' if args.multi else
                   'sim/out/manager-measured-checkpoint')
    if args.multi:
        paths = {str(Path(str(stem)+'-'+kind+'.json').relative_to(ROOT)):digest(str(stem)+'-'+kind+'.json')
                 for kind in ('metadata','alloc','diff')}
        checkpoint = dict(paths=paths, actualMetadata=json.loads(Path(str(stem)+'-metadata.json').read_text()))
    else:
        checkpoint = base_packet['checkpoint']
    meta = checkpoint['actualMetadata']
    for name, expected in checkpoint['paths'].items():
        assert digest(ROOT / name) == expected, 'authenticated checkpoint changed'
    settings = json.loads((ROOT / 'deploy/manager.json').read_text())
    assert settings == base_packet['managerValues']
    calibration = (settings if args.no_fee_sweep_calibration else settings | dict(
        keeperShareBps=5_000,gasCeilingWei=500_000_000 if args.multi else 310_000_000))
    manager = to_checksum_address(base_packet['manager'])
    owner = to_checksum_address(meta['owner'])
    keeper = to_checksum_address(base_packet['keeper'])
    purchaser = to_checksum_address(meta['purchaser'])
    buyer = to_checksum_address(keccak(text='pack-vault-test-measured-scan-buyer')[-20:])
    url = f'http://127.0.0.1:{args.port}'
    work = Path(tempfile.mkdtemp(prefix='manager-scan-'))
    if args.multi:
        historical = public_read('eth_getTransactionByHash',[meta['requestTx']])
        header = public_read('eth_getBlockByNumber',[historical['blockNumber'],False])
        index = int(historical['transactionIndex'],16)
        assert header['transactions'][index].lower() == meta['requestTx'].lower()
        prefix = (['--fork-block-number',str(meta['requestBlock']-1)] if args.block_fork else
                  ['--fork-transaction-hash',header['transactions'][index-1]] if index else
                  ['--fork-block-number',str(meta['requestBlock']-1)])
        command = ['anvil','--host','127.0.0.1','--port',str(args.port),'--accounts','0',
                   '--chain-id','31337','--hardfork','osaka','--enable-tx-gas-limit',
                   '--gas-limit','60000000','--fork-url',PUBLIC,*prefix,'--retries','30',
                   '--fork-retry-backoff','5000','--silent']
    else:
        command = list(base_packet['nodeCommand'])
        command[command.index('--port') + 1] = str(args.port)
        if args.block_fork and '--fork-transaction-hash' in command:
            index = command.index('--fork-transaction-hash')
            command[index:index+2] = ['--fork-block-number',str(meta['requestBlock']-1)]
    node = subprocess.Popen(command, stdout=open(work / 'anvil.log', 'w'), stderr=subprocess.STDOUT,
                            start_new_session=True)
    packet = dict(status='RUNNING', chainId=31337, executionHardfork='Osaka', rpc=url,
                  forkBlock=meta['requestBlock'], contractSourceSha256=sources(),
                  fullGasSchedule=settings['gasSchedule'], manager=manager, owner=owner, keeper=keeper,
                  purchaser=purchaser, buyer=buyer, sourceReceipt=str(BASE.relative_to(ROOT)),
                  sourceReceiptSha256=digest(BASE), authenticatedCheckpoint=checkpoint['paths'],
                  scriptSha256=digest(__file__), nodePid=node.pid, nodeCommand=command,
                  workDirectory=str(work), publicTransactions=0, transactions=[], contexts=[],
                  scanPositions=args.scan_positions,multipleRealSelections=args.multi,
                  resolveLaterFirst=args.resolve_later_first,
                  preselectedListing=meta.get('preselected'),
                  forkBaseMode='prior-block-plus-verified-export' if args.block_fork else 'prior-transaction-plus-verified-export',
                  calibrationOverride=None if args.no_fee_sweep_calibration else {
                    'keeperShareBps':5_000,'gasCeilingWei':calibration['gasCeilingWei'],
                    'purpose':'Reach a real fee-credit sweep with the authenticated small credit; gas schedule and runtime remain identical. Keeper economics under this override are not candidate economics.'})

    def save():
        out.write_text(json.dumps(packet, indent=1) + '\n')

    def rpc(method, *params):
        return rpc_at(url, method, list(params))

    def read(target, signature, kinds=(), values=(), returns=('uint256',)):
        raw = rpc('eth_call', {'to': target, 'data': data(signature, kinds, values)}, 'latest')
        return decode(returns, bytes.fromhex(raw[2:]))

    def number(target, signature, kinds=(), values=()):
        return read(target, signature, kinds, values)[0]

    def config():
        return read(manager, 'configurationHash()', returns=('bytes32',))[0]

    def prime(base):
        from tx import next_base_fee
        rpc('anvil_setNextBlockBaseFeePerGas', hex(base * 8 // 7))
        rpc('evm_mine')
        assert next_base_fee(rpc('eth_getBlockByNumber', 'latest', False)) == base

    def send(sender, target, signature, kinds=(), values=(), *, value=0, base=150_000_000,
             price=200_000_000, branch='prepare', paid=False, count=1):
        prime(base)
        payload = {'from': sender, 'to': target, 'data': data(signature, kinds, values),
                   'value': hex(value), 'maxFeePerGas': hex(2 * base + 50_000_000),
                   'maxPriorityFeePerGas': hex(50_000_000)}
        simulated = None
        if paid:
            simulated = read_pending(payload)
            assert simulated > 0
            values = list(values)
            values[-2] = simulated * 8 // 10
            payload['data'] = data(signature, kinds, values)
        estimate = int(rpc('eth_estimateGas', payload), 16)
        limit = (estimate * 5 + 3) // 4
        assert 0 < limit <= 16_777_216
        tx_hash = rpc('eth_sendTransaction', payload | {'gas': hex(limit)})
        for _ in range(120):
            receipt = rpc('eth_getTransactionReceipt', tx_hash)
            if receipt:
                break
            time.sleep(.5)
        assert receipt and int(receipt['status'], 16) == 1, (branch, signature, tx_hash)
        tx = rpc('eth_getTransactionByHash', tx_hash)
        block = rpc('eth_getBlockByHash', receipt['blockHash'], False)
        assert int(receipt['effectiveGasPrice'], 16) == price
        assert int(block['baseFeePerGas'], 16) == base
        logs = [log for log in receipt['logs'] if log['address'].lower() == target.lower()]
        meters = [decode(['uint256', 'uint256', 'uint256', 'uint256', 'bool'], bytes.fromhex(log['data'][2:]))
                  for log in logs if log['topics'][0].lower() == METER.lower()]
        compensation = sum(int(log['data'], 16) for log in logs if log['topics'][0].lower() == PAID.lower())
        row = dict(branch=branch, operation=signature.split('(')[0], workCount=count, targetAccount=target,
                   gasEstimate=estimate, estimateKind='rpc-estimate', signedGasLimit=limit,
                   gasUsed=int(receipt['gasUsed'], 16), effectiveGasPrice=price, blockBaseFeeWei=base,
                   gasCostWei=int(receipt['gasUsed'], 16) * price, compensationWei=compensation,
                   transaction=tx, receipt=receipt)
        if paid:
            assert len(meters) == 1
            meter = dict(zip(('measuredGas', 'gasAllowance', 'gasPrice', 'workUnits', 'essential'), meters[0]))
            calibrated = packet['calibrationOverride'] is not None
            assert meter['gasPrice'] == (min(price, calibration['gasCeilingWei']) if calibrated else price)
            expected = (min(meter['measuredGas'], meter['gasAllowance']) + settings['gasSchedule']['overhead']) * meter['gasPrice']
            expected = expected * (10_000 + (0 if meter['essential'] else settings['payMarkupBps'])) // 10_000
            expected += meter['workUnits'] * settings['workFeeWei']
            assert compensation == expected
            if not calibrated:
                assert compensation >= row['gasCostWei']
            row.update(measuredWork=meter, simulatedCompensationWei=simulated,
                       minimumPaymentWei=simulated * 8 // 10, keeperNetWei=compensation-row['gasCostWei'])
        else:
            assert not meters and compensation == 0
        packet['transactions'].append(row)
        save()
        return row

    def read_pending(payload):
        raw = rpc('eth_call', payload, 'pending')
        return decode(['uint256'], bytes.fromhex(raw[2:]))[0]

    def fingerprint():
        head = rpc('eth_getBlockByNumber', 'latest', False)
        state = dict(blockHash=head['hash'], blockNumber=head['number'],
                     managerCash=rpc('eth_getBalance', manager, 'latest'),
                     config='0x' + config().hex(),
                     cursor=number(manager, 'acquisitionCursor()'),
                     sequence=number(FWA, 'nextSequenceToProcess()'),
                     openCount=number(manager, 'openListingCount()'),
                     feeCredit=number(FWA, 'feeCredit(address)', ('address',), (manager,)),
                     packOwner=read(PACKS, 'ownerOf(uint256)', ('uint256',), (meta['pack'],), ('address',))[0])
        if args.multi:
            state['secondPackOwner']=read(PACKS, 'ownerOf(uint256)', ('uint256',),
                                          (meta['secondPack'],), ('address',))[0]
        return hashlib.sha256(json.dumps(state, sort_keys=True, default=str).encode()).hexdigest(), state

    def mine_to_request_deadline():
        for _ in range(32):
            if number(FWA, 'unsettledAcquisitionCount()') == 0:
                break
            sequence = number(FWA, 'nextSequenceToProcess()')
            request = number(FWA, 'requestIdAtSequence(uint64)', ('uint64',), (sequence,))
            fields = read(FWA, 'acquisitionMeta(uint256)', ('uint256',), (request,),
                          ('uint64', 'uint64', 'uint64', 'uint16', 'uint16', 'uint256'))
            gap = max(0, fields[1] + 1 - int(rpc('eth_blockNumber'), 16))
            assert gap <= 7201
            if gap:
                rpc('anvil_mine', hex(gap), hex(12))
            send(owner, FWA, 'processAcquisitions(uint256)', ('uint256',), (32,))
            assert number(FWA, 'nextSequenceToProcess()') > sequence
        assert number(FWA, 'unsettledAcquisitionCount()') == 0

    save()
    try:
        for _ in range(1800):
            if node.poll() is not None:
                raise RuntimeError('isolated anvil stopped')
            try:
                if rpc('eth_chainId') == '0x7a69':
                    break
            except (OSError, RuntimeError):
                time.sleep(1)
        else:
            raise RuntimeError('isolated fork startup timed out')
        assert rpc('anvil_nodeInfo')['hardFork'] == 'Osaka'
        alloc = {k.lower(): v for k, v in json.loads(Path(str(stem)+'-alloc.json').read_text()).items()}
        diffs = json.loads(Path(str(stem)+'-diff.json').read_text())
        critical = decode(['address[]', 'uint256[]', 'uint256[]', 'bytes[]'],
                          bytes.fromhex(meta['criticalAccountsAbi'][2:]))
        for address, balance, nonce, code in zip(*critical):
            alloc.setdefault(address.lower(), {}).update(balance=hex(balance), nonce=hex(nonce), code='0x'+code.hex())
        for address, account in diffs.items():
            if address.lower() == meta['harness'].lower():
                continue
            for slot, change in account['stateDiff'].items():
                saved = alloc.setdefault(address.lower(), {}).setdefault('storage', {}).get(slot, '0x0')
                assert int(saved, 16) == int(change['newValue'], 16)
                alloc[address.lower()]['storage'][slot] = change['newValue']
        current = int(rpc('eth_blockNumber'), 16)
        while current < meta['block']:
            current += 1
            rpc('evm_setNextBlockTimestamp', meta['timestamp']-(meta['block']-current))
            rpc('evm_mine')
        native = {address: dict(balance=account.get('balance', '0x0'), nonce=int(account.get('nonce','0x0'),0),
                                code=account.get('code','0x'), storage=account.get('storage', {}))
                  for address, account in alloc.items()}
        chunk = {}
        size = 0
        for address, account in native.items():
            size += len(json.dumps({address: account}))
            chunk[address] = account
            if size > 500_000:
                assert rpc('anvil_loadState', '0x'+json.dumps(dict(block=None,best_block_number=None,accounts=chunk)).encode().hex())
                chunk, size = {}, 0
        if chunk:
            assert rpc('anvil_loadState', '0x'+json.dumps(dict(block=None,best_block_number=None,accounts=chunk)).encode().hex())
        checked = 0
        for address,account in native.items():
            assert int(rpc('eth_getBalance',address,'latest'),16)==int(account['balance'],0)
            assert int(rpc('eth_getTransactionCount',address,'latest'),16)==account['nonce']
            assert rpc('eth_getCode',address,'latest').lower()==account['code'].lower()
            checked += 3
            for slot,value in account['storage'].items():
                assert int(rpc('eth_getStorageAt',address,slot,'latest'),16)==int(value,16)
                checked += 1
        packet['verifiedExportFields']=checked
        save()
        assert read(manager, 'owner()', returns=('address',))[0].lower() == owner.lower()
        assert int(rpc('eth_getBalance', manager, 'latest'),16) == meta['managerCashWei']
        assert number(manager, 'openListingCount()') == (2 if args.multi else 1)
        assert number(SHAPES, 'totalSupply()') == meta['shapeSupply']
        for actor, amount in ((owner, 5*10**18),(keeper, 10**18),(purchaser,10**18),(buyer,10**18)):
            code = rpc('eth_getCode', actor, 'latest')
            assert code == '0x' or (actor == purchaser and code.lower().startswith('0xef0100') and len(code)==48)
            if int(rpc('eth_getBalance', actor, 'latest'),16) < amount:
                rpc('anvil_setBalance', actor, hex(amount))
            rpc('anvil_impersonateAccount', actor)
        assert tuple(read(manager, 'getParams()', returns=(PARAMS_T,))[0]) != tuple(params_values(settings))
        send(owner, manager, f'setParams({PARAMS_T},bytes32)', (PARAMS_T,'bytes32'),
             (params_values(settings),config()), branch='prepare')
        assert tuple(read(manager, 'getParams()', returns=(PARAMS_T,))[0]) == tuple(params_values(settings))
        if not args.multi:
            send(purchaser, FWA, 'acceptDepositorBid(uint256)', ('uint256',), (meta['listing'],))
            mine_to_request_deadline()
        # An added listing remains genuine, funded and unique. FWA's real completed queue
        # makes the bounded scan cheaper than journal reads.
        initial = 2 if args.multi else 1
        for index in range(initial,args.scan_positions):
            backing = 21*10**16 + (index if args.multi else index)*10_000
            send(keeper, manager, 'build(uint256,uint256[],uint256,bytes32)',
                 ('uint256','uint256[]','uint256','bytes32'), (3,[backing],0,config()), paid=True)
        assert number(manager, 'openListingCount()') == args.scan_positions
        if not args.multi:
            now = int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)
            rpc('evm_setNextBlockTimestamp', now - now % 43_200 + 43_200 + 60)
            rpc('evm_mine')
            for _ in range(4):
                quote = read(FWA, 'quoteAcquisitionPrice()', returns=('uint256','uint256','uint256'))[2]
                send(buyer, FWA, 'acquire(address,uint256,uint256,uint256,uint256)',
                     ('address','uint256','uint256','uint256','uint256'), (buyer,1,0,0,10_000), value=2*quote)
            mine_to_request_deadline()
        if not args.no_fee_sweep_calibration:
            send(owner, manager, f'setParams({PARAMS_T},bytes32)', (PARAMS_T,'bytes32'),
                 (params_values(calibration),config()), branch='calibration')
        assert tuple(read(manager, 'getParams()', returns=(PARAMS_T,))[0]) == tuple(params_values(calibration))
        packet['prestate'] = fingerprint()[1]
        prepared = rpc('evm_snapshot')
        cases = [(resolved,price,base) for resolved in ((1,2) if args.multi else (1,))
                 for price,base in ((200_000_000,150_000_000),(500_000_000,450_000_000))]
        ordered = sorted((meta['listing'],meta['secondListing'])) if args.multi else [meta['listing']]
        for resolved,price, base in cases:
            assert rpc('evm_revert',prepared)
            prepared=rpc('evm_snapshot')
            branch=(f'multi-{args.scan_positions}-{resolved}-{price}' if args.multi else
                    f'scan-no-credit-{price}' if args.no_fee_sweep_calibration else f'scan-credit-{price}')
            ids = (ordered[-1:] if args.multi and args.resolve_later_first and resolved == 1
                   else ordered[:resolved])
            if args.multi:
                for listing in ids:
                    send(purchaser,FWA,'acceptDepositorBid(uint256)',('uint256',),(listing,),branch=branch)
            before,state=fingerprint()
            pair=rpc('evm_snapshot')
            paid=send(keeper, manager, 'sync(uint256[],uint256,uint256,bytes32)',
                      ('uint256[]','uint256','uint256','bytes32'), (ids,0,0,config()),
                      base=base,price=price,branch=branch,paid=True,count=2 if args.multi else 1)
            assert rpc('evm_revert',pair)
            restored,restored_state=fingerprint()
            assert before==restored and state==restored_state
            owner_row=send(owner,manager,'recover(uint256[],uint256)',('uint256[]','uint256'),
                           (ids,0),base=base,price=price,branch=branch,count=2 if args.multi else 1)
            meter=paid['measuredWork']
            owner_row['verifiedContext']=dict(gasAllowance=meter['gasAllowance'],
                                              workUnits=meter['workUnits'],
                                              pairedPaidHash=paid['receipt']['transactionHash'],
                                              prestateSha256=before)
            paid['prestateSha256']=before
            owner_row['prestateSha256']=before
            packet['contexts'].append(dict(branch=branch,prestateSha256=before,
                gasAllowance=meter['gasAllowance'],workUnits=meter['workUnits'],
                paidGasUsed=paid['gasUsed'],ownerGasUsed=owner_row['gasUsed'],
                paidHash=paid['receipt']['transactionHash'],ownerHash=owner_row['receipt']['transactionHash']))
            save()
        packet['status']='PASS'
    except Exception as error:
        packet['status']='FAIL'
        packet['error']=repr(error)
        raise
    finally:
        packet['nodeRetained']=node.poll() is None
        save()
    print(json.dumps(dict(status=packet['status'], contexts=packet['contexts']),indent=1))


if __name__ == '__main__':
    main()
