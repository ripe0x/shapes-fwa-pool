# Measured journal candidate and funding decision

The owner-approved amended local candidate passed on the exact `aa38fab` source. Combined baseline/candidate usage is 517/540 transactions and 27.869594973162081536/32 simulated ETH aggregate value. Initial 8.3 ETH funding was not topped up. The 199-transaction candidate needed no repair, and restored the owned 8559 entry state. Quote selection is locally verified; operating acceptance remains blocked.

The current measured schedule is 85,000 ordinary base, 22,000 per completed record, 110,000 required holder-tail base and 80,000 extra only for actual qualified distribution-proof work. Pack 325,000 and all deployment values remain. All 24 candidate journal cases have positive calibration-receipt keeper net, positive full signed-estimate headroom and accepted ordinary preflight. These were refunded records. Successful-foreign receipts and combined own maxima remain gaps. Details: `receipts/efficient-journal-candidate-summary.json`.

## Actual cash source and spending permission

Vault free ETH, earned FWA fees and returned principal supply cash; protected holder buckets do not. Request charges fund their existing checkpoint pool. Creator mint revenue is a separate recipient flow, never an assumed recurring subsidy. Spending permission supplies no cash.

The following arithmetic holds exposure throughout the archived 18,281-record window, packs 128-record jobs perfectly, and assumes one final eligible distribution tail. It excludes own work, additional required tails and actual execution billing. Unexposed intervals can advance unpaid. This is a recorded-window expense comparison, not a forecast.

| Regime | Global journal quote over 30 days | Average quote/day | Existing refill/day | Initial cap plus 30-day refill |
|---|---:|---:|---:|---:|
| Mainnet, 0.2 gwei |0.0828884 ETH|~0.00276295 ETH|0.005 ETH|0.25 ETH|
| Mainnet, 0.5 gwei |0.207221 ETH|~0.00690737 ETH|0.005 ETH|0.25 ETH|
| Canary, 0.2 gwei |0.0828884 ETH|~0.00276295 ETH|0.0008 ETH|0.054 ETH|

Canary's global-only amount is 4.14442% of its 2 ETH deposit cap over this window, before its own work. This is an expense/capital ratio, not a net-return estimate. At 0.5 gwei mainnet's initial cap can temporarily cover the global-only refill deficit; it does not establish recurring coverage. No allowance change is proposed on incomplete economics.

## Complete conditional operating paths

The corrected opt-in model uses 3600-second expiry, distinct 12-hour/15-minute blackout windows, 60-second polls and 40 calls/pass. It uses conditional market/response assumptions and historical or quote gas proxies. The old daily 112-case ledger outputs are explicitly unsuitable for operating/return acceptance. Neither model is an expected-return forecast or a full timed fork replay.

| Candidate conditional path | Exit completes | Fully paid routine work | Underpaid holder harvests | Holder net after caller-gas proxy |
|---|---|---|---:|---:|
| Zero demand |Yes|Yes|0|-0.073071229658515459 ETH|
| Timely 120-second purchaser |Yes|No|44|-0.155298663096359599 ETH|
| Silent purchaser |No|No|45|Incomplete, no realized-return claim|
| Late 7200-second purchaser |Yes|No|45|+0.095939180762570863 ETH|

These paths start with 6.8 ETH principal plus modeled holder charges, run two operating days and at most two exit days at 0.2 gwei, seed 8, with 609 successful selections/day plus the recorded refund ratio in busy cases. That 609 is a conditional stress input, not a replay of the archived window's 439.7 successful/day. They already assume 0.3 ETH initial permission and 0.01 ETH/day refill within hard maxima. No actual parameter changed. Assets and independent external-fee ledgers reconcile to zero wei gaps, but three exits are not three funded-operation passes.

