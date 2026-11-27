# Owner requirements

The owner's own words, numbered and dated. Later decisions are appended, never rewritten.
Section B2 records the prior outcomes. The 2026-11-17 asset-flow signature applies to that older candidate, not to the position-accounting integration. New evidence and any changed outcomes require review before launch.

## A. Requirements (owner's words)

Source: "FWA Depositor Vault: live findings and implementation plan", revision 2, 2026-11-15.

1. (2026-11-15) "main pool only."
2. (2026-11-15) "One immutable deployment with full functionality (distributions, token
   conversion, keeper compensation all in). Phases below are build and validation order, not
   product versions."
3. (2026-11-15) Gate: "10% a year net of gas at trailing-30-day volume with tokens at zero.
   Capacity at that hurdle is reported, not a pass or fail condition."
4. (2026-11-15) "No minimum TVL to start. The vault operates from the first deposit: small
   minimum deposit (first-issuance protection only), and it lists whenever idle ETH above
   reserves covers one position."
5. (2026-11-15) "Fixed costs must therefore scale down: a checkpoint runs only when there are
   pending deposits, redemptions or a distribution due, and sync and harvest batches are skipped
   when their gas exceeds the value they realize."
6. (2026-11-15) "RPC: Tenderly's public mainnet gateway (https://mainnet.gateway.tenderly.co) as
   the default MAINNET_RPC_URL."
7. (2026-11-15) "Larger packs: yes. ... The vault carries a governed allowed-P set bounded in
   bytecode; canList already rejects any size the live cap makes unprofitable."
8. (2026-11-15) Gate conditions (plan 0.5): "Go only if net of gas the bid outcome is positive at
   the gas ceiling, annualized return at last-30-day volume clears the hurdle with tokens at
   zero, and there is at least one usable exit window a day."
9. (2026-11-15, overnight instruction) "complete the entire process e2e without asking me for
   more info ... create a list of decisions you made that you normally would have asked me
   about" (see docs/DECISIONS.md).
10. (2026-11-16) Gate volume window: "Keep 30-day" (answer to D17; 7-day not adopted).
11. (2026-11-16, repair review) "Keep the owner's existing decision to use trailing 30-day volume
    for the formal economic gate, unless new evidence demonstrates that it produces materially
    misleading decisions." "Do not deploy contracts to mainnet or spend real funds." "If the
    corrected economics no longer justify the vault, state that clearly."
12. (2026-11-16) Canary: "approved." Roles: "why do we need both? seems overly complex" (D44).
13. (2026-11-16) Gas: "no, don't wind down. admin should be able to raise the gwei limit as
    needed." "is the gate the max gas? if so use 0.5 gwei to start" (D42).
14. (2026-11-16) Tokens: "we shouldn't sell" ... "i'd rather claim + burn them" (D43; supersedes
    the token conversion in item 2).

## B. Proposed outcomes (2026-11-15; superseded by B2)

Numbers measured at block 26,424,971 unless stated. P = 0.03 ETH pack, B = 0.0363 ETH backing.

| # | Outcome | Proposed number | Measured by |
|---|---|---|---|
| O1 | Holder return at the gate | >= 10%/yr at 30-day volume, 1.2 gwei, tokens zero | model: +86% (30 d), +13.8% (7 d) |
| O2 | Edge per selection, bid outcome | +B (k - 1) = +1.40 mETH before gas; gas per cycle about 0.73M | fork: k 1.0385 live, 1.0378 to 1.0576 measured by bucket |
| O3 | Purchaser on a bid outcome | receives 0.9 B = 0.03267 ETH; vault gets the pack back | ForkSelection bid test (absolute) |
| O4 | Vault on a keep or silent outcome | +B (1 - s) = 0.035937 ETH back; pack goes to purchaser | ForkSelection keep and silent tests |
| O5 | Keeper pay | at most gas x min(price, 1.5 gwei), from 5% of harvested fees, at most 25% of value realized | ForkSelection harvest test |
| O6 | Cheapest way to stall holders | keep FWA's queue busy through a blackout: about 0.054 ETH per 12 h delayed; self-heals | reasoning (D15); 120 of 121 historical blackouts drained |
| O7 | User pays | mint fee 0.001 ETH per 0.1 ETH of Shapes (about 0.0003 per pack); no vault fee | lifecycle round trip (absolute) |
| O8 | End state | wind-down with zero acquisitions returns every holder's NAV share; only the 0.01 ETH seed's share remains | lifecycle wind-down test |
| O9 | Token income | counted as zero; one real buyback paid 20 listings 2.5e12 wei in total | ForkTokens |
## B2. Revised proposed outcomes (2026-11-16, supersede section B; signed 2026-11-17 via asset-flow.json)

