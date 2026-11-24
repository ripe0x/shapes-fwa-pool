# Main pool completion scope, 2026-11-24

This engineering record carries the owner's current implementation request. The chat request is
authoritative and supersedes older six-unit, compulsory buyer-keep and external-policy assumptions.
Prior evidence and approvals apply only to their original code/configuration.

## Outcome and boundaries

Finish contracts, keeper, accounting, simulation, app integration, tests and unsigned deployment
tooling. Integrate useful work from main PRs 6 and 7 after inspection. App starts from latest
community main (PR31 is now merged). Preserve community deployments, legacy routes, settings,
keeper integration and the closed main-pool launch gate. Isolated local branches and draft PRs
are authorized. No public transactions, production mint-fee changes, live cutover or merges.
Independent review of combined immutable changes is required, with substantiated findings repaired.

## Fixed launch and owner authority

- Launch packs: 0.03 ETH, three directly minted 0.01 ETH Shapes, units 3, mask 8.
- Every fresh Shape pays actual applicable primary mint fee. No bulk/split replacement or fee bypass.
- Preserve immediate economic adjustability under each account owner's control. Factory has no
  authority over managers already created. Keep PackAccount and shared linked-library architecture.
- Unlimited total positions; bounded incremental calls, no required complete book scans or holders.
- Last verified fee was 0.001 ETH per Shape. Read current fee at recorded block; never alter public
  fee. The 0.0005 ETH scenario is isolated-fork sensitivity only.

## One keeper payment calculation

Remove main external KeeperPolicy address, quote/failure paths, version validation, setters,
deployment/initialization and fixed factory policy. Do not add a policy creation argument.
Keep verified-operation counts and quoted gas, not community measured-gas reimbursement. Measure
actual receipts for calibration; do not copy unrelated community coefficients. Named account-owned
GasSchedule contains every operative coefficient; derived totals remain derived. The SAME payment
calculation drives envelope, compensation and charges: verified allowance, appropriate gas ceiling
and basefee+priority, routine markup on routine gas, workFee per verified service unit, then funding
source/cash/spending-permission limits and minPay. A no-op pays nothing. Protect every liability.
Accrue budget at OLD rate before updating, then clamp capacity; capacity increase never refills.
Operation bounds independent of gas prices. ScanLib.rebase must have a fixed per-call bound before
scan/journal economics, and use journal above bound. Receipt callback must stay cheap with no large
configuration load or external call. Document retained monetary maxima and operating limitations.

## Coherent configuration and mint fees

One effective configuration per operation. Bind previews/execution with expected config hash or
version, including relevant mint fee state, for creation and work spending/committing funds. Stale
expectations fail before work. Claims and necessary recovery stay unconditional; do not hash budget
balances/timestamps. Store accepted mint fee maximum; actual mint fee within max is paid, a decrease
lowers actual expense. An unrelated settings update must not silently accept a fee increase.
Reserve conservative acceptance limits separately from actual spending. Test fee changes both ways
on real isolated fork. Ownership acceptance window is separate and unchanged.

## Recipe, backing and lifecycle

Propagate units3/mask8 through deployment, keeper, charge/backing/profitability calculations,
simulation, rehearsal, app, ABIs and verification. Remove simulator OR of default recipe into mask.
Remove six-unit and unexplained fixed-capital references from active code. Charges derive actual
recipe, mint count and relevant capital; multiple recipes require bounded conservative comparison,
not assumption smallest face has highest fee/ETH. Existing inventory retains actual value/count.
Zero mask forbids fresh builds, still permits valid old inventory relisting. listingPaused stops
new exposure. No fallback reenables fresh mints; maintenance/exits always remain available.

Replace compulsory purchaser-keep backing constraint entirely with adjustable backing ratio.
Keep actual FWA admission, uniqueness, quantization and asset coverage. Correct duplicate listing
allowance and missing bases. Distinguish initial build; bid return/renewal; keep/replacement; shared
maintenance; conditional harvest; holder processing; final exit. Holder cost counts actual keeper
pay once; keeper actual gas/margin analyzed separately; holder wallet gas is additional cost.

## Renewal and funding

Two explicit modes: FreshAfterAcquisition and ReuseReturned. Local candidate uses fresh. An acquired
pack returning permits bounded retirement and replacement with three paid mints and listing WHEN
funded. Completed acquisition authorizes replacement only ONCE, from verified protocol state and
actual ownership. Preserve legitimate eligibility through owed/delayed recovery. Ordinary unselected
withdrawal/kick grants none. Exit inventory is never reminted. Insufficient cash/permission is
visible waiting, no silent reuse fallback. Eligibility is permission, never extra NAV. Redeem actual
returned principal. Processing incremental/bounded. No cadence engine, substitute fee or subsidy.

Derive renewal float SEPARATELY from maintenance reserve. Growth preserves both plus liabilities;
eligible renewal can consume its designated float under documented rules. Accrued NAV is not cash.
Bounded genuine renewal harvesting may fund need using actual receipt checks; avoid unnecessary
harvest. Distinguish insufficient cash from exhausted spending permission; raising permission is
not funding.

## Local economic candidate (not production approval)

- Pack 0.03 ETH; verified current mint fee baseline.
- Backing ratio 70,000 bps, 0.21 ETH separate backing.
- Fresh paid replacement after completed acquisitions.
- One separately funded renewal float; 0.005 ETH maintenance reserve.
- Caller-funded shared unwind and funded checkpoints.
- Maximum unresolved keep uplift 25 bps of preflow NAV.

