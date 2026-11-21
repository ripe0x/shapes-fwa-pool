# Unified economics of the redesigned FWA Shape-pack strategy

**Model:** `sim/unified.py` · **self-checks:** `sim/test_unified.py` (all pass) · **receipt:**
`docs/receipts/unified-economics.json` · **256 seeds/cell, master seed 2024, runtime ~0.2 s.**

Event-driven over the real FWA acquisition history (`sim/forward.py` `history()`, validated by
`sim/replay.py`): the trailing-30-day window ending at the latest archive block (blocks to
t=1,794,773,723; **11,254 mature acquisitions, 375/day**), tiled to a year. Every own listing's fee
share and selection odds use FWA's formulas with **all our accounts' listings inserted**, the exact
externality of `sim/forward.py.backtest()` (verified identical to <1e-9 in `test_unified.py`). Tokens
at zero. Integer-wei conservation checked in the ledger test. 0.5 gwei gas ceiling unless noted.

## Headline

**Recommend recipe 4 (directly-minted 0.06 packs).** It is the simplest viable direct-mint design,
clears the owner's 10%/yr hurdle by a wide margin in every pooled configuration, and pays the Shapes
creator the most mint-fee revenue per ETH of any viable recipe. The pooled vault beats personal
managers at matched capital, mainly through one shared reserve and higher capital utilisation. A
shared exposure cap is economically justified once our combined listings exceed ~10% of FWA weight.

**The redesign's engine:** the keep-incentive backing (`VaultLib.edge`, `B(1-s) ≥ P`) makes
purchasers (and silent reclaims) *keep* the pack and return the backing as `B(1-s)` instead of
*bidding* and burning the whole backing `B`. Keep roughly **doubles** the return of the old bid design
(not 30×: the kept pack, worth `P`, is given to the purchaser and is a real loss offset only by the
accrued fees — `keep_cost = P + sB + mint + build_gas + sync`). The entire uplift is **contingent on
purchasers keeping**, which the account cannot control (sensitivity C).

---

## A. Recipe comparison (2 ETH pool, matched capital, designed behaviour, 0.5 gwei, 256 seeds)

Each pack ties up `B + P` of capital (backing + the Shapes embodied in the pack, recovered at exit).
"Designed behaviour" = recipe 1 bids (keep 0), recipes 2–5 keep (keep 1).

| # | Recipe | B (ETH) | P | packs n | sel/yr | creator mint ETH/yr (/ETH) | keeper ETH/yr | **mean** | median | p10 | p5 | P(loss) |
|---|--------|--------:|---:|--------:|-------:|---------------------------:|--------------:|---------:|-------:|----:|---:|--------:|
| 1 | 0.03 bulk-split, **old bid** backing | 0.0333 | 0.03 | 30 | 3595 | 0.009 (0.004) | 3.14 | **+78%** | +77% | −54% | −82% | 25% |
| 2 | 0.03 bulk-split, keep backing | 0.0324 | 0.03 | 31 | 3815 | 1.15 (0.58) | 3.91 | **+380%** | +378% | +253% | +226% | 0% |
| 3 | 0.03 **direct** mint (3 Shapes) | 0.0324 | 0.03 | 30 | — | 0.09 (0.05) | 1.12 | **−1.7%** | −1.7% | −1.7% | −1.7% | **100%** |
| **4** | **0.06 direct mint (2 Shapes)** | 0.0652 | 0.06 | 15 | 948 | **1.93 (0.96)** | 1.12 | **+186%** | +184% | +58% | +31% | 2% |
| 5 | 0.07 direct mint (3 Shapes) | 0.0761 | 0.07 | 13 | 705 | 2.15 (1.08) | 0.88 | **+146%** | +143% | +17% | −11% | 7% |

**Reading it:**

