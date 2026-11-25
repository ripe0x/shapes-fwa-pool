#!/usr/bin/env python3
"""Receipt measurements of reuse-only managers on an authenticated isolated fork.

The checkpoint is exported by the real historical request/proof test. Native import restores
that executed state, including zero writes, and validates every restored field before work.
This is operating calibration, not an owner-return portfolio or a public deployment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from eth_abi import decode, encode
from eth_utils import keccak, to_checksum_address
from config import PARAMS_T, params_values
from rehearse_manager_r2 import ROOT, PUBLIC, FWA, SHAPES, PACKS, sources

OUT = ROOT / 'docs/receipts/manager-measured-receipts.json'
STEM = ROOT / 'sim/out/manager-measured-checkpoint'
METER = '0x' + keccak(text='KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)').hex()
PAID = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rpc_at(url, method, params):
    body = json.dumps(dict(jsonrpc='2.0', id=1, method=method, params=params)).encode()
    req = urllib.request.Request(url, body, {'Content-Type': 'application/json'})
    # Never retry an uncertain mutating call.
    with urllib.request.urlopen(req, timeout=600) as response:
        row = json.load(response)
    if 'error' in row:
        raise RuntimeError(method + ': ' + json.dumps(row['error']))
    return row['result']


def data(signature, kinds=(), values=()):
    return '0x' + (keccak(text=signature)[:4] + encode(kinds, values)).hex() if signature else '0x'


def main():
    global OUT
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--execute', action='store_true')
    ap.add_argument('--output', default=str(OUT), help='Fresh receipt path; existing attempts are never overwritten')
    ap.add_argument('--profile-only', action='store_true', help='Regenerate the cost profile from completed real receipt packets, no RPC or transactions')
    ap.add_argument('--port', type=int, default=18786)
    ap.add_argument('--resume-after-setup', help='Recover the exact successful setup transaction hash, never resubmit it')
    ap.add_argument('--resume-startup', action='store_true', help='Continue only the retained failed startup before any billed transaction')
    ap.add_argument('--export-existing', action='store_true', help='Use this unchanged-source newly exported checkpoint')
    a = ap.parse_args()
    OUT=Path(a.output).resolve()
    if a.profile_only:
        completed=json.loads(OUT.read_text());assert completed['status']=='PASS'
        write_profile(completed);return
    if not a.execute or os.environ.get('CANDIDATE_RUN') != '1':
        raise SystemExit('Plan: authenticated checkpoint, one owned Osaka fork, actual paid receipts at .2/.5gwei, intact migration and owner-paid exit. Requires --execute and CANDIDATE_RUN=1.')
    previous = json.loads(OUT.read_text()) if a.resume_startup or a.resume_after_setup else None
    if previous:
        assert previous['status'] in ('FAIL','RUNNING') and previous.get('phase')=='native checkpoint validation'
        assert not previous['transactions'], 'prework continuation cannot replay a billed transaction'
        assert previous['contractSourceSha256']==sources(), 'startup continuation cannot change runtime'
        assert previous['rpc']==f'http://127.0.0.1:{a.port}'
        preserved=OUT.with_name('manager-measured-startup-failed.json')
        if not preserved.exists():preserved.write_bytes(OUT.read_bytes())
        else:assert json.loads(preserved.read_text())['ownedNodePid']==previous['ownedNodePid']
        previous.setdefault('preworkAttempts',[]).append(dict(status=previous['status'],error=previous.get('error')))
        work=Path(previous['workDirectory'])
    else:
        assert not OUT.exists(), 'preserve the existing measured attempt; do not overwrite receipts'
        with socket.socket() as sock:sock.bind(('127.0.0.1', a.port))
        work=Path(tempfile.mkdtemp(prefix='manager-measured-'))
    start = time.monotonic()
    url = f'http://127.0.0.1:{a.port}'
    settings = json.loads((ROOT/'deploy/manager.json').read_text())
    report = dict(status='RUNNING', command=[sys.executable, *sys.argv], scriptSha256=sha(__file__),
        compensation_mode='bounded-measured-v1', contractSourceSha256=sources(), managerValues=settings,
        managerValuesSha256=sha(ROOT/'deploy/manager.json'), rpc=url, chainId=31337, executionHardfork='Osaka',
        workDirectory=str(work), publicTransactions=0, sharedVaultDeployed=False, transactions=[],
        limitations=['Authenticated checkpoint setup is executed by Foundry and is not a billed production transaction.',
            'Restored branches are separate operation samples, not one economic portfolio.',
            'Gasleft work spans exclude refunds; keeper expenses use receipt gasUsed.',
            'Local wallet funding and fork-only actual EOA administration are explicit setup, not owner yield.',
            'No production signing, public inclusion, Fly cutover or shared-vault deployment.'])

    if previous:
        assert previous['managerValues']==settings
        report=previous | dict(status='RUNNING',error=None,continuationCommand=[sys.executable,*sys.argv],
            continuationScriptSha256=sha(__file__),previousAttempt='docs/receipts/manager-measured-startup-failed.json')

    def save():
        OUT.write_text(json.dumps(report, indent=1)+'\n')

    save()
    if not a.export_existing and not previous:

        command = ['forge','test','--match-path','test/fork/ManagerOperationsCheckpoint.t.sol',
            '--match-test','test_exportAuthenticatedAllocatedCheckpoint','--rpc-url',PUBLIC,
            '--fork-retries','30','--fork-retry-backoff','5000','--compute-units-per-second','100','-vv']
        begun = time.monotonic()
        r = subprocess.run(command, cwd=ROOT, env=os.environ | {'EXPORT_MANAGER_OPERATING':'true',
            'MANAGER_CHECKPOINT_STEM':str(STEM.relative_to(ROOT))}, capture_output=True, text=True)
        log = ROOT/'docs/receipts/manager-measured-export.log'
        log.write_text(r.stdout+r.stderr)
        report['export'] = dict(command=command, exitStatus=r.returncode, elapsedSeconds=time.monotonic()-begun,
            log=str(log.relative_to(ROOT)), logSha256=sha(log))
        save()
        assert r.returncode == 0, 'authentic export failed; no node or billed call started'
    paths = {kind:Path(str(STEM)+'-'+kind+'.json') for kind in ('metadata','alloc','diff')}
    meta = json.loads(paths['metadata'].read_text())
    alloc = {k.lower():v for k,v in json.loads(paths['alloc'].read_text()).items()}
    diffs = json.loads(paths['diff'].read_text())
    writes = {(address.lower(),slot.lower()):v['newValue'].lower() for address,account in diffs.items()
        if address.lower()!=meta['harness'].lower() for slot,v in account['stateDiff'].items()}
    critical = decode(['address[]','uint256[]','uint256[]','bytes[]'],bytes.fromhex(meta['criticalAccountsAbi'][2:]))
    for address,balance,nonce,code in zip(*critical):
        account = alloc.setdefault(address.lower(), {})
        account.update(balance=hex(balance),nonce=hex(nonce),code='0x'+code.hex())
    for (address,slot),value in writes.items():
        account = alloc.setdefault(address, {})
        storage = account.setdefault('storage', {})
        previous_value = storage.get(slot, '0x0')
        assert int(previous_value,16)==int(value,16), ('executed diff/dump disagree',address,slot)
        storage[slot] = value  # dumpState may omit executed zero writes; the diff proves them.
    report['checkpoint'] = dict(paths={str(p.relative_to(ROOT)):sha(p) for p in paths.values()},
        source={p:sha(ROOT/p) for p in ('test/fork/ManagerOperationsCheckpoint.t.sol','test/fork/ForkMainRenewal.t.sol','test/fixtures/completion-selection.json')},
        actualMetadata=meta, writtenSlots=len(writes), zeroWrites=sum(int(v,16)==0 for v in writes.values()))
    tx = rpc_at(PUBLIC,'eth_getTransactionByHash',[meta['requestTx']])
    header = rpc_at(PUBLIC,'eth_getBlockByNumber',[tx['blockNumber'],False])
    index = int(tx['transactionIndex'],16)
    assert header['transactions'][index].lower()==meta['requestTx'].lower()
    prefix = ['--fork-transaction-hash',header['transactions'][index-1]] if index else ['--fork-block-number',str(meta['requestBlock']-1)]
    command = ['anvil','--host','127.0.0.1','--port',str(a.port),'--accounts','0','--chain-id','31337',
        '--hardfork','osaka','--enable-tx-gas-limit','--gas-limit','60000000','--fork-url',PUBLIC,*prefix,
        '--retries','30','--fork-retry-backoff','5000','--silent']
    if previous:
        assert command==previous['nodeCommand']
        pid=previous['ownedNodePid']
        assert subprocess.check_output(['ps','-p',str(pid),'-o','comm='],text=True).strip().split('/')[-1]=='anvil'
        class RetainedNode:
            def __init__(self,pid):self.pid=pid
            def poll(self):
                try:os.kill(self.pid,0);return None
                except ProcessLookupError:return 1
        node=RetainedNode(pid)
    else:
        node = subprocess.Popen(command,stdout=open(work/'anvil.log','w'),stderr=subprocess.STDOUT,start_new_session=True)
    report.update(ownedNodePid=node.pid,nodeCommand=command,phase='native checkpoint validation')
    save()

    def rpc(method,*params):
        return rpc_at(url,method,params)

    owner = to_checksum_address(meta['owner'])
    keeper = to_checksum_address(keccak(text='pack-vault-test-measured-v1-keeper')[-20:])
    manager = to_checksum_address(meta['manager'])
    base, price = 150000000, 200000000
    branch = 'setup'

    def read(target,signature,kinds=(),values=(),returns=('uint256',)):
        raw = rpc('eth_call',dict(to=target,data=data(signature,kinds,values),**{'from':keeper},
            gasPrice=hex(price)),'latest')
        return decode(returns,bytes.fromhex(raw[2:]))

    def number(target,signature,kinds=(),values=()):
        return read(target,signature,kinds,values)[0]

    def config(account):
        return read(account,'configurationHash()',returns=('bytes32',))[0]

    def prime():
        rpc('anvil_setNextBlockBaseFeePerGas',hex(base*8//7));rpc('evm_mine')
        parent = rpc('eth_getBlockByNumber','latest',False)
        assert int(parent['gasUsed'],16)==0
        from tx import next_base_fee
        assert next_base_fee(parent)==base

    def setup_actor(actor,amount,role):
        code = rpc('eth_getCode',actor,'latest')
        assert code=='0x' or (role in ('actual purchaser','actual mint admin') and code.lower().startswith('0xef0100') and len(code)==48)
        report.setdefault('walletSetup',[]).append(dict(actor=actor,role=role,beforeWei=int(rpc('eth_getBalance',actor,'latest'),16),setupWei=amount,delegationCode=code))
        current=int(rpc('eth_getBalance',actor,'latest'),16)
        if current<amount:rpc('anvil_setBalance',actor,hex(amount))
        rpc('anvil_impersonateAccount',actor)

    def send(sender,target,signature,kinds=(),values=(),operation=None,value=0,count=1,paid=False):
        prime()
        payload = dict(to=to_checksum_address(target),data=data(signature,kinds,values),value=hex(value),
            maxFeePerGas=hex(2*base+50000000),maxPriorityFeePerGas=hex(50000000),**{'from':sender})
        simulated = None
        if paid:
            simulated = decode(['uint256'],bytes.fromhex(rpc('eth_call',payload,'pending')[2:]))[0]
            assert simulated>0, 'ordinary paid work must simulate positive compensation'
            floor = simulated*8//10
            vals = list(values);vals[-2]=floor;payload['data']=data(signature,kinds,vals)
        estimate = int(rpc('eth_estimateGas',payload),16);limit=(estimate*5+3)//4
        assert limit<=16777216
        hash_ = rpc('eth_sendTransaction',payload|dict(gas=hex(limit)))
        report['pendingLocalTransaction']=dict(hash=hash_,signature=signature,sender=sender,target=target,gasEstimate=estimate,signedGasLimit=limit)
        save()
        receipt = None
        for _ in range(120):
            receipt=rpc('eth_getTransactionReceipt',hash_)
            if receipt:break
            time.sleep(.5)
        assert receipt and int(receipt['status'],16)==1, ('reverted',signature,hash_)
        transaction = rpc('eth_getTransactionByHash',hash_)
        block = rpc('eth_getBlockByHash',receipt['blockHash'],False)
        assert int(receipt['effectiveGasPrice'],16)==price and int(block['baseFeePerGas'],16)==base
        logs = [l for l in receipt['logs'] if l['address'].lower()==target.lower()]
        compensation = sum(int(l['data'],16) for l in logs if l['topics'][0]==PAID)
        meters = [decode(['uint256','uint256','uint256','uint256','bool'],bytes.fromhex(l['data'][2:])) for l in logs if l['topics'][0]==METER]
        row = dict(branch=branch,operation=operation or signature.split('(')[0],workCount=count,targetAccount=target,
            gasEstimate=estimate,signedGasLimit=limit,gasUsed=int(receipt['gasUsed'],16),
            effectiveGasPrice=price,blockBaseFeeWei=base,gasCostWei=int(receipt['gasUsed'],16)*price,
            compensationWei=compensation,transaction=transaction,receipt=receipt)
        if paid:
            assert len(meters)==1 and compensation>=floor
            meter=dict(zip(('measuredGas','gasAllowance','gasPrice','workUnits','essential'),meters[0]))
            assert meter['gasPrice']==price
            actual_settings = read(target,'getParams()',returns=(PARAMS_T,))[0]
            from config import PARAM_FIELDS,GAS_FIELDS
            p=dict(zip((k for k,_ in PARAM_FIELDS),actual_settings[:-1]));g=dict(zip(GAS_FIELDS,actual_settings[-1]))
            overhead=g['overhead'];markup=0 if meter['essential'] else p['payMarkupBps']
            expected=(min(meter['measuredGas'],meter['gasAllowance'])+overhead)*price*(10000+markup)//10000+meter['workUnits']*p['workFeeWei']
            assert compensation==expected, 'actual receipt compensation differs from recorded meter/configuration'
            assert compensation>=row['gasCostWei'], ('unsubsidized keeper loss',row['operation'],compensation,row['gasCostWei'])
            row.update(measuredWork=meter,overhead=overhead,markupBps=markup,workFeeWei=p['workFeeWei'],
                simulatedCompensationWei=simulated,minimumPaymentWei=floor,keeperNetWei=compensation-row['gasCostWei'])
        else:
            assert compensation==0 and not meters, 'owner work must not earn keeper rewards'
        report['transactions'].append(row);report.pop('pendingLocalTransaction',None);save()
        return row

    def state(account):
        return dict(cash=int(rpc('eth_getBalance',account,'latest'),16),credit=number(FWA,'feeCredit(address)',['address'],[account]),
            **{n:number(account,n+'()') for n in ('openListingCount','idlePackCount','recoveryPackCount','pendingReceipts')})

    def drain_queue():
        # Advance only actual request deadlines, then the clock window in one block.
        # Mining an entire 12-hour interval as empty blocks adds no integration evidence.
        for _ in range(32):
            if number(FWA,'unsettledAcquisitionCount()')==0:break
            seq=number(FWA,'nextSequenceToProcess()')
            request=number(FWA,'requestIdAtSequence(uint64)',['uint64'],[seq])
            fields=read(FWA,'acquisitionMeta(uint256)',['uint256'],[request],('uint64','uint64','uint64','uint16','uint16','uint256'))
            gap=max(0,fields[1]+1-int(rpc('eth_blockNumber'),16))
            assert gap<=7201, 'real protocol deadline exceeds bounded setup'
            if gap:rpc('anvil_mine',hex(gap),hex(12))
            send(owner,FWA,'processAcquisitions(uint256)',['uint256'],[32],operation='processAcquisitions')
            assert number(FWA,'nextSequenceToProcess()')>seq, 'real expired queue must progress'
        assert number(FWA,'unsettledAcquisitionCount()')==0
        now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)
        rpc('evm_setNextBlockTimestamp',now-now%43200+43200+60);rpc('evm_mine')

    try:
        if not a.resume_after_setup:
            for _ in range(1800):
                assert node.poll() is None, 'owned node stopped during startup'
                try:
                    if rpc('eth_chainId')=='0x7a69':break
                except (OSError,RuntimeError):time.sleep(1)
            else:raise RuntimeError('fork startup timed out')
            assert rpc('anvil_nodeInfo')['hardFork']=='Osaka'
            current=int(rpc('eth_blockNumber'),16)
            while current<meta['block']:
                current+=1;rpc('evm_setNextBlockTimestamp',meta['timestamp']-(meta['block']-current));rpc('evm_mine')
            native={address:dict(balance=account.get('balance','0x0'),nonce=int(account.get('nonce','0x0'),0),
                code=account.get('code','0x'),storage=account.get('storage',{})) for address,account in alloc.items()}
            chunk={};size=0
            for address,account in native.items():
                size+=len(json.dumps({address:account}));chunk[address]=account
                if size>500000:
                    assert rpc('anvil_loadState','0x'+json.dumps(dict(block=None,best_block_number=None,accounts=chunk)).encode().hex());chunk={};size=0
            if chunk:assert rpc('anvil_loadState','0x'+json.dumps(dict(block=None,best_block_number=None,accounts=chunk)).encode().hex())
            checks=[];expected=[]
            for address,account in native.items():
                checks += [('eth_getBalance',[address,'latest']),('eth_getTransactionCount',[address,'latest']),('eth_getCode',[address,'latest'])]
                expected += [int(account['balance'],0),account['nonce'],account['code'].lower()]
                for slot,value in account['storage'].items():
                    checks.append(('eth_getStorageAt',[address,slot,'latest']));expected.append(int(value,16))
            for start_at in range(0,len(checks),90):
                payload=[dict(jsonrpc='2.0',id=i,method=m,params=p) for i,(m,p) in enumerate(checks[start_at:start_at+90],start_at)]
                req=urllib.request.Request(url,json.dumps(payload).encode(),{'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=120) as response:answers=sorted(json.load(response),key=lambda x:x['id'])
                for answer in answers:
                    assert 'error' not in answer, answer
                    wanted=expected[answer['id']];actual=answer['result']
                    assert (actual.lower() if isinstance(wanted,str) else int(actual,16))==wanted,checks[answer['id']]
            checked=len(checks)
            report['checkpoint']['verifiedFields']=checked
            report['checkpoint']['validatedBeforeBilledWork']=True
            setup_actor(keeper,10**18,'keeper')
            assert number(manager,'openListingCount()')==meta['openListingCount']
            assert number(SHAPES,'totalSupply()')==meta['shapeSupply']
            assert int(rpc('eth_getBalance',manager,'latest'),16)==meta['managerCashWei']
            assert read(manager,'owner()',returns=('address',))[0].lower()==owner.lower()
            setup_actor(owner,5*10**18,'manager owner')
            factory=read(manager,'factory()',returns=('address',))[0];report.update(factory=factory,manager=manager,owner=owner,keeper=keeper)
            send(owner,manager,f'setParams({PARAMS_T},bytes32)',[PARAMS_T,'bytes32'],[params_values(settings),config(manager)])
        else:
            assert rpc('eth_chainId')=='0x7a69' and rpc('anvil_nodeInfo')['hardFork']=='Osaka'
            h=a.resume_after_setup
            receipt=rpc('eth_getTransactionReceipt',h);tx_setup=rpc('eth_getTransactionByHash',h)
            assert receipt and int(receipt['status'],16)==1
            assert tx_setup['from'].lower()==owner.lower() and tx_setup['to'].lower()==manager.lower()
            assert int(tx_setup['value'],16)==0 and int(tx_setup['nonce'],16)==0
            sig=f'setParams({PARAMS_T},bytes32)'
            expected_data=data(sig,[PARAMS_T,'bytes32'],[params_values(settings),bytes.fromhex(meta['configurationHash'][2:])])
            assert tx_setup['input'].lower()==expected_data.lower(), 'setup recovery must match the exact original reviewed calldata'
            assert tuple(read(manager,'getParams()',returns=(PARAMS_T,))[0])==tuple(params_values(settings))
            factory=read(manager,'factory()',returns=('address',))[0]
            assert previous['checkpoint']['validatedBeforeBilledWork'] and previous['checkpoint']['verifiedFields']>0
            gas_limit=int(tx_setup['gas'],16);estimate=gas_limit*4//5
            assert (estimate*5+3)//4==gas_limit
            report['transactions'].append(dict(branch='setup',operation='setParams',workCount=1,targetAccount=manager,
                gasEstimate=estimate,gasEstimateRecoveredFromSignedLimit=True,signedGasLimit=gas_limit,
                gasUsed=int(receipt['gasUsed'],16),effectiveGasPrice=int(receipt['effectiveGasPrice'],16),
                blockBaseFeeWei=base,gasCostWei=int(receipt['gasUsed'],16)*int(receipt['effectiveGasPrice'],16),
                compensationWei=0,transaction=tx_setup,receipt=receipt))
            report['setupRecoveredWithoutResubmission']=h
            save()
        origin=rpc('evm_snapshot')
        for price,base in ((200000000,150000000),(500000000,450000000)):
            assert rpc('evm_revert',origin);origin=rpc('evm_snapshot')
            branch=f'authenticated-reuse-{price}';report['phase']=branch;save()
            send(keeper,manager,'sync(uint256[],uint256,uint256,bytes32)',
                ['uint256[]','uint256','uint256','bytes32'],[[],0,0,config(manager)],operation='sync',paid=True)
            setup_actor(to_checksum_address(meta['purchaser']),10**18,'actual purchaser')
            send(to_checksum_address(meta['purchaser']),FWA,'acceptDepositorBid(uint256)',['uint256'],[meta['listing']])
            send(keeper,manager,'sync(uint256[],uint256,uint256,bytes32)',
                ['uint256[]','uint256','uint256','bytes32'],[[meta['listing']],0,0,config(manager)],operation='sync',paid=True)
            drain_queue()
            supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()')
            send(keeper,manager,'list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[[21*10**16],0,config(manager)],paid=True)
            assert number(SHAPES,'totalSupply()')==supply and number(SHAPES,'pendingFees()')==creator
            report.setdefault('reuseProofs',[]).append(dict(branch=branch,pack=meta['pack'],shapeSupplyUnchanged=supply,creatorMintFeesAddedWei=0))
        report['phase']='migration and new paid batches';save()
        send(owner,manager,'setListingPaused(bool)',['bool'],[True])
        ids=[number(manager,'openListingAt(uint256)',['uint256'],[i]) for i in range(number(manager,'openListingCount()'))]
        send(owner,manager,'unlistForWithdrawal(uint256[])',['uint256[]'],[ids])
        count=number(factory,'managerCount()')
        expected=read(factory,f'configHashFor({PARAMS_T})',[PARAMS_T],[params_values(settings)],('bytes32',))[0]
        send(owner,factory,f'create(address,{PARAMS_T},bytes32)',['address',PARAMS_T,'bytes32'],[owner,params_values(settings),expected],operation='create')
        destination=read(factory,'managerAt(uint256)',['uint256'],[count],('address',))[0]
        report['destination']=destination
        send(owner,destination,'setListingPaused(bool)',['bool'],[True])
        held=[number(manager,'idlePackAt(uint256)',['uint256'],[i]) for i in range(number(manager,'idlePackCount()'))]
        integrity={str(i):dict(value=number(PACKS,'valueOf(uint256)',['uint256'],[i]),
            contents=list(read(PACKS,'contentsOf(uint256)',['uint256'],[i],('uint256[]',))[0])) for i in held}
        supply=number(SHAPES,'totalSupply()');creator=number(SHAPES,'pendingFees()')
        send(owner,manager,'withdrawPacks(address,uint256)',['address','uint256'],[destination,len(held)])
        send(owner,destination,'importPacks(uint256[],bytes32)',['uint256[]','bytes32'],[held,config(destination)])
        for i in held:
            assert read(PACKS,'ownerOf(uint256)',['uint256'],[i],('address',))[0].lower()==destination.lower()
            assert list(read(PACKS,'contentsOf(uint256)',['uint256'],[i],('uint256[]',))[0])==integrity[str(i)]['contents']
            assert number(destination,'inventoryShapeCount(uint256)',['uint256'],[i])==len(integrity[str(i)]['contents'])
        assert number(SHAPES,'totalSupply()')==supply and number(SHAPES,'pendingFees()')==creator
        report['migration']=dict(source=manager,destination=destination,packIntegrity=integrity,creatorMintFeesWei=0,
            shapeSupplyBefore=supply,shapeSupplyAfter=number(SHAPES,'totalSupply()'),sourceNotExiting=not read(manager,'windingDown()',returns=('bool',))[0])
        # Explicitly move the source's cash through its owner; no mint or hidden capital injection.
        if number(FWA,'feeCredit(address)',['address'],[manager]):
            send(owner,manager,'harvest(uint256[],uint256)',['uint256[]','uint256'],[[],0])
        cash=int(rpc('eth_getBalance',manager,'latest'),16)
        send(owner,manager,'withdraw(address,uint256)',['address','uint256'],[owner,cash])
        send(owner,destination,'',value=cash)
        report['migration']['cashTransferredWei']=cash
        assert not any(state(manager).values())
        send(owner,destination,'setListingPaused(bool)',['bool'],[False])
        send(keeper,destination,'list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[[21*10**16],0,config(destination)],paid=True)
        assert number(SHAPES,'totalSupply()')==supply and number(SHAPES,'pendingFees()')==creator
        report['migration']['relistedWithoutRemint']=True
        report['retainedMigrationSnapshot']=rpc('evm_snapshot')
        matrix=report['retainedMigrationSnapshot']
        # Separate restored branches measure paid batch shapes, not portfolio returns.
        for price,base in ((200000000,150000000),(500000000,450000000)):
            assert rpc('evm_revert',matrix);matrix=rpc('evm_snapshot')
            branch=f'paid-batches-{price}';report['phase']=branch;save()
            index=number(factory,'managerCount()')
            expected=read(factory,f'configHashFor({PARAMS_T})',[PARAMS_T],[params_values(settings)],('bytes32',))[0]
            send(owner,factory,f'create(address,{PARAMS_T},bytes32)',['address',PARAMS_T,'bytes32'],[owner,params_values(settings),expected],operation='create',value=3*10**18)
            target=read(factory,'managerAt(uint256)',['uint256'],[index],('address',))[0]
            opening=rpc('evm_snapshot')
            before_supply=number(SHAPES,'totalSupply()');before_fees=number(SHAPES,'pendingFees()')
            send(keeper,target,'build(uint256,uint256[],uint256,bytes32)',['uint256','uint256[]','uint256','bytes32'],[3,[21*10**16],0,config(target)],operation='build',paid=True)
            assert number(SHAPES,'totalSupply()')-before_supply==3
            assert number(SHAPES,'pendingFees()')-before_fees==3*number(SHAPES,'mintFee()')
            assert rpc('evm_revert',opening)
            for offset in (0,4):
                proposals=[21*10**16+i*10000 for i in range(offset,offset+4)]
                send(keeper,target,'build(uint256,uint256[],uint256,bytes32)',['uint256','uint256[]','uint256','bytes32'],[3,proposals,0,config(target)],operation='build',paid=True,count=4)
            ids=[number(target,'openListingAt(uint256)',['uint256'],[i]) for i in range(8)]
            send(owner,target,'setExiting(bool)',['bool'],[True])
            # One paid eight-pack withdrawal creates real inventory for list1/3/8.
            send(keeper,target,'unlist(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[ids,0,config(target)],operation='unlist',paid=True,count=8)
            send(owner,target,'setExiting(bool)',['bool'],[False])
            send(owner,target,'setListingPaused(bool)',['bool'],[False])
            idle=rpc('evm_snapshot')
            for count in (1,3,8):
                assert rpc('evm_revert',idle);idle=rpc('evm_snapshot')
                proposals=[21*10**16+i*10000 for i in range(count)]
                send(keeper,target,'list(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[proposals,0,config(target)],operation='list',paid=True,count=count)
                selected=[number(target,'openListingAt(uint256)',['uint256'],[i]) for i in range(count)]
                send(owner,target,'setExiting(bool)',['bool'],[True])
                send(keeper,target,'unlist(uint256[],uint256,bytes32)',['uint256[]','uint256','bytes32'],[selected,0,config(target)],operation='unlist',paid=True,count=count)
                send(keeper,target,'liquidate(uint256,uint256,bytes32)',['uint256','uint256','bytes32'],[count,0,config(target)],operation='liquidate',paid=True,count=count)
        assert rpc('evm_revert',matrix)
        report['retainedMigrationSnapshot']=rpc('evm_snapshot')
        report['status']='PASS';report['elapsedSeconds']=time.monotonic()-start;save()
        print(json.dumps(dict(status='PASS',transactions=len(report['transactions']),rpc=url,destination=destination,migration=report['migration']),indent=1))
    except Exception as exc:
        report.update(status='FAIL',error=str(exc),elapsedSeconds=time.monotonic()-start);save();raise
    finally:
        report['ownedNodeRetained']=node.poll() is None;save()
    if report['status']=='PASS':write_profile(report)


def write_profile(report):
    assert report['status']=='PASS' and report['contractSourceSha256']==sources()
    paths=[OUT]
    for name in ('manager-measured-splitting-50k.json','manager-measured-owner-exit.json',
                 'manager-measured-sync-contexts.json','manager-measured-owner-batch-exit.json',
                 'manager-measured-ordinary-keeper.json','manager-measured-ordinary-relist.json'):
        path=ROOT/'docs/receipts'/name
        if path.exists():paths.append(path)
    rows={}
    for path in paths:
        packet=json.loads(path.read_text());assert packet['status']=='PASS'
        assert packet['contractSourceSha256']==report['contractSourceSha256']
        if 'fullGasSchedule' in packet:
            assert packet['fullGasSchedule']==report['managerValues']['gasSchedule']
        for original in packet.get('transactions',packet.get('measurements',[])):
            row=original.copy();receipt=row['receipt'];transaction=row['transaction']
            assert int(receipt['status'],16)==1
            row.update(hash=receipt['transactionHash'],gasUsed=int(receipt['gasUsed'],16),
                estimateKind=row.get('estimateKind','rpc-estimate'),signedGasLimit=int(transaction['gas'],16))
            assert type(row['gasEstimate']) is int and row['gasEstimate']>0
            op=row['operation'] or 'fund'
            rows.setdefault(op,[]).append(row)
    def curve(selected, metered=False):
        singles=[r for r in selected if r['workCount']==1]
        assert singles, 'one-work receipt baseline required'
        result={}
        for name,key in (('billed','gasUsed'),('estimate','gasEstimate'),('meter',None)):
            if name=='meter' and not metered:continue
            get=(lambda r:r[key]) if key else (lambda r:r['measuredWork']['measuredGas'])
            baseline=max(get(r) for r in singles)
            result['single_'+name+'_gas']=baseline
            result[name+'_per_extra_work']=max([0]+[-(-(get(r)-baseline)//(r['workCount']-1)) for r in selected if r['workCount']>1])
        return result
    paid=('build','list','sync','unlist','liquidate')
    aliases={'recover_sync':'recover'}
    operations=(*paid,'create','setExiting','withdraw','recover_sync','processAcquisitions','harvest')
    curves={op:curve(rows[aliases.get(op,op)],op in paid) for op in operations}
    owners={op:curve(rows[source]) for op,source in (('unlist','recoverUnlist'),('liquidate','recoverLiquidate'))}
    gas={op:c['single_billed_gas'] for op,c in curves.items()}
    estimates={op:c['single_estimate_gas'] for op,c in curves.items()}
    meters={op:curves[op]['single_meter_gas'] for op in paid}
    def contexts(selected,owner=False):
        result={}
        for row in selected:
            source=row['verifiedContext'] if owner else row['measuredWork']
            key=f"{source['gasAllowance']}:{source['workUnits']}"
            sample=dict(single_billed_gas=row['gasUsed'],single_estimate_gas=row['gasEstimate'])
            if not owner:sample['measured_gas']=source['measuredGas']
            result[key]={name:max(value,result.get(key,{}).get(name,0)) for name,value in sample.items()}
        assert result
        return result
    sync_contexts=contexts(rows['sync'])
    owner_sync_contexts=contexts(rows['recover'],True)
    source_paths=list(report['contractSourceSha256'])+['keeper/rehearse_manager_measured.py',
        'keeper/rehearse_manager_sync_contexts.py','keeper/policy.py','keeper/config.py',
        'sim/vault.py','sim/manager.py','sim/forward.py','sim/manager_operating_assessment.py']
    profile=dict(compensation_mode='bounded-measured-v1',contract_source_sha256=report['contractSourceSha256'],
        source_sha256={p:sha(ROOT/p) for p in source_paths},receipts=str(OUT.relative_to(ROOT)),receipts_sha256=sha(OUT),
        receipt_inputs=[dict(path=str(p.relative_to(ROOT)),sha256=sha(p)) for p in paths],
        measurements=rows,gas_proxy=gas,gas_estimate_proxy=estimates,gas_meter_proxy=meters,gas_curves=curves,
        owner_gas_curves=owners,fullGasSchedule=report['managerValues']['gasSchedule'],
        sync_contexts=sync_contexts,owner_sync_contexts=owner_sync_contexts,
        gas_meter_max_work={op:max(r['workCount'] for r in rows[op]) for op in paid},
        owner_gas_max_work={op:max(r['workCount'] for r in rows[source]) for op,source in
            (('unlist','recoverUnlist'),('liquidate','recoverLiquidate'),('recover_sync','recover'))},
        unmeasured_operations=['larger sync batches'],
        limitations=report['limitations']+['Count interpolation is a declared proxy, not an actual transaction receipt.',
            'Only recorded count support is admitted; larger sync/owner recovery calls remain unmeasured.',
            'Historical100k signed minPay values cannot be reused for50k settings; actual fresh preflight is required.'])
    (ROOT/'docs/receipts/manager-measured-cost-calibration.json').write_text(json.dumps(profile,indent=1)+'\n')


if __name__=='__main__':
    main()
