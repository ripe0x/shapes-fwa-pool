> **Current: [docs/UNIFIED-SYSTEM.md](UNIFIED-SYSTEM.md)** and the release package [docs/release/](release/RUNBOOK.md) (2026-11-21). One strategy implementation for the pooled vault and personal managers (D77–D85). Everything below the line is history for earlier candidates.

**2026-11-23 checkpoint timing review (D86):** the `codex/adversarial-checkpoint-nav` candidate repairs cancellable-escrow redemption delay and refunds checkpoint charges when every request cancels. A real FWA selection replay measured a bounded keep-timing shift of 1,057,625,183,394,753 wei to a new 1 ETH depositor's marked claim; no profitable completed exit was demonstrated. Full evidence, exact scope and open gaps: [checkpoint-timing-adversarial.md](receipts/checkpoint-timing-adversarial.md). The changed vault bytecode invalidates the prior release identity and owner signatures for this candidate. It is not approved for deployment.

# Unified system, release candidate (2026-11-21)

Branch `claude/unified-shapes-fwa-system-852d17`, draft PR ripe0x/shapes-fwa-pool#5. Final source verified: 276 fork tests, scale 3/3, reconciler to the wei, 16 asset-flow regimes with outcomes O1–O11, all 17 production rehearsal steps, the keeper image's fork rehearsal in CI, independent review with no critical, high or medium finding. FWA payments are resolved from FWA's own record even when a receipt is missing (D84); pricing cost is bounded (32 allocation entries). Purchaser gas is a fixed 2 gwei bound (D85). The matched recipe comparison keeps 0.06 ETH packs. Formal gate at 0.5 gwei: median +70.6% (1.96 ETH, 5/16 runs lose), +55.9% (6.8 ETH), +37.7% (20 ETH, none lose). Not deployed; acceptance package unsigned (`docs/release/acceptance.json`).

---

> **Current release instructions: [docs/release/RUNBOOK.md](release/RUNBOOK.md)** (2026-11-19). This document is history for the candidate it names; where it gives current instructions, the runbook replaces them.

# Complete operating pass

2026-11-18. The remaining contract, keeper and economic changes are implemented together. Standalone harvesting is caller funded. Economical fee credit and the smallest necessary active fee prefix can fund verified sync work, with protected cash, fee share, budget and distribution checks enforced onchain. The keeper uses bounded exact preflight alternatives and the model follows the same indexed candidates.

Paid primary shapes mints, mint fees, the split and pack recipe, one authoritative book and the absence of a total position ceiling are preserved. Routine spending is funded by actual vault cash. The refill is sized from complete operation and exit scenarios, including a 90 day permission drift check; creator revenue is separate.

**Current result and evidence: [Complete operating pass](COMPLETE-OPERATING-PASS.md).** That document is the current decision record and explains the precise receipt and simulation scope. The original O2 threshold still fails at 1,919,655 versus 1,750,000; O6 remains 0.0002 ETH. PR 2 remains draft, with no merge, public deployment or new outcome signature.

Everything below is historical evidence for its named revision. Its proposed next steps and missing evidence statements are superseded by the current pass above.

---

# Efficient journal revision: candidate measured, economics blocked

2026-11-18. The approved baseline and amended candidate passed: **517/540 transactions**, **27.869594973162081536/32 simulated ETH** aggregate value, 8.3 ETH funded once, no topups. The 199-transaction candidate required no repair. The owned 8559 node is restored to entry; 8557 is untouched. Code remains `aa38fab`.

All 24 candidate journal cases show positive operator-calibration keeper net, positive exact signed-estimate headroom and accepted ordinary preflight. Default holder/distribution singleton bills are 122,417/202,270 gas against 132,000/212,000 quotes; full 128 bills 2,233,071 against 2,901,000. Processing-pool/holder protection and routine classification pass. Calibration sends use `minPay=0`; signed 80% preflight is separate evidence. Refunded records do not prove successful-foreign costs.

The baseline standalone full-holder checkpoint bills 346,017 gas and passes ordinary preflight at 0.2/0.5/2 gwei. O6 remains 0.0002 ETH; O2 remains 1,919,655 versus 1,750,000. Runtime 24,451/23,001 bytes. The candidate did not repeat the full-holder baseline fixture. No outcome, allowance, fee, minimum TVL or sponsorship assumption changed; no public deployment or release acceptance.

The corrected conditional timed model completes 3/4 exits, but only zero demand pays every routine job. Frequent harvesting remains an economic blocker.32 of 44 timely underpaid holder harvests hit the existing 25% fee-share zero-payment gate, so permission alone cannot pay those same calls. A bot-only scheduling improvement also cannot constrain other permissionless callers.

Current receipts: `receipts/efficient-journal-candidate-summary.json`; proposed next work and complete conditional cash/return table: `REVIEW-FUNDING-PROPOSAL.md`; detailed scope/history: `EFFICIENT-JOURNAL-RESULTS.md`.

Things that don't make sense: global expense follows unrelated activity; gross fees also replace backing transferred out; complete claims can depend on underpaid routine work. The PR stays draft.

Everything below is prior revision evidence for its named source, retained as history.

---

# Current review repair

2026-11-18. Empty-vault bootstrap capital is protected by the owner-approved unexposed cursor
advance (D67). The keeper image installs pinned dependencies and persists both stores under
`/data`; actual image startup and two-container persistence passed. Packaging commit: `2f3ca40`.
Verified vault/keeper/model repair and focused evidence commit: `6319d5e`.
Checkpoint calibration and final affected verification commit: `e948b1e`.

