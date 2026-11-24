# Main pool economic evaluation, 2026-11-24

**Keep the package unsigned and the main-pool production gate closed.** The implementation evidence is distinct from the economic launch decision. At the selected 0.03 ETH recipe, the 1.9601 ETH holder cell fails the unchanged 10% net return hurdle at 0.5 gwei. None of the tested small-capital backing/float alternatives establishes that hurdle using the standard median.

| Outcome | Bounded result |
|---|---|
| Three paid fresh mints | 0.03 ETH pack; gross primary fees accrued 0.003 ETH at the current fee, 0.0015 ETH in the isolated half-fee sensitivity. |
| 10% holder hurdle | **FAIL**: standard median -53.68%, historical upper-middle -24.73%, worst -83.80%, losses 3/4 in the 1.9601 ETH / 0.5 gwei cell. |
| Completed exits | 89/89 model exits complete; all six actual contract/mirror trace groups reconcile to the wei. This does not guarantee future exit timing. |
| Bid-cycle screen | Closed-form net at 0.5 gwei +0.003603205 ETH after the full fresh lifecycle quote; this does not establish annual holder returns. |
| Keeper receipt sample | All 19 positive-payment rows among 103 campaign receipts have positive pay minus billed gas; smallest observed surplus 26907309484955 wei. This is not an all-operation profitability claim. |
| Checkpoint expense target | **FAIL** against retained O6 target 0.0002 ETH: 500,000 gas + 0.00002 work fee costs 0.00027 ETH at 0.5 gwei, or 0.00102 ETH at the 2 gwei funded-checkpoint ceiling. Allocation-proof work can add cost. |
| Unresolved pricing | Selected 25 bps tolerance permits measurable ordering transfers; a 0.18 ETH unresolved uplift requires at least 72 ETH preflow NAV. |
| Production boundary | No public transaction, mint-fee change, live cutover or merge. Existing contracts and balances are preserved. |

## Evidence and method

One frozen campaign ran `CANDIDATE_RUN=1 /tmp/shapes-completion-python/bin/python sim/formal.py --seeds 4 --workers 4`: 22 stochastic cells with four draws each, plus one deterministic zero-demand case. The actual trailing 30 days are repeated for 360 operating days, with up to 30 exit days. Tokens are zero. The fee archive checked 876,437 EarningsAccrued records with zero mismatches and continuous acquisition sequences.

The window contains 9856 successful and 5090 refunded acquisitions (328.53 successes/day), ending at block 26,484,850. Latest separate readback at block 26,485,995 confirms the current Shapes mint fee remains 0.001 ETH. The half-fee cells keep the accepted maximum at 0.001 ETH, so their float stays conservative.

Every holder return below includes actual account mint fees and keeper compensation once, checkpoint/contribution net consumption, and holder wallet gas. Wallet gas is a labelled proxy from actual billed receipts; variable unpaid maintenance uses the larger of its verified-work allowance and calibrated receipt sample. Reverted races and inclusion latency are not priced. Keeper columns show compensation, not net profit. Creator columns show gross paid primary-mint fees accrued in Shapes; no creator wallet withdrawal was executed or claimed.

The deployment package separately requires a 0.01 ETH seed and estimates 0.022785059249598685 ETH one-off deployment gas. These are unsigned simulation values, not public expenditure. They are excluded from recurring holder returns; creator gross fees are not owner net profit after startup/withdrawal costs.

The standard median is the mean of the middle pair. The original script upper-middle statistic remains visible for comparison and floors to integer basis points; occasional 0.01 percentage-point display differences even for one draw come from that flooring. Both fail the overall gate. With four draws, the empirical P10 equals the worst draw; none is a statistical confidence bound. Large positive outliers must not be substituted for depositor downside.

The complete six-group contract/mirror command was `/tmp/shapes-completion-python/bin/python sim/reconcile.py` from the repository root, exit 0. Exact argv, environment, source/trace hashes and durable stdout are embedded in the frozen-run JSON. Archive replay also ran inside that exact formal invocation before any scenario jobs.

## All scenario cells

Amounts in ETH; flow columns are means within the same cell. Returns are completed-holder net returns on actual paid-in value.