Own work includes sync/terminal/pruning, harvesting, building, relisting, unlisting, liquidation, checkpoint and claims. Whole paid mints, remaining inventory and actual modeled claims are included. Timely gross received fees are 1.819168941380021572 ETH, backing transferred out 1.60792901857869 ETH, harvest pay 0.266081233333330390 ETH, mint fees 0.027 ETH and holder gas proxy 0.0202763454 ETH. Harvest pay alone exceeds gross fees minus transferred backing by 0.054841310531998818 ETH on this particular path, before other operating expenses. Principal recovery is not yield, and creator revenue is not credited back to holders.

Of timely's 44 underpaid holder harvests, 32 hit the 25% realized-fee payment gate and necessarily receive zero at those call states even if permission is increased; corresponding cash deltas confirm the entire fee inflow remains in the vault. Late has 33 such calls among 45. Raising the allowance therefore cannot reimburse every recorded exit call under the current rule. Different policies can produce different trajectories; this does not hold those trajectories fixed as a forecast.

## Recommendation and remaining decision

Keep the PR draft. Do not raise an outcome limit, reduce truthful compensation, impose a minimum TVL or assume creator sponsorship to obtain a pass. Finish successful-foreign evidence when an authentic permitted setup is available. Preserve the one vault, incremental book, paid mints and existing holder liabilities.

The next focused economic experiment should use fee credit first, avoid redundant harvesting before a ready checkpoint, and collect active fees only for a concrete eligible upkeep or exit cash gap. Preserve cash-raising work before a partial redemption checkpoint. This is a proposed scheduling rule, not an implemented or measured saving. The exact next-job cost must include own transitions; the displayed journal floor is insufficient.

A bot-only improvement cannot impose a vault-wide expense guarantee: permissionless callers can still earn current repeated harvest payments. Enforcing useful paid harvest jobs onchain is a separate payment-eligibility design, with gas/size, liquidity and full-exit verification. The current 125-byte PackVault headroom makes that design consequential. Detailed tradeoffs: `receipts/efficient-harvest-next-step.md`. No new policy, allowance, live action or outcome acceptance is authorized by this proposal.

## Things that don't make sense

- A 25% cap on gross fees can exceed the strategy's net edge after backing leaves.
- Permission can be insufficient, but increasing it cannot bypass the existing zero-payment gate or provide ETH.
- Complete claims and exact accounting can still depend on underpaid holder work.
- Global upkeep remains expensive for a small vault even after efficient batching and compensation.

---

The superseded proposals below are retained for their named historical inputs.

# Superseded funding proposal

The owner superseded the recommendation below with the efficient-journal revision dated2026-11-18
(`EFFICIENT-JOURNAL-REVISION.md`, D69). Default funding is vault operating cash, with full expenses
subtracted from holder returns. Recurring sponsorship from creator mint revenue is not the default.
No completion bonus, new minimum TVL, budget/refill increase or outcome revision is adopted.
The old16-record model, essential sync classification, incomplete marked returns and342,766
Foundry checkpoint deduction below are historical and do not describe the new candidate. The
refund deduction double-counted finalized refunds; see `receipts/restock-efficiency-meter-correction.json`.
The new measured operating/complete-exit proposal will be recorded with the efficient revision.

---

# Review follow-up: journal compensation and funding

**Journal compensation and recurring funding remain unresolved; no journal quote, allowance, refill, fee, or accepted owner outcome is changed by this proposal.** The separately implemented checkpoint correction is 360,000 gas. The numerical operating model below has been refreshed for that correction. The actual local journal/exit receipt matrix ran on the preceding 400,000 checkpoint source; its original source/deployment hashes remain attached.

The replacement rehearsal completed within the owner's new boundaries: **77 local transactions, 1.755867382438961584 ETH aggregate transaction value, and exactly 3 simulated ETH initial funding once**, with no topups. It used six verified clean actors and a new exclusively owned Anvil at `127.0.0.1:8557`, fork block 26418539. All branch receipts were archived before restoring the entry snapshot. The original missing-node failure and original approved plan remain preserved, with replacement approval/startup/postflight recorded separately.

