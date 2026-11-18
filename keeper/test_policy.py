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
    # Audit E5: 100 staged listings activate in batches that fit one transaction.
    many = [Listing(1000 + i, STAGED) for i in range(100)]
    acts = [st for st in plan(state(listings=many, open_positions=100, free=E)) if st[0] == "activate"]
    assert len(acts) == 5 and all(len(st[1]) == 20 and st[2] == 20 for st in acts), acts
    assert sorted(i for st in acts for i in st[1]) == [l.id for l in many]

    # Audit E2: a due distribution schedules a checkpoint with no holder flows; not above the ceiling.
    assert "checkpoint" in fns(plan(state(distribution_due=True, listings=act, open_positions=10)))
    assert "checkpoint" not in fns(plan(state(listings=act, open_positions=10)))
    assert "checkpoint" not in fns(plan(state(distribution_due=True, listings=act, open_positions=10, **spike)))

    # A drained acquisition queue can coexist with an older staged backlog.
    # Do not list more inventory, but keep checkpoints, exits and activation live.
    backlog = state(listings=act + staged, open_positions=11, idle_eth=E,
                    free=E, idle_packs=2, staging_empty=False)
    got = fns(plan(backlog))
    assert "list" not in got and "restock" not in got, got
    assert "activate" in got, got
    assert "STAGING_BACKLOG" in {c for c, _, _ in status(backlog)}, status(backlog)
    backlog_with_deposit = state(listings=act + staged, open_positions=11,
                                 free=E, pending_deposits=10**17, staging_empty=False)
    assert "checkpoint" in fns(plan(backlog_with_deposit)), plan(backlog_with_deposit)
    backlog_with_redemption = state(listings=act, open_positions=10, free=0,
                                    locked_shares=10**18, owed_estimate=E,
                                    staging_empty=False)
    assert "unlist" in fns(plan(backlog_with_redemption)), plan(backlog_with_redemption)

    # Audit E11: a mask without 3-unit packs builds nothing (this keeper builds 3-unit packs only).
    build = dict(listings=act, open_positions=10, idle_eth=E, free=E, loose_shapes=0)
    assert "restock" in fns(plan(state(**build)))
    assert "restock" not in fns(plan(state(pack_units_mask=1 << 4, **build)))

    # Audit E6: above the ceiling, a redemption checkpoint is preceded by syncing expired allocations.
    expired = [Listing(5, ALLOCATED, allocated_at=10**6 - 7200)]
    got = fns(plan(state(listings=expired, locked_shares=10**18, owed_estimate=10**15, free=E, open_positions=1, **spike)))
    assert got.index("sync") < got.index("checkpoint"), got
    # Audit E4: with processingPool subtracted, the auditor's fork balances show the real
    # 0.000624 ETH shortfall and the keeper releases liquidity before the checkpoint.
    s = state(markup_bps=0, listings=[Listing(1, ACTIVE)], loose_shapes=7, free=873_337_920_659_858_602,
              owed_estimate=873_961_920_659_858_594, locked_shares=86_597_063_493_129_589, idle_eth=0,
              open_positions=1, work_fee=20_000_000_000_000)
    got = fns(plan(s))
    assert "liquidate" in got and got.index("liquidate") < got.index("checkpoint"), got
    # Audit E7: no listing or building while FWA's queue is busy (it would stage and cost activation).
    assert not {"list", "restock"} & set(fns(plan(state(queue_drained=False, **build))))
    assert "list" in fns(plan(state(idle_packs=2, listings=act, open_positions=10, idle_eth=E, free=E)))
    print("keeper/test_policy.py: pass")


if __name__ == "__main__":
    main()
