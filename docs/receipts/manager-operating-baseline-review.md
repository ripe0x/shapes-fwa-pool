# Independent baseline manager economic-output review

2026-11-25. **BASELINE ONLY: 960/960 paths and exits pass the financial artifact checks.**
This record concerns source `2b9b1658a36c3b0f837f0e83b2728106d8062764` and the original gas profile
`e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`.
It is not the recalibrated candidate or production acceptance.
The subsequent local quote-calibration repair and its new assessment require separate evidence.

The reviewer waited for the completed `summary.json` before reading any financial rows.
No model, fork, test suite, ingestion or public RPC was run. Read-only Python 3.11.8 artifact
assertions and SQLite queries checked the completed outputs. No execution input was changed.
The lead owns the separate economic narrative and any subsequent calibration work.

## Evidence identity

| Artifact | SHA256 |
| --- | --- |
| [Frozen manifest](../../sim/out/manager-operating-assessment/manifest.json) | `8ba3482f4146b9d32c276cb8ff13c9d1cf2b9e5a4f6734c099bed5ac13093e34` |
| [All integer-wei paths](../../sim/out/manager-operating-assessment/paths.jsonl) | `de382ba22fc69bf2e7493faffef039cc8fec6052ecaa9ca724ed992fff2212b3` |
| [Completed summary](../../sim/out/manager-operating-assessment/summary.json) | `e595103ee5f54eba54b50dbdf3fa622b931ba80bf62e03f1344ea9165e67aa4e` |
| `sim/data/fwa.sqlite` | `9f05929e7d333f3b43d5c85ef3e8b03f0498523c1a7ab60a0267c87749cd019c` |
| Baseline `manager-operating-cost-calibration.json`, calibration commit `72a9586` | `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af` |
| Baseline raw Osaka operating receipts | `eb1ff1c81cfe085e46515bbaf0c9d474284cd092271654efb4652fc5b63b5beb` |

The manifest retains every exact source, contract, receipt, archive, gas-curve and live-observation
binding. These hashes matched the files when checked, before the subsequent calibration repair.
Later working values or profiles do not replace this baseline evidence. The [source/calibration
review](manager-operating-model-review.md), as recorded at commit
`28044e65f7157aaaffd93a24e58a9beaec817cb6`, identifies the corresponding model and native-import scope.

The fixed design has 24 configurations, two archived windows, eight paired allocation seeds per
window, two buyer regimes and three demand regimes: 768 recorded-month rows and 96 rows each for
quiet and burst. All 960 planned scenario keys occur exactly once; none is omitted or duplicated.
The run took **1739.158 seconds**. The count was agent-selected, with no owner-approved manager
return/risk hurdle or future-market precision claim.

## Cash and completion scorecard

| Check | Result |
| --- | --- |
| Initial account funding | Exactly 0.5 ETH in every path; no topup |
| Complete and qualified exits | **960 / 960** |
| Ending cash, physical assets, inventory, receipts and external fee rights | **Zero in every path** |
| Account, owner and keeper partitions | Exact integer-wei equality |
| Unpaid ordinary calls / negative keeper proxy margins | **0 / 0** |
| Cap breaches / paths stopped by the exit cap | **0 / 0** |
| Largest cumulative signed exit reservation | **0.00941895455 ETH** |
| Largest billed owner-exit gas proxy | **0.0029747495 ETH** |
| Evaluation exit cap | 0.01 ETH; clone creation excluded |

Each owner's wallet-gas total equals exit spending plus exactly one clone-creation gas charge.
Creation is included in owner net even though it is outside the exit cap. Keeper compensation
equals both its routine/essential partition and the sum of operation payments; keeper gas is
subtracted from keeper compensation only. Receipt-history call counts match accepted ordinary
operation counts, excluding owner recovery. Creator accrual is divisible by three paid primary
mints at the selected fee and is never added to manager-owner profit.

All 144 output groups and 72 paired backing comparisons were independently recomputed from the
integer rows. All pairs retain the same keyed request tape. Every group is complete here, so no
mean-suppression branch is exercised by these data; the source/test guard still withholds a primary
owner-return mean if a planned path or pair is incomplete. Printed floating-point means match exact
rational recomputation within IEEE-754 input-conversion rounding, at most eight wei in the affected
primary/paired values. Raw cash partitions remain exact to the wei. An initially overstrict
floating-summary comparison was corrected to that numerical bound; no monetary row was changed
and no simulation was repeated.

One absolute modeled path illustrates the partition without rounded means: latest window, seed
200008, observed choices, Fresh, 0.21 ETH backing, current 0.0005 ETH mint fee and 0.5 gwei.