## Evidence and capital boundary

The archived 30-day window ends at block 26425092/timestamp 1794802079, with 18,281 completed records: 13,191 successful and 5,090 refunded. The fully packed lower bound is 1,143 calls. Inputs are `receipts/integration-maintenance-mainnet.json` and `integration-maintenance-canary.json`. This is a recorded window, not a forecast.

The review repair permits an unpaid cursor rebase only when the authoritative book has no open position, reserved identifier, active count/backing, allocation, or pending receipt. With exposure, the existing ordered record processor remains required. Unexposed cash-only vaults therefore need not pay to replay foreign history. The following global-cost bounds apply to a vault exposed throughout the window, before its own work. Exposure timing and rebase opportunities change actual spend; these old bounds must not be presented as unavoidable costs of every empty or small vault.

| Exposed-vault regime | Global quote over 30 days | Maximum 30 day routine permission | Global refill need/day | Configured refill/day |
|---|---:|---:|---:|---:|
| Mainnet, 0.2 gwei |0.129117 ETH|0.25 ETH|0.0043039 ETH|0.005 ETH|
| Mainnet, 0.5 gwei |0.3227925 ETH|0.25 ETH|0.01075975 ETH|0.005 ETH|
| Canary, 0.2 gwei |0.129117 ETH|0.054 ETH|0.0043039 ETH|0.0008 ETH|
| Canary, 0.5 gwei |0.3227925 ETH|0.054 ETH|0.01075975 ETH|0.0008 ETH|

The mainnet hard refill maximum is 0.01 ETH/day, already below the 0.5 gwei global-only requirement. The canary's 0.129117 ETH is 6.45585% of its 2 ETH deposit cap. That percentage is a maintenance-expense comparison, not a net return. A 0.005 ETH reserve buys bounded progress; it does not fund recurring global costs.

## Calibrate before changing permission

Archived successful-foreign measurements on the previous source give 158,812 complete gross gas for a startup singleton, 138,930 for a steady singleton, 420,622 for a batch of 16, and 2,181,216 for 16 singleton calls. Archived real refunded receipts give 112,080 billed gas for steady 1 and 361,148 for 16. These gross and billed series are different evidence and cannot be combined into one measured keeper-profit curve. The capital repair adds an exposure/rebase branch before the unchanged processor; the archived measurements do not measure its additional overhead.

The current 85,000+30,000 n quote pays 115,000 for 1 and 565,000 for 16. The two successful-foreign steady gross endpoints imply approximately 120,151 fixed gas and 18,779 per entry. A simple fixed-base increase can cover a tail while increasing the reward for splitting work into small calls. A lower per-entry quote can make nonfinal calls unprofitable and prevent catchup entirely. Neither adjustment is justified merely because it fits an allowance.

The owner-approved replacement executed real refunded prefixes 1..16 and final tails 1..15 from identical exposed state, with actual estimates, 25% signed limits, receipts, payments, and asserted 0.15 gwei basefee/0.2 gwei effective price. One genuine Active vault listing prevented an unexposed rebase shortcut. The genuine requests reached status 3 through FWA's own deadline/processor, then the requester withdrew its actual refund. Actual estimates and billed gas are in `receipts/review-journal-calibration.md`; full inputs, receipts, source hashes and limits are in `review-journal-calibration-summary.json` and `review-journal-local-results.json`.

| Refunded work, one real Active listing | Exact estimate | Billed gas | Paid gas equivalent at 0.2 gwei | Keeper net ETH |
|---|---:|---:|---:|---:|
| Nonfinal prefix 1 | 117,495 | 112,515 | 115,000 | +0.000000497 |
| Full prefix 16 | 366,612 | 361,632 | 565,000 | +0.0000406736 |
| Final tail 1 after processing 15 | 117,469 | 112,489 | 115,000 | +0.0000005022 |

