#!/usr/bin/env python3
"""Fresh source-bound manager-only receipt refresh through the production deployment/keeper paths."""
import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from eth_abi import decode
from eth_utils import keccak,to_checksum_address
from config import PARAMS_T,guarded_call,tuple_arg

ROOT=Path(__file__).resolve().parent.parent
PUBLIC='https://mainnet.gateway.tenderly.co'
FWA='0x958C41181182e76F221331b2755b77D9e1426A98'
SHAPES='0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0'
PACKS='0xf21514B090Da7dF4390803497d6ae673801E5cA7'
OUT=ROOT/'docs/receipts'


def request(url,method,*params):
    req=urllib.request.Request(url,data=json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),headers={'Content-Type':'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=60) as f:r=json.load(f)
            if 'error' in r:raise RuntimeError(method+': '+json.dumps(r['error']))
            return r['result']
        except (OSError,TimeoutError):
            if attempt==3:raise
            time.sleep(2**attempt)


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def sources():return {str(p.relative_to(ROOT)):sha(p) for p in sorted((ROOT/'src').rglob('*.sol'))}

def integer(text):return int(str(text).split()[0],0)


def observe_live():
    block=int(request(PUBLIC,'eth_blockNumber'),16);header=request(PUBLIC,'eth_getBlockByNumber',hex(block),False)
    def read(target,signature,types,args=()):
        from eth_abi import encode
        sig=signature.split('(')[0];inputs=signature[signature.index('(')+1:-1].split(',') if '(' in signature and not signature.endswith('()') else []
        data='0x'+(keccak(text=signature)[:4]+encode(inputs,args)).hex()
        return decode(types,bytes.fromhex(request(PUBLIC,'eth_call',dict(to=target,data=data),hex(block))[2:]))[0]
    economics={name:read(FWA,name+'()',['uint256']) for name in ('ownerAcquisitionFeeBps','ownerSettlementFeeBps','topListingShareBps',
        'settlementDiscountBps','tokenSettlementDiscountBps','settlementWindow','finalizeWindow','activeListingCount','totalWeight','weightedBackingTotal','acquisitionFee')}
    retained=read(FWA,'retainedToProtocol()',['bool'])
    economics['mainPacksOracleExempt']=read(FWA,'oracleExemptCollections(address)',['bool'],[PACKS])
    economics['mainPacksCanDeposit']=read(FWA,'canDeposit(address)',['bool'],[PACKS])
    assert read(PACKS,'shapes()',['address']).lower()==SHAPES.lower()
    observation=dict(readOnly=True,rpc=PUBLIC,block=block,blockHash=header['hash'],timestamp=int(header['timestamp'],16),
        baseFeeWei=int(header['baseFeePerGas'],16),shapes=SHAPES,packs=PACKS,fwa=FWA,
        mintFeeWei=read(SHAPES,'mintFee()',['uint256']),acceptedMaximumWei=10**15,economics=economics,
        oracleExempt=economics['mainPacksOracleExempt'])
    with sqlite3.connect('file:'+str(ROOT/'sim/data/fwa.sqlite')+'?mode=ro',uri=True) as db:
        top=db.execute('SELECT max(block) FROM logs').fetchone()[0]
        configuration={}
        for at,args in db.execute("SELECT block,args FROM logs WHERE contract=? AND event='ConfigSet' ORDER BY block DESC,log_index DESC",(FWA.lower(),)):
            values=json.loads(args)
            configuration.setdefault(str(values['key']),dict(block=at,valueWei=int(values['value'])))
        last=configuration.get('22')
    assert last is not None,'archive lacks authenticated ConfigSet22 baseline'
    logs=[];topic='0x'+keccak(text='ConfigSet(uint256,uint256)').hex()
    for start in range(top+1,block+1,1500):
        logs+=request(PUBLIC,'eth_getLogs',dict(address=FWA,fromBlock=hex(start),toBlock=hex(min(block,start+1499)),topics=[topic]))
    min_logs=[]
    for log in logs:
        key=str(int(log['topics'][1],16));configuration[key]=dict(block=int(log['blockNumber'],16),valueWei=int(log['data'],16))
        if key=='22':min_logs.append(log)
    effective=configuration['22']['valueWei']
    continuity=dict(readOnly=True,rpc=PUBLIC,fromBlock=top+1,toBlock=block,blockHash=header['hash'],configKey=22,
        archiveLastChange=last,subsequentLogs=min_logs,minBackingWei=effective,retainedToProtocol=retained)
    observation['minBackingWei']=effective
    observation['configSetState']=configuration
    observation['economics']['surchargeBps']=configuration['13']['valueWei']
    assert retained == bool(configuration['40']['valueWei'])
    expected_value=economics['weightedBackingTotal']//economics['totalWeight']
    assert expected_value>0
    assert economics['acquisitionFee']==expected_value*(10000+economics['surchargeBps'])//10000
    multiplier=economics['acquisitionFee']*10**18//expected_value
    multiplier=multiplier*(10000-economics['ownerAcquisitionFeeBps'])//10000
    multiplier=multiplier*(10000-economics['topListingShareBps'])//10000
    observation['protocol']=economics|dict(inferredGrossMultiplier1e18=multiplier,expectedValueWei=expected_value,
        inferredGrossMultiplierRoundingBound=(10**18+expected_value-1)//expected_value+2,
        retainedToProtocol=retained)
    observation['configSetLogsSinceArchive']=logs
    provenance=json.loads((OUT/'manager-standard-backing-fork.json').read_text())['dependencies']
    observation['dependencyRuntimeContinuity']={}
    for name,target in (('FWA',FWA),('Shapes',SHAPES),('ShapePacks',PACKS)):
        runtime=hashlib.sha256(bytes.fromhex(request(PUBLIC,'eth_getCode',target,hex(block))[2:])).hexdigest()
        assert runtime==provenance[name]['runtimeSha256'],name+' differs from verified MAIN dependency'
        observation['dependencyRuntimeContinuity'][name]=dict(address=target,runtimeSha256=runtime,verifiedSourceSha256=provenance[name]['sourceSha256'])
    (OUT/'manager-r2-live-observation.json').write_text(json.dumps(observation,indent=1)+'\n')
    (OUT/'manager-r2-min-backing-continuity.json').write_text(json.dumps(continuity,indent=1)+'\n')
    return observation


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--port',type=int,default=18731);ap.add_argument('--execute',action='store_true');ap.add_argument('--resume',action='store_true');a=ap.parse_args()
    if not a.execute:raise SystemExit('Plan: fresh isolated fork; manager-only deployment,0.5ETH single-pack and1ETH three-pack owners; approximately22local transactions.')
    if os.environ.get('CANDIDATE_RUN')!='1':raise SystemExit('CANDIDATE_RUN=1 requires the frozen authorized batch')
    path=OUT/'manager-r2-closeout.json'
    previous=json.loads(path.read_text()) if a.resume else None
    if a.resume:
        assert previous['status']=='FAIL' and not(OUT/'manager-r2-cost-calibration.json').exists()
        assert previous['contractSourceSha256']==sources(),'source drift invalidates preserved fork continuation'
        # Only completed preparation is resumed; no acquisition or exit transaction is replayed.
        assert all(item['operation'] in ('deployment','create','build','setParams') for item in previous['transactions']),'later-phase failure needs explicit state reconciliation'
        live=json.loads((OUT/'manager-r2-live-observation.json').read_text())
        assert (live['block'],live['blockHash'])==(previous['forkBlock'],previous['forkHash'])
        work=Path(previous['workDirectory']);assert work.is_dir()
        url=previous['rpc'];assert url==f'http://127.0.0.1:{a.port}'
        pid=previous['ownedNodePid'];os.kill(pid,0)
        process=subprocess.check_output(['ps','-p',str(pid),'-o','command='],text=True)
        assert 'anvil' in process and f'--port {a.port}' in process and f'--fork-block-number {live["block"]}' in process,'preserved node identity differs'
    else:
        for name in ('manager-r2-closeout.json','manager-r2-cost-calibration.json','manager-r2-live-observation.json','manager-r2-min-backing-continuity.json'):
            assert not (OUT/name).exists(),'preserve existing R2 evidence; repair/resume explicitly instead of overwriting'
        with socket.socket() as available:available.bind(('127.0.0.1',a.port))
        live=observe_live();work=Path(tempfile.mkdtemp(prefix='shapes-manager-r2-'));url=f'http://127.0.0.1:{a.port}'
    assert live['mintFeeWei']<=live['acceptedMaximumWei']
    before_sources=sources()
    env=dict(os.environ,PATH=str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH',''))
    for name in list(env):
        if name=='VAULT' or name.startswith('KEEPER_KEYSTORE') or name.startswith('KEEPER_PASSWORD'):env.pop(name)
    def command(*args,environment=None):
        result=subprocess.run(list(map(str,args)),cwd=ROOT,env=environment or env,capture_output=True,text=True)
        if result.returncode:raise RuntimeError(' '.join(map(str,args[:3]))+': '+result.stdout[-3000:]+result.stderr[-3000:])
        return result.stdout.strip()
    def cast(*args):return command('cast',*args,'--rpc-url',url)
    def rpc(method,*args):return request(url,method,*args)
    def call(target,signature,*args):return cast('call',target,signature,*args)
    def number(target,signature,*args):return integer(call(target,signature,*args))
    def boundary():
        assert url.startswith('http://127.0.0.1:') and integer(cast('chain-id'))==31337
        assert rpc('web3_clientVersion').lower().startswith('anvil/')
        info=rpc('anvil_nodeInfo');assert info['forkConfig']['forkUrl']==PUBLIC and int(info['forkConfig']['forkBlockNumber'])==live['block']
    node=None if a.resume else subprocess.Popen(['anvil','--host','127.0.0.1','--port',str(a.port),'--chain-id','31337','--accounts','0','--silent',
        '--fork-url',PUBLIC,'--fork-block-number',str(live['block']),'--retries','30','--fork-retry-backoff','5000',
        '--base-fee','150000000','--gas-limit','16777216','--enable-tx-gas-limit'],stdout=open(work/'anvil.log','w'),stderr=subprocess.STDOUT)
    actors=previous['actors'] if a.resume else {label:to_checksum_address(keccak(text=f'manager-r2-{live["block"]}-{label}')[-20:]) for label in ('deployer','keeper','single-owner','batch-owner','purchaser')}
    direct_owner_upper={actors[label].lower():0 for label in ('single-owner','batch-owner')}
    if a.resume:
        for item in previous['transactions']:
            tx=item['transaction'];sender=tx['from'].lower()
            if sender in direct_owner_upper and item['operation']!='create':
                direct_owner_upper[sender]+=int(tx['gas'],16)*int(tx.get('maxFeePerGas') or tx['gasPrice'],16)+int(tx['value'],16)
        retained=previous.get('directOwnerSignedUpperWei',direct_owner_upper)
        for sender in direct_owner_upper:
            assert direct_owner_upper[sender]<=retained[sender]<=10**16
        direct_owner_upper=dict(retained)
    report=previous if a.resume else dict(status='RUNNING',command=[sys.executable,*sys.argv],rpc=url,chainId=31337,forkBlock=live['block'],forkHash=live['blockHash'],
        contractSourceSha256=before_sources,scriptSha256=sha(__file__),actors=actors,transactions=[],cases=[],workDirectory=str(work),ownedNodePid=node.pid,
        limits=['Local unlocked clean actors; encrypted-keystore/hardware transport is not exercised.',
            'Actual acquisitions expire through the real deadline/processor; no VRF response or protocol storage/balance is fabricated.',
            'Authenticated-VRF billed renewal and standalone harvest remain unmeasured.',
            'Gas-price sensitivities multiply these billed gas units; actual receipt basefee/effective price are retained.'])
    if a.resume:
        failure_log=Path('/tmp/shapes-manager-funded-rehearsal-resume.log' if 'resumeCommand' in previous else '/tmp/shapes-manager-funded-rehearsal.log')
        report.setdefault('attempts',[]).append(dict(status=previous['status'],command=previous.get('resumeCommand',previous['command']),scriptSha256=previous.get('resumedScriptSha256',previous['scriptSha256']),
            error=previous.get('error'),receiptHashes=[item['transaction']['hash'] for item in previous['transactions']],
            reportSha256BeforeResume=sha(path),failureLog=str(failure_log),failureLogSha256=sha(failure_log) if failure_log.exists() else None,
            failureLogTail=failure_log.read_text()[-2500:] if failure_log.exists() else None))
        report.update(status='RUNNING',resumeCommand=[sys.executable,*sys.argv],resumedScriptSha256=sha(__file__))
        report.pop('error',None)
    def save():path.write_text(json.dumps(report,indent=1)+'\n')
    def record(operation,tx_hash):
        tx=rpc('eth_getTransactionByHash',tx_hash);r=rpc('eth_getTransactionReceipt',tx_hash)
        assert r and int(r['status'],16)==1,operation+' receipt failed'
        block=rpc('eth_getBlockByHash',r['blockHash'],False)
        item=dict(operation=operation,actor=next((k for k,v in actors.items() if v.lower()==tx['from'].lower()),'unknown'),
            gasUsed=int(r['gasUsed'],16),effectiveGasPrice=int(r['effectiveGasPrice'],16),blockBaseFeeWei=int(block['baseFeePerGas'],16),
            gasCostWei=int(r['gasUsed'],16)*int(r['effectiveGasPrice'],16),transaction=tx,receipt=r)
        if not any(old['transaction']['hash']==tx_hash for old in report['transactions']):report['transactions'].append(item);save()
        return item
    def send(sender,target,signature,*args,value=0,label=None,legacy_gas_price=None):
        boundary();signature,args=guarded_call(signature,args,lambda view,*vals:call(target,view,*vals).split()[0])
        fee=int(rpc('eth_getBlockByNumber','pending',False)['baseFeePerGas'],16)
        fee_flags=['--gas-price',2*fee+50_000_000,'--priority-gas-price','50000000'] if legacy_gas_price is None else ['--legacy','--gas-price',legacy_gas_price]
        estimate=integer(cast('estimate',target,signature,*args,'--from',sender,'--value',value,
            *fee_flags))
        limit=(estimate*5+3)//4;assert limit<=16_777_216
        if sender.lower() in direct_owner_upper and not signature.startswith('create('):
            upper=limit*(2*fee+50_000_000 if legacy_gas_price is None else legacy_gas_price)+value
            assert direct_owner_upper[sender.lower()]+upper<=10**16,'owner direct exit/configuration reservation exceeds0.01ETH'
            direct_owner_upper[sender.lower()]+=upper
            report['directOwnerSignedUpperWei']=dict(direct_owner_upper);save()
        receipt=json.loads(cast('send',target,signature,*args,'--from',sender,'--unlocked','--value',value,
            '--gas-limit',limit,*fee_flags,'--json'));receipt=receipt.get('data',receipt)
        item=record(label or signature.split('(')[0],receipt['transactionHash'])
        if legacy_gas_price is not None:
            assert item['effectiveGasPrice']==legacy_gas_price and int(item['transaction']['type'],16)==0
        return item
    def state(manager):
        return dict(cashWei=integer(cast('balance',manager)),feeCreditWei=number(FWA,'feeCredit(address)(uint256)',manager),
            **{name:number(manager,name+'()(uint256)') for name in ('openListingCount','idlePackCount','recoveryPackCount','pendingReceipts')})
    def quiet_time():
        now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16);phase=now%43200
        if phase>=39600:rpc('evm_setNextBlockTimestamp',now+43200-phase+60);rpc('evm_mine')
    try:
        for _ in range(180):
            if node is not None and node.poll() is not None:raise RuntimeError('owned R2 node exited during startup')
            try:boundary();break
            except (RuntimeError,OSError):time.sleep(1)
        else:raise RuntimeError('R2 fork startup timed out')
        assert rpc('eth_getBlockByNumber',hex(live['block']),False)['hash']==live['blockHash']
        if a.resume:
            initial_balances=report['initialActorBalancesWei']
            assert number(SHAPES,'mintFee()(uint256)')==live['mintFeeWei']
            for item in report['transactions']:
                receipt=rpc('eth_getTransactionReceipt',item['transaction']['hash'])
                assert receipt and int(receipt['status'],16)==1 and receipt['blockHash']==item['receipt']['blockHash'],'preserved receipt changed'
        else:
            for actor in actors.values():
                assert cast('code',actor)=='0x' and integer(cast('nonce',actor))==0 and integer(cast('balance',actor))==0
                rpc('anvil_setBalance',actor,hex(10*10**18));rpc('anvil_impersonateAccount',actor)
            initial_balances={k:integer(cast('balance',v)) for k,v in actors.items()};report['initialActorBalancesWei']=initial_balances
        save()
        # Historical requests on this new fork may only expire through their actual deadline.
        for _ in range(64):
            if number(FWA,'unsettledAcquisitionCount()(uint256)')==0:break
            cursor=number(FWA,'nextSequenceToProcess()(uint64)');req=number(FWA,'requestIdAtSequence(uint64)(uint256)',cursor)
            meta=call(FWA,'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)',req).splitlines()
            needed=max(0,integer(meta[1])+1-integer(cast('block-number')));assert needed<=7201
            while needed:
                count=min(32,needed);rpc('anvil_mine',hex(count));needed-=count
            send(actors['purchaser'],FWA,'processAcquisitions(uint256)',16,label='historical timeout setup')
        assert number(FWA,'unsettledAcquisitionCount()(uint256)')==0
        if a.resume:
            factory=report['factory'];assert cast('code',factory)!='0x'
        else:
            report['deploymentOutput']=command('script/deploy.sh','deploy/manager-factory.json','--target','manager','--broadcast',
                environment=env|dict(RPC_URL=url,FORGE_WALLET_ARGS='--unlocked --sender '+actors['deployer']))
            deployment=json.loads((ROOT/'broadcast/Deploy.s.sol/31337/run-latest.json').read_text())
            assert not any(t.get('contractName')=='PackVault' for t in deployment['transactions'])
            factory=next(t['contractAddress'] for t in deployment['transactions'] if t.get('contractName')=='PackManagerFactory');report['factory']=factory
            for receipt in deployment['receipts']:record('deployment',receipt['transactionHash'])
            report['factoryPostflight']=command(sys.executable,'script/release.py','postflight-manager',factory,'deploy/manager-factory.json',environment=env|dict(RPC_URL=url))
        values=json.loads((ROOT/'deploy/manager.json').read_text());assert values['packUnitsMask']==8 and values['renewalMode']==0
        if a.resume:
            assert report['managerValuesSha256']==sha(ROOT/'deploy/manager.json') and report['managerValues']==values
            creator_before=report['creatorFeesBeforeWei']
        else:creator_before=number(SHAPES,'pendingFees()(uint256)');report['creatorFeesBeforeWei']=creator_before
        report.update(managerValues=values,managerValuesSha256=sha(ROOT/'deploy/manager.json'),liveObservation='docs/receipts/manager-r2-live-observation.json')
        keeper_state=work/'keeper-state.json';index=work/'index';index.mkdir(exist_ok=True)
        for label,funding,packs in (('single-owner',5*10**17,1),('batch-owner',10**18,3)):
            owner=actors[label];case=next((case for case in report['cases'] if case['label']==label),None)
            if case is not None:
                manager=case['manager'];assert case['owner']==owner and case['fundingWei']==funding and case['expectedPacks']==packs
                assert call(manager,'owner()(address)').lower()==owner.lower()
                if 'afterBuild' in case:
                    assert state(manager)==case['afterBuild'],'prepared inventory/cash changed before resume'
                    assert number(manager,'openListingCount()(uint256)')==packs
                    assert call(manager,'budget()(uint256,uint256)').split()==['0','0']
                    zeros=values|dict(routineCapWei=0,routineRatePerDayWei=0,essentialCapWei=0,essentialRatePerDayWei=0)
                    expected=call(factory,f'configHashFor({PARAMS_T})(bytes32)',tuple_arg(zeros))
                    assert call(manager,'configurationHash()(bytes32)')==expected,'prepared owner settings or flags changed'
                    continue
            else:
                count=number(factory,'managerCount()(uint256)')
                send(owner,factory,f'create(address,{PARAMS_T})',owner,tuple_arg(values),value=funding)
                manager=call(factory,'managerAt(uint256)(address)',count).split()[0]
                initial_cash=state(manager)['cashWei'];assert initial_cash==funding,'fresh-clone dust would change the declared funding case'
                case=dict(owner=owner,label=label,manager=manager,fundingWei=funding,initialAccountCashWei=initial_cash,preexistingDustWei=initial_cash-funding,expectedPacks=packs);report['cases'].append(case);save()
                case['postflight']=command(sys.executable,'script/release.py','postflight-manager',factory,'deploy/manager-factory.json',manager,owner,funding,environment=env|dict(RPC_URL=url))
            quiet_time()
            keeper_env=env|dict(FACTORY=factory,KEEPER_FROM=actors['keeper'],RPC_URL=url,POLL_SECONDS='0',HEALTH_PORT='0',
                KEEPER_ARGS=f'--state {keeper_state} --index {index} --loop 0 --max-steps 1 --confirmations 1')
            for attempt in range(16):
                output=command('sh','keeper/entrypoint.sh',environment=keeper_env)
                log=work/f'keeper-{label}-run{len(report.get("attempts",[]))}-{attempt}.log';log.write_text(output)
                report.setdefault('keeperPasses',[]).append(dict(case=label,passIndex=attempt,log=str(log),tail=output[-4000:],account=state(manager)))
                save()
                if keeper_state.exists():
                    saved=json.loads(keeper_state.read_text())
                    for entry in saved['counted']:
                        if not entry.get('reorged'):record('build' if entry['label'].split()[0]=='build' else entry.get('function',entry['label']),entry['hash'])
                    if not saved.get('pending') and state(manager)['openListingCount']==packs:break
                rpc('evm_mine')
            assert state(manager)['openListingCount']==packs,'bounded keeper indexing/build did not complete after16passes'
            case['afterBuild']=state(manager)
            send(owner,manager,f'setParams({PARAMS_T})',tuple_arg(values|dict(routineCapWei=0,routineRatePerDayWei=0,essentialCapWei=0,essentialRatePerDayWei=0)))
        assert number(SHAPES,'pendingFees()(uint256)')-creator_before==12*live['mintFeeWei']
        quiet_time();acquire_gas_price=200_000_000
        assert int(rpc('eth_getBlockByNumber','pending',False)['baseFeePerGas'],16)<=acquire_gas_price
        quote=[integer(v) for v in call(FWA,'quoteAcquisitionPrice()(uint256,uint256,uint256)','--from',actors['purchaser'],
            '--block','pending','--legacy','--gas-price',acquire_gas_price).splitlines()]
        assert len(quote)==3 and quote[0]+quote[1]==quote[2];price=quote[2]
        report['acquisitionQuote']=dict(fromAddress=actors['purchaser'],legacyGasPriceWei=acquire_gas_price,
            acquisitionFeeWei=quote[0],vrfFeeWei=quote[1],exactAttachedValueWei=price)
        purchaser_before=integer(cast('balance',actors['purchaser']))
        acquired=send(actors['purchaser'],FWA,'acquire(address,uint256,uint256,uint256,uint256)',actors['purchaser'],1,0,0,10000,value=price,legacy_gas_price=acquire_gas_price)
        requested_topic='0x'+keccak(text='AcquisitionRequested(uint256,address,uint256,uint256)').hex()
        vrf_topic='0x'+keccak(text='VrfServiceFeePaid(address,uint256)').hex()
        actual_fee=sum(decode(['uint256','uint256'],bytes.fromhex(log['data'][2:]))[0] for log in acquired['receipt']['logs'] if log['address'].lower()==FWA.lower() and log['topics'][0]==requested_topic)
        actual_vrf=sum(int(log['data'],16) for log in acquired['receipt']['logs'] if log['address'].lower()==FWA.lower() and log['topics'][0]==vrf_topic)
        immediate_refund=integer(cast('balance',actors['purchaser']))-purchaser_before+acquired['gasCostWei']+price
        report['acquisitionQuote'].update(actualAcquisitionFeeWei=actual_fee,actualVrfFeeWei=actual_vrf,immediateRefundWei=immediate_refund)
        assert (actual_fee,actual_vrf)==(quote[0],quote[1]) and immediate_refund==price-actual_fee-actual_vrf==0
        assert number(FWA,'unsettledAcquisitionCount()(uint256)')>0
        for case in report['cases']:send(case['owner'],case['manager'],'setExiting(bool)','true')
        seq=number(FWA,'nextSequenceToProcess()(uint64)');req=number(FWA,'requestIdAtSequence(uint64)(uint256)',seq)
        meta=call(FWA,'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)',req).splitlines();needed=max(0,integer(meta[1])+1-integer(cast('block-number')));assert needed<=7201
        while needed:
            count=min(32,needed);rpc('anvil_mine',hex(count));needed-=count
        now=int(rpc('eth_getBlockByNumber','latest',False)['timestamp'],16);rpc('evm_setNextBlockTimestamp',now+13*3600);rpc('evm_mine');quiet_time()
        # The first owner explicitly pays for real foreign-queue processing and recovery.
        send(report['cases'][0]['owner'],FWA,'processAcquisitions(uint256)',16)
        assert number(FWA,'unsettledAcquisitionCount()(uint256)')==0
        refund=number(FWA,'acquisitionRefundCredit(address)(uint256)',actors['purchaser'])
        assert refund>0,'the genuine expired request must leave its payer a refund'
        refund_before=integer(cast('balance',actors['purchaser']))
        refunded=send(actors['purchaser'],FWA,'withdrawAcquisitionRefund()',label='acquisition refund')
        assert integer(cast('balance',actors['purchaser']))-refund_before+refunded['gasCostWei']==refund
        assert number(FWA,'acquisitionRefundCredit(address)(uint256)',actors['purchaser'])==0
        report['externalRequest']=dict(priceWei=price,refundWei=refund,serviceCostWei=price-refund)
        for case in report['cases']:
            manager,owner=case['manager'],case['owner'];ids=[number(manager,'openListingAt(uint256)(uint256)',i) for i in range(case['expectedPacks'])]
            # Explicit bounded caller-funded sync on the actual post-timeout journal.
            send(owner,manager,'recover(uint256[],uint256)','['+','.join(map(str,ids))+']',0)
            owner_state=work/(case['label']+'-exit.json');owner_index=work/(case['label']+'-index');owner_index.mkdir()
            for attempt in range(8):
                reserved=json.loads(owner_state.read_text()).get('signed_upper_wei',0) if owner_state.exists() else 0
                direct=direct_owner_upper[owner.lower()]
                assert direct+reserved<10**16
                args=[sys.executable,'keeper/keeper.py',manager,'--send','--from',owner,'--rpc',url,'--state',owner_state,'--index',owner_index,
                    '--caller-funded-exit','--exit-spend-limit-wei',str(10**16-direct-reserved),'--max-steps','32','--confirmations','1','--pending-timeout','30']
                output=command(*args);(work/f'{case["label"]}-exit-{attempt}.log').write_text(output)
                saved=json.loads(owner_state.read_text())
                for entry in saved['counted']:
                    if not entry.get('reorged'):record(entry.get('function',entry['label']),entry['hash'])
                if all(v==0 for v in state(manager).values()):break
                rpc('evm_mine')
            assert all(v==0 for v in state(manager).values())
            assert saved['stats']['paid_wei']==0 and direct_owner_upper[owner.lower()]+saved['signed_upper_wei']<=10**16
            case.update(final=state(manager),ownerExitSignedUpperWei=direct_owner_upper[owner.lower()]+saved['signed_upper_wei'])
        # Decode actual payments/mints; owner debits and account expenses close independently.
        pay_topic='0x'+keccak(text='KeeperPaid(address,uint256)').hex();mint_topic='0x'+keccak(text='ShapeMinted(uint256,address,uint256,bytes32,uint256)').hex()
        keeper_paid=sum(int(log['data'],16) for item in report['transactions'] for log in item['receipt']['logs'] if log['topics'] and log['topics'][0]==pay_topic)
        minted=[log for item in report['transactions'] for log in item['receipt']['logs'] if log['address'].lower()==SHAPES.lower() and log['topics'][0]==mint_topic]
        fee_topic='0x'+keccak(text='MintFeeAccrued(uint256)').hex()
        accrued=sum(int(log['data'],16) for item in report['transactions'] for log in item['receipt']['logs'] if log['address'].lower()==SHAPES.lower() and log['topics'][0]==fee_topic)
        assert len(minted)==12 and all(decode(['uint256','bytes32','uint256'],bytes.fromhex(log['data'][2:]))[0]==10**16 for log in minted)
        creator=number(SHAPES,'pendingFees()(uint256)')-creator_before;assert creator==accrued==12*live['mintFeeWei']
        withdrawn_topic='0x'+keccak(text='Withdrawn(address,uint256)').hex()
        for case in report['cases']:
            owner=case['owner'];own=[t for t in report['transactions'] if t['transaction']['from'].lower()==owner.lower()]
            withdrew=sum(int(log['data'],16) for item in own for log in item['receipt']['logs'] if log['address'].lower()==case['manager'].lower() and log['topics'][0]==withdrawn_topic)
            gas=sum(t['gasCostWei'] for t in own);end=integer(cast('balance',owner));assert end-initial_balances[case['label']]==withdrew-case['fundingWei']-gas
            case.update(withdrawnWei=withdrew,walletGasWei=gas,ownerNetWei=end-initial_balances[case['label']],ownerLedgerGapWei=0)
        assert sum(c['initialAccountCashWei']-c['withdrawnWei'] for c in report['cases'])==creator+keeper_paid
        keeper_gas=sum(t['gasCostWei'] for t in report['transactions'] if t['actor']=='keeper')
        assert integer(cast('balance',actors['keeper']))-initial_balances['keeper']==keeper_paid-keeper_gas
        purchaser_gas=sum(t['gasCostWei'] for t in report['transactions'] if t['actor']=='purchaser')
        assert integer(cast('balance',actors['purchaser']))-initial_balances['purchaser']==refund-price-purchaser_gas
        deployment_gas=sum(t['gasCostWei'] for t in report['transactions'] if t['actor']=='deployer')
        assert integer(cast('balance',actors['deployer']))-initial_balances['deployer']==-deployment_gas
        assert before_sources==sources()
        report.update(status='PASS',finalBlock=integer(cast('block-number')),creatorPrimaryFeesAccruedWei=creator,paidPrimaryShapeMints=12,
            keeper=dict(compensationWei=keeper_paid,walletGasWei=keeper_gas,netWei=keeper_paid-keeper_gas),
            purchaserWalletGasWei=purchaser_gas,deploymentWalletGasWei=deployment_gas,accountLedgerGapWei=0)
        save()
        measurements={}
        for item in report['transactions']:measurements.setdefault(item['operation'],[]).append({k:item[k] for k in ('actor','gasUsed','effectiveGasPrice','blockBaseFeeWei','gasCostWei')}|dict(hash=item['transaction']['hash']))
        aliases=dict(create='create',setExiting='setExiting',withdraw='withdraw',unlist='recoverUnlist',liquidate='recoverLiquidate',recover_sync='recover',processAcquisitions='processAcquisitions',build='build')
        gas={key:max(x['gasUsed'] for x in measurements[value]) for key,value in aliases.items()}
        for key in ('build','unlist','liquidate'):
            gas[key]=max(item['gasUsed'] for item in report['transactions'] if item['operation']==aliases[key]
                         and item['transaction']['to'].lower()==report['cases'][0]['manager'].lower())
        gas['harvest']=300000
        calibration=dict(method='Actual new-source isolated-fork billed receipts; smaller one-pack floor plus work-size quoted allowance in model',
            contract_source_sha256=before_sources,source_sha256=before_sources,receipts=str(path.relative_to(ROOT)),receipts_sha256=sha(path),gas_proxy=gas,
            measurements=measurements,unmeasured_operations=['renew','standalone-harvest','list','sync'],
            limits=['Single and three-pack samples are retained separately; proxy floors are not exact curves for every batch.',
                'recover_sync is an unpaid owner-recovery receipt, not paid routine sync; list/sync variable work and authenticated-VRF renewal remain unmeasured.',
                'Standalone harvest uses an explicit300000gas proxy, not an invented receipt.',
                'Owner0.5ETH case and separate1ETH calibration case have no further account funding; wallet gas is separate from account cash.',
                'One-time deployment gas is separate startup cost; model owners pay clone creation gas.'])
        (OUT/'manager-r2-cost-calibration.json').write_text(json.dumps(calibration,indent=1)+'\n')
        print(json.dumps(dict(status='PASS',forkBlock=live['block'],factory=factory,cases=report['cases'],gas_proxy=gas),indent=1))
    except Exception as exc:report.update(status='FAIL',error=str(exc));save();raise
    finally:
        # Preserve a failed fork and its exact progress for a bounded repair, rather than replay setup.
        if report['status']=='PASS' and node is not None and node.poll() is None:node.terminate();node.wait(30)


if __name__=='__main__':main()