→ **Recipe 3 is non-viable.** Directly-minted 0.03 packs *list* (bid/keep gates pass) but **fail the
restock gate** `B(k-s)-P ≥ cycleCost + buildCost`: the keep margin (0.0033 ETH) cannot repay a fresh
3-Shape build (0.0046 ETH). Each kept pack cannot be replaced, so inventory depletes in ~3 days
(active fraction 0.008) and the run loses its build costs. Small *direct* packs don't work.

→ **Smaller packs trade fee-share density against replacement cost.** Halving pack size (0.06→0.03)
doubles packs-per-ETH, so ~4× the selections and fee throughput — but each keep must buy a fresh mint.
At 0.03 that extra inventory cost only clears with the **old bulk-mint-split** construction (recipe 2,
0.0003 ETH/pack mint), not direct mint. Recipe 2's +380% beats recipe 4's +186% **but** the advantage
is not "simple" or free: it needs the legacy 0.1-ETH bulk mint, it runs backing barely above the floor
(0.0324) so it takes **~2× the FWA selection share per ETH** (more externality/exposure), and it
**starves the creator** (0.58 vs 0.96 ETH mint/ETH). The owner wants *both* holder return and creator
revenue; recipe 4 wins creator revenue and simplicity and lower exposure.

→ **Larger packs (0.07, recipe 5)** pay the creator the most (1.08 ETH/ETH) but fewer selections and a
thinner p5 (−11%, 7% loss): more capital parked per pack, less fee-share density.

→ **Keep vs bid is the whole story.** Same 0.03 construction: bid (recipe 1) +78% with 25% loss
probability; keep (recipe 2) +380% with 0% loss. Keep preserves the backing; bid burns 0.033 ETH per
selection (119.8 ETH/yr of backing churn barely covered by 124.6 ETH/yr of fees).

**Verdict: recipe 4.** No simple recipe is materially better for *both* holder return and creator
revenue. Dynamic sizing is not justified.

---

## B. Products and scale (recipe 4, 0.5 gwei, 256 seeds)

| Product | accts | packs | util | **mean** | median | p10 | p5 | P(loss) | ≥10% hurdle |
|---------|------:|------:|-----:|---------:|-------:|----:|---:|--------:|:-----------:|
| Pooled vault 2 ETH | 1 | 15 | 0.94 | **+186%** | +184% | +58% | +31% | 2.0% | **pass** |
| Pooled vault 20 ETH | 1 | 156 | 0.98 | **+172%** | +172% | +133% | +124% | 0% | **pass** |
| 10 managers × 1 ETH | 10 | 70 | 0.88 | +163% | +164% | +117% | +100% | 0% | pass |
| 1 pool (2) + 10 managers (1) | 11 | 85 | 0.89 | +163% | +164% | +113% | +102% | 0% | pass |
| 50 managers × 0.2 ETH | 50 | 50 | 0.63 | +117% | +119% | +74% | +63% | 0% | pass |
| 5 managers × 0.14 (smallest) | 5 | 5 | 0.89 | +171% | +181% | −47% | −113% | 16% | pass (high variance) |
| Pool 2, FWA market ×0.50 | 1 | 15 | 0.94 | +93% | +92% | +2% | −18% | 9% | pass |
| Pool 20, FWA market ×0.50 | 1 | 156 | 0.98 | +85% | +85% | +57% | +52% | 0% | pass |
| Pool 2, FWA market ×0.25 | 1 | 15 | 0.94 | +47% | +45% | −16% | −32% | 20% | pass (mean) |
| Pool 20, FWA market ×0.25 | 1 | 156 | 0.98 | +42% | +41% | +22% | +18% | 0.4% | pass |

**Bigger and pooled is steadier:** a 20 ETH pool holds 156 packs; the law of large numbers pulls p5
to +124% (vs +31% for the 2 ETH pool) with zero observed loss. Small accounts keep the same mean but
a fat left tail (a 0.14 ETH manager with 1 pack has p5 −113%: one bad year of few selections can't
amortise its fixed build/exit gas). Shrinking the FWA market scales returns roughly linearly and
only the smallest pools approach the hurdle at 25% of today's volume.

