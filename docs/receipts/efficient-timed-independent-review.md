# Independent review of the conditional timed model

What this change does: adds an opt-in event calendar around the existing integer vault book and policy executor. This review reads source and archived JSON only; it runs no model, tests or chain actions. It is separate from the approved transaction batch, and establishes neither release readiness nor expected returns.

**Conclusion:** I found no concrete clock-ordering or duplicate fee-recognition defect in the reviewed paths. The repeated harvest expense is a real consequence of the policy **within these conditional executions**, rather than fees counted twice. Completed exits must still be distinguished from fully funded keeper operation.

## Reviewed inputs

- `sim/forward.py`: `d34620fcd7932c3eaad03abd78a7f4d806510ca7af442cce7b93d5da43486562`.
- `sim/efficient_operating.py`: `027df41dfb2e6d9153c465351863ca4fa3af95afb89a50ac3491e1e847832e90`.
- Unchanged financial core `sim/vault.py`: `e958d86859ff9ddd9e2766459683f77cf9caea9ac87691be6360d2e92614ba7a`; policy: `cba78633858db621b48bf729571673f84693e503d6d49eecda0cb905730703a2`.
- Timed checks JSON: `bf860d925beceb90fe5a3198474d15818d31d5342c1d963396f76b87d5c7f481`; results JSON: `b02e39b36824405daff795ee4861d871ea0962ff5103943bf149ba54a42c6321`, plus their text/Markdown companions. These hashes matched during review.

## Timing and accounting

The calendar uses 3,600-second expiry eligibility, 43,200-second intervals and the final 900-second blackout. It moves new blackout requests to the next opening, allows their later completions, and blocks pricing until the modeled request queue drains. The keeper waits 36 seconds after a successful action, re-reads, and polls after 60 seconds when idle or after 40 calls. Action effects occur at the read, **before** that confirmation delay, so boundary inclusion remains optimistic.

Responses and market events precede keeper reads on timestamp ties. A purchaser can respond after expiry while status remains allocated; an executed reclaim removes that possibility. Silent positions become expired without magically transferring assets. Recorded redemptions occur exactly 172,800 seconds after scenario start. The 3,599/3,600 boundary check is a policy projection of an authentic position, not a new timed fork execution.

The timed branch keeps financial mutations in the existing integer book. External fee generation and weighted selection remain explicit floating-point scenario approximations before conversion to wei. Stored asset gaps and generated-fee conservation gaps are zero in all four cases. I independently summed the archived harvest amounts; pending balances and credit are cleared after collection, selection moves only remaining pending fees into credit, and checkpoints clear collected credit.

## Economic interpretation

All cases use 6.8 ETH principal, two operating days, at most two exit days, 0.2 gwei total price, seed 8, and proposed routine permission of 0.3 ETH plus 0.01 ETH/day.

| Scenario | Exit complete | Fully paid routine operation | Underpaid holder harvest calls | Holder maintenance gas proxy, ETH |
|---|---:|---:|---:|---:|
| Zero activity | Yes | Yes | 0 | 0.008883 |
| Timely purchaser | Yes | No | 30 | 0.016265 |
| Silent purchaser | No | No | 30 | 0.015836 |
| Late purchaser | Yes | No | 30 | 0.016344087 |

`rescue_sync=False` disables the extra sync rescue, **not** holder fallback for harvest, unlist or liquidation. Essential compensation is zero here. These maintenance proxies are personal caller costs outside vault NAV; holder compensation is added back separately. Fixed user-call proxies derive from historical receipts, variable maintenance from quotes. They are not fresh billed costs or funded-exit proof.

The timely trace contains 972 distinct harvest calls and 15,529 membership-harvest occurrences. Their amounts sum to exactly **1.796011982853566498 ETH** received; vault harvest compensation totals **0.264933499999997087 ETH**, or **14.751210%** of gross fees. Membership 8 is cleared at 195 different timestamps before selection, receiving 0.015504676819132035 ETH across those harvests. Its repeated 80,000-gas marginal quotes alone equal 0.00312 ETH at this price. The policy repeatedly becomes eligible after fresh accrual, so a once-per-cycle harvest charge misses this expense. Real keeper estimates, profitability decisions and inclusion are not simulated; the quoted expense is conditional on successful execution.

## Remaining evidence and reporting gaps

- Same-day listing is permitted without the legacy daily delay. The assertion only finds a listing after a purchaser response on the same day; traces do not retain pack identity to prove that specific returned pack's relist and later reselection. Do not describe this as an identity-linked round-trip regression.
- The results Markdown rounds the timely fee and compensation figures 60 wei and 15 wei away from the exact JSON values above. This is a presentation discrepancy, not a detected accounting gap.
- Raw timed rows inherit the legacy annualized `ret` field. It is neither a short-period realized-return field nor an accepted forecast, especially for the unfinished silent exit. Use the explicit realized cash/caller-cost fields and completion flags.
- Static foreign inventory, generated VRF timing/selection, fixed purchaser delays, optimistic inclusion, unreached NFT-reclaim expiry and the authentic prepriced-holder cash-cycle gap remain disclosed limitations. Existing fork reconciliation validates only its executed paths.

## Things that don't make sense

- A percentage-of-gross harvest cap can authorize repeated spending that overwhelms net strategy income; exact fee conservation does not resolve that economic problem.
- A completed conditional exit can still require personal holder labor and gas while routine funding repeatedly fails. It cannot justify the proposed allowance or establish sustainable returns.
