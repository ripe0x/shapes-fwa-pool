# Individual manager uncalibrated baseline, 2026-11-25

**Historical uncalibrated baseline, not the corrected candidate. Do not launch these settings.** The complete recorded-period cohort has positive average high-backing returns, severe losing paths and frequent keeper refusals. In recorded-month / 0.21 ETH backing cases at 0.5 gwei, every current-fee Fresh path waits on keeper economics, and the latest-window paths execute no paid renewal. A positive average under that behavior does not establish the intended continuously renewed strategy or production viability. No production economic setting was changed.

## One-screen scorecard

All scenarios start with exactly **0.5 ETH**, without topups, and include clone creation plus owner-paid exit gas. Amounts below are **net ETH per account** over the latest recorded 30-day window, with up to seven exit days. Each displayed buyer regime has eight fixed paths. These are conditional simulated outcomes, not billed full-period portfolios or APR. Actual operating receipts are reported separately. Percentages divide net ETH by the 0.5 ETH account funding and are not annualized.

| Mode / gas gwei | Observed-choice mean net | Worst observed-choice net | Losing paths | Forced-return stress mean net | Creator mean gross ETH, observed | Keeper mean margin ETH, observed |
|---|---:|---:|---:|---:|---:|---:|
| Fresh / 0.2 | 0.13899557 (+27.80%) | -0.42639091 | 2/8 | 0.10139075 | 0.00243750 | 0.00009252 |
| Fresh / 0.5 | 0.11745511 (+23.49%) | -0.18544656 | 4/8 | 0.06518944 | 0.00187500 | 0.00002130 |
| Reuse / 0.2 | 0.42063126 (+84.13%) | -0.13233368 | 2/8 | 0.18804096 | 0.00600000 | 0.00022876 |
| Reuse / 0.5 | 0.28860380 (+57.72%) | -0.13391689 | 2/8 | 0.12564123 | 0.00450000 | 0.00014376 |

This table uses 0.21 ETH backing and the observed 0.0005 ETH fee per Shape. Creator accrual counts paid primary mints only. Keeper margin subtracts modeled receipt-calibrated gas; it excludes hosting/RPC overhead. A different earlier window includes a **negative 0.03411522 ETH mean** for Reuse at 0.5 gwei in forced-return stress. No pooled 10% annual depositor hurdle is applied to these personal accounts, and this study does not establish that shared-vault requirement. No separate manager return/risk hurdle has been owner-approved.

## What is measured and what is assumed

The single frozen run completed **960/960 scenarios in 1739.158 seconds**, exit 0, at model revision `2b9b165` with calibration `72a9586`. Its two nonoverlapping 30-day completion cohorts contain 47,559 and 14,946 distinct completed request/completion pairs, respectively: 62,505 total. Selection is by AcquisitionProcessed timestamp; the generic importer clamps any earlier-origin request to the window opening. These two cohorts have no observed opening carry-ins or in-window-origin requests missing a completion. Ingestion cursors cover the pinned end block; the last tracked event is 516 seconds earlier, which is not a proven ingestion gap. The windows run 2026-09-25 to 2026-10-25 and 2026-10-25 to 2026-11-24, with boundaries at 11:54:35 UTC. Eight fixed paired allocation paths per window, two buyer regimes, three demand regimes, both renewal modes, both backing cases, three fees and two gas prices form the bounded design. The path count is an agent choice, not an owner acceptance requirement or future-market confidence threshold.

Observed choices retain archived first-response timing, including late and censored cases. The separate adverse regime forces eventual responders to return the pack within 3480 seconds; archive-unresolved cases stay silent. Foreign requests/weights and protocol service follow the recorded tape, with the stated repeated tape through exits. Participants do not react to the added manager. This is not a replay of its exact historical VRF selections. Quiet and early-burst-then-zero are synthetic activity regimes. Current protocol rules and fee states are applied to the tapes.

Gas uses real billed single-work samples and measured extra-work slopes, conservatively combined with verified-work allowances. The keeper screen reuses production default ratios, then same-label last-20 receipt history after three observations. Each scenario starts with fresh empty history, and an additional known-bill/physical-cost floor prevents assumed losses. Historical signed gas limits are explicitly upper bounds where raw estimates are unavailable. MinPay/replacement-specific estimate changes, failed inclusion, other-account history and unmeasured larger batch costs remain limitations. These modeled gas amounts are not transaction receipts.

[Frozen manifest](../../sim/out/manager-operating-assessment/manifest.json), [all integer-wei paths](../../sim/out/manager-operating-assessment/paths.jsonl), [complete grouped report](../../sim/out/manager-operating-assessment/report.md), and [full summary](../../sim/out/manager-operating-assessment/summary.json) retain every cell. The withdrawn two-draw result and all earlier incomplete campaigns supply no numbers here.

