import hashlib, importlib.util, json, pathlib, sys, time
ROOT=pathlib.Path('/Users/dd/.codex/worktrees/da17/shapes-fwa-pool')
sys.path.insert(0,str(ROOT/'keeper'))
spec=importlib.util.spec_from_file_location('approved_batch',ROOT/'keeper/efficient_journal_rehearsal.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
PLAN_HASH='1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd'
assert m.digest(m.PLAN)==PLAN_HASH
plan=json.loads(m.PLAN.read_text());work=pathlib.Path('/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-journal-baseline-eqm_12s8')
state=json.loads((work/'results.json').read_text());assert state['status']=='failed' and state['failure']=='normal production deployment failed; preserve receipts before any retry'
assert state['broadcasts']==3 and state['external_value_wei']==10**16 and not state['actions']
b=m.LocalBatch(plan,work);b.pid=state['pid'];b.state=state;b.actions=state['actions'];b.guard()
actual={r:dict(balance=m.num(b.cast('balance',a)),nonce=m.num(b.cast('nonce',a)),code=b.cast('code',a)) for r,a in m.ACTORS.items()}
assert actual==state['entry_actors'],actual
assert b.rpc('eth_getBlockByNumber','latest',False)['hash']==state['entry_head']['hash']
assert b.rpc('anvil_getAutomine') is True and b.rpc('txpool_status')=={'pending':'0x0','queued':'0x0'}
assert state['funded']==m.FUNDING
b.broadcasts=0;b.external_value=0
b.state.update(status='resuming',global_phase='baseline_running',approval=dict(owner_answer='Approve this local batch',plan_sha256=PLAN_HASH),repair1=dict(reason='ABI-only deployment artifact; no transaction broadcast',preserved='failure1-no-deploy-bytecode.json',deployer_nonce=0,all_actor_balances_nonces_code_unchanged=True,head_unchanged=True,released_provisional_deployment_reservation_transactions=3,released_provisional_value_wei=10**16,initial_funding_not_repeated=True,compiler_work='/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-deploy-artifact-vthw_1ir'))
b.save()
def reuse_verified_owned_node():
    b.guard()
    assert {r:dict(balance=m.num(b.cast('balance',a)),nonce=m.num(b.cast('nonce',a)),code=b.cast('code',a)) for r,a in m.ACTORS.items()}==state['entry_actors']
b.start=reuse_verified_owned_node
print('Resuming verified owned node',b.pid,'same funded entry; no restart/reset/topup',flush=True)
try:b.run()
except BaseException as exc:
    b.state.update(status='failed',global_phase='baseline_failed',failure=str(exc),node_preserved=True);b.save();raise