Three bootstrap and five real exposure/admission tests pass. The new mutating checkpoint gate
rejects an unseen own selection/receipt, then succeeds after reconciliation. Four exact receiver
checks and both fork/model reconciliations pass. Current runtime is 24,322 bytes, 254 below EIP-170.

**Acceptance remains blocked.** O2 is still 1,919,655 quoted gas versus 1,750,000. Checkpoint's gas
component is now 360,000, meeting O6's existing 0.0002 ETH limit, with fresh affected fork checks.
Exposed global maintenance funding remains insufficient in the recorded window. No journal quote,
cap, refill, accepted outcome or signature changed. Actual billed full-holder checkpoint evidence
remains a release gap; the calibration uses bounded executed-fork refund measurements.

The owner-approved replacement local batch passed: 77/80 transactions, 1.755867382438961584/3 ETH
aggregate transaction value, exactly 3 simulated ETH initial funding and no topups. Real refunded
prefixes/tails and an exposed zero-essential-budget exit are recorded on the preceding Q400 source.
The exit's six calls cost 0.0003838206 ETH gas at 0.2 gwei and paid only 0.0001 ETH checkpoint pay.
Its entry snapshot is restored; owned PID 98279 remains at port 8557 with an empty pool. The
earlier PID 10583 observation below is historical.

Current evidence and exact limits: `POSITION-INTEGRATION-ACCEPTANCE.md` review repair section.
Funding and return options: `REVIEW-FUNDING-PROPOSAL.md`.

Things that don't make sense: global costs scale with all FWA activity while small-vault income
does not; zero-funded essential exits include foreign history; larger allowances supply no cash.

---

# Earlier position-accounting integration

2026-11-18. **Implemented and locally verified; milestone acceptance is blocked by maintenance
funding and changed economic outcomes.** Branch `codex/incremental-position-integration` starts at
research handoff `f75ee77` (proof `3b9cd65`, main baseline `063b6c7`).

Production/test/deployment commit: `909e761`. Keeper/simulation commit: `c93ac2f`.
The implementation removes the total position ceiling, full valuation and ordinary keeper scans.
One exact book, ordered global journal, authenticated receipts and fee witness now price the
existing share vault. Paid primary mints, their fees, the mint/split/pack recipe, pack sizing and
holder rules remain. There is no factory, shared exposure book or new holder charge policy.

- Final affected regressions: **52/52**, plus detailed final receiver traces and the separate real
  301-listing setup. All 13 failures from the first 120/133 broad run are preserved and resolved by
  affected passing checks. The reused eight-test production model includes 40,960 steps and
  301/1,000/10,000 bookkeeping positions; it is not 10,000 external FWA listings.
- Exact production receiver: **46,462 gas keep / 69,730 kick**, at least 30,270 below the 100,000
  stipend; all 99 sampled gas boundaries record or fail atomically. Every measured maximum
  operation fits 16,777,216 with 25% margin. Runtime is **24,549 bytes**, only 27 below EIP-170.
- Both Python/fork traces match every financial bucket to the wei; ten accounting tests and seven
  focused forward scenarios pass. Final quiet local lifecycle: 29 listings, 20 keeper transactions,
  no reverted receipts, full holder exit and zero ledger gap. Root's pinned readback confirms no
  positions, inventory, allocations, pending receipts or holder requests; 2 wei rounding reserve
  remains beside the dead-share seed slice.
- Independent implementation review covered immutable production and keeper inputs and affected
  repairs. It is not a full security audit or release approval.

**Unchanged settings do not fund continuous journal progress.** At 0.5 gwei the recorded 30-day
global-only quote is at least 0.3227925 ETH, against at most 0.25 ETH of mainnet routine budget:
0.0727925 ETH shortfall before own work. Canary's 0.054 ETH permits less than the 0.129117 ETH
quote even at 0.2 gwei. The 0.005 ETH reserve covers individual batches, not the recurring cost.
No budget, reserve, mint fee or keeper maximum was raised to make this appear affordable.

The asset gate exits 2. O2 is **1,919,655 quoted gas versus 1,750,000**; O6 is **0.00022 ETH versus
0.0002 ETH**. Every asset-flow bucket balances across 16 regimes, but the historical signature
and outcomes do not approve this changed candidate. No new signature is supplied.

Details, exact inputs/commands, gas, deployment receipts, budget options and gaps:
`POSITION-INTEGRATION-ACCEPTANCE.md`. Draft PR body: `POSITION-INTEGRATION-PR.md`. One-screen
scorecard: `receipts/integration-economic-scorecard.md`.

Only the explicitly approved isolated local batch ran. No public-network transaction, real funds,
push, merge or owner signature occurred. Local node PID 10583 and the paused original driver
PID 10551 remain preserved at 127.0.0.1:8557. Current pending/queued pools are empty.

Next action: review the funding/outcome proposal in the acceptance report before changing policy
or preparing a funded release candidate. The current annual return report is historical.

Things that don't make sense: each vault must pay for new global FWA activity even without an
own selection. Conservatively quoting batches while some singleton calls lose money also means
balanced books and an affordable single batch cannot establish continuous keeper liveness.

---

The report below is historical evidence for the earlier main candidate and is not a release
recommendation for this integration.

# PackVault: validation and repair report

2026-11-16, second pass. Scope: does the automation work, are the performance claims supported,
is a small private canary technically justified. Owner decisions applied the same day (D42 to
D44) are in section 8. Decisions D32 to D44 in `docs/DECISIONS.md`;
proposed outcomes in `OWNER-REQUIREMENTS.md` section B2; economics in `sim/out/forward.md` and
`sim/out/backtest_audit.md`. Earlier reports are in git history (1b8cf91, 847b3fe).

