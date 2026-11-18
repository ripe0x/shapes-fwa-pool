"""Local real-vault same-nonce replacement after a basefee spike."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'keeper'))
import tx
RPC='http://127.0.0.1:8547'
VAULT='0x321d151f896c205ac5c747c2cff4e9a0e185a27c'
KEEPER='0x6B401c3364dFb17fe7D54237fC04aba3f7739dd0'
STATE=ROOT/'audit/release-ba8d26e/tx_replace_state.json'
if STATE.exists(): STATE.unlink()
tm=tx.TxManager(RPC,str(STATE),KEEPER,['--unlocked','--from',KEEPER],confirmations=1,replace_after=2)
try:
    args=['checkpoint(uint256)','0']
    # The local reorg removed the receipt but left lastCheckpointInterval set while epoch
    # returned to zero (Anvil anomaly). Advance to the next real FWA blackout window.
    now=int(tm.rpc_call('eth_getBlockByNumber','latest',False)['timestamp'],16)
    target=now-now%43200+43200+42360
    tm.rpc_call('evm_setNextBlockTimestamp',target)
    tm.rpc_call('evm_mine')
    est,why,_=tm.preflight(VAULT,args)
    assert est is not None,why
    base=int(tm.rpc_call('eth_getBlockByNumber','latest',False)['baseFeePerGas'],16)
    nonce=tm.nonce('pending')
    tm.rpc_call('evm_setAutomine',False)
    tm.submit('checkpoint',VAULT,args,est,base,50_000_000,0)
    original=tm.state['pending']['hashes'][0]
    assert tm.state['pending']['nonce']==nonce
    tm.rpc_call('anvil_setNextBlockBaseFeePerGas',hex(base*20))
    tm.rpc_call('anvil_mine','0x2')
    assert tm._receipt(original) is None
    assert tm.resolve(lambda p,prio,max_fee: tm.preflight(p['to'],p['args'])[0]) is True
    p=tm.state['pending']
    assert p['replacements']==1 and len(p['hashes'])==2 and p['nonce']==nonce,p
    replacement=p['hashes'][-1]
    tm.rpc_call('anvil_mine','0x1')
    assert tm.resolve(lambda p,prio,max_fee: tm.preflight(p['to'],p['args'])[0]) is False
    entry=tm.state['counted'][-1]
    assert entry['hash']==replacement and entry['status']==1
    assert tm.nonce('latest')==nonce+1
    assert tm._receipt(original) is None
    print(json.dumps({'nonce':nonce,'original':original,'replacement':replacement,
                      'receipt':entry,'stats':tm.state['stats']},indent=2))
finally:
    tm.rpc_call('evm_setAutomine',True)
    tm._lockf.close()