---

## C. Full ledger per run (recipe 4, 2 ETH pool, keep 1, 0.5 gwei) and sensitivity

**Per-run flows (ETH/yr):** gross FWA fees **64.3** · creator mint fees **1.93** (948 rebuilds) ·
packs created 963 (15 initial + 948 replacements) · packs permanently acquired by purchasers **948** ·
packs returned/reused (bids) **0** at keep=1 · keeper pay **1.12** (sync + build gas) · deployment
expense 0 (pool; managers pay 250,000 gas/clone ≈ 0.00013 ETH, **stated, not measured**) · exit gas
**0.0035** (unlist + liquidate 15 packs) · working-capital utilisation **0.94** · request-funded
checkpoint charge 0.0002 (depositor, one-time). Complete-withdrawal cost ≈ 0.0035 ETH, time ≈ 1 h
settlement window + one keeper poll.

**Keep-behaviour sweep (the dominant risk) — recipe 4, 2 ETH:**

| purchaser keep rate | mean | median | p5 | P(loss) |
|---|---:|---:|---:|---:|
| 0% (all bid, backing burned) | **+81%** | +79% | −79% | 23% |
| 25% | +108% | +105% | −54% | 16% |
| 50% | +134% | +132% | −25% | 9% |
| 75% | +160% | +159% | +3% | 5% |
| 100% (all keep) | **+186%** | +184% | +31% | 2% |

Keep behaviour moves the return from +81% (bid floor) to +186% (keep ceiling) and the loss
probability from 23% to 2%. **Historically unresolved (silent) purchasers fold into the keep branch**
because the keep-incentive backing makes `B(1-s) ≥ P` the account's best reclaim — distinct from a
purchaser *choosing* to keep, which needs the pack's Shapes to beat the bid `d·B`.

**Gas / volume / liquidity (recipe 4, 2 ETH, keep 1):**

| scenario | mean | median | p5 | P(loss) |
|---|---:|---:|---:|---:|
| gas 0.15 gwei | +218% | +216% | +64% | 1% |
| gas 0.5 (gate) | +186% | +184% | +31% | 2% |
| gas 1.0 gwei | +186% | +184% | +31% | 2% |
| gas 2.0 gwei | +186% | +184% | +31% | 2% |
| volume full | +186% | +184% | +31% | 2% |
| volume ×0.5 (low activity) | +93% | +92% | −18% | 9% |
| volume ×0.25 | +46% | +45% | −32% | 20% |
| **volume 0 (zero activity)** | **−2.3%** | −2.3% | −2.3% | 100% |
| capital 0.2 ETH (1 pack, reserve binds) | +128% | +120% | −294% | 32% |
| capital 0.5 ETH (3 packs) | +155% | +154% | −117% | 20% |
| capital 2 ETH (15 packs) | +186% | +184% | +31% | 2% |
| capital 20 ETH (156 packs) | +172% | +172% | +124% | 0% |

Zero activity loses exactly the build/list + exit gas (−2.3%, self-checked). Gas is flat from 0.5 to
2 gwei **because keeper pay is capped at the 0.5 gwei ceiling** — see limitation (L3). Constrained
capital keeps the mean but widens the tail (fixed costs over fewer packs). Concentrated activity is
represented by the mature stream's own bursts (the low-N tail is excluded as bootstrap, see L1).

---

## D. Explicit answers

1. **When does the pool beat personal management (same capital)?** Essentially always, and the margin
   grows with reserve drag. At **10 ETH**: pool **+182%** vs ten 1-ETH managers **+163%** (+19 pp).
   The pool ties up **one** 0.005 ETH reserve; ten managers tie up **0.05 ETH** (10×), and the pool's
   shared cash/inventory lifts utilisation to 0.976 vs 0.876. Managers only win when a depositor
   distrusts pooling or wants isolation; they never earn the pool's return at equal size.

