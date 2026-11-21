#!/usr/bin/env python3
"""Unified economic study of the redesigned FWA Shape-pack strategy.

One strategy, run in independent accounts that all list on the same FWA V2 main pool:
  - a pooled PackVault (multi-depositor shares, one reserve, request-funded checkpoints), and
  - personal PackManagers (one owner, ERC-1167 clones, own reserve/budget/keeper pay, no checkpoints).

The engine is event-driven over the REAL trailing-30-day acquisition history (sim/forward.py
history(), validated by sim/replay.py), tiled to a year. Every own listing's fee share and
selection odds are computed from FWA's formulas with ALL our accounts' listings inserted into the
shared pool, exactly as sim/forward.py.backtest() does (the shared-market externality). Tokens are
valued at zero.

FWA mechanics (mirror of forward.backtest + VaultLib):
  F = (1+surcharge) x harmonic-mean backing;  F(1-cut)(1-crown) split EVENLY over active listings;
  selection odds proportional to 1/B. Inserting our listings (total weight Wn=sum n_a/B_a, total
  count Ntot=sum n_a) raises the harmonic mean (so F) and dilutes the per-listing split. Algebra:
  our per-listing fee share for acquisition i collapses to
      fee_i * (1-cut_i)(1-crown_i) * w_i / (N_i * (w_i + Wn))
  (Ntot cancels; the count dilution and the harmonic lift offset), and our per-listing selection
  probability is (1/B) / (w_i + Wn).

Per selection (VaultLib.edge / vault.py):
  - KEEP  (purchaser keeps the pack, or silent reclaim-backing when B(1-s) >= P): account gets
          B(1-s) cash, pack is GONE -> a replacement needs a fresh build (new primary mint fees).
  - BID   (purchaser takes FWA's best bid d*B): account keeps the pack, LOSES the whole backing B,
          relists the pack with fresh backing, NO mint.
The keep-incentive backing (VaultLib.edge) sizes B so B(1-s) >= P and d*B < P, so purchasers keep:
the expensive bid (lose B) becomes the cheap keep (lose only the settlement fee s*B plus rebuild).

Integer wei for money. The big grid sums fee accrual in float ETH (rounded to wei) for speed; a
fully-integer single-account ledger in sim/test_unified.py checks wei conservation.
"""
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import forward  # noqa: E402  (reused read-only: history, pool_snapshot, daily_volume)

E = 10**18
GWEI = 10**9
DAY = 86_400
WINDOW_DAYS = 30
YEAR_DAYS = 365

# ---- protocol / live parameters (task + deploy/mainnet.json) ----
SUR, CUT, CROWN, S_FEE = 0.05, 0.01, 0.001, 0.01   # surcharge, cut, crown, settlement fee s
D_ETH, D_TOK = 0.90, 0.915                          # ETH bid, token bid; max(d,td) in edge = 0.915
BID_BPS = 9150                                      # max(settlementDiscount, tokenSettlementDiscount)
CEILING_GWEI = 0.5                                  # gasCeiling (hurdle gas)
WORK_FEE = 2 * 10**13                               # 0.00002 ETH per work unit (D55)
MINT_FEE = 10**15                                   # 0.001 ETH primary mint fee per Shape
RESERVE = 5 * 10**15                                # 0.005 ETH default reserve per account
MIN_KEEP_ADVANTAGE = 3 * 10**14                     # 0.0003 ETH
Q_PURCHASER_REDEEM = 160_000
K = (1 + SUR) * (1 - CUT) * (1 - CROWN)             # ~1.03851 (k_of)