Section B's O2 and O5 rested on a 5% keeper fee skim that exceeded the edge (D19). Numbers at
block 26,424,971 unless stated; P = 0.03 ETH pack, B = 0.0363 ETH backing, k = 1.0385.

| # | Outcome | Proposed number | Measured by |
|---|---|---|---|
| O1 | Holder return at the gate | >= 10%/yr at trailing-30-day volume of successful acquisitions, tokens zero, after every expense, at the 0.5 gwei gas ceiling: closed form +121%, simulated +76% (p5 -8%) | sim/out/forward.md section 1 |
| O2 | Edge per bid cycle | B (k - 1) = 1.396 mETH before gas; cycle gas 0.8M: net 1.264 mETH at 0.15 gwei, 0.516 at 1.0, 0.076 at 1.5; break-even 1.59 gwei | fork gas (ForkReconcile), D20 |
| O3 | Purchaser on a bid outcome | receives 0.9 B = 0.03267 ETH; the vault keeps the pack | ForkSelection bid test (absolute) |
| O4 | Vault on a keep or silent outcome | B (1 - s) = 0.035937 ETH back; pack goes to purchaser | ForkSelection keep and silent tests |
| O5 | Keeper pay | quoted gas per operation x min(basefee + 0.05 gwei, 0.5 gwei gas ceiling; 2 gwei for redemption and wind-down work, D61) + 0.00002 ETH per unit of work, no premium (D56); offered by a replaceable policy contract, capped by the vault (D57); from free ETH within refilling budgets; harvest paid only if pay <= 25% of ETH realized; no-op calls pay nothing. Rehearsal: every V1 call below the ceiling profits (+12% to +148%) | ForkVaultAdversarial, ForkSelection, canary rehearsal |
| O6 | New packs | built only when one bid cycle repays the build (1.39M quoted gas + 0.0003 ETH + 1 work fee): quoted price below ~0.52 gwei | D20, test_restockGated |
| O7 | User pays | mint fee 0.001 ETH per 0.1 ETH of Shapes; keeper gas; no vault fee | lifecycle round trip (absolute, every wei) |
| O8 | End state | wind-down returns every holder's NAV share; only the seed's dead-share slice remains | lifecycle wind-down test, keeper rehearsal |
| O9 | Historical size (superseded by A2.15) | at most 300 positions (about 20 ETH); worst-case checkpoint 10.17M gas; the 2 ETH canary holds 28 positions | checkpoint gas tests, canary rehearsal |
| O10 | Liabilities | escrow, redemption and distribution reserves and settled claimables are never deployable or payable to keepers | test_settledUnclaimedEthIsNotDeployable, invariants |
| O11 | Token rewards | claimed and burned (supply falls by exactly the claimed amount); never sold; holders pay no gas for it | ForkTokens, canary rehearsal |

## B3. Accepted risk: owner-key compromise (owner, 2026-11-17, D61)

Admin changes apply at once (D58) and one owner holds every role (D59). A compromised owner key
can raise keeper pay to the bytecode maxima and run the keeper itself: at most the budgets'
balance plus refill at the maximum rates, about **0.045 ETH in the first 24 h and 0.015 ETH a day
after** at canary budgets (routine 0.03 ETH; no essential budget, D64) (measured on a fork: 0.038895 ETH taken at once from three positions,
`test/audit/release/AuditOwnerExtraction.t.sol`). Raising `tvlCap` exposes more holders to bad
settings but does not raise that rate. Mitigation: the owner key is a multisig or hardware wallet.

Update (owner, 2026-11-22, launch audits A and B): the numbers above understate the current
bytecode maxima (routine 0.3 ETH cap at 0.02 a day, essential 0.1 at 0.005 a day, 50 gwei ceiling;
audit B measured 0.3726 ETH over 30 days on the canary). The owner accepts owner-key compromise as
a risk without a numeric bound and does not want it raised again.


## A2. Position accounting integration (owner, 2026-11-18)

Source: the owner's “Remove the position ceiling from shapes-fwa-pool” implementation brief,
retained in `docs/CODEX-POSITION-ACCOUNTING-IMPLEMENTATION.md`.

15. One production vault, one capital pool, one authoritative accounting book. Remove the arbitrary
    position ceiling, required full portfolio valuation, and ordinary keeper inventory scans.
