# Individual manager: corrected operating assessment

**Engineering and unsigned manager-only preparation are complete within the stated scope. Production economics remain unaccepted.** Three measured keeper underquotes were corrected using account-owned gas allowances, and the real keeper now accepts all twelve tested one-work cases at 0.2/0.5 gwei. The same fixed 960-case design was then rerun. Positive recorded-period averages coexist with severe losses, funding waits and three spending-limited exits in a nondeployable backing sensitivity. This is not demonstrated APR or a production viability claim.

## One-screen scorecard

Current fee **0.0005 ETH per primary Shape**, pack **0.03 ETH / three paid mints**, separate backing **0.21 ETH**, initial funding **0.5 ETH with no topups**. These are latest-window net ETH outcomes, including creation and owner exit gas. Eight fixed paths per buyer regime; percentages, when quoted elsewhere, divide net ETH by initial account funding and are not annualized.

| Renewal / total gas gwei | Observed-choice mean net ETH | Worst observed net ETH | Losing paths | Forced-return mean net ETH | Creator gross mean ETH, observed | Keeper proxy margin mean ETH, observed |
|---|---:|---:|---:|---:|---:|---:|
| Fresh / 0.2 | 0.13893782 | -0.42651691 | 2/8 | 0.10132250 | 0.00243750 | 0.00009252 |
| Fresh / 0.5 | 0.13736673 | -0.42934912 | 2/8 | 0.09873460 | 0.00243750 | 0.00007754 |
| Reuse / 0.2 | 0.49224098 | -0.02302724 | 2/8 | 0.23090374 | 0.00637500 | 0.00024376 |
| Reuse / 0.5 | 0.48549333 | -0.02634245 | 2/8 | 0.22782235 | 0.00618750 | 0.00023190 |

Creator amounts are gross primary mint-fee accrual, not profit after deployment/service costs. Keeper proxy margin excludes infrastructure and failed-inclusion costs. Neither is owner profit. No personal-manager return/risk hurdle has been owner-approved; this study neither changes nor establishes the shared vault’s separate 10% annual depositor requirement. The new shared vault remains undeployed.

**Recommendation:** retain the 0.03 ETH recipe and the measured quote correction; do not recommend a live launch from these conditional means. Fresh with one float remains the evaluated candidate, not an approved production default. Reuse is a deliberate alternative with different funding/exposure and creator mint frequency, not a blanket fix for losses. No public mint-fee reduction or subsidy is proposed.

## Exact frozen evidence

Corrected candidate `5701f84`, unchanged Solidity `1bbe54c`, 43 new Osaka receipt observations (29 distinct hashes) and the 73-sample combined gas profile are bound in the manifest. The single corrected run completed **960/960 cases in 1236.431 seconds**, exit 0. The prior 960-case uncalibrated run remains separately preserved at `ce0950c`; it is not silently overwritten or mixed into current returns.

The two 30-day completion cohorts contain **62,505 distinct request/completion pairs**: 47,559 and 14,946. Boundaries are 2026-09-25, 2026-10-25 and 2026-11-24 at 11:54:35 UTC. Selection is by completion timestamp. These cohorts have no observed opening carry-ins or originated requests missing a completion; tracked-log ingestion cursors cover the pinned end block. The last tracked log being 516 seconds earlier is not evidence of an ingestion gap.

The design fixes eight request-keyed allocation paths per window, both renewal modes, 0.21 and hypothetical 0.03 backing, fees 0.001/0.0005/0.00025 ETH, and total gas 0.2/0.5 gwei. Owner allocations and purchaser responses are seeded counterfactual draws. Responses sample the recorded empirical first-response cohort, including late/silent patterns, rather than replaying the buyer attached to each original request. Observed-choice and forced timely-return regimes are paired; unresolved responses remain silent. Quiet and two-day busiest-day-then-zero activity are synthetic stresses. Foreign demand and weights do not react to the added manager; current fee rules and stated repeated tapes through exits are assumptions. The path count is an agent choice, not a confidence threshold or owner acceptance requirement.

Gas is a receipt-calibrated curve combined conservatively with work allowances, not a new receipt for every simulated call. Production startup and receipt-history ratios are reused; each path starts without other-account history. Larger sync/renewal sizes remain unmeasured. Model-only KEEPER_LOSS waits may reflect conservative generic cost envelopes or learned proxy ratios; they do not contradict the real corrected one-work acceptance proof. MinPay/replacement estimate variation and failed inclusion remain outside the cohort. No model-only refusal is called a newly demonstrated production defect.