# ---- keeper gas quotes (VaultLib Q_* ; a quote is fixed, never measured gas) ----
Q_BUILD_BASE, Q_BUILD_PACK, Q_BUILD_SHAPE = 300_000, 300_000, 130_000
Q_LISTED = 825_000                                  # per pack, build-and-list and list
Q_LIST_BASE = 280_000
Q_SYNC, Q_SELECTED, Q_SYNCED, Q_PRUNED = 85_000, 180_000, 120_000, 45_000
Q_FEECLAIM_BASE, Q_FEECLAIM_PER = 40_000, 80_000    # fee claim inside sync
Q_UNLIST_BASE, Q_UNLIST_PER = 340_000, 285_000
Q_LIQ_BASE, Q_LIQ_PACK, Q_LIQ_SHAPE = 75_000, 80_000, 35_000
Q_CHECKPOINT = 360_000
CYCLE_GAS = (22_000 + Q_SELECTED + Q_SYNCED + Q_PRUNED) + Q_LISTED + Q_FEECLAIM_PER  # gate cycle
DEPLOY_GAS = 250_000                                # manager clone deploy+initialize (stated; unmeasured)

# old (recipe 1/2) construction: 0.1 ETH bulk mint split ten ways, quoted gas (task + policy.py)
OLD_MINT_GAS_PER_PACK = 2_200_000 // 10             # 0.1 mint amortised over ten packs
OLD_PACK_GAS = 325_000                              # per pack


def quote(gas, units, basefee_gwei):
    """Keeper pay for one call: gas x min(basefee+0.05, ceiling) gwei + units x work_fee. No markup."""
    price_gwei = min(basefee_gwei + 0.05, CEILING_GWEI)
    return int(round(gas * price_gwei * GWEI)) + units * WORK_FEE


def floor_1e4(x):
    return x - (x % 10_000)


