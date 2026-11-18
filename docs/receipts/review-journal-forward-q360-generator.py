import json,sys
from pathlib import Path
root=Path('/Users/dd/.codex/worktrees/da17/shapes-fwa-pool')
sys.path.insert(0,str(root/'sim'))
import forward as f
f.DB=Path('/Users/dd/CascadeProjects/shapes-fwa-pool/sim/data/fwa.sqlite')
f.POOL=f.pool_snapshot();f.STAGING=f.staging_delays(30)
db=f.sqlite3.connect(f'file:{f.DB}?mode=ro',uri=True)
end,block=db.execute('SELECT max(ts),max(block) FROM logs').fetchone()
statuses=[int(json.loads(a)['status']) for a, in db.execute("SELECT args FROM logs WHERE event='AcquisitionProcessed' AND ts>=?",(end-30*f.DAY,))]
success=sum(s==2 for s in statuses);f.REFUNDS_PER_SELECTION=(len(statuses)-success)/success
if sys.argv[1]=='self-check':
 results=f.self_check()
 print(json.dumps(dict(block=block,end_timestamp=end,pool_listings=len(f.POOL),completed30d=len(statuses),successful30d=success,context='Model scenarios, no return gate claim',results=results),indent=2))
 print(f'PASS: {len(results)} focused forward model scenarios')
else:
 rows=[]
 for config,n in [('canary.example',27),('mainnet',100)]:
  values=json.loads((root/'deploy'/f'{config}.json').read_text())
  for total in [.2,.5]:
   for volume in [success/30,71]:
    row=f.run(f.Scenario(volume=f.const(volume),gwei=total-.05),n,8,days=30,values=values)
    rows.append(dict(configuration=config,total_gwei=total,successful_volume_per_day=volume,target_positions=n,**row))
 print(json.dumps(dict(context='Q_CHECKPOINT360k, unchanged journal quotes; illustrative30day scenarios, single seed; no forecast or realized/billed return claim',block=block,timestamp=end,completed30d=len(statuses),successful30d=success,rows=rows),indent=2))