Backing 0.21 and uplift25 are provisional evaluation inputs, NOT approved production defaults.
Recalculate first productive opening, capital, float coverage under early acquisition bursts,
checkpoint waiting and low-activity losses using actual implemented configuration/receipt costs.
Old 0.24/0.465 ETH figures are unvalidated leads. One bounded evaluation of backing/funding around
fixed0.03 recipe. Preserve owner gate: 10% annual net gas, trailing30day successful activity, tokens0.
Report failure honestly, no omitted costs, assumed favorable buyer choice, subsidies or reduced fee.

## Canonical checkpoint contributions and issuance

Use useful PR6 corrections: cancellable deposits never suppress preparatory liquidation, but
actually committing deposits can fund atomic matched redemptions. Unused contributions belong to
actual payer and era, refundable. Zero quote/temporarily empty pool must NOT close era while requests
remain. Finalize after relevant successful checkpoint including partial fills, or when BOTH pending
deposits and locked redemptions end. Protected refund reserve, explicit funding topups while work
exists, return excess funding, lazy claims without payer enumeration, deterministic every-wei
rounding attribution. Refund liabilities excluded from NAV/investment/keeper/distributions/liquidity.
Payment classification stays request-funded through final redemption checkpoint. Regression sequence:
Alice funds; Bob joins; quote goes zero; Bob cancels; quote restored; Carol funds then cancels;
Alice cancels. Verify Solidity permanent regression and Python reconciliation.

Pending deposits hold GROSS cancellable escrow. Derive construction allowance at actual committing
checkpoint (settings/fee can change), epoch issuance ratio supports lazy holder settlement; reconcile
aggregate issuance and rounding without enumeration. Preview is estimated, cancellation before
commit remains. Required holder pricing work has explicit source: request-funded tails/bounded
scans separate from routine maintenance. Never temporarily expose contributions as free cash.

## Unresolved settlement uncertainty and exit liveness

Replace allocated face percentage with incremental MAX positive unresolved keep uplift, stored per
position from stored backing minus stored face, conservative settlement fee (fee reduction must not
invalidate bound). Remove exact stored contribution at terminal state INCLUDING owed returns.
No scanning all allocations for checkpoint. Permitted uplift relative to preflow NAV adjustable;
25bps only candidate. Fairness tests: genuine live incumbent, actual checkpoint entrant, unresolved
allocation, keep immediately before/after pricing, complete exits including charges+gas, multiple
allocations near bound, late allocation missing window. Report incumbent wealth effect separately
from entrant profit; marked NAV gain/no profitable extraction alone proves no fairness.

CLI AND app must provide explicit caller-funded exit, stated spend limit/expected wallet gas,
necessary bounded maintenance, settlements, unlisting, redemption, checkpoint contributions,
partial fills, claims. Once holder accepts cost, profitability filters cannot suppress essential
work. Do not assume unpaid keeper. Preserve manager's distinct self-funded behavior.

## App requirements

Final main ABI/config. Preserve community contracts/settings/deployment selection/legacy/keeper.
Show selected value/mint count; principal/backing/fees/reserves separately; renewal mode and paid
creator revenue implication; estimated count/minimum usable opening; accepted/live mint fee;
configuration changes between review/submission; pending requests/contributions/refunds;
cash/permission renewal wait; complete caller-funded withdrawal. Remove .06/.1248 defaults and
unconditional reuse copy. Do not live-cutover.

## Validation and delivery

Real FWA, main Shapes and main Pack collection on isolated mainnet fork; community pack differs.
Minimum cases: vault and new manager three paid primary mints; normal bid/fresh/keep/reuse;
single-use/owed recovery/no exit remint; settings with existing inventory/pending; each gas
coefficient propagates quote/pay/charge; markup; stale hash; fee up/down; contribution zero/restored
quotes/cancels/topups/checkpoints/partial/refunds; budget old-rate/clamp; >300 positions with scan
economically favored; keeper small jobs/tails; early burst then quiet; routine exhaustion vs cash;
live incumbent timing; full funded exit; disabled mint/list; callbacks/bytecode/EIP7825 gas.
Use billed transaction receipts, not Forge aggregate gas, for keeper viability. Independent account,
holder, keeper and creator cash-flow reconciliation; not copies of same formula. Evaluate current
and half fee separately at0.2 and0.5gwei. Label synthetic activity, no sensitivity called demonstrated
APR. One final exact combined revision, exact commands/status/limitations. Cadence: implement whole
slice with build/typecheck only, ONE integrated affected test batch, repair/retest only failures.
Broad candidate verification uses CANDIDATE_RUN=1. No unapproved paid resources or public broadcast.

Regenerate ABIs/manifests/keeper config/app types. Verify EVERY final setting, owner, dependency,
linked library independently; wrong recipe/stale ABI/omitted setting fail. Preserve historical
evidence with old revision, no reused signatures. Fresh production-path local fork rehearsal,
recheck existing balances/claims/manager creation before unsigned replacement plan. Deliver separate
main/app draft PRs, removed complexity, candidate vs production settings inventory, receipt and
reconciliation evidence, creator/holder economics under same scenarios, explicit requirement result,
unsigned package and genuine blockers with narrow decision/recommendation. Finish engineering even
if economics fail; keep PRs draft while release conditions remain.