## All cash buckets close

All **960 exits complete**, with zero ending cash, inventory, receipts and external credit; all account ledger gaps are zero. No account topup or unpaid ordinary call occurs. No caller cap is breached or stops an exit. The largest cumulative signed exit reservation is **0.00941895455 ETH**, below the evaluation 0.01 ETH cap. Every keeper proxy margin is nonnegative, including each accepted-call cost floor. The owner pays exit processing and required recovery; the model does not invent an unpaid keeper.

For the latest-window Fresh / 0.21 backing / current fee / 0.5 gwei / observed-choice case, the same eight paths have this mean partition:

| Bucket | Mean ETH |
|---|---:|
| FWA fees actually collected in the modeled path | 0.31318920 |
| Backing/principal lost on acquisitions | 0.19125000 |
| Settlement fees | 0.00052500 |
| Paid primary mint fees to creator accrual | 0.00187500 |
| Actual modeled keeper payment, counted once | 0.00127125 |
| Owner wallet gas, including creation/exit | 0.00081285 |
| Owner net after all those costs | 0.11745511 |
| Keeper gas, separate from owner costs | 0.00124995 |
| Keeper margin, separate from owner return | 0.00002130 |

Owner net equals collected fees minus acquisition loss, settlement fees, creator mint fees, keeper compensation and wallet gas. Keeper gas is subtracted only from keeper compensation to calculate its margin; it is not charged to the owner again. Creator amounts are gross accrued primary fees, not a claim of net creator profit after factory/service costs. One-time global deployment and service costs are separate from per-clone owner returns.

## Standard 0.03 backing comparison

The actual FWA admits a 0.03 ETH pack with 0.03 ETH backing, as the separate manual fork receipts show. **The current manager rejects it** through its conservative coverage/admission checks, including coverage at the protocol maximum 5% settlement fee. The isolated comparison relaxes admission only; it is not deployable by selecting a ratio in this manager. Both backing cases share each request-keyed tape. Below are means over both windows, sixteen paths per buyer regime, at the current fee.

| Mode / gas | .21 backing, observed mean ETH | .03 hypothetical, observed mean ETH | .21 backing, forced-return mean ETH | .03 hypothetical, forced-return mean ETH |
|---|---:|---:|---:|---:|
| Fresh / 0.2 | 0.15202877 | -0.10623690 | 0.11244259 | -0.07631138 |
| Fresh / 0.5 | 0.10233012 | -0.11186922 | 0.06597136 | -0.07345384 |
| Reuse / 0.2 | 0.25564738 | 0.06627643 | 0.09581586 | 0.11028394 |
| Reuse / 0.5 | 0.17036615 | 0.02347780 | 0.04576300 | 0.00193447 |

Fresh at standard backing loses on average in all four current-fee recorded-month comparisons. Some hypothetical Reuse means are positive, but that does not remove the actual manager admission restriction, losing paths or funding/keeper waits. No code change to admit that ratio is included.

## Fee sensitivities remain separate

Current 0.0005 ETH was observed publicly at block 26,492,390. Historical/accepted 0.001 ETH and agent-chosen fork-only half-current 0.00025 ETH cases were evaluated separately, including both real fork fee directions. No public fee was changed. This table keeps Fresh, .21 backing and both full windows fixed.

| Fee per Shape ETH | Gas gwei | Observed mean net ETH | Forced-return mean net ETH | Creator observed mean ETH |
|---|---:|---:|---:|---:|
| 0.001 | 0.2 | 0.14884127 | 0.10747384 | 0.00637500 |
| 0.001 | 0.5 | 0.10008012 | 0.06447136 | 0.00450000 |
| 0.0005 | 0.2 | 0.15202877 | 0.11244259 | 0.00318750 |
| 0.0005 | 0.5 | 0.10233012 | 0.06597136 | 0.00225000 |
| 0.00025 | 0.2 | 0.15362252 | 0.11492697 | 0.00159375 |
| 0.00025 | 0.5 | 0.10345512 | 0.06672136 | 0.00112500 |

The lower fee is a sensitivity, not the baseline or an approved fix. None of these returns is annualized.

## Funding and low activity

A position uses **0.24 ETH** in pack principal plus separate backing before costs. At the observed fee, the conditional first productive Fresh opening is **0.461605 ETH at 0.5 gwei**, or **0.4610425 ETH at 0.2 gwei**, excluding creation wallet gas. It includes actual opening mint fees, initial quoted work, **0.2141275 ETH conservative renewal float** and **0.005 ETH operating reserve**. The float uses the accepted fee limit, not a claim that actual mints spend that maximum. Reuse derives no fresh-renewal float in the current implementation, so mode comparisons also change deployable capital and exposure; they are not a pure fee-only experiment.

