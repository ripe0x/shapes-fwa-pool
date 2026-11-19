# Efficient journal revision results

2026-11-18. **The approved candidate is locally measured; economic acceptance remains blocked.** Code is `aa38fab`. Combined baseline/candidate:517 transactions, 27.869594973162081536 simulated ETH aggregate value, 8.3 ETH funded once, no repairs/topups in the 199-transaction candidate, entry restored. All 24 candidate journal rows show positive calibration-receipt net, positive exact signed-estimate net and accepted ordinary preflight. Exact archive: `receipts/efficient-journal-candidate-summary.json`, results, ledger and analysis. Independent evidence review is `receipts/efficient-final-receipt-review.md`.

The measured schedule is 22k/record, 110k holder-tail base and 80k qualified distribution-proof work, with ordinary 85k and pack 325k unchanged. Default holder/distribution singletons bill 122,417/202,270 against 132,000/212,000 quotes; full 128 bills 2,233,071. All holder liabilities/processing-pool/free-cash deltas reconcile. These are refunded entries, operator `minPay=0` receipts and separately checked signed 80% preflight, not actual signed 80% receipt claims. Candidate has one Active position versus baseline 40. No matched-state source-only savings or universal keeper profit is claimed.

The baseline named full-holder standalone fixture bills 346,017 gas; candidate does not repeat it. O6 passes 0.0002 ETH, O2 fails 1,919,655 versus 1,750,000. Runtime 24,451/23,001 bytes. No allowance, refill, fee, minimum TVL, accepted outcome or signature changed. Exact original and amended plans remain byte-for-byte frozen, including their pre-approval status text; approval and completion are recorded in execution-status/results instead.

Complete current funding/conditional returns, harvest attribution and next recommendation: `REVIEW-FUNDING-PROPOSAL.md`. Timed candidate paths have 3/4 complete exits but only 1/4 fully paid routine paths.32 of 44 timely underpaid harvest calls are zero under the fee-share gate, independent of a larger allowance at those call states. A primary-bot-only fix cannot enforce a vault-wide expense rule.

The detailed pre-receipt report below is retained for its named source. Its pending 8559 batch/standalone receipt and unchanged numerical quote statements describe the earlier phase. The owner's scope remains `EFFICIENT-JOURNAL-REVISION.md` and D69; local measurement approval is not economic or release acceptance.

The contract executes an automatic journal job, bounded independently by 128 global records,
16 actual own transitions,16 supplied terminal IDs and16 pruned heads. It stops before consuming
a seventeenth own transition. IDs cannot shrink the read job. The public interface deliberately
changes to `sync(ids,witnessId,minPay)`; current keeper and test callers migrate together.

Full jobs and actual own work qualify for journal compensation. A short foreign tail qualifies
only for a fresh blackout checkpoint with its external queue drained and pending holder flows,
or an authenticated distribution that can exceed0.01 ETH after the maximum sync envelope.
A configured distribution percentage alone cannot qualify. Post-harvest liquidity is calculated
from unclamped free cash plus genuine fee credit before subtracting reserve and compensation.
Unqualified tails can advance unpaid with `minPay=0`; insufficient positive `minPay` rolls back.
The provably unexposed advance stays unpaid. No completion bonus was introduced.

All sync uses routine upkeep permission, including while shares are locked or the vault winds
down. D64 keeps unlisting/liquidation caller-funded when essential permission is zero. The keeper
waits for useful journal jobs and reversibly pauses new exposure if known backlog exceeds actual
free ETH or routine permission. Its status reports those amounts separately. No automatic
permanent wind-down or new reserve framework was added.

The event index authenticates actual ETH/token depositor-bid events independently of older
unresolved allocations. It retains unseen selections, discovers expiry independently and rotates
OWED recovery. Existing indexes replay newly relevant history without losing their financial or
transaction head. Canonical rollback, stale-writer guards and restart tests cover the projections.
Real eighteen-allocation event histories and actual ETH/token bid payloads are used; a live
seventeen-allocation PackVault/bid/reorg scenario is not claimed.

Restock consumes new split IDs from memory and persists only true leftovers, keeping the exact
LIFO recipe and paid primary mint/ten-way split/creator fee. Shared economics are read once before
minting; independent list admissions still re-read them. Seven matched inventory profiles improve
receipt-equivalent execution by 1.28%–7.24%; ten small packs improve by 674,385 gas (6.53%). Current
fixed holder compensation is unchanged, so these execution savings initially accrue to keepers.

## Verification and its limits

`receipts/efficient-focused-results.json` records commands, source hashes, passing checks and
preserved failures. Five new real FWA refund/journal/distribution cases, seventeen lifecycle and
real-selection callers, five minimum-seed/cash-only callers and an authentic unexposed successful
history check pass. The incremental production suite's three old selective-work expectations were
repaired and pass; its other thirteen affected cases passed. Fourteen accounting-model tests,
keeper policy checks and durable event-index tests pass.