def edge_backing(p_wei, ceiling_gwei=CEILING_GWEI):
    """VaultLib.edge keep-incentive backing: floor_1e4((P - margin)*1e4 / max(d,td)_bps)."""
    margin = MIN_KEEP_ADVANTAGE + Q_PURCHASER_REDEEM * int(ceiling_gwei * GWEI)
    return floor_1e4((p_wei - margin) * 10_000 // BID_BPS)


def old_backing(p_wei):
    """Legacy backing max(P/d, P/(1-s)) so the purchaser bids d*B == P (recipe 1)."""
    return floor_1e4(max(p_wei * 10_000 // 9000, p_wei * 10_000 // 9900))


def gate_ok(B, P, cycle_cost):
    """VaultLib.edge `ok`: lists iff floor and k>=1+minEdge and _profitable(newlyBuilt=False):
    the bid outcome B(k-1) and the keep outcome B(k-s)-P both clear the cycle keeper pay."""
    floor = -(-P * 20 // 19)                          # ceil(P/0.95)
    if K < 1 + 100 * 1e-4 or B < floor:
        return False
    bid_ok = B * (K - 1) > cycle_cost
    keep_ok = B * (K - S_FEE) - P >= cycle_cost
    return bid_ok and keep_ok


def restock_ok(B, P, cycle_cost, build_cost):
    """VaultLib._profitable(newlyBuilt=True): the keep outcome also repays a fresh build.
    False means kept packs cannot be profitably replaced -> inventory depletes."""
    return B * (K - S_FEE) - P >= cycle_cost + build_cost


@dataclass
class Recipe:
    name: str
    units: int                # P = units * 0.01 ETH
    shapes: int
    legacy: bool = False      # old bulk-mint construction + bid backing
    keep_backing: bool = True  # edge (keep-incentive) vs old bid backing

    @property
    def P(self):
        return self.units * 10**16

    @property
    def mint_fee(self):
        return 3 * 10**14 if self.legacy else self.shapes * MINT_FEE  # 0.0003 legacy; 0.001/Shape direct

    def backing(self, ceiling_gwei=CEILING_GWEI):
        if self.keep_backing:
            return edge_backing(self.P, ceiling_gwei)
        return old_backing(self.P)

    def build_gas(self):
        if self.legacy:
            return OLD_MINT_GAS_PER_PACK + OLD_PACK_GAS + Q_LISTED
        return Q_BUILD_BASE + Q_BUILD_PACK + Q_BUILD_SHAPE * self.shapes + Q_LISTED

    def build_cost(self, basefee_gwei):
        return quote(self.build_gas(), 2, basefee_gwei) + self.shapes * MINT_FEE * (0 if self.legacy else 1) + (self.mint_fee if self.legacy else 0)

    def list_cost(self, basefee_gwei):
        return quote(Q_LIST_BASE + Q_LISTED, 1, basefee_gwei)

    def sync_cost(self, basefee_gwei):
        # one paid sync per resolution: base + own selection + terminal return + prune + fee claim
        gas = Q_SYNC + Q_SELECTED + Q_SYNCED + Q_PRUNED + Q_FEECLAIM_BASE + Q_FEECLAIM_PER
        return quote(gas, 1, basefee_gwei)

    def cycle_cost(self, basefee_gwei):
        return quote(CYCLE_GAS, 2, basefee_gwei)


# the five recipes of question A
RECIPES = {
    "r1_old_bid":    Recipe("0.03 bulk-split, old bid backing", 3, 3, legacy=True, keep_backing=False),
    "r2_old_keep":   Recipe("0.03 bulk-split, keep backing",    3, 3, legacy=True, keep_backing=True),
    "r3_direct03":   Recipe("0.03 direct mint (3 Shapes)",      3, 3, keep_backing=True),
    "r4_direct06":   Recipe("0.06 direct mint (2 Shapes)",      6, 2, keep_backing=True),  # preferred
    "r5_direct07":   Recipe("0.07 direct mint (3 Shapes)",      7, 3, keep_backing=True),
}


@dataclass
class Account:
    recipe: Recipe
    capital: int            # wei
    is_pool: bool = False
    reserve: int = RESERVE
    n: int = 0              # listings (set in size())
    B: int = 0
    can_restock: bool = True

    def size(self, basefee_gwei):
        self.B = self.recipe.backing(CEILING_GWEI)
        cyc = self.recipe.cycle_cost(basefee_gwei)
        self.can_restock = restock_ok(self.B, self.recipe.P, cyc, self.recipe.build_cost(basefee_gwei))
        # capital per listing: backing B locked + pack worth P (the Shapes it embodies, recoverable
        # at exit by redeeming) + the one-time build gas and mint fee.
        slot = self.B + self.recipe.P + self.recipe.build_cost(basefee_gwei)
        avail = self.capital - self.reserve
        self.n = max(0, avail // slot) if avail > 0 else 0
        if not gate_ok(self.B, self.recipe.P, cyc):        # per-listing gate (capital-independent)
            self.n = 0
        return self.n


# --------------------------------------------------------------- history stream


# Launch-scale calibration: 39% of the trailing-30-day events are FWA bootstrap / quiet periods
# (active listing count N < 500) where any inserted listing wins a wildly outsized share. Those
# periods are not the mature market the owner's gate targets ("use launch-scale numbers"), and they
# are exactly what makes the raw backtest print ~19x the validated forward simulation. The primary
# stream keeps only mature events (N >= MATURE_MIN_N); with it a 2 ETH pool sees ~950 selections/yr,
# matching the forward sim's ~982 (docs/KEEPER-ECONOMICS.md). Set MATURE_MIN_N=0 for the raw backtest.
MATURE_MIN_N = 500


def window_arrays(mature_min_n=MATURE_MIN_N):
    """Trailing-30-day arrays (fee, w, N, cut, crown) ending at the latest archive block,
    restricted to mature events (N >= mature_min_n) for launch-scale calibration."""
    h = forward.history()
    ts = h["ts"]
    t1 = ts.max()
    t0 = t1 - WINDOW_DAYS * DAY
    m = (ts >= t0) & (ts < t1) & (h["n"] >= mature_min_n)
    return dict(fee=h["fee"][m], w=h["w"][m], N=h["n"][m],
                cut=h["cut"][m] / 1e4, crown=h["crown"][m] / 1e4, t0=int(t0), t1=int(t1),
                n_acq=int(m.sum()), mature_min_n=mature_min_n)


def year_stream(win):
    """Tile the 30-day window to a 365-day event stream (12 full tiles + a 5-day partial)."""
    reps = YEAR_DAYS // WINDOW_DAYS       # 12
    tail_frac = (YEAR_DAYS - reps * WINDOW_DAYS) / WINDOW_DAYS  # 5/30
    n = len(win["fee"])
    tail = int(n * tail_frac)
    idx = list(range(n)) * reps + list(range(tail))
    idx = np.array(idx)
    return {k: win[k][idx] for k in ("fee", "w", "N", "cut", "crown")}


# --------------------------------------------------------------- the model


@dataclass
class Scenario:
    label: str
    keep_rate: float = 1.0          # purchaser-keep fraction (silent folds in for keep backing)
    basefee_gwei: float = 0.15
    volume_scale: float = 1.0       # smaller FWA market: each historical acquisition occurs w.p. f
    seeds: int = 256                # >= 32 required; runtime is ~0.3s so use more for stable tails


def run_cell(accounts, scenario, stream):
    """Return per-account yearly economics across seeds, with all accounts inserted into FWA.

    Identical accounts are computed once (grouped). Selections use common random numbers (one shared
    uniform matrix, fixed master seed) so every account/recipe/cell faces matched seeds.
    """
    bf = scenario.basefee_gwei
    for a in accounts:
        a.size(bf)
    Wn = sum(a.n / (a.B / E) for a in accounts if a.n)       # total our weight (1/ETH)
    fee, w, N = stream["fee"], stream["w"], stream["N"]
    ksplit = (1 - stream["cut"]) * (1 - stream["crown"])
    denom = w + Wn                                           # w_i + Wn  (foreign+our weight)
    f = scenario.volume_scale
    share_per_listing = fee * ksplit * w / (N * denom) * f   # ETH per our listing per event
    results = {}
    for i, a in enumerate(accounts):
        if a.n == 0:
            results[id(a)] = _dead_account(a, scenario)
            continue
        # selection count ~ Poisson(mu): ~220k independent Bernoulli events, each p~1e-4 (p<<1).
        # Independent per account (own VRF) with a matched master seed, so recipes/cells line up.
        p_listing = (E / a.B) / denom * f                    # prob this listing wins this event
        mu = float((a.n * p_listing).sum())                  # expected yearly selections
        rng = np.random.default_rng(2024 + i)                # matched across cells; independent per account
        sel = rng.poisson(mu, scenario.seeds).astype(np.int64)
        gross_fees = int(round(a.n * share_per_listing.sum() * E))
        keeps = rng.binomial(sel, scenario.keep_rate).astype(np.int64)
        bids = sel - keeps
        results[id(a)] = _account_economics(a, scenario, gross_fees, sel, keeps, bids)
    return results


def _dead_account(a, scenario):
    """Gate failed or no room: no listing. Loses only any deploy cost (none built)."""
    deploy = 0 if a.is_pool else quote(DEPLOY_GAS, 0, scenario.basefee_gwei)
    net = -deploy
    return dict(n=0, B=a.B, capital=a.capital, gross_fees=0, backing_lost=0, keeper=0, mint=0,
                settlement=0, gas_deploy=deploy, initial_build=0, exit_gas=0, deployed=0,
                util=0.0, can_restock=a.can_restock, active_frac=0.0, request_charge=0,
                net_mean=net, net_median=net, returns=np.full(scenario.seeds, net / a.capital),
                sel_mean=0.0, keeps_mean=0.0, bids_mean=0.0, new_packs=0, kept_by_purchaser=0.0,
                reused_packs=0.0, exit_days=0.0)


def _account_economics(a, scenario, gross_fees, sel, keeps, bids):
    bf = scenario.basefee_gwei
    B = a.B
    shapes = a.recipe.shapes
    mint_per = a.recipe.mint_fee                            # per pack (creator)
    build_gas_q = quote(a.recipe.build_gas(), 2, bf)        # keeper build pay (gas only)
    list_cost = a.recipe.list_cost(bf)                      # keeper relist pay
    sync_cost = a.recipe.sync_cost(bf)                      # keeper sync pay per resolution
    settle_per = B - B * (10_000 - int(S_FEE * 10_000)) // 10_000   # s*B wei (exact, record_keep)
    deploy = 0 if a.is_pool else quote(DEPLOY_GAS, 0, bf)
    request_charge = quote(Q_CHECKPOINT, 1, bf) if a.is_pool else 0   # pool checkpoints: request-funded
    exit_gas = quote(Q_UNLIST_BASE + Q_UNLIST_PER * a.n, 1, bf) + \
        quote(Q_LIQ_BASE + Q_LIQ_PACK * a.n + Q_LIQ_SHAPE * shapes * a.n, 2, bf)

    P = a.recipe.P
    # per-selection NAV loss (wei), from vault.py record_keep/bid_settled:
    #   BID : backing B gone (backing_lost += B), pack kept (P retained) + relist gas + sync.
    #   KEEP: backing returns B(1-s) (-> -s*B net on backing) AND the pack (worth P) goes to the
    #         purchaser and is gone (consume_keep: backing_lost += value). Compensated only by the
    #         accrued fees. Then rebuild (mint price P is recovered as new pack inventory; its mint
    #         FEE and build gas are not) + sync.  keep_cost = P + s*B + mint_fee + build_gas + sync.
    #   The keep-incentive backing sizes B so B(1-s) >= P, so the account always prefers (and silent
    #   purchasers trigger) the keep branch; purchasers keep when the pack's Shapes beat the bid d*B.
    bid_cost = B + list_cost + sync_cost
    if a.can_restock:
        keep_cost = P + settle_per + mint_per + build_gas_q + sync_cost
        active_frac = 1.0
        keeps_eff = keeps.astype(float)
    else:
        # Kept packs cannot be profitably replaced: no rebuild, the pack is permanently gone, and
        # the account's n packs deplete. Active fraction ~ n / unconstrained keeps/yr.
        keep_cost = P + settle_per + sync_cost
        mean_keeps = max(1.0, float(np.mean(keeps)))
        active_frac = min(1.0, a.n / mean_keeps)
        keeps_eff = np.minimum(keeps, a.n).astype(float)
    gross = float(gross_fees) * active_frac
    initial_build = a.n * (build_gas_q + mint_per)         # P is capital (recovered), not an expense

    # float wei (yearly fees exceed int64); the wei-exact ledger lives in test_unified.py
    net = (gross - bids.astype(float) * bid_cost - keeps_eff * keep_cost
           - float(initial_build + deploy + request_charge))
    net_exit = net - float(exit_gas)
    capital = a.capital + request_charge
    returns = net_exit / capital
    deployed = a.n * (B + P)                                # backing + pack value embodied

    mk = float(np.mean(keeps_eff))
    rebuilds = mk if a.can_restock else 0.0                 # kept packs replaced only if restockable
    keeper = (np.mean(sel) * sync_cost + np.mean(bids) * list_cost + rebuilds * build_gas_q
              + a.n * build_gas_q + deploy + request_charge)
    mint = (a.n + rebuilds) * mint_per
    backing_lost = np.mean(bids) * B + mk * P    # vault.backing_lost: bid += B, keep(consume) += P
    return dict(
        n=a.n, B=B, capital=capital, deployed=deployed, util=deployed / capital,
        can_restock=a.can_restock, active_frac=active_frac,
        gross_fees=int(gross), backing_lost=int(backing_lost), keeper=int(keeper), mint=int(mint),
        settlement=int(mk * settle_per), gas_deploy=deploy,
        initial_build=int(initial_build), exit_gas=exit_gas, request_charge=request_charge,
        net_mean=float(np.mean(net_exit)), net_median=float(np.median(net_exit)), returns=returns,
        sel_mean=float(np.mean(sel)), keeps_mean=mk, bids_mean=float(np.mean(bids)),
        new_packs=float(a.n + rebuilds), kept_by_purchaser=mk,
        reused_packs=float(np.mean(bids)), exit_days=1.0 / 24 + 60 / DAY)


# --------------------------------------------------------------- summaries


def summarize(returns):
    return dict(mean=float(np.mean(returns)), median=float(np.median(returns)),
                p10=float(np.percentile(returns, 10)), p5=float(np.percentile(returns, 5)),
                ploss=float(np.mean(returns < 0)), worst=float(np.min(returns)))


HURDLE = 0.10  # owner's formal gate: >= 10%/yr net at trailing-30-day volume, tokens zero, 0.5 gwei


def main():
    import time
    t0 = time.time()
    win = window_arrays()
    stream = year_stream(win)
    out = {"inputs": dict(window_days=WINDOW_DAYS, year_days=YEAR_DAYS, n_acq_window=win["n_acq"],
                          t0=win["t0"], t1=win["t1"], acq_per_day=round(win["n_acq"] / WINDOW_DAYS, 1),
                          seeds=256, ceiling_gwei=CEILING_GWEI, reserve=RESERVE, work_fee=WORK_FEE,
                          mint_fee=MINT_FEE, k=K, edge_06=edge_backing(6 * 10**16)),
           "recipes": {}, "products": {}, "sensitivity": {}, "exposure": {}, "answers": {}}

    base_gate = Scenario("gate (0.5 gwei ceiling, keep)", keep_rate=1.0, basefee_gwei=0.5)

    # ---- A. recipe comparison: one 2 ETH pool, matched capital, designed behaviour ----
    for key, rc in RECIPES.items():
        keep = 0.0 if (rc.legacy and not rc.keep_backing) else 1.0   # recipe 1 designed to bid
        sc = Scenario(f"recipe {key}", keep_rate=keep, basefee_gwei=0.5)
        acc = Account(rc, 2 * E, is_pool=True)
        res = run_cell([acc], sc, stream)[id(acc)]
        res["summary"] = summarize(res["returns"])
        res["recipe"] = rc.name
        res["keep_rate"] = keep
        res["P"] = rc.P
        out["recipes"][key] = _strip(res)

    # ---- B. products and scale (recipe 4) ----
    r4 = RECIPES["r4_direct06"]
    products = {
        "pool_2": lambda: [Account(r4, 2 * E, is_pool=True)],
        "pool_20": lambda: [Account(r4, 20 * E, is_pool=True)],
        "managers_10x1": lambda: [Account(r4, 1 * E) for _ in range(10)],
        "pool_2_plus_10_managers": lambda: [Account(r4, 2 * E, is_pool=True)] + [Account(r4, 1 * E) for _ in range(10)],
        "managers_50x02": lambda: [Account(r4, 2 * 10**17) for _ in range(50)],
        "managers_smallest": lambda: [Account(r4, min_viable_manager(r4, 0.5), ) for _ in range(5)],
    }
    for name, make in products.items():
        accs = make()
        res = run_cell(accs, base_gate, stream)
        out["products"][name] = _aggregate_product(name, accs, res)
    # smaller FWA market (recipe 4, pool 2 + pool 20)
    for scale in (0.5, 0.25):
        for cap, tag in ((2, "pool_2"), (20, "pool_20")):
            sc = Scenario(f"{tag} market x{scale}", keep_rate=1.0, basefee_gwei=0.5, volume_scale=scale)
            acc = Account(r4, cap * E, is_pool=True)
            r = run_cell([acc], sc, stream)[id(acc)]
            out["products"][f"{tag}_market_{int(scale*100)}"] = _aggregate_product(
                f"{tag}_market_{int(scale*100)}", [acc], {id(acc): r})

    # ---- exposure guard: combined share of FWA weight for the biggest aggregate run ----
    out["exposure"] = exposure_study(r4, win, stream)

    # ---- C. sensitivity grids (recipe 4, 2 ETH pool) ----
    grid = {}
    for keep in (0.0, 0.25, 0.5, 0.75, 1.0):
        sc = Scenario(f"keep {keep}", keep_rate=keep, basefee_gwei=0.5)
        acc = Account(r4, 2 * E, is_pool=True)
        grid[f"keep_{keep}"] = summarize(run_cell([acc], sc, stream)[id(acc)]["returns"])
    for gw, tag in ((0.15, "gas_0.15"), (0.5, "gas_0.5"), (1.0, "gas_1.0"), (2.0, "gas_2.0")):
        sc = Scenario(tag, keep_rate=1.0, basefee_gwei=gw)
        acc = Account(r4, 2 * E, is_pool=True)
        grid[tag] = summarize(run_cell([acc], sc, stream)[id(acc)]["returns"])
    for scale, tag in ((1.0, "vol_full"), (0.5, "vol_half"), (0.25, "vol_quarter"), (0.0, "vol_zero")):
        sc = Scenario(tag, keep_rate=1.0, basefee_gwei=0.5, volume_scale=scale)
        acc = Account(r4, 2 * E, is_pool=True)
        grid[tag] = summarize(run_cell([acc], sc, stream)[id(acc)]["returns"])
    # constrained liquidity: tiny capital (reserve binds), concentrated activity (few big listings)
    for cap, tag in ((0.2, "capital_0.2"), (0.5, "capital_0.5"), (2, "capital_2"), (20, "capital_20")):
        sc = Scenario(tag, keep_rate=1.0, basefee_gwei=0.5)
        acc = Account(r4, int(cap * E), is_pool=True)
        grid[tag] = dict(summarize(run_cell([acc], sc, stream)[id(acc)]["returns"]), n=acc.n)
    out["sensitivity"] = grid

    # ---- D. explicit answers ----
    out["answers"] = answer_D(r4, win, stream)

    out["runtime_s"] = round(time.time() - t0, 1)
    return out


def min_viable_manager(rc, basefee_gwei):
    """Smallest capital (wei) at which a manager lists >=1 pack and clears the 10% hurdle."""
    for milli in range(50, 2000, 10):
        cap = milli * 10**15
        a = Account(rc, cap)
        a.size(0.5)
        if a.n >= 1:
            return cap
    return 200 * 10**15


def _aggregate_product(name, accounts, res):
    rets = []
    g = dict(net_mean=0.0, gross_fees=0, keeper=0, mint=0, backing_lost=0, deployed=0, capital=0,
             n=0, sel=0.0, keeps=0.0, bids=0.0, new_packs=0.0, kept=0.0, reused=0.0, exit_gas=0,
             deploy=0, initial_build=0, request_charge=0)
    per_acct_returns = []
    for a in accounts:
        r = res[id(a)]
        per_acct_returns.append(r["returns"])
        g["net_mean"] += r["net_mean"]
        g["gross_fees"] += r["gross_fees"]
        g["keeper"] += r["keeper"]
        g["mint"] += r["mint"]
        g["backing_lost"] += r["backing_lost"]
        g["deployed"] += r["deployed"]
        g["capital"] += r["capital"]
        g["n"] += r["n"]
        g["sel"] += r["sel_mean"]
        g["keeps"] += r["keeps_mean"]
        g["bids"] += r["bids_mean"]
        g["new_packs"] += r["new_packs"]
        g["kept"] += r["kept_by_purchaser"]
        g["reused"] += r["reused_packs"]
        g["exit_gas"] += r["exit_gas"]
        g["deploy"] += r["gas_deploy"]
        g["initial_build"] += r["initial_build"]
        g["request_charge"] += r.get("request_charge", 0)
    # portfolio return across matched seeds: total net / total capital, seed by seed
    net_by_seed = sum((res[id(a)]["returns"] * res[id(a)]["capital"]) for a in accounts)
    port_returns = net_by_seed / g["capital"]
    g["util"] = g["deployed"] / g["capital"]
    g["summary"] = summarize(port_returns)
    g["n_accounts"] = len(accounts)
    g["exit_days"] = res[id(accounts[0])]["exit_days"]
    g["passes_hurdle"] = g["summary"]["mean"] >= HURDLE
    return _wei_to_eth(g)


def exposure_study(rc, win, stream):
    """How combined participation (our aggregate weight vs FWA's) changes each account's return.
    Justifies a shared exposure cap iff returns fall materially as our combined weight rises."""
    W_foreign_mean = float(np.mean(stream["w"]))
    rows = {}
    for n_managers in (1, 10, 50, 200, 500):
        accs = [Account(rc, 1 * E) for _ in range(n_managers)]
        res = run_cell(accs, Scenario(f"{n_managers} managers", keep_rate=1.0, basefee_gwei=0.5), stream)
        a0 = accs[0]
        Wn = sum(a.n / (a.B / E) for a in accs if a.n)
        rows[f"{n_managers}_managers"] = dict(
            n_managers=n_managers, our_weight=round(Wn, 1),
            share_of_total=round(Wn / (W_foreign_mean + Wn), 4),
            per_manager_return_mean=round(float(np.mean(res[id(a0)]["returns"])), 4),
            per_manager_sel=round(res[id(a0)]["sel_mean"], 1),
            per_manager_fees_eth=round(res[id(a0)]["gross_fees"] / E, 4))
    return dict(foreign_weight_mean=round(W_foreign_mean, 1), rows=rows)


def answer_D(rc, win, stream):
    sc = Scenario("D", keep_rate=1.0, basefee_gwei=0.5)
    # pool vs managers at matched 10 ETH total
    pool10 = Account(rc, 10 * E, is_pool=True)
    rp = run_cell([pool10], sc, stream)[id(pool10)]
    mgrs = [Account(rc, 1 * E) for _ in range(10)]
    rm = run_cell(mgrs, sc, stream)
    mgr_net = sum(rm[id(a)]["net_mean"] for a in mgrs)
    mgr_cap = sum(rm[id(a)]["capital"] for a in mgrs)
    # pooled-accounting cost: pool request charge + reserve drag vs a single manager of same size
    mgr10 = Account(rc, 10 * E)   # one big personal manager, no checkpoints
    rm10 = run_cell([mgr10], sc, stream)[id(mgr10)]
    return dict(
        pool_10_return=round(float(np.mean(rp["returns"])), 4),
        pool_10_util=round(rp["util"], 4),
        managers_10x1_return=round(mgr_net / mgr_cap, 4),
        managers_10x1_reserve_eth=round(10 * RESERVE / E, 4),
        pool_10_reserve_eth=round(RESERVE / E, 4),
        pooled_accounting_cost_eth=round((rm10["net_mean"] - rp["net_mean"]) / E, 5),
        pool_request_charge_eth=round(rp.get("request_charge", 0) / E, 6),
        min_viable_manager_eth=round(min_viable_manager(rc, 0.5) / E, 3),
        creator_mint_per_eth_pool=round(rp["mint"] / E / (rp["capital"] / E), 5),
        hurdle=HURDLE)


def _strip(res):
    r = dict(res)
    r.pop("returns", None)
    return _wei_to_eth(r)


def _wei_to_eth(d):
    out = {}
    for k, v in d.items():
        if isinstance(v, bool):
            out[k] = v
        elif isinstance(v, (int, np.integer)) and k not in ("n", "n_accounts", "n_managers"):
            out[k] = round(v / E, 6)
        elif isinstance(v, dict):
            out[k] = v
        else:
            out[k] = v
    return out


if __name__ == "__main__":
    res = main()
    res["seeds"] = 32
    res["master_seed"] = 2024
    res["rpc"] = "offline (sim/data/fwa.sqlite archive)"
    receipt = ROOT.parent / "docs/receipts/unified-economics.json"
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(res, indent=2, default=float))
    print(f"wrote {receipt}  (runtime {res['runtime_s']}s)")
    print(json.dumps({"recipes": {k: v["summary"] for k, v in res["recipes"].items()},
                      "products": {k: v["summary"] for k, v in res["products"].items()}},
                     indent=2, default=float))
