#!/usr/bin/env python3
"""Pure economic policy and bounded work tests. No fabricated successful service answers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import policy as P
from policy import ACTIVE, ALLOCATED, SETTLED, Listing, State, plan, reserve_need, status

G, E = 10**9, 10**18


def state(**kw):
    backing = kw.get("backing", 363 * 10**14)
    base = dict(now=10**6, gas_price=200_000_000, base_fee=150_000_000, gas_ceiling=500_000_000,
                max_tip=50_000_000, markup_bps=1_000, share_bps=2_500, k=1_038_500_000_000_000_000,
                backing=backing, min_edge_bps=100, mint_fee=10**15, settlement_window=3600,
                blackout=True, queue_drained=True, checkpoint_done_this_interval=False, reserve=10**16,
                backing_proposals=P.propose_backings(backing, 0, 16, lambda _: False),
                restock_proposals=[-(-backing // 10_000) * 10_000] * 10)
    base.update(kw)
    return State(**base)


def fns(steps):
    return [s[0] for s in steps]


def main():
    act = [Listing(i, ACTIVE, pending_fees=10**14) for i in range(1, 11)]
    settled = [Listing(30, SETTLED)]
    s = state(listings=act + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=11, fee_credit=10**16)
    got = fns(plan(s))
    assert {"sync", "harvest", "list"} <= set(got), got
    assert "checkpoint" not in got  # terminal work must be reconciled, then re-read before pricing
    assert "checkpoint" in fns(plan(state(listings=act, free=E, pending_deposits=10**17)))

    spike = dict(gas_price=1_050_000_000, base_fee=G)
    s = state(listings=act + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=11, fee_credit=10**16, token_pending=E, token_ids=[1], burn_tokens=True, **spike)
    assert plan(s) == []
    assert status(s)[0][:2] == ("GAS_ABOVE_CEILING", "wait")
    s = state(listings=act + settled, idle_packs=2, idle_value=6 * P.UNIT, free=0, locked_shares=E,
              owed_estimate=3 * E // 10, open_positions=11, fee_credit=10**16, **spike)
    got = fns(plan(s))
    assert set(got) <= {"sync", "harvest", "liquidate", "unlist", "checkpoint"}, got
    assert {"sync", "harvest", "unlist", "liquidate"} <= set(got)
    assert "checkpoint" not in got
    assert fns(plan(state(listings=act, free=E, locked_shares=E, owed_estimate=3 * E // 10, **spike))) == ["checkpoint"]
    assert {"unlist", "liquidate"} <= set(fns(plan(state(listings=act, winding_down=True, idle_packs=1, **spike))))
    assert plan(state(listings=act, free=E, pending_deposits=10**17, **spike)) == []

    # Absolute envelope cash at0.5gwei: list8=(400k+8*825k)*0.55gwei=0.00385ETH;
    # routine journal16+prune16=(85k+16*30k+16*45k)*0.55gwei=0.00070675ETH.
    assert reserve_need(state()) == 4_490_750_000_000_000
    s = state(essential_ceiling=2 * G, work_fee=20_000_000_000_000)
    assert reserve_need(s) == 6_514_000_000_000_000
    unpaid = state(essential_ceiling=2 * G, work_fee=20_000_000_000_000, essential_cap=0)
    assert reserve_need(unpaid) == 4_650_750_000_000_000  # D64: no essential vault pay
    assert "RESERVE_BELOW_NEED" in {c for c, _, _ in status(state(reserve=10**15))}
    assert P.checkpoint_cost(state(open_positions=301)) == P.checkpoint_cost(state(open_positions=10_000))
    assert P.request_charge(state(open_positions=1000)) == P.request_charge(state(open_positions=10_000))

    # Necessary global catchup is bounded even with a huge foreign-only backlog; it runs at the
    # essential gas class for locked exits, and never pretends foreign entries are own positions.
    s = state(journal_cursor=7, completed_prefix=100_007)
    sync = plan(s)[0]
    assert sync == ("sync", 16, [], 16), sync
    s = state(journal_cursor=7, completed_prefix=100_007, listings=settled * 20)
    sync = plan(s)[0]
    assert sync[1] + len(sync[2]) <= 16
    assert "checkpoint" not in fns(plan(state(journal_cursor=7, completed_prefix=8, pending_deposits=E)))
    assert "checkpoint" not in fns(plan(state(pending_receipts=1, pending_deposits=E)))
    assert "checkpoint" not in fns(plan(state(allocation_stale=True, pending_deposits=E)))
    assert plan(state(journal_cursor=1, completed_prefix=2, **spike)) == []
    assert plan(state(journal_cursor=1, completed_prefix=2, locked_shares=1, **spike))[0][0] == "sync"

    s = state(listings=[Listing(1, ALLOCATED, allocated_at=10**6 - 10)], blackout=False, pending_deposits=1, free=E)
    assert {"WAITING_SETTLEMENT", "WAITING_CHECKPOINT_WINDOW"} <= {c for c, _, _ in status(s)}
    assert status(state(backing=0, listings=act))[0][0] == "QUOTE_UNAVAILABLE"
    assert ("EDGE_GATE_FAILED", "action") in {(c, k) for c, k, _ in status(state(k=E, listings=act))}
    assert status(state(listings=act, free=E, idle_eth=0))[0][0] == "OK"
    assert "checkpoint" in fns(plan(state(distribution_due=True, listings=act)))
    assert "checkpoint" not in fns(plan(state(distribution_due=True, listings=act, **spike)))
    build = dict(listings=act, idle_eth=E, free=E)
    assert "restock" in fns(plan(state(**build)))
    assert "restock" not in fns(plan(state(pack_units_mask=1 << 4, **build)))
    # Building does not reserve a tag. Listing is replanned from the next fresh inventory state.
    assert "list" not in fns(plan(state(**build)))
    assert not {"list", "restock"} & set(fns(plan(state(queue_drained=False, **build))))
    assert "list" in fns(plan(state(idle_packs=2, **build)))
    # An unlistable larger gift must not bury valid3-unit inventory forever.
    gift = state(idle_packs=1, idle_value=4 * P.UNIT, backing_proposals=[], **build)
    assert "restock" in fns(plan(gift))
    gift.idle_funding = E
    assert "restock" not in fns(plan(gift))
    gift.idle_funding = 0
    gift.backing_proposals = [2 * E]
    assert "restock" not in fns(plan(gift)), "viable inventory retains cash priority"
    # Cached usable idle backing, rather than a hypothetical fixed 0.03 pack, covers liquidity.
    assert "unlist" not in fns(plan(state(idle_packs=1, idle_value=3 * E // 10, locked_shares=1,
                                          owed_estimate=2 * E // 10, listings=act)))
    # Audit E4: processingPool remains excluded; the original 0.000624 ETH shortfall liquidates.
    s = state(markup_bps=0, listings=[Listing(1, ACTIVE)], loose_shapes=7, idle_value=7 * P.UNIT,
              free=873_337_920_659_858_602, owed_estimate=873_961_920_659_858_594,
              locked_shares=86_597_063_493_129_589, work_fee=20_000_000_000_000)
    assert fns(plan(s)).index("liquidate") < fns(plan(s)).index("checkpoint")

    # Identifiers can go on either side, obey the actual interval, and become reusable.
    target = 10**16 + 1234
    used = {target // 10_000 * 10_000, (target // 10_000 + 1) * 10_000}
    probes = []
    def occupied(b):
        probes.append(b)
        return b in used
    qs = P.propose_backings(target, len(used), 16, occupied)
    assert len(qs) == len(set(qs)) == 16 and len(probes) <= 64 * 16
    assert all(b % 10_000 == 0 and abs(b - target) <= (len(used) + i + 1) * 10_000 for i, b in enumerate(qs))
    below = P.propose_backings(target, 10, 1, lambda _: False, maximum=target - 1)
    above = P.propose_backings(target, 10, 1, lambda _: False, minimum=target + 1)
    assert below[0] < target < above[0]
    assert P.propose_backings(target, 10, 1, lambda _: False, minimum=target, maximum=target) == []
    assert P.propose_backings(target, 0, 1, lambda _: False)[0] == target // 10_000 * 10_000
    assert P.propose_backings(target, 0, 1, lambda _: True) == []
    crowded_target = 36_300_000_000_000_000
    crowded = {crowded_target - i * 10_000 for i in range(10_000)}
    edges = P.propose_backings(crowded_target, len(crowded), 8, crowded.__contains__, maximum=crowded_target)
    assert len(edges) == 8 and len(set(edges)) == 8
    assert all(b not in crowded and b <= crowded_target for b in edges)
    print("keeper/test_policy.py: pass (economic gates, constant checkpoint charge, bounded catchup/proposals, reserve amounts)")


if __name__ == "__main__":
    main()
