#!/usr/bin/env python3
"""Matched, cash-path recipe comparison for the unified Shape-pack strategy (owner brief A3.31).

The existing sim/unified.py study has no cash path (returns truncate at ruin, pack count fixed) and
sim/forward.py's closed form uses different purchaser assumptions, so its recipe numbers are not
comparable to the formal gate. This drives every recipe through the SAME formal simulator the gate
uses (sim/formal.py -> sim/forward.run -> the sim/vault.py integer mirror of PackVault + keeper
decisions from keeper/policy.py), with the full cash path: real cash reserve, replacement-build
delays, profitability gates, backing posted and lost, keeper budgets and fixed pay quotes, mint
fees, FWA settlement fees, and a complete holder withdrawal at the end (residual to the wei).

Everything is identical across recipes except the recipe itself: same starting capital, same FWA
demand history (sim/data/fwa.sqlite, the actual 30 days ending at the pinned block, tiled to a
year), same purchaser-response pool, same gas, same random seeds. The three candidates differ only
in pack value P, Shape count, construction gas and creator mint fee; all three use the CURRENT
keep-incentive backing rule (VaultLib.edge / keeper.policy.edge_backing) with PURCHASER_GAS_PRICE a
fixed 2 gwei.

Candidates (owner brief):
  r1_06  0.06 direct mint (CURRENT): one 0.05 + one 0.01 Shape, 2 paid mints (0.002 ETH at 0.001).
  r2_03b 0.03 bulk mint + split (removed recipe): a 0.1 ETH Shape minted and split into 0.01
         denominations; 3 of them make a 0.03 pack. Construction gas and the 0.0003 ETH/pack creator
         fee recovered from main's VaultLib and sim/unified.py (OLD_PACK_GAS 325k + bulk-mint
         220k/pack amortised; one 0.1 mint fee 0.001 ETH split 10 ways = 0.0001/unit = 0.0003/pack).
  r3_03d 0.03 direct mint (three 0.01 Shapes, 3 paid mints): the simple alternative the current
         contract could build if packUnitsMask allowed units=3.

Recipe parameters are injected into the forward/policy modules per worker (spawn resets module
globals), leaving src/, keeper/ and the mirror untouched. Purchaser redeem gas follows each
recipe's Shape count through keeper/policy.py (REDEEM_2, REDEEM_3).

Usage: sim/recipe_comparison.py [--seeds 160] [--workers 14] [--quick] [--grid core|full]
"""
import argparse
import hashlib
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "keeper"))
import forward as F        # noqa: E402
import formal as FM        # noqa: E402
import policy              # noqa: E402
import replay              # noqa: E402

ROOT = HERE.parent
OUT = HERE / "out"
RECEIPT = ROOT / "docs/receipts"
HURDLE_BPS = 1_000  # owner's 10%/yr net gate

# ShapePacks.redeem of a 2-Shape 0.06 pack is 157,023 gas (ForkDirectMint.t.sol), quoted 160,000.
# Purchaser redeem gas comes from keeper.policy (VaultLib): a pack plus 30,000 per Shape.
REDEEM_2 = policy.Q_PURCHASER_REDEEM_PACK + 2 * policy.Q_PURCHASER_REDEEM_SHAPE
REDEEM_3 = policy.Q_PURCHASER_REDEEM_PACK + 3 * policy.Q_PURCHASER_REDEEM_SHAPE

RECIPES = {
    "r1_06":  dict(name="0.06 direct (current)",   units=6, mint_fee=10**15, redeem=REDEEM_2, legacy=False),
    "r2_03b": dict(name="0.03 bulk mint + split",  units=3, mint_fee=10**14, redeem=REDEEM_3, legacy=True),
    "r3_03d": dict(name="0.03 direct (3 Shapes)",  units=3, mint_fee=10**15, redeem=REDEEM_3, legacy=False),
}
# r2 legacy construction gas (non-listed, per pack): OLD_PACK_GAS 325,000 + bulk-mint 220,000
# (a 2,200,000-gas 0.1 ETH mint amortised over its ten 0.01 denominations). Direct mint instead
# costs Q_BUILD_PACK 300,000 + n x Q_BUILD_SHAPE 130,000.
LEGACY_BUILD_PACK, LEGACY_BUILD_SHAPE = 545_000, 0
DIRECT_BUILD_PACK, DIRECT_BUILD_SHAPE = 300_000, 130_000

