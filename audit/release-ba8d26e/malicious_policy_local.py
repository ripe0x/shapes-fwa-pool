"""Local Anvil fork: real PackVault plus real keeper against a gas-price-sensitive policy.
Run only on the already started local mainnet fork at 127.0.0.1:8547.
"""
import json, os, subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RPC='http://127.0.0.1:8547'
DEPLOYER='0xe0980b9f7F5fB4a98813552894f4E980836cDa7c'
HOLDER='0xDd4B0D7470953fb19b97fa130A15Af59537Bc523'
KEEPER='0x6B401c3364dFb17fe7D54237fC04aba3f7739dd0'
OWNER='0x0000000000000000000000000000000000000002'
STATE=ROOT/'audit/release-ba8d26e/malicious_keeper_state.json'

def run(*args, env=None, allow_fail=False):
 r=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True,text=True,env=env)
 if r.returncode and not allow_fail: raise RuntimeError(f'{args}: {r.returncode} {r.stdout[-500:]} {r.stderr[-500:]}')
 return r

def cast(*args): return run('cast',*args,'--rpc-url',RPC).stdout.strip()
def num(x): return int(x.split()[0],0)
def send(sender,to,sig,*args,value=None):
 a=['cast','send',to,sig,*map(str,args),'--from',sender,'--unlocked','--rpc-url',RPC,'--json']
 if value is not None: a+=['--value',str(value)]
 r=run(*a)
 receipt=json.loads(r.stdout)
 assert receipt['status']=='0x1',receipt
 return receipt

assert num(cast('chain-id'))==1
for actor in (DEPLOYER,HOLDER,KEEPER):
 assert cast('code',actor)=='0x'
# These are actors the existing rehearsal checked clean on the pinned mainnet fork.
run('forge','script','script/Deploy.s.sol','--rpc-url',RPC,'--broadcast','--unlocked','--sender',DEPLOYER,
    env={**os.environ,'DEPLOY_VALUES':'deploy/canary.example.json'})
run_data=json.loads((ROOT/'broadcast/Deploy.s.sol/1/run-latest.json').read_text())
vault=next(t['contractAddress'] for t in run_data['transactions'] if t.get('contractName')=='PackVault')
print('vault',vault,flush=True)
r=run('forge','create','--broadcast','--unlocked','--from',DEPLOYER,'--rpc-url',RPC,
    'test/audit/AuditMaliciousPolicy.t.sol:GasPriceSwitchPolicy')
policy=next(line.split(':',1)[1].strip() for line in r.stdout.splitlines() if line.startswith('Deployed to:'))
print('policy',policy,flush=True)
send(OWNER,vault,'setPolicy(address)',policy)
ck=num(cast('call',vault,'requestCharge()(uint256)'))
send(HOLDER,vault,'deposit()',value=10**18+ck)
now=num(cast('block','latest','--field','timestamp'))
nxt=now-now%43200+42360
if nxt<=now: nxt+=43200
cast('rpc','evm_setNextBlockTimestamp',str(nxt))
cast('rpc','evm_mine')
assert cast('call','0x958C41181182e76F221331b2755b77D9e1426A98','isPurchaseBlackout()(bool)')=='true'
if STATE.exists(): STATE.unlink()
r=run('python3','keeper/keeper.py',vault,'--send','--from',KEEPER,'--rpc',RPC,'--state',STATE,'--max-steps','1','--pending-timeout','20',allow_fail=True)
print('keeper exit',r.returncode,flush=True)
print(r.stdout,flush=True)
print(r.stderr,flush=True)
st=json.loads(STATE.read_text())
print('counted',st['counted'],flush=True)
assert st['counted'], 'keeper did not broadcast; check whether eth_call saw zero gas price'
e=st['counted'][-1]
assert e['expected_pay']>0 and e['pay']==0 and e['status']==0 and e['cost']>0,e
print('unaccepted gas loss wei',e['cost'],flush=True)