16. Preserve paid primary Shapes mints, their fees, existing splitting/packing behavior and allowed
    pack sizing. The research fixture's 0.03 ETH packs do not set production size policy.
17. Preserve share pricing order, partial redemptions, holder liabilities, claims, cancellation,
    dead shares, high-water marks, distributions and wind-down. Token rewards stay claim-and-burn,
    valued at zero.
18. Use bounded ordered global acquisition processing, authenticated keep/kick receipts, exact
    active fee aggregation, bounded allocation recovery and unique 10,000 wei backing identifiers.
19. Keep admission economics, oracle constraints, capital and liquidity reserves, allocated exposure,
    permissionless maintenance and the replaceable keeper policy with its vault-enforced caps.
20. No factory, sharding, shared exposure contract, adaptive sizing, new mint/coin strategy, or
    weakened valuation. No merge to main, mainnet deployment, real-fund transaction or owner signature.

B2 O9's 300-position limit is superseded by item 15. Its replacement is constant valuation work
and measured per-call gas bounds, with finite capital and external protocol capacity. The remaining
B2 amounts are historical measurements until the integrated candidate is measured. Maintenance of
new global FWA acquisitions is a new explicit cost borne by free vault ETH inside existing budgets;
no new holder charge or reserve/budget change is authorized by this requirement.

Current risk clarification (engineering, 2026-11-18): B3's budget amounts bound maintenance paid
from free vault ETH, not separately request-funded checkpoint payments. A checkpoint can pay from
`processingPool` at most its fixed 400,000-gas quote plus one work fee, once per 12-hour interval.
At the existing bytecode maxima of 50 gwei and 0.00005 ETH work fee that is 0.02005 ETH per
checkpoint, limited to the charge pool actually funded by requests. This route already existed;
the portfolio-dependent charge is removed. No other holder liability can fund it. B3 is therefore
not a bound on all gross ETH an owner acting as keeper can receive. The candidate's new measured
outcomes and funding shortfall are in `docs/POSITION-INTEGRATION-ACCEPTANCE.md`; no new approval is
recorded here.

21. (2026-11-18, review repair) Owner approved: "Approve provably unexposed cursor advance".
    This refines the requirement to inspect every global entry: a constant-work, unpaid advance
    is allowed only when onchain state proves no outstanding FWA position/identifier, active or
    allocated membership, or pending receipt can hide relevant work. Any exposure retains strict
    ordered journal processing. Idle inventory held by the vault is not FWA exposure. Checkpoint
    may apply the same proof so an empty seed vault can price its first deposit without rescue ETH.

22. (2026-11-18) Efficient-journal revision: "Separate cheap reads from expensive changes." Global
    journal reads have an independent bounded batch; terminal IDs must not shrink it. Stop before
    exceeding actual own-transition limits. Compensate full jobs, verified own selections/returns,
    and necessary residual tails at FWA's checkpoint window with its request queue drained.
    Unexposed cursor advances remain unpaid. Enforce eligibility onchain and schedule it efficiently.
23. (2026-11-18) "Keep the current journal base until the new job boundaries are measured."
    No completion bonus. Measure32/64/128; finish actual successful-foreign and standaloneQ360
    full-holder receipts at matched0.2/0.5gwei, default policy and maximum markup, and ordinary
    keeper profitability preflight. Gas-limit padding is separate from billed expense.
24. (2026-11-18) "Use vault operating expenses as the default funding model." Measure optimized
    costs, pay required work when needed, clear the backlog, finish exits, and assess holder returns
    before proposing allowances. No assumed recurring mint-revenue sponsorship or silent minimumTVL.
25. (2026-11-18) Profile memory use for newly minted IDs and shared restock economics once per
    validation batch. Preserve the paid primary mint, ten-way split, pack recipe and creator fee.
    "Treat O2 as a bounded expense decision after one focused optimization pass." No revised O2
    number is approved by this request.
26. (2026-11-18) "keep ordinary synchronization funded as routine upkeep while preserving caller
    funded unlisting and liquidation." Mixed sync calls and gas ceilings follow the same class.
    Display known backlog cost, available cash and permission separately; reversibly stop new
    exposure when mandatory work is unaffordable. No automatic permanent wind-down/reserve system.
27. (2026-11-18) Complete event-based returned-pack discovery: authenticate both actual bid events,
    retain unreconciled own selections, discover expiry independently, replay missing history on
    existing-index upgrade, and verify more than16allocations with restart/reorg behavior.

