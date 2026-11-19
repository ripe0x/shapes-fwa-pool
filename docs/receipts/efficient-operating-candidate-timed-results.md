# Candidate focused timed comparison

**Three of four conditional exits complete; only the zero-demand case has fully paid routine work.** Timely and late completed exits include holder-paid, underfunded harvest calls. `holder_rescue_sync=False` forbids unpaid synchronization, but still permits caller-paid necessary harvest and other exit work. These are distinct from fully funded operation.

Candidate quote: 22,000 gas per global record, 110,000 required holder tail base, and 80,000 extra only for a verified distribution-only proof; sync base 85,000 and pack quote 325,000 remain unchanged. This run has no transactions and does not authorize candidate broadcasts.

Four conditional paths use 6.8 ETH principal, two operating days and at most two exit days, seed 8, 0.2 gwei total price, and 609 successful global selections/day plus the recorded refund ratio in busy cases. The 0.3 ETH routine cap and 0.01 ETH/day refill are model proposals within existing maxima, funded from vault cash. No sponsor, donation or mint-revenue recycling is assumed.

| Path | Completed exit | Fully paid routine | Holder underpaid harvest calls | Holder underpaid sync calls | Gross received fees ETH | Harvest payments ETH |
|---|---:|---:|---:|---:|---:|---:|
| zero | 1 | 1 | 0 | 0 | 0.000000000000000000 | 0.000000000000000000 |
| timely | 1 | 0 | 44 | 0 | 1.819168941380021572 | 0.266081233333330390 |
| silent | 0 | 0 | 45 | 0 | 1.916686416113682250 | 0.270435433333330427 |
| late | 1 | 0 | 45 | 0 | 1.862151985294759769 | 0.258901433333330410 |

All four modeled asset ledgers and independent external-fee ledgers have zero wei gaps. Exact assertion: `external_fees_generated_wei == fees_received_wei + unharvested_fee_credit_wei + unharvested_listing_fees_wei`. Every harvest clears its chosen listing pending fees and all claimed fee credit once. This proves accounting on these hypothetical paths, not authentic external timing or profitability.

| Candidate versus prior Q30 path | Prior underpaid holder harvest calls | Candidate underpaid holder harvest calls | Prior gross received fees ETH | Candidate gross received fees ETH | Prior harvest payments ETH | Candidate harvest payments ETH |
|---|---:|---:|---:|---:|---:|---:|
| zero | 0 | 0 | 0.000000000000000000 | 0.000000000000000000 | 0.000000000000000000 | 0.000000000000000000 |
| timely | 30 | 44 | 1.796011982853566498 | 1.819168941380021572 | 0.264933499999997087 | 0.266081233333330390 |
| silent | 30 | 45 | 1.888010087907315034 | 1.916686416113682250 | 0.269266499999997100 | 0.270435433333330427 |
| late | 30 | 45 | 1.836258194008872585 | 1.862151985294759769 | 0.258243499999997078 | 0.258901433333330410 |

Precision correction for the immutable prior Q30 report: timely gross fees are exactly **1.796011982853566498 ETH**, with harvest payments exactly **0.264933499999997087 ETH**. Its timely and late completed exits each include 30 underpaid holder harvest calls. The earlier prose used floating-point formatting and rounded these amounts; the integer raw evidence remains unchanged.

The candidate timely path makes 990 harvest calls over 15813 membership harvests, with up to 198 harvests before a membership's selection. Its gross fee income and expense remain materially different from once-per-cycle `CYCLE_GAS` economics. A quarter-of-realized-fees cap can exceed the strategy's net edge because gross fee income also compensates backing transferred to purchasers. Lower journal quotes do not resolve that operating-expense question.


Holder cash and caller funding remain separate from vault expenses. These gas amounts are historical/quote proxies, not candidate receipt measurements.

| Path | Actual modeled holder claims ETH | Holder keeper compensation ETH | Holder gas proxy ETH | Creator mint fees ETH |
|---|---:|---:|---:|---:|
| zero | 6.736078115741484541 | 0.000000000000000000 | 0.008965345400000000 | 0.027000000000000000 |
| timely | 6.664858448970310011 | 0.000303233333330390 | 0.020276345400000000 | 0.027000000000000000 |
| silent | 0.000000000000000000 | 0.000429433333330427 | 0.020263209600000000 | 0.036000000000000000 |
| late | 6.916627315629240453 | 0.000429433333330410 | 0.020933568200000000 | 0.035000000000000000 |

## Scope and limitations

- The request/completion and purchaser-response times are explicit conditional scenarios. Ambiguous settlement logs are not treated as authenticated purchaser delays.

- The driver uses 3,600-second reclaim eligibility, 12-hour intervals, a final-15-minute blackout, 60-second configured polls, and at most 40 calls/pass. Purchasers may act after expiry until keeper reclaim wins.

- Actions take effect at a modeled fresh read; the next confirmed read is delayed 36 seconds. This optimistic inclusion assumption omits variable block timing and reverted races at boundaries.

- The foreign pool remains a recorded static snapshot. Fee/selection calculations approximate the counterfactual external market. NFT expiry reclaim remains implemented but unexecuted by these accepted-backing scenarios.

- User-call gas inputs are labeled historical Q400 billed counts; unexposed synchronization uses the caller-meter-plus-intrinsic proxy, and other unpaid maintenance uses quote gas proxies. They are not current candidate billed receipts.

- No full matrix, forced build, chain reads or transactions occurred. The shared checks include one focused legacy partial-redemption regression, not a new legacy matrix.

- Raw `ret` remains the legacy annualized calculation for compatibility. It is never presented as achieved or expected annual return. These results establish neither a forecast, an annual acceptance result nor a budget recommendation.

## Things that don't make sense

- A completed holder exit can depend on underpaid routine harvest work; completion must not be labeled fully funded operation.

- Gross-fee spending caps and exact conservation do not establish that the strategy retains an acceptable net return.
