#!/usr/bin/env python3
"""Gas classes (D45), reserve need (D46) and status codes. Pure policy: no chain.
Run: python3 keeper/test_policy.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from policy import ACTIVE, ALLOCATED, SETTLED, STAGED, Listing, State, plan, reserve_need, status  # noqa: E402

G = 10**9
E = 10**18


def state(**kw):
    base = dict(now=10**6, gas_price=int(0.2 * G), base_fee=int(0.15 * G), gas_ceiling=int(0.5 * G),
                max_tip=int(0.05 * G), markup_bps=1_000, share_bps=2_500, k=int(1.0385 * E), backing=int(0.0363 * E),
                min_edge_bps=100, mint_fee=10**15, settlement_window=3600, blackout=True, queue_drained=True,
                checkpoint_done_this_interval=False, max_positions=30, reserve=5 * 10**15)
    base.update(kw)
    return State(**base)


def fns(steps):
    return [s[0] for s in steps]


def main():
    act = [Listing(i, ACTIVE, pending_fees=10**14) for i in range(1, 11)]
    staged = [Listing(20, STAGED)]
    settled = [Listing(30, SETTLED)]

    # Below the ceiling: building, relisting, activation, harvest and deposit pricing all plan.
    s = state(listings=act + staged + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=12, fee_credit=10**16)
    got = fns(plan(s))
    assert {"sync", "harvest", "activate", "checkpoint", "list"} <= set(got), got

    # Above the ceiling with nothing owed: nothing at all.
    spike = dict(gas_price=int(1.05 * G), base_fee=int(1.0 * G))
    s = state(listings=act + staged + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=12, fee_credit=10**16, token_pending=10**18, token_ids=[1], burn_tokens=True, **spike)
    assert plan(s) == [], plan(s)
    assert status(s)[0][0] == "GAS_ABOVE_CEILING" and status(s)[0][1] == "wait"

    # Above the ceiling with a redemption short of ETH: only liability work, never deployment.
    s = state(listings=act + staged + settled, idle_packs=2, idle_eth=0, free=0, locked_shares=10**18,
              owed_estimate=int(0.3 * E), open_positions=12, fee_credit=10**16, token_pending=10**18,
              token_ids=[1], burn_tokens=True, **spike)
    got = fns(plan(s))
    assert set(got) <= {"sync", "harvest", "liquidate", "unlist", "checkpoint"}, got
    assert {"sync", "harvest", "unlist", "liquidate", "checkpoint"} <= set(got), got
    codes = {c for c, _, _ in status(s)}
    assert {"GAS_ABOVE_CEILING", "REDEMPTION_LIQUIDITY_SHORT", "STAGED_PENDING_ACTIVATION"} <= codes, codes

    # Above the ceiling with a redemption already covered by free ETH: just the pricing checkpoint.
    s = state(listings=act, free=E, locked_shares=10**18, owed_estimate=int(0.3 * E), open_positions=10, **spike)
    assert fns(plan(s)) == ["checkpoint"], plan(s)

    # Above the ceiling while winding down: unwinding continues.
    s = state(listings=act, free=0, winding_down=True, open_positions=10, idle_packs=1, **spike)
    assert {"unlist", "liquidate"} <= set(fns(plan(s))), plan(s)

    # Deposits alone above the ceiling wait (depositors can cancel).
    s = state(listings=act, free=E, pending_deposits=10**17, open_positions=10, **spike)
    assert plan(s) == []

    # Reserve need at the canary: one 10-pack listing batch at 0.5 gwei with the 10% premium:
    # (255k + 10 x 530k) quoted gas x 0.55 gwei (checkpoints are paid from request charges).
    assert reserve_need(state()) == 5_555_000 * int(0.5 * G) * 11_000 // 10_000
    assert 0.0030 * E < reserve_need(state()) < 0.0031 * E
    assert "RESERVE_BELOW_NEED" in {c for c, _, _ in status(state(reserve=10**15))}

    # Waiting states.
    s = state(listings=[Listing(1, ALLOCATED, allocated_at=10**6 - 10)], blackout=False, pending_deposits=1,
              open_positions=1, free=E)
    codes = {c for c, _, _ in status(s)}
    assert {"WAITING_SETTLEMENT", "WAITING_CHECKPOINT_WINDOW"} <= codes, codes
    assert status(state(backing=0, listings=act, open_positions=10))[0][0] == "QUOTE_UNAVAILABLE"
    assert ("EDGE_GATE_FAILED", "action") in {(c, k) for c, k, _ in status(state(k=E, listings=act))}
    assert status(state(listings=act, open_positions=10, free=E, idle_eth=0))[0][0] == "OK"
    print("keeper/test_policy.py: pass")


if __name__ == "__main__":
    main()
