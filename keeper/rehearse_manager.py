#!/usr/bin/env python3
"""Manager-only production image/CLI rehearsal on fresh local Anvil, with no secrets.

Uses script/deploy.sh --target manager and the existing image keeper/proxy helpers.
No public transaction, pool deployment or protocol-state replacement is permitted.
"""
import argparse
import hashlib
import json
import os
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from eth_utils import keccak, to_checksum_address
import rehearse_image as I
from config import PARAMS_T, tuple_arg

ROOT=Path(__file__).resolve().parent.parent
PAY_TOPIC='0x496b3bf0725d338a836ecf0b614e039f3736dacfd57aa32af1bf55ea601ceaf5'


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--image',required=True)
    ap.add_argument('--fork-block',type=int,default=26486686);ap.add_argument('--port',type=int,default=18683)
    a=ap.parse_args()
    if os.environ.get('CANDIDATE_RUN')!='1':raise SystemExit('CANDIDATE_RUN=1 is required for this frozen rehearsal')
    for port in (a.port,a.port+1):
        with socket.socket() as available:available.bind(('127.0.0.1',port))
    I.PORT,I.PROXY_PORT,I.RPC=a.port,a.port+1,f'http://127.0.0.1:{a.port}'
    I.VAULT=None
    actors={name:to_checksum_address(keccak(text=f'pack-manager-image-{a.fork_block}-{name}')[-20:]) for name in ('deployer','owner','primary','purchaser')}
    work=Path(tempfile.mkdtemp(prefix='pack-manager-image-'))
    evidence=dict(chainId=31337,rpc=I.RPC,forkBlock=a.fork_block,image=a.image,actors=actors,transactions=[],steps=[],limits=[
        'Fresh unlocked local actors; encrypted-keystore/hardware transport and live Fly deployment are not exercised.',
        'One real pending request expires locally; authentic historical VRF renewal receipt remains a separate known limitation.'])
    node=subprocess.Popen(['anvil','--host','127.0.0.1','--port',str(a.port),'--chain-id','31337','--accounts','0','--silent',
        '--fork-url','https://mainnet.gateway.tenderly.co','--fork-block-number',str(a.fork_block),'--hardfork','osaka','--retries','30','--fork-retry-backoff','5000',
        '--base-fee','150000000','--gas-limit',str(I.MAX_GAS),'--enable-tx-gas-limit'],stdout=open(work/'anvil.log','w'),stderr=subprocess.STDOUT)
    workers=[];proxy=None;source={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    evidence['contractSourceSha256']=source

    def send(sender,target,sig='',*args,value=0,fees=None):
        from config import guarded_call
        if sig:sig,args=guarded_call(sig,args,lambda view,*a:I.cast('call',target,view,*a).split()[0])
        if fees is None:
            base=I.num(I.rpc('eth_getBlockByNumber','pending',False)['baseFeePerGas'])
            fees=['--gas-price',str(2*base+50_000_000),'--priority-gas-price','50000000']
        receipt=json.loads(I.cast('send',target,*([sig,*map(str,args)] if sig else []),'--from',sender,'--unlocked','--value',str(value),*fees,'--json'))
        receipt=receipt.get('data',receipt);assert int(receipt['status'],16)==1
        transaction=I.rpc('eth_getTransactionByHash',receipt['transactionHash'])
        evidence['transactions'].append(dict(operation=sig.split('(')[0] or 'fund',sender=sender,to=target,valueWei=value,
            arguments=list(args),transaction=transaction,receipt=receipt))
        return receipt

    def account():
        fields={name:I.call(name+'()(uint256)',to=I.MANAGER) for name in ('openListingCount','idlePackCount','recoveryPackCount','pendingReceipts')}
        fields['cashWei']=I.num(I.cast('balance',I.MANAGER));fields['feeCreditWei']=I.call('feeCredit(address)(uint256)',I.MANAGER,to=I.FWA)
        fields['owner']=I.cast('call',I.MANAGER,'owner()(address)');return fields

    owner_state=work/'owner-state.json';owner_index=work/'owner-index';owner_index.mkdir()
    def owner_exit():
        reserved=json.loads(owner_state.read_text()).get('signed_upper_wei',0) if owner_state.exists() else 0
        remaining=10**16-reserved
        if remaining<=0:raise RuntimeError('manager exit exhausted the accepted 0.01 ETH signed reservation cap')
        command=[sys.executable,'keeper/keeper.py',I.MANAGER,'--send','--from',actors['owner'],'--rpc',I.RPC,
            '--state',str(owner_state),'--index',str(owner_index),'--caller-funded-exit','--exit-spend-limit-wei',str(remaining),
            '--confirmations','1','--pending-timeout','30']
        output=I.sh(*command);evidence['steps'].append(dict(step='owner caller-funded CLI',command=command,output=output,state=account()))
        return output

    try:
        for _ in range(180):
            if node.poll() is not None:raise RuntimeError('owned manager Anvil exited during startup')
            try:
                assert I.num(I.cast('chain-id'))==31337
                break
            except (RuntimeError,AssertionError):time.sleep(1)
        else:raise RuntimeError('owned manager Anvil did not become ready')
        evidence['forkHash']=I.rpc('eth_getBlockByNumber',hex(a.fork_block),False)['hash']
        for actor in actors.values():
            assert I.cast('code',actor)=='0x' and I.num(I.cast('nonce',actor))==0 and I.num(I.cast('balance',actor))==0,'fresh actor is not clean'
            I.rpc('anvil_setBalance',actor,hex(10*10**18));I.rpc('anvil_impersonateAccount',actor)
        owner_start=I.num(I.cast('balance',actors['owner']))
        # Existing fork requests have no future VRF delivery here. Let the real processor
        # resolve only their actual expired deadlines before this manager exists.
        initial_pending=I.call('unsettledAcquisitionCount()(uint256)',to=I.FWA)
        for _ in range(64):
            if not I.call('unsettledAcquisitionCount()(uint256)',to=I.FWA):break
            cursor=I.call('nextSequenceToProcess()(uint64)',to=I.FWA)
            request=I.call('requestIdAtSequence(uint64)(uint256)',cursor,to=I.FWA)
            metadata=I.cast('call',I.FWA,'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)',request).splitlines()
            needed=max(0,I.num(metadata[1])+1-I.num(I.cast('block-number')))
            if needed>7201:raise RuntimeError('initial request deadline exceeds protocol bound')
            while needed:
                count=min(32,needed);I.rpc('anvil_mine',hex(count));needed-=count
            send(actors['purchaser'],I.FWA,'processAcquisitions(uint256)',16)
            if I.call('nextSequenceToProcess()(uint64)',to=I.FWA)<=cursor:raise RuntimeError('initial protocol queue made no genuine progress')
        else:
            if I.call('unsettledAcquisitionCount()(uint256)',to=I.FWA):raise RuntimeError('initial queue exceeds bounded setup allowance')
        evidence['steps'].append(dict(step='initial historical request timeout setup',requests=initial_pending,payer=actors['purchaser'],scope='External calibration actor before manager creation; not owner strategy funding or exit subsidy.'))
        values=ROOT/'deploy/manager-factory.json'
        deploy_output=I.sh('script/deploy.sh',values,'--target','manager','--broadcast',env=dict(os.environ,RPC_URL=I.RPC,FORGE_WALLET_ARGS=f"--unlocked --sender {actors['deployer']}"))
        deployment=json.loads((ROOT/'broadcast/Deploy.s.sol/31337/run-latest.json').read_text())
        assert not any(t.get('contractName')=='PackVault' for t in deployment['transactions']),'manager path deployed a pool'
        I.FACTORY=next(t['contractAddress'] for t in deployment['transactions'] if t.get('contractName')=='PackManagerFactory')
        evidence['deployment']=dict(target='manager',factory=I.FACTORY,output=deploy_output,transactions=deployment['transactions'],receipts=deployment['receipts'])
        params=json.loads((ROOT/'deploy/manager.json').read_text())
        send(actors['owner'],I.FACTORY,f'create(address,{PARAMS_T})',actors['owner'],tuple_arg(params),value=10**18)
        I.MANAGER=I.cast('call',I.FACTORY,'managerAt(uint256)(address)',0).split()[0]
        evidence['manager']=I.MANAGER
        initial_cash=I.num(I.cast('balance',I.MANAGER))
        evidence['initialManagerCashWei']=initial_cash
        evidence['preexistingManagerDustWei']=initial_cash-10**18
        evidence['postflight']=I.sh(sys.executable,'script/release.py','postflight-manager',I.FACTORY,values,I.MANAGER,actors['owner'],10**18,env=dict(os.environ,RPC_URL=I.RPC))
        volume=work.name+'-primary-data';I.sh('docker','volume','create',volume)
        primary=I.Keeper(work.name+'-primary',actors['primary'],volume,a.image,rpc=I.RPC,factory_only=True)
        shapes=I.cast('call',I.MANAGER,'shapes()(address)')
        live_mint_fee=I.call('mintFee()(uint256)',to=shapes)
        evidence['liveMintFeeWei']=live_mint_fee
        creator_before=I.call('pendingFees()(uint256)',to=shapes)
        workers.append(primary);primary.start();I.warp_to(60)
        def confirmed(worker,minimum_open,minimum_mined):
            if I.call('openListingCount()(uint256)',to=I.MANAGER)<minimum_open:return False
            stored=worker.stored()
            return bool(stored and stored['pending'] is None and stored['stats']['mined']>=minimum_mined)
        I.wait_for('factory-only image confirms three launch packs',lambda:confirmed(primary,3,1),seconds=420)
        before=primary.stored();assert before and before['pending'] is None
        evidence['steps'].append(dict(step='factory-only production entrypoint',health=primary.health(),stored=before,account=account()))
        primary.stop();workers.remove(primary)
        I.DropFirstSend.dropped.clear();proxy=socketserver.ThreadingTCPServer(('127.0.0.1',a.port+1),I.DropFirstSend)
        threading.Thread(target=proxy.serve_forever,daemon=True).start()
        replacement=I.Keeper(work.name+'-replacement',actors['primary'],volume,a.image,rpc=f'http://127.0.0.1:{a.port+1}',factory_only=True)
        workers.append(replacement);replacement.start();send(actors['owner'],I.MANAGER,value=5*10**17)
        I.wait_for('replacement confirms real lost response',lambda:bool(I.DropFirstSend.dropped) and confirmed(replacement,5,before['stats']['mined']+1),seconds=420)
        after=replacement.stored();primary_full=json.loads(I.sh('docker','run','--rm','--mount',f'type=volume,source={volume},target=/data','--entrypoint','python3',a.image,'-c',"import json;print(open('/data/keeper-state.json').read())"))
        evidence['primaryTxState']=primary_full
        creator_paid=I.call('pendingFees()(uint256)',to=shapes)-creator_before
        primary_topic='0x'+keccak(text='PrimaryMinted(uint256,uint256,uint256,uint256)').hex()
        minted=[0,0,0,0]
        from eth_abi import decode
        for counted in primary_full['counted']:
            if counted.get('reorged'):continue
            receipt=I.rpc('eth_getTransactionReceipt',counted['hash'])
            assert receipt and int(receipt['status'],16)==1
            for log in receipt['logs']:
                if log['address'].lower()==I.MANAGER.lower() and log['topics'] and log['topics'][0]==primary_topic:
                    amounts=decode(['uint256']*4,bytes.fromhex(log['data'][2:]))
                    minted=[a+b for a,b in zip(minted,amounts)]
        assert minted[0]>=5 and minted[1]==3*minted[0] and minted[2]==3*10**16*minted[0]
        assert creator_paid==minted[3]==minted[1]*live_mint_fee,'every receipt-proven primary Shape pays the actual fee'
        evidence['primaryMintEvents']=dict(zip(('packs','shapes','principalWei','mintFeesWei'),minted))
        evidence['creatorPrimaryFeesAccruedWei']=creator_paid
        dropped=I.rpc('eth_getTransactionReceipt',I.DropFirstSend.dropped[0])
        assert dropped and int(dropped['status'],16)==1 and after['stats']['mined']>before['stats']['mined'] and after['head']>=before['head']
        evidence['steps'].append(dict(step='persistent replacement and lost response',stored=after,droppedHash=I.DropFirstSend.dropped[0],droppedReceipt=dropped,account=account()))
        replacement.stop();workers.remove(replacement)
        zero=params|{'routineCapWei':0,'routineRatePerDayWei':0,'essentialCapWei':0,'essentialRatePerDayWei':0}
        send(actors['owner'],I.MANAGER,f'setParams({PARAMS_T})',tuple_arg(zero))
        # Genuine external request: no fabricated fulfillment or protocol state.
        fee=I.num(I.rpc('eth_getBlockByNumber','pending',False)['baseFeePerGas']);fees=['--gas-price',str(2*fee+50_000_000),'--priority-gas-price','50000000']
        price=I.num(I.cast('call',I.FWA,'quoteAcquisitionPrice()(uint256,uint256,uint256)','--block','pending',*fees).splitlines()[2])
        # This is an isolated calibration purchaser, separate from owner strategy funding.
        send(actors['purchaser'],I.FWA,'acquire(address,uint256,uint256,uint256,uint256)',actors['purchaser'],1,0,0,10000,value=price,fees=fees)
        assert I.call('unsettledAcquisitionCount()(uint256)',to=I.FWA)>0
        assert I.call('processAcquisitions(uint256)(uint256)',16,to=I.FWA)==0
        owner_exit()
        pending_before=account();assert pending_before['openListingCount']>0,'pending request did not exercise a blocked exit'
        current=I.call('nextSequenceToProcess()(uint64)',to=I.FWA);request=I.call('requestIdAtSequence(uint64)(uint256)',current,to=I.FWA)
        metadata=I.cast('call',I.FWA,'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)',request).splitlines();deadline=I.num(metadata[1])
        needed=max(0,deadline+1-I.num(I.cast('block-number')));assert needed<=7201
        while needed:
            count=min(32,needed);I.rpc('anvil_mine',hex(count));needed-=count
        timestamp=I.num(I.cast('block','latest','--field','timestamp'));I.rpc('evm_setNextBlockTimestamp',str(timestamp+13*3600));I.rpc('evm_mine')
        assert I.call('processAcquisitions(uint256)(uint256)',16,to=I.FWA)>0
        for _ in range(8):
            owner_exit();state=account()
            if all(state[k]==0 for k in ('openListingCount','idlePackCount','recoveryPackCount','pendingReceipts','cashWei','feeCreditWei')):break
        else:raise RuntimeError('manager exit did not complete in eight bounded CLI passes')
        final=account();state=json.loads(owner_state.read_text());assert state['signed_upper_wei']<=10**16
        for counted in primary_full['counted']+state['counted']:
            if counted.get('reorged'):continue
            receipt=I.rpc('eth_getTransactionReceipt',counted['hash']);transaction=I.rpc('eth_getTransactionByHash',counted['hash'])
            assert receipt and int(receipt['status'],16)==1
            evidence['transactions'].append(dict(operation=counted.get('function',counted['label']),sender=transaction['from'],to=transaction['to'],
                valueWei=I.num(transaction['value']),transaction=transaction,receipt=receipt))
        assert state['stats']['paid_wei']==0,'owner-paid exit earned keeper compensation'
        assert final['owner'].lower()==actors['owner'].lower()
        owner_end=I.num(I.cast('balance',actors['owner']))
        withdrawn_topic='0x'+keccak(text='Withdrawn(address,uint256)').hex()
        withdrawn=sum(int(log['data'],16) for entry in evidence['transactions'] for log in entry['receipt']['logs'] if log['address'].lower()==I.MANAGER.lower() and log['topics'] and log['topics'][0]==withdrawn_topic)
        keeper_pay=primary_full['stats']['paid_wei']
        assert initial_cash+5*10**17-creator_paid-keeper_pay-withdrawn==0,'manager physical cash ledger does not close'
        owner_gas=sum(int(entry['receipt']['gasUsed'],16)*int(entry['receipt']['effectiveGasPrice'],16) for entry in evidence['transactions'] if entry['sender'].lower()==actors['owner'].lower())
        assert owner_end-owner_start==withdrawn-15*10**17-owner_gas,'owner wallet ledger does not close'
        evidence.update(result='PASS',final=final,ownerLedger=dict(startWei=owner_start,endWei=owner_end,initialManagerFundingWei=10**18,additionalManagerFundingWei=5*10**17,
            walletNetWei=owner_end-owner_start,withdrawnWei=withdrawn,ownerGasCostWei=owner_gas,keeperCompensationWei=keeper_pay,creatorPrimaryFeesAccruedWei=creator_paid,exitSignedUpperWei=state['signed_upper_wei'],exitGasCostWei=state['stats']['spent_wei'],exitKeeperPayWei=state['stats']['paid_wei']),ownerTxState=state)
        assert source=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    finally:
        for worker in workers:
            try:evidence.setdefault('workerLogTails',{})[worker.name]=worker.logs();worker.stop()
            except Exception as error:evidence.setdefault('cleanupErrors',[]).append(str(error))
        if proxy:proxy.shutdown();proxy.server_close()
        node.terminate();node.wait(30)
        evidence['retainedWorkDirectory']=str(work)
        print(I.scrub(json.dumps(evidence,indent=1,default=str)))


if __name__=='__main__':main()
