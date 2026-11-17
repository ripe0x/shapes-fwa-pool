#!/usr/bin/env python3
"""Economics of PackVault, four ways, kept apart in the output (sim/out/forward.md):

1. Expectation: closed form per bid cycle, B (k - 1) less cycle gas, times cycles per year.
2. Backtest: FWA's real acquisition history replayed with a vault of n listings inserted. Every
   real acquisition's fee, total weight and active count come from the event log; the vault's
   presence changes the harmonic backing (so the fee) and the selection odds exactly as FWA's
   formulas do. Selections are drawn per acquisition.
3. Forward simulation: a year, day by day, with the vault's cash flows from sim/vault.py (the
   model reconciled to a fork run to the wei, sim/reconcile.py) and every keeper decision from
   keeper/policy.py (the live keeper's rules). FWA's pool is the live snapshot; volume, gas,
   protocol settings, purchaser behaviour and holder flows vary by scenario.
4. Realized performance: none. Nothing is deployed.

FWA mechanics (validated exactly by sim/replay.py against every historical EarningsAccrued):
fee per acquisition F = (1 + surcharge) x harmonic-mean backing; F (1 - cut)(1 - crown) split
equally over active listings; selection odds proportional to 1 / backing. FWA tokens are zero.
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "keeper"))
import policy  # noqa: E402
from vault import ACTIVE, ALLOCATED, SETTLED, WITHDRAWN, Vault  # noqa: E402

DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
E = 10**18
GWEI = 10**9
P = 3 * 10**16
SUR, CUT, S_FEE, BID_RATE = 0.05, 0.01, 0.01, 0.90
ASK, PREMIUM = 0.033, 0.10
MINT_FEE = 10**15
DAY = 86_400
WORK_FEE = 2 * 10**13  # wei per unit of work, canary value (D55)
CEILING = 0.5  # gwei: canary gasCeiling; above it the keeper waits (D45, D51)
ESSENTIAL_CEILING = 2.0  # gwei: canary essentialCeiling (redemption and wind-down work)


# ---------------------------------------------------------------- history


def history():
    """Per-acquisition arrays from the event log: time, fee, total weight (sum of 1/B in 1/ETH),
    active listing count, protocol cut and crown share in force."""
    cache = OUT / "acq_history.npz"
    if cache.exists():
        return dict(np.load(cache))
    db = sqlite3.connect(DB)
    n_active, cut, crown = 0, 100, 500
    rows = []
    q = ("SELECT ts, event, args FROM logs WHERE event IN ('ListingRewardActivated','ListingRewardRemoved',"
         "'AcquisitionRequested','ConfigSet') ORDER BY block, log_index")
    for ts, ev, a in db.execute(q):
        if ev == "ListingRewardActivated":
            n_active += 1
        elif ev == "ListingRewardRemoved":
            n_active -= 1
        elif ev == "ConfigSet":
            a = json.loads(a)
            if a["key"] == "18":
                cut = int(a["value"])
            elif a["key"] == "15":
                crown = int(a["value"])
        else:
            a = json.loads(a)
            rows.append((ts, int(a["acquisitionFee"]) / E, int(a["totalWeight"]) / E, n_active, cut, crown))
    h = {k: np.array(v) for k, v in zip(("ts", "fee", "w", "n", "cut", "crown"), zip(*rows))}
    np.savez(cache, **h)
    return h


def pool_snapshot():
    """Backings (ETH) of listings active at the end of the ingested history."""
    db = sqlite3.connect(DB)
    value = {}
    for ev, a in db.execute("SELECT event, args FROM logs WHERE event IN ('NFTListed','BackingUpdated',"
                            "'NFTAllocated','ListingWithdrawn','ListingKicked') ORDER BY block, log_index"):
        a = json.loads(a)
        lid = int(a["listingId"])
        if ev == "NFTListed":
            value[lid] = int(a["value"]) / E
        elif ev == "BackingUpdated" and lid in value:
            value[lid] = int(a["newBacking"]) / E
        else:
            value.pop(lid, None)
    return np.array(list(value.values()))


def daily_volume(h):
    days = (h["ts"] // DAY).astype(int)
    first, last = days.min(), days.max()
    return np.bincount(days - first, minlength=last - first + 1).astype(float), first


# ---------------------------------------------------------------- 1. expectation


def k_of(crown=0.001, cut=CUT, sur=SUR):
    return (1 + sur) * (1 - cut) * (1 - crown)


def expectation(n, volume, gwei, B=0.0363, crown=0.001, premium=0.0):
    pool = POOL
    W = np.sum(1 / pool) + n / B
    cycles = 365 * volume * (1 / B) / W
    # A bid cycle's keeper pay as the vault quotes it (D56): quoted gas at basefee + 0.05 gwei tip,
    # capped at the ceiling (V1: no premium), plus two work units (resolve and relist).
    gas = policy.CYCLE_GAS * min(gwei + 0.05, CEILING) * 1e-9 * (1 + premium) + 2 * WORK_FEE / E
    net = B * (k_of(crown) - 1) - gas
    capital = n * (B + P / E)
    return dict(cycle_days=365 / cycles, net_meth=net * 1e3, apr=cycles * net / (B + P / E),
                share=(n / B) / W, capital=capital)


# ---------------------------------------------------------------- 2. backtest


def backtest(h, n, gwei, t0, t1, B=0.0363, runs=400, seed=1, premium=0.0):
    """Vault of n listings at backing B inside the real history between t0 and t1 (unix s).
    Positions are relisted the same day after a bid outcome (cycle gas charged per selection)."""
    m = (h["ts"] >= t0) & (h["ts"] < t1)
    fee, w, N, cut, crown = h["fee"][m], h["w"][m], h["n"][m], h["cut"][m] / 1e4, h["crown"][m] / 1e4
    if len(fee) == 0:
        return None
    k_hist = (1 + SUR) * (1 - cut) * (1 - crown)
    H, H2 = N / w, (N + n) / (w + n / B)
    fee2 = fee * H2 / H  # the vault's listings move the harmonic backing, so the fee
    vault_fees = fee2 * (1 - cut) * (1 - crown) * n / (N + n)
    p_sel = (n / B) / (w + n / B)
    cycle_cost = B + policy.CYCLE_GAS * min(gwei + 0.05, CEILING) * 1e-9 * (1 + premium) + 2 * WORK_FEE / E
    days = (t1 - t0) / DAY
    capital = n * (B + P / E)
    exp_pnl = vault_fees.sum() - p_sel.sum() * cycle_cost
    rng = np.random.default_rng(seed)
    sel = (rng.random((runs, len(p_sel))) < p_sel).sum(axis=1)
    pnl = vault_fees.sum() - sel * cycle_cost
    ann = pnl / capital * 365 / days
    return dict(days=days, acq=len(fee), per_day=len(fee) / days, k=float(np.mean(k_hist)),
                exp_apr=exp_pnl / capital * 365 / days, p5=np.percentile(ann, 5), p50=np.median(ann),
                p95=np.percentile(ann, 95), ploss=float(np.mean(pnl < 0)), selections=float(p_sel.sum()))


# ---------------------------------------------------------------- 3. forward simulation


class Scenario(dict):
    """volume(day, rng) -> acquisitions; gas gwei; crown/ask changes by day; keep rate;
    elasticity; checkpoint miss rate; holder flows."""


def charge_state(gas, open_positions, pool=0):
    """Minimal policy state for the request charges at `gas` wei basefee (canary parameters)."""
    return policy.State(now=0, gas_price=gas, base_fee=gas, gas_ceiling=int(CEILING * GWEI), max_tip=5 * 10**7,
                        markup_bps=0, share_bps=2_500, k=0, backing=0, min_edge_bps=100, mint_fee=MINT_FEE,
                        settlement_window=0, blackout=False, queue_drained=True, checkpoint_done_this_interval=False,
                        open_positions=open_positions, work_fee=WORK_FEE,
                        essential_ceiling=int(ESSENTIAL_CEILING * GWEI), processing_pool=pool)


def run(sc, n_target, seed, days=365):
    rng = np.random.default_rng(seed)
    others = POOL
    if sc.get("pool_scale", 1.0) != 1.0:
        others = rng.choice(POOL, int(len(POOL) * sc["pool_scale"]))
    W_o, N_o = float(np.sum(1 / others)), len(others)
    g_of = sc.get("gwei", 0.15)  # gwei, or a function of the day (gas changing after deployment)
    deposit = int((n_target * (0.0363 + 0.03) + 0.06 + 0.11) * E)  # positions + mint room + slack
    v = Vault(seed=10**16, balance=10**16, reserve=9 * 10**15)  # policy.reserve_need at 300 positions, 0.5 gwei (D46)
    g0 = g_of(0) if callable(g_of) else g_of
    st0 = charge_state(int(g0 * GWEI), 0)
    ck0 = policy.request_charge(st0)
    d0 = policy.deploy_charge(st0)
    v.deposit("h", deposit, ck0, deposit * d0 // (policy.POSITION_VALUE + d0))  # D56 request charges
    paid_in = deposit + ck0  # every wei the holder sent
    nav0_per_share = None
    next_id = 0
    credit = 0  # FWA fee credit owed to the vault
    keeper_unpaid = 0  # gas keepers spent on calls the vault does not pay
    allocated_day = {}
    ask, crown = ASK, 0.001
    vol_hist = []
    checkpoints = 0
    accrued = selected = 0
    missed_alloc = 0  # model check: accrued / (selected x B) must approach k
    open_days = []
    for d in range(days):
        gas = int((g_of(d) if callable(g_of) else g_of) * GWEI)
        for (day, key, val) in sc.get("changes", []):
            if day == d:
                if key == "crown":
                    crown = val
                elif key == "ask":
                    ask = val
                    cap = int(ask * (1 + PREMIUM) * E)
                    for i, p in list(v.positions.items()):
                        if p.status == ACTIVE and p.backing > cap:
                            v.kicked(i)  # anyone may kick it in the next blackout
        cap = int(ask * (1 + PREMIUM) * E)
        k = int(k_of(crown) * E)
        backing = cap if (k >= E + 100 * 10**14 and cap * (k - S_FEE * 1e4 * 10**14) >= P * E) else 0

        # Purchasers resolve yesterday's allocations: bid unless they keep (vault prefers keep).
        for i, d0 in list(allocated_day.items()):
            if d >= d0 + 1:
                del allocated_day[i]
                if rng.random() < sc.get("keep", 0.0):
                    v.resolve_keep(i)
                else:
                    v.bid_settled(i)

        # FWA acquisitions today.
        act = [i for i, p in v.positions.items() if p.status == ACTIVE]
        n = len(act)
        Bv = backing or cap
        W = W_o + (n / (Bv / E) if n else 0)
        share = (n / (Bv / E)) / W if n else 0
        vol = sc["volume"](d, rng) * max(0.0, 1 - sc.get("elasticity", 0) * share)
        A = rng.poisson(vol) if vol > 0 else 0
        vol_hist.append(A)
        if n and A:
            H = (N_o + n) / W
            per_listing = int((1 + SUR) * H * (1 - CUT) * (1 - crown) / (N_o + n) * E)
            # Each listing is selected at most once: its odds over the day are 1 - (1 - q)^A with
            # q = (1/B) / W per acquisition. (Drawing Binomial(A, n q) over-selects by (A-1) q / 2.)
            q = (1 / (Bv / E)) / W
            p_day = 1 - (1 - q) ** A
            hit = rng.random(n) < p_day
            chosen = {i for i, h_ in zip(act, hit) if h_}
            sel = len(chosen)
            # A selected listing earned one share per acquisition up to and including the one
            # that picked it: E[N | N <= A] for N ~ Geometric(q). About (A + 1) / 2 on a quiet
            # day, about 1 / q on a day busy enough that most listings get picked.
            before_sel = int(per_listing * (1 / q - A * (1 - q) ** A / p_day))
            selected += sel
            accrued += per_listing * A * (n - sel) + before_sel * sel
            for i in act:
                p = v.positions[i]
                if i in chosen:  # selected mid-day: fees up to and including that acquisition
                    credit += p.pending_fees + before_sel
                    p.pending_fees = 0
                    p.status = ALLOCATED
                    allocated_day[i] = d
                else:
                    p.pending_fees += per_listing * A

        # Keeper passes: repeat in the open interval until nothing is left to resolve or deploy
        # (a live keeper loops), then one pass in the blackout, which may host a checkpoint
        # unless FWA's queue is busy.
        blackout_ok = rng.random() >= sc.get("checkpoint_miss", 0.0)
        recent = float(np.mean(vol_hist[-7:]))
        passes = 0
        # Congestion: inclusion needs a priority fee above the reimbursed maxTip, so a keeper
        # that is not subsidized does nothing that day.
        step = 2 if sc.get("congested") and sc["congested"](d) else 0
        open_days.append(len(v.positions))
        while step < 2:
            passes += 1
            listings = [policy.Listing(i, p.status, allocated_at=0, pending_fees=p.pending_fees)
                        for i, p in v.positions.items()]
            # The simulator settles allocations at day granularity: nothing waits on the window.
            st = policy.State(
                now=d * DAY, gas_price=gas, base_fee=gas, gas_ceiling=int(CEILING * GWEI), max_tip=5 * 10**7,
                markup_bps=0, share_bps=2_500, k=k, backing=backing, min_edge_bps=100, mint_fee=MINT_FEE,
                settlement_window=10**12, blackout=(step == 1), queue_drained=blackout_ok or step == 0,
                checkpoint_done_this_interval=False, listings=listings, idle_packs=len(v.idle_packs),
                loose_shapes=v.loose_shapes, free=v.free(), idle_eth=v.idle(), owed_estimate=v.owed_estimate(),
                pending_deposits=v.pending_total, locked_shares=v.locked_shares, fee_credit=credit,
                open_positions=len(v.positions), max_positions=300, recent_volume=recent, work_fee=WORK_FEE,
                slowdown_volume=sc.get("slowdown", 0.0), essential_ceiling=int(ESSENTIAL_CEILING * GWEI),
                processing_pool=v.processing_pool)
            planned = policy.plan(st)
            if step == 1:
                step = 2
            elif passes >= 40 or not any(a[0] in ("sync", "list", "restock") for a in planned):
                step = 1
            for act_ in planned:
                fn = act_[0]
                q = lambda g, u=0, e=False: policy.quote(st, g, u, e)  # noqa: E731  envelope (gates)
                pv = lambda g, u=0, e=False: policy.pay_v1(st, g, u, e)  # noqa: E731  V1 pay
                Q = policy.Q
                ess = v.locked_shares != 0  # redemption work: no premium, essential budget (D56)
                if fn == "sync":
                    for i in act_[1]:
                        p = v.positions[i]
                        if p.status in (SETTLED, WITHDRAWN) and p.pack_owned:
                            v.sync_owned(i)
                    n_ = len(act_[1])
                    v.pay_keeper(pv(Q["sync"] + Q["synced"] * n_, n_, ess))
                elif fn == "harvest":
                    amt = credit + sum(v.positions[i].pending_fees for i in act_[1])
                    for i in act_[1]:
                        v.positions[i].pending_fees = 0
                    credit = 0
                    v.receive_fees(amt)
                    g = q(Q["harvest"] + Q["harvested"] * len(act_[1]))
                    if g * 10_000 <= amt * 2_500:  # gate on the envelope, pay the policy
                        v.pay_keeper(pv(Q["harvest"] + Q["harvested"] * len(act_[1])))
                    else:
                        keeper_unpaid += g
                elif fn == "unlist":
                    for i in act_[1]:
                        p = v.positions[i]
                        credit += p.pending_fees
                        v.unlist(i)
                    n_ = len(act_[1])
                    v.pay_keeper(pv(Q["unlist"] + Q["unlisted"] * n_, n_, True))
                elif fn == "liquidate":
                    m = 0
                    while m < act_[1] and (v.idle_packs or v.loose_shapes) and \
                            (v.owed_estimate() > v.free() + v.pending_total):
                        v.liquidate_one()
                        m += 1
                    if m:
                        v.pay_keeper(pv(Q["liquidate"] + Q["liq_pack"] * m, m, True))
                elif fn == "checkpoint":
                    nav_pos = v.nav_positions()[0]
                    pool = v.processing_pool
                    flows = v.pending_total != 0 or v.locked_shares != 0
                    try:
                        paid = v.checkpoint(credit)
                    except RuntimeError:  # AllocatedExposure: the contract reverts; retry next blackout
                        missed_alloc += 1
                        continue
                    credit = 0
                    checkpoints += 1
                    g = pv(Q["checkpoint"] + Q["checkpoint_pos"] * len(v.positions), 1, True)
                    if paid:
                        v.pay_keeper(min(g, pool) if flows else g)  # flows: paid from the request charges
                    if nav0_per_share is None:
                        nav0_per_share = v.last_nav * E // v.total_shares
                    del nav_pos
                elif fn == "restock":
                    if v.idle() >= act_[1] * backing:
                        mints = v.restock(act_[1], 3, MINT_FEE)
                        v.pay_keeper(pv(Q["restock"] + Q["pack"] * act_[1] + Q["mint"] * mints, act_[1]))
                elif fn == "list":
                    m = 0
                    while m < act_[1] and v.idle_packs and v.idle() >= backing:
                        v.list(next_id, backing)
                        next_id += 1
                        m += 1
                    if m:
                        v.pay_keeper(pv(Q["list"] + Q["listed"] * m, m))
        # Holder flows by scenario.
        for (day, frac) in sc.get("redeem", []):
            if day == d:
                sh = v.share_balance("h") * frac // 1
                st1 = charge_state(gas, len(v.positions), v.processing_pool)
                ck = policy.request_charge(st1)
                unwind = (sh * v.last_nav // v.total_shares) * policy.unwind_charge(st1) // policy.POSITION_VALUE
                v.request_redeem("h", sh, ck, unwind)
                paid_in += ck + unwind
    end_nav = v.nav_now() + credit
    supply = v.total_shares
    # Holder's value: shares at end NAV plus anything already redeemed or claimable.
    # Escrowed deposits (never priced, e.g. no keeper ran) stay cancellable at face value.
    d_ = v.pending.get("h", [0, 0])
    unpriced = d_[0] if d_[1] >= v.epoch else 0  # priced deposits already count as shares
    claimed = v.claimable.get("h", 0) + v.redemption_reserve + unpriced
    holder = v.share_balance("h") * end_nav // supply + claimed
    locked_val = v.locked_shares * end_nav // supply
    value_end = holder + locked_val
    ret = value_end / paid_in - 1
    deployed = sum(p.backing + p.units * 10**16 for p in v.positions.values())
    return dict(ret=ret * 365 / days, keeper=v.keeper_paid / deposit, mint=v.mint_fees / deposit,
                fees=v.fees_received / deposit, lost=v.backing_lost / deposit, util=deployed / max(1, end_nav),
                positions=len(v.positions), pos_mean=float(np.mean(open_days)), pos_max=max(open_days),
                checkpoints=checkpoints,
                k_eff=accrued / max(1, selected * 0.0363 * E), missed_alloc=missed_alloc, keeper_unpaid=keeper_unpaid / deposit,
                vol=float(np.mean(vol_hist)))


def wilson(k, n, z=1.96):
    """95% interval for a proportion k / n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    c = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    m = (p + z * z / (2 * n)) / (1 + z * z / n)
    return (max(0.0, m - c), min(1.0, m + c))


