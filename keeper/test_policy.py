#!/usr/bin/env python3
"""Pure economic policy and bounded work tests. No fabricated successful service answers."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import policy as P
from policy import ACTIVE, ALLOCATED, SETTLED, Listing, State, plan, reserve_need, status

G, E = 10**9, 10**18


def state(**kw):
    # Selected launch recipe: three paid Shapes, 0.03 ETH face and provisional 0.21 ETH backing.
    backing = kw.get("backing", 21 * 10**16)
    base = dict(now=10**6, gas_price=200_000_000, base_fee=150_000_000, gas_ceiling=500_000_000,
                max_tip=50_000_000, markup_bps=1_000, share_bps=2_500, k=1_038_500_000_000_000_000,
                backing=backing, min_edge_bps=100, settlement_fee_bps=100, mint_fee=10**15, settlement_window=3600,
                blackout=True, queue_drained=True, checkpoint_done_this_interval=False, reserve=10**16,
                backing_proposals=P.propose_backings(backing, 0, 16, lambda _: False),
                build_proposals=[-(-backing // 10_000) * 10_000] * 8)
    base.update(kw)
    return State(**base)


def fns(steps):
    return ["sync" if s[0] == "syncCheckpoint" else s[0] for s in steps]


def main():
    act = [Listing(i, ACTIVE, pending_fees=10**14) for i in range(1, 11)]
    settled = [Listing(30, SETTLED)]
    s = state(listings=act + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=11, fee_credit=10**16)
    got = fns(plan(s))
    assert {"sync", "list"} <= set(got), got
    assert "harvest" not in got
    assert "checkpoint" not in got  # terminal work must be reconciled, then re-read before pricing
    assert "checkpoint" in fns(plan(state(listings=act, free=E, pending_deposits=10**17)))
    # A kept-early booked-Allocated listing (FWA SELFDESTRUCT force-sent the payment: no CashReceipt,
    # pending_receipts==0) inside the settlement window must be synced before any checkpoint, even in
    # the checkpoint window, so the keeper never loops a checkpoint the vault reverts on PendingReceipts.
    kept_early = state(listings=[Listing(5, SETTLED, allocated_at=10**6 - 10)], pending_deposits=10**17,
                       free=E, pending_receipts=0)
    kept_plan = fns(plan(kept_early))
    assert "sync" in kept_plan and "checkpoint" not in kept_plan, kept_plan

    spike = dict(gas_price=1_050_000_000, base_fee=G)
    s = state(listings=act + settled, idle_packs=2, idle_eth=E, free=E, pending_deposits=10**17,
              open_positions=11, fee_credit=10**16, token_pending=E, token_ids=[1], burn_tokens=True, **spike)
    assert plan(s) == []
    assert status(s)[0][:2] == ("GAS_ABOVE_CEILING", "wait")
    s = state(listings=act + settled, idle_packs=2, idle_value=6 * P.UNIT, free=0, locked_shares=E,
              owed_estimate=3 * E // 10, open_positions=11, fee_credit=10**16, **spike)
    got = fns(plan(s))
    assert set(got) <= {"sync", "harvest", "liquidate", "unlist", "checkpoint"}, got
    assert {"unlist", "liquidate"} <= set(got)
    assert "harvest" not in got  # A claim that cannot fund the cash gap would precede the same unlists.
    assert "sync" not in got
    assert "checkpoint" not in got
    assert fns(plan(state(listings=act, free=E, locked_shares=E, owed_estimate=3 * E // 10, **spike))) == ["checkpoint"]
    assert {"unlist", "liquidate"} <= set(fns(plan(state(listings=act, winding_down=True, idle_packs=1, **spike))))
    assert plan(state(listings=act, free=E, pending_deposits=10**17, **spike)) == []

    # Active fee claims are candidates on real bounded maintenance, never a paid recurring job.
    fees = [Listing(i, ACTIVE, pending_fees=i * 10**15) for i in range(1, 30)]
    ample = state(listings=fees, free=E, fee_credit=E, blackout=False)
    assert "harvest" not in fns(plan(ample))
    funded_sync = state(listings=fees + settled, free=0, completed_prefix=128, open_positions=100)  # journal vault
    choices = [step for step in plan(funded_sync) if step[0] == "sync"]
    assert choices[0][1] == [30] and choices[1][1] == [30, 29], choices
    assert len(choices[-1][1]) == 16
    funded_sync.free = E
    assert plan(funded_sync)[0][1] == [30], "already funded jobs do not carry redundant active IDs"
    funded_sync.free, funded_sync.routine_budget = 0, 0
    assert plan(funded_sync)[0][1] == [30], "active fees cannot fix exhausted spending permission"
    one_own = state(listings=[Listing(1, ACTIVE, pending_fees=10**15)], free=0,
                    own_journal_pending=True, completed_prefix=1, open_positions=100,
                    routine_budget=150_000_000_000_000, markup_bps=0)
    assert plan(one_own)[1][1] == [1], "upper16-own bound must not hide a funded one-own job"
    two_own = state(listings=[Listing(i, ACTIVE, pending_fees=500_000) for i in (1, 2)],
                    own_journal_pending=True, completed_prefix=2, open_positions=100,
                    free=0, base_fee=1, max_tip=0, gas_price=1, markup_bps=0, routine_budget=1_000_000)
    assert [step[1] for step in plan(two_own) if step[0] == "sync"] == [[], [1], [1, 2]], \
        "exact preflight must reach the funded two-claim alternative"
    full_terminals = state(listings=[Listing(i, SETTLED) for i in range(30, 46)] + fees,
                           free=0, routine_budget=E)
    choices = [step for step in plan(full_terminals) if step[0] == 'sync']
    assert choices[0][1] == list(range(30, 46))
    assert choices[1][1] == list(range(30, 45)) + [29]
    assert all(len(step[1]) <= 16 for step in choices)
    assert all(any(i >= 30 for i in step[1]) for step in choices), 'fee-only no-op is not an alternative'
    # A small holder redemption can claim just enough real fees, unpaid, rather than unwind.
    partial = state(listings=fees, free=0, locked_shares=E, total_shares=3 * E,
                    owed_estimate=45 * 10**15, blackout=False)
    assert plan(partial)[0] == ("harvest", [28, 29])
    assert "unlist" not in fns(plan(partial))
    partial.total_shares = E + 10**15
    assert "harvest" not in fns(plan(partial)), "full holder exit collects fees while unlisting"
    credit_only = state(listings=fees, fee_credit=10**16, free=0, locked_shares=E,
                        total_shares=3 * E, owed_estimate=10**16)
    assert fns(plan(credit_only)) == ["checkpoint"], "checkpoint already collects sufficient credit"

    # Absolute envelope cash at0.5gwei: list8=(280k+8*825k)*0.55gwei=0.003784ETH;
    # routine journal128+prune16=(125k+128*22k+16*45k)*0.55gwei=0.00201355ETH.
    assert reserve_need(state()) == 5_797_550_000_000_000
    s = state(essential_ceiling=2 * G, work_fee=20_000_000_000_000)
    assert reserve_need(s) == 5_957_550_000_000_000
    unpaid = state(essential_ceiling=2 * G, work_fee=20_000_000_000_000, essential_cap=0)
    assert reserve_need(unpaid) == 5_957_550_000_000_000  # Sync is routine even with unpaid exits.
    assert "RESERVE_BELOW_NEED" in {c for c, _, _ in status(state(reserve=10**15))}
    assert P.checkpoint_cost(state(open_positions=301)) == P.checkpoint_cost(state(open_positions=10_000))
    assert P.request_charge(state(open_positions=1000)) == P.request_charge(state(open_positions=10_000))
    # Current provisional 500k checkpoint calibration, plus the work fee, at the routine ceiling.
    spike_checkpoint = state(base_fee=1_950_000_000, gas_price=2 * G,
                             markup_bps=0, work_fee=20_000_000_000_000)
    assert P.payment(spike_checkpoint, P.Q["checkpoint"], 1) == 270_000_000_000_000

    # Global reads and terminal IDs have independent bounds; small unrelated tails wait.
    s = state(journal_cursor=7, completed_prefix=100_007, open_positions=100, active_count=100)
    sync = plan(s)[0]
    assert sync == ("sync", [], 0), sync
    s = state(journal_cursor=7, completed_prefix=100_007, open_positions=100,
              listings=[Listing(30 + i, SETTLED) for i in range(20)])
    sync = plan(s)[0]
    assert len(sync[1]) == 16
    assert "sync" not in fns(plan(state(journal_cursor=7, completed_prefix=8, open_positions=1)))
    assert "sync" in fns(plan(state(journal_cursor=7, completed_prefix=8, open_positions=100, own_journal_pending=True)))
    assert "sync" in fns(plan(state(journal_cursor=7, completed_prefix=8, open_positions=1, pending_deposits=E)))
    assert "sync" in fns(plan(state(journal_cursor=7, completed_prefix=8, open_positions=1,
                                   distribution_bps=5000, distribution_due=False, witness_id=91)))
    blocked = state(journal_cursor=0, completed_prefix=128, open_positions=100, free=E,
                    idle_eth=E, idle_packs=1, routine_budget=1, markup_bps=0)
    assert P.journal_backlog_floor(blocked) == 588_200_000_000_000
    assert "sync" in fns(plan(blocked))
    assert not {"build", "list"} & set(fns(plan(blocked)))
    assert "MAINTENANCE_UNFUNDED" in {c for c, _, _ in status(blocked)}
    # Cash shortage, permission shortage and keeper profitability stay distinct, and each clears.
    detail = lambda st: next(d for c, _, d in status(st) if c == "MAINTENANCE_UNFUNDED")  # noqa: E731
    assert "routine permission" in detail(blocked) and "routine cash" not in detail(blocked)
    cash_short = state(journal_cursor=0, completed_prefix=128, open_positions=1, free=1, idle_eth=E, idle_packs=1,
                       routine_budget=E, markup_bps=0)
    assert "routine cash" in detail(cash_short) and "routine permission" not in detail(cash_short)
    assert not {"build", "list"} & set(fns(plan(cash_short)))
    resumed = state(journal_cursor=0, completed_prefix=128, open_positions=1, free=E, idle_eth=E, idle_packs=1,
                    routine_budget=E, markup_bps=0)
    assert "MAINTENANCE_UNFUNDED" not in {c for c, _, _ in status(resumed)}
    assert "list" in fns(plan(resumed)) or "build" in fns(plan(resumed)) or "sync" in fns(plan(resumed))
    assert "checkpoint" not in fns(plan(state(journal_cursor=7, completed_prefix=8, pending_deposits=E, open_positions=1)))

    # Scan vaults (at most 96 open): FWA's global activity alone never triggers paid work. One scan
    # selects and resolves each own selection once it settles or expires; other work rides along.
    scan = dict(journal_cursor=0, completed_prefix=5_000, open_positions=28, active_count=27, free=E)
    assert P.scan_vault(state(**scan)) and P.scan_proof(state(**scan))
    assert not P.scan_proof(state(journal_cursor=0, completed_prefix=37, open_positions=28))  # 28*30k > 37*22k
    assert "sync" not in fns(plan(state(**scan))), "foreign backlog alone is not vault work"
    inside = Listing(5, ALLOCATED, allocated_at=10**6 - 10, unapplied=True)
    assert "sync" not in fns(plan(state(listings=[inside], own_journal_pending=True, **scan))), \
        "a selection inside the window waits for its outcome"
    settled_own = Listing(5, SETTLED, allocated_at=10**6 - 10, unapplied=True)
    assert ("sync", [5], 0) in plan(state(listings=[settled_own], own_journal_pending=True, **scan))
    expired_own = Listing(5, ALLOCATED, allocated_at=10**6 - 3_601, unapplied=True)
    assert ("sync", [5], 0) in plan(state(listings=[expired_own], own_journal_pending=True, **scan))
    kicked = Listing(6, P.WITHDRAWN)
    assert "sync" not in fns(plan(state(listings=[kicked], **scan))), "an unpaid scan waits for a paid one"
    assert ("sync", [6, 5], 0) in plan(state(listings=[kicked, settled_own], own_journal_pending=True, **scan))
    assert ("sync", [6], 0) in plan(state(listings=[kicked], locked_shares=E, owed_estimate=E // 10, blackout=False, **scan)), \
        "holders waiting are served even when the scan is unpaid"
    assert plan(state(listings=[kicked], pending_deposits=E, **scan))[0] == ("syncCheckpoint", [], 0), \
        "in a checkpoint window the paid scan runs first, the terminal after it without a scan"
    assert P.journal_backlog_floor(state(markup_bps=0, routine_budget=1, **scan)) == (120_000 + 28 * 30_000) * 200_000_000
    assert "checkpoint" in fns(plan(state(journal_cursor=7, completed_prefix=100_007, pending_deposits=E)))
    assert "sync" not in fns(plan(state(journal_cursor=7, completed_prefix=100_007)))
    assert "checkpoint" not in fns(plan(state(pending_receipts=1, pending_deposits=E)))
    assert "checkpoint" not in fns(plan(state(allocation_stale=True, pending_deposits=E)))
    assert plan(state(journal_cursor=1, completed_prefix=2, **spike)) == []
    assert "sync" not in fns(plan(state(journal_cursor=1, completed_prefix=2, locked_shares=1, open_positions=1, **spike)))

    s = state(listings=[Listing(1, ALLOCATED, allocated_at=10**6 - 10)], blackout=False, pending_deposits=1, free=E)
    assert {"WAITING_SETTLEMENT", "WAITING_CHECKPOINT_WINDOW"} <= {c for c, _, _ in status(s)}
    assert status(state(backing=0, listings=act))[0][0] == "QUOTE_UNAVAILABLE"
    assert ("EDGE_GATE_FAILED", "action") in {(c, k) for c, k, _ in status(state(k=E, listings=act))}
    assert status(state(listings=act, free=E, idle_eth=0))[0][0] == "OK"
    assert "checkpoint" in fns(plan(state(distribution_due=True, listings=act)))
    assert "checkpoint" not in fns(plan(state(distribution_due=True, listings=act, **spike)))
    build = dict(listings=act, idle_eth=E, free=E)
    assert "build" in fns(plan(state(**build)))
    assert "build" not in fns(plan(state(pack_units_mask=1 << 4, **build)))  # REF_UNITS bit unset
    # Building does not reserve a tag. Listing is replanned from the next fresh inventory state.
    assert "list" not in fns(plan(state(**build)))
    assert not {"list", "build"} & set(fns(plan(state(queue_drained=False, **build))))
    assert "list" in fns(plan(state(idle_packs=2, **build)))
    # An unlistable larger gift must not bury valid inventory forever.
    gift = state(idle_packs=1, idle_value=4 * P.UNIT, backing_proposals=[], **build)
    assert "build" in fns(plan(gift))
    gift.idle_funding = E
    assert "build" in fns(plan(gift)), "old idle quotes do not reserve cash beside renewal float"
    gift.idle_funding = 0
    gift.backing_proposals = [2 * E]
    assert "build" not in fns(plan(gift)), "viable inventory retains cash priority"
    # Cached usable idle backing, rather than a hypothetical fixed 0.03 pack, covers liquidity.
    assert "unlist" not in fns(plan(state(idle_packs=1, idle_value=3 * E // 10, locked_shares=1,
                                          owed_estimate=2 * E // 10, listings=act)))
    # Audit E4: processingPool remains excluded; the original 0.000624 ETH shortfall liquidates.
    s = state(markup_bps=0, listings=[Listing(1, ACTIVE)], idle_packs=7, idle_value=7 * P.UNIT,
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
    # Personal manager (PackManager): no shares, deposits, redemptions or checkpoints; one owner's
    # ETH. The same strategy builds and lists; winding_down is the owner's reversible exit mode.
    mgr = state(pooled=False, listings=act, idle_eth=E, free=E)
    assert "checkpoint" not in fns(plan(mgr))
    assert "build" in fns(plan(mgr)), "a manager still builds and lists from its own ETH"
    # Even with a (mis)set pool flow, a manager never plans a checkpoint it has no function for.
    assert "checkpoint" not in fns(plan(state(pooled=False, pending_deposits=E, listings=act)))
    exiting = state(pooled=False, winding_down=True, listings=act, idle_packs=1)
    assert {"unlist", "liquidate"} <= set(fns(plan(exiting)))
    assert "build" not in fns(plan(exiting)), "exit mode lists nothing new"

    # Build is planned only when one bid cycle repays the build; a large mint fee breaks the gate.
    assert "build" in fns(plan(state(**build)))
    assert "build" not in fns(plan(state(mint_fee=10**17, **build))), "build gate fails when it cannot repay"

    # Planning is a pure function of state: the same State yields the same plan every time, and two
    # independent accounts' plans do not interact (no shared mutable module state between accounts).
    pool_acct = state(listings=act, idle_eth=E, free=E)
    mgr_acct = state(pooled=False, winding_down=True, listings=act, idle_packs=1)
    assert plan(pool_acct) == plan(pool_acct)
    assert fns(plan(pool_acct)) != fns(plan(mgr_acct))
    assert plan(mgr_acct) == plan(mgr_acct)

    # Combined FWA selection-weight share across accounts (monitoring only, never changes a plan).
    # Each listing's FWA weight is 1e36/backing; the share is their sum over FWA.totalWeight().
    b = 36_300_000_000_000_000  # one 0.0363 ETH listing
    w1 = 10**36 // b
    assert P.exposure_share_bps([b], w1) == 10_000  # a lone listing is the whole weight
    assert P.exposure_share_bps([b, b], 4 * w1) == 5_000  # two of four equal-weight listings
    assert P.exposure_share_bps([], 10**40) == 0 and P.exposure_share_bps([b], 0) == 0
    low = P.exposure_status(P.exposure_share_bps([b], 20 * w1))  # 5%
    assert [c for c, _, _ in low] == ["EXPOSURE_SHARE"]
    high = P.exposure_status(P.exposure_share_bps([b] * 2, 20 * w1))  # 10%
    assert ("EXPOSURE_SHARE_HIGH", "action") in {(c, k) for c, k, _ in high}
    assert P.exposure_share_bps([b] * 2, 20 * w1) == P.EXPOSURE_SHARE_HIGH_BPS

    print("keeper/test_policy.py: pass (economic gates, build gate, manager vs pool, per-account isolation, "
          "constant checkpoint charge, bounded catchup/proposals, reserve amounts)")


if __name__ == "__main__":
    main()
