# Personal manager economics

**Candidate evaluation, not a production recommendation or realized return.** Recipe: three paid 0.01 ETH Shapes per 0.03 ETH pack; backing 0.21 ETH. No personal-manager return hurdle has been approved.

Current mint fee: **0.0005 ETH** at block **26486686**. The 0.001 ETH cells are the historical higher-fee comparison. Activity remains the separately pinned 30-day study ending at block 26484850. No public fee transaction was sent.

48 bounded runs: 32 recorded-month, eight zero-demand and eight feasible early-burst cases. Recorded-month cells have two draws. Standard medians average the middle pair; downside and incomplete exits remain visible. All owner amounts include clone creation, owner exit and required pending-queue processing wallet gas. Operating keeper payments and fresh-mint fees are charged once to account cash.

## Recorded month: owner, keeper and creator in the same cells

Amounts are ETH over 30 operating days plus at most seven exit days. Keeper gas is a calibrated proxy. Creator amounts are gross paid primary-fee accrual, not withdrawn cash or profit after startup costs.

| Mode | Fee | Gas gwei | Funding | Exit | Owner median net | Worst | Losses | Keeper paid / gas / net | Creator gross |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fresh | 0.001 | 0.2 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00103000 / 0.00141573 / -0.00038573 | 0.00600000 |
| Fresh | 0.001 | 0.2 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.00790550 / 0.00689550 / 0.00101000 | 0.04950000 |
| Fresh | 0.001 | 0.5 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00239500 / 0.00353934 / -0.00114434 | 0.00600000 |
| Fresh | 0.001 | 0.5 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.01811375 / 0.01711375 / 0.00100000 | 0.04950000 |
| Fresh | 0.0005 | 0.2 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00103000 / 0.00141573 / -0.00038573 | 0.00300000 |
| Fresh | 0.0005 | 0.2 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.00811350 / 0.00707350 / 0.00104000 | 0.02550000 |
| Fresh | 0.0005 | 0.5 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00239500 / 0.00353934 / -0.00114434 | 0.00300000 |
| Fresh | 0.0005 | 0.5 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.01874375 / 0.01770375 / 0.00104000 | 0.02550000 |
| Reuse | 0.001 | 0.2 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00114050 / 0.00121323 / -0.00007273 | 0.00600000 |
| Reuse | 0.001 | 0.2 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.00574850 / 0.00507850 / 0.00067000 | 0.02400000 |
| Reuse | 0.001 | 0.5 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00265625 / 0.00303309 / -0.00037684 | 0.00600000 |
| Reuse | 0.001 | 0.5 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.01336625 / 0.01269625 / 0.00067000 | 0.02400000 |
| Reuse | 0.0005 | 0.2 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00123300 / 0.00129573 / -0.00006273 | 0.00300000 |
| Reuse | 0.0005 | 0.2 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.00574850 / 0.00507850 / 0.00067000 | 0.01200000 |
| Reuse | 0.0005 | 0.5 | 0.5 | 0/2 | incomplete | incomplete | 0/2 | 0.00287250 / 0.00323934 / -0.00036684 | 0.00300000 |
| Reuse | 0.0005 | 0.5 | 2 | 0/2 | incomplete | incomplete | 0/2 | 0.01336625 / 0.01269625 / 0.00067000 | 0.01200000 |

## Quiet use and feasible early burst

The burst repeats the busiest actual request day twice at whole-day offsets, retains authentic completion delays and blackout phase, and then stops requests. Tight permission uses a 0.004 ETH routine cap with zero refill. Wait counts are planner observations, not distinct transactions or an elapsed-time claim.

