# PackVault: repair review report

2026-11-16. Independent engineering and economic review of the overnight build, with repairs.
Decisions: `docs/DECISIONS.md` (D19 to D31 are new). Owner requirements and proposed outcomes:
`OWNER-REQUIREMENTS.md` (B2 supersedes B). Economics: `sim/out/forward.md`. The overnight
report this replaces is in git history (commit 1b8cf91).

## Bottom line

- **The overnight contract lost money for holders on every bid cycle.** Its 5% keeper fee skim
  (1.885 mETH per cycle) exceeded the whole edge (1.396 mETH), and the skimmed ETH never returned
  to holders. The overnight model left the skim out, so its +86%/yr was wrong. Fixed (D19).
- **Corrected, the strategy is positive in expectation** wherever gas is below 1.59 gwei. Net
  per bid cycle is +1.264 mETH at 0.15 gwei (live gas 0.14 gwei). Volume sets how often cycles
  happen, so it sets the return rate, not its sign.
- **Returns are volatile and depend on FWA activity.** At the last 14 days' rate (71 a day), 100
  positions: mean +23%/yr, 15% chance of a losing year. At the 30-day gate rate: +118%. At 15 a
  day: +3%. Each selection costs 55% of a position's capital.
- **Recommendation: a funded canary is justified, small and capped**, after you set guardian and
  admin addresses and sign off B2. No critical or high custody or accounting defect is open.
  External audit and legal review remain before any launch beyond the canary.
- Implementation, tests and model now agree: the Python vault model matches a real-VRF fork cycle
  to the wei, and the simulation uses that model and the live keeper's policy.

## 1. Confirmed findings

