# Personal manager economics

**Candidate evaluation, not a production recommendation or realized return.** Recipe: three paid 0.01 ETH Shapes per 0.03 ETH pack; backing 0.21 ETH. No personal-manager return hurdle has been approved.

Current mint fee: **0.0005 ETH** at block **26486686**. The 0.001 ETH cells are the historical higher-fee comparison. Activity remains the separately pinned 30-day study ending at block 26484850. No public fee transaction was sent.

48 bounded runs: 32 recorded-month, eight zero-demand and eight feasible early-burst cases. Recorded-month cells have two draws. Standard medians average the middle pair; downside and incomplete exits remain visible. All owner amounts include clone creation, owner exit and required pending-queue processing wallet gas. Operating keeper payments and fresh-mint fees are charged once to account cash.

## Recorded month: owner, keeper and creator in the same cells

Amounts are ETH over 30 operating days plus at most seven exit days. Keeper gas is a calibrated proxy. Creator amounts are gross paid primary-fee accrual, not withdrawn cash or profit after startup costs.

| Mode | Fee | Gas gwei | Funding | Exit | Owner median net | Worst | Losses | Keeper paid / gas / net | Creator gross |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Fresh | 0.001 | 0.2 | 0.5 | 2/2 | -0.14542343 | -0.28041736 | 2/2 | 0.00103000 / 0.00091923 / 0.00011077 | 0.00600000 |
| Fresh | 0.001 | 0.2 | 2 | 2/2 | -0.44615788 | -0.65872138 | 2/2 | 0.00790550 / 0.00689550 / 0.00101000 | 0.04950000 |
| Fresh | 0.001 | 0.5 | 0.5 | 2/2 | -0.14722769 | -0.28208287 | 2/2 | 0.00239500 / 0.00229807 / 0.00009693 | 0.00600000 |
| Fresh | 0.001 | 0.5 | 2 | 2/2 | -0.45767788 | -0.67085836 | 2/2 | 0.01811375 / 0.01711375 / 0.00100000 | 0.04950000 |
| Fresh | 0.0005 | 0.2 | 0.5 | 2/2 | -0.14242343 | -0.27741736 | 2/2 | 0.00103000 / 0.00091923 / 0.00011077 | 0.00300000 |
| Fresh | 0.0005 | 0.2 | 2 | 2/2 | -0.41575859 | -0.63320538 | 2/2 | 0.00811350 / 0.00707350 / 0.00104000 | 0.02550000 |
| Fresh | 0.0005 | 0.5 | 0.5 | 2/2 | -0.14422769 | -0.27908287 | 2/2 | 0.00239500 / 0.00229807 / 0.00009693 | 0.00300000 |
| Fresh | 0.0005 | 0.5 | 2 | 2/2 | -0.42772558 | -0.64531836 | 2/2 | 0.01874375 / 0.01770375 / 0.00104000 | 0.02550000 |
| Reuse | 0.001 | 0.2 | 0.5 | 2/2 | -0.07104450 | -0.24837361 | 1/2 | 0.00114050 / 0.00101050 / 0.00013000 | 0.00600000 |
| Reuse | 0.001 | 0.2 | 2 | 2/2 | -0.27067354 | -0.30256310 | 2/2 | 0.00574850 / 0.00507850 / 0.00067000 | 0.02400000 |
| Reuse | 0.001 | 0.5 | 0.5 | 2/2 | -0.07306626 | -0.25006660 | 1/2 | 0.00265625 / 0.00252625 / 0.00013000 | 0.00600000 |
| Reuse | 0.001 | 0.5 | 2 | 2/2 | -0.27956652 | -0.31156408 | 2/2 | 0.01336625 / 0.01269625 / 0.00067000 | 0.02400000 |
| Reuse | 0.0005 | 0.2 | 0.5 | 2/2 | -0.00651224 | -0.24537361 | 1/2 | 0.00123300 / 0.00109300 / 0.00014000 | 0.00300000 |
| Reuse | 0.0005 | 0.2 | 2 | 2/2 | -0.25867354 | -0.29056310 | 2/2 | 0.00574850 / 0.00507850 / 0.00067000 | 0.01200000 |
| Reuse | 0.0005 | 0.5 | 0.5 | 2/2 | -0.00867623 | -0.24706660 | 1/2 | 0.00287250 / 0.00273250 / 0.00014000 | 0.00300000 |
| Reuse | 0.0005 | 0.5 | 2 | 2/2 | -0.26756652 | -0.29956408 | 2/2 | 0.01336625 / 0.01269625 / 0.00067000 | 0.01200000 |

