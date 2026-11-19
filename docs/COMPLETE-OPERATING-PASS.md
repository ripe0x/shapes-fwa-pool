> **Current release instructions: [docs/release/RUNBOOK.md](release/RUNBOOK.md)** (2026-11-19). This document is history for the candidate it names; where it gives current instructions, the runbook replaces them.

# Complete operating pass

2026-11-18. This pass resolves the remaining implementation choices together under the owner's instruction to finish the system autonomously. PR 2 remains one vault, one capital pool and one authoritative incremental book. There is no total position ceiling, factory, shared exposure contract or new mint strategy.

The operating expense source is the vault's unencumbered cash. Creator mint revenue stays separate. Every primary shapes mint still pays the actual mint fee, and the existing split and pack recipe remains intact.

## Enforced collection economics

Standalone `harvest(ids, minPay)` is now caller funded. Its positive `minPay` reverts; zero permits manual collection and useful holder liquidity work. Permissionless callers cannot repeatedly extract a harvest reward from gross fees that largely replace transferred backing.

Fee collection accompanies verified useful `sync` work:

1. Process the bounded journal job and supplied terminal positions first, including actual returned cash.
2. Sweep credited fees when their value covers the incremental quote within the existing fee share restraint and routine spending permission.
3. If protected free cash still cannot fund the completed job, claim the first distinct active fee prefix that funds the job and its collection cost.
4. Stop at that prefix. Extra IDs, duplicates and unrelated IDs earn no extra compensation. A failed share, permission or distribution test does not justify collecting more IDs to manufacture eligibility.
5. Apply the final payment envelope to a distribution tail's eligibility proof. Collection cannot consume the gain that made the tail payable.

Optional foreign tails, empty calls and unexposed cursor advances cannot create compensated collection. Checkpoint continues to sweep credited fees. Full exits collect active fees through unlisting, avoiding a redundant standalone transaction beforehand. A small partial redemption can still use a cheaper unpaid claim.

The public sync ABI is unchanged. Global processing remains at most 128 records per call. Own selections, supplied position IDs and pruned allocation heads each retain their independent bounds of 16. A supplied ID list cannot shorten the global journal to create more paid jobs.

## Keeper and model

The keeper first preflights the ordinary sync. If cash may be short, it offers bounded active fee prefixes and uses the shortest profitable exact call. Declining one prefix does not suppress the next. If terminal IDs fill the argument, alternatives reserve space for funding candidates while still completing verified work. The keeper sends one transaction, checks its receipt and replans.

This removes a duplicate offchain eligibility formula. The contract determines actual work, cash receipts and payable fees. All alternatives use the already bounded event index candidates; there is no portfolio scan.

The timed simulation now uses the same bounded candidate projection as the real event index, including independent terminal classes, debt ordering and rotating returned claims. A 700 position regression checks that projection against the index's SQL results. All cash, permission, creator fees, caller expenses and completed holder claims remain separate.

## Compensation decisions

| Component | Previous quoted gas | Final quoted gas | Reason |
| --- | ---: | ---: | --- |
| Ordinary sync base | 85,000 | 85,000 | Preserve the measured job structure and splitting economics |
| Global journal record | 22,000 | 22,000 | Preserve the calibrated record quote |
| Required foreign tail base | 110,000 | 120,000 | A genuine successful singleton billed about 131,700 including the record; the old total of 132,000 left almost no room |
| Own selection | 160,000 | 180,000 | The measured own selection without a useful credit sweep exceeded its old envelope |
| Credit withdrawal within eligible sync | None | 40,000 | Measured incremental work was 19,517 gas |
| Active collection within eligible sync | None | 40,000 plus 80,000 per actual claim | Measured first claim increment was 80,272 gas |
| Additional shape beyond the reference three | 35,000 | 100,000 | The four shape leftover branch underpaid at 0.5 gwei; the new slope covers the current signed receipt in the gas component |

The three shape pack, paid mint, listing and checkpoint quotes remain unchanged. The extra shape quote is deliberately conservative for larger packs. At the older historical fork, the four shape leftover sample still requires the configured work fee for coverage; this is not a universal guarantee for every allowed owner parameter combination.

**O2 remains 1,919,655 quoted gas per position against the original 1,750,000 target.** Its work fees are excluded from that metric. The measured small construction and listing paths do not support cutting those quotes enough to satisfy the target reliably. The difference is 169,655 quoted gas, or about 0.0000848275 ETH per position at 0.5 gwei. The original target is retained as a failure, with no invented pass.

O6 remains 0.0002 ETH at the routine gas ceiling. The final source fits the deployment limit: PackVault 24,136 bytes, VaultLib 24,304 bytes and KeeperPolicyV1 216 bytes.

## Cash and spending permission

