import ast,importlib.util,json,pathlib,sys,textwrap,time
ROOT=pathlib.Path('/Users/dd/.codex/worktrees/da17/shapes-fwa-pool');sys.path.insert(0,str(ROOT/'keeper'))
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
m=load('batch',ROOT/'keeper/efficient_journal_rehearsal.py');r=load('recovery','/private/tmp/efficient-journal-recovery-review.py');assert m.digest(m.PLAN)==r.PLAN_SHA256
w=pathlib.Path('/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-journal-baseline-eqm_12s8');d=json.loads((w/'results.json').read_text());assert d['status']=='failed' and d['broadcasts']==297 and len(d['actions'])==294
assert 'too_many_data_frames' in str(d['ordinary_dispatches'][-1])
b=m.LocalBatch(json.loads(m.PLAN.read_text()),w);b.state=d;b.pid=d['pid'];b.vault=d['vault'];b.greedy_policy=d['test_policy_greedy'];b.actions=d['actions'];b.broadcasts=d['broadcasts'];b.external_value=d['external_value_wei'];b.guard()
assert b.params()[3]==1000 and b.value('lockedShares()(uint256)')==0
begin=m.num(d['before_foreign_requests']['acquisitionCursor']);assert b.value('acquisitionCursor()(uint64)')==begin and b.value('nextSequenceToProcess()(uint64)',to=b.plan['values']['fwa'])==begin+1
inc=b.inclusion
def pinned():
 p=b.rpc('eth_getBlockByNumber','latest',False);b.rpc('evm_setNextBlockTimestamp',hex(m.num(p['timestamp'])+1));return inc()
b.inclusion=pinned;r.install_zero_offer_decline_observation(b,m);r.install_future_snapshot_id_log(b)
original_dispatch=b.ordinary_dispatch
def retry_transport(sig,args,absent=False):
 for attempt in range(3):
  counters=(b.broadcasts,b.external_value,len(b.actions));old=len(b.state.get('ordinary_dispatches',[]))
  try:return original_dispatch(sig,args,absent=absent)
  except RuntimeError:
   recent=b.state.get('ordinary_dispatches',[])[old:]
   if attempt==2 or 'too_many_data_frames' not in str(recent):raise
   assert counters==(b.broadcasts,b.external_value,len(b.actions))
   b.state.setdefault('transport_retries',[]).append(dict(case=len(b.actions),attempt=attempt+1,reason='actual public fork transport too_many_data_frames; retry same read-only CLI',counters_unchanged=True));b.save();time.sleep(2*(attempt+1))
b.ordinary_dispatch=retry_transport
source=(ROOT/'keeper/efficient_journal_rehearsal.py').read_text();tree=ast.parse(source);cl=next(x for x in tree.body if isinstance(x,ast.ClassDef) and x.name=='LocalBatch');fn=next(x for x in cl.body if isinstance(x,ast.FunctionDef) and x.name=='run');ls=source.splitlines();start=next(i for i in range(fn.lineno-1,fn.end_lineno) if ls[i].strip()=="if self.profile['full_holder']:");ns={};exec('def finish(self,base,entry):\n'+textwrap.indent(textwrap.dedent('\n'.join(ls[start:fn.end_lineno])),'    ')+'\n',m.__dict__,ns)
b.state.pop('failure',None);b.state.update(status='resuming',global_phase='baseline_running',repair4=dict(reason='Transient public fork HTTP2 transport failure before send; resume exact max-markup singleton branch',preserved='failure4-one-record-keeper-dispatch.json',remaining_branch_snapshot='0xe9',no_gain_origin='0xe0',cumulative_counters_preserved=True));b.save()
print('Resume two max-markup singleton distribution receipts, holder1 and full-holder receipts; cumulative297 retained',flush=True)
try:
 witness=b.witness();branch='0xe9'
 for price in (200000000,500000000):
  branch=b.restore(branch);b.warp(42360);b.fee(price);before=b.getters()
  row=b.send('keeper',b.vault,'sync(uint256[],uint256,uint256)',('[]',witness,0),label=f'distribution journal1/markup1000/price{price}',measure=True)
  after=b.getters();row.update(before=before,after=after,records=1,markup=1000,tail_mode='distribution')
  assert after['acquisitionCursor']-before['acquisitionCursor']==1
  assert not before['lockedShares'] and not before['pendingDepositTotal'] and row['keeper_paid_wei']>0
  assert before['budget'][1]==after['budget'][1]==0 and before['processingPool']==after['processingPool'];b.save()
 b.restore('0xe0');b.queue_half();holder=b.snapshot();b.matrix(holder,1,witness,'holder',(200000000,500000000))
 ns['finish'](b,'0x12','0x0')
except BaseException as exc:
 b.state.update(status='failed',global_phase='baseline_failed',failure=str(exc),node_preserved=True);b.save();raise