SMALL = 1_960_100_000_000_000_000  # formal's 1.96 ETH holder cell


def set_recipe(r):
    """Inject a recipe into the forward/policy module globals (this process only)."""
    F.P = r["units"] * 10**16
    F.BUILD_UNITS = r["units"]
    F.MINT_FEE = r["mint_fee"]
    policy.PURCHASER_GAS_PRICE = int(r.get("gps_gwei", 2) * 10**9)
    policy.Q["build_pack"] = LEGACY_BUILD_PACK if r["legacy"] else DIRECT_BUILD_PACK
    policy.Q["build_shape"] = LEGACY_BUILD_SHAPE if r["legacy"] else DIRECT_BUILD_SHAPE


def config_for(principal):
    return "mainnet"


# ----------------------------------------------------------------- scenarios

def make_scenario(w, behaviour, keep_p, events, period, exempt=True):
    """A timed replay scenario with a purchaser-response sampler. Timing is clamped just inside FWA's
    settlement window for every behaviour (matched), so recipes differ only in the keep/bid choice.
    Silent responders (no recorded answer) let the account reclaim backing, which is a keep."""
    responses = w["responses"]
    last = F.OperatingClock.SETTLEMENT - 120

    def sampler(rng):
        delay, rec_kept = responses[int(rng.integers(len(responses)))]
        if delay is None:
            return None, None
        delay = min(delay, last)
        if behaviour == "allbid":
            kept = False
        elif behaviour == "value":
            kept = True
        elif behaviour == "observed":
            kept = bool(rec_kept)
        else:  # fixed keep rate
            kept = bool(rng.random() < keep_p)
        return delay, kept

    return F.Scenario(volume=F.const(0), timed=True, start_timestamp=w["start"], poll_seconds=60,
                      receipt_seconds=36, replay_events=w["events"] if events is None else events,
                      replay_period_seconds=FM.WINDOW if period is None else period,
                      response_sampler=sampler, foreign_pool_weight=1.0, exempt=exempt)


def recent_events(w, days=10):
    """The window's last `days` tiled (quieter / more concentrated demand)."""
    start = FM.WINDOW - days * F.DAY
    pairs = [(max(0, r - start), c - start, x) for r, c, x in w["pairs"] if c >= start]
    return FM.flatten(pairs), days * F.DAY


# ----------------------------------------------------------------- worker

_W = None  # window, built once per worker


def _init(window):
    global _W
    _W = window


def _one(task):
    """Run one seeded cell. task carries the recipe and the formal job."""
    (rkey, gps, label, principal, price, behaviour, keep_p, kind, seed, days, exit_days) = task
    r = dict(RECIPES[rkey])
    if gps is not None:
        r["gps_gwei"] = gps
    set_recipe(r)
    events, period = (None, None)
    if kind == "recent10":
        events, period = recent_events(_W, 10)
    elif kind == "zero":
        events, period = [], FM.WINDOW
    config = config_for(principal)
    values = json.loads((ROOT / f"deploy/{config}.json").read_text())
    sc = make_scenario(_W, behaviour, keep_p, events, period)
    sc.update(gwei=max(0.0, price - values["maxTipWei"] / F.GWEI), deposit_wei=principal,
              exit_all=True, exit_days=exit_days, user_gas_proxy=_W["user_gas"])
    res = F.run(sc, 1, seed, days=days, values=values)
    res.pop("ret", None)
    assert res["ledger_gap_wei"] == 0 and res["unknown_user_gas_calls"] == 0
    assert res["routine_keeper_paid_wei"] <= res["routine_period_permission_upper_wei"]
    shapes = policy.shape_count(r["units"])
    net_bps = res["holder_net_realized_wei"] * 10_000 // res["holder_paid_in_wei"]
    return dict(
        cell="|".join([rkey, str(gps or 2), label, str(principal), f"{price}", behaviour,
                       f"{keep_p}", kind]),
        rkey=rkey, gps=gps or 2, label=label, principal=principal, price=price, behaviour=behaviour,
        keep_p=keep_p, kind=kind, seed=seed, config=config,
        exit_complete=bool(res["exit_complete"]), net_bps=int(net_bps),
        net_wei=res["holder_net_realized_wei"], paid_in_wei=res["holder_paid_in_wei"],
        creator_mint_fees_wei=res["creator_mint_fees_wei"], fees_received_wei=res["fees_received_wei"],
        keeper_paid_wei=res["keeper_paid_wei"], routine_keeper_paid_wei=res["routine_keeper_paid_wei"],
        request_keeper_paid_wei=res["request_funded_keeper_paid_wei"],
        backing_lost_wei=res["backing_lost_wei"], settlement_fees_wei=res["settlement_fees_wei"],
        own_selections=res["own_selections"], pos_mean=res["pos_mean"], pos_max=res["pos_max"],
        util=res["util"], min_free_wei=res["min_free_wei"],
        build_calls=res["keeper_calls_build"], list_calls=res["keeper_calls_list"],
        routine_unfunded=res["routine_unfunded_attempts"], skipped_unfunded=res["skipped_unfunded"],
        operating_active_days=res["operating_active_days"], shapes=shapes,
        mint_count=res["creator_mint_fees_wei"] // (shapes * r["mint_fee"]) if r["mint_fee"] else 0,
        avg_book_wei=res["avg_book_wei"], avg_deployed_wei=res["avg_deployed_wei"])


