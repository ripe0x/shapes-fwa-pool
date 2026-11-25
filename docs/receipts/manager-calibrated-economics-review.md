# Independent corrected manager economic-output review

**957/960 exits qualify; all 480 candidate-backing cases qualify.** This is the corrected local evaluation candidate, source revision `5701f84`, with the three manager quote changes and profile `3a1aa827...`. It is separate from the preserved 960-path baseline and is not production economic approval.

The reviewer read financial rows only after the completed summary existed. Read-only artifact assertions recomputed scenario coverage, hashes, integer partitions, signed caps, activity and grouped means. No model, test, fork, ingestion, public RPC, transaction or service was run by this reviewer. No execution input was changed.

## Exact evidence

| Artifact | SHA-256 |
|---|---|
| [Frozen manifest](../../sim/out/manager-calibrated-assessment/manifest.json) | `650176c293d951d85966667b8734b57ef0ca8c0a145ccdb6384b3f92da2f28e1` |
| [Integer-wei paths](../../sim/out/manager-calibrated-assessment/paths.jsonl) | `67431bfa1ef671cfe03f1c5d826800987392b5c15f585c8033bbf75fde27d81d` |
| [Completed summary](../../sim/out/manager-calibrated-assessment/summary.json) | `f188a421c92f6823215ef420bac551b5a1b578bc7e35fedaa95e0ce804bdee11` |
| Current manager values | `24f8c18184fde67f007aaa3c94d8d0fc693e9879893f8aab0c59eb6054b07288` |
| Corrected gas profile | `3a1aa82707e1ef9e6116ad32b7bcdfb5ac6ae44c801a3b383cb3c169a3229137` |
| Corrected raw receipt packet | `2b8e6771aa2259c7a6782b109fa19a8ea15c325aba44be91c0366e18bc845099` |
| SQLite archive | `9f05929e7d333f3b43d5c85ef3e8b03f0498523c1a7ab60a0267c87749cd019c` |
| `sim/forward.py` | `dde8e57fa8090cf51c8aba741f7e3e19691dc98c5191c534ebf54167cd7a13d1` |
| `sim/manager_operating_assessment.py` | `a386e262decbc74b6a2b14861df4e2dfa578e88b843881afbc6630c5856bb3d6` |

All manifest source, contract, receipt, reconciliation, observation, archive and gas-profile hashes match current files. The [independent calibration review](manager-calibrated-review.md), commit `501d6a1`, binds exact executed source and the 43 new receipt observations. The baseline remains under [its own review](manager-operating-baseline-review.md), original values hash `f216770efacfe587770fe3d3821d0f2489d40c4e4f7758a051be77195ac0c026`, original profile `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`, and original output hashes. Baseline financial rows were not overwritten.

The fixed design has 24 configurations, two archive windows, eight seeds per window, two buyer regimes, 768 recorded-month rows and 96 rows each for quiet and burst. All 960 expected scenario keys occur exactly once. Every corrected key matches its baseline key and request-tape hash. Other manager values are identical; only list base 280,000 → 380,000, selected 180,000 → 225,000 and synced 120,000 → 285,000 change. The corrected receipt profile also changes, so the comparison includes recalibration as well as quote changes. Runtime was **1236.431 seconds**, not a sampled stopping rule.

## Cash and completion scorecard

| Check | Result |
|---|---|
| Funding | Exactly 0.5 ETH once per account; no topups |
| Complete and qualified exits | **957 of 960** |
| Candidate 0.21 backing exits | **480 / 480**, zero ending owned assets |
| Actual raw cash partitions | Exact integer-wei equality |
| Unpaid executed ordinary calls / negative keeper proxy margins | **0 / 0** |
| Signed exit-cap breaches | **0** |
| Paths stopped before the next call exceeds the cap | **3** |
| Largest cumulative signed exit reservation | **0.00864614855 ETH** |
| Largest billed owner-exit gas proxy | **0.0028422495 ETH** |
| Exit cap | 0.01 ETH; clone creation excluded |

