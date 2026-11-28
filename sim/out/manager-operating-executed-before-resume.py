#!/usr/bin/env python3
"""Continue an authenticated execution-derived overlay and bill local operations."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from eth_abi import encode, decode
from eth_account import Account
from eth_utils import keccak
from config import PARAMS_T, params_values
from rehearse_manager_r2 import request, sources, PUBLIC, FWA, SHAPES, PACKS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/receipts'
STEM = ROOT / 'sim/out/manager-operating-checkpoint'
ZERO = '0x' + '00' * 32
PRICE = 200_000_000
BASE = 150_000_000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def calldata(signature, types=(), values=()):
    return '0x' + (keccak(text=signature)[:4] + encode(types, values)).hex()


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def main():
    global PRICE, BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--port', type=int, default=18781)
    parser.add_argument('--reuse-export', action='store_true', help='Reuse a previously passing unchanged checkpoint after a zero-receipt failure')
    args = parser.parse_args()
    if not args.execute:
        raise SystemExit('Plan: one authentic-proof export, exact same-base import validation, then isolated billed operation branches. No public broadcast.')
    assert os.environ.get('CANDIDATE_RUN') == '1'
    path = OUT / 'manager-operating-receipts.json'
    previous_attempts=[]
    previous=None
    if path.exists():
        previous=json.loads(path.read_text())
        assert previous['status']=='FAIL' and not previous['transactions'], 'existing billed attempt needs explicit state reconciliation'
        if previous.get('ownedNodePid'):
            try: os.kill(previous['ownedNodePid'],0)
            except ProcessLookupError: pass
            else: raise AssertionError('preserve live owned node; inspect before continuation')
        attempt=1
        while (OUT/f'manager-operating-failed-attempt-{attempt}.json').exists():attempt+=1
        archive=OUT/f'manager-operating-failed-attempt-{attempt}.json'
        archive.write_bytes(path.read_bytes())
        old_log=OUT/'manager-operating-export.log'
        archived_log=OUT/f'manager-operating-failed-attempt-{attempt}.log'
        archived_log.write_bytes(old_log.read_bytes())
        previous_attempts=previous.get('previousAttempts',[])+[dict(path=str(archive.relative_to(ROOT)),sha256=sha(archive),log=str(archived_log.relative_to(ROOT)),logSha256=sha(archived_log))]
    if args.reuse_export:
        assert previous and previous['export']['exitStatus']==0 and previous['contractSourceSha256']==sources()
        assert all(sha(ROOT/name)==digest for name,digest in previous['checkpoint']['files'].items()), 'checkpoint drift'
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', args.port))
    report = dict(status='RUNNING', command=[sys.executable, *sys.argv], transactions=[],
                  contractSourceSha256=sources(), scriptSha256=sha(__file__), publicTransactions=0,previousAttempts=previous_attempts,
                  limitations=['Historical authenticated setup is not billed and is not a production deployment rehearsal.',
                               'Local chain only; purchaser/admin role impersonation uses actual external entry points, never the VRF coordinator.',
                               'The .00025 ETH mint fee is an agent-selected fork sensitivity, not an approved public fee.',
                               'One genuinely selected returned pack; multi-pack fresh renewal is not measured.'])
    def save():
        path.write_text(json.dumps(report, indent=1) + '\n')
    save()
    env = dict(os.environ, EXPORT_MANAGER_OPERATING='true')
    command = ['forge', 'test', '--match-path', 'test/fork/ManagerOperationsCheckpoint.t.sol',
               '--match-test', 'test_exportAuthenticatedAllocatedCheckpoint', '--rpc-url', PUBLIC,
               '--fork-retries', '30', '--fork-retry-backoff', '5000', '--compute-units-per-second', '100', '-vv']
    if args.reuse_export:
        report['export']=previous['export'] | dict(reusedPassingExport=True)
    else:
        start = time.monotonic()
        result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True)
        log = OUT / 'manager-operating-export.log'
        log.write_text(result.stdout + result.stderr)
        report['export'] = dict(command=command, exitStatus=result.returncode,
                                elapsedSeconds=time.monotonic() - start, log=str(log.relative_to(ROOT)), logSha256=sha(log))
    if report['export']['exitStatus']:report['status']='FAIL'
    report['exportSourceSha256']={name:sha(ROOT/name) for name in ('test/fork/ManagerOperationsCheckpoint.t.sol','test/fork/ForkMainRenewal.t.sol','test/fork/ForkBase.sol','test/fixtures/completion-selection.json')}
    save()
    assert report['export']['exitStatus'] == 0, 'checkpoint export failed; no node or billed transactions started'
    alloc_path = Path(str(STEM) + '-alloc.json')
    meta_path = Path(str(STEM) + '-metadata.json')
    diff_path = Path(str(STEM) + '-diff.json')
    meta = json.loads(meta_path.read_text())
    alloc = {k.lower(): v for k, v in json.loads(alloc_path.read_text()).items()}
    diff = json.loads(diff_path.read_text())
    writes = {(address.lower(),slot.lower()):change['newValue'].lower()
              for address,account in diff.items() if address.lower()!=meta['harness'].lower()
              for slot,change in account['stateDiff'].items()}
    assert writes, 'empty recorded write witness'
    critical=decode(['address[]','uint256[]','uint256[]','bytes[]'],bytes.fromhex(meta['criticalAccountsAbi'][2:]))
    accounts={address.lower():dict(address=address,balance=str(balance),nonce=nonce,code='0x'+code.hex())
              for address,balance,nonce,code in zip(*critical)}
    for (address, slot), value in writes.items():
        assert address in alloc, ('changed account missing', address)
        storage = {k.lower(): v.lower() for k, v in alloc[address].get('storage', {}).items()}
        assert slot in storage and storage[slot] == value, ('changed slot missing from dump', address, slot, value)
    for address, a in accounts.items():
        # Empty accounts are deliberately omitted by Foundry; their unchanged base is checked below.
        if address in alloc:
            d = alloc[address]
            assert int(d.get('balance', 0), 0) == int(a['balance'])
            assert int(d.get('nonce', '0x0'), 0) == a['nonce']
            assert d.get('code', '0x').lower() == a['code'].lower()
    report['checkpoint'] = dict(metadata=meta, files={str(p.relative_to(ROOT)): sha(p) for p in
                                 (alloc_path, meta_path, diff_path)}, uniqueWrittenSlots=len(writes),
                                 zeroWrittenSlots=sum(int(v, 16) == 0 for v in writes.values()), touchedAccounts=len(accounts))
    values = json.loads((ROOT / 'deploy/manager.json').read_text())
    assert bytes.fromhex(meta['paramsAbi'][2:]) == encode([PARAMS_T], [params_values(values)]), 'export settings differ from manager values'
    tx = request(PUBLIC, 'eth_getTransactionByHash', meta['requestTx'])
    header = request(PUBLIC, 'eth_getBlockByNumber', tx['blockNumber'], False)
    index = int(tx['transactionIndex'], 16)
    assert header['transactions'][index].lower() == meta['requestTx'].lower()
    base_args = ['--fork-transaction-hash', header['transactions'][index - 1]] if index else ['--fork-block-number', str(meta['requestBlock'] - 1)]
    report['base'] = dict(requestTransaction=tx, requestHeader=header,
                          precedingTransaction=header['transactions'][index - 1] if index else None, anvilArguments=base_args)
    work = Path(tempfile.mkdtemp(prefix='manager-operating-'))
    url = f'http://127.0.0.1:{args.port}'
    node_log = open(work / 'anvil.log', 'w')
    node = subprocess.Popen(['anvil', '--host', '127.0.0.1', '--port', str(args.port), '--accounts', '0',
                             '--chain-id', '31337', '--hardfork', 'cancun', '--enable-tx-gas-limit', '--gas-limit', str(int(header['gasLimit'],16)),
                             '--fork-url', PUBLIC, *base_args, '--retries', '30', '--fork-retry-backoff', '5000', '--silent'],
                            stdout=node_log, stderr=subprocess.STDOUT, start_new_session=True)
    report.update(rpc=url, chainId=31337, ownedNodePid=node.pid, workDirectory=str(work))
    save()
    def rpc(method, *params):
        assert url == f'http://127.0.0.1:{args.port}'
        return request(url, method, *params)
    def batch(calls):
        body=[dict(jsonrpc='2.0', id=i, method=m, params=p) for i,(m,p) in enumerate(calls)]
        req=urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=120) as response: rows=json.load(response)
        rows=sorted(rows,key=lambda r:r['id'])
        assert all('error' not in r for r in rows), rows
        return [r['result'] for r in rows]
    def read(target, signature, types=(), vals=(), returns=('uint256',)):
        raw = rpc('eth_call', dict(to=target, data=calldata(signature, types, vals), gasPrice=hex(PRICE)), 'latest')
        return decode(returns, bytes.fromhex(raw[2:]))
    def number(target, signature, types=(), vals=()):
        return read(target, signature, types, vals)[0]
    manager = meta['manager']
    def config():
        return read(manager, 'configurationHash()', returns=('bytes32',))[0]
    def view_checks():
        assert int(rpc('eth_getBalance', manager, 'latest'), 16) == meta['managerCashWei']
        assert rpc('eth_call', dict(to=manager, data=calldata('getParams()')), 'latest').lower() == meta['paramsAbi'].lower()
        assert config().hex() == meta['configurationHash'][2:]
        assert rpc('eth_call', dict(to=FWA, data=calldata('listings(uint256)', ['uint256'], [meta['listing']])), 'latest').lower() == meta['listingAbi'].lower()
        for target, sig, expected in ((manager, 'openListingCount()', meta['openListingCount']),
                                     (FWA, 'unsettledAcquisitionCount()', meta['unsettledAcquisitionCount']),
                                     (SHAPES, 'totalSupply()', meta['shapeSupply']), (SHAPES, 'mintFee()', meta['mintFeeWei'])):
            assert number(target, sig) == expected, sig
        assert number(FWA, 'feeCredit(address)', ['address'], [manager]) == meta['feeCreditWei']
        assert read(PACKS, 'ownerOf(uint256)', ['uint256'], [meta['pack']], ['address'])[0].lower() == meta['packOwner'].lower()
    owner = Account.from_key(keccak(text='pack-vault-test-main-renewal-owner'))
    assert owner.address.lower() == meta['owner'].lower()
    keeper = Account.create()
    signers = {owner.address.lower(): owner, keeper.address.lower(): keeper}
    report['actors'] = dict(owner=owner.address, keeper=keeper.address, purchaser=meta['purchaser'])
    paid_topic = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()
    branch = 'import'
    def send(sender, target, signature, types=(), vals=(), operation=None, quoted_pay=0):
        assert int(rpc('eth_chainId'), 16) == 31337 and rpc('web3_clientVersion').lower().startswith('anvil/')
        rpc('anvil_setNextBlockBaseFeePerGas', hex(BASE))
        data=calldata(signature,types,vals)
        request_tx=dict(from_=sender, to=target, data=data, gasPrice=hex(PRICE))
        request_tx['from']=request_tx.pop('from_')
        estimate=int(rpc('eth_estimateGas',request_tx),16)
        gas=(estimate*5+3)//4
        assert gas <= 16_777_216
        if sender.lower() in signers:
            signed=signers[sender.lower()].sign_transaction(dict(chainId=31337, nonce=int(rpc('eth_getTransactionCount',sender,'latest'),16),
                                                               to=target, value=0, data=data, gas=gas, gasPrice=PRICE))
            txhash=rpc('eth_sendRawTransaction','0x'+signed.raw_transaction.hex())
        else:
            # Only the real purchaser and Shapes admin may use external-role impersonation.
            assert sender.lower() in {meta['purchaser'].lower(), report.get('feeAdmin','').lower()}
            rpc('anvil_impersonateAccount',sender)
            txhash=rpc('eth_sendTransaction',request_tx|dict(gas=hex(gas)))
            rpc('anvil_stopImpersonatingAccount',sender)
        report.setdefault('submissions',[]).append(dict(branch=branch,operation=operation or signature.split('(')[0],hash=txhash,gasEstimate=estimate,signedGasLimit=gas))
        save()
        receipt=None
        for _ in range(240):
            receipt=rpc('eth_getTransactionReceipt',txhash)
            if receipt is not None:break
            time.sleep(.25)
        assert receipt and int(receipt['status'],16)==1, (operation,txhash,receipt)
        transaction=rpc('eth_getTransactionByHash',txhash)
        block=rpc('eth_getBlockByHash',receipt['blockHash'],False)
        paid=sum(int(log['data'],16) for log in receipt['logs'] if log['address'].lower()==manager.lower() and log['topics'][0].lower()==paid_topic)
        assert paid == quoted_pay, ('payment changed', operation, paid, quoted_pay)
        item=dict(branch=branch,operation=operation or signature.split('(')[0],actor=sender,gasUsed=int(receipt['gasUsed'],16),
                  effectiveGasPrice=int(receipt['effectiveGasPrice'],16),blockBaseFeeWei=int(block['baseFeePerGas'],16),
                  gasCostWei=int(receipt['gasUsed'],16)*int(receipt['effectiveGasPrice'],16),compensationWei=paid,
                  gasEstimate=estimate,signedGasLimit=gas,
                  transaction=transaction,receipt=receipt)
        assert item['effectiveGasPrice']==PRICE and item['blockBaseFeeWei']==BASE
        report['transactions'].append(item);save()
        return item
    def paid(signature, types, vals, pay_index, operation):
        zero=list(vals);zero[pay_index]=0
        pay=read(manager,signature,types,zero)[0]
        assert pay>0, ('positive paid work not reached',operation)
        zero[pay_index]=pay
        return send(keeper.address,manager,signature,types,zero,operation, pay)
    try:
        for _ in range(180):
            if node.poll() is not None: raise RuntimeError('owned node exited: '+(work/'anvil.log').read_text()[-3000:])
            try:
                if int(rpc('eth_chainId'),16)==31337:break
            except (RuntimeError,OSError):time.sleep(1)
        else: raise RuntimeError('owned node startup timed out')
        assert rpc('anvil_nodeInfo')['forkConfig']['forkUrl']==PUBLIC
        rpc('evm_setBlockGasLimit',hex(16_777_216))
        current=int(rpc('eth_blockNumber'),16)
        assert current <= meta['block']
        while current < meta['block']:
            current+=1
            rpc('evm_setNextBlockTimestamp', meta['timestamp']-(meta['block']-current))
            rpc('anvil_setNextBlockBaseFeePerGas',hex(meta['basefee']))
            rpc('evm_mine')
        assert int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)==meta['timestamp']
        native=dict(block=None,best_block_number=None,accounts={address:dict(nonce=int(a.get('nonce','0x0'),0),
                    balance=a['balance'],code=a.get('code','0x'),storage=a.get('storage',{})) for address,a in alloc.items()})
        assert rpc('anvil_loadState', '0x'+json.dumps(native).encode().hex())
        checks=[];expected=[]
        for address,a in accounts.items():
            checks += [('eth_getBalance',[address,'latest']),('eth_getTransactionCount',[address,'latest']),('eth_getCode',[address,'latest'])]
            expected += [int(a['balance']),a['nonce'],a['code'].lower()]
        for start in range(0,len(checks),90):
            results=batch(checks[start:start+90])
            for i,value in enumerate(results,start):
                wanted=expected[i]
                assert (value.lower() if isinstance(wanted,str) else int(value,16))==wanted, ('account import mismatch',checks[i],value,wanted)
        # Verify every allocation row, including factory, implementation and library code.
        all_checks=[];all_expected=[]
        for address,a in alloc.items():
            all_checks += [('eth_getBalance',[address,'latest']),('eth_getTransactionCount',[address,'latest']),('eth_getCode',[address,'latest'])]
            all_expected += [int(a['balance'],0),int(a.get('nonce','0x0'),0),a.get('code','0x').lower()]
        for start in range(0,len(all_checks),90):
            for i,value in enumerate(batch(all_checks[start:start+90]),start):
                wanted=all_expected[i]
                assert (value.lower() if isinstance(wanted,str) else int(value,16))==wanted, ('allocation import mismatch',all_checks[i])
        entries=list(writes.items())
        for start in range(0,len(entries),100):
            group=entries[start:start+100]
            actual=batch([('eth_getStorageAt',[address,slot,'latest']) for (address,slot),_ in group])
            assert all(int(a,16)==int(value,16) for a,(_,value) in zip(actual,group)), 'storage import mismatch'
        view_checks()
        report['checkpoint']['importVerified']=True
        report['checkpoint']['importBlock']=rpc('eth_getBlockByNumber','latest',False)
        for address in (owner.address,keeper.address):
            assert rpc('eth_getCode',address,'latest')=='0x'
            assert int(rpc('eth_getTransactionCount',address,'latest'),16)==0
            assert int(rpc('eth_getBalance',address,'latest'),16)==0
            rpc('anvil_setBalance',address,hex(10**18))
        assert rpc('eth_getCode',meta['purchaser'],'latest')=='0x'
        save()
        native_state=rpc('anvil_dumpState')
        native_path=ROOT/'sim/out/manager-operating-native-checkpoint.hex'
        native_path.write_text(native_state+'\n')
        report['nativeCheckpoint']=dict(path=str(native_path.relative_to(ROOT)),sha256=sha(native_path))
        origin=rpc('evm_snapshot');report['originSnapshot']=origin;save()
        for price,base in ((200_000_000,150_000_000),(500_000_000,450_000_000)):
            PRICE,BASE=price,base
            if price!=200_000_000:
                assert rpc('evm_revert',origin)
                origin=rpc('evm_snapshot');report['originSnapshot']=origin;save()
            rpc('anvil_setNextBlockBaseFeePerGas',hex(BASE));rpc('evm_mine')
            price_origin=rpc('evm_snapshot')
            for fee in (10**15,5*10**14,250_000_000_000_000):
                if fee != 10**15:
                    assert rpc('evm_revert',price_origin);price_origin=rpc('evm_snapshot')
                    admin=read(SHAPES,'admin()',returns=('address',))[0]
                    assert rpc('eth_getCode',admin,'latest')=='0x','fee admin is not EOA'
                    report['feeAdmin']=admin
                    if int(rpc('eth_getBalance',admin,'latest'),16)<10**16:rpc('anvil_setBalance',admin,hex(10**18))
                    branch='fee-admin-sensitivity'
                    send(admin,SHAPES,'setMintFee(uint256)',['uint256'],[fee],'setMintFee')
                fee_origin=rpc('evm_snapshot')
                for mode in (0,1):
                    if mode:
                        assert rpc('evm_revert',fee_origin)
                    branch=f'gas-{PRICE}-mint-{fee}-'+('fresh' if mode==0 else 'reuse')
                    if mode:
                        adjusted=values|dict(renewalMode=1)
                        send(owner.address,manager,f'setParams({PARAMS_T},bytes32)',[PARAMS_T,'bytes32'],[params_values(adjusted),config()],'setParams')
                    # Collect actual nonzero earnings without keeper compensation.
                    ids=[number(manager,'openListingAt(uint256)',['uint256'],[i]) for i in range(number(manager,'openListingCount()'))]
                    active=[i for i in ids if i!=meta['listing']]
                    before=int(rpc('eth_getBalance',manager,'latest'),16)
                    send(owner.address,manager,'harvest(uint256[],uint256)',['uint256[]','uint256'],[active,0],'harvest')
                    collected=int(rpc('eth_getBalance',manager,'latest'),16)-before
                    assert collected>0,'standalone harvest must collect actual nonzero cash'
                    report.setdefault('harvestAmounts',[]).append(dict(branch=branch,collectedWei=collected));save()
                    sig='sync(uint256[],uint256,uint256,bytes32)';types=['uint256[]','uint256','uint256','bytes32']
                    paid(sig,types,[[],0,0,config()],2,'syncAllocated')
                    send(meta['purchaser'],FWA,'acceptDepositorBid(uint256)',['uint256'],[meta['listing']],'acceptDepositorBid')
                    paid(sig,types,[[meta['listing']],0,0,config()],2,'syncResolved')
                    now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)
                    rpc('evm_setNextBlockTimestamp',now-now%43200+43200+60)
                    rpc('evm_mine')
                    send(owner.address,FWA,'processAcquisitions(uint256)',['uint256'],[32],'processAcquisitions')
                    assert number(FWA,'unsettledAcquisitionCount()')==0
                    supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()')
                    if mode==0:
                        paid('renew(uint256[],uint256[],uint256[],uint256,bytes32)',
                             ['uint256[]','uint256[]','uint256[]','uint256','bytes32'],[[meta['pack']],[21*10**16],[],0,config()],3,'renew')
                        assert number(SHAPES,'pendingFees()')-creator==3*fee
                    else:
                        paid('list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[[21*10**16],0,config()],1,'list')
                        assert number(SHAPES,'pendingFees()')==creator
                    assert number(SHAPES,'totalSupply()')==supply
                    assert not number(manager,'renewalEligible(uint256)',['uint256'],[meta['pack']])
                    assert number(manager,'openListingCount()')==meta['openListingCount']
        assert report['contractSourceSha256']==sources(), 'runtime source changed during calibration'
        report['status']='PASS';save()
        old=OUT/'manager-r2-cost-calibration.json'
        baseline=json.loads(old.read_text())
        gas=dict(baseline['gas_proxy'])
        aliases=dict(renew='renew',list='list',sync='syncAllocated',harvest='harvest')
        for key,operation in aliases.items():gas[key]=max(t['gasUsed'] for t in report['transactions'] if t['operation']==operation)
        gas['sync']=max(t['gasUsed'] for t in report['transactions'] if t['operation'] in ('syncAllocated','syncResolved'))
        old_receipts=json.loads((ROOT/baseline['receipts']).read_text())
        estimates={key:max(int(t['transaction']['gas'],16) for t in old_receipts['transactions'] if t['operation']==operation)
                   for key,operation in dict(create='create',setExiting='setExiting',withdraw='withdraw',unlist='recoverUnlist',liquidate='recoverLiquidate',recover_sync='recover',processAcquisitions='processAcquisitions',build='build').items()}
        for key,operation in aliases.items():estimates[key]=max(t['gasEstimate'] for t in report['transactions'] if t['operation']==operation)
        estimates['sync']=max(t['gasEstimate'] for t in report['transactions'] if t['operation'] in ('syncAllocated','syncResolved'))
        calibration=dict(method='Actual local receipts after independently validated authentic execution-derived checkpoint continuation',
             contract_source_sha256=report['contractSourceSha256'],source_sha256=report['contractSourceSha256'],
             receipt_inputs=[dict(path=str(old.relative_to(ROOT)),sha256=sha(old)),dict(path=str(path.relative_to(ROOT)),sha256=sha(path))],
             receipts=str(path.relative_to(ROOT)),receipts_sha256=sha(path),gas_proxy=gas,gas_estimate_proxy=estimates,
             gas_estimate_provenance='New samples record actual eth_estimateGas before signing. R2 operations conservatively use the actual signed transaction gas limit, without dividing by a padding factor.',
             measurements=report['transactions'],unmeasured_operations=['multi-pack authenticated renewal','multi-pack reuse listing'],
             limitations=report['limitations'])
        (OUT/'manager-operating-cost-calibration.json').write_text(json.dumps(calibration,indent=1)+'\n')
        print(json.dumps(dict(status='PASS',transactions=len(report['transactions']),gas_proxy=gas),indent=1))
    except Exception as exc:
        report.update(status='FAIL',error=str(exc));save();raise
    finally:
        # Preserve the owned node and all branch receipts for diagnosis/readback.
        node_log.flush()


if __name__=='__main__':
    main()