# ----------------------------------------------------------------- cell plan

def build_jobs(seeds, quick, grid):
    """Yield (task) tuples with per-cell seed counts. Seeds are spent where the downside lives: the
    small 1.96 ETH canary has wide seed variance (so it gets the full count); large pools are tight
    by the law of large numbers (fewer seeds); r3 (0.03 direct) never lists, so it is deterministic
    (2 seeds prove the gate failure); zero-demand is deterministic (1 seed)."""
    days, exit_days = (30, 30) if quick else (360, 30)

    def nseeds(rk, principal, kind):
        if quick:
            return 1
        if kind == "zero":
            return 1
        if rk == "r3_03d":          # never lists: deterministic flat return
            return 2
        if principal <= 2 * 10**18:  # 1.96 ETH canary: widest variance, the downside cell
            return seeds
        if principal <= 7 * 10**18:  # 6.8 ETH
            return min(seeds, 64)
        if principal <= 20 * 10**18:
            return min(seeds, 48)
        return min(seeds, 24)        # 50 ETH: very tight distribution

    jobs = []
    recs = list(RECIPES)

    def add(label, principal, price, behaviour, keep_p, kind, gps=None):
        for rk in recs:
            for s in range(1, nseeds(rk, principal, kind) + 1):
                jobs.append((rk, gps, label, principal, price, behaviour, keep_p, kind, s, days, exit_days))

    if grid == "focused":
        # Coordinator subset: canary + one larger level, behaviours {0%, 50%, 100%, observed},
        # base and stressed (last-10-days) demand. Plus purchaser-gas sensitivity and zero demand.
        BEH = [("allbid", 0.0), ("fixed", 0.5), ("value", 1.0), ("observed", 1.0)]
        for beh, kp in BEH:
            add("1.96ETH", SMALL, 0.5, beh, kp, "base")   # canary, every behaviour, base demand
            add("20ETH", 20 * F.E, 0.5, beh, kp, "base")   # larger level, every behaviour
        # Stressed (last-10-days) demand at the extremes of keep, both capitals.
        for beh, kp in (("allbid", 0.0), ("value", 1.0)):
            add("1.96ETH", SMALL, 0.5, beh, kp, "recent10")
            add("20ETH", 20 * F.E, 0.5, beh, kp, "recent10")
        add("1.96ETH", SMALL, 0.5, "value", 1.0, "zero")
        add("1.96ETH", SMALL, 0.2, "value", 1.0, "base")  # low gas
        for gps in (1, 3):                                   # purchaser-gas sensitivity
            add("1.96ETH", SMALL, 0.5, "value", 1.0, "base", gps=gps)
        return jobs

    # Headline: recipe x capital x behaviour, at the 0.5 gwei gate price.
    caps_all = [("1.96ETH", SMALL), ("20ETH", 20 * F.E)]
    caps_edge = [("6.8ETH", 68 * 10**17), ("50ETH", 50 * F.E)]
    for label, cap in caps_all:
        for beh, kp in (("allbid", 0.0), ("value", 1.0), ("observed", 1.0)):
            add(label, cap, 0.5, beh, kp, "base")
    for label, cap in caps_edge:                       # capacity curve: two behaviours only
        for beh, kp in (("allbid", 0.0), ("value", 1.0)):
            add(label, cap, 0.5, beh, kp, "base")

    if grid == "full":
        # Fixed keep-rate sweep at the canary (0 and 1 already covered by allbid/value).
        for kp in (0.25, 0.5, 0.75):
            add("1.96ETH", SMALL, 0.5, "fixed", kp, "base")
        # Stress: quieter/concentrated (last 10 days) and zero demand, value-aware.
        add("1.96ETH", SMALL, 0.5, "value", 1.0, "recent10")
        add("1.96ETH", SMALL, 0.5, "value", 1.0, "zero")
        # Higher gas: 0.2 gwei (low) already excluded; run the ceiling already is 0.5. Add a
        # low-gas 0.2 reference at the canary, value-aware.
        add("1.96ETH", SMALL, 0.2, "value", 1.0, "base")
        # Purchaser-gas-price sensitivity (changes backing): 1 and 3 gwei (2 is the base above).
        for gps in (1, 3):
            add("1.96ETH", SMALL, 0.5, "value", 1.0, "base", gps=gps)
    return jobs