| Bucket | ETH |
| --- | ---: |
| Account funding | 0.500000000000000000 |
| FWA fees collected | 0.226036775378364031 |
| Backing lost | 0.210000000000000000 |
| Settlement fees | 0 |
| Paid primary mint-fee accrual | 0.001500000000000000 |
| Keeper compensation | 0.000977500000000000 |
| Owner withdrawal | 0.513559275378364031 |
| Owner wallet-gas proxy, including creation | 0.000792846500000000 |
| **Owner net** | **0.012766428878364031** |
| Keeper gas proxy / net | 0.000962458 / 0.000015042 |

Funding plus collected fees equals withdrawal plus acquisition loss, mint fees and keeper pay.
Keeper gas is not debited from owner net a second time. This path has one build, one selection,
**zero paid renewals** and 35,117 keeper-loss wait observations. Its positive cash outcome does
not demonstrate a continuously renewed strategy.

## Current-fee comparisons

All entries below are **mean modeled owner net ETH**, including wallet gas, at the observed
0.0005 ETH fee. Recorded-month cells have 16 paths, quiet/burst cells two paths per buyer regime.
Every displayed cell completes. Quiet results are identical under both buyer regimes.
The 0.03 ETH column is the isolated admission hypothesis, which the actual current manager rejects.

| Demand / buyer | Mode | 0.21 backing, 0.2 gwei | 0.21 backing, 0.5 gwei | 0.03 hypothetical, 0.2 gwei | 0.03 hypothetical, 0.5 gwei |
| --- | --- | ---: | ---: | ---: | ---: |
| Recorded month / Observed choices | Fresh | 0.15202877 | 0.10233012 | -0.10623690 | -0.11186922 |
| Recorded month / Observed choices | Reuse | 0.25564738 | 0.17036615 | 0.06627643 | 0.02347780 |
| Recorded month / Forced return | Fresh | 0.11244259 | 0.06597136 | -0.07631138 | -0.07345384 |
| Recorded month / Forced return | Reuse | 0.09581586 | 0.04576300 | 0.11028394 | 0.00193447 |
| Quiet / Both | Fresh | -0.00223214 | -0.00327035 | -0.01392614 | -0.01864535 |
| Quiet / Both | Reuse | -0.00416914 | -0.00580285 | -0.01586314 | -0.01864535 |
| Burst then zero / Observed choices | Fresh | 0.03587614 | -0.01554917 | -0.14106404 | -0.16354382 |
| Burst then zero / Observed choices | Reuse | -0.11290799 | -0.11449770 | -0.12651101 | -0.09478873 |
| Burst then zero / Forced return | Fresh | -0.04439381 | -0.11292905 | -0.14269104 | -0.16629924 |
| Burst then zero / Forced return | Reuse | -0.20187649 | -0.20349395 | -0.11379772 | -0.16096980 |

The positive high-backing recorded-month means coexist with quiet losses and adverse burst
outcomes. Fresh at hypothetical standard backing loses on average in every current-fee
recorded-month comparison. Some hypothetical Reuse means are positive; they do not override
admission, establish risk acceptability or justify a production recommendation.

Reuse is not a fee-only comparison: it releases the fresh-renewal float and initially exposes
more capital. Its worse high-backing burst results prevent treating it as a blanket fix. The
separate buyer stress forces eventual responders to return within 3480 seconds; it is not a
guaranteed worst case for every backing, and archive-unresolved responses remain censored.

## Activity and waits

These totals cover matched **scenario alternatives**, not real network transaction totals.
For each strategy, a recorded-month row combines 64 paths across both gas prices and both
buyer regimes; quiet/burst rows combine eight. The columns count executed modeled calls and
selections, so inactivity cannot be mistaken for a fully operating investment strategy.

| Demand | Backing / mode | Paths | Builds / renewals / relists | Selections | Maximum positions | Paths with keeper-loss waits | Paths with renewal-cash waits |
| --- | --- | ---: | --- | ---: | ---: | ---: | ---: |
| Recorded month | 0.21 / Fresh | 64 | 74 / 49 / 0 | 102 | 5 | 49 | 1 |
| Recorded month | 0.21 / Reuse | 64 | 84 / 0 / 23 | 169 | 7 | 48 | 0 |
| Recorded month | 0.03 hypothetical / Fresh | 64 | 176 / 3639 / 0 | 4865 | 15 | 64 | 64 |
| Recorded month | 0.03 hypothetical / Reuse | 64 | 291 / 0 / 1876 | 4644 | 22 | 64 | 0 |
| Quiet | 0.21 / Fresh | 8 | 8 / 0 / 0 | 0 | 1 | 0 | 0 |
| Quiet | 0.21 / Reuse | 8 | 8 / 0 / 0 | 0 | 2 | 0 | 0 |
| Quiet | 0.03 hypothetical / Fresh | 8 | 16 / 0 / 0 | 0 | 7 | 0 | 0 |
| Quiet | 0.03 hypothetical / Reuse | 8 | 16 / 0 / 0 | 0 | 8 | 0 | 0 |
| Burst then zero | 0.21 / Fresh | 8 | 9 / 5 / 0 | 10 | 2 | 5 | 0 |
| Burst then zero | 0.21 / Reuse | 8 | 8 / 0 / 0 | 16 | 2 | 7 | 0 |
| Burst then zero | 0.03 hypothetical / Fresh | 8 | 16 / 104 / 0 | 205 | 7 | 8 | 8 |
| Burst then zero | 0.03 hypothetical / Reuse | 8 | 19 / 0 / 31 | 147 | 8 | 8 | 0 |

