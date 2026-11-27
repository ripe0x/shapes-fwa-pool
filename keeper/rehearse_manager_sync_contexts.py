#!/usr/bin/env python3
"""Pair paid sync and unpaid owner recovery from identical real FWA fork state."""
import argparse
import hashlib
import json
import time
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak, to_checksum_address

from config import GAS_FIELDS, PARAMS_T, params_values
from rehearse_manager_measured import data, rpc_at
from rehearse_manager_r2 import ROOT, FWA, PACKS, sources

# Current defaults: the retained main-run node is on 8545 and the fresh main packet records its
# post-setup snapshot. Overridable by args for a different run.
URL = 'http://127.0.0.1:8545'
BASE = ROOT / 'docs/receipts/manager-measured-50k-receipts-current.json'
OUT = ROOT / 'docs/receipts/manager-measured-sync-contexts-current.json'
METER = '0x' + keccak(text='KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)').hex()
PAID = '0x' + keccak(text='KeeperPaid(address,uint256)').hex()


def rpc(method, *params):
    return rpc_at(URL, method, params)


def call(target, signature, kinds=(), values=(), returns=('uint256',)):
    raw = rpc('eth_call', {'to':target, 'data':data(signature,kinds,values)}, 'latest')
    return decode(returns,bytes.fromhex(raw[2:]))[0]


