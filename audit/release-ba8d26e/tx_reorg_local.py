"""Local real-vault receipt reorg check following tx_lost_response_local.py."""
import json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'keeper'))
import tx
RPC='http://127.0.0.1:8547'
KEEPER='0x6B401c3364dFb17fe7D54237fC04aba3f7739dd0'
STATE=ROOT/'audit/release-ba8d26e/tx_lost_state.json'
tm=tx.TxManager(RPC,str(STATE),KEEPER,['--unlocked','--from',KEEPER],confirmations=1)
assert tm.state['stats']['mined']==1
original=tm.state['counted'][0]
tm.rpc_call('anvil_reorg',1,[])
tm.check_reorgs(tm.head())
assert tm.state['stats']['mined']==0 and tm.state['stats']['reorged']==1
assert tm.state['stats']['spent_wei']==0 and tm.state['stats']['paid_wei']==0
assert tm.state['counted'][0]['reorged'] is True
assert tm._receipt(original['hash']) is None
print(json.dumps({'original_hash':original['hash'],'stats':tm.state['stats'],
                  'last_error':tm.state['errors'][-1]},indent=2))
tm.save()
tm._lockf.close()