# ----------------------------------------------------------------- analysis

def backing_table(gps_gwei=2, price_gwei=0.5):
    """Analytic backing and keep advantage per recipe at the gate, no simulation."""
    vals = json.loads((ROOT / "deploy/mainnet.json").read_text())
    k = int(F.k_of() * F.E)
    rows = {}
    for rk, r in RECIPES.items():
        policy.PURCHASER_GAS_PRICE = int(gps_gwei * 10**9)
        P = r["units"] * 10**16
        B = policy.edge_backing(k, None, int(F.S_FEE * 1e4), r["units"], vals["gasCeilingWei"],
                                vals["payMarkupBps"], vals["workFeeWei"],
                                price=min(int(price_gwei * F.GWEI), vals["gasCeilingWei"]),
                                mint_fee=r["mint_fee"], buffer_bps=vals["bufferBps"],
                                min_edge_bps=vals["minEdgeBps"])
        best_bid = B * 9150 // 10_000  # FWA's best bid (token discount 9150 bps)
        redeem_cost = r["redeem"] * int(gps_gwei * 10**9)
        keep_adv = P - best_bid - redeem_cost  # purchaser keeps a P-pack vs the best bid, after gas
        # build gate (keeper.policy.build_net >= build_cost) at the ceiling
        set_recipe(dict(r, gps_gwei=gps_gwei))
        st = F.charge_state(int(price_gwei * F.GWEI), 0)
        st.gas_ceiling, st.max_tip, st.work_fee = vals["gasCeilingWei"], vals["maxTipWei"], vals["workFeeWei"]
        st.k, st.backing, st.build_units, st.settlement_fee_bps = k, B, r["units"], int(F.S_FEE * 10_000)
        st.markup_bps, st.mint_fee = vals["payMarkupBps"], r["mint_fee"]
        rows[rk] = dict(
            name=r["name"], P_eth=P / 1e18, backing_wei=int(B), backing_eth=B / 1e18,
            ratio=round(B / P, 4) if B else 0.0,
            lists=B > 0, best_bid_eth=best_bid / 1e18, keep_advantage_eth=keep_adv / 1e18,
            build_cost_eth=policy.build_cost(st, r["units"]) / 1e18,
            build_net_eth=policy.build_net(st) / 1e18,
            can_rebuild=policy.build_net(st) >= policy.build_cost(st, r["units"]) and B > 0,
            creator_fee_per_pack_eth=policy.shape_count(r["units"]) * r["mint_fee"] / 1e18)
    return rows