Spending permission must replenish fast enough for actual operation. A larger initial bucket can hide a recurring deficit for a short test. The mainnet stress case spent 0.466152 ETH on routine work over 30 operating days. That exceeds the former 0.01 ETH per day hard maximum on an ongoing basis even though the vault had enough actual cash.

The routine refill hard ceiling is now 0.02 ETH per day. The capacity hard ceiling and every other hard cap remain unchanged. Tests verify the new limit, rejection above it, capped accrual, no instant permission refill when settings change and no creation of actual ETH.

The chosen mainnet setting keeps its 0.1 ETH capacity and uses 0.02 ETH per day refill. The 90 day high activity test preserves permission near the full bucket at days 30, 60 and 90, completes its holder claim and pays every routine job from actual vault cash. The canary keeps its 0.03 ETH capacity and uses 0.01 ETH per day refill; its tested high activity cases also complete without permission stalls. No recurring creator subsidy or minimum TVL is assumed.

These higher permissions enlarge the amount of real vault cash that authorized maintenance can spend over time. They do not fund that cash. A small vault still bears the cost of the shared FWA journal and can have poor holder economics even with sufficient permission.

## Complete operating and exit results

The applied settings below use the authenticated current pool context, 439.7 successful acquisitions per day, the archived refund ratio, timely purchaser responses and seed 8. Amounts are ETH. Holder net includes the stated external caller gas proxies and is reported after the modeled claim completes.

| Depositor principal | Operating period | Total gas price | Routine keeper expense | Claimed holder net | Creator mint fees | Routine funding and final exit |
| ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 6.8 | 30 days | 0.5 gwei | 0.466152 | +1.176212 | 0.025 | Complete; every routine job paid |
| 6.8 | 90 days | 0.5 gwei | 1.339094 | +1.827994 | 0.025 | Complete; permission stable at each monthly check |
| 1.9601 | 30 days | 0.2 gwei | 0.120818 | +0.657555 | 0.008 | Complete; every routine job paid |
| 1.9601 | 30 days | 0.5 gwei | 0.283338 | +0.572792 | 0.007 | Complete; one necessary active fee claim |

All four cases finish with no positions or inventory. These are conditional paths, not expected returns. The 1.9601 ETH amount is depositor principal within the canary's 2 ETH cap, with seed and charges treated separately.

The matched short comparison holds the earlier recorded pool weight and conditional exemption assumption fixed. It runs two operating days plus exit time at 0.2 gwei and 609 successful acquisitions per day.

| Metric | Previous source | Final source |
| --- | ---: | ---: |
| Standalone harvest calls | 990 | 0 |
| Standalone harvest payments | 0.266081233 | 0 |
| Total routine keeper payments | 0.319476433 | 0.048699000 |
| Unpaid routine calls | 44 | 0 |
| Claimed holder net after caller costs | −0.155298663 | +0.073280518 |
| Creator mint fees | 0.027 | 0.026 |

The fee rate and recipe are preserved; mint counts can differ as cash timing and admission change. This matched path has one fewer paid primary mint. Creator revenue is counted from actual mints, never inferred from FWA turnover. The 90 day timely bid path also illustrates that cycling an existing pack does not generate another mint fee.

Five final timing cases cover timely bids, late responses, silence, direct buyer retention and zero demand. All complete and pay their routine work under the applied mainnet settings. Late and silent cases produce 0.036 ETH of mint fees, direct retention produces 0.034 ETH and timely returns produce 0.026 ETH in their two day windows. The zero demand holder result is a loss of about 0.071096 ETH.

The small 0.15 ETH scenarios also complete and fund maintenance under their tested previous permissions, but lose approximately 0.0276 to 0.0452 ETH at 0.2 to 0.5 gwei. Even their zero gas controls lose money. An early selection can leave insufficient liquid cash to relist. More spending permission and a mint fee waiver do not establish viability for that capital size. The system retains the requested absence of a minimum TVL, while reporting this limitation plainly.

Exact inputs, monthly permission marks, cash minima, complete claims and residual assets are in [the operating evidence](receipts/complete-operating-candidate.json), [timing evidence](receipts/complete-timing-regressions.json) and [economic interpretation](REVIEW-COMPLETE-OPERATING.md).

## External context

The original snapshot at block 26,425,092 had shape packs subject to FWA's oracle ceiling. The authenticated current snapshot at block 26,446,755 has the exemption enabled. Both the weight and exemption are explicit simulation inputs. The current receipt profiles use real current fork settings without modifying the oracle or counterparty balances.

The primary timed comparisons use the current aggregate foreign weight. The archived successful and refunded activity rates are explicit scenario inputs, rather than a newly ingested historical replay. The small before and after regression preserves its original conditional exemption assumption and labels it separately. Protocol setting changes are not attributed to this PR.

## Evidence and limits