For baseline 0.21 ETH Fresh at 0.5 gwei in the recorded-month regime, all 32 current-fee paths
have keeper-economics waits. The latest-window 16 paths across the two buyer regimes execute
no paid renewal. Quiet paths have no such waits, so the refusal statement must not be generalized
to every demand regime. Wait counters are poll observations, not failed paid transactions or
measured stall durations. Under this baseline profile, marked activity and successful owner exit
do not establish dependable small-work keeper acceptance.

The largest signed exit reservation leaves only 0.00058104545 ETH below the evaluation cap.
All retained physical and external assets are zero in this cohort; that does not guarantee a
different path, gas market, dependency state or larger workload completes within the same cap.

## Archive and scope qualification

The two tape windows are 2026-09-25 to 2026-10-25 and 2026-10-25 to 2026-11-24, with boundaries
at 11:54:35 UTC. Their monthly-event hashes are:

- `7f909f02bb0eedcad92492707711e2e68e4f6080b6d5c340b10fa77716b317ad`
- `16c8618f954e6cba72bb7fd10542e3105aab112a2aeeae227f1031822a6ecc6d`

The corresponding burst hashes are `6d6a547743a0f084b1ef7c8524ace1c52355838b07580c550759396e69b9ab03` and
`c1f35cd23e83b4e95230eec379ad407f43f2c79b281edc01dd54f3500852fb7e`. All are also bound in the manifest.

Read-only SQLite queries find 47,559 and 14,946 originated request IDs and the same respective
numbers of completed-request pairs. Neither window has an opening carry-in, a recorded
originated request without a recorded completion by its cutoff, or an event exactly on the
shared boundary. The tape constructor nevertheless selects by completion timestamp; this is
not a claim that it reconstructs an arbitrary live queue.

The last stored event is timestamp 1795520759, 516 seconds before the final boundary
1795521275. The per-contract ingestion cursors for FWA and the other archived contracts reach
block 26,484,850, exactly the pinned block. Thus **the 8m36s last-event gap is not evidence of a
missing fetched tail**. The response-cohort diagnostic uses last-event time as its conservative
follow-up horizon. Future purchaser responses remain right-censored; no new data was ingested.

## Review of the lead's baseline narrative

The latest-window eight-path scorecard, full two-window 16-path comparisons, cash partition,
fee sensitivities and stated losing-path counts agree with the raw rows. The worst latest
observed-choice Fresh/0.2 path loses 0.4263909132751079 ETH, approximately 85.28% of the initial
account funding; that is a loss severity, not an estimated future probability.

The baseline cold-keeper quote gaps are supported by the actual receipt/estimate comparison.
The arithmetic additional allowances 30,916 selected gas, 136,429 synced gas and 64,424 list-base
gas are recorded-call lower bounds without headroom, not a tested production calibration.
Measured single-return Reuse expense savings are 0.001746 ETH at 0.2 gwei and 0.002055 ETH
at 0.5 gwei, including 0.0015 ETH of avoided creator fees. These local savings do not establish
a portfolio preference. Fixing numerical underquotes is an engineering follow-up, not a new
owner-approved financial outcome or a reason to mislabel the baseline as a final candidate.

No numerical blocker was found in the lead's baseline economic narrative. The scope qualifications
are explicit: keeper-refusal statements concern the relevant recorded-month high-backing cohort,
and archive last-event time must be distinguished from ingestion coverage. These qualifications
do not change financial inputs or results. Subsequent repaired-calibration results must retain
their own values, profile and output hashes.

## Limits and outcome

The cohort has no incomplete exits or retained assets, but it remains a conditional, small
descriptive experiment. Foreign demand, weights and service outcomes do not react to the added
manager; buyer response behavior is sampled from censored history. The month repeats during the
exit tail. Gas and receipt history are calibrated proxies. Larger paid sync, multi-pack fresh
renewal and work beyond measured sizes remain unmeasured. Global deployment/hosting costs are
outside per-clone owner returns; creator accrual is gross.

The reviewer finds the **baseline artifacts internally reconciled and honestly reportable with
these conditions**. No APR, future return distribution, production economic acceptance or launch
recommendation follows. The shared vault remains undeployed, and this review authorizes no
public transaction, merge, signature or live keeper/application cutover.

Things that don't make sense: equating positive averages with downside protection; calling a
passively collecting, keeper-stalled path continuously renewed; treating the last log timestamp
as an ingestion failure; or presenting this superseded baseline as the repaired candidate.