| Cell | Capital | gwei | Standard median | Upper-middle | Worst | Losses; claims | Gross primary fees accrued | Keeper compensation | Wallet gas proxy |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| formal | 1.9601 | 0.5 | -53.68% | -24.73% | -83.80% | 3/4; 4/4 | 0.735750 | 0.312059 | 0.008227 |
| formal | 6.8 | 0.5 | +121.84% | +239.78% | -57.61% | 1/4; 4/4 | 2.688000 | 1.214015 | 0.019514 |
| formal | 20 | 0.5 | +80.81% | +88.23% | +41.36% | 0/4; 4/4 | 6.501750 | 3.234138 | 0.046177 |
| formal | 1.9601 | 0.2 | -54.90% | -29.31% | -83.14% | 3/4; 4/4 | 0.721500 | 0.131881 | 0.002896 |
| formal | 6.8 | 0.2 | +58.78% | +124.36% | -82.41% | 2/4; 4/4 | 2.544750 | 0.480607 | 0.007489 |
| formal | 20 | 0.2 | +77.39% | +98.91% | +41.80% | 0/4; 4/4 | 6.953250 | 1.375077 | 0.018503 |
| half-fee-sensitivity | 1.9601 | 0.2 | -79.80% | -77.92% | -84.52% | 3/4; 4/4 | 0.401625 | 0.148730 | 0.002997 |
| half-fee-sensitivity | 1.9601 | 0.5 | -69.00% | -59.94% | -82.36% | 3/4; 4/4 | 0.394500 | 0.338342 | 0.008438 |
| recent-10-days | 1.9601 | 0.5 | -44.73% | -14.01% | -80.12% | 3/4; 4/4 | 0.113250 | 0.044655 | 0.004716 |
| zero-demand | 1.9601 | 0.5 | -1.61% | -1.62% | -1.62% | 1/1; 1/1 | 0.021000 | 0.006213 | 0.004393 |
| recorded-timing | 1.9601 | 0.5 | +3245.07% | +4052.77% | +212.55% | 0/4; 4/4 | 4.477500 | 2.227301 | 0.050264 |
| recorded-choice | 1.9601 | 0.5 | +6935.51% | +7320.04% | +3449.55% | 0/4; 4/4 | 6.888750 | 3.596609 | 0.065440 |
| oracle-capped | 1.9601 | 0.5 | -0.06% | -0.07% | -0.07% | 4/4; 4/4 | 0.000000 | 0.000270 | 0.000768 |
| backing-50000 | 1.9601 | 0.2 | -54.09% | -46.25% | -78.35% | 3/4; 4/4 | 1.341000 | 0.251886 | 0.003813 |
| backing-50000 | 1.9601 | 0.5 | -48.32% | -31.28% | -81.35% | 3/4; 4/4 | 1.374750 | 0.589802 | 0.009746 |
| backing-90000 | 1.9601 | 0.2 | +5.24% | +95.86% | -88.10% | 2/4; 4/4 | 0.675000 | 0.122556 | 0.003547 |
| backing-90000 | 1.9601 | 0.5 | -33.83% | +11.12% | -88.60% | 2/4; 4/4 | 0.601500 | 0.250758 | 0.007825 |
| float-2 | 1.9601 | 0.2 | -53.75% | -25.32% | -83.85% | 3/4; 4/4 | 0.782250 | 0.141368 | 0.003374 |
| float-2 | 1.9601 | 0.5 | -66.55% | -51.09% | -83.65% | 3/4; 4/4 | 0.639750 | 0.259538 | 0.006821 |
| early-burst-then-zero | 1.9601 | 0.2 | -74.81% | -74.33% | -79.20% | 3/4; 4/4 | 0.280500 | 0.059371 | 0.002560 |
| early-burst-then-zero | 1.9601 | 0.5 | -57.29% | -38.22% | -80.53% | 3/4; 4/4 | 0.213000 | 0.096179 | 0.006337 |
| early-burst-low-permission | 1.9601 | 0.2 | -10.56% | +2.64% | -30.26% | 2/4; 4/4 | 0.025500 | 0.003921 | 0.001307 |
| early-burst-low-permission | 1.9601 | 0.5 | -5.21% | -1.90% | -11.64% | 3/4; 4/4 | 0.012000 | 0.004166 | 0.002723 |

