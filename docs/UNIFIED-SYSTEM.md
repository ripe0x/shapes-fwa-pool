# Unified main Shapes pool

Current owner scope: [MAIN-POOL-COMPLETION.md](MAIN-POOL-COMPLETION.md), OWNER-REQUIREMENTS A8.
This is an unsigned implementation candidate. Historical design and measurements are preserved
under `release/history/e94fd99/`. They do not validate this configuration.

## Architecture and custody

PackVault pools nontransferable holder shares. PackManager is an individually owned ERC-1167 clone.
Both inherit PackAccount and execute StrategyLib, VaultLib and ScanLib against their own storage.
Each account is FWA's depositor and owns its cash, packs, liabilities and keeper permissions.
PackManagerFactory creates and discovers managers; it has no owner or authority over created clones.
The original two-step ownership handover remains 48 hours. There is no external keeper policy.

## Configuration and paid construction

Launch units 3, mask 8: three directly minted 0.01 ETH Shapes in one 0.03 ETH pack. Every fresh Shape
pays the actual live mint fee. The historical 0.001 ETH fee was observed at block 26,484,850;
the read-only refresh at block 26,493,799 found 0.0005 ETH per Shape. A fresh pack therefore accrued
0.0015 ETH creator revenue in the current-fee local fork. No bulk mint, split, fee exemption or hidden subsidy.
The 0.00025 ETH case is an isolated half-current-fee sensitivity, not a public fee change or production approval.

Each owner can immediately change numerical Params and its named GasSchedule. An explicit accepted
mint-fee maximum is separate from ordinary settings. Decreases lower actual spending; increases over
the accepted maximum block fresh mints. A configuration hash binds creation and sensitive work to
Params, live mint fee and operating flags, excluding changing budgets and time. Claims, cancellation
and necessary unpaid recovery remain available when the configuration changes.

Backing is an adjustable ratio, checked against actual FWA admission, asset coverage, quantization,
unique identifiers and the selected lifecycle's costs. A local backing floor of ceil(face/0.95)
preserves the face mark of unresolved allocations even at FWA's immutable 5% settlement-fee cap;
it limits owner-selected backing to at least 1.052632x face. It is an account NAV coverage rule,
not FWA's mutable minimum, which the real listing call enforces. It contains no purchaser bid
discount or redeem gas: a buyer may profitably take the bid. Buyer choice is never imposed by a keep
preference. Local evaluation uses 70,000 bps, or 0.21 ETH backing separate from 0.03 ETH principal.
That backing and the 25 bps checkpoint uplift value are provisional, not production approval.

Returned packs are reused intact. There is one renewal behavior, with no fresh-return mode,
replacement eligibility ledger or dedicated renewal float. A purchaser keep removes that pack;
funded growth may build a replacement using paid primary mints. Zero recipe mask prevents fresh
builds while old inventory may still relist. Listing pause stops all new exposure. Exit inventory
is redeemed without reminting.

## Cash, pricing and holder accounting

Growth preserves holder liabilities and the owner's maintenance reserve. Cash and spending
permission are separate: increasing a budget creates no ETH. Bounded collection of actual FWA
fees may fund necessary maintenance; accrued NAV is not spendable cash.

Deposits escrow gross cancellable principal. The committing checkpoint derives construction from
its effective settings and live fee, then stores an epoch issuance ratio. Lazy settlements assign
the aggregate rounding residue to the final settling deposit, without holder enumeration.
Cancellable escrow does not suppress preparatory liquidation. Actually committing deposits can
fund atomic matched redemptions. Redemptions retain pro-rata partial fills and unconditional claims.
Unpaid caller-funded recovery checkpoints fill redemptions from free cash only, leave gross pending
escrow and its pricing epoch unchanged, and need no mint-fee/configuration expectation. A successful
partial or full recovery fill closes the sponsorship era and refunds its unused funding when
no deposits remain unpriced. Pending deposits retain their funded era for the normal checkpoint;
an incumbent's tiny unpaid redemption cannot strip that keeper compensation.

Checkpoint sponsorship remains attributed to its payer and era in canonical wei. A zero quote or
empty pool never closes an era while requests remain. Successful checkpoints, including partial
fills, or the end of all requests finalize it. Unused funding moves directly to a protected refund
reserve. Adjacent contribution-interval floor differences attribute every refundable wei without
payer enumeration. Explicit topups return excess funding. Required pricing tails/scans have their
own contribution source; contribution cash never temporarily becomes general free cash.