## Bottom line

- **A critical custody defect was open and is fixed.** ETH settled to a holder but not yet
  claimed counted as free, so keepers could deploy it or be paid from it (reproduced: 1.0 ETH
  owed, 0.35 ETH left). It is now a tracked liability (D32).
- **FWA token rewards are now claimed and burned, never sold** (owner, D43). Selling was not
  self-funding at canary size (8.2e12 wei of tokens against 5.0e13 wei of gas pay); the sale
  path is deleted and PackVault shrank to 22,206 bytes.
- **The published backtest (+2,731%) was not a return estimate.** It counted refunded requests as
  revenue and relisted vault positions instantly while FWA's pool drained on Oct 31. With only
  successful acquisitions and real settlement, keeper timing, cash and staging, the same 30 days
  give +169% annualized, matching the closed form (+166%) at the true volume (D38, D39).
- **Returns at current activity:** 100 positions, last 14 days' activity (71 a day), 0.15 gwei:
  mean +20.3% a year, 17% chance of a losing year (95% interval 13 to 21%), with quoted keeper
  pay and request charges (D56).
- **Keeper pay is a fixed quote paid through a replaceable policy contract (D56, D57).** Caller
  gas and tip change nothing; budgets cap all pay at 0.041 ETH a day at canary values. Two High
  defects found in this work are fixed (section 14).
- **Gas is the binding risk.** The gas ceiling is now 0.5 gwei and the gate passes there (+132%
  closed form, +78.5% simulated; D42). Above it the keeper waits instead of spending: with 1.0
  gwei from day 30 the year is +3.1% (34% chance of loss).
- **Recommendation: proceed with the approved private canary** (28 positions fit, not 30), with
  your own keeper running `--burn-tokens`. No critical or high defect is open;
  every lifecycle step except acquisitions selecting vault listings ran through the production
  keeper on a local fork, and those ran on real VRF in the Solidity fork tests.

## 1. Findings

### Confirmed and fixed