Recorded timing/choice cases are diagnostics, not the all-bid formal gate. Purchaser choices and vault selections are seeded counterfactuals; historical VRF selected foreign listings. Foreign pool weights/fees do not react to the candidate. Early-burst cases synthesize ten copies of the recorded month compressed into the first two days and then zero acquisitions, not observed activity or billed fork performance. In this abstract compression, 2,834 of 149,460 requests land inside purchase blackout; the compressed request/VRF schedule is not feasible onchain. These cells only stress cash and permission and cannot establish protocol timing or a passing return gate.

Fee and gas cells follow state-dependent selection and reinvestment paths even with the same seed. Four draws do not establish that a fee reduction causes worse returns. With other state held fixed, the fork tests verify that a lower live fee reduces the actual mint cost; none of these sensitivities approves a production fee change.

## First opening and burst funding

Named schedule: full construction allowance 1,875,000 gas; retirement allowance 260,000 gas. One conservative renewal float is backing + three accepted fees + full retirement/build/list compensation at the routine ceiling: **0.2141275 ETH**. The independent maintenance reserve is 0.005 ETH.

| Actual mint fee per Shape | Total gas price | Construction compensation | Gross primary fees | Account cash needed before first build |
|---|---:|---:|---:|---:|
| 0.001 ETH | 0.2 gwei | 0.0004150 | 0.0030 | 0.4625425 ETH |
| 0.001 ETH | 0.5 gwei | 0.0009775 | 0.0030 | 0.4631050 ETH |
| 0.0005 ETH | 0.2 gwei | 0.0004150 | 0.0015 | 0.4610425 ETH |
| 0.0005 ETH | 0.5 gwei | 0.0009775 | 0.0015 | 0.4616050 ETH |

These are account cash thresholds including seed cash, reserve and float; checkpoint sponsorship and wallet/deployment gas are additional. They are not a minimum deposit or a minimum TVL. Cash-only deposits and exits still work below the first productive opening.

One float covers one worst-gap returned acquisition renewal, not an arbitrary burst. The real conditional-credit funding trace started with 0.213466500807007324 ETH cash, 0.03 ETH returned principal and 0.000072998385985353 ETH actual fee credit. It paid 0.000503 ETH keeper compensation and 0.003 ETH mint fees, then ended with 0.000036499192992677 ETH cash, one eligible returned pack and 0.298675333333333333 ETH routine permission. The next renewal waits for cash despite ample permission. That isolated branch uses reserve zero to expose funding; it is not the default reserve scenario.

Conversely, the low-permission stress uses routine cap 0.004 ETH and refill zero. Raising a capacity does not refill spent permission; increasing a rate accrues prospectively. Available ETH cannot substitute for spending authority. Operating-end diagnostics below distinguish the two balances; cash includes protected amounts and is not all spendable.

| Synthetic cell | gwei | Standard median | Mean operating-end cash | Mean remaining routine permission | Mean routine compensation | Mean journal backlog at cutoff |
|---|---:|---:|---:|---:|---:|---:|
| early-burst-then-zero | 0.2 | -74.81% | 0.148413 | 0.100000 | 0.059251 | 32451.2 |
| early-burst-then-zero | 0.5 | -57.29% | 0.122638 | 0.100000 | 0.095909 | 33811.0 |
| early-burst-low-permission | 0.2 | -10.56% | 1.464674 | 0.000199 | 0.003801 | 134440.2 |
| early-burst-low-permission | 0.5 | -5.21% | 1.732019 | 0.000104 | 0.003896 | 139869.8 |

## Backing, float and uncertainty tradeoffs

Keep the fixed three-mint recipe. None of these four-seed small-capital alternatives clears the standard-median hurdle at both tested prices. Do not change production economics to manufacture a passing upper-middle statistic.