## A3. Unified shapes FWA system (owner, 2026-11-21)

Source: the owner's "Implement the unified shapes FWA system" brief (2026-11-21, main 78ad729,
research PR #1). It supersedes A2.20's "No factory ... shared exposure contract ... new mint/coin
strategy" for this work, and D62's bid-favouring backing floor. Owner's words:

28. "Build one unified system for automatically managing shapes and shape packs on FWA, supporting
    two products": "A shared pool where multiple depositors contribute capital and earn
    proportional returns" and "A personal manager factory where anyone can deploy their own isolated
    manager". "Both products must execute the same underlying strategy implementation."
29. "There must be exactly one authoritative implementation of these strategy mechanics." "Do not
    add a separately funded central strategy contract or shared asset custodian." "Assets belonging
    to one manager must never become accessible to another manager or to the factory."
30. "The factory must not have authority to withdraw funds, replace the manager's owner, redirect
    proceeds, or change individual manager settings." "Do not charge an additional factory or
    management fee". "Do not introduce upgradeable manager implementations unless absolutely
    necessary."
31. Recipe: "A 0.06 eth pack consisting of one newly minted 0.05 eth shape and one newly minted 0.01
    eth shape" using "the deployed shape packs contract's native ability to mint shapes directly into
    a pack". "Do not redeem and remint returned packs merely to collect another fee." "Do not reduce
    the live mint fee from 0.001 eth merely to force a recipe to pass."
32. Keep incentive: "Pack value: 0.06 eth. Backing: approximately 0.0648 eth ... Minimum modeled
    advantage for keeping versus the best alternative: 0.0003 eth after relevant gas." "These are
    starting points, not fixed constants." "Pause fresh investment when the required economic
    conditions are unavailable. Preserve settlement, asset recovery, and withdrawals".
33. "Prefer live FWA admission economics and independent account safety checks unless the tests
    demonstrate a need for centralized exposure enforcement." "Never allow a factory controlled
    registry to become a custody authority."
34. "The system should operate with one keeper codebase." "One manager with inadequate cash, paused
    listings, or a stuck position must not prevent useful work on other managers." "Do not add an
    onchain keeper coordinator unless it is necessary."
35. "Preserve the pooled vault's recently implemented two step ownership handover and prohibition
    on ownership renunciation." "Do not make production contracts upgradeable just to simplify code
    sharing."
36. "Use the formal existing 10% net annual return requirement as the pooled vault acceptance
    hurdle. Do not value FWA token rewards as depositor income." "If an economic requirement fails,
    do not hide the failure or lower the requirement."
37. "Do not merge, deploy publicly, move real funds, or change the live shapes mint fee." Create a
    branch from main, push, open a draft PR.

B2 O3/O4/O6 change meaning under item 32: purchasers are now expected to keep (B (1 - s) back to the
account and a replacement build with fresh mints) rather than bid. The restated outcomes are in
`asset-flow.json` (unsigned) and `docs/UNIFIED-SYSTEM.md`; no new owner signature exists.

## A4. Complete the unified system for release (owner, 2026-11-21)

Architecture accepted as built (A3); "Do not redesign the project, introduce additional contract
layers, or reopen decisions that are already supported by evidence."

1. FWA payment receipts: "A payment callback failure must not permanently prevent an account from
   resolving a legitimate FWA position or recovering its funds." Recovery must authenticate the FWA
   listing, depositor, pack, status and outcome; prevent fabricated, duplicate and misattributed
   receipts; preserve protected liabilities and correct NAV; work for pools and managers and "even if
   the original callback exhausted its gas allowance". "Do not assume that matching an eth balance
   increase alone proves a particular settlement outcome." (D84)
2. Recipe: a matched comparison of 0.03 and 0.06 packs through the formal simulator with identical
   inputs, enough seeds for the downside, keep rates 0-100% and stressed demand and gas. "Retain 0.06
   as the preferred recipe unless the stronger comparison demonstrates that another simple recipe
   materially improves the combined objectives." 10% a year net stays the minimum gate. "Do not reduce
   the current 0.001 eth shapes mint fee." The all-bids case is a stress case, not assumed to be a
   lower bound.
3. "Decouple purchaser gas assumptions from keeper compensation." "Prefer an explicit, bounded
   purchaser gas assumption." No new oracle, role or configuration subsystem. (D85)
4. Production keeper rehearsal on a fresh fork with the production image, encrypted keys, durable
   state, multiple managers, outcomes, restarts, container replacement, backup keeper, lost responses,
   nonce races, per-account failure isolation, index persistence and reorgs. Retire scripts that
   target the old `restock` API. "Do not simulate successful recovery by manually changing protected
   accounting state."
