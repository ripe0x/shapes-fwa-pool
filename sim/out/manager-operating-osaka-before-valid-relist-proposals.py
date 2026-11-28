#!/usr/bin/env python3
"""Bill Osaka operations from immutable authenticated execution-derived checkpoints."""
import argparse
import gzip
import hashlib
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
from eth_abi import encode, decode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
from config import PARAMS_T, params_values
from rehearse_manager_r2 import PUBLIC, FWA, SHAPES, PACKS, sources

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/receipts'
PRICE, BASE = 200_000_000, 150_000_000


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def data(signature, types=(), values=()):
    return '0x' + (keccak(text=signature)[:4] + encode(types, values)).hex()


def main():
    global PRICE, BASE
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--finish-matrix', action='store_true', help='Continue the preserved completed base sweep with list curves and fresh-build estimates')
    parser.add_argument('--attach', action='store_true', help='Continue a zero-receipt startup/import failure on its preserved owned node')
    parser.add_argument('--port', type=int, default=18783)
    args = parser.parse_args()
    if args.finish_matrix:args.attach=True
    if not args.execute:
        raise SystemExit('Plan: validate archived authenticated allocated/returned native checkpoints; one owned Osaka node; actual signed local samples and real fork-only EOA admin setters. No public broadcast.')
    assert os.environ.get('CANDIDATE_RUN') == '1'
    evidence = OUT / 'manager-operating-osaka-receipts.json'
    previous=None
    if evidence.exists():
        previous=json.loads(evidence.read_text())
        assert args.attach and previous['status']=='FAIL' and (args.finish_matrix or (not previous['transactions'] and not previous['submissions'])), 'reconcile billed attempts before continuation'
        attempt=1
        while (OUT/f'manager-operating-osaka-failed-attempt-{attempt}.json').exists():attempt+=1
        preserved=OUT/f'manager-operating-osaka-failed-attempt-{attempt}.json'
        preserved.write_bytes(evidence.read_bytes())
    old_path = OUT / 'manager-operating-receipts.json'
    old = json.loads(old_path.read_text())
    assert old['contractSourceSha256'] == sources()
    archive = OUT / 'manager-operating-cancun-receipts.json'
    if not archive.exists():archive.write_text(json.dumps(old | dict(executionHardfork='Cancun', excludedFromFinalGasCalibration=True), indent=1) + '\n')
    allocated_json = ROOT / 'sim/out/manager-operating-native-checkpoint.json'
    allocated_hex = ROOT / old['nativeCheckpoint']['path']
    assert sha(allocated_hex) == old['nativeCheckpoint']['sha256']
    returned_json = ROOT / 'sim/out/manager-operating-returned-native.json'
    returned_hex = ROOT / 'sim/out/manager-operating-returned-native.hex'
    for name, digest in old['returnedNativeCheckpoint']['files'].items():
        assert sha(ROOT / name) == digest
    for plain, compressed in ((allocated_json, allocated_hex), (returned_json, returned_hex)):
        assert plain.read_bytes() == gzip.decompress(bytes.fromhex(compressed.read_text().strip()[2:]))
    meta = old['checkpoint']['metadata']
    manager = meta['manager']
    values = json.loads((ROOT / 'deploy/manager.json').read_text())
    assert encode([PARAMS_T], [params_values(values)]).hex() == meta['paramsAbi'][2:]
    inputs = {str(p.relative_to(ROOT)): sha(p) for p in (allocated_json, allocated_hex, returned_json, returned_hex, archive)}
    inputs.update(old['checkpoint']['files'])
    if not args.attach:
        with socket.socket() as available:available.bind(('127.0.0.1', args.port))
    work = Path(tempfile.mkdtemp(prefix='manager-operating-osaka-'))
    url = f'http://127.0.0.1:{args.port}'
    command = ['anvil', '--host', '127.0.0.1', '--port', str(args.port), '--accounts', '0', '--chain-id', '31337',
               '--hardfork', 'osaka', '--enable-tx-gas-limit', '--gas-limit', '60000000', '--fork-url', PUBLIC,
               '--fork-block-number', str(meta['requestBlock'] - 1), '--retries', '30', '--fork-retry-backoff', '5000', '--silent']
    if args.attach:
        assert previous['rpc']==url
        identity=subprocess.check_output(['ps','-p',str(previous['ownedNodePid']),'-o','command='],text=True)
        assert f'--port {args.port}' in identity and '--hardfork osaka' in identity
        node=None;node_pid=previous['ownedNodePid'];work=Path(previous['workDirectory'])
    else:
        node = subprocess.Popen(command, stdout=open(work / 'anvil.log', 'w'), stderr=subprocess.STDOUT, start_new_session=True)
        node_pid=node.pid
    owner = Account.from_key(keccak(text='pack-vault-test-main-renewal-owner'))
    assert owner.address.lower() == meta['owner'].lower()
    keeper = Account.create()
    signers = {owner.address.lower(): owner, keeper.address.lower(): keeper}
    report = dict(status='RUNNING', phase='startup', command=[sys.executable, *sys.argv], scriptSha256=sha(__file__),
                  contractSourceSha256=sources(), input_sha256=inputs, executionHardfork='Osaka', compilerTarget='Cancun',
                  rpc=url, chainId=31337, publicTransactions=0, ownedNodePid=node_pid, nodeCommand=command,
                  workDirectory=str(work), transactions=[], submissions=[], checkpointLoads=[], externalEOAs={},
                  actors=dict(owner=owner.address, keeper=keeper.address, purchaser=meta['purchaser']),
                  limitations=['Authenticated request/proof setup is execution-derived and not billed as a production deployment.',
                               'Historical Cancun samples are preserved and excluded from this gas calibration.',
                               'Independent restored branches are samples, not one cash lifecycle or full-period return.',
                               '.00025 ETH is an agent-selected fork sensitivity, not an approved public mint fee.',
                               'Multi-pack fresh renewal and operating work beyond the measured sizes remain unmeasured.'])
    if args.finish_matrix:
        assert len(previous.get('completedBranches',[]))==12 and len(previous['transactions'])==44
        report=previous
        report.update(status='RUNNING',phase='finish-list-matrix',matrixCompletionCommand=[sys.executable,*sys.argv],matrixCompletionScriptSha256=sha(__file__))
        report.pop('error',None)
        report.setdefault('additionalKeepers',[]).append(keeper.address)
    branch = 'startup'
    def save():
        evidence.write_text(json.dumps(report, indent=1) + '\n')
    save()
    def rpc(method, *params):
        payload = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
        req = urllib.request.Request(url, payload, {'Content-Type': 'application/json'})
        # Mutating requests are never retried after an uncertain response.
        with urllib.request.urlopen(req, timeout=600) as response:
            result = json.load(response)
        if 'error' in result:
            raise RuntimeError(method + ': ' + json.dumps(result['error']))
        return result['result']
    def batch(calls):
        payload = [dict(jsonrpc='2.0', id=i, method=m, params=p) for i, (m, p) in enumerate(calls)]
        req = urllib.request.Request(url, json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=120) as response:
            rows = sorted(json.load(response), key=lambda r: r['id'])
        assert all('error' not in r for r in rows), rows
        return [r['result'] for r in rows]
    def read(target, signature, types=(), vals=(), returns=('uint256',)):
        raw = rpc('eth_call', dict(to=target, data=data(signature, types, vals), **{'from':keeper.address}, gasPrice=hex(PRICE)), 'latest')
        return decode(returns, bytes.fromhex(raw[2:]))
    def number(target, signature, types=(), vals=()):
        return read(target, signature, types, vals)[0]
    def config():
        return read(manager, 'configurationHash()', returns=('bytes32',))[0]
    def prime(price, base):
        global PRICE, BASE
        PRICE, BASE = price, base
        rpc('anvil_setNextBlockBaseFeePerGas', hex(BASE)); rpc('evm_mine')
        info = rpc('anvil_nodeInfo')
        assert info['hardFork'] == 'Osaka' and info['environment']['chainId'] == 31337
        assert int(rpc('eth_getBlockByNumber', 'latest', False)['baseFeePerGas'], 16) == BASE
    def fresh_keeper():
        assert rpc('eth_getCode', keeper.address, 'latest') == '0x'
        assert int(rpc('eth_getTransactionCount', keeper.address, 'latest'), 16) == 0
        assert int(rpc('eth_getBalance', keeper.address, 'latest'), 16) == 0
        rpc('anvil_setBalance', keeper.address, hex(10**18))
    def external_eoa(address, role):
        code = rpc('eth_getCode', address, 'latest')
        delegated = len(code) == 48 and code.lower().startswith('0xef0100')
        assert code == '0x' or delegated, (role, 'requires a real EOA, not a contract caller', address)
        report['externalEOAs'][address.lower()] = dict(role=role, code=code, delegated=delegated)
        if int(rpc('eth_getBalance', address, 'latest'), 16) < 10**16:
            rpc('anvil_setBalance', address, hex(10**18))
        return address
    paid_topic = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()
    def send(sender, target, signature, types=(), vals=(), operation=None, pay=0, work_count=1, value=0):
        assert rpc('anvil_nodeInfo')['hardFork'] == 'Osaka'
        rpc('anvil_setNextBlockBaseFeePerGas', hex(BASE))
        target = to_checksum_address(target)
        tx = dict(to=target, data=data(signature, types, vals), gasPrice=hex(PRICE), value=hex(value), **{'from':sender})
        estimate = int(rpc('eth_estimateGas', tx), 16)
        limit = (estimate * 5 + 3) // 4
        assert limit <= 16_777_216
        if sender.lower() in signers:
            signed = signers[sender.lower()].sign_transaction(dict(chainId=31337, nonce=int(rpc('eth_getTransactionCount', sender, 'latest'), 16),
                to=target, value=value, data=tx['data'], gas=limit, gasPrice=PRICE))
            txhash = rpc('eth_sendRawTransaction', '0x' + signed.raw_transaction.hex())
        else:
            assert sender.lower() in report['externalEOAs'] or sender.lower() == meta['purchaser'].lower()
            rpc('anvil_impersonateAccount', sender)
            txhash = rpc('eth_sendTransaction', tx | dict(gas=hex(limit)))
            rpc('anvil_stopImpersonatingAccount', sender)
        report['submissions'].append(dict(branch=branch, operation=operation or signature.split('(')[0], hash=txhash,
                                           gasEstimate=estimate, signedGasLimit=limit)); save()
        receipt = None
        for _ in range(240):
            receipt = rpc('eth_getTransactionReceipt', txhash)
            if receipt is not None: break
            time.sleep(.25)
        assert receipt and int(receipt['status'], 16) == 1, (operation, txhash, receipt)
        transaction = rpc('eth_getTransactionByHash', txhash)
        header = rpc('eth_getBlockByHash', receipt['blockHash'], False)
        actual_pay = sum(int(log['data'], 16) for log in receipt['logs'] if log['address'].lower() == manager.lower() and log['topics'][0].lower() == paid_topic)
        assert actual_pay == pay
        item = dict(branch=branch, operation=operation or signature.split('(')[0], workCount=work_count, actor=sender,
                    executionHardfork='Osaka', gasUsed=int(receipt['gasUsed'], 16), gasEstimate=estimate, signedGasLimit=limit,
                    effectiveGasPrice=int(receipt['effectiveGasPrice'], 16), blockBaseFeeWei=int(header['baseFeePerGas'], 16),
                    gasCostWei=int(receipt['gasUsed'], 16) * int(receipt['effectiveGasPrice'], 16), compensationWei=actual_pay,
                    transaction=transaction, receipt=receipt, rpc=url,targetAccount=manager)
        assert item['effectiveGasPrice'] == PRICE and item['blockBaseFeeWei'] == BASE and item['gasUsed'] <= 16_777_216
        report['transactions'].append(item); save()
        return item
    def paid(signature, types, vals, index, operation, count=1):
        quoted = list(vals); quoted[index] = 0
        pay = read(manager, signature, types, quoted)[0]
        assert pay > 0, ('paid work not reached', operation)
        quoted[index] = pay
        return send(keeper.address, manager, signature, types, quoted, operation, pay, count)
    def load_checkpoint(name, path):
        report['phase'] = 'load-' + name; save()
        state = json.loads(path.read_text())
        checks=[]; expected=[]
        for address, account in state['accounts'].items():
            checks += [('eth_getBalance',[address,'latest']),('eth_getTransactionCount',[address,'latest']),('eth_getCode',[address,'latest'])]
            expected += [int(account['balance'],0),int(account['nonce']),account['code'].lower()]
            for slot, value in account['storage'].items():
                checks.append(('eth_getStorageAt',[address,slot,'latest'])); expected.append(int(value,16))
        already_loaded=False
        if args.attach and name=='allocated':
            already_loaded=True
            for start in range(0,len(checks),100):
                for index,actual in enumerate(batch(checks[start:start+100]),start):
                    wanted=expected[index]
                    if (actual.lower() if isinstance(wanted,str) else int(actual,16))!=wanted:already_loaded=False
        if not already_loaded:
            # The native rows are unchanged; chunk only the transport to fit Anvil's2MB HTTP limit.
            chunks=[];current={};size=0
            for address,account in state['accounts'].items():
                cost=len(json.dumps({address:account}))
                if current and size+cost>600_000:chunks.append(current);current={};size=0
                current[address]=account;size+=cost
            if current:chunks.append(current)
            for i,accounts in enumerate(chunks):
                payload=dict(block=None,best_block_number=None,accounts=accounts)
                encoded=json.dumps(payload).encode();assert len(encoded)*2+1000<2_000_000
                report['phase']=f'load-{name}-chunk-{i+1}-of-{len(chunks)}';save()
                assert rpc('anvil_loadState','0x'+encoded.hex())
            metadata=state|dict(accounts={})
            compressed=gzip.compress(json.dumps(metadata).encode(),mtime=0)
            assert len(compressed)*2+1000<2_000_000
            assert rpc('anvil_loadState','0x'+compressed.hex())
            assert rpc('anvil_nodeInfo')['hardFork'] == 'Osaka'
        for start in range(0,len(checks),100):
            for index, actual in enumerate(batch(checks[start:start+100]),start):
                wanted=expected[index]
                assert (actual.lower() if isinstance(wanted,str) else int(actual,16)) == wanted, ('checkpoint mismatch',name,checks[index])
        # Priced eth_call validates sender funds too; only this fresh external wallet is funded.
        fresh_keeper()
        assert read(manager,'owner()',returns=('address',))[0].lower()==owner.address.lower()
        assert number(FWA,'unsettledAcquisitionCount()')==(meta['unsettledAcquisitionCount'] if name=='allocated' else 0)
        assert number(manager,'renewalEligible(uint256)',['uint256'],[meta['pack']])==(name=='returned')
        report['checkpointLoads'].append(dict(name=name,path=str(path.relative_to(ROOT)),sha256=sha(path),accounts=len(state['accounts']),
                                            verifiedFields=len(checks),nodeInfo=rpc('anvil_nodeInfo')));save()
    def set_fee(fee):
        if number(SHAPES,'mintFee()') != fee:
            admin=external_eoa(read(SHAPES,'admin()',returns=('address',))[0],'Shapes mint-fee admin')
            send(admin,SHAPES,'setMintFee(uint256)',['uint256'],[fee],'setMintFee')
        assert number(SHAPES,'mintFee()')==fee
    def set_reuse():
        send(owner.address,manager,f'setParams({PARAMS_T},bytes32)',[PARAMS_T,'bytes32'],[params_values(values|dict(renewalMode=1)),config()],'setParams')
    def finish_list_matrix():
        nonlocal branch
        if int(rpc('eth_getBalance',keeper.address,'latest'),16)==0:fresh_keeper()
        assert number(manager,'openListingCount()')==8 and number(FWA,'unsettledAcquisitionCount()')==0
        assert number(SHAPES,'mintFee()')==500_000_000_000_000
        prepared=rpc('evm_snapshot');report['listMatrixSnapshot']=prepared;save()
        listing_types=['address']*3+['uint256']*6+['uint64','uint8']
        for count in (1,3,8):
            assert rpc('evm_revert',prepared);prepared=rpc('evm_snapshot');report['listMatrixSnapshot']=prepared;save()
            branch=f'owner-unlist-reuse-list-{count}';report['phase']=branch;save();prime(200_000_000,150_000_000)
            ids=[number(manager,'openListingAt(uint256)',['uint256'],[i]) for i in range(count)]
            backings=[read(FWA,'listings(uint256)',['uint256'],[i],listing_types)[5] for i in ids]
            top=number(FWA,'topListingId()');now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)
            if top in ids:
                unlocked=number(FWA,'topListingSince()')+43200+1
                if now<unlocked:rpc('evm_setNextBlockTimestamp',unlocked);rpc('evm_mine')
            send(owner.address,manager,'setExiting(bool)',['bool'],[True],'setExiting')
            idle=number(manager,'idlePackCount()');cash=int(rpc('eth_getBalance',manager,'latest'),16)
            send(owner.address,manager,'recoverUnlist(uint256[])',['uint256[]'],[ids],'recoverUnlist',work_count=count)
            assert number(manager,'openListingCount()')==8-count and number(manager,'idlePackCount()')==idle+count
            assert int(rpc('eth_getBalance',manager,'latest'),16)-cash==sum(backings)
            send(owner.address,manager,'setExiting(bool)',['bool'],[False],'setExiting')
            send(owner.address,manager,'setListingPaused(bool)',['bool'],[False],'setListingPaused')
            supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()');cash=int(rpc('eth_getBalance',manager,'latest'),16)
            proposals=[21*10**16+10000*(100+i) for i in range(count)]
            sample=paid('list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[proposals,0,config()],1,'list',count)
            assert number(manager,'openListingCount()')==8 and number(manager,'idlePackCount()')==idle
            assert number(SHAPES,'totalSupply()')==supply and number(SHAPES,'pendingFees()')==creator
            assert cash-int(rpc('eth_getBalance',manager,'latest'),16)==sum(proposals)+sample['compensationWei']
            report.setdefault('verifiedListWorkCounts',[]).append(count);save()
        report['syncBatchGap']='Only actual single-position allocated/resolved/combined sync sampled. Oracle owner is a contract; no contract caller was impersonated to invent kick fixtures.'
        save()
    def fresh_build_estimates():
        nonlocal manager,branch
        original_manager=manager
        factory=read(manager,'factory()',returns=('address',))[0]
        builder=Account.create();signers[builder.address.lower()]=builder
        assert rpc('eth_getCode',builder.address,'latest')=='0x' and int(rpc('eth_getTransactionCount',builder.address,'latest'),16)==0
        assert int(rpc('eth_getBalance',builder.address,'latest'),16)==0
        rpc('anvil_setBalance',builder.address,hex(3*10**18));report['openingFundingActor']=builder.address
        opening=rpc('evm_snapshot');report['openingSnapshot']=opening;save()
        for price,base in ((200_000_000,150_000_000),(500_000_000,450_000_000)):
            for fee in (500_000_000_000_000,10**15):
                assert rpc('evm_revert',opening);opening=rpc('evm_snapshot');report['openingSnapshot']=opening;save()
                manager=original_manager
                branch=f'fresh-clone-build1-price-{price}-fee-{fee}';report['phase']=branch;save();prime(price,base);set_fee(fee)
                before=number(factory,'managerCount()');expected=read(factory,f'configHashFor({PARAMS_T})',[PARAMS_T],[params_values(values)],('bytes32',))[0]
                send(builder.address,factory,f'create(address,{PARAMS_T},bytes32)',['address',PARAMS_T,'bytes32'],[owner.address,params_values(values),expected],'create',value=5*10**17)
                manager=read(factory,'managerAt(uint256)',['uint256'],[before],('address',))[0]
                assert number(manager,'openListingCount()')==0
                assert read(manager,'owner()',returns=('address',))[0].lower()==owner.address.lower()
                cash=int(rpc('eth_getBalance',manager,'latest'),16);assert cash>=5*10**17
                creator=number(SHAPES,'pendingFees()');supply=number(SHAPES,'totalSupply()')
                sample=paid('build(uint256,uint256[],uint256,bytes32)',['uint256','uint256[]','uint256','bytes32'],[3,[21*10**16],0,config()],2,'build',1)
                sample.update(genuineFreshAccount=True,fundingWei=5*10**17,initialAccountCashWei=cash);save()
                assert number(manager,'openListingCount()')==1 and number(SHAPES,'totalSupply()')-supply==3
                assert number(SHAPES,'pendingFees()')-creator==3*fee
                assert cash-int(rpc('eth_getBalance',manager,'latest'),16)==24*10**16+3*fee+sample['compensationWei']
        manager=original_manager
    sync_sig='sync(uint256[],uint256,uint256,bytes32)'; sync_types=['uint256[]','uint256','uint256','bytes32']
    try:
        for _ in range(600):
            assert node is None or node.poll() is None, (work/'anvil.log').read_text()[-2000:]
            try:
                if rpc('eth_chainId')=='0x7a69':break
            except urllib.error.URLError:time.sleep(1)
        else:raise RuntimeError('owned Osaka node startup timed out')
        info=rpc('anvil_nodeInfo');assert info['hardFork']=='Osaka' and info['forkConfig']['forkUrl']==PUBLIC
        assert int(info['forkConfig']['forkBlockNumber'])==meta['requestBlock']-1
        if args.finish_matrix:
            finish_list_matrix();fresh_build_estimates()
            assert report['contractSourceSha256']==sources()
            report.update(status='PASS',phase='complete');save();write_calibration(evidence)
            print(json.dumps(dict(status='PASS',samples=len(report['transactions'])),indent=1));return
        if args.attach:
            bare=previous.get('pristineBareSnapshot',previous['bareSnapshot'])
            assert bare in rpc('anvil_metadata')['snapshots'], 'preserve actual untouched base snapshot'
        else:bare=rpc('evm_snapshot')
        report['nodeInfo']=info;report['bareSnapshot']=bare;report['pristineBareSnapshot']=bare;save()
        load_checkpoint('allocated',allocated_json)
        allocated=rpc('evm_snapshot')
        for price,base in ((200_000_000,150_000_000),(500_000_000,450_000_000)):
            for combined in (False,True):
                assert rpc('evm_revert',allocated);allocated=rpc('evm_snapshot')
                branch=f'allocated-price-{price}-'+('combined' if combined else 'separate');report['phase']=branch;save();prime(price,base)
                before=number(FWA,'feeCredit(address)',['address'],[manager]);cash=int(rpc('eth_getBalance',manager,'latest'),16)
                send(owner.address,manager,'harvest(uint256[],uint256)',['uint256[]','uint256'],[[],0],'harvest')
                assert before==meta['feeCreditWei']>0 and int(rpc('eth_getBalance',manager,'latest'),16)-cash==before
                if not combined:
                    sample=paid(sync_sig,sync_types,[[],0,0,config()],2,'syncAllocated')
                    sample.update(selectedCount=1,resolvedCount=0)
                assert rpc('eth_getCode',meta['purchaser'],'latest')=='0x'
                send(meta['purchaser'],FWA,'acceptDepositorBid(uint256)',['uint256'],[meta['listing']],'acceptDepositorBid')
                sample=paid(sync_sig,sync_types,[[meta['listing']],0,0,config()],2,'syncCombined' if combined else 'syncResolved')
                sample.update(selectedCount=1 if combined else 0,resolvedCount=1);save()
                assert number(manager,'renewalEligible(uint256)',['uint256'],[meta['pack']])
        assert rpc('evm_revert',bare),'restore untouched base before max-nonce state merge'
        load_checkpoint('returned',returned_json)
        returned=rpc('evm_snapshot');report['returnedSnapshot']=returned;save()
        for price,base in ((200_000_000,150_000_000),(500_000_000,450_000_000)):
            for fee in (10**15,500_000_000_000_000,250_000_000_000_000):
                for reuse in (False,True):
                    assert rpc('evm_revert',returned);returned=rpc('evm_snapshot');report['returnedSnapshot']=returned;save()
                    branch=f'price-{price}-fee-{fee}-'+('reuse' if reuse else 'fresh');report['phase']=branch;save();prime(price,base);set_fee(fee)
                    if reuse:set_reuse()
                    supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()');cash=int(rpc('eth_getBalance',manager,'latest'),16)
                    if reuse:
                        sample=paid('list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[[21*10**16],0,config()],1,'list')
                    else:
                        sample=paid('renew(uint256[],uint256[],uint256[],uint256,bytes32)',['uint256[]','uint256[]','uint256[]','uint256','bytes32'],[[meta['pack']],[21*10**16],[],0,config()],3,'renew')
                    assert number(SHAPES,'pendingFees()')-creator==(0 if reuse else 3*fee)
                    assert number(SHAPES,'totalSupply()')==supply
                    assert cash-int(rpc('eth_getBalance',manager,'latest'),16)==21*10**16+sample['compensationWei']+(0 if reuse else 3*fee)
                    assert not number(manager,'renewalEligible(uint256)',['uint256'],[meta['pack']])
                    report.setdefault('completedBranches',[]).append(branch);save()
        report['phase']='base-operations-complete';save()
        assert rpc('evm_revert',returned);returned=rpc('evm_snapshot');prime(200_000_000,150_000_000);set_fee(500_000_000_000_000);set_reuse()
        branch='matrix-build-preparation'
        for start in (0,4):
            proposals=[21*10**16+10000*(i+1) for i in range(start,start+4)]
            creator=number(SHAPES,'pendingFees()');supply=number(SHAPES,'totalSupply()')
            paid('build(uint256,uint256[],uint256,bytes32)',['uint256','uint256[]','uint256','bytes32'],[3,proposals,0,config()],2,'build',4)
            assert number(SHAPES,'pendingFees()')-creator==12*500_000_000_000_000 and number(SHAPES,'totalSupply()')-supply==12
        ids=[number(manager,'openListingAt(uint256)',['uint256'],[i]) for i in range(number(manager,'openListingCount()'))];assert len(ids)==8
        fwa_admin=external_eoa(read(FWA,'owner()',returns=('address',))[0],'FWA admin')
        oracle=read(FWA,'floorOracle()',returns=('address',))[0]
        oracle_owner=read(oracle,'owner()',returns=('address',))[0]
        oracle_code=rpc('eth_getCode',oracle_owner,'latest')
        if not (oracle_code=='0x' or (len(oracle_code)==48 and oracle_code.startswith('0xef0100'))):
            finish_list_matrix();fresh_build_estimates()
            assert report['contractSourceSha256']==sources()
            report.update(status='PASS',phase='complete');save();write_calibration(evidence)
            print(json.dumps(dict(status='PASS',samples=len(report['transactions'])),indent=1));return
        oracle_admin=external_eoa(oracle_owner,'floor-oracle admin')
        prepared=rpc('evm_snapshot')
        for count in (1,3,8):
            assert rpc('evm_revert',prepared);prepared=rpc('evm_snapshot')
            branch=f'kick-sync-list-{count}';report['phase']=branch;save();prime(200_000_000,150_000_000)
            send(fwa_admin,FWA,'setOracleExemptCollection(address,bool)',['address','bool'],[PACKS,False],'setOracleExempt')
            send(oracle_admin,oracle,'setFloor(address,uint256)',['address','uint256'],[PACKS,3*10**16],'setFloor')
            now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16);ready=now+7*3600
            blackout=ready-ready%43200+42300
            if blackout<ready:blackout+=43200
            rpc('evm_setNextBlockTimestamp',blackout+1);rpc('evm_mine')
            idle=number(manager,'idlePackCount()');cash=int(rpc('eth_getBalance',manager,'latest'),16)
            for ident in ids[:count]:send(fwa_admin,FWA,'kickListing(uint256)',['uint256'],[ident],'kickListing')
            assert int(rpc('eth_getBalance',manager,'latest'),16)-cash==sum(21*10**16+10000*(i+1) for i in range(count))
            assert number(manager,'pendingReceipts()')==count
            sample=paid(sync_sig,sync_types,[ids[:count],0,0,config()],2,'syncKicked',count)
            assert number(manager,'openListingCount()')==8-count and number(manager,'idlePackCount()')==idle+count
            assert number(manager,'pendingReceipts()')==0
            send(fwa_admin,FWA,'setOracleExemptCollection(address,bool)',['address','bool'],[PACKS,True],'setOracleExempt')
            supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()');cash=int(rpc('eth_getBalance',manager,'latest'),16)
            proposals=[21*10**16+10000*(100+i) for i in range(count)]
            sample=paid('list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[proposals,0,config()],1,'list',count)
            assert number(manager,'openListingCount()')==8 and number(manager,'idlePackCount()')==idle
            assert number(SHAPES,'totalSupply()')==supply and number(SHAPES,'pendingFees()')==creator
            assert cash-int(rpc('eth_getBalance',manager,'latest'),16)==sum(proposals)+sample['compensationWei']
            report.setdefault('verifiedWorkCounts',[]).append(dict(sync=count,list=count));save()
        assert report['contractSourceSha256']==sources()
        report.update(status='PASS',phase='complete');save()
        write_calibration(evidence)
        print(json.dumps(dict(status='PASS',samples=len(report['transactions'])),indent=1))
    except BaseException as exc:
        report.update(status='FAIL',error=repr(exc));save();raise


def write_calibration(evidence):
    report=json.loads(evidence.read_text())
    assert report['status']=='PASS' and report['executionHardfork']=='Osaka'
    baseline_path=OUT/'manager-r2-cost-calibration.json';baseline=json.loads(baseline_path.read_text())
    baseline_receipts=ROOT/baseline['receipts'];assert sha(baseline_receipts)==baseline['receipts_sha256']
    r2=json.loads(baseline_receipts.read_text());assert r2['status']=='PASS'
    assert r2['contractSourceSha256']==report['contractSourceSha256']==sources()
    aliases=dict(create='create',setExiting='setExiting',withdraw='withdraw',recoverUnlist='unlist',
                 recoverLiquidate='liquidate',recover='recover_sync',processAcquisitions='processAcquisitions',build='build')
    samples=[]
    def events(item,signature,kinds):
        topic='0x'+keccak(text=signature).hex();target=item['transaction']['to'].lower()
        return [decode(kinds,bytes.fromhex(log['data'][2:])) for log in item['receipt']['logs']
                if log['address'].lower()==target and log['topics'][0].lower()==topic]
    for original in r2['transactions']:
        op=original['operation']
        if op not in aliases:continue
        item=dict(original);raw=bytes.fromhex(item['transaction']['input'][10:]);count=1
        if op=='build':
            count=len(decode(['uint256','uint256[]','uint256','bytes32'],raw)[1])
            assert events(item,'Built(uint256,uint256)',['uint256','uint256'])[0][0]==count
        elif op=='recoverUnlist':
            count=len(decode(['uint256[]'],raw)[0]);topic='0x'+keccak(text='Unlisted(uint256)').hex()
            assert sum(log['address'].lower()==item['transaction']['to'].lower() and log['topics'][0].lower()==topic for log in item['receipt']['logs'])==count
        elif op=='recoverLiquidate':
            count=sum(row[0] for row in events(item,'Liquidated(uint256,uint256,uint256)',['uint256']*3))
            assert count>0
        elif op=='recover':
            item['inspectedIds']=list(decode(['uint256[]','uint256'],raw)[0]);count=1
        assert count>0
        item.update(calibrationOperation=aliases[op],workCount=count,workCountBasis='Actual Built/Liquidated/Unlisted events, inspected recover IDs, or fixed operation; R2 process is the one genuine expired request.',
                    gasEstimate=int(item['transaction']['gas'],16),signedGasLimit=int(item['transaction']['gas'],16),
                    estimateKind='signed-limit-upper',gasEstimateBasis='Conservative signed transaction gas limit; actual estimate was not recorded.',source=str(baseline_receipts.relative_to(ROOT)))
        item.update(recordedOperation=op,operation=aliases[op],hash=item['transaction']['hash'],transactionHash=item['transaction']['hash'])
        assert item['transactionHash']==item['receipt']['transactionHash']
        samples.append(item)
    for original in report['transactions']:
        op=original['operation'];item=dict(original)
        canonical='sync' if op in ('syncAllocated','syncResolved','syncCombined','syncKicked') else op
        if canonical not in ('build','renew','list','sync','harvest','create','setExiting','recoverUnlist'):continue
        if canonical=='recoverUnlist':canonical='unlist'
        assert item['workCount']>0 and int(item['receipt']['status'],16)==1 and item['executionHardfork']=='Osaka'
        if op=='build':assert events(item,'Built(uint256,uint256)',['uint256','uint256'])[0][0]==item['workCount']
        item.update(calibrationOperation=canonical,estimateKind='rpc-estimate',gasEstimateBasis='Actual pre-signing eth_estimateGas',source=str(evidence.relative_to(ROOT)))
        item.update(recordedOperation=op,operation=canonical,hash=item['transaction']['hash'],transactionHash=item['transaction']['hash'])
        assert item['transactionHash']==item['receipt']['transactionHash']
        samples.append(item)
    required={'create','setExiting','withdraw','unlist','liquidate','recover_sync','processAcquisitions','build','renew','list','sync','harvest'}
    curves={};gas={};estimates={}
    for op in sorted(required):
        rows=[row for row in samples if row['calibrationOperation']==op];single=[row for row in rows if row['workCount']==1]
        assert single,('single-work evidence missing',op)
        billed=max(row['gasUsed'] for row in single)
        estimate_rows=[row for row in rows if row['estimateKind']=='rpc-estimate'] or rows
        estimate_single=[row for row in estimate_rows if row['workCount']==1];assert estimate_single,('actual single estimate missing',op)
        estimate=max(row['gasEstimate'] for row in estimate_single)
        def slope(field,base,chosen):
            return max([0]+[max(0,(row[field]-base+row['workCount']-2)//(row['workCount']-1)) for row in chosen if row['workCount']>1])
        curve=dict(single_billed_gas=billed,single_estimate_gas=estimate,
                   billed_per_extra_work=slope('gasUsed',billed,rows),estimate_per_extra_work=slope('gasEstimate',estimate,estimate_rows))
        for row in rows:
            assert row['gasUsed']<=billed+(row['workCount']-1)*curve['billed_per_extra_work']
            if row in estimate_rows:assert row['gasEstimate']<=estimate+(row['workCount']-1)*curve['estimate_per_extra_work']
        curves[op]=curve;gas[op]=billed;estimates[op]=estimate
    writer_sources=sources()|{name:sha(ROOT/name) for name in ('keeper/calibrate_manager_operations.py','keeper/config.py',
        'test/fork/ManagerOperationsCheckpoint.t.sol','test/fork/ForkMainRenewal.t.sol','test/fixtures/completion-selection.json')}
    calibration=dict(method='Count-aware Osaka actual operation samples and immutable R2 receipts; single-work baselines plus conservative observed extra-work slopes',
        contract_source_sha256=report['contractSourceSha256'],source_sha256=writer_sources,
        receipts=str(evidence.relative_to(ROOT)),receipts_sha256=sha(evidence),
        receipt_inputs=[dict(path=str(path.relative_to(ROOT)),sha256=sha(path)) for path in (baseline_path,baseline_receipts,evidence)],
        gas_proxy=gas,gas_estimate_proxy=estimates,gas_curves=curves,measurements={op:[row for row in samples if row['calibrationOperation']==op] for op in sorted(required)},
        gas_estimate_provenance='New Osaka samples record actual eth_estimateGas. R2 estimates use signed gas limits as conservative upper bounds without reversing padding.',
        measured_work_counts={op:sorted({row['workCount'] for row in samples if row['calibrationOperation']==op}) for op in required},
        unmeasured_operations=[],unsampled_work_counts={'renew':'2..32 packs','list':'9..32 packs','sync':'2..32 positions'},
        limitations=report['limitations']+['Required operation names are covered; fresh renewal only1, list/unlist1/3/8, sync only1 (separate and combined). No larger sync was fabricated through a contract oracle owner. Owner recover_sync is a fixed scan with1/3 inspected IDs, not1/3 completed settlements.'])
    (OUT/'manager-operating-cost-calibration.json').write_text(json.dumps(calibration,indent=1)+'\n')


if __name__=='__main__':main()