The two-part full-prefix branches add 95,878–95,902 billed gas compared with one 16-record call. A proposed 105,000 base would pay more than that added cost even at zero markup; at 10% markup its extra payment is 115,500 gas equivalent. Per-entry components and a single final-completion payment cancel in this comparison. **Reject the 105,000-base candidate on this observed refunded path.** The existing 85,000 base pays 93,500 extra at maximum 10% markup, below the measured added cost. This is an actual billed two-part comparison, not a universal bound for every future transaction.

Actual successful-foreign small/full/tail billed receipts remain a separate gap. The archived gross successful curve cannot erase the measured refunded split counterexample. The proposed authentic fulfillment route requires a fork after real request creation and before its recorded fulfillment, preserving the historical VRF request blockhash and genuine coordinator caller; that route has not been broadcast here.

A candidate worth measuring, not adopting, is 85,000 base+22,000/entry plus 35,000 only when a nonempty processed batch reaches the completed prefix. It quotes 437,000 for a nonfinal full batch and 142,000 for a final singleton. Those values exceed the two archived successful steady gross points, but leave little singleton margin and have no current receipt proof. A completion payment requires a separately reviewed policy rule; it must never be awarded for empty rebase/no work. At maximum 10% markup the archived split-vs-batch gross comparison is encouraging but does not establish a billed anti-splitting bound. Real estimates and receipts across startup, full, tail, own selections and fee regimes must decide the final constants. This candidate would quote only 107,000 for an intentionally nonfinal singleton versus the measured refunded 112,515 billed gas; a bot processing its maximum can avoid that choice, but that operating assumption must be explicit. No proposed schedule is adopted.

Even this candidate would cost at least 0.249686 ETH/30 days at 0.5 gwei for the recorded entries when only one completion payment is counted, before own work. At one completion per full call it would cost 0.269671 ETH. Catchup frequency determines the completion count. These are arithmetic scenarios, not a calibrated quote or funding recommendation.

## Cash sources and complete own-position cost

Routine budget is spending permission. It neither deposits ETH nor makes protected liabilities spendable. Pending deposits, claimable holder ETH and the processing pool are protected. Request charges fund checkpoint work; entry charges retain build/list resources. They must not silently become recurring global subsidies. Paid primary mints move real ETH to Shapes. Own selected backing, returned principal and harvested fees must be reconciled without counting principal as yield.

For a separate global journal total that already includes every own selection's 30,000 component, own incremental cycle quotes are 160,000 selection+120,000 terminal+45,000 prune+825,000 relist+80,000 harvest=1,230,000 gas. At 0.5 gwei and zero markup this is 0.000615 ETH plus two 0.00002 ETH work fees, or 0.000655 ETH per completed own cycle, before amortized call bases. Adding another 30,000 here would double count the journal already in the global total. Entry per three-unit pack retains 325,000 assembly+660,000 mint share+825,000 listing=1,810,000 quoted gas, plus 0.0003 ETH mint-fee share and two work fees: 0.001245 ETH at 0.5 gwei, before amortized restock/list bases. Actual initial ten-Shape mint is 0.001 ETH, with seven Shapes retained as inventory after one three-unit pack; the per-pack share is not the transaction's whole cash outflow.

A complete funding/return run must reconcile actual free ETH at every call, all global records during exposure, own cycles and their call bases, upfront whole mints, fees actually harvested, request-funded checkpoints, holder entries/exits, and terminal inventory claims. For each regime, report gross income minus recurring maintenance, mint expense and caller costs separately from principal movements. No current result establishes positive net depositor returns or a reliable replenishment source at the stated global activity.