2. **Minimum economically useful personal-manager balance: ~0.14 ETH** (one pack: `reserve 0.005 +
   B 0.065 + P 0.06 + build`). Below that it cannot list. At 0.14 ETH the mean is high (+171%) but the
   single-pack variance is brutal (p5 −113%, 16% loss); **~0.5–1 ETH** is the first balance with a
   sane tail (p5 −107% → positive by ~1 ETH).

3. **How much do shared inventory and cash improve efficiency?** Utilisation rises from 0.63 (fifty
   0.2-ETH managers) and 0.88 (ten 1-ETH managers) to **0.98** (one 20-ETH pool); mean return rises
   from +117% / +163% to +172%. One shared reserve and a shared cash buffer for keeper pay are the
   mechanism.

4. **How much does pooled ownership accounting cost?** Almost nothing: **~0.00007 ETH/yr** of return
   drag plus a one-time **0.0002 ETH** request charge (which *funds* checkpoints, so it is not a
   depositor loss against return). Pooling's benefits dwarf its accounting cost by ~1000×.

5. **Which product generates more creator mint fees per ETH?** Direct-mint recipes, because every keep
   buys a fresh mint: recipe **5 (0.07) = 1.08 ETH/ETH**, **recipe 4 (0.06) = 0.96**, recipe 2 (0.03
   bulk) = 0.58, recipe 1 (bid, rarely rebuilds) = 0.004. Recipe 4 pays the creator **~210× recipe 1**.
   The keep redesign is as much a creator-revenue engine as a holder-return engine.

6. **How does aggregate participation affect the FWA opportunity?** It cannibalises: adding our own
   listings raises the shared weight denominator `w + Wn`, lowering every account's fee share *and*
   selection odds (exposure section).

**10% hurdle verdict (≥10%/yr net, trailing-30-day volume, tokens zero, 0.5 gwei ceiling):**
**every pooled configuration passes** — pool 2 ETH +186% (p5 +31%), pool 20 ETH +172% (p5 +124%),
and even at 25% of today's FWA volume the 20 ETH pool clears it (+42%, p5 +18%). The hurdle is not
the binding constraint; **purchaser keep behaviour and FWA volume are** (at keep 0 / volume ×0.25 the
2 ETH pool drops toward the hurdle). The hurdle was not lowered.

---

## Exposure guard — economically justified beyond ~10% of FWA weight

Scaling identical 1-ETH managers (recipe 4), each inserts ~107 of weight; FWA's mean foreign weight is
41,588.

| our accounts | combined capital | our share of FWA weight | sel/yr each | fees ETH/yr each | **return each** |
|---:|---:|---:|---:|---:|---:|
| 1 | 1 ETH | 0.26% | 444 | 30.2 | **+179%** |
| 10 | 10 ETH | 2.5% | 425 | 28.8 | +170% |
| 50 | 50 ETH | 11.4% | 362 | 24.6 | +145% |
| 200 | 200 ETH | 34.1% | 247 | 16.8 | +97% |
| 500 | 500 ETH | 56.4% | 157 | 10.7 | **+64%** |

Up to ~2.5% share the self-cannibalisation is negligible (+179%→+170%). By **11% share it costs
~34 pp** per account (+179→+145) and by 34% share it **halves** per-account selections and nearly
halves return. **A registry capping our combined share of FWA weight is justified**: it prevents later
accounts from diluting earlier ones once the aggregate passes ~10% of the pool. Below ~10% a guard is
unnecessary overhead; above it, every added account imposes a negative externality on all the others.
A single pool self-limits (its own weight is one number); many independent managers are what create the
need for a shared cap.

---

## Modelling limits

