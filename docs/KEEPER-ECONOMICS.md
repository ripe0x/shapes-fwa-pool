# Keeper economics: why the 2 ETH canary lost money, and the corrected numbers

Branch `claude/canary-keeper-economics`, built on PR 2 (`codex/incremental-position-integration`
22e5e23, which contains `main` 063b6c7). Decision D75. Evidence: `docs/receipts/keeper-economics.json`
(400 seeds per scenario), `docs/receipts/scan-gas.json`, fork tests named below.

## 1. Root cause of the −5.3% / 1.5 ETH figures

The replay is `sim/formal.py` at block 26,450,200 (`docs/receipts/formal-assessment.json`, D72),
reproduced exactly from that script and data: median −528 bps, mean +531, p10 −6,710, 9 of 16 seeds
lose, routine keeper pay 1.5252 ETH a year (16-seed mean, 0.5 gwei).

The owner's stated limits were checked against the code that replay ran (PR 2 head):

| Limit as stated | In the code | Holds? |
|---|---|---|
| TVL cap 2 ETH | `deploy/canary.json` `tvlCapWei` 2e18 | yes |
| Routine pay capped at 0.5 gwei | `gasCeilingWei` 0.5 gwei, `maxTip` 0.05 gwei, markup 0 | yes |
| Routine capacity 0.03 ETH refilling 0.0008 ETH/day (≤ 0.322 ETH year one) | capacity 0.03 ETH, **refill 0.01 ETH/day** (D71, engineering, 2026-11-18): up to 3.63 ETH year one | **no** (0.0008 is `main`'s value) |
| Request-funded checkpoints separate | processing pool, `pay(cap=pool)` skips budgets | yes |
| Essential compensation disabled | `essentialCapWei` 0 | yes |
| Unlisting and exit liquidation at caller's gas | D64 | yes |

Where the 1.525 ETH went (16-seed means, 0.5 gwei):

| Category | ETH/yr | Note |
|---|---:|---|
| Routine pay: journal sync | **1.203** | 92,120 global FWA records read on-chain per year (22,000 quoted gas each, 16.6k marginal measured) plus own bookkeeping |
| Routine pay: listing | 0.298 | 284 calls |
| Routine pay: building (restock) | 0.0245 | 7 calls |
| Routine pay: checkpoint | 0.0004 | |
| Request-funded checkpoint pay | 0.0004 | paid by requesters, not holders |
| Essential pay | 0 | disabled |
| Keeper operator expense not reimbursed | 0.006 | holder exit gas proxy |
| Mint fees (creator, not keeper) | 0.0139 | |
| Modeling errors | none found in cash flows | the simulator mirrors the contract; see §4 |

So the cost was real on-chain work the contract required, not a simulator miscount: PR 2's
completeness proof (D65) reads every completed global acquisition once the vault holds a listing.
It scales with FWA's activity (16,694 sequence entries in the 30-day window), not with the vault.
With the 0.01 ETH/day refill the budget allowed it; with 0.0008 it would have stalled the journal.

## 2. Which FWA actions need a vault transaction

Real FWA events in the gate window (30 days to the pin, `sim/data/fwa.sqlite`):

| FWA activity | Count / 30 d | Vault transaction needed? |
|---|---:|---|
| Global acquisitions (sequence entries) | 16,694 (11,604 fulfilled, 5,090 slippage refunds) | Before: every entry read on-chain. Now: none for a vault with ≤ 93 open positions |
| Acquisitions selecting a vault listing | counterfactual (vault absent) | yes: one paid sync applies the selection and resolves its outcome |
| Fee accrual (`EarningsAccrued`) | 170,752 | no: FWA's accumulator; collected inside paid sync or checkpoint |
| Reconciliation (bid return, keep receipt, expiry reclaim) | per own selection | yes, in the same paid sync |
| Harvesting | — | no standalone call (D70) |
| Pack building / relisting | per own bid return | yes: `restock` / `list` |
| Checkpoints | per holder flow | yes, request-funded |
| Off-chain scanning (event index) | all | no: keeper reads logs for free |

## 3. Fixes

1. **Contract (smallest safe change).** `src/ScanLib.sol` + `VaultLib._syncChanges`: read the
   vault's own open listings (29,337 gas each, `ScanGas.t.sol`) instead of the global journal when
   that costs no more than the next journal batch; pay the scan only when it applies an own
   selection or is the required checkpoint tail. PackVault unchanged. Removed dead `cycleNet` and
   internalized helpers for EIP-170 size. `script/release.py` handles the second library (CREATE2
   addresses match a `forge script` simulation).
2. **Keeper scheduling.** No work for FWA's global activity alone; wait for each own selection to
   settle or expire and resolve it in one paid call; ride terminal/cleanup work on the next paid scan
   unless holders need it; in a checkpoint window, the paid scan first.
3. **Simulator.** Mirror of the scan path (wei-exact fork reconcile, `ForkScanReconcile.t.sol` +
   `sim/reconcile.py`); 6.6× faster with result-identical caches; time-weighted diagnostics.
4. **Payment formula unchanged** (quoted gas × min(basefee + 0.05, 0.5 gwei) + 0.00002 ETH per work
   unit, 0% premium). Calls are now counted per vault event and batched; the paid scan bills 272,738
   gas against a 295,000 quote (keeper margin 7.5%), so no lower pay is justified.

## 4. Results (same demand throughout: the actual trailing 30 days, in-window bids, tokens at zero)

### 2 ETH canary, actual `deploy/canary.json` (400 seeds per row; `docs/receipts/keeper-economics.json`)

| Gas (total price) | Mean | Median | p10 | p5 | P(loss) | Fees − backing lost | Routine keeper | Checkpoint (request-funded) | Mint fees | Unreimbursed exit gas | Holder net on exit |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0.15 gwei | +113.0% | +87.9% | −48.1% | −61.0% | 23.5% | 2.693 | 0.428 | 0.0001 | 0.0244 | 0.0067 | +2.216 ETH |
| **0.5 gwei (gate)** | **+62.7%** | **+40.5%** | −61.6% | −67.4% | **33.0%** | 2.241 | 0.970 | 0.0004 | 0.0181 | 0.0161 | +1.229 ETH |
| 0.5, 2 gwei days 30–120 | +46.3% | +31.7% | −57.2% | −64.6% | 35.2% | 1.652 | 0.710 | 0.0004 | 0.0156 | 0.0149 | +0.907 ETH |
| 0.5, 1 gwei from day 30 | +3.3% | +2.0% | −26.6% | −32.6% | 45.5% | 0.168 | 0.092 | 0.0004 | 0.0081 | 0.0053 | +0.064 ETH |

| Gas | Keeper calls sync / list / restock / checkpoint | Paid sync / list / restock ETH | Own selections | Scans (listings read) | Global records read / never read | Waiting for gas | Terminal work deferred | Avg positions / deployed |
|---|---|---|---:|---|---|---:|---:|---|
| 0.15 | 1,104 / 586 / 12 / 2.6 | 0.194 / 0.219 / 0.014 | 1,322 | 599 (20.0) | 8,828 / 169,320 | 0 h | 329 h | 20.1 / 1.53 ETH |
| 0.5 | 783 / 429 / 10 / 2.5 | 0.444 / 0.494 / 0.032 | 982 | 529 (18.0) | 6,796 / 167,384 | 0 h | 353 h | 17.1 / 1.36 ETH |
| 2 gwei spike | 571 / 319 / 8 / 2.5 | 0.316 / 0.367 / 0.028 | 724 | 403 (17.0) | 4,216 / 178,247 | 2,160 h | 262 h | 15.3 / 1.22 ETH |
| 1 gwei from day 30 | 63 / 39 / 4 / 2.5 | 0.034 / 0.044 / 0.014 | 89 | 50 (14.4) | 304 / 198,766 | 7,920 h | 34 h | 12.7 / 1.02 ETH |

Before (16 seeds, `docs/receipts/formal-assessment.json`, reproduced exactly): median −5.3%, mean
+5.3%, p10 −67%, 9 of 16 lose, routine keeper 1.525 ETH, fees − backing lost 1.656 ETH.

### 6.8 and 20 ETH, `deploy/mainnet.json` (routine 0.1 ETH, 0.02 ETH/day), 0.5 gwei — 32 seeds only

| Vault | Mean | Median | p10 | p5 | P(loss) | Fees − lost | Routine keeper (sync / list / restock) | Scans | Global records read | Avg positions | Before (16 seeds): median, keeper |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---|
| 6.8 ETH | +65.3% | +68.9% | +1.3% | −15.0% | 9.4% | 8.36 | 3.78 (1.85 / 1.83 / 0.11) | 471 | 61,802 | 67.5 | +76%, 4.44 ETH |
| 20 ETH | +47.3% | +41.2% | +16.3% | +5.7% | 3.1% | 16.13 | 6.38 (2.78 / 3.36 / 0.24) | 31 | 97,904 | 156.8 | +49%, 6.52 ETH |

Above 93 open positions the journal stays (it is cheaper there), so 20 ETH changes little; its
routine budget binds (248k unfunded retries). Medians differ from the old 16-seed rows within
sampling noise at these seed counts.

### Why the results differ from the old simulation

1. Journal reads are gone for vaults with ≤ 93 open positions: 92,120 paid global reads a year
   become about 530 paid scans reading 18 own listings each (−1.2 ETH a year at 0.5 gwei).
2. The keeper no longer syncs at allocation and again at settlement; one paid call does both.
3. The routine budget stops binding (unfunded attempts 23,277 a seed before, about 16,400 now,
   mostly brief retries at the 0.03 ETH cap), so the vault stays deployed (17 vs 13 positions) and
   earns more cycles (982 vs 582 selections), which is why listing pay rose and gross edge grew.

## 5. The 2 ETH canary against the owner's requirements

| Requirement | Result |
|---|---|
| No minimum TVL to start | holds: operates from the first deposit; unexposed history is skipped free (D67) |
| Fixed costs scale down for small vaults | **now holds**: upkeep scales with the vault's own listings (scan), not FWA's 16,694 entries a month |
| Maintenance pays for itself | holds: keeper pay 0.97 ETH a year against 2.24 ETH gross edge at 0.5 gwei; every paid scan bills below its quote |
| ≥ 10% a year after gas, trailing 30 days, tokens zero, 0.5 gwei | **passes the gate as defined (median +40.5%, mean +62.7%)**; P(loss) 33%, p10 −62% |
| Depositor assets fully protected | holds for safety: liabilities never fund keepers (ScanSync j, O5); exits complete in every run (400/400). Market risk is not protected: a third of years lose |

The loss tail is selection luck, not cost: each selection costs the full backing and fees return
about 4.6% more on average (pooled over 400 runs), so a year with few selections (536 vs 1,201 in
winning years) loses. A larger vault averages it out. Diagnostics at 100 seeds (busiest day removed,
0.0008 ETH/day refill, 6.8/20 ETH spikes) were not completed in this pass.

## 6. Limits

- 6.8 and 20 ETH were run at 32 seeds, not 400, and only at 0.5 gwei (time).
- Gas is constant per scenario apart from the spike paths; reverted races and inclusion delay are not
  charged. Purchasers bid inside the window (formal method).
- `Q_SCAN` margin is 2.2% per listing (29,337 measured vs 30,000); a costlier FWA read would erode it.
- Two 301-listing fork tests fail on the PR 2 head as before (memory/gas limit), unchanged.
- No owner signature, merge, deployment or spending.