Allocated positions store max(backing - face, 0), using zero settlement fee as a conservative maximum
keep uplift. The aggregate updates incrementally and removes the exact stored contribution at
terminal resolution, including owed returns. Pricing compares it with preflow NAV. One 0.18 ETH
uplift needs at least 72 ETH preflow NAV at 25 bps; smaller pools wait for real settlement.

## Bounded measured payment and work

Verified completed work determines the gas allowance cap. Actual pay uses the lesser of the
captured gasleft span and that cap, plus the account's named overhead allowance. The price is
min(actual transaction gas price, basefee + configured priority allowance, class gas ceiling).
Reimbursed gas is paid at that price (no markup); verified service units add the work fee.
Cash, funding source and spending permission then clip the result. minPay rolls back all work
when the final offer is too low. Quotes and holder charges remain conservative envelopes.
No verified progress earns no overhead or repeat reward. Paid inputs must all be useful; stale,
foreign, duplicate or unnecessary hints revert atomically. Unpaid recovery tolerates stale hints.

The work span is gross gas before refunds, not receipt gasUsed. Keeper expense is measured from
actual receipts and reported separately from account compensation. The candidate overhead of
100,000 gas is provisional main-system calibration, not community's coefficient. Per-transaction
overhead can change incentives to split jobs; receipt comparisons must state
that tradeoff. Raising capacity never refills spent permission: old-rate accrual precedes a
settings update and the new capacity clamps it. Numeric calibration remains immediately owner
adjustable. Changing the algorithm requires new code.

No total position limit exists. Journal reads are capped at 128, own selections/terminals/prunes
at 16, builds at 4, relisting batches at 8, allocation proof at 32 entries and optional scans at
96 positions. Mutable economic coefficients cannot increase these operation limits. Larger books
use the journal. Receipt callbacks read no large configuration and call no external payment policy.
Every real transaction remains subject to EIP-7825's 16,777,216 gas limit.

Retained numerical bounds are explicit operating limits: gas ceilings 50 gwei, work fee 0.00005 ETH,
routine capacity 0.3 ETH/refill 0.02 ETH per day (the single keeper budget; exit work is unpaid),
harvest compensation share 50%, distribution share 50%, uplift tolerance 10%,
backing ratio 100x and each gas coefficient 16,777,216. They constrain quoted spending, arithmetic
and admission under the current algorithm; an owner cannot operate beyond them by settings alone.
They are not a promise about owner-key compromise or sufficient keeper margins at every gas price.
Pack sizes 3 through 30 units bound per-pack mint/redemption work. Recipe selection compares
bounded allowed alternatives; existing inventory retains actual face and Shape counts.

## Validation and delivery

Exact current measurements and gaps belong in the completion receipts and scorecard. The main
recipe, creator revenue and holder costs must share the same scenarios. The existing net 10% annual
holder hurdle at trailing 30-day successful activity remains in effect, with tokens zero. Synthetic
sensitivities are not demonstrated APR. A failing economic candidate must remain failing.

The app and CLI expose explicit caller-funded exits under a wallet spending cap. Ordinary keeper
profitability never vetoes necessary work that the caller accepts. The community app/contracts,
legacy selection and keeper remain intact; the main production app gate stays closed.

## Intact manager migration

The owner pauses source and destination, unlists without entering exit mode, transfers actual
pack NFTs and explicitly imports them at the destination. Import accepts canonical sealed packs,
at most 16 per call and 30 Shapes per pack, verifies contents/custody/principal and records actual
Shape counts. It neither mints nor pays a keeper. A sealed recovery pack can be withdrawn by its
checked index and ID even when another recovery entry is an unsealed claim. Burned pack NFTs
cannot move intact. Recovery claims retain their original owner-controlled cash recovery path.
The factory remains immutable and has no authority over existing managers.

The UI checks both owners, official factory membership, clone runtime, dependencies and import
support; it retains nonce-based spend reservations and rechecks canonical receipts in bounded
pages. ETH is an explicit source-to-owner withdrawal followed by a reviewed wallet transfer.
Migration never turns on permissionless liquidation.

Things that don't make sense until measured: 25 bps causes small pooled vaults to wait; positive
creator fees do not imply positive owner return; per-call overhead may favor splitting work.