| # | Severity | Finding | Fix | Regression |
|---|---|---|---|---|
| V1 | Critical | Settled-but-unclaimed ETH counted as free: deployable and payable to keepers | `claimableTotal` liability in `_free()` | `test_settledUnclaimedEthIsNotDeployable`, invariant |
| V2 | High | Keeper never harvested token rewards (`token_pending_eth` never set); valued tokens at the reference floor; proposed sales above `clipMax` that could only revert; one stale id blocked the claim and the credit | `convert(ids, maxAmount, minOut)` claims (stale-safe), withdraws credit, sells at most `clipMax`; keeper reads real entitlements and simulates the exact sale | 6 token fork tests; canary rehearsal |
| V3 | High | Unlisting (and so wind-down and redemption liquidity) reverted when FWA's owner repointed the oracle to a failing contract | Raw `staticcall` oracle read; failure means no cap | `test_windDownSurvivesBrokenOracle` |
| V4 | High (economic) | Revenue counted acquisition requests; 28% of the last 30 days' requests were refunded and paid nothing | Successful selections only, everywhere | `sim/out/backtest_audit.md` section 1 |
| V5 | High (reporting) | Backtest assumed instant, free, unlimited relisting during a pool drain | Executable replay; instant replay labelled theoretical | `sim/out/backtest_audit.md` sections 2 to 4 |
| V6 | Medium | Staged listings (listed while FWA's queue is busy) earn nothing and the keeper never activated them | Paid `activate(ids, maxCount)` | ForkReconcile (a listing FWA really staged) |
| V7 | Medium | `sync` and `unlist` reimbursed padding (junk ids) at the 10% premium | Pay capped at 300k gas per position moved | `test_paddedSyncPaysOnlyForWorkDone` |
| V8 | Medium | Keeper bid the node's price (1 gwei tip on anvil) but is reimbursed at basefee + 0.05 gwei: lost money every call | Keeper bids basefee + `maxTip` | canary rehearsal: keeper net +0.0011 ETH |
| V9 | Medium | Keeper planned a whole pass from one read; dependent steps used stale state | One call at a time, re-read after each | canary rehearsal |
| V10 | Low | A no-op checkpoint used up the 12 h slot ahead of later flows (second review) | Refused unless flows or distributions | `test_idleCheckpointUnpaid` |
| V11 | Medium (evidence) | Overnight rehearsal used anvil dev accounts; one is a real mainnet address with an EIP-7702 delegation that diverted keeper pay | Fresh checked addresses; `rehearse.sh` removed | `keeper/rehearse_canary.py` |
| V12 | Low (presentation) | `nan` percentiles, segment percentiles averaged, raw vs annualized mixed, 200 runs | Removed; continuous P&L; raw and annualized separate; 400 runs and 95% intervals | `sim/out/forward.md` |

### Verified, no defect

- Liabilities: every spend path (restock, list, distribution, keeper pay) is gated on `_idle()` or
  `_free()`, which subtract all four liabilities (both independent reviews).
- Worst supported checkpoint: 300 positions all kicked and unsynced, 10.17M gas (39% under the
  16,777,216 cap), NAV exact to the wei (`test_checkpointGasAllPositionsKickedUnsynced`); all
  active, 9.83M.
- Admission changes: FWA's `canDeposit` makes no oracle call; with admission off the vault stops
  listing and still unlists by k.
- Withdrawals never redeploy cash owed to exiting holders (`_idle` excludes the owed estimate and
  claimables; the keeper deploys nothing in a pass that frees redemption cash).

### Rejected or reclassified

- "Annualized below -100% is a bug": not by itself. Short-window annualization of a raw loss can
  go below -100%; every raw loss in the simulations stays above -100% (worst raw year -50.5%).
- "Oct 31 is a reconstruction error": rejected. Rebuilt pool weight matches FWA's `totalWeight`
  at all 18,377 requests (max error 0.0000%); the drain was real. What a vault could not do is
  capture it.

## 2. Backtest versus closed form, explained

Same window (last 30 days), 30 positions, 0.15 gwei, annualized means, 300 draws:

| Model | Annualized | What it assumes |
|---|---|---|
| A. Published backtest | +2,865% | requests are revenue; 30 listings always active |
| B. Successful selections only | +700% | fees only where FWA distributed them |
| C. + real settlement delay, 10 min keeper | +362% | packs wait for the purchaser (median 2 min, 99th pct 5 h) |
| D. + relists funded by earned fees | +314% | no outside capital |
| E. + staging while FWA's queue is busy | **+169%** | a relist earns nothing until activated |
| Closed form, today's pool, 442 successful/day | +166% | stationary pool |

Oct 31 (UTC) explains the gap. Between 02:00 and 05:00 FWA's active listings fell from 2,084 to
18 and its pool weight from 31,412 to 161 (1/ETH); 30 always-active vault listings would have
taken 62% to 84% of selections. A to C let a position cycle many times in those hours. In reality
FWA's queue never drained that day, so a relist stayed staged (E), and the day contributes +4%
raw (E) instead of +217% (A). Outside Oct 31 every model agrees within noise (+113% to +135%
annualized at 312 successful/day vs +117% closed form). Residual: over the full window B is 16%
below the closed form on the window's own pool, because FWA prices the fee at request time and
sets selection odds at processing, and the pool shrank in between during the drain.

## 3. Returns and downside (forward simulation)

One year, 400 runs per row, reconciled vault model, live keeper policy, real cash, inventory,
settlement, position limits and withdrawal liabilities; tokens at zero; raw year = annual.

| Scenario | Positions target/mean/max | Mean | p5 | P(losing year) [95%] |
|---|---|---|---|---|
| Gate window (trailing 30 d, successful), 0.15 gwei | 100/131/262 | +123% | +23% | 3% [2-5] |
| Same without Oct 31 | 100/136/238 | +105% | +12% | 2% [1-5] |
| Last 7 d (97/day) | 100/111/148 | +32% | -9% | 12% [9-16] |
| Last 14 d (71/day) | 30/31/46 | +20% | -36% | 34% [29-39] |
| Last 14 d | 100/105/136 | +21% | -14% | 18% [14-22] |
| Last 14 d | 300/297/300 | +20% | +3% | 2% [1-4] |
| 15/day | 100/98/109 | +2% | -12% | 42% [38-47] |
| Decline 97 to 10/day | 100/104/120 | +11% | -11% | 26% [22-31] |
| Inactive after 60 days | 100/97/112 | +3% | -9% | 37% [33-42] |
| Last 14 d at the 0.5 gwei ceiling | 100/98/126 | +9% | -23% | 32% [28-37] |
| Enter at 0.15 gwei, 0.4 gwei from day 30 | 100/101/130 | +14% | -17% | 26% [22-30] |
| Enter at 0.15 gwei, 1.0 gwei (above ceiling) from day 30 | 100/100/108 | +3% | -9% | 36% [31-40] |
| Enter at 0.15, 2.0 gwei (above ceiling) days 30-120 | 100/103/131 | +17% | -13% | 19% [15-23] |
| 1.2 gwei with a cheap day every 7 | 100/107/132 | +22% | -12% | 14% [11-18] |
| 50% redemption at day 120 in 7 congested days | 100/66/117 | +14% | -13% | 22% [19-27] |
| Crown share to 5% at day 90 (vault unwinds) | 100/24/114 | +4% | -12% | 33% [29-38] |
| 11% of purchasers keep | 100/118/149 | +38% | 0% | 5% [3-8] |

Positions grow above the target as NAV compounds (cap 300). Worst single year in any row: -50.5%
raw (30 positions). Gas above the 0.5 gwei ceiling costs little: the keeper stops, listed
positions keep earning, sold ones wait to relist. Sustained gas just under the ceiling is what
hurts: at 0.5 gwei all year keeper gas is 13% of deposits and the year is +9%.

**Formal gate (owner's definition, trailing 30 days, tokens zero):**

| Gas | Net per bid cycle | Closed form | Forward simulation (cold start) | 10%? |
|---|---|---|---|---|
| 0.15 gwei (spot at pinned block) | +1.232 mETH | +156% | +104.7% (p5 +2.6%) | yes |
| 0.5 gwei (gas ceiling, D42) | +1.046 mETH | +132% | +78.5% (p5 -8.6%) | yes |

The gate passes at the ceiling. The 30-day figure is several times the return at the current run
rate (+9% to +21% at last-14-day activity) and should not be shown to holders as expected.

**Thresholds revalidated against measured gas:** bid cycle 0.8M gas (sync 158k + relist 499k to
570k + harvest share + 2 x 30k overhead): break-even 1.59 gwei. New pack build measured 921k +
30k: payback in one cycle below 0.58 gwei (0.54 with the contract's conservative 1.05M constant).

**Keeper economics:** in the canary rehearsal the keeper was paid 0.00715 ETH for 0.00605 ETH of
gas actually spent (+18%: 10% premium plus the 30k overhead). When inclusion needs a priority
fee above `maxTip` (0.05 gwei), every call loses about 1 mETH per million gas per extra gwei of
tip (a 100-position checkpoint, 3.4M gas, costs 3.4 mETH more per gwei); an unsubsidized keeper
waits and redemptions are delayed, not lost. The admin can raise `maxTip` through the delay.

**Tokens:** claimed and burned (D43); zero in NAV as before.

## 4. Canary configuration, validated

`deploy/canary.example.json` exactly (2 ETH TVL cap, 0.01 ETH seed, 0.05 ETH reserve, 30-position
limit, 0.5 gwei ceiling, 0.05 gwei maxTip, 10% premium, 10% allocation bound, 2-day delay)
through `script/Deploy.s.sol` and `keeper/keeper.py` on an anvil fork of block 26,418,539
(`keeper/rehearse_canary.py`, result in `sim/out/canary-rehearsal.json`), rerun on the final
contract:

- Deposit 1.99 ETH accepted; a further 0.02 ETH refused by the cap. **28 positions** built and
  listed (30 do not fit: 30 x 0.0663 + mints and reserve exceed 2 ETH); 0.018 ETH stays idle.
- Real permissionless fee payout and buyback: 4.87 FWA tokens to the 28 listings; without the
  opt-in the keeper left them and said so; with `--burn-tokens` it claimed and burned all of
  them (supply fell by exactly that amount, vault ETH unchanged, keeper gas 3.4e13 wei).
- Oracle owner lowered the ask, anyone kicked a listing: the keeper synced and relisted it.
- Partial withdrawal with the keeper interrupted after one call and restarted from chain state;
  full withdrawal; wind-down to empty.
- Ledger to the wei: seed + deposits = claims + keeper pay + mint fees + balance.
  Holder: -0.016 ETH on 1.99 ETH (-0.8%) with no acquisitions in the window, i.e. the entry and
  exit cost (9 mints = 0.009 ETH, keeper gas 0.0071 ETH). Keeper: +0.0011 ETH net.
- Not reachable locally: acquisitions selecting vault listings (VRF proofs bind the original
  block hash). Covered by the Solidity fork tests on real VRF replays (bid, keep, silent
  purchaser, fee shares) and the to-the-wei reconciliation.

## 5. Reproduce

```sh
forge build --sizes   # PackVault 22,206 bytes (2,370 under EIP-170), VaultLib 1,929
forge test --match-path "test/fork/*.t.sol" --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100   # 41 pass
python3 sim/reconcile.py              # after ForkReconcile: model = fork, to the wei
python3 sim/backtest_audit.py 300 && python3 sim/backtest_audit.py --compare
python3 sim/forward.py 400
anvil --fork-url https://mainnet.gateway.tenderly.co --fork-block-number 26418539 --port 8547 --base-fee 150000000
python3 keeper/rehearse_canary.py
```

Pinned blocks: 26,424,971 (lifecycle and adversarial suites), 26,417,086 and 26,405,703 (VRF
replays), 26,423,454 (buyback), 26,418,539 (canary rehearsal). Data: `sim/data/fwa.sqlite`,
events through block 26,425,500.

## 6. Remaining limitations and untested paths

- A failed pack delivery (FWA's stuck-NFT path) cannot be produced with the deployed ShapePacks
  without mocks; covered by review only (D23).
- Live keeper competition, mempool congestion and real priority fees: canary only.
- Acquisitions selecting vault listings through the production keeper: not reachable locally.
- Staging and `activate` under a long foreign backlog (review LOW-2): pays for others' listings.
- Simulations assume a stationary pool apart from the stated scenarios, rational purchasers,
  theoretical selection weights (history shows low-backing listings picked 1.5 to 6% less, which
  would help the vault), and a daily step (one selection per position per day).
- Invariant campaigns are shallow (16 x 25); defect V1 was found by review, not by fuzzing.
- External audit, legal review and a mainnet canary are not done.

## 7. Decisions for the owner

Answered 2026-11-16 (sections 8, 9): canary approved; no gas stop rule; tokens burned, unpaid,
public; gate at the 0.5 gwei ceiling. Open:
1. **Guardian and admin addresses** (one address may hold both, D44).
2. **Sign `asset-flow.json`** (10 DRAFT outcomes, all OK in 16 regimes; hash
   `f23d05389860157fa782341e3a3cff2065e92d3d4f61a3dd28f4176ee0fcc3b0`; signing commands in
   `~/.agents/guidance/asset-flow-kit/README.md`). Until signed the gate reports INCOMPLETE.
3. ~~Keeper loss allowance~~: answered: the keeper stops above the ceiling (`--max-loss-wei 0`, the
   default); holders or anyone may still call any step, reimbursed at the ceiling price (D51).
4. Sign off section B2 of `OWNER-REQUIREMENTS.md`.

## 8. Owner decisions applied (2026-11-16)

| Decision | Change | Evidence |
|---|---|---|
| Gate tested at the gas ceiling, 0.5 gwei (D42) | `gasCeilingWei` 0.5 gwei in `deploy/canary.example.json`; simulation ceiling and gate at 0.5 | gate passes (section 3); canary rehearsal reran on the new values |
| No wind-down on gas; admin raises the ceiling (D42) | none: `proposeParams` plus the 2-day delay already does this | `test_paramsDelayAndBounds` |
| Claim and burn tokens, never sell (D43) | `convert`, the v4 swap and its three parameters removed; `burnTokens` added; keeper `--burn-tokens` | ForkTokens (3 tests: active, stale id plus credit, zero); canary rehearsal |
| One address for both roles (D44) | none | deploy takes the same address twice |

Verification after these changes (HEAD of this commit): `forge build --force` and `--sizes`; all
fork test suites, 41 pass; `sim/reconcile.py` exact; `sim/forward.py 400`; canary rehearsal
ledger gap 0. A separate reviewer read the burn diff: no critical or high issue. Fixed from it:
the keeper now passes only listings with pending tokens, 60 per call (a 20-listing burn measured
1.13M gas), and the rehearsal snapshots pending right before the burn. Accepted: the keeper burns
whenever anything is pending and only at or under the gas ceiling (operator cost about 3.4e13 wei
per burn at canary size). Open question from it: purchasers can take an FWA-token bid; the
simulation assumes ETH bids, as before this change.

## 9. Balancer review pass (2026-11-16, D45 to D50)

Compared with shapes-pool-balancer `05e6b60`; full table in `docs/BALANCER-COMPARISON.md`.

**Changed**
- **Keeper execution (`keeper/tx.py`, D47).** Persistent in-flight transaction saved before
  broadcast, same-nonce +25% replacement, lost-response lookup, receipts reconciled against
  `KeeperPaid`, reorg re-check, file lock, `/health`, `--status`, 14 status codes (wait vs action).
  Python kept: the simulation imports the policy.
- **Gas classes (D45).** Above the ceiling the keeper plans only liability work (redemptions,
  wind-down); a keeper pays the difference only within `--max-loss-wei`. Thresholds per operation
  in `docs/GAS.md`.
- **Reserve (D46).** Canary reserve 0.05 to 0.005 ETH, sized from obligations (0.0038 ETH need);
  no contract change. The 2 ETH canary builds 29 positions instead of 28.
- **Asset flow (D49).** The owner's asset-flow kit, 16 regimes on a real fork, ETH conserved to
  the wei in each, `docs/SYSTEM-MAP.md`, 10 DRAFT outcomes awaiting signature.
- **Unchanged:** contract bytecode, inventory planning (D48), token burn (unpaid, public, D50).

**Verified** (this commit; Tenderly fork, canary values unless stated)
| Check | Result |
|---|---|
| `python3 keeper/test_policy.py` | pass (gas classes, reserve need, status codes) |
| `python3 keeper/test_tx.py` (plain anvil) | 10 scenarios pass: preflight classes, receipt + pay, lock, restart with tx in flight, same-nonce replacement, lost response not broadcast, lost response broadcast, nonce used externally, work done by another keeper, reorg removal |
| `keeper/rehearse_canary.py` (fork 26,418,539) | 29 positions; ledger gap 0; keeper state file equals chain pay and gas to the wei (18 tx, net +0.000353 ETH); spike at 1.05 gwei: no-loss keeper waits, bounded-loss keeper releases 0.96 ETH and prices the redemption (keeper loss 0.00078 ETH); holder -0.0201 ETH on 1.99 ETH with zero acquisitions |
| `forge test --match-path test/scenario/VaultFlow.t.sol` | 16 regimes pass, 0 mismatches |
| asset-flow gate | INCOMPLETE only for the missing owner signature; all outcomes OK |
| `python3 sim/forward.py 400` | gate +116% (0.15 gwei) and +73% (0.5 gwei, p5 -10%); last 14 d, 100 positions +22.8%, P(loss) 16% [13-20]; whole year at the 0.5 gwei ceiling +12.0%, P(loss) 27%. Differences from the previous run are within about 2 standard errors (the reserve change deploys 0.6% more capital at 100 positions) |
| Independent keeper review | no double-send or fund-safety issue; fixed: reorg relocation recounted instead of uncounted, lost-response lookup covers downtime, expected reverts matched by selector, declined liability work raised as action, first broadcast counted as sent |

**Not tested:** a reorg that re-includes the same transaction elsewhere (anvil drops reorged
transactions and re-signing needs a key on the command line); several real selections in one fork
(only two VRF fixtures exist; the simulation covers bursts statistically); fees accruing while a
keeper sleeps (no real acquisition at the pinned rehearsal block).

**Canary readiness:** technically ready for the small private canary once the owner supplies the
role address(es) and signs the outcomes. No open defect. The economic case is unchanged: modest at
current activity (about +20% a year at 100 positions, 16% chance of a losing year), dependent on
gas staying under the ceiling.

## 10. Gas-price refusal removed (D51, 2026-11-16)

Owner decision: no call is refused for gas price; the ceiling only caps reimbursement. `restock`
and `list` now run at any gas price, paid at the 0.5 gwei ceiling price with the caller paying the
rest. The keeper still waits above the ceiling (`--max-loss-wei 0`). PackVault 22,171 bytes.
Verified after the change: 41 fork tests (new `test_buildAboveCeilingPaidAtCeilingPrice`: a
one-pack build at 2 gwei paid exactly gas x 0.5 gwei x 1.10), `sim/reconcile.py` exact, 16
asset-flow regimes with no mismatch (gate INCOMPLETE only for the signature; outcome hash
`0a0900c4...d9d1a3`), canary rehearsal unchanged (29 positions, ledger gap 0, keeper books equal
the chain). The DRAFT outcome tightening proposed in chat (O3, O5, O8 checks, O2 count, O9 as
information, a zero-demand holder cost bound) is done in section 11.

## 11. Outcomes tightened (D52)

All 10 DRAFT outcomes hold in all 16 regimes; gate INCOMPLETE only for the signature. Outcome
hash to sign: `f23d05389860157fa782341e3a3cff2065e92d3d4f61a3dd28f4176ee0fcc3b0`.

| # | Outcome | Measured |
|---|---|---|
| O1 | bid: backing leaves, vault keeps the pack | 0.0363 ETH |
| O2 | keeper gas per position built and listed (keeper batches) | 1.60M gas (bound 1.75M; at most 0.00096 ETH at the ceiling) |
| O3 | wind-down claim = holder's value share | 0 wei gap |
| O4 | left after wind-down | 0.0105 ETH (seed slice) |
| O5 | liabilities never spendable | 0 wei overlap; asserted after every keeper call |
| O6 | checkpoint pay at 2 gwei, priced at the ceiling | 0.000137 ETH |
| O7 | ETH paid for burning tokens | 0 |
| O8 | redemption paid with the oracle broken | 0.9975 of 1 ETH |
| O9 | holder cost with zero acquisitions | 0.46% (bound 1.5%) |
| O10 | staged relist activated | yes |

## 12. Outcomes signed (2026-11-17)

The owner signed outcome hash `f23d0538...0fcc3b0` with the `asset-flow` SSH key in the kit's
allowed signers. `asset_gate.py .` returns **PASS** (16 regimes, 10 outcomes). Remaining before a
canary deploy: an independent review recorded under `audit/` for the current source hash (the
deploy step runs the gate with `--require-review`), the guardian/admin address, and the owner's
deploy authorization.

## 13. Flat work fee for permissionless keepers (D55, 2026-11-17)

Owner decision: keep paying keepers gas plus 10%, and add a flat fee per unit of work so outside
keepers have a reason to run the vault. Canary fee 0.00002 ETH per unit (maximum 0.0001); units
are positions listed, resolved, activated or unlisted, items liquidated, and pricing checkpoints;
splitting work earns no extra fee. The guardian can lower the fee at once, and a guardian stop now
cancels any queued admin proposal. Cost: about 0.1% of deposits over a zero-acquisition canary
lifecycle; about 3% of the edge per bid cycle. Review record: `audit/rc-workfee/`. The changed O2
wording needs the owner's signature again (hash `f5100bae992f2ab5fb41c772707570d1dc5d7a0c0cdcd773317bc125927740bd`).
F1 (premium maximum 50%) is still open.

## 14. Quoted keeper pay and a replaceable payment policy (D56, D57, 2026-11-17)

**What changed.** Keeper pay no longer reads measured gas or the caller's gas price. Each
operation has a quoted gas figure; the vault's envelope is that quote at
`min(basefee + 0.05 gwei, 0.5 gwei)` plus 0.00002 ETH per unit of work (no premium at canary).
A separate policy contract proposes the payment; the vault pays the smallest of the offer, the
envelope, the funding cap, free ETH and a refilling budget. The policy is swapped through the
admin delay, anyone activates it, and the guardian cancels a queued one or stops all pay at once.
Deposits and redemptions now pay request charges for the work they cause (D56).

**Found and fixed during this work**
| # | Severity | Defect | Fix | Evidence |
|---|---|---|---|---|
| P1 | High (liveness) | Yul evaluated `and(staticcall, gt(returndatasize, 31))` right to left: the size check read the previous call's data, so every policy offer read 0 and keepers were paid nothing | bind the call result first | ForkKeeperPolicy (V1 pays its quote to the wei) |
| P2 | High | Security review H1: the deployment charge was stored as uint64; a charge above 18.4 ETH (one 40 ETH deposit at a 50 gwei ceiling) truncated, minting shares the checkpoint never added to the supply, and cancel could underflow `pendingChargeTotal`, blocking checkpoints | `PendingDeposit` is `uint96 amount, uint64 epoch, uint96 charge` (one slot; uint96 exceeds all ETH) | `test_largeDepositChargeNotTruncated` (20.5 ETH charge stored whole; holder shares = supply minted) |
| P3 | Low | Security review L1: `lowerCaps` could leave `maxTip` above a lowered ceiling, inflating the deployment charge | `lower` clamps `maxTip` to the new ceiling | `test_guardianCancelsPendingPolicy` |
| P4 | Evidence | Rehearsal ledger counted the quoted redemption charge, not the charge kept after the refund of any excess | count the vault's balance change | canary rehearsal ledger gap 0 |

**Evidence (this revision).** 80 Solidity tests pass (fork, audit, scenario). The reconciler matches
the Python model to the wei. `keeper/test_policy.py` passes. The canary rehearsal deploys with the
production script, runs the unchanged keeper, swaps V1 for a different-formula V2 mid-run (balance,
shares, NAV, positions and tokens unchanged across the swap), and closes the ledger and the keeper's
own accounting to the wei. PackVault 23,888 bytes then; 22,809 after D58.

**Keeper pay vs keeper cost per operation** (µETH; pay / cost (net); basefee shown, keeper bids
basefee + 0.05 gwei; cost from measured billed gas, `sim/out/gas-quotes.json`):

| Operation | 0.15 gwei | 0.5 gwei | 1.0 gwei | 1.5 gwei | 5 gwei |
|---|---|---|---|---|---|
| checkpoint, 23 positions | 203 / 195 (+8) | 478 / 536 (-58) | 478 / 1,024 (-546) | 478 / 1,512 (-1,034) | 478 / 4,926 (-4,448) |
| restock 10 (3 mints) | 1,976 / 1,824 (+152) | 4,640 / 5,017 (-377) | 4,640 / 9,578 (-4,938) | 4,640 / 14,138 (-9,498) | 4,640 / 46,063 (-41,423) |
| list 1 | 177 / 172 (+5) | 412 / 472 (-60) | 412 / 902 (-489) | 412 / 1,331 (-919) | 412 / 4,337 (-3,924) |
| list 10 | 1,311 / 1,158 (+153) | 2,978 / 3,185 (-207) | 2,978 / 6,080 (-3,103) | 2,978 / 8,976 (-5,998) | 2,978 / 29,244 (-26,266) |
| sync 3 (kicked) | 120 / 60 (+60) | 210 / 165 (+45) | 210 / 316 (-106) | 210 / 466 (-256) | 210 / 1,519 (-1,309) |
| unlist 8 | 480 / 333 (+147) | 960 / 917 (+43) | 960 / 1,751 (-791) | 960 / 2,584 (-1,624) | 960 / 8,419 (-7,459) |
| liquidate 1 | 65 / 50 (+15) | 133 / 138 (-5) | 133 / 263 (-130) | 133 / 388 (-255) | 133 / 1,263 (-1,131) |

Every operation pays below the ceiling (break-even near 0.45 gwei basefee). Above it, pay stops at
the ceiling price: the keeper waits for routine work, and liability work runs only when a caller
accepts the loss (D45, D51).

**Worst-case keeper spend** (budgets bound all pay, checkpoints included): canary 0.041 ETH in any
24 h, 0.405 ETH a year; at the bytecode maxima 0.415 ETH in 24 h, 5.875 ETH a year.

**Holder round trip** (economic review): deployment charge 0.92% of a deposit at 0.15 gwei, 1.54% at
the ceiling; unwind 0.16% to 0.30%; two fixed checkpoint charges of 0.00024 to 0.00057 ETH each.
Total 1.1% to 1.9% for a 1 to 2 ETH holder; 5.9% to 13.3% for a 0.01 ETH minimum deposit.

**Not changed, for the owner to know**
- A checkpoint pays less than its gas at the ceiling (23 positions: -58 µETH). Above the ceiling a
  redemption checkpoint needs a caller willing to lose that, or the holder (unpaid, permissionless).
- A cancelled deposit forfeits its checkpoint charge (it already paid for a checkpoint slot).
- Several deposits in one interval each pay a full checkpoint charge for one shared checkpoint; the
  surplus goes to NAV, not to a keeper.
- About 0.5% of each charge that lifts NAV accrues to the seed's dead shares (by design).
- The asset-flow outcomes O2 and O6 were reworded for the new rule; the gate needs the owner's new
  signature (`asset_gate.py` reports the approval hash mismatch; every metric is within its bound).

## 15. Admin changes take effect at once (D58, 2026-11-17)

Owner decision: no delay on parameter or keeper-policy changes. `setParams` and `setPolicy` replace
the propose/apply flow; bounds are unchanged. Holders lose the warning window before a change. Worst
case from a compromised admin key acting as keeper: about 0.055 ETH on the first day of a 2 ETH
canary, then 0.015 ETH a day (budget refill at the bytecode maxima). 80 tests pass, the reconciler is
exact and the canary rehearsal closes to the wei. The asset-flow gate still needs the owner's
signature.

## 16. One owner role (D59, 2026-11-17)

Guardian and admin merged into `owner`; `lowerCaps` removed (`setParams` covers it). 80 tests pass,
reconciler exact, canary rehearsal closes to the wei. PackVault 22,364 bytes. Not yet independently
reviewed: covered by the release audit prompt (`docs/AUDIT-PROMPT.md`).

## 17. Launch audit A and repairs (D60, 2026-11-17)

External audit step A at `ba8d26e` recommended stopping before mainnet. Every code finding is
repaired and proven by the auditor's own witnesses rewritten as regressions
(`audit/release-ba8d26e-repairs/REPAIRS.md`). Still open and blocking release: E7 (forward return
model omits FWA staging, so the return gate is unvalidated), E8 (owner-compromise bound and the
raisable TVL cap need an owner decision), E9 (outcome signature). Launch steps B to E (uninformed
second audit, comparison, real-transaction rehearsal, canary plan) have not run.

## 18. Return gate with FWA staging (audit E7, 2026-11-17)

The keeper now lists only when FWA's queue is drained, and the forward model makes each listing
wait the queue's historical drain time (10,588 relist moments in the last 30 days: 46.4% found it
busy, waits up to 4.7 h). Gate at trailing-30-day volume, 100 positions, 400 runs:
**0.5 gwei ceiling +76.6% mean (p5 -13.0%), was +78.5%; 0.15 gwei +107.5% (p5 +8.0%).** The gate
(10%) passes. At last-14-day activity: +18.7% mean, 22% chance of a losing year (was +20.3%, 20%);
at the 0.5 gwei ceiling +12.0%, 31%. With 1.0 gwei from day 30: +2.4%, 41%. Closed form unchanged.

## 19. Backing rule and oracle exemption (D62, 2026-11-17)

FWA made ShapePacks oracle-exempt; the vault would have listed nothing on mainnet (found by the
current-block rehearsal). Backing is now computed by the vault: floor max(P / 0.9, P / 0.99) =
0.0333 ETH so purchasers take the bid and packs keep cycling; raised so one cycle repays a build at
today's price (0.0360 ETH at 0.5 gwei); gas-optimal above ~1 gwei; spare capital spread when the
position count binds; FWA's oracle cap only when not exempt. Forward simulation, 100 positions,
400 runs: gate window at 0.5 gwei **+76.8%** (p5 -12.0%); last 14 days **+20.3%, 17% chance of a
losing year** (was +18.7%, 22%); 1.0 gwei from day 30 +6.1%, 22% (was +2.4%, 41%). 98 tests;
reconciler exact; rehearsals at the pinned and the current block list 30 positions, ledgers exact.

## 20. Launch audit B and comparison (D63, 2026-11-17)

Uninformed audit B at `c884959` (Fable 5.2): no path to take holders' principal; one high
(exits read FWA's economics and could be frozen by FWA's owner) and six medium findings. All code
findings are repaired and proven by B's own tests rewritten as regressions
(`audit/release-c884959-B/REPAIRS.md`). 105 fork, audit and scenario tests; reconciler exact.
Open: canary essential budget sizing (owner), outcome signature, mainnet canary (step E).