| # | Severity | Finding | Fix |
|---|---|---|---|
| F1 | Critical (economic) | 5% keeper fee skim exceeded the per-cycle edge; holders lost 0.49 mETH per bid cycle; skim stranded outside NAV forever | Keeper pay is reimbursed gas plus 10% from vault ETH (D19) |
| F2 | High | Unlist to cover redemptions, relist the freed ETH, be paid both ways, repeat while redeemers wait | ETH owed to redeemers excluded from idle ETH (D21) |
| F3 | High | Anyone could unwind every earning position (paid) when the oracle quote went stale | Unlisting only in wind-down, for redemptions, or when FWA's k gives no edge (D22) |
| F4 | High (liveness) | Checkpoint resolved and liquidated inside its loop: 16.08M gas at 400 positions (4% under EIP-7825's cap) and unbounded after a busy day; deposits and redemptions could stall | Read-only checkpoint, 300 positions (9.83M worst case), separate bounded `liquidate` (D24) |
| F5 | Medium | `restock` spent ETH on packs regardless of the edge, gas, or capital to list them | Restock needs live edge, one-cycle payback, backing capital (D20) |
| F6 | Medium | A failed pack recovery made the vault forget the pack | Position stays open on FWA's `stuckNFTRecipient` record; any `sync` retries (D23) |
| F7 | Medium | Checkpoints with no holder flows were paid (about 6M gas at 150 positions, every 12 h) | Unpaid unless flows (D19) |
| F8 | Medium | Allocated-exposure bound of 2% blocks checkpoints at normal busy-day volume | Recommended 10% (D30) |
| F9 | Medium | `opGasCap` 3M left necessary large calls (checkpoint at scale, restock batches) underpaid | Bound raised to 16,777,216, default 15M (D29) |
| F10 | Medium (review S1) | `maxTip` unbounded | `maxTip <= gasCeiling` (D31) |
| F11 | Low | Dust harvests paid up to 25% of what they collected; active fees needed unlisting to become ETH | All-or-nothing pay rule; `harvest(ids)` claims active fees (D19, D25) |
| F12 | Low (tests) | Gas test assumed a 30M transaction limit | Asserts 80% of 16,777,216 for checkpoint; every keeper batch run under the cap |
| F13 | Keeper | Did not harvest active fees, free redemption liquidity, liquidate, unwind, wind down or loop; broke on the ABI change | `keeper/policy.py` shared with the simulation (D27) |

Root causes: keeper compensation was designed as a share of revenue instead of a cost; spending
paths checked capital or the edge but not both together with gas; the checkpoint did unbounded
work; the overnight model and the contract were never reconciled against each other.

## 2. Verification

All on a mainnet fork of the real contracts, `vm.fee`/`vm.txGasPrice` set, no mocks.

| Suite | Tests | Covers |
|---|---|---|
| ForkVaultLifecycle | 11 | round trip (every wei, keeper pay included), kick, crown raise, stale quote cannot unlock unlisting, guardian, delay and `maxTip` bound, cancel, pro rata, wind-down |
| ForkVaultAdversarial | 15 | gas ceiling, forced ETH, hostile NFT, reentrancy, distributions, all-holders-exit, checkpoint at 300 positions (9.83M), keeper batches under the tx cap, no fee skim, idle checkpoint unpaid, restock gates, unlist/list loop closed, liquidation only when needed |
| ForkSelection | 4 | real VRF replays: bid, keep, silent purchaser, pre-admission; sync pay, dust harvest unpaid |
| ForkReconcile | 1 | full real-VRF cycle traced; `sim/reconcile.py` matches every vault number to the wei |
| ForkTokens | 1 | real buyback, claim, sale, floor guards |
| ForkMeasure | 2 | gas table, token route, transfer lock |
| ForkVaultInvariant | 4 invariants | reserves covered, claims within reserves, shares conserved, every wei held or paid as mint fee or keeper pay |

- Local rehearsal (`keeper/rehearse.sh`, anvil fork): production deploy script, keeper only:
  pricing, 20 positions built and listed, full redemption (unlist, liquidate, checkpoint, claim),
  redeploy, wind-down to empty. Anvil gas was ~1 gwei.
- Independent review of the repairs: no critical or high finding; resolutions in D31.
- Measured gas: sync 158k, harvest of 29 listings 496k, list 499k to 570k, restock 921k per pack,
  unlist 201k, liquidate about 160k per pack, checkpoint 0.22M plus 32k per position.
- Not tested for real: a failed pack delivery (unreachable with the deployed ShapePacks and FWA's
  stipend rules without mocks, D23); live keeper competition, mempool congestion, behaviour after
  block 26,427,553.

## 3. Economic model

Three kinds of numbers, kept apart (`sim/out/forward.md`): expectation (closed form), backtest
(real FWA history with the vault inserted), forward simulation (a year through the reconciled
vault model and the live keeper policy). Realized performance: none.

The simulator itself was checked: fees per selection reproduce k (1.032 to 1.044 vs 1.0385 over
tens of thousands of selections), and at constant volume its mean return sits below the closed
form only by measured cash drag (after a bid outcome a pack waits for fee income to relist).
Bugs found in it and fixed before use: over-selection by 2.7%, overpaid fees on very busy days, a
keeper that relisted too slowly, a double-counted deposit.

**Per bid cycle (expectation):** B (k - 1) = 1.396 mETH; cycle gas 0.8M: net +1.264 mETH at 0.15
gwei, +0.516 at 1.0, +0.076 at 1.5; break-even 1.59 gwei. New packs only below about 0.54 gwei
(one-cycle payback). Only 3-unit packs pass the keep-outcome gate at the 0.0363 cap.

## 4. Projections

Forward simulation, one year, 200 runs per row, holder return after every expense, gas 0.15
gwei unless stated, tokens at zero. Full table and backtest: `sim/out/forward.md`.

| Activity | Positions | Mean | p5 | Median | P(losing year) |
|---|---|---|---|---|---|
| Trailing 30 days (611/day, the gate) | 100 | +118% | +22% | +113% | 2% |
| Trailing 30 days without Oct 31 (311/day) | 100 | +109% | +6% | +102% | 4% |
| Last 7 days (97/day) | 100 | +34% | -8% | +34% | 10% |
| Last 14 days (71/day) | 30 | +24% | -33% | +21% | 28% |
| Last 14 days (71/day) | 100 | +23% | -11% | +23% | 15% |
| Last 14 days (71/day) | 300 | +20% | +5% | +21% | 2% |
| Decline from 97 to 10/day over the year | 100 | +11% | -11% | +11% | 26% |
| 15/day | 100 | +3% | -10% | +2% | 40% |
| Inactive after 60 days | 100 | +3% | -9% | +3% | 37% |
| Holder redeems 50% at day 120 | 100 | +15% | -13% | +13% | 24% |
| Crown share raised to 5% at day 90 (vault unwinds) | 100 | +4% | -10% | +4% | 32% |
| Gas 1.0 gwei or more, sustained | 100 | 0% | 0% | 0% | (nothing deployed) |

Backtest of the real last 14 days: expected +34% (30 positions) and +28% (300) annualized; 14
days is too short to annualize safely (p5 to p95 spans -332% to +384% at 30 positions).

**What these say:**
- **30-day gate (owner's definition): passes**, with or without the Oct 31 day of 9,315.
- **The 30-day window does not mislead the go/no-go decision, but it overstates the return by
  about 4x.** At the current run rate (71 to 97 a day) the mean is about +20 to +34% with a 10 to
  28% chance of a losing year. The 30-day figure should not be shown to holders as expected.
- **Below about 15 acquisitions a day the vault is barely worth running** (+3%, 40% chance of a
  losing year), though it never loses its expected edge per cycle.
- **Volume-triggered pause: not worth adding (D28).** A keeper slowdown at 30 or 60 a day changed
  returns by under 1 point in every scenario tested; the one-cycle payback rule already stops
  new packs when gas makes them costly.
- **Gas is the binding constraint.** At 1.0 gwei sustained a new vault builds nothing (packs need
  gas below ~0.54 gwei); existing positions keep cycling until 1.59 gwei.
- **Size:** larger vaults are less volatile (P(loss) 28% at 30 positions, 2% at 300) with slightly
  lower mean returns. Keeper gas is 3 to 13% of deposits a year against fees of 7x to 36x
  deposits; mint fees under 1.4%.

## 5. Remaining risks and limitations

- FWA dependency: FWA's owner can move fees, the crown share, the oracle cap or admission at any
  time. The vault reads them live and stops or unwinds, but positions are exposed until it does.
- Variance: each selection costs 0.0363 ETH against a 3.85% edge; short windows and small vaults
  can lose.
- Purchaser behaviour is assumed rational (take the bid); keeps help the vault.
- Selection anomaly (overnight): listings backed 0.02 to 0.04 ETH were picked 1.5 to 6% less than
  weight predicts. Unexplained; it helps the vault; the model uses the theoretical weights.
- Gas constants (`CYCLE_GAS`, `RESTOCK_GAS_PER_PACK`) are in bytecode.
- Keeper liveness under congestion depends on `maxTip`; redemptions are delayed, never lost.
- Bytecode margin 1,712 bytes; VaultLib is a second address to verify.
- Not done: external audit, legal review, mainnet rehearsal and canary (owner authority).

## 6. Decisions for owner review

1. Sign off the outcomes in OWNER-REQUIREMENTS B2 (O1 to O9), especially O5 (keeper pay) and O6
   (no new packs above ~0.54 gwei).
2. D30: allocated-exposure bound 10% (the reviewer preferred tighter; 2% blocks checkpoints).
3. D24: 300-position cap (about 20 ETH).
4. D28: no on-chain volume pause.
5. Guardian and admin addresses; canary caps in `deploy/canary.example.json`.
6. Disclosure to holders: returns are volatile; the 30-day figure is not an expected return.

## 7. Canary recommendation

**Justified, as a capped canary only:** 2 ETH TVL cap, 30 positions, 1.5 gwei ceiling,
`maxTip` 0.05 gwei, 10% keeper premium, allocated bound 10%, run by your own keeper. Its purpose
is to observe what no fork can show: real keeper competition and priority fees, checkpoint misses
when FWA's queue is busy, purchaser choices on vault packs, and FWA owner changes. Stop and wind
down if live gas holds above 1 gwei, if k falls below 1.01, or if realized fees per selection fall
materially below k. The canary is a mainnet broadcast and needs your authority.