Account funding plus collected fees equals withdrawal plus keeper compensation, paid primary mint fees, acquisition/backing losses, settlement fees and retained physical assets. External unclaimed credit is tracked separately. Owner wallet gas equals billed exit gas plus exactly one creation charge. Creation is excluded from the exit cap but included in owner net. Keeper compensation equals both the routine/essential split and the sum of operation payments. Keeper gas is subtracted only from keeper compensation, not charged to the owner twice. Creator accrual remains gross and is divisible by three paid primary mint fees.

All executed ordinary calls have compensation. All receipt-history counts match ordinary call counts, excluding owner recovery. Routine paid amounts stay within cumulative permission bounds; no aggregate budget breach or negative keeper proxy net occurs. Forty-seven paths have denied routine-funding attempts; this is not unpaid executed work. Compact rows do not reconstruct every intermediate budget checkpoint; the source-bound focused validation and reconciliation remain separate evidence.

All 144 grouped cells and 72 paired backing contrasts were recomputed. Three primary owner-return means and their three paired contrasts are correctly **suppressed** because one planned path in each group is incomplete. Complete-group means agree with exact rational recomputation within IEEE-754 conversion/mean rounding. Across all monetary summary fields the largest such difference is 272.625 wei, within its input-rounding bound; every raw money partition is exact. No row or model was changed to resolve the review.

Foreign journal entries remain in 691 paths, at most 45,782. An empty personal manager need not pay to clear unrelated protocol work. Manager positions, pending receipts and recovery packs end at zero in every path; retained idle packs, cash and external credit in the three incomplete cases are explicitly below.

## Three incomplete hypothetical exits

All three share earlier window `w1792929275`, seed 200005, forced-responsive-bid stress, Reuse, hypothetical 0.03 backing and 0.5 gwei. One occurs at each fee. The current candidate rejects this backing sensitivity; the 0.21-backing candidate cases are complete.

| Fee per Shape ETH | Idle packs | Account cash ETH | External fee credit ETH | Total retained assets ETH | Withdrawn ETH | Signed reservation ETH |
|---|---:|---:|---:|---:|---:|---:|
| .00025 | 11 | .591601186828380758 | .492449594834606491 | 1.414050781662987249 | 0 | .0077157157 |
| .0005 | 12 | .577561765579170673 | .494965074760599249 | 1.432526840339769922 | 0 | .00781193455 |
| .001 | 10 | .501437697491474368 | .463913783026519217 | 1.265351480517993585 | 0 | .00665425125 |

Physical retained assets include cash plus pack principal of 0.33/0.36/0.30 ETH respectively. They are not realized payouts or profits. The next whole liquidation's signed reservation exceeds the remaining permission even though the existing reservation is below 0.01 ETH. Billed gas is lower still; it must not replace the signed bound. More permission does not create cash, and account wealth does not authorize spending the owner's wallet. These rows report no final owner net, and their full-period group means are not computed from the 15 survivors.

## Current-fee comparisons

Entries are mean modeled owner net ETH including creation and exit wallet gas, at 0.0005 ETH per primary Shape. Recorded-month means combine 16 paths; quiet/burst means use two tapes per buyer regime. The last two numeric columns use an isolated, nondeployable backing hypothesis. “Suppressed” retains the incomplete path.

| Demand / buyer | Mode | .21 backing, .2 gwei | .21 backing, .5 gwei | .03 hypothetical, .2 gwei | .03 hypothetical, .5 gwei |
|---|---|---:|---:|---:|---:|
| recorded-month / observed-choices | Fresh | 0.15195789 | 0.14996184 | -0.07073698 | -0.11791495 |
| recorded-month / observed-choices | Reuse | 0.26713278 | 0.26177013 | 0.03233574 | 0.00262383 |
| recorded-month / forced-responsive-bid-stress | Fresh | 0.11234809 | 0.10935332 | -0.10012197 | -0.10528545 |
| recorded-month / forced-responsive-bid-stress | Reuse | 0.07561055 | 0.08420571 | 0.08539690 | suppressed |
| quiet / both | Fresh | -0.00223214 | -0.00327035 | -0.01392614 | -0.01864535 |
| quiet / both | Reuse | -0.00416914 | -0.00580285 | -0.01586314 | -0.01864535 |
| early-burst-then-zero / observed-choices | Fresh | 0.03581314 | 0.03391094 | -0.07264487 | -0.15495902 |
| early-burst-then-zero / observed-choices | Reuse | -0.03660245 | -0.03928541 | -0.14162220 | -0.15995114 |
| early-burst-then-zero / forced-responsive-bid-stress | Fresh | -0.04445681 | -0.04683077 | -0.18003757 | -0.21555458 |
| early-burst-then-zero / forced-responsive-bid-stress | Reuse | -0.13519783 | -0.13761529 | -0.12253627 | -0.16590869 |