[Frozen manifest](../../sim/out/manager-calibrated-assessment/manifest.json), [all integer-wei paths](../../sim/out/manager-calibrated-assessment/paths.jsonl), [all 144 grouped cells](../../sim/out/manager-calibrated-assessment/report.md), [summary](../../sim/out/manager-calibrated-assessment/summary.json), and [independent results review](manager-calibrated-economics-review.md) provide the complete record.

## Cash, caps and incomplete exits

**957/960 modeled exits complete.** All 480 cases with the deployable 0.21 backing complete, including all fees, both gas contexts and all demand/buyer regimes. Their ending manager-owned cash, inventory, receipts and credit are zero. Unrelated foreign journal entries can remain after a personal manager owns nothing; clearing the entire protocol journal is not required or funded. There are no account topups, unpaid ordinary calls, negative keeper proxy margins, cap breaches or account ledger gaps. The largest signed reservation is **0.00864615 ETH**.

Three hypothetical 0.03-backing Reuse cases at 0.5 gwei stop before the next liquidation would exceed the stated 0.01 ETH signed limit. They share earlier-window path 200005/forced-return stress, one for each fee. No final net return or affected group mean is published. Remaining assets are not called realized owner profit.

| Fee per Shape ETH | Owner ETH withdrawn so far | Manager assets retained ETH | Signed gas maximum already reserved ETH |
|---|---:|---:|---:|
| 0.00025 | 0.00000000 | 1.41405078 | 0.00771572 |
| 0.0005 | 0.00000000 | 1.43252684 | 0.00781193 |
| 0.001 | 0.00000000 | 1.26535148 | 0.00665425 |

A caller limit can require an explicit additional spending authorization to continue. It does not mint ETH or reset prior reservations, and available account assets do not automatically increase wallet permission. The actual independent zero-budget fork exit remains complete within its stated cap; these sensitivity stops are not silently topped up.

For latest-window Fresh / .21 backing / current fee / .5 gwei / observed choices, the same eight paths have this mean cash partition:

| Bucket | Mean ETH |
|---|---:|
| Modeled collected FWA fees | 0.32008771 |
| Net acquisition backing/principal loss | 0.17625000 |
| Settlement fees | 0.00131250 |
| Paid primary mint fees | 0.00243750 |
| Keeper compensation, owner cost once | 0.00217594 |
| Owner wallet gas, including entry/exit | 0.00054503 |
| Owner net | 0.13736673 |
| Keeper gas, not charged to owner again | 0.00209840 |
| Keeper margin | 0.00007754 |

Every raw complete-path owner net is independently reconciled as fees minus acquisition loss, settlement fees, paid mint fees, keeper compensation and wallet gas. Keeper gas is deducted only in its own margin. Creator gross accrual counts paid model mints; real fork receipts separately prove three paid primary events per fresh launch pack. Global factory deployment and hosting/RPC costs are not hidden inside a per-clone owner return.

## Standard backing and fee comparisons

Actual FWA receipts admit .03 backing on .03 packs, but the current manager’s conservative coverage/admission guards reject it, including coverage at the protocol maximum 5% settlement fee. The following isolated admission sensitivity is **not deployable through this manager**. Means combine both windows, sixteen paths per buyer regime; incomplete groups are suppressed.

| Mode / gas | .21 observed mean ETH | .03 hypothetical observed mean ETH | .21 forced-return mean ETH | .03 hypothetical forced-return mean ETH |
|---|---:|---:|---:|---:|
| Fresh / 0.2 | 0.15195789 | -0.07073698 | 0.11234809 | -0.10012197 |
| Fresh / 0.5 | 0.14996184 | -0.11791495 | 0.10935332 | -0.10528545 |
| Reuse / 0.2 | 0.26713278 | 0.03233574 | 0.07561055 | 0.08539690 |
| Reuse / 0.5 | 0.26177013 | 0.00262383 | 0.08420571 | suppressed |

The verified public fee remains .0005 ETH at block 26,492,785, accepted maximum .001 ETH. The .001 case is historical/accepted comparison; .00025 is an agent-chosen fork-only half-current sensitivity, not an approved baseline or public change. Here Fresh/.21 backing is held fixed across both windows:

| Fee per Shape ETH | Gas | Observed mean net ETH | Forced-return mean net ETH | Creator observed gross mean ETH |
|---|---:|---:|---:|---:|
| 0.001 | 0.2 | 0.14877039 | 0.10737934 | 0.00637500 |
| 0.001 | 0.5 | 0.14677434 | 0.10438457 | 0.00637500 |
| 0.0005 | 0.2 | 0.15195789 | 0.11234809 | 0.00318750 |
| 0.0005 | 0.5 | 0.14996184 | 0.10935332 | 0.00318750 |
| 0.00025 | 0.2 | 0.15355164 | 0.11483247 | 0.00159375 |
| 0.00025 | 0.5 | 0.15155559 | 0.11183770 | 0.00159375 |

