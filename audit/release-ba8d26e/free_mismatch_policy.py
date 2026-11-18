"""Keeper planner at the actual balances logged by AuditFreeMismatch.t.sol."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "keeper"))
import policy
s = policy.State(now=0, gas_price=200_000_000, base_fee=150_000_000,
    gas_ceiling=500_000_000, max_tip=50_000_000, markup_bps=0, share_bps=2500,
    k=1_038_500_000_000_000_000, backing=36_300_000_000_000_000,
    min_edge_bps=100, mint_fee=10**15, settlement_window=3600,
    blackout=True, queue_drained=True, checkpoint_done_this_interval=False,
    listings=[policy.Listing(id=1, status=policy.ACTIVE)], loose_shapes=7,
    free=874_648_320_659_858_602, owed_estimate=873_961_920_659_858_594,
    locked_shares=86_597_063_493_129_589, recent_volume=0, slowdown_volume=1,
    idle_eth=0, reserve=5_000_000_000_000_000,
    work_fee=20_000_000_000_000)
steps = policy.plan(s)
print('keeper steps:', steps)
print('keeper shortfall wei:', max(0, s.owed_estimate - s.free))
print('vault cash shortfall wei:', s.owed_estimate - 873_337_920_659_858_602)
assert any(step[0] == 'checkpoint' for step in steps)
assert not any(step[0] in ('liquidate', 'unlist') for step in steps)
