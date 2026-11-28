#!/usr/bin/env python3
"""Exercise an unapproved manager quote candidate through the production keeper executor."""
import argparse
import copy
import gzip
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
from eth_abi import decode, encode
from eth_account import Account
from eth_utils import keccak, to_checksum_address
import keeper as client
import policy
import tx as txm
import index as event_index
from config import PARAMS_T, params_values
from rehearse_manager_r2 import PUBLIC, FWA, SHAPES, PACKS, sources

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/receipts'
BASE_PROFILE='e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def calldata(signature,types=(),values=()): return '0x'+(keccak(text=signature)[:4]+encode(types,values)).hex()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--port',type=int,default=18784)
    args=parser.parse_args()
    if not args.execute: raise SystemExit('Plan: one new owned Osaka fork, unchanged authenticated native checkpoints, three quote changes, actual cold keeper executor/CLI calls and zero-budget owner exit. No public broadcast.')
    assert os.environ.get('CANDIDATE_RUN')=='1'
    packet=OUT/'manager-calibrated-receipts.json';assert not packet.exists(),'preserve existing attempt before continuation'
    baseline_path=OUT/'manager-operating-cost-calibration.json';assert sha(baseline_path)==BASE_PROFILE
    baseline=json.loads((OUT/'manager-baseline-settings.json').read_text())
    candidate=copy.deepcopy(baseline)
    candidate['gasSchedule'].update(selected=225000,synced=285000,list=380000)
    assert params_values(candidate)==params_values(json.loads((ROOT/'deploy/manager.json').read_text()))
    meta=json.loads((ROOT/'sim/out/manager-operating-checkpoint-metadata.json').read_text())
    baseline_raw=json.loads((OUT/'manager-operating-osaka-receipts.json').read_text())
    assert baseline_raw['status']=='PASS' and baseline_raw['contractSourceSha256']==sources()
    native_paths=[ROOT/'sim/out/manager-operating-native-checkpoint.json',ROOT/'sim/out/manager-operating-returned-native.json']
    for path in native_paths:
        expected=next(x['sha256'] for x in baseline_raw['checkpointLoads'] if x['path']==str(path.relative_to(ROOT)))
        assert sha(path)==expected
    with socket.socket() as available: available.bind(('127.0.0.1',args.port))
    work=Path(tempfile.mkdtemp(prefix='manager-calibrated-'));url=f'http://127.0.0.1:{args.port}'
    node_args=['anvil','--host','127.0.0.1','--port',str(args.port),'--accounts','0','--chain-id','31337','--hardfork','osaka',
               '--enable-tx-gas-limit','--gas-limit','60000000','--fork-url',PUBLIC,'--fork-block-number',str(meta['requestBlock']-1),
               '--retries','30','--fork-retry-backoff','5000','--silent']
    node=subprocess.Popen(node_args,stdout=open(work/'anvil.log','w'),stderr=subprocess.STDOUT,start_new_session=True)
    owner=Account.from_key(keccak(text='pack-vault-test-main-renewal-owner'));assert owner.address.lower()==meta['owner'].lower()
    keeper=Account.create();builder=Account.create();signers={a.address.lower():a for a in (owner,keeper,builder)}
    price,base=200000000,150000000;branch='startup';manager=meta['manager']
    report=dict(status='RUNNING',phase=branch,command=[sys.executable,*sys.argv],scriptSha256=sha(__file__),candidate=candidate,
                candidateApproval='UNAPPROVED_LOCAL_CANDIDATE',runtimeSourceSha256=sources(),baselineProfileSha256=BASE_PROFILE,
                sourceSha256={str(p.relative_to(ROOT)):sha(p) for p in native_paths},rpc=url,chainId=31337,executionHardfork='Osaka',
                ownedNodePid=node.pid,nodeCommand=node_args,workDirectory=str(work),transactions=[],executions=[],cliRuns=[],getterBootstraps=[],checkpointLoads=[],
                actors=dict(owner=owner.address,keeper=keeper.address,builder=builder.address),publicTransactions=0,
                clientIdentity=txm.client_identity([client,policy,txm,event_index]),limitations=[
                    'Allocated-only sync is an explicit production-executor quote test; the planner deliberately defers this job before settlement.',
                    'Imported checkpoint setup has no fabricated native events. Index bootstrap uses actual pinned onchain position getters; subsequent logs are ingested by the unmodified CLI.',
                    'Historical checkpoints and baseline69 receipts remain unchanged; no production approval or public transaction is included.'])
    def save():packet.write_text(json.dumps(report,indent=1)+'\n')
    save()
    def rpc(method,*params):
        request=urllib.request.Request(url,json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),{'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=600) as response: result=json.load(response)
        if 'error' in result: raise RuntimeError(method+': '+json.dumps(result['error']))
        return result['result']
    def batch(calls):
        body=[dict(jsonrpc='2.0',id=i,method=m,params=p) for i,(m,p) in enumerate(calls)]
        request=urllib.request.Request(url,json.dumps(body).encode(),{'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=120) as response:rows=sorted(json.load(response),key=lambda x:x['id'])
        assert all('error' not in row for row in rows),rows
        return [row['result'] for row in rows]
    def read(target,signature,types=(),values=(),returns=('uint256',)):
        raw=rpc('eth_call',dict(to=target,data=calldata(signature,types,values)),'latest')
        return decode(returns,bytes.fromhex(raw[2:]))
    def number(target,signature,types=(),values=()):return read(target,signature,types,values)[0]
    def config():return read(manager,'configurationHash()',returns=('bytes32',))[0]
    def prime():
        parent_base=base*8//7
        rpc('anvil_setNextBlockBaseFeePerGas',hex(parent_base));rpc('evm_mine')
        parent=rpc('eth_getBlockByNumber','latest',False);assert int(parent['gasUsed'],16)==0
        assert txm.next_base_fee(parent)==base
        client.RPC=url
        authenticated,future=client.inclusion_context();assert future==base and authenticated['hash']==parent['hash']
        return parent
    def fund_actor(address,amount):
        assert rpc('eth_getCode',address,'latest')=='0x' and int(rpc('eth_getTransactionCount',address,'latest'),16)==0
        assert int(rpc('eth_getBalance',address,'latest'),16)==0
        rpc('anvil_setBalance',address,hex(amount))
    def record(hash_,operation,estimate,limit,mode,account=None):
        receipt=None
        for _ in range(240):
            receipt=rpc('eth_getTransactionReceipt',hash_)
            if receipt is not None:break
            time.sleep(.25)
        assert receipt and int(receipt['status'],16)==1,(operation,hash_,receipt)
        transaction=rpc('eth_getTransactionByHash',hash_);header=rpc('eth_getBlockByHash',receipt['blockHash'],False)
        target=(account or manager).lower();topic='0x'+keccak(text='KeeperPaid(address,uint256)').hex()
        pay=sum(int(log['data'],16) for log in receipt['logs'] if log['address'].lower()==target and log['topics'][0]==topic)
        row=dict(branch=branch,operation=operation,workCount=1,actor=transaction['from'],targetAccount=account or manager,
                 executionHardfork='Osaka',estimateKind='rpc-estimate',hash=hash_,transactionHash=hash_,gasEstimate=estimate,signedGasLimit=limit,
                 gasUsed=int(receipt['gasUsed'],16),effectiveGasPrice=int(receipt['effectiveGasPrice'],16),blockBaseFeeWei=int(header['baseFeePerGas'],16),
                 gasCostWei=int(receipt['gasUsed'],16)*int(receipt['effectiveGasPrice'],16),compensationWei=pay,executionMode=mode,transaction=transaction,receipt=receipt)
        assert row['effectiveGasPrice']==price and row['blockBaseFeeWei']==base and limit<=16777216
        report['transactions'].append(row);save();return row
    def send(sender,target,signature,types=(),values=(),operation=None,value=0):
        prime();target=to_checksum_address(target)
        tx=dict(to=target,data=calldata(signature,types,values),value=hex(value),maxFeePerGas=hex(2*base+50000000),maxPriorityFeePerGas=hex(50000000),**{'from':sender})
        estimate=int(rpc('eth_estimateGas',tx),16);limit=(estimate*5+3)//4;assert limit<=16777216
        if sender.lower() in signers:
            signed=signers[sender.lower()].sign_transaction(dict(chainId=31337,nonce=int(rpc('eth_getTransactionCount',sender,'latest'),16),
                to=target,data=tx['data'],value=value,gas=limit,maxFeePerGas=2*base+50000000,maxPriorityFeePerGas=50000000,type=2))
            hash_=rpc('eth_sendRawTransaction','0x'+signed.raw_transaction.hex())
        else:
            allowed=(sender.lower()==meta['purchaser'].lower() or sender.lower()==read(SHAPES,'admin()',returns=('address',))[0].lower())
            code=rpc('eth_getCode',sender,'latest');assert allowed and (code=='0x' or len(code)==48 and code.startswith('0xef0100'))
            if int(rpc('eth_getBalance',sender,'latest'),16)<10**16:rpc('anvil_setBalance',sender,hex(10**18))
            rpc('anvil_impersonateAccount',sender);hash_=rpc('eth_sendTransaction',tx|dict(gas=hex(limit)));rpc('anvil_stopImpersonatingAccount',sender)
        return record(hash_,operation or signature.split('(')[0],estimate,limit,'real owner/admin/setup call')
    def apply_candidate(mode=0,zero=False):
        settings=copy.deepcopy(candidate);settings['renewalMode']=mode
        if zero:
            for key in ('routineCapWei','routineRatePerDayWei'):settings[key]=0
        send(owner.address,manager,f'setParams({PARAMS_T},bytes32)',[PARAMS_T,'bytes32'],[params_values(settings),config()],'setParams')
        assert rpc('eth_call',dict(to=manager,data=calldata('getParams()')),'latest').lower()=='0x'+encode([PARAMS_T],[params_values(settings)]).hex()
        if number(SHAPES,'mintFee()')!=500000000000000:
            admin=read(SHAPES,'admin()',returns=('address',))[0]
            send(admin,SHAPES,'setMintFee(uint256)',['uint256'],[500000000000000],'setMintFee')
        return settings
    def load(name,path):
        report['phase']='load-'+name;save();state=json.loads(path.read_text())
        chunks=[];chunk={};size=0
        for address,account in state['accounts'].items():
            cost=len(json.dumps({address:account}))
            if chunk and size+cost>600000:chunks.append(chunk);chunk={};size=0
            chunk[address]=account;size+=cost
        if chunk:chunks.append(chunk)
        for i,accounts in enumerate(chunks):
            report['phase']=f'load-{name}-{i+1}/{len(chunks)}';save()
            body=json.dumps(dict(block=None,best_block_number=None,accounts=accounts)).encode();assert len(body)*2+1000<2000000
            assert rpc('anvil_loadState','0x'+body.hex())
        body=gzip.compress(json.dumps(state|dict(accounts={})).encode(),mtime=0);assert len(body)*2+1000<2000000
        assert rpc('anvil_loadState','0x'+body.hex())
        calls=[];expected=[]
        for address,account in state['accounts'].items():
            calls += [('eth_getBalance',[address,'latest']),('eth_getTransactionCount',[address,'latest']),('eth_getCode',[address,'latest'])]
            expected += [int(account['balance'],0),int(account['nonce']),account['code'].lower()]
            for slot,value in account['storage'].items():calls.append(('eth_getStorageAt',[address,slot,'latest']));expected.append(int(value,16))
        for start in range(0,len(calls),100):
            for i,actual in enumerate(batch(calls[start:start+100]),start):
                wanted=expected[i];assert (actual.lower() if isinstance(wanted,str) else int(actual,16))==wanted,(name,calls[i])
        assert rpc('anvil_nodeInfo')['hardFork']=='Osaka'
        report['checkpointLoads'].append(dict(name=name,path=str(path.relative_to(ROOT)),sha256=sha(path),verifiedFields=len(calls)));save()
        fund_actor(keeper.address,10**18)
        return rpc('evm_snapshot')
    def bootstrap_index(directory):
        directory.mkdir(parents=True,exist_ok=True)
        deployment=number(manager,'deploymentBlock()');head=rpc('eth_getBlockByNumber','latest',False)
        path=directory/f'index-31337-{manager.lower()}-{deployment}.sqlite'
        idx=event_index.EventIndex(path,31337,manager,deployment,start_block=deployment)
        positions=[]
        for i in range(number(manager,'openListingCount()')):
            ident=number(manager,'openListingAt(uint256)',['uint256'],[i])
            p=read(manager,'position(uint256)',['uint256'],[ident],['uint256','uint256','uint256','uint256','uint64','uint8','uint256'])
            with idx.db:idx.db.execute('INSERT OR REPLACE INTO positions(id,pack_id,value,backing,debt,allocated_at,state) VALUES (?,?,?,?,?,?,?)',tuple(map(str,(ident,*p[:6]))))
            positions.append(dict(listing=ident,position=list(p)))
        idx.close();report['getterBootstraps'].append(dict(account=manager,block=int(head['number'],16),blockHash=head['hash'],positions=positions,
            note='Direct actual contract getter cache; no event or successful service answer fabricated. Local logs are ingested by production index.'));save()
    def expected_quote(operation):
        q=candidate['gasSchedule'];work=candidate['workFeeWei']
        sync=q['sync'];journal=q['journal'];selected=q['selected'];synced=q['synced'];pruned=q['pruned']
        build=q['build']+q['buildPack']+3*q['buildShape']+q['listed']
        if operation=='syncAllocated':return (sync+journal+selected)*price
        if operation=='syncResolved':return (sync+synced+pruned)*price+work
        if operation=='syncCombined':return (sync+journal+selected+synced+pruned)*price+work
        if operation=='list':return (q['list']+q['listed'])*price+work
        if operation=='build':return build*price+2*work
        raise ValueError(operation)  # 'renew' is retired (reuse-only strategy)
    def explicit(step,label):
        parent=prime();client.RPC=url
        state_path=work/f'{branch}-{label}-tx.json';assert not state_path.exists()
        logs=[];tm=txm.TxManager(url,str(state_path),keeper.address,['--unlocked','--from',keeper.address],confirmations=1,log=logs.append)
        assert tm.state['counted']==[]
        try:
            expected='0x'+config().hex();args0=client.to_cast(step,expected=expected)
            fees=client.fee_args(base,50000000);est,why,_=tm.preflight(manager,args0,fees);assert est is not None,why
            pay=client.compensation(manager,args0,keeper.address,fees);assert pay==expected_quote(label)
            cost,need,accepted=client.profitability_gate(est,price,pay,0,0,0,client.billed_ratio(tm,step[0]));assert accepted,(label,pay,cost)
            signed=client.to_cast(step,pay*8//10,expected);est2,why,_=tm.preflight(manager,signed,fees);assert est2 is not None,why
            signed_cost=client.execution_cost(est2,price,0,client.billed_ratio(tm,step[0]));assert pay>=signed_cost
            rpc('anvil_impersonateAccount',keeper.address)
            tm.submit(step[0],manager,signed,est2,base,50000000,pay,parent['hash'])
            assert not tm.wait(lambda pending,prio,max_fee:tm.preflight(pending['to'],pending['args'],['--gas-price',max_fee,'--priority-gas-price',prio])[0],30)
            rpc('anvil_stopImpersonatingAccount',keeper.address)
            counted=tm.state['counted'];assert len(counted)==1 and counted[0]['status']==1
            row=record(counted[0]['hash'],label,counted[0]['est'],counted[0]['gas_limit'],'production executor explicit candidate')
            assert row['compensationWei']==pay and row['compensationWei']>=row['gasCostWei']
            report['executions'].append(dict(branch=branch,label=label,coldHistory=True,estimate=est,signedEstimate=est2,quote=pay,minPay=pay*8//10,
                expectedCost=cost,signedCost=signed_cost,clientIdentity=txm.client_identity([client,policy,txm,event_index]),args=signed,counted=counted,logs=logs));save();return row
        finally:tm._lockf.close()
    def cli(label,expected,owner_exit=False,state_path=None,limit=10**16):
        prime();directory=work/(branch+'-'+label+'-index');bootstrap_index(directory)
        state_path=state_path or work/(branch+'-'+label+'-cli.json')
        before=json.loads(state_path.read_text()) if state_path.exists() else None
        sender=owner.address if owner_exit else keeper.address
        argv=[sys.executable,str(ROOT/'keeper/keeper.py'),manager,'--send','--from',sender,'--rpc',url,'--state',str(state_path),'--index',str(directory),
              '--max-steps','1','--confirmations','1','--pending-timeout','30']
        if owner_exit:argv+=['--caller-funded-exit','--exit-spend-limit-wei',str(limit)]
        else:assert before is None,'ordinary proof requires empty counted history'
        rpc('anvil_impersonateAccount',sender)
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True)
        rpc('anvil_stopImpersonatingAccount',sender)
        log=OUT/f'manager-calibrated-{branch}-{label}.log';log.write_text(result.stdout+result.stderr)
        after=json.loads(state_path.read_text());old_hashes={x['hash'] for x in (before or {}).get('counted',[])}
        fresh=[x for x in after['counted'] if x['hash'] not in old_hashes and not x.get('reorged')]
        report['cliRuns'].append(dict(branch=branch,label=label,command=argv,exitStatus=result.returncode,log=str(log.relative_to(ROOT)),logSha256=sha(log),coldHistory=before is None,
                                      state=after,expectedOperation=expected));save()
        assert result.returncode==0,(label,result.stdout[-2000:],result.stderr[-1000:])
        assert len(fresh)==1 and fresh[0]['label']==expected,(label,[x['label'] for x in fresh],result.stdout[-2500:])
        entry=fresh[0];row=record(entry['hash'],label,entry['est'],entry['gas_limit'],'ordinary CLI owner exit' if owner_exit else 'ordinary CLI')
        if not owner_exit:
            assert row['compensationWei']>0 and row['compensationWei']>=row['gasCostWei']
            raw=bytes.fromhex(row['transaction']['input'][10:]);signature=entry['args'][0] if 'args' in entry else ''
            assert entry['expected_pay']==row['compensationWei']==expected_quote(label)
            abi={'sync':['uint256[]','uint256','uint256','bytes32'],'list':['uint256[]','uint256','bytes32'],
                 'renew':['uint256[]','uint256[]','uint256[]','uint256','bytes32'],'build':['uint256','uint256[]','uint256','bytes32']}[expected]
            index={'sync':2,'list':1,'renew':3,'build':2}[expected]
            actual_min_pay=decode(abi,raw)[index];assert actual_min_pay==entry['expected_pay']*8//10
            row.update(minPay=actual_min_pay,configuredQuote=entry['expected_pay']);save()
        return row,after
    try:
        for _ in range(600):
            assert node.poll() is None,(work/'anvil.log').read_text()[-2000:]
            try:
                if rpc('eth_chainId')=='0x7a69':break
            except urllib.error.URLError:time.sleep(1)
        else:raise RuntimeError('owned Osaka startup timeout')
        assert rpc('anvil_nodeInfo')['hardFork']=='Osaka';bare=rpc('evm_snapshot');report['bareSnapshot']=bare;save()
        allocated=load('allocated',native_paths[0])
        for price,base in ((200000000,150000000),(500000000,450000000)):
            for combined in (False,True):
                assert rpc('evm_revert',allocated);allocated=rpc('evm_snapshot')
                branch=f'allocated-{price}-'+('combined' if combined else 'separate');report['phase']=branch;save();apply_candidate()
                if not combined:explicit(('sync',[],0),'syncAllocated')
                send(meta['purchaser'],FWA,'acceptDepositorBid(uint256)',['uint256'],[meta['listing']],'acceptDepositorBid')
                cli('syncCombined' if combined else 'syncResolved','sync')
                assert number(manager,'renewalEligible(uint256)',['uint256'],[meta['pack']])
        assert rpc('evm_revert',bare)
        returned=load('returned',native_paths[1])
        for price,base in ((200000000,150000000),(500000000,450000000)):
            for reuse in (False,True):
                assert rpc('evm_revert',returned);returned=rpc('evm_snapshot')
                branch=f'returned-{price}-'+('reuse' if reuse else 'fresh');report['phase']=branch;save();apply_candidate(1 if reuse else 0)
                cli('list' if reuse else 'renew','list' if reuse else 'renew')
        for price,base in ((200000000,150000000),(500000000,450000000)):
            assert rpc('evm_revert',returned);returned=rpc('evm_snapshot')
            branch=f'opening-{price}';report['phase']=branch;save();apply_candidate()
            if int(rpc('eth_getBalance',builder.address,'latest'),16)==0:fund_actor(builder.address,2*10**18)
            factory=read(manager,'factory()',returns=('address',))[0];before=number(factory,'managerCount()')
            expected=read(factory,f'configHashFor({PARAMS_T})',[PARAMS_T],[params_values(candidate)],('bytes32',))[0]
            created=send(builder.address,factory,f'create(address,{PARAMS_T},bytes32)',['address',PARAMS_T,'bytes32'],[owner.address,params_values(candidate),expected],'create',5*10**17)
            original=manager;manager=read(factory,'managerAt(uint256)',['uint256'],[before],('address',))[0]
            created.update(createdManager=manager,targetAccount=manager);save()
            assert number(manager,'openListingCount()')==0
            cli('build','build');assert number(manager,'openListingCount()')==1
            if price==200000000:
                apply_candidate(zero=True);exit_state=work/'zero-budget-exit.json';signed_before=0
                for step in range(8):
                    if number(manager,'openListingCount()')==0 and number(manager,'idlePackCount()')==0 and int(rpc('eth_getBalance',manager,'latest'),16)==0:break
                    ids=[number(manager,'openListingAt(uint256)',['uint256'],[i]) for i in range(number(manager,'openListingCount()'))]
                    if number(FWA,'topListingId()') in ids:
                        ready=number(FWA,'topListingSince()')+43201
                        if int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16)<ready:rpc('evm_setNextBlockTimestamp',ready);rpc('evm_mine')
                    expected_op='setExiting' if not read(manager,'windingDown()',returns=('bool',))[0] else ('unlist' if ids else ('liquidate' if number(manager,'idlePackCount()') else 'withdraw'))
                    _,exit_data=cli(f'owner-exit-{step}',expected_op,True,exit_state,10**16-signed_before);signed_before=exit_data['signed_upper_wei']
                terminal=dict(cash=int(rpc('eth_getBalance',manager,'latest'),16),credit=number(FWA,'feeCredit(address)',['address'],[manager]),
                    open=number(manager,'openListingCount()'),idle=number(manager,'idlePackCount()'),recovery=number(manager,'recoveryPackCount()'),receipts=number(manager,'pendingReceipts()'))
                assert not any(terminal.values()) and signed_before<=10**16
                report['zeroBudgetExit']=dict(account=manager,terminal=terminal,signedMaximumWei=signed_before);save()
            manager=original
        assert report['runtimeSourceSha256']==sources()
        report.update(status='PASS',phase='complete');save();write_profile(packet,baseline_path)
        print(json.dumps(dict(status='PASS',transactions=len(report['transactions']),cliRuns=len(report['cliRuns'])),indent=1))
    except BaseException as exc:report.update(status='FAIL',error=repr(exc));save();raise


def write_profile(raw_path,baseline_path):
    raw=json.loads(raw_path.read_text());assert raw['status']=='PASS'
    profile=json.loads(baseline_path.read_text());assert sha(baseline_path)==BASE_PROFILE
    profile=copy.deepcopy(profile);profile['candidate']=raw['candidate'];profile['candidateApproval']='UNAPPROVED_LOCAL_CANDIDATE'
    aliases={'syncAllocated':'sync','syncResolved':'sync','syncCombined':'sync','list':'list','renew':'renew','build':'build','create':'create'}
    for original in raw['transactions']:
        if original['operation'] not in aliases:continue
        row=copy.deepcopy(original);op=aliases[row['operation']]
        row.update(recordedOperation=row['operation'],operation=op,calibrationOperation=op,source=str(raw_path.relative_to(ROOT)),estimateKind='rpc-estimate')
        profile['measurements'][op].append(row)
    for op,rows in profile['measurements'].items():
        ones=[r for r in rows if r['workCount']==1];billed=max(r['gasUsed'] for r in ones)
        estimated=[r for r in rows if r['estimateKind']=='rpc-estimate'] or rows
        est=max(r['gasEstimate'] for r in estimated if r['workCount']==1)
        slope=lambda field,value,items:max([0]+[max(0,(r[field]-value+r['workCount']-2)//(r['workCount']-1)) for r in items if r['workCount']>1])
        profile['gas_curves'][op]=dict(single_billed_gas=billed,single_estimate_gas=est,billed_per_extra_work=slope('gasUsed',billed,rows),estimate_per_extra_work=slope('gasEstimate',est,estimated))
        profile['gas_proxy'][op]=billed;profile['gas_estimate_proxy'][op]=est
    profile['receipt_inputs'] += [dict(path=str(baseline_path.relative_to(ROOT)),sha256=sha(baseline_path)),dict(path=str(raw_path.relative_to(ROOT)),sha256=sha(raw_path))]
    profile.update(receipts=str(raw_path.relative_to(ROOT)),receipts_sha256=sha(raw_path),method='Baseline immutable gas envelope plus actual calibrated candidate keeper execution samples',
        source_sha256=raw['runtimeSourceSha256']|{name:sha(ROOT/name) for name in ('keeper/rehearse_manager_calibration.py','keeper/keeper.py','keeper/policy.py','keeper/tx.py','keeper/index.py','keeper/config.py')})
    (OUT/'manager-calibrated-cost-calibration.json').write_text(json.dumps(profile,indent=1)+'\n')


if __name__=='__main__':main()
