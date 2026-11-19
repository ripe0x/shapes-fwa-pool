import ast, collections, importlib.util, json, pathlib, sys, textwrap
ROOT=pathlib.Path('/Users/dd/.codex/worktrees/da17/shapes-fwa-pool');sys.path.insert(0,str(ROOT/'keeper'))
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);x=importlib.util.module_from_spec(s);s.loader.exec_module(x);return x
m=load('batch',ROOT/'keeper/efficient_journal_rehearsal.py');r=load('recovery','/private/tmp/efficient-journal-recovery-review.py')
assert m.digest('/private/tmp/efficient-journal-recovery-review.py')=='e9186a9fa591260d6d00be1573c0f1287d64c4c73b9c5660c212760801ae175b'
H=r.PLAN_SHA256;assert m.digest(m.PLAN)==H
w=pathlib.Path('/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-journal-baseline-eqm_12s8');d=json.loads((w/'results.json').read_text());assert d['status']=='failed' and d['failure']=='ordinary keeper chose sync for no-gain zero-pay tail';assert d['broadcasts']==229 and len(d['actions'])==226
rows=[a for a in d['actions'] if a.get('tail_mode')=='holder'];assert collections.Counter(a['records'] for a in rows)=={128:4,127:4,65:4,64:4,63:4,33:4}
b=m.LocalBatch(json.loads(m.PLAN.read_text()),w);b.state=d;b.pid=d['pid'];b.vault=d['vault'];b.greedy_policy=d['test_policy_greedy'];b.actions=d['actions'];b.broadcasts=d['broadcasts'];b.external_value=d['external_value_wei'];b.guard()
initial=m.num(d['before_foreign_requests']['acquisitionCursor']);assert b.value('acquisitionCursor()(uint64)')==initial;assert b.value('nextSequenceToProcess()(uint64)',to=b.plan['values']['fwa'])==initial+32
assert b.value('unsettledAcquisitionCount()(uint256)',to=b.plan['values']['fwa'])==0
assert b.value('lockedShares()(uint256)')==0 and b.value('pendingDepositTotal()(uint256)')==0
assert b.params()[2]==5000 and b.params()[3]==0
inc=b.inclusion
def pinned():
 parent=b.rpc('eth_getBlockByNumber','latest',False);b.rpc('evm_setNextBlockTimestamp',hex(m.num(parent['timestamp'])+1));return inc()
b.inclusion=pinned
r.install_zero_offer_decline_observation(b,m);r.install_future_snapshot_id_log(b)
sm=r.expected_original_snapshot_map();witness=b.witness();b.state.pop('failure',None);b.state.update(status='resuming',global_phase='baseline_running',repair3=dict(reason='Dry CLI prints candidates before profitability; observe real zero-offer preflight decline, never fake absence',helper_sha256=m.digest('/private/tmp/efficient-journal-recovery-review.py'),snapshot_derivation=sm,all_previous_cumulative_counters_preserved=True));b.save()
source=(ROOT/'keeper/efficient_journal_rehearsal.py').read_text();tree=ast.parse(source);cl=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LocalBatch');run=next(n for n in cl.body if isinstance(n,ast.FunctionDef) and n.name=='run');lines=source.splitlines();start=next(i for i in range(run.lineno-1,run.end_lineno) if lines[i].strip()=="if self.profile['full_holder']:");tail='\n'.join(lines[start:run.end_lineno]);ns={};exec('def finish_holder_and_postflight(self,base,entry):\n'+textwrap.indent(textwrap.dedent(tail),'    ')+'\n',m.__dict__,ns)
print('Resume32 no-gain observation and remaining approved jobs;229 cumulative transactions retained',flush=True)
try:
 origin=b.distribution_cases(sm['predicted_first_no_gain32_origin'],32,witness)
 b.queue_half();holder=b.snapshot();b.matrix(holder,32,witness,'holder',(200000000,500000000))
 for count in (31,17,16,15,7,3,2,1):
  origin=b.restore(sm['natural_prefixes'][count])
  if count==1:origin=b.distribution_cases(origin,count,witness)
  b.queue_half();holder=b.snapshot();b.matrix(holder,count,witness,'holder',(200000000,500000000))
 ns['finish_holder_and_postflight'](b,sm['base_before_foreign'],sm['entry'])
except BaseException as exc:
 b.state.update(status='failed',global_phase='baseline_failed',failure=str(exc),node_preserved=True);b.save();raise