The final evidence bundle contains actual submitted local transaction receipts, exact `minPay` calldata estimates, ordinary keeper profitability results, protected balance checks, source hashes and runtime identity. Receipt gas includes finalized refunds. Diagnostic isolated frame measurements are labeled separately. The foreign receipt setup is restored from authenticated fork execution; the measured transactions are mined on an owned local node. The full holder checkpoint prices all live holder shares and funds their redemption reserve in a one position fixture with a 3 ETH dead seed. The seed and one active position remain. That checkpoint receipt measures pricing and reserve funding, rather than a complete liquidation or the holder's later claim transaction.

All twelve final foreign and checkpoint receipts submit actual 80% `minPay` calls at 0.2 and 0.5 gwei. All pass ordinary keeper preflight, cover billed costs and preserve protected balances. The retained fork tests pass five cases; the optional export test passes separately for all four fixture sizes.

| Measured operation | Billed gas | Quoted gas | Actual records |
| --- | ---: | ---: | --- |
| Required singleton | 131,692 | 142,000 | One successful foreign record |
| Required small tail | 150,482 to 150,494 | 164,000 | Two successful foreign records |
| Required large tail | 2,466,724 | 2,870,000 | 125 successful foreign records |
| Full journal batch | 2,512,081 | 2,901,000 | 125 successful foreign records and three genuine deadline refunds |
| Full batch with attached fee collection | 2,621,560 | 3,021,000 | The same mixed batch, with one actual active fee claim |
| Full live holder checkpoint | 295,510 | 360,000 | All live shares priced and their redemption reserve funded |

The foreign fixture has zero flat work fee and zero markup, so its checkpoint payment at 0.5 gwei is 0.00018 ETH. The separately verified O6 scenario includes the configured work fee and pays 0.0002 ETH. The two attached collection cases reduce only local vault free cash to exercise the funding branch, preserving protected balances and genuine accrued FWA fees. They establish billed cost and eligibility in that explicit calibration; the separate timed model supplies the complete operating cash scenarios.

The ten final construction receipts cover three shape, four shape and thirty shape paths, including the four shape leftover branch that justified the quote correction. All cover billed costs and pass ordinary preflight. See [foreign receipts](receipts/complete-foreign-journal.json), [construction receipts](receipts/complete-cost-receipts.json) and [final validation](receipts/complete-final-validation.json).

The fork reconciliation replays a full cycle and a partial redemption followed by complete wind down. The Python model matches every financial bucket to the wei. Focused contract tests cover useful work eligibility, fee debts, duplicate and padded candidates, distribution thresholds, budget exhaustion, unit recipes and permission limits.

The timed results report a holder return only after the modeled claim completes. Static foreign weight, prescribed purchaser timing, one named stochastic seed and caller gas proxies make them conditional engineering scenarios. They establish behavior under those inputs, not an expected investment return or the formal trailing 30 day historical return gate. A pure 128 successful record receipt and the combined maximum of 16 own transitions with journal and collection work remain outside the submitted receipt coverage. Authentic live returned pack coverage also remains narrower than the keeper's historical payload, restart and reorg tests. The original outcome signature is not reused for this candidate. Refill rounding in the timed driver can conservatively understate permission by tiny amounts because it materializes refill at each event; the independent review records a one wei example. This does not create cash, and both fork financial reconciliations remain exact.

## Reproducing the submitted receipts

Run from the repository root with the recorded Foundry tool versions, Solidity 0.8.30 and the keeper Python dependencies installed. The historical input JSON is included. Its generator, `python3 sim/complete_foreign_fixture.py`, is optional when using those retained inputs. Generated state files and model caches are excluded from the deliverable.

```bash
for count in 1 2 125 128
do
    EXPORT_COMPLETE_FOREIGN=true COMPLETE_FOREIGN_COUNT="$count" \
    forge test \
        --match-path test/fork/CompleteForeignJournal.t.sol \
        --match-test test_exportSuccessfulForeignReceiptFixture \
        --rpc-url https://mainnet.gateway.tenderly.co \
        --fork-retries 30 \
        --fork-retry-backoff 5000 \
        --compute-units-per-second 100 \
        --out /tmp/pr2-foreign-final-out \
        --cache-path /tmp/pr2-foreign-final-cache \
        -vv
done

python3 keeper/complete_foreign_receipts.py \
    --counts 1 2 125 128 \
    --artifacts /tmp/pr2-foreign-final-out

COMPLETE_COST_PROFILE=extra-unit python3 keeper/complete_cost_receipts.py
```

Each receipt runner starts and terminates its own local node. The foreign runner uses port 8562 and the construction runner uses port 8561. Their upstream RPC access supplies fork state; measured transactions are submitted only to those owned local nodes.

PR 2 stays draft. No merge, public deployment, real funds or new owner outcome signature are included in this pass.