| Operating choice | Who supplies real ETH | Tradeoff | Recommendation |
|---|---|---|---|
| Preserve current allowances and wait for profitable/admissible work | Existing vault cash; callers fund unpaid exit work | Underfunded global catchup can stall; allowance is not yield | Keep limits unchanged during calibration; do not claim unattended viability |
| Explicit recurring sponsor funding | Named sponsor donates unencumbered ETH; donated balance increases vault NAV | Needs a committed amount and source; budget alone cannot provide it | Price full calibrated operating envelope first |
| Change depositor fee/return requirements or admission scale | Depositors through an explicitly approved fee/scale rule | Changes participant economics and accepted outcomes | Requires owner decision with complete return evidence |

Raising the hard maximum alone is not a funding proposal. The recommended next decision is a named, quantified funding source and return envelope after calibrated receipts, rather than an unsupported refill increase.

## Numerical thirty-day operating and funding proposal

These eight illustrative runs use the current 360,000 checkpoint quote, unchanged 85,000/30,000 journal quotes and repaired vault model, unchanged canary/mainnet values, one random seed (8), and 30 days. The canary starts with 1.9601 ETH principal below its 2 ETH cap; mainnet starts with 6.8 ETH. Both include a separate 0.01 ETH dead-share seed. Targets are 27 and 100 positions respectively, not guaranteed maintained exposure. Successful volume is either the recorded 439.7/day or the older 71/day sensitivity; recorded refunded-to-successful activity is included. The accounting model matches both refreshed real fork lifecycles exactly. Its stochastic external events are approximations, so these scenarios are neither fork replay nor a forecast. Raw exact amounts and reproducible method/source/config/database hashes are in `receipts/review-journal-forward-q360-funding.json` and `review-journal-forward-q360-provenance.json`. The exact generator and 7 passing focused model self-checks are archived beside them. The preceding Q_CHECKPOINT400,000 matrix remains immutable historical evidence in `review-journal-forward-funding.json`; no old receipt is relabeled as the new source.

All cost columns below are ETH. Journal pay includes global base/entries **and own selection, resolution and prune**; other keeper pay is total minus journal, avoiding double counting. Other keeper pay includes the initial request-funded checkpoint (0.000092 ETH at 0.2 gwei, 0.0002 ETH at 0.5 gwei); the permission table below removes that payment because it does not draw routine budget. Fees are actually received by the model; backing loss is principal transferred to purchasers, not a keeper fee. Minimum free ETH is sampled after successful calls and at initialization, not continuously. It is distinct from deployment idle ETH after reserve and from a guaranteed cash floor.

| Scale, successful volume, quote price | Fees received | Backing lost | Mint fees | Journal/own-sync pay | Other keeper pay | End journal backlog | Minimum sampled free ETH |
|---|---:|---:|---:|---:|---:|---:|---:|
| Canary, 439.7/day, 0.2 gwei | 1.664450 | 1.661839 | 0.008000 | 0.038650 | 0.014556 | 12,923 | 0.003428 |
| Canary, 71/day, 0.2 gwei | 1.069041 | 0.830920 | 0.009000 | 0.022072 | 0.029371 | 0 | 0.004556 |
| Canary, 439.7/day, 0.5 gwei | 1.135294 | 1.145201 | 0.007000 | 0.030052 | 0.023330 | 16,251 | 0.010000 |
| Canary, 71/day, 0.5 gwei | 0.094831 | 0.597496 | 0.007000 | 0.026452 | 0.026792 | 1,473 | 0.010000 |
| Mainnet, 439.7/day, 0.2 gwei | 14.290001 | 12.002171 | 0.033000 | 0.148427 | 0.096532 | 0 | 0.000106 |
| Mainnet, 71/day, 0.2 gwei | 3.677363 | 2.585083 | 0.030000 | 0.025300 | 0.099923 | 0 | 0.004184 |
| Mainnet, 439.7/day, 0.5 gwei | 4.605678 | 4.082890 | 0.028000 | 0.154218 | 0.090928 | 10,364 | 0.010000 |
| Mainnet, 71/day, 0.5 gwei | 3.024714 | 1.941862 | 0.027000 | 0.059692 | 0.182122 | 0 | 0.010000 |