| Mode / gas | Quiet mean loss ETH | Early-burst-then-zero, forced-return mean ETH | Worst burst path ETH |
|---|---:|---:|---:|
| Fresh / 0.2 | -0.00223214 | -0.04439381 | -0.08212356 |
| Fresh / 0.5 | -0.00327035 | -0.11292905 | -0.12528725 |
| Reuse / 0.2 | -0.00416914 | -0.20187649 | -0.24580404 |
| Reuse / 0.5 | -0.00580285 | -0.20349395 | -0.24744275 |

Each quiet/burst cell contains two stated tapes, not a statistical forecast. One float does not cover arbitrary early acquisitions. Reuse reduces per-return mint expense but can expose more capital and performs worse in these burst cases. Cash shortfalls and permission exhaustion are recorded independently; increasing permission creates no ETH. At hypothetical low backing/current fee/0.5 gwei, Fresh includes renewal-cash, renewal-permission and maintenance waits. These are poll observations, not paid failed transactions.

## Keeper calibration is the first necessary change

The raw Osaka receipts show positive actual combined-sync margins, but the cold keeper still refuses those calls. Separate sync can lose on the bill itself. Required one-pack relisting also misses cold estimates. The measured allowance increases below are only the arithmetic lower bounds for the recorded calls at 0.5 gwei with zero requested margin/failure allowance. They are **not production settings or a new passing economic candidate**; exact minPay re-estimation and state changes need headroom.

| Named coefficient | Existing gas allowance | Minimum recorded additional allowance | Resulting arithmetic floor |
|---|---:|---:|---:|
| selected | 180000 | 30916 | 210916 |
| synced | 120000 | 136429 | 256429 |
| list (base) | 280000 | 64424 | 344424 |

Each account owner can make those numerical changes immediately with the existing configuration; no external policy or algorithm replacement is needed. At 0.5 gwei the current cold shortfalls are 0.000015458 ETH for allocated sync, 0.0000682145 ETH for resolved sync, 0.0000467105 ETH for combined sync and 0.000032212 ETH for one-pack relisting. Do not lower one shared billed ratio to hide an operation that really loses money. The current .005 ETH reserve is also below its displayed .0054 ETH maximum-batch quote.

**Recommendation: keep the 0.03 ETH recipe and fix measured quote calibration before release. Do not adopt Reuse as a blanket viability fix or lower the public mint fee.** An explicit Reuse choice saves 0.001746 ETH at .2 gwei or 0.002055 ETH at .5 gwei per returned launch pack in the measured local renewal-versus-listing expense, including 0.0015 ETH of creator fees no longer paid on that return. A keep still needs a fresh paid replacement. The full-cohort comparison shows why that local saving alone is not a production recommendation: Reuse releases the float, changes exposure and can worsen early-burst outcomes.

This baseline candidate fails the required dependable small-work keeper acceptance, even where its conditional mean owner return is positive. It therefore does **not** satisfy the complete operating requirements for release. The three measured gas-underquote defects are being repaired using owner-owned numerical configuration before a new unsigned candidate is prepared. No production economic calibration/funding choice is approved. No untested adjustment is called viable, and no new return/risk requirement is invented. Larger sync and multi-pack fresh-renewal sizes remain unmeasured.

## Actual receipts remain a different evidence class

The current-image 1 ETH plus explicit .5 ETH growth lifecycle returned 1.49185190960227 ETH, with .000247555822532839 ETH owner gas: net **-.008395646220262839 ETH**. Creator gross fees were .0075 ETH from fifteen actual paid mints; keeper compensation .00064809039773 ETH minus .000398315631865707 ETH actual gas left .000249774765864293 ETH. The actual no-topup .5 ETH R2 round trip separately lost .001940071586360229 ETH including wallet gas. These are complete unselected fork lifecycles, not thirty-day portfolios. Calibrated renewal/reuse branches prove actual paid work but are not one continuous portfolio.

[Operating verification](manager-operating-verification.md) contains commands, revisions, real-counterparty proof, image results, remaining evidence gaps and unsigned deployment data. [Independent source/calibration review](manager-operating-model-review.md) and the [baseline financial review](manager-operating-baseline-review.md) retain their own scope. The shared vault remains undeployed, both main app launch switches stay disabled, both PRs stay draft, and no public transaction, production fee change, production signature, cutover or merge occurs.

Things that do not make sense: calling a strategy continuously renewing when all current-fee .5 gwei Fresh paths stall on keeper economics; treating a positive mean as protection against an 85% losing path; or counting creator and keeper revenue as owner profit.