def fingerprint(manager, pack):
    head=rpc('eth_getBlockByNumber','latest',False)
    state=dict(blockNumber=head['number'],blockHash=head['hash'],
        cash=rpc('eth_getBalance',manager,'latest'),
        config='0x'+call(manager,'configurationHash()',returns=('bytes32',)).hex(),
        openCount=call(manager,'openListingCount()'),idleCount=call(manager,'idlePackCount()'),
        recoveryCount=call(manager,'recoveryPackCount()'),pendingReceipts=call(manager,'pendingReceipts()'),
        feeCredit=call(FWA,'feeCredit(address)',('address',),(manager,)),
        nextSequence=call(FWA,'nextSequenceToProcess()'),
        unsettled=call(FWA,'unsettledAcquisitionCount()'),
        packOwner=call(PACKS,'ownerOf(uint256)',('uint256',),(pack,),('address',)))
    digest=hashlib.sha256(json.dumps(state,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    return digest,state


def prime(base):
    rpc('anvil_setNextBlockBaseFeePerGas',hex(base*8//7))
    rpc('evm_mine')
    from tx import next_base_fee
    head=rpc('eth_getBlockByNumber','latest',False)
    assert next_base_fee(head)==base


def send(sender,target,signature,kinds,values,branch,operation,base,price,paid=False,prestate=None):
    prime(base)
    payload={'from':sender,'to':target,'data':data(signature,kinds,values),
        'value':'0x0','maxFeePerGas':hex(2*base+50000000),'maxPriorityFeePerGas':hex(50000000)}
    simulated=None
    if paid:
        simulated=decode(['uint256'],bytes.fromhex(rpc('eth_call',payload,'pending')[2:]))[0]
        assert simulated>0
        values=list(values);values[-2]=simulated*8//10
        payload['data']=data(signature,kinds,values)
    estimate=int(rpc('eth_estimateGas',payload),16)
    gas_limit=(estimate*5+3)//4
    assert 0<gas_limit<=16777216
    h=rpc('eth_sendTransaction',payload|{'gas':hex(gas_limit)})
    for _ in range(120):
        receipt=rpc('eth_getTransactionReceipt',h)
        if receipt:break
        time.sleep(.5)
    assert receipt and int(receipt['status'],16)==1,(branch,operation,h)
    tx=rpc('eth_getTransactionByHash',h)
    block=rpc('eth_getBlockByHash',receipt['blockHash'],False)
    assert int(receipt['effectiveGasPrice'],16)==price and int(block['baseFeePerGas'],16)==base
    logs=[l for l in receipt['logs'] if l['address'].lower()==target.lower()]
    meters=[decode(['uint256','uint256','uint256','uint256','bool'],bytes.fromhex(l['data'][2:]))
        for l in logs if l['topics'][0].lower()==METER.lower()]
    compensation=sum(int(l['data'],16) for l in logs if l['topics'][0].lower()==PAID.lower())
    row=dict(branch=branch,operation=operation,workCount=1,targetAccount=target,
        gasEstimate=estimate,estimateKind='rpc-estimate',signedGasLimit=gas_limit,
        gasUsed=int(receipt['gasUsed'],16),effectiveGasPrice=price,blockBaseFeeWei=base,
        gasCostWei=int(receipt['gasUsed'],16)*price,compensationWei=compensation,
        transaction=tx,receipt=receipt)
    if prestate:row['prestateSha256']=prestate
    if paid:
        assert len(meters)==1 and compensation>=simulated*8//10
        row['measuredWork']=dict(zip(('measuredGas','gasAllowance','gasPrice','workUnits','essential'),meters[0]))
        row['simulatedCompensationWei']=simulated
        row['minimumPaymentWei']=simulated*8//10
        row['keeperNetWei']=compensation-row['gasCostWei']
    else:
        assert not meters and compensation==0
    return row


def main():
    global URL,BASE,OUT
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--starting-snapshot',default=None,help='Post-setup snapshot on the retained node; defaults to the base packet record')
    ap.add_argument('--port',type=int,default=8545,help='Retained main-run node port (anvil only runs on 8545)')
    ap.add_argument('--base',default=str(BASE),help='Fresh main measured packet the node was set up from')
    ap.add_argument('--output',default=str(OUT),help='Fresh output packet; existing packets are never overwritten')
    args=ap.parse_args()
    URL=f'http://127.0.0.1:{args.port}';BASE=Path(args.base).resolve();OUT=Path(args.output).resolve()
    assert not OUT.exists(),'preserve existing immutable receipt packet'
    base_packet=json.loads(BASE.read_text())
    if args.starting_snapshot is None:
        args.starting_snapshot=base_packet['postSetupSnapshot']
    assert base_packet['status']=='PASS' and base_packet['contractSourceSha256']==sources()
    assert rpc('eth_chainId')=='0x7a69' and rpc('anvil_nodeInfo')['hardFork']=='Osaka'
    manager=to_checksum_address(base_packet['manager'])
    owner=to_checksum_address(base_packet['owner'])
    keeper=to_checksum_address(base_packet['keeper'])
    meta=base_packet['checkpoint']['actualMetadata']
    listing=meta['listing']
    values=json.loads((ROOT/'deploy/manager.json').read_text())
    assert list(values['gasSchedule'])==GAS_FIELDS
    assert rpc('evm_revert',args.starting_snapshot),'authenticated setup snapshot missing; do not substitute state'
    assert rpc('eth_getBalance',manager,'latest')==hex(meta['managerCashWei'])
    assert call(manager,'owner()',returns=('address',)).lower()==owner.lower()
    assert tuple(call(manager,'getParams()',returns=(PARAMS_T,)))==tuple(params_values(values))
    for actor in (owner,keeper,to_checksum_address(meta['purchaser'])):
        rpc('anvil_impersonateAccount',actor)
        assert int(rpc('eth_getBalance',actor,'latest'),16)>10**16
    initial=rpc('evm_snapshot')
    packet=dict(status='RUNNING',chainId=31337,rpc=URL,executionHardfork='Osaka',
        contractSourceSha256=sources(),sourceReceipt=str(BASE.relative_to(ROOT)),
        sourceReceiptSha256=hashlib.sha256(BASE.read_bytes()).hexdigest(),
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),startingSnapshot=args.starting_snapshot,
        fullGasSchedule=values['gasSchedule'],manager=manager,owner=owner,keeper=keeper,
        listing=listing,transactions=[],contexts=[],
        limitations=['Restored branches are independent receipt samples, not one portfolio.',
            'Only exact verified sync contexts are supported; unmeasured work patterns are refused.',
            'All transactions are local chain 31337; public transactions zero.'])
    OUT.write_text(json.dumps(packet,indent=1)+'\n')
    try:
        for price,base in ((200000000,150000000),(500000000,450000000)):
            for variant in ('allocation-journal','terminal-journal','combined-journal'):
                assert rpc('evm_revert',initial)
                initial=rpc('evm_snapshot')
                branch=f'{variant}-{price}'
                prime(base)
                if variant=='terminal-journal':
                    row=send(owner,manager,'recover(uint256[],uint256)',('uint256[]','uint256'),([],0),
                        branch,'prepareRecover',base,price)
                    packet['transactions'].append(row)
                if variant!='allocation-journal':
                    row=send(to_checksum_address(meta['purchaser']),FWA,'acceptDepositorBid(uint256)',
                        ('uint256',),(listing,),branch,'prepareBid',base,price)
                    packet['transactions'].append(row)
                ids=[] if variant=='allocation-journal' else [listing]
                before,state=fingerprint(manager,meta['pack'])
                pair=rpc('evm_snapshot')
                expected=call(manager,'configurationHash()',returns=('bytes32',))
                paid=send(keeper,manager,'sync(uint256[],uint256,uint256,bytes32)',
                    ('uint256[]','uint256','uint256','bytes32'),(ids,0,0,expected),branch,'sync',base,price,True,before)
                packet['transactions'].append(paid)
                assert rpc('evm_revert',pair)
                after,restored=fingerprint(manager,meta['pack'])
                assert before==after and state==restored,'owner recovery must start from exact paid prestate'
                owner_row=send(owner,manager,'recover(uint256[],uint256)',('uint256[]','uint256'),(ids,0),
                    branch,'recover',base,price,False,before)
                m=paid['measuredWork']
                owner_row['verifiedContext']=dict(gasAllowance=m['gasAllowance'],workUnits=m['workUnits'],
                    pairedPaidHash=paid['receipt']['transactionHash'],prestateSha256=before)
                packet['transactions'].append(owner_row)
                packet['contexts'].append(dict(branch=branch,prestateSha256=before,
                    paidHash=paid['receipt']['transactionHash'],ownerHash=owner_row['receipt']['transactionHash'],
                    gasAllowance=m['gasAllowance'],workUnits=m['workUnits'],
                    paidGasUsed=paid['gasUsed'],ownerGasUsed=owner_row['gasUsed']))
                OUT.write_text(json.dumps(packet,indent=1)+'\n')
        # `initial` is a freshly re-taken post-setup snapshot that survives this run; the owner-exit
        # packet reverts to it next (reverting the base packet's snapshot consumed it here).
        packet['postSetupSnapshot']=initial
        packet['status']='PASS'
    except Exception as e:
        packet['status']='FAIL';packet['error']=str(e)
        raise
    finally:
        OUT.write_text(json.dumps(packet,indent=1)+'\n')
    print(json.dumps(dict(status=packet['status'],contexts=packet['contexts']),indent=1))


if __name__=='__main__':main()