def summarize(rows):
    out = {}
    keys = dict.fromkeys(r["cell"] for r in rows)
    for cell in keys:
        g = [r for r in rows if r["cell"] == cell]
        done = [r for r in g if r["exit_complete"]]
        bps = sorted(r["net_bps"] for r in done)
        a = g[0]
        yrs = 1.0  # 360 operating days; net_bps is the annual return
        cap_eth = a["principal"] / 1e18
        out[cell] = dict(
            rkey=a["rkey"], gps=a["gps"], label=a["label"], principal_eth=cap_eth, price=a["price"],
            behaviour=a["behaviour"], keep_p=a["keep_p"], kind=a["kind"], config=a["config"],
            runs=len(g), completed=len(done), blocked=len(g) - len(done),
            mean_bps=int(np.mean(bps)) if bps else None, median_bps=bps[len(bps) // 2] if bps else None,
            p5_bps=int(np.percentile(bps, 5)) if bps else None,
            p10_bps=int(np.percentile(bps, 10)) if bps else None,
            worst_bps=bps[0] if bps else None, best_bps=bps[-1] if bps else None,
            loss_runs=sum(b < 0 for b in bps), below_hurdle_runs=sum(b < HURDLE_BPS for b in bps),
            loss_frac=round(sum(b < 0 for b in bps) / len(bps), 4) if bps else None,
            mean_creator_mint_eth=float(np.mean([r["creator_mint_fees_wei"] for r in g])) / 1e18,
            creator_per_eth_yr=float(np.mean([r["creator_mint_fees_wei"] for r in g])) / 1e18 / cap_eth / yrs,
            mean_fees_eth=float(np.mean([r["fees_received_wei"] for r in g])) / 1e18,
            mean_keeper_eth=float(np.mean([r["keeper_paid_wei"] for r in g])) / 1e18,
            mean_backing_lost_eth=float(np.mean([r["backing_lost_wei"] for r in g])) / 1e18,
            mean_selections=float(np.mean([r["own_selections"] for r in g])),
            mean_builds=float(np.mean([r["build_calls"] for r in g])),
            mean_mint_count=float(np.mean([r["mint_count"] for r in g])),
            mean_pos=float(np.mean([r["pos_mean"] for r in g])),
            mean_util=float(np.mean([r["util"] for r in g])),
            mean_min_free_eth=float(np.mean([r["min_free_wei"] for r in g])) / 1e18,
            mean_active_days=float(np.mean([r["operating_active_days"] for r in g])),
            mean_routine_unfunded=float(np.mean([r["routine_unfunded"] for r in g])),
            turnover_per_eth=float(np.mean([r["own_selections"] for r in g])) / cap_eth,
            pass_hurdle=bool(bps and np.median(bps) >= HURDLE_BPS and len(done) == len(g)))
    return out


# ----------------------------------------------------------------- main

SOURCES = ["sim/recipe_comparison.py", "sim/forward.py", "sim/vault.py", "keeper/policy.py",
           "sim/formal.py", "deploy/mainnet.json"]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seeds", type=int, default=160)
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    ap.add_argument("--grid", choices=["core", "full", "focused"], default="full")
    ap.add_argument("--quick", action="store_true", help="1 seed, 30 days (smoke test, not a result)")
    ap.add_argument("--no-replay", action="store_true", help="skip the archive fee-replay check")
    a = ap.parse_args()
    OUT.mkdir(exist_ok=True)
    RECEIPT.mkdir(parents=True, exist_ok=True)
    if not a.no_replay:
        assert replay.main() == 0, "archive fails exact fee replay"
    sha = lambda p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest()
    frozen = {p: sha(p) for p in SOURCES}

    db = F.ROOT / "data/fwa.sqlite"
    w = FM.window(db, FM.PIN["timestamp"])
    import efficient_operating as C
    w["user_gas"] = C.receipt_gas()
    assert w["archive_top_block"] <= FM.PIN["block"]

    jobs = build_jobs(a.seeds, a.quick, a.grid)
    print(f"{len(jobs)} runs, {a.workers} workers, {a.seeds} seeds, grid={a.grid}", flush=True)
    t0 = time.time()
    rows, done = [], 0
    with ProcessPoolExecutor(a.workers, initializer=_init, initargs=(w,)) as pool:
        for r in pool.map(_one, jobs):
            rows.append(r)
            done += 1
            if done % 100 == 0:
                print(f"  {done}/{len(jobs)} ({time.time() - t0:.0f}s)", flush=True)
    assert frozen == {p: sha(p) for p in SOURCES}, "a source file changed during the run"
    summary = summarize(rows)
    backing = {g: backing_table(gps_gwei=g) for g in (1, 2, 3)}
    report = dict(
        generated=time.strftime("%Y-%m-%d"), pin=FM.PIN, seeds=a.seeds, grid=a.grid,
        command=["python3", *sys.argv], source_sha256=frozen,
        window=dict(start=w["start"], end=w["end"], successful=w["successful"],
                    refunded=w["refunded"], successful_per_day=w["successful_per_day"],
                    purchaser_responses=w["response_kinds"]),
        live_fwa=dict(settlement_discount_bps=9000, token_settlement_discount_bps=9150,
                      accept_bid_as_tokens_enabled=True,
                      note="pinned-block ConfigSet values (sim/out/phase0.2.md); best bid = token 9150"),
        hurdle_bps=HURDLE_BPS, recipes={k: v for k, v in RECIPES.items()},
        redeem_gas=dict(two_shape=REDEEM_2, three_shape=REDEEM_3,
                        note="2-Shape measured 157,023 (ForkDirectMint); 3rd Shape derived from "
                             "policy.Q[redeem_shape]=35,000, not fork-measured"),
        backing_by_gps_gwei=backing, summary=summary, runtime_s=round(time.time() - t0, 1),
        notes=[
            "0.06 keep-incentive backing B = 64,896,174,863,380,000 wei (PURCHASER_GAS_PRICE 2 gwei), "
            "matching the final contract; see backing_by_gps_gwei['2']['r1_06']['backing_wei'].",
            "Checkpoint pay: this cash path prices a checkpoint at the flat Q_CHECKPOINT=360,000 gas "
            "(policy.Q['checkpoint']) plus one work fee. The final contract adds 6,000 gas per "
            "allocation-queue entry read and 30,000 per FWA listing read, at most 32 entries, usually "
            "0-2 at a checkpoint. At 0.5 gwei that is at most ~0.00058 ETH and usually <0.00004 ETH "
            "extra per checkpoint; checkpoints fire only on holder flows (~2 over a run: price the "
            "deposit, price the exit), so the omission shifts every recipe's annual return by well "
            "under 0.01% and does not change any ranking. It is request-funded (holder-paid), equal "
            "across recipes.",
            "Every recipe uses the current keep-incentive backing rule with the live token-bid "
            "discount 9150 bps; r2/r3 (0.03 packs, three 0.01 Shapes) price the purchaser redeem at "
            "195,000 gas (160,000 measured for a 2-Shape pack + 35,000 derived per Shape, not "
            "fork-measured). The effect on 0.03 backing versus 160,000 is ~7e-5 ETH, immaterial.",
        ])
    (RECEIPT / "recipe-comparison.json").write_text(json.dumps(report, indent=1, default=float) + "\n")
    write_markdown(report)
    print(f"wrote {RECEIPT / 'recipe-comparison.json'} and {OUT / 'recipe-comparison.md'} "
          f"({report['runtime_s']}s)")


def pct(bps):
    return "n/a" if bps is None else f"{bps / 100:+.1f}%"


def write_markdown(rep):
    s = rep["summary"]
    md = [f"# Matched recipe comparison (cash path, formal simulator)\n",
          f"Generated {rep['generated']}. `python3 sim/recipe_comparison.py --seeds {rep['seeds']} "
          f"--grid {rep['grid']}`. Pinned block {rep['pin']['block']:,}; {rep['seeds']} seeds per "
          "sampled cell (zero-demand is deterministic, 1 seed). Every recipe runs through "
          "`sim/formal.py`/`sim/forward.run` (the `sim/vault.py` PackVault mirror + `keeper/policy.py` "
          "decisions) with the full cash path and a complete holder exit; matched capital, demand "
          "history, purchaser pool, gas and seeds. Return is net realized cash / paid-in after one "
          "operating year; the 10% annual net hurdle is the minimum gate. FWA tokens valued at zero.\n",
          f"Window: {rep['window']['successful']} successful acquisitions in 30 days "
          f"({rep['window']['successful_per_day']:.0f}/day); purchaser responses "
          f"{rep['window']['purchaser_responses']}. Live FWA at the pin: settlement discount "
          f"{rep['live_fwa']['settlement_discount_bps']}, token discount "
          f"{rep['live_fwa']['token_settlement_discount_bps']}, acceptBidAsTokens "
          f"{rep['live_fwa']['accept_bid_as_tokens_enabled']} (best bid = token bid, so it counts).\n"]

    # Backing / build-gate table
    md += ["## Backing and build gate (analytic, 0.5 gwei ceiling, 2 gwei purchaser gas)\n",
           "| recipe | P | backing B | B/P | lists | keep adv. | creator fee/pack | build cost | build net | rebuilds after keep |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for rk, b in rep["backing_by_gps_gwei"][2].items():
        md.append(f"| {b['name']} | {b['P_eth']:.2f} | {b['backing_eth']:.5f} | {b['ratio']} | "
                  f"{'yes' if b['lists'] else 'NO'} | {b['keep_advantage_eth']*1e3:+.2f} mETH | "
                  f"{b['creator_fee_per_pack_eth']*1e3:.2f} mETH | {b['build_cost_eth']*1e3:.2f} mETH | "
                  f"{b['build_net_eth']*1e3:.2f} mETH | {'yes' if b['can_rebuild'] else 'NO'} |")
    md.append("\n`build net < build cost` (rebuilds = NO) means a kept pack cannot be profitably "
              "replaced, so inventory depletes to zero and the account stops earning.\n")

    # Per-scenario decision tables
    def table(title, pred, cols_extra=True):
        rows = [v for v in s.values() if pred(v)]
        rows.sort(key=lambda v: (v["label"], v["behaviour"], v["keep_p"], v["rkey"]))
        md.append(f"## {title}\n")
        head = ("| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | "
                "<10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | "
                "builds | mint# | util | min free |")
        md.append(head)
        md.append("|" + "---|" * 19)
        for v in rows:
            beh = v["behaviour"] if v["behaviour"] not in ("fixed",) else f"keep {v['keep_p']}"
            md.append(
                f"| {RECIPES[v['rkey']]['name']} | {v['principal_eth']:.2f} | {beh} | "
                f"{pct(v['mean_bps'])} | {pct(v['median_bps'])} | {pct(v['p5_bps'])} | "
                f"{pct(v['p10_bps'])} | {pct(v['worst_bps'])} | {100*v['loss_frac']:.0f}% | "
                f"{v['below_hurdle_runs']}/{v['runs']} | {v['creator_per_eth_yr']:.3f} | "
                f"{v['mean_creator_mint_eth']:.4f} | {v['mean_fees_eth']:.4f} | {v['mean_keeper_eth']:.4f} | "
                f"{v['mean_selections']:.0f} | {v['mean_builds']:.0f} | {v['mean_mint_count']:.0f} | "
                f"{v['mean_util']:.2f} | {v['mean_min_free_eth']:.4f} |")
        md.append("")

    table("Canary 1.96 ETH, by behaviour", lambda v: v["label"] == "1.96ETH" and v["price"] == 0.5
          and v["kind"] == "base" and v["gps"] == 2 and v["behaviour"] in ("allbid", "value", "observed"))
    table("20 ETH, by behaviour", lambda v: v["label"] == "20ETH" and v["kind"] == "base"
          and v["behaviour"] in ("allbid", "value", "observed"))
    table("Capacity curve (6.8 and 50 ETH)", lambda v: v["label"] in ("6.8ETH", "50ETH")
          and v["kind"] == "base")
    if rep["grid"] in ("full", "focused"):
        table("Fixed keep-rate (50%) and keep sweep", lambda v: v["behaviour"] == "fixed"
              and v["kind"] == "base")
        table("Stress: quieter (last 10 days) and zero demand",
              lambda v: v["kind"] in ("recent10", "zero"))
        table("Low gas (0.2 gwei), value-aware",
              lambda v: v["price"] == 0.2)
        # PURCHASER_GAS_PRICE sensitivity
        md += ["## Purchaser-gas-price sensitivity (1 / 2 / 3 gwei), 1.96 ETH value-aware\n",
               "Backing (analytic) and simulated return per recipe.\n",
               "| recipe | gwei | backing | B/P | keep adv. | lists | mean | median | loss% |",
               "|---|---|---|---|---|---|---|---|---|"]
        for gps in (1, 2, 3):
            for rk in RECIPES:
                b = rep["backing_by_gps_gwei"][gps][rk]
                cell = next((v for v in s.values() if v["rkey"] == rk and v["gps"] == gps
                             and v["label"] == "1.96ETH" and v["behaviour"] == "value"
                             and v["kind"] == "base"), None)
                mean = pct(cell["mean_bps"]) if cell else "n/a"
                median = pct(cell["median_bps"]) if cell else "n/a"
                loss = f"{100*cell['loss_frac']:.0f}%" if cell else "n/a"
                md.append(f"| {b['name']} | {gps} | {b['backing_eth']:.5f} | {b['ratio']} | "
                          f"{b['keep_advantage_eth']*1e3:+.2f} mETH | {'yes' if b['lists'] else 'NO'} | "
                          f"{mean} | {median} | {loss} |")
        md.append("")
    (OUT / "recipe-comparison.md").write_text("\n".join(md) + "\n")


if __name__ == "__main__":
    main()