5. Independent review of the final source; all tests, reconciliations and regimes to the wei.
6. A fresh unsigned acceptance package bound to the final bytecode, values, libraries and keeper
   image. "Do not generate or reuse an owner signature."
7. Canary: the existing 2 eth pooled canary as a limited technical deployment. "Do not increase the
   initial capital exposure merely to produce better modeled investment results." "Distinguish
   authorization to deploy a contract from authorization to offer the personal manager product
   publicly."
8. Final simplification pass without weakening security, accounting or performance.

Update (owner, 2026-11-22): no canary, ever. Item 7 is withdrawn; deployment uses
`deploy/mainnet.json`, which has no deposit cap (set 2026-11-17, cba0cf5).
"Do not merge, deploy, sign acceptance documents, or spend real funds."


## A5. Main pool completion (owner, 2026-11-24)

The owner's implementation request supersedes six-unit launch assumptions, compulsory buyer-keep
backing and the external keeper policy. Full acceptance scope is in
`docs/MAIN-POOL-COMPLETION.md`; the originating chat remains authoritative.

1. “Launch with **0.03 eth packs containing three directly minted 0.01 eth shapes**.” Launch
   units are 3 and mask 8, immediately owner-adjustable for later operation.
2. “The owner's revenue comes from shapes mint fees.” Every fresh Shape pays the live fee within
   the explicitly accepted maximum. No bulk/split substitution or public mint-fee change.
3. “Preserve unlimited total positions with bounded incremental work.” Preserve pooled vault,
   independently owned managers and shared implementation; no factory control over existing managers.
4. “Use one consistent calculation for the payment envelope, actual compensation and relevant
   charge calculations.” Account-owned numerical gas calibration, verified operation counts and
   routine markup; remove the external policy path and its deployment machinery.
5. “Use one effective economic configuration per operation.” Expected configuration guards bind
   economically sensitive work, while claims, cancellation and necessary recovery remain available.
6. “Implement two account owned renewal modes”: FreshAfterAcquisition and ReuseReturned. Fresh
   mode uses single-use verified acquisition eligibility, actual returned principal, paid fresh
   mints, a separate float, protected maintenance reserves and explicit cash/permission waits.
7. “Unused checkpoint contributions remain attributable and refundable to their payers.” Keep
   canonical wei attribution across zero quotes, cancellations, topups, partial fills and successful
   checkpoints. Gross escrow is priced for construction at commitment using lazy epoch issuance.
8. Bound incremental unresolved keep uplift, replacing allocated face percentage. The local
   evaluation uses backing70,000bps, uplift25bps, one fresh renewal float and reserve0.005ETH.
   “The 0.21 backing and 25 bps threshold are provisional evaluation values, not approved
   production defaults.” The existing net depositor return requirement remains in effect.
9. “Provide an explicit caller funded exit path in the CLI and app.” Expected wallet spend and
   caller limit cover necessary bounded work, settlements, checkpoints, partial fills and claims.
10. Real-counterparty forks, measured transaction receipts and independent cash-flow reconciliation
    must evaluate creator and holder economics together, separately at current fee and fork-only
    half fee, at0.2/0.5gwei. Synthetic assumptions are labelled; no manufactured passing return.
11. “Keep public network transactions, production mint fee changes, live application cutover and
    merges outside this task. Prepare the deployment package unsigned.” Draft PRs are authorized.

No historical asset-flow signature or deployment acceptance authorizes this changed candidate.

## A6. Individual manager closeout (owner, 2026-11-24)

“Go ahead and finish the individual manager: owner-paid exit flow, manager-only deployment
package, economics and focused validation. Work autonomously, update the draft PRs, and keep the
shared vault closed. No public transactions or merges.”

Complete the manager's own wallet flow, independently deployable factory/implementation package
through the existing deployment path, and manager-specific owner/keeper/creator cost accounting.
The pooled-vault return result and pooled checkpoint uplift gate are not manager evidence. Preserve
the fixed launch recipe, individually owned managers, common strategy implementation and existing
community application. Production settings remain provisional; public deployment, production fee
changes, live cutover, acceptance signing and merges retain their existing separate authority limits.


## A7. Remaining manager operating validation (owner, 2026-11-25)