## Funding, activity and creator tradeoff

Pack principal plus listing backing is **.24 ETH before costs**. At the current fee the conditional first productive Fresh opening is **.461605 ETH at .5 gwei**, or **.4610425 ETH at .2 gwei**, excluding creation wallet gas. It includes actual opening mint fees, quoted initial work, **.2141275 ETH conservative accepted-fee renewal float** and **.005 ETH operating reserve**. The three corrected allowances do not change that initial build/float calculation. The reserve is below the conservative .0054805 ETH maximum listing-plus-journal batch need, and the CLI displays that fact.

Reuse has no fresh-renewal float in this implementation, so it can deploy more capital and change exposure. Per-return savings do not isolate the whole mode effect. One float cannot cover arbitrary early acquisitions; accrued fees require actual collection, and cash and routine-permission waits are separate. All actual keeper payments, including the increased corrected quotes, enter owner costs once.

| Mode / gas | Quiet mean net ETH | Two-day burst then zero, forced-return mean ETH | Worst burst path ETH |
|---|---:|---:|---:|
| Fresh / 0.2 | -0.00223214 | -0.04445681 | -0.08216556 |
| Fresh / 0.5 | -0.00327035 | -0.04683077 | -0.08410677 |
| Reuse / 0.2 | -0.00416914 | -0.13519783 | -0.24588804 |
| Reuse / 0.5 | -0.00580285 | -0.13761529 | -0.24770775 |

Quiet/burst groups contain two stated tapes, not a population forecast. Positive recorded-month averages do not remove their losses. Reuse can worsen the burst outcome despite saving repeated mint fees. With corrected quotes, the measured per-return expense saving from explicit Reuse is **.001726 ETH at .2 gwei / .002005 ETH at .5 gwei**: Fresh pays .0015 ETH creator fees plus .000487/.0011275 keeper compensation; Reuse pays no creator mint fee on that returned pack and .000261/.0006225 compensation. A keep still requires fresh paid replacement. Total-period creator accrual may rise through greater growth/exposure, as the scorecard shows. No hidden fee reduction or recurring sponsorship funds the comparison.

The correction demonstrably enables required small work; it does not impose an invented manager return target or prove future profitability. The selected pack remains .03 ETH. Any production economic acceptance must address the observed loss/funding tradeoff and provisional reserve. The owner can immediately adjust numerical settings; algorithm changes need code.

## Actual execution and delivery boundaries

The corrected fork validates twelve cold ordinary one-work cases at matched .2/.5 gwei: allocated/resolved/combined sync, fresh renewal, explicit reuse listing and fresh build. Ten use the unmodified planner/CLI; allocated-only sync is an explicit production-executor test because the planner defers it before settlement. Four additional CLI calls finish a .5 ETH zero-budget owner exit. All six manager-owned buckets finish at zero. Actual exit gas is **.0001795922 ETH** at .2 gwei; signed exit maxima including budget-zeroing setup are **.00053375455 ETH**, below .01 ETH. These are receipt measurements, not thirty-day returns.

The current image rehearsal separately returned 1.49185190960227 ETH from 1 ETH plus explicit .5 ETH growth funding, including .000247555822532839 ETH owner wallet gas: net -.008395646220262839 ETH. Its creator gross was .0075 ETH from fifteen paid mints, and keeper margin .000249774765864293 ETH after actual gas. The no-topup .5 ETH R2 round trip separately lost .001940071586360229 ETH. Each receipt set retains its original settings/scope; none is added to the simulated portfolio as another charge.

[Operating verification](manager-operating-verification.md), [corrected real CLI proof](manager-calibrated-verification.md), [independent calibration review](manager-calibrated-review.md) and the unsigned manager-only runbook document the final source, commands and limits. Larger sync and multi-pack fresh-renewal receipts, production encrypted-key/hardware transport, public inclusion and live service operation remain unverified or excluded. Both draft PRs remain draft; there is no new shared vault, public transaction, production fee change, production/acceptance signature, live cutover or merge.

Things that do not make sense: positive conditional averages are not downside protection; more spending permission creates no cash; and the .005 reserve remains below the .0054805 maximum-batch need. Those facts are retained rather than tuning away unfavorable results.
