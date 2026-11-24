#!/usr/bin/env python3
"""Bounded direct MAIN protocol admission/unselected-exit proof on the owned warm fork."""
import concurrent.futures
import hashlib
import json
import os
import sys
import time
import urllib.request
from pathlib import Path
from eth_account import Account
from eth_abi import encode,decode
from eth_utils import keccak

ROOT=Path(__file__).resolve().parent.parent
RPC='http://127.0.0.1:18661'
FWA='0x958C41181182e76F221331b2755b77D9e1426A98'
SHAPES='0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0'
PACKS='0xf21514B090Da7dF4390803497d6ae673801E5cA7'
FACE=BACKING=30_000_000_000_000_000
OUT=ROOT/'docs/receipts/manager-standard-backing-fork.json'


def rpc(method,*params):
    req=urllib.request.Request(RPC,data=json.dumps(dict(jsonrpc='2.0',id=1,method=method,params=params)).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as f:response=json.load(f)
    if 'error' in response:raise RuntimeError(method+': '+json.dumps(response['error']))
    return response['result']


def calldata(signature,types=(),args=()):
    return '0x'+(keccak(text=signature)[:4]+encode(types,args)).hex()


def call(target,signature,returns,types=(),args=()):
    return decode(returns,bytes.fromhex(rpc('eth_call',dict(to=target,data=calldata(signature,types,args)),'latest')[2:]))


def boundary():
    assert RPC=='http://127.0.0.1:18661'
    assert int(rpc('eth_chainId'),16)==31337
    assert rpc('web3_clientVersion').lower().startswith('anvil/')
    info=rpc('anvil_nodeInfo')
    assert info['forkConfig']['forkUrl']=='https://mainnet.gateway.tenderly.co'
    assert int(info['forkConfig']['forkBlockNumber'])==26486686
    return info


def verified(item):
    name,address,source=item
    url=f'https://sourcify.dev/server/v2/contract/1/{address}?fields=sources,runtimeBytecode'
    with urllib.request.urlopen(url,timeout=40) as f:record=json.load(f)
    assert record['runtimeMatch']=='match'
    code=rpc('eth_getCode',address,'latest')
    assert code==record['runtimeBytecode']['onchainBytecode'],name+' runtime differs from verified source'
    return name,dict(address=address,source=source,url=url,runtimeSha256=hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(),
        sourceSha256=hashlib.sha256(record['sources'][source]['content'].encode()).hexdigest(),runtimeMatch=True)


def execute(report,gas_price):
    # The signing key exists only in this process; neither signing objects nor raw signatures are persisted.
    actor=Account.create();address=actor.address
    assert rpc('eth_getCode',address,'latest')=='0x'
    assert int(rpc('eth_getBalance',address,'latest'),16)==0
    assert int(rpc('eth_getTransactionCount',address,'pending'),16)==0
    rpc('anvil_setBalance',address,hex(10**17))
    row=dict(actor=address,totalGasPriceWei=gas_price,baseFeeWei=gas_price-50_000_000,priorityFeeWei=50_000_000,
        initialOwnerCashWei=10**17,transactions=[],status='RUNNING')
    report['cases'].append(row)
    save=lambda:OUT.write_text(json.dumps(report,indent=1)+'\n')
    save()
    balance=lambda:int(rpc('eth_getBalance',address,'latest'),16)
    fees_before=call(SHAPES,'pendingFees()',['uint256'])[0]
    mint_fee=call(SHAPES,'mintFee()',['uint256'])[0]
    supply_before=call(SHAPES,'totalSupply()',['uint256'])[0]
    row['liveMintFeeWei']=mint_fee
    row['creatorFeesBeforeWei']=fees_before
    def send(operation,target,signature,types=(),args=(),value=0):
        boundary()
        assert int(rpc('eth_getCode',target,'latest')!='0x')
        rpc('anvil_setNextBlockBaseFeePerGas',hex(row['baseFeeWei']))
        transaction=dict(from_=address,to=target,data=calldata(signature,types,args),value=value)
        transaction['from']=transaction.pop('from_')
        preview=transaction|dict(maxFeePerGas=hex(gas_price),maxPriorityFeePerGas=hex(row['priorityFeeWei']))
        # Authenticate the exact call/value at the next block's recorded fee environment.
        rpc('eth_call',preview,'pending')
        estimate=int(rpc('eth_estimateGas',preview),16)
        limit=(estimate*125+99)//100
        assert limit<16_777_216 and value+limit*gas_price<10**17
        nonce=int(rpc('eth_getTransactionCount',address,'pending'),16)
        signed=actor.sign_transaction(dict(chainId=31337,nonce=nonce,to=target,data=transaction['data'],value=value,
            gas=limit,maxFeePerGas=gas_price,maxPriorityFeePerGas=row['priorityFeeWei']))
        before=balance()
        tx_hash=rpc('eth_sendRawTransaction','0x'+bytes(signed.raw_transaction).hex())
        receipt=None
        for _ in range(120):
            receipt=rpc('eth_getTransactionReceipt',tx_hash)
            if receipt:break
            time.sleep(.25)
        assert receipt is not None,'local receipt missing'
        tx=rpc('eth_getTransactionByHash',tx_hash)
        block=rpc('eth_getBlockByHash',receipt['blockHash'],False)
        gas=int(receipt['gasUsed'],16);price=int(receipt['effectiveGasPrice'],16)
        record=dict(operation=operation,decodedArguments=list(args),valueWei=value,ownerCashBeforeWei=before,
            ownerCashAfterWei=balance(),gasUsed=gas,effectiveGasPriceWei=price,walletGasWei=gas*price,
            executedBlockBaseFeeWei=int(block['baseFeePerGas'],16),transaction={k:tx[k] for k in ('hash','from','to','nonce','value','input','gas','type','chainId','maxFeePerGas','maxPriorityFeePerGas')},receipt=receipt)
        row['transactions'].append(record);save()
        assert int(receipt['status'],16)==1,operation+' reverted'
        assert price==gas_price and record['executedBlockBaseFeeWei']==row['baseFeeWei']
        assert tx['from'].lower()==address.lower() and tx['to'].lower()==target.lower() and int(tx['value'],16)==value
        return record

    try:
        assert call(PACKS,'shapes()',['address'])[0].lower()==SHAPES.lower()
        assert call(FWA,'canDeposit(address)',['bool'],['address'],[PACKS])[0]
        assert call(FWA,'unsettledAcquisitionCount()',['uint256'])[0]==0,'existing live queue prevents isolated admission/exit proof'
        created=send('create three directly paid Shapes',PACKS,'createPack(uint256[],uint32[])',['uint256[]','uint32[]'],[[],[3,0,0,0,0,0,0,0,0]],FACE+3*mint_fee)
        transfer='0x'+keccak(text='Transfer(address,address,uint256)').hex()
        pack_logs=[log for log in created['receipt']['logs'] if log['address'].lower()==PACKS.lower() and log['topics'][0]==transfer and int(log['topics'][1],16)==0]
        assert len(pack_logs)==1
        pack_id=int(pack_logs[0]['topics'][3],16);row['packId']=pack_id
        assert call(PACKS,'ownerOf(uint256)',['address'],['uint256'],[pack_id])[0].lower()==address.lower()
        assert call(PACKS,'valueOf(uint256)',['uint256'],['uint256'],[pack_id])[0]==FACE
        contents=call(PACKS,'contentsOf(uint256)',['uint256[]'],['uint256'],[pack_id])[0]
        assert len(contents)==3
        assert [call(SHAPES,'backingOf(uint256)',['uint256'],['uint256'],[i])[0] for i in contents]==[10**16]*3
        minted='0x'+keccak(text='ShapeMinted(uint256,address,uint256,bytes32,uint256)').hex()
        paid='0x'+keccak(text='MintFeeAccrued(uint256)').hex()
        mint_logs=[log for log in created['receipt']['logs'] if log['address'].lower()==SHAPES.lower() and log['topics'][0]==minted]
        paid_logs=[log for log in created['receipt']['logs'] if log['address'].lower()==SHAPES.lower() and log['topics'][0]==paid]
        assert len(mint_logs)==3 and all(decode(['uint256','bytes32','uint256'],bytes.fromhex(log['data'][2:]))[0]==10**16 for log in mint_logs)
        assert sum(decode(['uint256'],bytes.fromhex(log['data'][2:]))[0] for log in paid_logs)==3*mint_fee
        assert call(SHAPES,'totalSupply()',['uint256'])[0]==supply_before+3
        assert call(SHAPES,'pendingFees()',['uint256'])[0]-fees_before==3*mint_fee
        row.update(primaryMintEvents=3,mintFeeAccrualEvents=len(paid_logs),shapeIds=list(contents),paidPrimaryMintFeesWei=3*mint_fee)
        send('approve MAIN FWA',PACKS,'approve(address,uint256)',['address','uint256'],[FWA,pack_id])
        listed=send('admit 0.03 backing on 0.03 face',FWA,'listNFT(address,uint256)',['address','uint256'],[PACKS,pack_id],BACKING)
        listed_topic='0x'+keccak(text='NFTListed(uint256,uint256,address,address,uint256,uint256,uint256)').hex()
        logs=[log for log in listed['receipt']['logs'] if log['address'].lower()==FWA.lower() and log['topics'][0]==listed_topic]
        assert len(logs)==1
        listing_id=int(logs[0]['topics'][1],16);row['listingId']=listing_id
        listing=call(FWA,'listings(uint256)',['address','address','address','uint256','uint256','uint256','uint256','uint256','uint256','uint64','uint8'],['uint256'],[listing_id])
        assert listing[0].lower()==PACKS.lower() and listing[1].lower()==address.lower() and listing[3]==pack_id and listing[5]==BACKING and listing[-1]==1
        assert call(PACKS,'ownerOf(uint256)',['address'],['uint256'],[pack_id])[0].lower()==FWA.lower()
        row['admittedListing']=list(listing)
        assert call(FWA,'topListingId()',['uint256'])[0]!=listing_id,'unexpected crown requires a separately scoped delayed exit'
        withdrew=send('withdraw unselected backing and pack',FWA,'withdrawListing(uint256)',['uint256'],[listing_id])
        assert withdrew['ownerCashAfterWei']-withdrew['ownerCashBeforeWei']+withdrew['walletGasWei']==BACKING
        assert call(PACKS,'ownerOf(uint256)',['address'],['uint256'],[pack_id])[0].lower()==address.lower()
        redeemed=send('redeem pack face to original owner',PACKS,'redeem(uint256)',['uint256'],[pack_id])
        assert redeemed['ownerCashAfterWei']-redeemed['ownerCashBeforeWei']+redeemed['walletGasWei']==FACE
        assert call(SHAPES,'totalSupply()',['uint256'])[0]==supply_before
        assert call(SHAPES,'pendingFees()',['uint256'])[0]-fees_before==3*mint_fee
        assert call(FWA,'feeCredit(address)',['uint256'],['address'],[address])[0]==0
        gas=sum(tx['walletGasWei'] for tx in row['transactions'])
        final=balance();gap=10**17-final-gas-3*mint_fee
        assert gap==0
        row.update(status='PASS',finalOwnerCashWei=final,totalWalletGasWei=gas,creatorGrossFeeAccrualWei=3*mint_fee,
            returnedPackFaceWei=FACE,returnedListingBackingWei=BACKING,ownerNetWei=final-10**17,ledgerGapWei=gap)
        save()
    except Exception as exc:
        row.update(status='FAIL',error=str(exc));save();raise


def main():
    if os.environ.get('CANDIDATE_RUN')!='1':raise SystemExit('CANDIDATE_RUN=1 required for the authorized local rehearsal')
    assert not OUT.exists(),'preserve existing evidence; do not silently rerun the batch'
    before=boundary()
    source={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
    dependencies=dict(concurrent.futures.ThreadPoolExecutor(3).map(verified,[('FWA',FWA,'src/FWAV2/FWAV2.sol'),('Shapes',SHAPES,'src/Shapes.sol'),('ShapePacks',PACKS,'src/ShapePacks.sol')]))
    report=dict(status='RUNNING',command=[sys.executable,*sys.argv],rpc=RPC,chainId=31337,fork=before['forkConfig'],
        startBlock=int(rpc('eth_blockNumber'),16),sourceSha256=source,dependencies=dependencies,cases=[],
        scope='Direct MAIN protocol admission at B=0.03 ETH for P=0.03 ETH, followed by unselected same-owner withdrawal and redemption.',
        limitations=['No selected bid/keep, authentic VRF acquisition, manager strategy admission or monthly return is established.',
            'Creator amounts are gross primary-fee accrual, not withdrawn wallet cash or net profit.',
            'Fresh local wallets are funded as test setup; signing keys remain ephemeral RAM only.'])
    try:
        for price in (200_000_000,500_000_000):execute(report,price)
        assert source=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'src').rglob('*.sol'))}
        report.update(status='PASS',endBlock=int(rpc('eth_blockNumber'),16))
    finally:OUT.write_text(json.dumps(report,indent=1)+'\n')
    print(json.dumps(dict(status=report['status'],cases=[{k:r[k] for k in ('totalGasPriceWei','packId','listingId','totalWalletGasWei','creatorGrossFeeAccrualWei','ownerNetWei','ledgerGapWei')} for r in report['cases']]),indent=1))


if __name__=='__main__':main()