The owner asked to complete the remaining billed operating measurements, realistic operating-period economics, keeper readiness, and unsigned deployment preparation: “do all those. i'm going to bed. have them all done when i wake up.” After an explicit request for more validation time, the owner answered: “no budget cap”. This removes the cumulative validation-time cap for this remaining task. It does not authorize public transactions, production fee changes, live application/service cutover, signatures, a shared-vault deployment or merges.

The owner clarified that the new shared vault is undeployed; “closed” must not imply an existing deployed candidate. Its app launch remains disabled. Any local evaluation setting and simulation cohort is an agent-selected method, not an owner-approved production default or a newly required sample size. Complete available engineering and evidence, and report genuine economic failure or remaining release decisions honestly.

## A8. Reuse-only manager, measured keeper pay and pack-preserving migration (owner, 2026-11-25)

The owner superseded A5's two renewal modes: “we should only have one mode: reuse. no need for the other.” Returned packs are relisted intact; new packs are minted only for opening, funded growth or inventory that a buyer kept. Launch remains 0.03 ETH with three directly paid 0.01 ETH Shapes. Remove the FreshAfterAcquisition mode, eligibility/remint machinery and dedicated fresh-renewal float; retain immediate account-owned settings and actual inventory values/counts.

The owner approved switching from fixed quoted compensation to the community pattern of **bounded measured-gas payment**, with safeguards and gas measurements for these main operations rather than copied community coefficients. Verified work allowances become payment caps; compensate measured work plus account-owned overhead at the bounded actual gas price, with consistent routine markup/work fees, budgets, protected cash and minimum payment. Numerical payment inputs remain adjustable. No automatic subsidy or unnecessary work is authorized.

The owner approved UI-orchestrated migration and explicitly requested the destination import capability in the first version: “lets build this into the first version”. Owners must be able to unlist, transfer and register existing packs without redeeming/burning/reminting their Shapes. Imports must be bounded and owner-controlled, validate actual canonical assets/value/contents and record each pack once. Migration uses a stated durable wallet spending limit and verifies source/destination ownership; it must not enable automatic liquidation while awaiting transfers. A generic owner-paid unlist capability is permitted as necessary to make this preserve-assets workflow concrete. There is no approval here for factory authority over existing managers, an upgradeable manager, arbitrary pack makeup, or changing production settings.

A7's no execution-time cap continues for this follow-up. No public transaction, production mint-fee change, acceptance signature, live cutover, new shared-vault deployment or PR merge is authorized. Earlier quoted/Fresh economic receipts and studies remain historical at their original source/configuration and cannot be used as current measured-payment acceptance. Carry forward valid unchanged evidence only.

## A9. Launch-review decisions (owner, 2026-11-26 to 2026-11-27)

Recorded from the owner's messages during the manager launch review; quotes are verbatim. Details in D86 and the 2026-11-26 entries of `docs/DECISIONS.md`.

1. **Exit work is unpaid.** "we shouldnt pay keepers for exits". Wind-down and shortfall `unlist`, `liquidate` and the owner recovery calls run for anyone, pay the caller 0, and a nonzero `minPay` on them reverts. A personal manager has no holder shortfall, so its exits begin only when its owner enters exit mode.
2. **One keeper budget.** Routine keeper pay draws on a single refilling budget (`routineCap`, `routineRate`); there is no separate essential budget. Pay is bounded measured gas plus account-owned overhead plus a flat work fee per unit of work, with no percentage markup.
3. **Unused code is deleted, not disabled.** "we should remove unused contract code, not just set settings to inactive".
4. **Backing booked for returned packs is not build cash** (audit B finding E1, "Yes, fix E1"). Returned packs relist first; a build may spend only ETH beyond the backing reserved for idle inventory.
5. **Owner pack mix and backing.** The owner sets exact counts per pack size at creation (`design`) and may change them. New managers post backing of 11053 bps of pack value. The build gate charges neither gas nor mint fees to a selection; a keep must return at least the pack's face at FWA's 5% fee cap.
6. **Whitelist removal must not brick the system.** "If we add it, we should make sure it doesn't brick the system if it gets removed from the list. Same with packs too". If FWA removes ShapePacks from its collection whitelist, new listing stops, while settlement, sync, unlisting, exit and withdrawal of every pack and wei continue.
7. **Live inputs.** The accepted Shapes mint fee is 0.0005 ETH. The reserve is 0.006 ETH and only gates new exposure; routine keeper pay may draw on it and the owner may withdraw everything.

B3 (owner-key compromise accepted) continues. No public transaction, signing, mint-fee change, cutover, shared-vault deployment or merge is authorized by this section.
