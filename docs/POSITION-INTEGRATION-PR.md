# Remove the position ceiling with incremental accounting and efficient journal jobs

PackVault keeps one authoritative incremental book instead of a 300-position ceiling and portfolio scans. Paid Shapes mints, recipes, creator fees and protected holder liabilities remain. Provably unexposed history advances unpaid, preserving the 0.01 ETH seed and first-deposit pricing.

Journal jobs read up to 128 completed global records independently of 16 own transitions, 16 terminal IDs and 16 pruned heads. Callers cannot select a smaller paid slice. Small foreign tails require a genuine fresh checkpoint opportunity; distribution-only tails authenticate actual post-cost gain and liquidity. Sync uses routine upkeep during redemption; existing caller-funded unlisting/liquidation stays intact.

The durable keeper index discovers returns from actual ETH/token bid events, retains unseen selections, independently discovers expiry and replays newly relevant history on upgrade. Restock keeps immediately consumed minted IDs in memory and shares economics reads before minting.

## Current verification

- Both owner-approved local phases passed: **517/540 cumulative transactions**, **27.869594973162081536/32 simulated ETH** aggregate value, 8.3 ETH initial funding once, no topups. The amended candidate used 199 transactions and needed no repair. Entry actors/head restored; node preserved with an empty pool and automining. Normal code/gas limits.
- All **24 candidate journal cases** have positive calibration-receipt keeper net, positive exact signed-estimate headroom and accepted ordinary keeper preflight. Holder counts 1/16/32/64/128 use matched 0.2/0.5 gwei and default/maximum markup; distribution 1/32 use 0.5 gwei and both markups. Two no-gain cases return zero and the keeper declines without sending.
- The measured schedule is 22k/record, 110k holder-tail base and 80k for actual qualified distribution-proof work. Ordinary 85k and pack 325k stay unchanged. Default singleton holder/distribution bills are **122,417/202,270 gas**, versus **132,000/212,000** quotes. Full 128 bills **2,233,071** versus **2,901,000**. Protected buckets, cursor progress, actual fee/payment/native deltas and routine classification agree.
- The baseline standalone full-holder checkpoint bills **346,017 gas**, with ordinary preflight accepted at 0.2/0.5/2 gwei and protected buckets/claim checked. At 0.5 gwei its payment is **0.0002 ETH**. Its 1 ETH gain fixture is not earned income or an operating subsidy. The candidate did not repeat this fixture.
- Five focused journal/proof tests, 14 accounting tests, policy checks, both fork/Python reconciliations and two affected economic scenarios pass on the unchanged candidate code (`aa38fab`). Actual deployed runtime: **24,451/23,001 bytes**, 125/1,575 spare. Source/launcher and stored-record reviews found no actionable defect in their bounded scopes.
- Earlier lifecycle, minimum-seed, returned-index and receiver evidence remains scoped to unchanged paths. Earlier production-image startup/shared-volume replacement passed: [isolated image verification](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/44393965532).

Calibration receipts use `minPay=0`; actual signed 80% `minPay` estimates/preflight are separately recorded, not billed signed-80% receipts. Candidate has one Active position versus baseline 40, so this is not a matched-state estimate of source-only savings. Refunded records do not establish successful-foreign costs or a universal keeper-profit bound.

Evidence: [candidate summary](docs/receipts/efficient-journal-candidate-summary.json), [final evidence review](docs/receipts/efficient-final-receipt-review.md), [revision results](docs/EFFICIENT-JOURNAL-RESULTS.md), [cash and return proposal](docs/REVIEW-FUNDING-PROPOSAL.md).

## Economic scorecard

| Outcome | Requirement | Current result |
|---|---|---|
| Bootstrap |0.01 ETH seed, no rescue donation|Authentic unexposed history/first pricing passes|
| O2 build/list |≤1,750,000 quoted gas/position|**Fail: 1,919,655**; pack quote stays 325k because matched 0.5 gwei inventory cases were unavailable|
| O6 checkpoint |≤0.0002 ETH at routine ceiling|Affected pass; standalone baseline fixture bills 346,017 gas|
| Keeper compensation |Actual small/full/tail receipts and willingness|24 candidate refunded cases pass; successful-foreign and combined own maximum remain gaps|
| Recurring funding |Vault cash and permission pay all required work|Unresolved; packed global-only quote 0.207221 ETH/30 days at 0.5 gwei exceeds 0.15 steady refill before own work|
| Holder return/exit |All expenses, cleared backlog, claims|Conditional timed checks: 3/4 exits complete; only zero demand fully pays routine work; no return acceptance|

## Things that don't make sense

- **Repeated harvesting breaks once-per-cycle expense assumptions.** The timely candidate model makes 990 harvest calls, paying 0.266081233333330390 ETH against 1.819168941380021572 gross fees and 1.60792901857869 ETH backing transferred out. Harvest pay alone exceeds gross fees minus transferred backing by 0.054841310531998818 ETH, before other costs, on this conditional path.
- **More permission cannot pay every recorded call.** The timely exit includes 44 underpaid holder harvests; 32 necessarily receive zero under the existing 25% fee-share gate, confirmed by cash deltas. A bot-only scheduling improvement cannot prevent permissionless callers earning existing repeated harvest payments. [Next-step tradeoffs](docs/receipts/efficient-harvest-next-step.md).
- **Complete accounting does not establish a viable strategy.** The corrected timed model has actual 3,600-second expiry and separate blackout timing, but conditional purchaser timing, static foreign pool and historical/quote gas proxies remain. The timely completed path loses 0.155298663096359599 ETH after caller proxies; this is not an expected return. Its 609 successful/day stress input is distinct from the archived 439.7/day window.
- **Permission supplies no ETH.** Paying costs from vault cash reduces holder returns. Protected-cash/returned-pack reconciliation remains a model/source finding without an authentic timed fork reproduction. Creator mint revenue is separate and is not an assumed subsidy.
- **Receipt scope matters.** Successful-foreign and combined own-transition maxima remain unmeasured. The old 342,766 checkpoint bound double-subtracted refunds and is withdrawn. Foreign staging can still block admission; the authentic multi-allocation live returned-pack scenario remains narrower than historical-payload index/restart/reorg coverage.

**Keep this PR draft.** No allowance increase, minimum TVL, mint-fee change, recurring sponsorship, public-chain transaction, real funds, owner outcome signature or merge. Focused implementation verification is distinct from a full security audit and release acceptance.
