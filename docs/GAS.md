> **History.** This document describes an earlier candidate (restock, loose Shapes, bid-first backing). Current gas: `docs/UNIFIED-SYSTEM.md` section 4 and the quote constants in `src/VaultLib.sol`. Current release and canary instructions: `docs/release/RUNBOOK.md`.

# Final operating compensation

The current implementation and acceptance limits are in [Complete operating pass](COMPLETE-OPERATING-PASS.md). Actual signed receipts are in `receipts/complete-cost-receipts.json` and `receipts/complete-foreign-journal.json`. Source identity and focused checks are in `receipts/complete-final-validation.json` and `receipts/complete-contract-summary.json`.

| Component | Final quoted gas |
| --- | ---: |
| Checkpoint |360,000|
| Restock base / reference three shape pack |280,000 /325,000|
| Each additional shape in the pack |100,000|
| Paid primary mint and ten way split |2,200,000|
| List base / admitted position |280,000 /825,000|
| Ordinary sync base / required tail base |85,000 /120,000; choose one|
| Qualified distribution proof |80,000|
| Completed global journal record |22,000|
| Scan proof: each Active own position read (D75; 29,337 measured) |30,000|
| Own selection / terminal reconciliation / head prune |180,000 /120,000 /45,000|
| Economical fee credit withdrawal inside eligible sync |40,000|
| Necessary active fee funding inside eligible sync |40,000 plus 80,000 per actual claim|
| Standalone harvest |Unpaid|

Unlisting, liquidation, oversized gift recovery and the work fee retain their existing schedules. Fixed compensation is capped by policy, free cash and permission. Extra collection costs must satisfy the fee share restraint. Caller gas never determines vault compensation.

A current signed four shape leftover call at 0.5 gwei exposed an underpayment under the old 35,000 extra unit slope. The final 100,000 slope repairs it; all ten final affected signed cost receipts cover billed expense and pass ordinary preflight. The original three shape quotes and O2 result remain unchanged. Larger packs have deliberately conservative compensation. Owner settings different from the tested work fee, markup and price need their own willingness check.

