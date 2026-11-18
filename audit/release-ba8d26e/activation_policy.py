"""Replay keeper activation choice for 100 real staged IDs in AuditActivationGas.t.sol."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'keeper'))
import policy
s=policy.State(now=0,gas_price=200_000_000,base_fee=150_000_000,gas_ceiling=500_000_000,
    max_tip=50_000_000,markup_bps=0,share_bps=2500,k=1_038_500_000_000_000_000,
    backing=36_300_000_000_000_000,min_edge_bps=100,mint_fee=10**15,
    settlement_window=3600,blackout=False,queue_drained=True,
    checkpoint_done_this_interval=False,
    listings=[policy.Listing(id=i,status=policy.STAGED) for i in range(1,101)],
    max_positions=150,open_positions=100,free=10**18,slowdown_volume=1)
steps=policy.plan(s)
for step in steps: print(step[0], 'ids', len(step[1]) if len(step)>1 and isinstance(step[1],list) else '', 'maxCount',step[2] if len(step)>2 else '')
assert any(step[0]=='activate' and len(step[1])==100 and step[2]==200 for step in steps)