| Regime | Mode | Fee | Gas | Owner median net | Worst | Exit | Keeper paid / gas / net | Creator gross | Wait observations |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| zero-demand | Fresh | 0.001 | 0.2 | -0.00389051 | -0.00389051 | 1/1 | 0.00041500 / 0.00088073 / -0.00046573 | 0.00300000 | none |
| zero-demand | Fresh | 0.001 | 0.5 | -0.00516628 | -0.00516628 | 1/1 | 0.00097750 / 0.00220184 / -0.00122434 | 0.00300000 | none |
| zero-demand | Fresh | 0.0005 | 0.2 | -0.00239051 | -0.00239051 | 1/1 | 0.00041500 / 0.00088073 / -0.00046573 | 0.00150000 | none |
| zero-demand | Fresh | 0.0005 | 0.5 | -0.00366628 | -0.00366628 | 1/1 | 0.00097750 / 0.00220184 / -0.00122434 | 0.00150000 | none |
| zero-demand | Reuse | 0.001 | 0.2 | -0.00723351 | -0.00723351 | 1/1 | 0.00075800 / 0.00088073 / -0.00012273 | 0.00600000 | none |
| zero-demand | Reuse | 0.001 | 0.5 | -0.00896378 | -0.00896378 | 1/1 | 0.00177500 / 0.00220184 / -0.00042684 | 0.00600000 | none |
| zero-demand | Reuse | 0.0005 | 0.2 | -0.00423351 | -0.00423351 | 1/1 | 0.00075800 / 0.00088073 / -0.00012273 | 0.00300000 | none |
| zero-demand | Reuse | 0.0005 | 0.5 | -0.00596378 | -0.00596378 | 1/1 | 0.00177500 / 0.00220184 / -0.00042684 | 0.00300000 | none |
| early-burst-then-zero | Fresh | 0.0005 | 0.2 | incomplete | incomplete | 0/1 | 0.01376100 / 0.01234647 / 0.00141453 | 0.04200000 | RENEWAL_CASH_SHORT: 40655 |
| early-burst-low-permission | Fresh | 0.0005 | 0.2 | incomplete | incomplete | 0/1 | 0.00396000 / 0.00346000 / 0.00050000 | 0.01200000 | RENEWAL_PERMISSION_SHORT: 42329 |
| early-burst-then-zero | Fresh | 0.0005 | 0.5 | incomplete | incomplete | 0/1 | 0.03167250 / 0.03086617 / 0.00080633 | 0.04200000 | RENEWAL_CASH_SHORT: 40655 |
| early-burst-low-permission | Fresh | 0.0005 | 0.5 | 0.14809241 | 0.14809241 | 1/1 | 0.00377250 / 0.00359250 / 0.00018000 | 0.00600000 | RENEWAL_PERMISSION_SHORT: 42328 |
| early-burst-then-zero | Reuse | 0.0005 | 0.2 | incomplete | incomplete | 0/1 | 0.01022160 / 0.00920433 / 0.00101727 | 0.01500000 | none |
| early-burst-low-permission | Reuse | 0.0005 | 0.2 | incomplete | incomplete | 0/1 | 0.00384600 / 0.00336600 / 0.00048000 | 0.01200000 | none |
| early-burst-then-zero | Reuse | 0.0005 | 0.5 | incomplete | incomplete | 0/1 | 0.02372400 / 0.02301084 / 0.00071316 | 0.01500000 | none |
| early-burst-low-permission | Reuse | 0.0005 | 0.5 | 0.14809241 | 0.14809241 | 1/1 | 0.00377250 / 0.00359250 / 0.00018000 | 0.00600000 | none |

## First productive opening

Account cash needed for the first pack includes 0.24 ETH face plus backing, actual paid mint fees, the quoted build payment, maintenance reserve and conservative renewal float. Owner clone-creation wallet gas is additional. Accepted maximum remains 0.001 ETH per mint in both fee cases; lower actual fees do not silently release the conservative float.

| Mode | Actual fee | Gas gwei | Account funding | Float included |
|---|---:|---:|---:|---:|
| Fresh | 0.0005 | 0.2 | 0.46104250 | 0.21412750 |
| Fresh | 0.0005 | 0.5 | 0.46160500 | 0.21412750 |
| Fresh | 0.001 | 0.2 | 0.46254250 | 0.21412750 |
| Fresh | 0.001 | 0.5 | 0.46310500 | 0.21412750 |
| Reuse | 0.0005 | 0.2 | 0.24691500 | 0.00000000 |
| Reuse | 0.0005 | 0.5 | 0.24747750 | 0.00000000 |
| Reuse | 0.001 | 0.2 | 0.24841500 | 0.00000000 |
| Reuse | 0.001 | 0.5 | 0.24897750 | 0.00000000 |

## Interpretation and limits

Retain manager.json as a candidate. Two paths per baseline cell cannot establish an expected return or justify changing the owner’s settings. Fresh renewal pays for three new mints after each acquisition and retains its designated float; reuse relists returned inventory. A manager has one owner and no share-pricing uncertainty gate, checkpoint charges, dead shares or depositor refunds.

Owner-funded final maintenance bypasses keeper-profit selection, pays no keeper reward and is charged to the owner wallet. Cash availability and spending permission remain separate. Recorded ordinary VRF/processing is funded by historical external actors; pending queue work required at exit carries a conservative owner reserve, charging a full measured single-request processing call per pending record in batches of at most 16. This is a gas reserve, not a claim those archived events were replayed as new owner receipts.

Unmeasured gas operations: renew, standalone-harvest. Where a quoted allowance substitutes for a billed receipt, keeper net is a proxy and may differ from inclusion costs. Global factory deployment and production service costs are one-time operator costs outside per-clone owner returns. Primary fees accrue to the Shapes creator and are not creator net profit.

All numerical scenario results are conditional on the matched real-fork manager transitions and the frozen receipt/proxy inputs. The archive’s foreign weights and buyer behavior do not react to the manager. Fee and gas cases can follow different paths, so differences across two draws are not causal estimates of a fee change. Prior pooled-vault evidence is preserved separately.

Things that don’t make sense: a profitable keeper quote or a fully balanced ledger does not establish positive owner returns; unresolved gas measurements and the two-draw sample limit any stronger conclusion.