| Candidate | First-opening cash at 0.5 gwei/current fee | Worst-gap float | Preflow NAV for one unresolved allocation at 25 bps | Tradeoff |
|---|---:|---:|---:|---|
| 50,000 bps / float1 | 0.3431050 ETH | 0.1541275 ETH | 48 ETH | Lower cash demand, lower bid-cycle margin |
| 70,000 bps / float1 | 0.4631050 ETH | 0.2141275 ETH | 72 ETH | Selected local evaluation candidate |
| 90,000 bps / float1 | 0.5831050 ETH | 0.2741275 ETH | 96 ETH | More cash and greater pricing uncertainty |
| 70,000 bps / float2 | 0.6772325 ETH | 0.4282550 ETH | 72 ETH | One extra worst-gap replacement, less growth cash |

For selected backing 0.21 ETH and face 0.03 ETH, unresolved uplift is 0.18 ETH. The bound is `uplift × 10,000 ≤ preflow NAV × 25`, giving exactly 72 ETH for one allocation and 144 ETH for two. Pending unpriced deposits do not fund this denominator. Smaller accounts wait for real settlement/recovery; this is a temporary pricing limitation, not a listing cap or a new minimum TVL.

## Actual pricing-order wealth effects

The current real-protocol fairness tests completed both holders’ full exits. Comparing keep-after-pricing with keep-before-pricing shows an economic transfer within the selected tolerance, not zero dilution:

| Authentic unresolved allocations | Incumbent wealth effect | Entrant wealth effect | Entrant full-roundtrip result, before wallet gas |
|---|---:|---:|---:|
| 1 | -0.002377394133252854 ETH | +0.002370543496979275 ETH | -0.011591967591048566 ETH |
| 2 | -0.002393508309942320 ETH | +0.002379284175813841 ETH | -0.011676106130900297 ETH |

The holder sizes are 73 ETH incumbent / 1 ETH entrant for one allocation, and 146 ETH / 1 ETH for two. These are genuine previously priced incumbents; the entrant’s complete result remains negative before adding wallet gas. A passed accounting test is not a claim that the ordering transfer vanishes.

## Calibration limits and recommendation

Keep this candidate unsigned and the production app gate closed. Larger-capital sample medians do not justify imposing a new minimum TVL, and four draws do not establish reliable capacity at the hurdle. A second float needs another 0.2141275 ETH of funding and buys one finite replacement opportunity; it does not create permission or income.

The cold sixteen-kick Forge logger compares frame gas 2,520,956 with only the 125,000 sync base. Actual verified allowance is 125,000 + 16×120,000 = 2,045,000 gas, plus sixteen work fees; actual compensation 0.000729 ETH exceeds that frame’s gas cost 0.0005041912 ETH at 0.2 gwei. The printed base-only UNDERPAYS label is not the payment gap. This is a Forge frame diagnostic, not a billed sixteen-kick receipt. The productive UI shared-vault one-pack build used 1,903,900 billed gas; its allowance 1,875,000 gas was lower, but work fees made total pay exceed actual gas by 0.000038554917143700 ETH at 0.050002867 gwei. Calibration does not promise every operation stays profitable.

Billed authentic-VRF renewal remains unmeasured: inserting contracts changes the historical request blockhash required by the proof. Real authenticated-proof Forge renewal traces agree with the mirror, including conditional credit funding; coordinator impersonation/receiver replacement are retired. Production-image execution passed CI run 45427099371 on commit 49da810, including fresh-fork operation and actual separate containers sharing durable storage. Encrypted-keystore/hardware-wallet transport and live Fly operation remain untested; no disposable secrets were generated.

Evidence: [frozen run](formal-assessment.json), [103 billed campaign receipts](completion-calibration.json), [production-path rehearsal](unified-production-rehearsal.json), [genuine funding trace](../../sim/out/reconcile-renewal-funding-trace.jsonl), [current fairness log](completion-checks/final-fairness-callback.log), [fresh signed-budget reorg proof](completion-signed-budget-reorg.json), [productive UI setup](completion-productive-ui-setup.json), [production image CI](completion-image.json).

## Things that do not make sense

- Positive means and a high upper-middle statistic conceal three losses in four small-capital samples. They cannot support a passing depositor-return claim.
- A finite float does not fund unlimited renewal bursts, and a 25 bps tolerance does not imply small accounts can price through unresolved allocations.
- Synthetic compression places 2,834 requests inside blackout; those abstract stress returns cannot be presented as a feasible market schedule.
- Creator fees have accrued; creator wallet withdrawals and billed authentic-VRF renewal profit have not been demonstrated.