The marked holder values below include unharvested fees and inventory/positions. A blocked pricing flag prevents treating that mark as withdrawable cash. Return is the actual 30-day marked change against all holder ETH paid in, including request charge. It is calculated from absolute amounts here; the raw `ret` field annualizes the scenario and is not used. External caller gas, donation/subsidy costs, and the additional unpaid backlog exit are excluded from these marks.

| Scale, volume, price | Holder paid in ETH | End marked holder ETH | 30-day marked change | Pricing blocked | Unfunded actions skipped |
|---|---:|---:|---:|---|---:|
| Canary, 439.7/day, 0.2 gwei | 1.960192 | 1.901791 | -2.98% | Yes | 141 |
| Canary, 71/day, 0.2 gwei | 1.960192 | 2.136854 | +9.01% | No | 0 |
| Canary, 439.7/day, 0.5 gwei | 1.960300 | 1.890186 | -3.58% | Yes | 158 |
| Canary, 71/day, 0.5 gwei | 1.960300 | 2.032685 | +3.69% | Yes | 154 |
| Mainnet, 439.7/day, 0.2 gwei | 6.800092 | 8.714687 | +28.16% | No | 70 |
| Mainnet, 71/day, 0.2 gwei | 6.800092 | 7.643465 | +12.40% | No | 0 |
| Mainnet, 439.7/day, 0.5 gwei | 6.800200 | 7.049281 | +3.66% | Yes | 164 |
| Mainnet, 71/day, 0.5 gwei | 6.800200 | 7.563115 | +11.22% | No | 52 |

For the four blocked runs, the following is a **minimum incremental catchup envelope at the existing quote**, with every remaining entry treated only as foreign and calls perfectly packed to 16. Own selections/terminal receipts/pruning can add costs, so these are lower bounds and the adjusted holder mark is optimistic. No new records arrive in this arithmetic catchup. End free cash is sufficient for this narrow work in all four runs; insufficient spending permission, rather than absent aggregate end cash, caused these stalls. This does not establish that the earlier cash path or a full subsequent exit is funded.

| Blocked regime | Minimum extra journal ETH | End free ETH | Routine keeper plus catchup ETH | Minimum extra 30-day permission vs current cap+refill | Minimum refill/day after spending initial cap |
|---|---:|---:|---:|---:|---:|
| Canary, 439.7/day, 0.2 gwei | 0.091274 | 1.111596 | 0.144388 | 0.090388 | 0.003812933 ETH |
| Canary, 439.7/day, 0.5 gwei | 0.286945 | 1.200011 | 0.340128 | 0.286128 | 0.010337583 ETH |
| Canary, 71/day, 0.5 gwei | 0.026048 | 0.109894 | 0.079092 | 0.025092 | 0.001636417 ETH |
| Mainnet, 439.7/day, 0.5 gwei | 0.183000 | 4.210051 | 0.427945 | 0.177945 | 0.010931500 ETH |

The busy mainnet 0.5 gwei scenario needs at least 0.010931500 ETH/day after spending its initial 0.1 ETH permission, already above the existing 0.01 ETH hard maximum. The busy canary at 0.5 gwei similarly needs at least 0.010337583 ETH/day after its 0.03 ETH initial cap. Neither bound includes additional own work hidden in the backlog. Conversely, mainnet 0.2 gwei catches up by day 30 while still skipping 70 unfunded actions earlier: ending current is not continuous availability.

Concrete choices for owner review, with no automatic change:

