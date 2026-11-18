"""Replay the keeper decision for the distribution-only state established by AuditDistribution.t.sol."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "keeper"))
import policy
s = policy.State(now=0, gas_price=200_000_000, base_fee=150_000_000,
    gas_ceiling=500_000_000, max_tip=50_000_000, markup_bps=0, share_bps=2500,
    k=0, backing=0, min_edge_bps=100, mint_fee=10**15, settlement_window=3600,
    blackout=True, queue_drained=True, checkpoint_done_this_interval=False,
    pending_deposits=0, locked_shares=0, distribution_bps=5000, free=10**18,
    idle_eth=10**18, routine_budget=3*10**16, essential_budget=10**16)
steps = policy.plan(s)
print("steps:", steps)
assert not any(step[0] == "checkpoint" for step in steps)