## Quiet use and feasible early burst

The burst repeats the busiest actual request day twice at whole-day offsets, retains authentic completion delays and blackout phase, and then stops requests. Tight permission uses a 0.004 ETH routine cap with zero refill. Wait counts are planner observations, not distinct transactions or an elapsed-time claim.

| Regime | Mode | Fee | Gas | Owner median net | Worst | Exit | Keeper paid / gas / net | Creator gross | Wait observations |
|---|---|---:|---:|---:|---:|---:|---:|---:|---|
| zero-demand | Fresh | 0.001 | 0.2 | -0.00374034 | -0.00374034 | 1/1 | 0.00041500 / 0.00038423 / 0.00003077 | 0.00300000 | none |
| zero-demand | Fresh | 0.001 | 0.5 | -0.00479086 | -0.00479086 | 1/1 | 0.00097750 / 0.00096057 / 0.00001693 | 0.00300000 | none |
| zero-demand | Fresh | 0.0005 | 0.2 | -0.00224034 | -0.00224034 | 1/1 | 0.00041500 / 0.00038423 / 0.00003077 | 0.00150000 | none |
| zero-demand | Fresh | 0.0005 | 0.5 | -0.00329086 | -0.00329086 | 1/1 | 0.00097750 / 0.00096057 / 0.00001693 | 0.00150000 | none |
| zero-demand | Reuse | 0.001 | 0.2 | -0.00716866 | -0.00716866 | 1/1 | 0.00075800 / 0.00067800 / 0.00008000 | 0.00600000 | none |
| zero-demand | Reuse | 0.001 | 0.5 | -0.00880165 | -0.00880165 | 1/1 | 0.00177500 / 0.00169500 / 0.00008000 | 0.00600000 | none |
| zero-demand | Reuse | 0.0005 | 0.2 | -0.00416866 | -0.00416866 | 1/1 | 0.00075800 / 0.00067800 / 0.00008000 | 0.00300000 | none |
| zero-demand | Reuse | 0.0005 | 0.5 | -0.00580165 | -0.00580165 | 1/1 | 0.00177500 / 0.00169500 / 0.00008000 | 0.00300000 | none |
| early-burst-then-zero | Fresh | 0.0005 | 0.2 | 0.37965615 | 0.37965615 | 1/1 | 0.01376100 / 0.01194100 / 0.00182000 | 0.04200000 | RENEWAL_CASH_SHORT: 40655 |
| early-burst-low-permission | Fresh | 0.0005 | 0.2 | 0.41228089 | 0.41228089 | 1/1 | 0.00396000 / 0.00346000 / 0.00050000 | 0.01200000 | RENEWAL_PERMISSION_SHORT: 42329 |
| early-burst-then-zero | Fresh | 0.0005 | 0.5 | 0.36000366 | 0.36000366 | 1/1 | 0.03167250 / 0.02985250 / 0.00182000 | 0.04200000 | RENEWAL_CASH_SHORT: 40655 |
| early-burst-low-permission | Fresh | 0.0005 | 0.5 | 0.14809241 | 0.14809241 | 1/1 | 0.00377250 / 0.00359250 / 0.00018000 | 0.00600000 | RENEWAL_PERMISSION_SHORT: 42328 |
| early-burst-then-zero | Reuse | 0.0005 | 0.2 | 0.25516592 | 0.25516592 | 1/1 | 0.01022160 / 0.00900160 / 0.00122000 | 0.01500000 | none |
| early-burst-low-permission | Reuse | 0.0005 | 0.2 | 0.48055149 | 0.48055149 | 1/1 | 0.00384600 / 0.00336600 / 0.00048000 | 0.01200000 | none |
| early-burst-then-zero | Reuse | 0.0005 | 0.5 | 0.24006353 | 0.24006353 | 1/1 | 0.02372400 / 0.02250400 / 0.00122000 | 0.01500000 | none |
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

Lead evidence note: raw modeled paid-operation flags additionally include list and sync at unmeasured call sizes. Their keeper gas and margins use allowances, not matched billed curves. The optional pending-prefix processing reserve can overstate owner work when its own book is already empty; full single-request gas per record is a conservative cost reserve, and ceil(N/16) is an ideal batch count rather than a guaranteed number of calls. No fine-margin or causal conclusion follows from those proxies.