The two fresh affected economic scenarios retain O2's 1,919,655 failure and O6's 0.0002 ETH pass,
with no bucket mismatches; `receipts/efficient-o2-o6-results.json` preserves the zero-test/cache
attempts rejected before actual verification. Earlier flow files were restored after archiving
the current source-stamped outputs.

Both refreshed fork traces reconcile all financial buckets to the wei. Observed keeper payments
are replay inputs; equality proves accounting transitions rather than independently proving quote
pricing. The full cycle now directly asserts0.4 gwei BASEFEE/0.45 gwei TXGASPRICE inside an executed
call. Cold receiver samples remain46,462/69,730 gas. Current production runtime is 24,451/22,997
bytes for PackVault/VaultLib, leaving125/1,579 bytes below EIP-170. The maximum combined
128-global/16-own/16-terminal/16-prune job has not been reached in one real call; the seventeenth
own-stop case is accounting-model evidence.

The earlier full-holder342,766 bound double-subtracted finalized Foundry refunds and is withdrawn.
The current direct finalized sample is 345,937, below Q360 by 14,063 (4.07%); the reconstructed
pre-refund number is 375,537. Caller-meter-plus-intrinsic values are proxies. Installed Foundry
source and raw prior evidence are preserved in `receipts/restock-efficiency-meter-correction.json`.
Actual signed receipts remain separately required.

## Receipt calibration

The concrete new batch is prepared in `receipts/efficient-journal-local-plan.json` with exact
source/artifact hashes. It has not run. It uses a separate 8559 endpoint, six existing named clean
test actors,8.3 simulated ETH funded once, at most540 transactions/32 ETH aggregate value across
restored branches, normal code/gas limits, and one optional reviewed quote-only candidate.
The earlier8557 node and completed77-transaction batch remain separate historical evidence.
Explicit owner approval is pending. No public transactions or real funds are authorized.

The prepared scope covers natural refunded prefixes around32/64/128, genuine holder and
qualifying distribution tails, matched0.2/0.5 gwei/default/maximum policy offers, ordinary keeper
planning/profitability preflight, inventory receipts and standalone full-holder Q360 checkpoints.
A manually sent loss-making measurement will not be called keeper willingness.

Authentic exposed successful-foreign billed small/full/tail receipts remain a separate blocker.
A real historical cached-success queue exists, but new vault admission rejects its outstanding
requests; processing it before admission makes the unpaid unexposed proof skip it. Faking book
state, blockhashes or coordinator authority would test a different system. The report preserves
that gap rather than using refund receipts as a substitute.

## Economic acceptance

Vault operating cash is the default expense source. Creator mint fees are separate revenue,
never an assumed recurring subsidy. The completed comparison uses 30 operating days plus up to
30 exit days, three fixed seeds per active-volume case, first-position/canary/larger capital,
matched 0.2/0.5 gwei, zero demand and 71/439.7 successful acquisitions per day. It includes the
recorded refund ratio, all operation quotes, whole paid mints, actual modeled claims and caller
gas proxies. Foreign activity continues through the final claim. The core reconciles to real
fork traces; stochastic external timing is neither fork replay nor a forecast.

**The existing daily clock is not suitable for accepting operating economics.** It gives policy
a 10^12-second settlement surrogate instead of FWA's actual 3,600 seconds, uses the same day-start
time for open and blackout phases, and resolves own purchaser responses the next day. Those
inherited simplifications can change expiry work, cash-return timing, rescue need and exit
completion. The counts and returns below describe hypothetical accounting paths, not authentic
continuous keeper availability or achievable returns. They cannot justify a budget recommendation.
The disclosure and unchanged raw evidence are bound in `receipts/efficient-operating-results.json`.

Of 84 primary cases, 56 finish; only 40 avoid all routine funding stalls while paying full
routine quotes. All 28 incomplete cases finish in separate final-holder rescue diagnostics,
with unpaid sync gas charged to the holder and actual clipped payments credited. All 112
asset ledgers have zero gaps. Rescue and primary runs have identical operating prefixes.
These are not 112 funded-operation passes.

In the hypothetical first-position 0.15 ETH case, busy-volume/0.2 gwei modeled complete exits lose
18.69%–30.19% across the three illustrative seeds, including caller proxies. Some stop adding
exposure after an early bid because seven leftover Shapes hold 0.07 ETH while relisting needs
more liquid backing. Higher permission supplies neither cash nor acceptable returns. This does
not introduce a minimum TVL. The intended small-vault economics remain unsupported by credible
current receipt/timing evidence.

The diagnostic allowance comparison uses existing hard maxima, 0.3 ETH initial permission and
0.01 ETH/day, without adding cash. Configured canary is 0.03/0.0008 ETH/day; mainnet is
0.1/0.005. Larger permission alone does not solve the cash/reconciliation cycle or establish
returns. No deployment values changed and no increase is recommended on these incomplete
receipt inputs. Full per-operation costs, inventory/cash observations, rescue attribution,
reproducible command, source/database hashes and limits are in
`receipts/efficient-operating-results.json` and `efficient-operating-baseline.md`.