| Choice | Numerical cash/permission envelope | Depositor and sponsor consequence | Recommendation |
|---|---|---|---|
| Pay the blocked tail from existing unencumbered vault ETH | At least 0.091274 ETH canary/busy/0.2 gwei; 0.286945 ETH canary/busy/0.5; 0.0260475 ETH canary/quiet/0.5; 0.183 ETH mainnet/busy/0.5, plus own work | Reduces marked depositor assets; current essential cap remains zero, so requesting holders can instead pay their own transaction gas for mandatory exit work | Quantify full exposed exit before accepting cost; do not reclassify protected buckets |
| Sponsor the same known backlog while preserving pre-catchup vault capital | An identified sponsor donates at least the above amounts, with a separately approved spending allowance for paid routine work | Adds real unencumbered ETH; benefits existing shares including dead shares. It is external subsidy, not investment income or demonstrated returns | Viable only if the owner names and commits the actual cash source; no donation or budget change is authorized here |
| Commit a recurring operating subsidy/allowance | Busy observed routine keeper plus minimum catchup: 0.144388 ETH/canary/0.2; 0.3401275 ETH/canary/0.5; 0.427945 ETH/mainnet/0.5 per recorded 30-day scenario, before unprocessed own costs | These are minimum cost envelopes, not proposed depositor fees. Subtract only harvested income genuinely available after restoring transferred principal and other liabilities; principal and fee marks are not free new income | Calibrate first, then price the complete path and sponsor contribution; current figures do not justify raising a hard maximum alone |
| Retain current economics with no subsidy | Current configured cap/refill and existing free ETH only | Busy canary marks lose roughly 2.98% to 3.58% over these 30 days before clearing backlog; several marks cannot be priced | Keep limits unchanged pending evidence, and keep unattended operation/return acceptance blocked |

No owner funding source has been committed. The aggregate end balances show that some failures are permission/timing failures despite available vault ETH; donation is therefore an optional subsidy for preserving depositor capital, not a universally necessary rescue. A positive marked scenario does not settle O2 or the annual return requirement. The checkpoint correction does not fund recurring journal work. Sponsor capital must be excluded when evaluating earned return. The caller-funded exposed 16-refund exit is now measured below; successful-foreign billed calibration, broader exit liquidity and multi-seed sensitivity remain missing evidence.

## Exit and one-screen outcome scorecard

With shares locked or wind-down active, global catchup is essential. Both configured essential budgets/refills are zero; holders pay for unrelated history while they retain exposure. The actual local holder roundtrip used a 0.8 ETH deposit, one real three-unit pack/Active listing, and 16 genuinely expired/refunded records. Request, sync, unlist, full liquidation, checkpoint and claim billed **1,919,103 gas / 0.0003838206 ETH** at 0.2 gwei. Sync/unlist/liquidate were unpaid despite positive routine budget; checkpoint paid 0.0001 ETH from the request pool. Caller gas less compensation was **0.0002838206 ETH** across those six exit calls. The existing 400,000 checkpoint quote source was used; no new 360,000-source local receipt is claimed.

The holder paid 0.800187699 ETH including entry/exit request charges; received 0.798104438999250060 ETH claim plus its 0.0001 ETH checkpoint payment; and spent 0.000416728650215460 ETH on all seven holder transactions including deposit. Its complete native-flow loss is **0.002399988650965400 ETH**. This includes paid primary mint fees and keeper work, not only gas. The final vault balance directly read was 0.010073561000749940 ETH. Checkpoint/claim events prove 1 wei protected redemption-rounding reserve, leaving residual NAV 0.010073561000749939 ETH. Exact ledger: 0.01 ETH seed + 0.800187699 ETH holder input = 0.001009699 ETH keeper payments + 0.001 ETH primary mint fees + 0.798104438999250060 ETH claim + 0.010073561000749940 ETH residual cash. Holder shares, locked shares and claimable were directly asserted zero.

The final protected totals and final holder native balance are event/source derived; full final getters were not archived before snapshot restoration. This limitation is explicit in `review-journal-calibration-summary.json`. Postflight directly verified restoration of all six actor balances/nonces/code, the original head, automine, empty pool and owned node PID 98279. The 16 acquisition requests independently returned 0.943831021984321584 ETH from 0.945679683438961584 ETH sent; 0.001848661454640000 ETH remained as actual nonrefunded VRF/protocol expense, plus caller gas. That foreign requester expense is separate from vault/depositor economics.

