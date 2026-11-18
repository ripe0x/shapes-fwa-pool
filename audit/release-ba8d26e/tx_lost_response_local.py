"""Local-fork real-vault lost-response/restart check; no counterparty is replaced."""
import json, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'keeper'))
import tx
RPC='http://127.0.0.1:8547'
VAULT='0x321d151f896c205ac5c747c2cff4e9a0e185a27c'
KEEPER='0x6B401c3364dFb17fe7D54237fC04aba3f7739dd0'
STATE=ROOT/'audit/release-ba8d26e/tx_lost_state.json'
if STATE.exists(): STATE.unlink()
auth=['--unlocked','--from',KEEPER]
tm=tx.TxManager(RPC,str(STATE),KEEPER,auth,confirmations=1)
args=['checkpoint(uint256)','0']
est,why,_=tm.preflight(VAULT,args)
assert est is not None,why
base=int(tm.rpc_call('eth_getBlockByNumber','latest',False)['baseFeePerGas'],16)
prior=tm.nonce('latest')
real=tm._broadcast
def drop_response(p):
    real(p) # Actual signed local transaction is mined; only the RPC response is dropped.
    raise subprocess.CalledProcessError(1,'cast send',output='simulated lost response')
tm._broadcast=drop_response
tm.submit('checkpoint',VAULT,args,est,base,50_000_000,0)
assert tm.state['pending'] and not tm.state['pending']['hashes']
tm._lockf.close() # operator process exits; restart from saved state
restarted=tx.TxManager(RPC,str(STATE),KEEPER,auth,confirmations=1)
assert restarted.nonce('latest')==prior+1
assert restarted.resolve(lambda *a: None) is False
assert restarted.state['pending'] is None
assert len(restarted.state['counted'])==1
entry=restarted.state['counted'][0]
assert entry['status']==1 and entry['to'].lower()==VAULT.lower()
assert restarted.nonce('latest')==prior+1
print(json.dumps({'prior_nonce':prior,'final_nonce':restarted.nonce('latest'),
                  'receipt':entry,'stats':restarted.state['stats']},indent=2))
restarted._lockf.close()