Final runtime is 24,459 bytes for PackVault (24,136 before D76's owner handover), 24,440 bytes for VaultLib and 1,935 bytes for ScanLib (D75), below 24,576. Q360 remains within O6's 0.0002 ETH payment at the routine ceiling. O2 still misses its original 1,750,000 quoted gas target:1,919,655.

Everything below is historical evidence for its named source. It is preserved unchanged and must not be read as the current schedule, current runtime or outstanding work list.

---

# Efficient journal gas and compensation

The current fixed-work candidate passed its exact owner-approved local batch; no public deployment is implied. Economic acceptance
remains open: O2 is above 1,750,000 quoted gas, recurring expense must be paid from vault cash,
and exposed successful-foreign bills remain missing. No spending allowance or accepted outcome
has changed. The active implementation scope is `EFFICIENT-JOURNAL-REVISION.md`.

Compensation is a fixed quote for verified work, capped by the replaceable policy offer, envelope,
free cash, applicable permission and `minPay`. It is not measured-gas reimbursement. Request-funded
checkpoint charges remain protected in the processing pool. Foreign records earn no flat work fee.

| Component | Quoted gas |
|---|---:|
| Checkpoint |360,000|
| Restock base / three-Shape pack |280,000 /325,000|
| Additional Shape in a pack |35,000|
| Paid primary mint and ten-way split |2,200,000|
| List base / admitted position |280,000 /825,000|
| Sync ordinary base / required holder-tail base |85,000 /110,000; choose one|
| Actual qualified distribution-only proof |80,000 added to required-tail base only|
| Completed global journal record |22,000|
| Own selection / terminal reconciliation / head prune |160,000 /120,000 /45,000|
| Unlist base / moved position |340,000 /285,000|
| Liquidate base / ordinary pack / actual packed Shape burned |75,000 /80,000 /35,000|
| Loose Shape redemption |65,000|
| Oversized gift recovery |100,000 +35,000 per actual burned Shape +70,000 once for unseal, plus liquidation base|
| Harvest base / listing actually harvested |125,000 /80,000|

Sync automatically reads up to 128 completed records, with separate 16-own-selection, 16-terminal-ID
and 16-prune limits. The cursor stops before a seventeenth own transition. Full jobs and actual
own transitions qualify; a smaller foreign tail requires a genuine fresh checkpoint opportunity.
Distribution-only tails authenticate NAV, witness, high-water mark and liquidity after the maximum
sync envelope. Optional tails and provably unexposed advances are unpaid. No completion bonus.
All sync uses routine permission even during redemption or wind-down; D64 retains caller-funded
unlisting/liquidation. A supplied terminal list cannot manufacture a smaller paid journal job.

## Current actual receipts and measured candidate

The approved 8559 baseline completed 318 transactions/17.501610827424708864 ETH aggregate value and restored its entry without topups. Default holder/distribution singleton bills are 122,411/202,253 gas; both ordinary gates decline at the baseline 115,000 quote. Full 128 bills 2,233,060. The standalone full-holder checkpoint bills 346,017 at 0.2/0.5/2 gwei, with ordinary preflight accepted, protected buckets and claim checked. Q360 headroom is 13,983 gas (4.04%) for this fixture. Total pay also includes the work fee.

The amended candidate passed 199 transactions without repair:517/540 cumulative, 27.869594973162081536/32 ETH aggregate value, 8.3 funded once/no topups, entry restored. All 24 journal rows have positive calibration-receipt keeper net, positive exact signed-estimate headroom and accepted ordinary preflight. Default holder/distribution singletons bill 122,417/202,270 against 132,000/212,000 quoted gas. Full 128 bills 2,233,071 against 2,901,000. At 0.5 gwei singleton actual keeper nets are 0.0000047915/0.000004865 ETH; full 128 net 0.0003339645 ETH. Signed estimates and default ratios are separate from billed gas and 25% limits. Operator receipts use `minPay=0`; signed 80% calldata estimates are not signed 80% receipts.

Candidate has one Active position; baseline has 40. It did not repeat the baseline full-holder fixture. Actual candidate PackVault/VaultLib deployed sizes are 24,451/23,001 bytes. Successful-foreign and combined-own-maxima coverage remain gaps. All 0.5 gwei inventory proposals were unavailable, so Q_PACK stays 325,000. Fresh affected O2 remains 1,919,655; O6 remains 0.0002 ETH.

At measured candidate quotes, 18,281 perfectly packed records with a final qualified distribution tail imply 0.0828884 ETH at 0.2 gwei or 0.207221 ETH at 0.5 gwei, before own work/additional tails. The latter exceeds 0.15 ETH steady 30-day refill. This is quote arithmetic, not billed cost or returns. The candidate policy's retained-max-markup reserve envelope is 0.00577555 ETH (0.00593555with20,000,000,000,000wei work fee); informational, not an approved reserve change. Receipts: `receipts/efficient-journal-candidate-summary.json`; cash/own-work/return limits: `REVIEW-FUNDING-PROPOSAL.md`.

Everything below describes the pre-receipt phase and its named source. It is retained as history; its pending-receipt statements and85k/30k arithmetic are superseded above.

## Earlier measured scope

`receipts/efficient-focused-results.json` binds the five real refund/journal/distribution tests,
seventeen affected lifecycle/selection tests, unexposed authentic successful history, fourteen
accounting tests and keeper policy checks. `current-three-arg-reconciliation-results.json` contains
fresh exact accounting replays and unchanged46,462/69,730 receiver samples. Runtime is24,451 bytes
for PackVault and22,997 for VaultLib, leaving125 and1,579 bytes of EIP-170 space respectively.
Maximum combined128-global/16-own/16-terminal/16-prune work has not been reached in one real call.

Restock keeps immediately consumed new Shape IDs in memory and caches the unchanged economics
before minting. Seven matched authentic inventory cases retain exact mint fees, recipes, principal
and keeper payout. Ten three-unit packs save674,385 receipt-equivalent gas (6.53%); a first
three-unit pack saves36,025 (1.28%). See `receipts/restock-efficiency-results.json`.
These are execution savings with unchanged holder compensation, pending receipt calibration.

**Meter correction:** installed Foundry's isolated `lastCallGas().gasTotalUsed` has already applied
finalized refunds. Subtracting `gasRefunded` again was incorrect. The old342,766 checkpoint bound
and derived5.03% headroom are withdrawn. The current direct finalized sample is345,937; adding
its29,600 refund reconstructs375,537 pre-refund gas. The360,000 component has14,063 (4.07%) sample
headroom. Caller `gasleft` plus intrinsic meters are proxies, not true gross or billed receipts.
Primary Foundry implementation and preserved raw values are bound in
`receipts/restock-efficiency-meter-correction.json`. Actual signed Anvil receipts are separate.

The preceding Q400-source local receipts remain historical evidence for their source: refunded
singletons bill112,515 and sixteen bill361,632; arbitrary splitting added95,878–95,902 billed gas.
That rejects a105,000 base under the old arbitrary-slice rules. It neither proves the new tail
profitability nor supplies exposed successful-foreign bills. Standalone current full-holder and
new128-record receipts require the separately authorized prepared batch.

## Operating cost and cash source

At unchanged85,000+30,000 quotes, the archived18,281 completed-record window needs at least143
packed jobs with128-record bounds:0.112117 ETH at0.2gwei or0.2802925 ETH at0.5gwei, before own
work and additional small jobs. The latter is0.0093430833 ETH/day, above mainnet's0.005 daily
steady refill. Initial permission is not recurring funding; a reserve is not income.

The theoretical retained-cap reserve model is0.0059225 ETH at0.5gwei, above the configured0.005.
It is an informational conservative combined envelope, not a requirement to raise reserve.
The keeper separately compares the known packed backlog with actual free cash and routine
permission, reversibly pausing new exposure when insufficient.

Vault operating cash is the default expense source. Complete returns must subtract all keeper
payments, paid mint fees, transferred principal and holder caller costs, clear backlog and finish
claims. Creator mint revenue is reported separately and is not an assumed subsidy. No minimum TVL,
budget increase, mint-fee reduction or changed O2 acceptance is introduced.

Things that don't make sense: global maintenance scales with unrelated protocol activity while
small-vault income does not; execution savings do not automatically become holder savings; a
replayed model cannot replace authentic successful-foreign receipts or standalone keeper preflight.

---

# Gas and keeper compensation

## Pay rule (contract, D56/D57)

```
price    = min(basefee + maxTip, ceiling)       ceiling = gasCeiling (routine, canary 0.5 gwei) or
           essentialCeiling (redemption and wind-down, canary 2 gwei); maxTip 0.05 gwei
quoted   = base + perUnit x units (VaultLib.Q_*)                  fixed per operation, never gasleft()
envelope = quoted x price x (1 + payMarkupBps, routine only)      canary markup 0, bytecode max 10%
           + workFee x units                                      canary 0.00002 ETH, max 0.00005
offer    = active policy's quote(...)                             50,000-gas staticcall; failure = 0
pay      = min(offer, envelope, funding cap, free ETH, budget)    reverts if pay < minPay
V1 offer = quoted x price + workFee x units                        = the envelope at canary values
```

Units: packs built (restock), positions listed, resolved (sync), activated or unlisted, items
liquidated, positions harvested, 1 per checkpoint that priced flows or distributed. burnTokens is
unpaid.

Quoted gas (VaultLib, measured as billed gas on fork receipts, `sim/out/gas-quotes.json`):

| Operation | Base | Per unit | Measured billed |
|---|---|---|---|
| checkpoint | 225,000 | 33,000 per position | 221,860 (0 positions), 975,403 (23); quoted at measured cost (D61) |
| restock | 280,000 | 200,000 per pack + 2,200,000 per mint | 2,635,830 (1 pack, 1 mint), 9,121,461 (10 packs, 3 mints) |
| list | 255,000 | 530,000 | 858,779 (1), 5,790,861 (10) |
| sync | 75,000 | 75,000 | 158,661 (1), 300,695 (3 kicked); bid outcome ~181k |
| activate | 50,000 | 450,000 | ~518,000 (1) |
| unlist | 240,000 | 170,000 | 480,141 (1), 1,667,172 (8) |
| liquidate | 75,000 | 150,000 per pack, 65,000 per Shape | 250,185 (1) |
| harvest | 80,000 | 15,000 | |

Bounds on what a caller can extract:
- Pay is fixed by the operation and its completed units: gas limit, gas used and tip change nothing.
- Each base is under the measured fixed cost / 1.1, so splitting a job across calls loses money.
- A no-op call reverts `Nothing`; `checkpoint` without flows or distributions pays 0.
- A checkpoint with flows is paid from `processingPool`, filled only by the request charges.
- `harvest` pays only if its envelope is at most 25% of the fees it realized.
- Routine and essential budgets cap total pay per day (canary 0.0008 / 0.0002 ETH a day refill,
  0.03 / 0.01 ETH caps).
- Above the ceiling every call is accepted and paid at the ceiling price (D51).

## Keeper P&L per call (canary rehearsal receipts)

Setup: anvil fork of block 26,418,539 with an empty-block basefee that decays from 0.15 gwei;
`keeper/keeper.py` bidding basefee + 0.05 gwei; `keeper/rehearse_canary.py` (D57 run). Rows from
the first liquidate on run under V2, the test policy the rehearsal swaps in (3 work fees per unit,
no gas component), capped by the vault's envelope. "net" = KeeperPaid - gas x effective price.

| Call | Price gwei | Gas | Estimate | Est / gas | Keeper net (wei) | Net / cost |
|---|---|---|---|---|---|---|
| checkpoint (first pricing) | 0.154 | 229,097 | 245,621 | 1.07 | +1.24e13 | +35% |
| restock 10 | 0.141 | 9,176,506 | 10,055,643 | 1.10 | +1.58e14 | +12% |
| list 10 | 0.133 | 5,815,375 | 5,948,288 | 1.02 | +1.65e14 | +21% |
| burnTokens | 0.084 | 415,966 | 443,664 | 1.07 | -3.49e13 | unpaid |
| sync (kicked) | 0.067 | 179,877 | 199,197 | 1.11 | +1.80e13 | +148% |
| list 1 | 0.065 | 840,200 | 861,525 | 1.03 | +1.64e13 | +29% |
| V2: liquidate (spike) | 0.925 | 211,135 | 266,098 | 1.26 | -1.53e13 | -7% |
| V2: unlist 14 (spike) | 0.816 | 2,919,001 | 3,648,131 | 1.25 | -1.48e15 | -62% |
| V2: checkpoint (spike, redemption) | 0.925 | 707,889 | 742,375 | 1.05 | -5.95e14 | -90% |
| V2: unlist 15 (wind-down) | 0.118 | 2,657,521 | 3,318,422 | 1.25 | +2.76e14 | +88% |
| V2: checkpoint (final) | 0.096 | 209,368 | 241,007 | 1.15 | +1.72e13 | +85% |

Results:
- Under V1 below the ceiling every paid call profits: +12% to +148% (the work fee dominates small
  calls at sub-0.1 gwei prices).
- The spike rows ran under V2, which pays no gas: the keeper accepted the loss only because the
  rehearsal passes `--max-loss-wei 0.01 ETH`. The default keeper waits.
- Every payment's receipt matched the keeper's simulation except where basefee fell between the
  simulation and inclusion (each empty anvil block lowers it); the paid amount was then lower,
  never higher.

## Thresholds per operation (D45)

| Operation | Planned when | Gas limit for it |
|---|---|---|
| New packs (`restock` + `list`) | one bid cycle repays the build: 1.39M quoted gas + 0.0003 ETH mint share + 1 work fee | quoted price below about 0.52 gwei, and under the ceiling |
| Relist idle packs | a bid cycle nets positive: B(k-1) = 1.396 mETH against 0.62M quoted gas + 2 work fees | break-even 2.19 gwei, capped by the 0.5 gwei ceiling |
| Harvest fees | pay <= 25% of fees realized; or redemption cash needed | under the ceiling; above it only for redemptions |
| Activate staged listings | FWA's queue drained | under the ceiling |
| Burn token rewards | operator opt-in | under the ceiling; unpaid |
| Checkpoint | FWA blackout, queue drained, flows pending | deposits under the ceiling; redemptions at any gas |
| Sync (recovery of settled, kicked, expired positions) | due | under the ceiling; above it only for redemptions or wind-down |
| Liquidity release (`unlist`, `liquidate`) | redeemers short of ETH; wind-down; edge gate failed | any gas (keeper's loss above the ceiling) |
| Wind-down | owner started it | any gas |

## Reserve (D46)

```
reserve need = one 10-pack listing batch x ceiling x (1 + markup) + 10 work fees
             = (255k + 530k x 10) x 0.5 gwei + 10 x 0.00002 = 0.0030 ETH   (canary)
(checkpoints are paid from request charges; unlisting and syncs from the backing they return)
```

The canary reserve is 0.005 ETH. The need no longer grows with positions.
