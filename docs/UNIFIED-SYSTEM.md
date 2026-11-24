# Unified main Shapes pool

Current owner scope: [MAIN-POOL-COMPLETION.md](MAIN-POOL-COMPLETION.md), OWNER-REQUIREMENTS A5.
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
pays the actual live mint fee. The recorded baseline is 0.001 ETH per Shape at block 26,484,850:
0.003 ETH creator revenue per fresh launch pack. No bulk mint, split, fee exemption or hidden subsidy.
The 0.0005 ETH scenario is fork-only sensitivity, not a production fee change.

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

FreshAfterAcquisition retires a genuinely acquired return once, redeems its actual principal, pays
for fresh primary mints and lists a replacement. Verified keeps authorize one replacement. Owed
returns retain eligibility until actually recovered. Ordinary kicks/withdrawals authorize none.
ReuseReturned relists the actual returned pack. Fresh mode never silently falls back to reuse.
Exit inventory is liquidated without fresh minting. Zero recipe mask prevents builds and renewals;
old inventory can still relist. Listing pause stops all new exposure.

## Cash, pricing and holder accounting

Growth preserves all liabilities, a separately derived renewal float and the maintenance reserve.
One float is the maximum enabled-recipe backing plus accepted mint fees and full quoted renewal
work at the gas ceiling. Returned principal funds replacement principal. No harvest is presumed.
Routine payment cash excludes that float. Eligible renewal can consume it while preserving the
maintenance reserve and owed redemptions. Accrued NAV is not spendable cash; bounded verified fee
collection can fund genuine renewal need. Cash and spending permission are distinct conditions.

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

## Quoted payment and bounded work

One payment calculation supplies envelopes, compensation and relevant charges: verified completed
work times the account schedule, min(basefee + configured priority, class ceiling), routine markup
on routine gas, flat work fees, then source/cash/permission limits. minPay protects a keeper's offer.
No progress earns no repeat reward. Wallet gas and keeper actual billed expense are reported
separately from account compensation. Raising a budget capacity never refills spent permission:
old-rate accrual precedes the update, then the new capacity clamps it.

No total position limit exists. Journal reads are capped at 128, own selections/terminals/prunes
at 16, builds at 4, relisting batches at 8, renewal at 4, allocation proof at 32 entries and optional scans at
96 positions. Mutable economic coefficients cannot increase these operation limits. Larger books
use the journal. Receipt callbacks read no large configuration and call no external payment policy.
Every real transaction remains subject to EIP-7825's 16,777,216 gas limit.

Retained numerical bounds are explicit operating limits: gas ceilings 50 gwei, work fee 0.00005 ETH,
routine capacity 0.3 ETH/refill 0.02 ETH per day, essential capacity 0.1 ETH/refill 0.005 ETH per day,
routine markup 10%, harvest compensation share 50%, distribution share 50%, uplift tolerance 10%,
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

Things that don't make sense until measured: a single float cannot guarantee unlimited rapid
renewals; 25 bps causes small pools to wait; positive creator fees do not imply positive holder return.
