import ast, importlib.util, json, pathlib, sys, textwrap
ROOT=pathlib.Path('/Users/dd/.codex/worktrees/da17/shapes-fwa-pool');sys.path.insert(0,str(ROOT/'keeper'))
spec=importlib.util.spec_from_file_location('batch',ROOT/'keeper/efficient_journal_rehearsal.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
H='1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd';assert m.digest(m.PLAN)==H
w=pathlib.Path('/private/var/folders/ql/fxv4cbz95kz22crsmldp06sm0000gn/T/efficient-journal-baseline-eqm_12s8');d=json.loads((w/'results.json').read_text());assert d['status']=='failed' and d['broadcasts']==6 and len(d['actions'])==3
assert d['failure']=='ordinary keeper estimate differs from exact operator estimate'
b=m.LocalBatch(json.loads(m.PLAN.read_text()),w);b.state=d;b.pid=d['pid'];b.vault=d['vault'];b.greedy_policy=d['test_policy_greedy'];b.actions=d['actions'];b.broadcasts=d['broadcasts'];b.external_value=d['external_value_wei'];b.guard()
first=m.num(d['entry_head']['number']);head=m.num(b.cast('block-number'));txs=[]
for n in range(first+1,head+1):
 for tx in b.rpc('eth_getBlockByNumber',hex(n),True)['transactions']:
  assert tx['from'].lower() in {a.lower() for a in m.ACTORS.values()}
  rec=b.rpc('eth_getTransactionReceipt',tx['hash']);assert m.num(rec['status'])==1 and m.num(tx['gas'])<=m.MAX_GAS
  txs.append(dict(hash=tx['hash'],sender=tx['from'],nonce=m.num(tx['nonce']),value_wei=m.num(tx['value']),status=1))
assert len(txs)==b.broadcasts and sum(t['value_wei'] for t in txs)==b.external_value
assert all(b.cast('code',a)=='0x' for a in m.ACTORS.values())
assert sum(m.num(b.cast('nonce',a)) for a in m.ACTORS.values())==b.broadcasts
assert b.rpc('anvil_getAutomine') is True and b.rpc('txpool_status')=={'pending':'0x0','queued':'0x0'}
# Two entry snapshots, then stock fresh/origin and its two restored price branches.
probe=m.num(b.snapshot());assert probe in (6,7),('unexpected snapshot sequence',probe)
entry=hex(probe-6)
original_inclusion=b.inclusion
def pinned_inclusion():
 parent=b.rpc('eth_getBlockByNumber','latest',False)
 b.rpc('evm_setNextBlockTimestamp',hex(m.num(parent['timestamp'])+1))
 return original_inclusion()
b.inclusion=pinned_inclusion
b.state.pop('failure',None);b.state.update(status='resuming',global_phase='baseline_running',repair2=dict(reason='Pending timestamp drift changed real mint gas estimates across calls; pin next inclusion to parent+1 before fee preflights, preserving all estimate equality/receipt checks',diagnosis='estimate-equality-diagnosis.json',transactions_reconciled=txs,initial_funding_not_repeated=True,entry_snapshot=entry,observed_next_snapshot=probe));b.save()
source=(ROOT/'keeper/efficient_journal_rehearsal.py').read_text();tree=ast.parse(source);cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='LocalBatch');run=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='run');lines=source.splitlines();start=next(i for i in range(run.lineno-1,run.end_lineno) if "if self.profile['restock_inventory_paths']:self.stock_cases()" in lines[i]);tail='\n'.join(lines[start:run.end_lineno]);ns={};exec('def resume_remaining(self, entry):\n'+textwrap.indent(textwrap.dedent(tail),'    ')+'\n',m.__dict__,ns)
print('Resuming remaining approved actions on same node; six receipts reconciled; parent+1 pending timestamp',flush=True)
try:ns['resume_remaining'](b,entry)
except BaseException as exc:
 b.state.update(status='failed',global_phase='baseline_failed',failure=str(exc),node_preserved=True);b.save();raise