Caller costs use explicitly historical actual Q400 gas counts or operation-quote/caller-meter
proxies. The 25% gas-limit padding is not treated as billed gas. Three seeds do not establish an
expected-return interval or the annual return hurdle. No new minimum TVL, allowance or outcome
change is adopted.

| Outcome | Existing requirement | Current bounded evidence | Status |
|---|---|---|---|
| Seed/first deposit |0.01 ETH seed needs no donated rescue |673 authentic foreign records skipped unpaid; first pricing succeeds |Affected pass|
| Returned-pack discovery |>16 allocation history; bounded discovery/restart/rollback |Actual historical bid/allocation payloads; projection upgrade and canonical-cache tests pass |Functional repair; live multi-allocation gap disclosed|
| Paid journal jobs |Full automatic bounded jobs; actual own work/required tails |Five real FWA refund regressions; independent bounds and optional-tail refusal |Affected pass; combined own maximum unmeasured|
| Keeper quote support |Actual estimate/billed small/full/tail and full-holder |Current finalized fork meter; prepared signed matrix not run |Pending approval; successful-foreign gap remains|
| O2 build/list |≤1,750,000 quoted gas/position |Fresh max-load quote 1,919,655; ideal marginal 1,810,000 |Fail; no outcome increase|
| O6 checkpoint |≤0.0002 ETH at routine ceiling |Q360×0.5 gwei+0.00002 ETH=0.0002 ETH; current fork sample 345,937 |Bounded pass; standalone receipt pending|
| Recurring upkeep |Actual cash and permission; all expenses before returns |18,281 records in 143 jobs of at most 128 cost 0.2802925 ETH at 0.5 gwei before own work |Economic acceptance unresolved|
| Holder returns/exit |All expenses; backlog cleared; actual claims |112 exact ledgers on hypothetical daily paths; 56/84 primary model exits plus 28 rescues |Timing surrogate invalidates availability/return acceptance; no annual-return pass|

At current quotes the archived global-only cost is 0.0093430833 ETH/day at 0.5 gwei, against mainnet
steady refill 0.005. Larger batches save 13.2% compared with 16 but do not settle operating economics.
A refill is permission, not income; paying from existing free cash reduces holder returns.
The formal 10% annual return requirement cannot be established by an illustrative 30-day model.
No broad release campaign or new owner signature has been run. The read-only asset gate
(`--no-run`) remains incomplete against historical scorecards; its output is archived without
regenerating or replacing the prior sixteen-regime evidence.

## Cash and reconciliation during an exit

A focused operating-model case exposes a second distinction beyond spending permission. After a
partial redemption checkpoint, nearly all liquid ETH can sit in protected holder reserves. FWA
may then return a pack through a bid without returning cash. The vault must reconcile that return
before inventory liquidation, but ordinary sync has almost no free ETH from which to pay.
Increasing permission alone does not solve this cycle.

The current modeled example has 3 wei actual cash, 2 wei free cash, 0.18 ETH of returned-pack
principal awaiting book reconciliation and 0.3 ETH of routine permission. The existing holder
`minPay=0` path can reconcile and release the next liquidation step. The separate rescue diagnostic
charges that transaction gas explicitly to the holder and distinguishes it from a fully funded
keeper exit. No protected holder money is reassigned, no new rescue subsidy is assumed and no
reserve rule has been changed. The available authentic fixtures cannot reach the required pre-priced-holder timing: their
1-hour allocation window expires before the second 12-hour checkpoint. This remains a
model/source finding, not a genuine fork reproduction. See
`receipts/efficient-exit-cash-reachability.md`. No clock reversal, fake approval or protocol state
was introduced to conceal that gap.

Another small-vault issue is inventory liquidity. Reusing part of the seven loose Shapes for
ordinary backing may merit a separate measured proposal. For scale only, redeeming four loose
Shapes returns 0.04 ETH of existing principal; the existing liquidation quote is 335,000 gas
plus four work fees, or 0.000147/0.0002475 ETH at 0.2/0.5 gwei before any listing call. The
current ordinary liquidation permission does not authorize that new rebalancing strategy.
No such policy or capital-source change is implemented here, and it would not remove the
recurring global expense. Increasing allowance cannot substitute for this cash-flow decision.

## Things that don't make sense

- Global journal expense follows unrelated FWA activity while small-vault income follows its own capital.
- Lower EVM execution cost leaves holder expense unchanged until truthful compensation is recalibrated.
- Lowering quotes to fit a budget could strand a required job; a profitable last job cannot finance an unprofitable preceding keeper call.
- Authentic successful foreign receipt coverage is blocked by current local setup/admission, not solved by more refund samples.
- A partial checkpoint can protect the cash that a later reconciliation would need for compensation; holder rescue may remain necessary despite a full budget.
- The inherited model uses a 10^12-second settlement surrogate where deployed FWA uses 3,600 seconds. Its hypothetical returns and exit counts cannot establish live economics.
- Passing accounting checks, current cash, spending permission and acceptable holder returns are four different claims.