- **L1 — launch-scale calibration.** 39% of the trailing-30-day events have an active-listing count
  `N < 500` (FWA bootstrap/quiet periods) where any inserted listing wins a wild share; those make the
  raw `backtest()` print ~19× the owner's validated forward sim. The primary stream keeps only mature
  events (`N ≥ 500`, "use launch-scale numbers"); with it a 2 ETH bid vault sees ~980 selections/yr and
  +78–120%, bracketing `docs/KEEPER-ECONOMICS.md` (+62.7% mean, +121% closed form). Set
  `MATURE_MIN_N=0` to reproduce the raw backtest. **The externality math is exact; the activity *level*
  is a calibration choice, and the absolute APRs carry that uncertainty.** Relative conclusions (recipe
  ranking, keep vs bid, pool vs manager, the exposure curve) are robust to it.
- **L2 — steady-state listing count.** Each account holds a fixed `n = (capital − reserve)/(B+P+build)`
  through the year; allocated/settling downtime, budget binding and gate-driven pauses that the live
  keeper (`keeper/policy.py`) models are not simulated, so utilisation and selections are modest upper
  bounds. The forward sim is the authority on intra-year dynamics.
- **L3 — gas insensitivity.** Keeper pay is the capped quote `gas × min(basefee+0.05, 0.5 gwei)`, so
  depositor return is flat from 0.5 to 2 gwei. In reality, above the 0.5 gwei ceiling the keeper is
  underpaid and *stalls* (work defers), which the live keeper handles and this model does not — so the
  elevated-gas rows are an upper bound on realised return, not on keeper solvency.
- **L4 — fee throughput in float.** Yearly wei fees exceed int64, so the grid sums fee accrual in
  float ETH (rounded to wei); the wei-exact conservation path lives in `test_unified.py`.
- **L5 — selection independence.** Per-account selection counts are Poisson(µ) (≈220k independent
  events, each p≈1e-4), independent across accounts sharing one market — correct for portfolio tails,
  but it ignores the rare same-acquisition collision between two of our own listings (negligible at
  these probabilities).
- **L6 — exogenous keep rate.** Whether a purchaser keeps depends on the pack's Shapes beating the bid
  `d·B`, which is outside the model; it is swept 0–100% and is the single largest driver of the result.
- **L7 — manager clone deploy 250,000 gas is stated, not measured** (per the task); it is ≈0.00013 ETH
  at 0.5 gwei and immaterial to every verdict.

## Things that don't make sense (raised per holistic verification)

1. **Keep "doubles" bid, and that is the entire thesis — but it rests on an assumption the account
   cannot control.** The +186% keep headline collapses to +81% (the bid floor, 23% loss) if purchasers
   bid instead of keep. Purchasers keep only if the pack's Shapes are worth ≥ `d·B` ≈ 0.0585 ETH.
   If Shape secondary value is thin, the realistic number is the bid floor, not the keep ceiling. The
   study should not be read as "+186%" but as "+102% to +186% depending on a market behaviour we do not
   set." I flag this as the headline's load-bearing assumption.
2. **Gross fee throughput (64 ETH/yr on a 2 ETH vault) looks absurd until netted.** It is real FWA fee
   flow churned through ~950 selection cycles; in the bid world it is almost entirely offset by backing
   loss (net ~+1.6 ETH), and in the keep world it is offset by the pack given to each purchaser (`P`
   per keep). The large gross is not profit; only the net is. Verified by wei conservation.
3. **Recipe 2 beats the recommended recipe 4 on holder return (+380% vs +186%).** The recommendation
   stands only because recipe 2 is the legacy complex construction, pays the creator far less, and
   doubles our FWA exposure per ETH. If the owner weights holder return far above creator revenue and
   simplicity, recipe 2 (or a 0.03/0.04 direct pack *with a cheaper mint path*) deserves a second look —
   the model says the 0.03 size is more capital-efficient wherever its build cost can be made small
   enough to pass the restock gate.
4. **The 10% hurdle is never binding (lowest pass is +42%).** Either the opportunity is genuinely this
   rich at mature volume, or the activity level (L1/L2) is optimistic. Given (1) and the forward sim's
   more conservative +76%, treat the pass as comfortable but not a 10–20× margin of safety.