def summarize(sc, n, runs, days=365):
    rs = [run(sc, n, seed) for seed in range(runs)]
    r = np.array([x["ret"] for x in rs])
    mean = {k: float(np.mean([x[k] for x in rs])) for k in rs[0]}
    k = int(np.sum(r < 0))
    lo, hi = wilson(k, len(r))
    return dict(mean=float(r.mean()), se=float(r.std() / np.sqrt(len(r))), p5=float(np.percentile(r, 5)),
                p50=float(np.median(r)), p95=float(np.percentile(r, 95)), ploss=k / len(r), ploss_lo=lo, ploss_hi=hi,
                runs=len(r), worst=float(r.min()), **{f"m_{k_}": v for k_, v in mean.items()})


# ---------------------------------------------------------------- scenarios


def boot(series):
    s = np.asarray(series, float)
    return lambda d, rng: float(rng.choice(s))


def const(x):
    return lambda d, rng: x


def decline(start, end, days=365):
    return lambda d, rng: start * (end / start) ** (d / days)


def stop_after(series, day):
    b = boot(series)
    return lambda d, rng: b(d, rng) if d < day else 0.0


def pct(x):
    return f"{100 * x:+.1f}%"


def successful_daily():
    """Acquisitions per UTC day that reached a selection (fees were distributed). Requests that
    were refunded or expired distributed nothing (sim/backtest_audit.py)."""
    import backtest_audit
    sel = backtest_audit.load()["sel"]
    days = (sel[:, 0] // DAY).astype(int)
    return np.bincount(days - days.min()).astype(float), int(days.min())


def ci(s):
    return f"{100 * s['ploss']:.0f}% [{100 * s['ploss_lo']:.0f}-{100 * s['ploss_hi']:.0f}]"


def main():
    global POOL
    OUT.mkdir(exist_ok=True)
    POOL = pool_snapshot()
    vol, first = successful_daily()
    last30, last14, last7 = vol[-30:], vol[-14:], vol[-7:]
    spike = int(np.argmax(last30))
    last30_ex = np.delete(last30, spike)
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 400
    md = ["# PackVault economics: gate, expectation, forward simulation\n",
          "Generated by `python3 sim/forward.py " + str(runs) + "`. Data: `sim/data/fwa.sqlite`, FWA, rewards and oracle "
          "events through block 26,425,500 (`python3 sim/ingest.py`); pool snapshot at the end of that history; "
          "volume = acquisitions per UTC day that reached a selection (refunded requests distributed no fees). "
          "The historical replay and its reconciliation with these numbers are in `sim/out/backtest_audit.md`.\n",
          f"Pool: {len(POOL):,} listings, harmonic backing {len(POOL) / np.sum(1 / POOL):.4f} ETH. Successful acquisitions "
          f"per day: last 7 d {last7.mean():.0f}, last 14 d {last14.mean():.0f}, last 30 d {last30.mean():.0f} "
          f"({last30_ex.mean():.0f} without the {last30.max():.0f} of Oct 31), 30-day median {np.median(last30):.0f}.",
          "Vault: 3-unit packs (P = 0.03 ETH) at the 0.0363 cap; k = 1.0385; keeper pay V1 (quoted gas + work fee, no premium); maxTip 0.05 gwei; "
          f"gas ceiling {CEILING} gwei; FWA tokens at zero; purchasers take the bid unless stated (keeps pay the vault more).\n"]

    # 1. The formal gate, as approved: trailing 30-day volume, tokens at zero.
    md += ["## 1. Formal economic gate (owner's definition)\n",
           f"Gate: 10%/yr net of gas at trailing-30-day volume, tokens at zero, at the {CEILING} gwei gas ceiling (D42); "
           "bid outcome positive at the ceiling; a usable exit window each day. 0.15 gwei is spot at the pinned block. "
           "Above the ceiling the keeper waits; calls are still accepted, paid at the ceiling price (D51).\n",
           "| gas | net per bid cycle (mETH) | closed form, 100 positions | forward sim mean, 100 positions | passes 10%? |",
           "|---|---|---|---|---|"]
    gate = {}
    for g in (0.15, CEILING):
        x = expectation(100, last30.mean(), g)
        sm = summarize(Scenario(volume=boot(last30), gwei=g), 100, runs)
        gate[g] = (x, sm)
        md.append(f"| {g} gwei | {x['net_meth']:+.3f} | {pct(x['apr'])} | {pct(sm['mean'])} (p5 {pct(sm['p5'])}) | "
                  f"{'yes' if x['apr'] >= 0.10 else 'no'} (closed form); {'yes' if sm['mean'] >= 0.10 else 'no'} (sim) |")
        print(md[-1], flush=True)
    md.append(f"\nBid outcome at the {CEILING} gwei ceiling: {gate[CEILING][0]['net_meth']:+.3f} mETH per cycle. New packs "
              "need a quoted price below ~0.52 gwei (one bid cycle must repay the build); the closed form assumes positions already "
              "exist. Exit windows: 59 of the last 60 blackouts had a drained queue (Phase 0.2).\n")

    md += ["## 2. Expectation (closed form, per position, no variance)\n",
           "| volume/day | gas gwei | positions | cycle days | net per cycle mETH | APR | selection share |",
           "|---|---|---|---|---|---|---|"]
    for v_ in (15, last7.mean(), last30_ex.mean(), last30.mean()):
        for g in (0.15, CEILING, 1.0):
            for n in (30, 300):
                x = expectation(n, v_, g)
                md.append(f"| {v_:.0f} | {g} | {n} | {x['cycle_days']:.1f} | {x['net_meth']:+.3f} | {pct(x['apr'])} | "
                          f"{100 * x['share']:.1f}% |")
    gross = 0.0363 * (k_of() - 1)
    fee = WORK_FEE / E
    build_g = policy.Q["pack"] + policy.Q["mint"] * 3 // 10 + policy.Q["listed"]
    md.append(f"\nBreak-even quoted price for a bid cycle (D56: quoted gas {policy.CYCLE_GAS:,} = resolve 75k + relist 530k "
              f"+ harvest share 15k, + 2 work fees; V1 pays no markup): {(gross - 2 * fee) / policy.CYCLE_GAS * 1e9:.2f} gwei. "
              f"New packs (build {build_g:,} quoted gas, mint fee share 0.0003 ETH and one more work fee on top): "
              f"below {(gross - 0.0003 - 3 * fee) / (policy.CYCLE_GAS + build_g) * 1e9:.2f} gwei quoted price "
              "(basefee + 0.05 gwei tip).\n")

    def g_path(base, high, start, stop=10**9):
        return lambda d: high if start <= d < stop else base

    def cheap_windows(base, cheap, every):
        return lambda d: cheap if d % every == 0 else base

    scen = [
        ("trailing 30 d (gate window)", dict(volume=boot(last30), gwei=0.15), (30, 100, 300)),
        ("trailing 30 d without Oct 31", dict(volume=boot(last30_ex), gwei=0.15), (100,)),
        ("last 14 d", dict(volume=boot(last14), gwei=0.15), (30, 100, 300)),
        ("last 7 d", dict(volume=boot(last7), gwei=0.15), (100,)),
        ("15/day", dict(volume=const(15), gwei=0.15), (100,)),
        ("decline 97 -> 10/day over the year", dict(volume=decline(97, 10), gwei=0.15), (100,)),
        ("inactive after 60 days", dict(volume=stop_after(last14, 60), gwei=0.15), (100,)),
        ("last 14 d at the 0.5 gwei ceiling", dict(volume=boot(last14), gwei=0.5), (100,)),
        ("enter at 0.15 gwei, 0.4 gwei from day 30 on", dict(volume=boot(last14), gwei=g_path(0.15, 0.4, 30)), (100,)),
        ("enter at 0.15 gwei, 1.0 gwei (above ceiling) from day 30 on", dict(volume=boot(last14), gwei=g_path(0.15, 1.0, 30)), (100,)),
        ("enter at 0.15 gwei, 2.0 gwei (above ceiling) days 30-120", dict(volume=boot(last14), gwei=g_path(0.15, 2.0, 30, 120)), (100,)),
        ("1.2 gwei with a 0.1 gwei day every 7", dict(volume=boot(last14), gwei=cheap_windows(1.2, 0.1, 7)), (100,)),
        ("50% redemption at day 120 during 7 congested days", dict(volume=boot(last14), gwei=0.15, redeem=[(120, 0.5)],
                                                                    congested=lambda d: 120 <= d < 127), (100,)),
        ("50% redemption at day 120", dict(volume=boot(last14), gwei=0.15, redeem=[(120, 0.5)]), (100,)),
        ("crown share to 5% at day 90", dict(volume=boot(last14), gwei=0.15, changes=[(90, "crown", 0.05)]), (100,)),
        ("ask cut 0.033 -> 0.0275 at day 90", dict(volume=boot(last14), gwei=0.15, changes=[(90, "ask", 0.0275)]), (100,)),
        ("11% of purchasers keep", dict(volume=boot(last14), gwei=0.15, keep=0.11), (100,)),
        ("demand elasticity 1", dict(volume=boot(last14), gwei=0.15, elasticity=1.0), (100,)),
        ("pool shrinks to half", dict(volume=boot(last14), gwei=0.15, pool_scale=0.5), (100,)),
        ("half of checkpoints missed", dict(volume=boot(last14), gwei=0.15, checkpoint_miss=0.5), (100,)),
    ]
    md += ["## 3. Forward simulation (one year, daily, reconciled vault model + live keeper policy)\n",
           f"{runs} runs per row. One year, so the raw return is the annual return. Every expense is included: keeper gas "
           "pay, mint fees, FWA settlement fees, backing lost to purchasers. The simulation holds real cash: a relist "
           "needs backing the vault has, a pack waits for its purchaser's settlement, and redemptions are paid before "
           "anything is redeployed. Positions: the initial target / mean held / most held (cap 300; NAV growth can "
           "add positions). P(loss) with a 95% interval.\n",
           "| scenario | positions (target/mean/max) | mean (± s.e.) | p5 | median | p95 | worst run | P(loss) | fees/dep | "
           "lost/dep | keeper/dep | mint/dep |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    results = {}
    for name, sc, sizes in scen:
        for n in sizes:
            sm = summarize(Scenario(sc), n, runs)
            results[f"{name}|{n}"] = sm
            md.append(f"| {name} | {n}/{sm['m_pos_mean']:.0f}/{sm['m_pos_max']:.0f} | {pct(sm['mean'])} ± {100 * sm['se']:.1f} | "
                      f"{pct(sm['p5'])} | {pct(sm['p50'])} | {pct(sm['p95'])} | {pct(sm['worst'])} | {ci(sm)} | "
                      f"{100 * sm['m_fees']:.0f}% | {100 * sm['m_lost']:.0f}% | {100 * sm['m_keeper']:.2f}% | "
                      f"{100 * sm['m_mint']:.2f}% |")
            print(md[-1], flush=True)

    md += ["\n## 4. Deployment slowdown (keeper stops building new packs while 7-day volume is low)\n",
           "| scenario | slowdown below | mean | p5 | P(loss) | mint/dep | keeper/dep |", "|---|---|---|---|---|---|---|"]
    for name, sc in (("decline 97 -> 10/day", dict(volume=decline(97, 10), gwei=0.15)),
                     ("inactive after 60 days", dict(volume=stop_after(last14, 60), gwei=0.15))):
        for sl in (0, 30, 60):
            sm = summarize(Scenario({**sc, "slowdown": sl}), 100, runs)
            md.append(f"| {name} | {sl}/day | {pct(sm['mean'])} | {pct(sm['p5'])} | {ci(sm)} | "
                      f"{100 * sm['m_mint']:.2f}% | {100 * sm['m_keeper']:.2f}% |")
            print(md[-1], flush=True)

    md += ["\n## 5. FWA tokens (burned, never sold; D43)\n",
           "Holders get no token value by design: the vault claims FWA token rewards and burns them, at the operator's gas cost (`burnTokens`, unpaid). Measured in `keeper/rehearse_canary.py`: one real buyback paid the canary's 28 listings 4.87 FWA tokens (a pool sale would have realized about 8.2e12 wei), all claimed and burned.\n"]
    (OUT / "forward.md").write_text("\n".join(md) + "\n")
    json.dump(results, open(OUT / "forward.json", "w"), indent=1)
    print("wrote sim/out/forward.md")


if __name__ == "__main__":
    main()