Cash-only unexposed holders avoid the per-record path entirely. The focused real fork test has 269 authentic successful foreign records plus 16 new genuine refunds, rebase gross 121,884 gas and request/rebase/checkpoint/claim gross 681,114 gas, a 0.0001362228 ETH pre-refund proxy at 0.2 gwei. The holder claims 1.999894649974540410 ETH of its 2 ETH pre-charge capital after existing entry charge/dead-share pricing. These are Foundry meters, not billed receipts; source scope is in `review-journal-focused-evidence.json`.

| Owner outcome | Required number | Current bounded result | Status |
|---|---:|---:|---|
| Minimum-seed first deposit | No donated rescue capital | 3 real-fork tests pass; 673 actual foreign records skipped unpaid; seed preserved and first deposit priced (`receipts/review-bootstrap-results.json`) | **Focused pass** |
| O2 build/list per position | <=1,750,000 quoted gas | Unchanged build/list components: 1,919,655 in repaired-source max-load flow | **Fail; unchanged outcome** |
| O6 gas-spike checkpoint payment | <=0.0002 ETH | Current-source real gas-spike flow pays 0.0002 ETH; balanced accounting | **Focused pass; unchanged outcome limit** |
| Routine operational funding | Actual ETH and sustained refill sufficient | Exposed global-only 0.3227925 ETH/30 days at 0.5 gwei exceeds 0.25 ETH mainnet permission |**Blocked**|
| Zero-essential exposed backlog exit | Measured through checkpoint/claim | Actual 16-refund exposed exit: 1,919,103 billed gas; complete claim; exact ETH ledger | **Measured bounded pass** |
| Final small/full/tail quote profitability | Real estimates and billed receipts | Real refunded prefix/tail matrix completed; successful-foreign billed matrix missing | **Partially calibrated** |

The preceding 400,000-checkpoint source failed O2/O6 with balanced accounting (`receipts/review-bootstrap-o2-o6-results.json`, source hash `31ce8de4f1babf5f6a38de98d9403298bf4389b10477a7d91b4e706ca0b3dfa3`). O2 remains unchanged: its ideal marginal quote is already 1,810,000 before call bases and mint rounding, above its 1,750,000 limit.

The separately implemented 360,000 checkpoint quote meets O6's unchanged 0.0002 ETH number in the fresh real gas-spike flow, with zero accounting mismatches. Source-bound fresh full-holder, essential-spike, bootstrap, receipt/receiver and both exact model reconciliations also pass (`receipts/review-bootstrap-q360-results.json`; O6 source hash `b842725caa43f700be61110ac09d5586dd89aec29d248b64ec541290873065cf`). The full-holder checkpoint measures 372,366 gross gas and a 29,600 frame refund, a refund-adjusted sample upper bound of 342,766. This remains a Foundry frame-based bound, **not an actual billed receipt or a universal profitability claim**. Full-holder billed receipt confirmation is an explicit release evidence gap. The local journal/exit receipts above retain their original 400,000 checkpoint source attribution.

## Things that don't make sense

- A 30-day allowance can look sufficient while recurring refill and actual free ETH are insufficient. Three independent numbers must be shown.
- Charging a 2 ETH canary the global protocol's exposed maintenance is a material expense; larger permissions cannot establish acceptable returns.
- A blanket quote-base increase pays repeatedly for split calls. A quote reduction that makes early catchup calls lose money can strand the final profitable tail.
- The real 16-refund exposed exit is measured; that bounded case does not establish the cost of a larger successful-foreign backlog.
- The original node disappeared; the guard stopped before mutation. The owner separately approved the replacement rather than treating an unrelated listener as the original node.
- A 105,000 base appeared compatible with old successful gross splitting math, but the new actual refunded receipts show a profitable-split counterexample even at zero markup.
