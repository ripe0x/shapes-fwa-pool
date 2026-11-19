# Focused timestamp operating model

The new mode uses actual 3600 second reclaim eligibility, 12 hour intervals, 15 minute blackout and configured 60 second polling with 40 calls/pass. It shares the existing Vault accounting and action executor. Legacy daily runs remain the default and their archived outputs are unchanged. These are conditional scenarios, not actual counterparty transactions or return/budget acceptance.

Four scenarios use 6.8 ETH principal, 2 operating days, at most 2 exit days, seed 8 and 0.2 gwei total price. Busy cases use 609 successful global selections/day plus the recorded refund ratio. Routine 0.3 ETH cap/0.01 ETH daily refill are model proposals only; no deployment setting changes.

| Conditional purchaser behavior | Complete exit | Backing reclaims | Purchaser responses | Late responses | Ledger gaps |
|---|---:|---:|---:|---:|---:|
| zero | 1 | 0 | 0 | 0 |0 wei assets and external fees |
| timely | 1 | 0 | 35 | 0 |0 wei assets and external fees |
| silent | 0 | 37 | 0 | 0 |0 wei assets and external fees |
| late | 1 | 23 | 15 | 15 |0 wei assets and external fees |

Requests are generated during open periods and complete 60 seconds later; no requests begin in blackout. Purchaser choices are explicit conditional 120 second, absent, or 7200 second responses. A late purchaser can still act after expiry if the keeper has not reclaimed first. Event ties process market events before a keeper fresh read. Actions take effect atomically at that read;36 seconds pass before the next confirmed read. This optimistic inclusion model does not reproduce onchain races, variable latency or reverts near boundaries.

Each expired allocated position remains external exposure until an affordable synchronization call executes the actual economic reclaim choice. Reclaimed backing can fund the same synchronization call. `Position.expired` blocks pricing until required resolution. Redemption is requested at the exact 2 day cutoff, and actual modeled claims execute when payable.

## Repeated harvest expense

The timely scenario receives 1.796011982853566558 ETH fee income and pays 0.264933499999997102 ETH across 972 harvest calls, about 14.75% of gross fees. All harvested amounts sum exactly to received income; generated external fees also equal received plus unharvested balances. Pending listing fees and credit are cleared once.

Conditional membership 8 is harvested 195 times before selection. Its realized pending fees total 0.015504676819132035 ETH. The repeated 80000 gas-equivalent marginal component alone is 15600000 quoted gas, or 0.00312 ETH at 0.2 gwei, before shared bases. These are quote/payment and model amounts, not measured EVM gas. The once-per-cycle `CYCLE_GAS` assumption does not capture this frequency. This is an economic blocker for further evaluation, not an authorization to change harvest scheduling or compensation.

## Verification and limits

The authentic fixture allocation timestamps establish 1429 seconds versus 37213 seconds until blackout. The existing real-fork silent-purchaser test establishes the backing-reclaim asset path; the focused driver crosses a real recorded position’s 3599/3600 second policy boundary. The accounting core’s separate fresh fork reconciliation remains scoped to its executed paths. This does not establish an authentic timed full-holder run or the cash-cycle finding.

The legacy half-redemption regression matches all 115 previously archived fields exactly. Python compilation and owned diff checks pass. No full matrix was run. NFT reclaim after expiry is implemented but not reached under these accepted-backing scenarios; no low-backing protocol fixture was fabricated.

- Conditional generated request/completion times and purchaser choices are scenario assumptions, not real VRF replay or observed purchaser response behavior.
- Effects occur atomically at the fresh modeled read;36 seconds delay the next receipt-confirmed read. This optimistic inclusion assumption does not model fees, reverted races, variable block time or transaction latency across a boundary.
- At exact timestamp ties, market events precede keeper reads. Purchasers may respond after 3600 seconds until reclaim wins; expiry itself does not transfer assets.
- Static recorded foreign pool and per-completion fee/selection approximation remain. Successful journal compensation and keeper profitability still require separate actual receipts/preflight.
- NFT-reclaim expiry branch is implemented but not reached by these accepted-backing scenarios; no fabricated low-backing protocol fixture is supplied.
- These short conditional paths validate clock/accounting interactions. They do not reproduce the prepriced-holder cash-cycle or establish recommended budget, expected returns or annual acceptance.

## Things that don't make sense

- A gross-fee spending cap can exceed net strategy income. The keeper can repeatedly harvest the same active membership before it is selected.

- Timed accounting conservation still cannot establish realistic counterparty behavior or an acceptable budget.