The latest-window eight-path scorecard is distinct from these two-window means. At .21 backing/current fee, Fresh observed-choice means are **.1389378166 / .1373667337 ETH** at .2/.5 gwei, with two losing paths out of eight at each price. Worst losses are **.4265169133 / .4293491212 ETH**, approximately 85.30%/85.87% of initial funding. Fresh forced-return means are .1013224994/.0987346040 ETH. Latest Reuse observed means are .4922409811/.4854933297 ETH, and forced-return means .2309037406/.2278223452 ETH. Those averages do not remove losing paths, funding constraints or exposure differences.

The .21 Fresh matched two-window mean change from baseline is −.000070875 ETH at .2 observed and +.0476317220780096 ETH at .5 observed; forced-return changes are −.0000945 and +.04338196294272039 ETH. This is an exact pairing of the same 16 row keys, not independent experiments or a causal forecast.

One absolute corrected path is latest-window seed 200008, Fresh/.21/current fee/.5 gwei/observed choices. Funding .5 plus collected fees **.336893405915182160 ETH** equals withdrawal **.621393405915182160 ETH** plus .21 acquisition loss, .003 creator fees and .0025 keeper compensation. Wallet gas is .0008553465, giving owner net **.120538059415182160 ETH**. Keeper gas is .002404958 and keeper net .000095042. It has one build, one renewal, one selection and zero keeper-loss wait observations; the same baseline path had zero renewals and 35,117 such observations. No keeper gas is deducted twice.

## Executed modeled activity and waits

These totals are scenario alternatives, not network transaction totals. Each recorded-month row contains 64 paths across both prices and buyer regimes; quiet/burst rows contain eight. Counts are executed modeled calls, not attempts or pack counts.

| Demand | Backing / mode | Paths | Corrected builds / renewals / relists | Baseline builds / renewals / relists | Corrected selections | Paths with keeper-loss / renewal-cash waits |
|---|---|---:|---|---|---:|---|
| recorded-month | .21 / Fresh | 64 | 76 / 92 / 0 | 74 / 49 / 0 | 126 | 34 / 0 |
| recorded-month | .21 / Reuse | 64 | 104 / 0 / 90 | 84 / 0 / 23 | 225 | 0 / 0 |
| recorded-month | .03 hypothetical / Fresh | 64 | 177 / 3753 / 0 | 176 / 3639 / 0 | 4952 | 64 / 64 |
| recorded-month | .03 hypothetical / Reuse | 64 | 297 / 0 / 2992 | 291 / 0 / 1876 | 5037 | 54 / 0 |
| quiet | .21 / Fresh | 8 | 8 / 0 / 0 | 8 / 0 / 0 | 0 | 0 / 0 |
| quiet | .21 / Reuse | 8 | 8 / 0 / 0 | 8 / 0 / 0 | 0 | 0 / 0 |
| quiet | .03 hypothetical / Fresh | 8 | 16 / 0 / 0 | 16 / 0 / 0 | 0 | 0 / 0 |
| quiet | .03 hypothetical / Reuse | 8 | 16 / 0 / 0 | 16 / 0 / 0 | 0 | 0 / 0 |
| early-burst-then-zero | .21 / Fresh | 8 | 8 / 10 / 0 | 9 / 5 / 0 | 12 | 2 / 0 |
| early-burst-then-zero | .21 / Reuse | 8 | 8 / 0 / 10 | 8 / 0 / 0 | 20 | 0 / 0 |
| early-burst-then-zero | .03 hypothetical / Fresh | 8 | 16 / 104 / 0 | 16 / 104 / 0 | 205 | 8 / 8 |
| early-burst-then-zero | .03 hypothetical / Reuse | 8 | 18 / 0 / 69 | 19 / 0 / 31 | 173 | 1 / 0 |

In latest-window .21 Fresh/.5/current-fee paths, paid renewals increase from zero in both baseline buyer regimes to five observed-choice and eleven forced-return renewals. Current .21 Reuse has no modeled keeper-loss waits in either normal or burst groups. Current .21 Fresh recorded-month waits fall from 49 to 34 paths, but remain. Poll-observation counters measure neither paid failures nor full stall duration.

All twelve actual corrected one-work cases pass production cold acceptance at .2/.5 gwei. Remaining modeled `KEEPER_LOSS` observations use generic conservative work/receipt envelopes and learned proxy ratios; they are **not evidence that those measured production calls fail**. Larger operating sync and multi-pack fresh renewal remain measurement gaps. Activity improvement also does not establish that every path continuously operates or that all desired renewal cash is available.

## Review of the lead's final economic report

The latest eight-path scorecard, 16-path current-fee comparisons, incomplete-group suppression, fee sensitivity, mean cash partition, creator/keeper amounts, quiet and worst forced-burst figures agree with the raw rows. Corrected per-return Reuse savings are .001726 ETH at .2 gwei and .002005 ETH at .5 gwei, including avoided .0015 creator fees. Reuse also releases the fresh-renewal float and changes exposure; its period results cannot be attributed only to avoiding mint fees. Its larger worst burst losses remain visible.

The recommendation retains the measured quote correction and the 0.03 ETH recipe while declining to recommend a live launch from these conditional means. That is consistent with the evidence. It creates no new owner return hurdle, no fee reduction, no production approval and no inference about the shared vault's separate depositor objective. The [final narrative](manager-operating-economics.md) and machine-readable companion retain exact input hashes and the 957/960 qualification.

The reviewed narrative SHA-256 is `28dd94c872ed0911cef10949ea38c58db1ea4397cccdf12a9fae472d74329b0b`; the reviewed `manager-operating-economics.json` SHA-256 is `c0dbfd17fadd68142d10d0f252f0b9a7cc3f5a9de8384fb2ad3732e4eafa6e0e`. All four metadata input hashes, completion counts, cap maximum and unapproved production flags match the completed artifacts. A narrow follow-up confirmed that the sole narrative change from the previously reviewed `aeea89031eec17f10f71105ec43c460aa0f880805bb47532003aaa7063cf941c` clarifies empirical response sampling: request-keyed draws select the recorded first-response cohort rather than the buyer attached to the original request. This matches the executed assessment source. Reversing exactly that prose substitution reproduces the prior narrative hash; all other prose, numbers and the JSON are unchanged. No execution evidence was repeated.

Archive/input hashes match the preserved baseline. The same two completion cohorts contain 47,559 and 14,946 request/completion pairs. Ingestion reaches the pinned block; the 516-second last-event gap is not missing fetched coverage. Completion-time selection is not arbitrary live-queue reconstruction, and future purchaser responses remain right-censored. No new archive ingestion was needed for this review.

## Limits and outcome

These are descriptive conditional rows under fixed foreign demand, recorded weights/outcomes, sampled censored buyer behavior, request-keyed allocation and repeated exit tapes. Foreign participants do not react to the added manager. The experiment does not exactly replay future VRF, gas, buyer or service behavior. Receipt-history acceptance assumes a fresh keeper per path and proxy receipts; failed inclusion, replacement/minPay estimate variation and other-account history are absent.

The 0.005 ETH reserve is below the conservative .0054805 maximum-batch need and remains a visible limitation. Larger sync, multi-pack renewal, signer transport, live inclusion and live service behavior are outside the completed proof. Gross creator accrual omits global deployment/hosting expenses. Owner cap stops and retained assets are honest outcomes rather than removed data.

The corrected artifacts are internally reconciled and reportable with these qualifications. This review establishes no APR, future return probability, production economic acceptance or launch recommendation. The shared vault remains undeployed. No public transaction, merge, acceptance signature, production fee change or live cutover follows.

Things that don't make sense: treating positive means as downside protection; publishing returns for assets still held behind a spending limit; calling proxy refusal observations actual failed production jobs; or charging keeper gas to the owner twice.
