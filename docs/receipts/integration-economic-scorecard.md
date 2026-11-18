# Economic scorecard: position integration

**NOT ACCEPTED.** Source/evidence hash
`e2e2d2c3965d511c48587a04a135f2f8eaccdfb7d2b5dd3e218cb05e10b16895`.
All 16 regimes have zero bucket mismatches. Exact wei, bucket holdings/need/excess and outbound /
return flows are in the corresponding `flow/*.json`. ETH below is rounded to six decimals; regime
inputs differ, so only the paired short/long inactivity regimes support direct destination drift
comparison. Their allocations are identical. Main fork block is 26,424,971; selection regimes use
26,417,086 and tokens use 26,423,454. Fee values are asserted inside execution.

| Changed outcome | Measured | Existing requirement | Result |
| --- | ---: | ---: | --- |
| O2 build/list quoted gas per position | 1,919,655 | <=1,750,000 | FAIL |
| O6 spike checkpoint pay | 0.00022 ETH | <=0.0002 ETH | FAIL |
| Global journal quote at 0.5 gwei / 30d, own work excluded | >=0.3227925 ETH | mainnet budget <=0.25 ETH | 0.0727925 ETH shortfall |
| Same global work at 0.2 gwei | >=0.129117 ETH | canary budget <=0.054 ETH | 0.075117 ETH shortfall |

O1/O3-5/O7-10 remain within their recorded scenario bounds, with no new approval inferred.
Wind-down holder claim gap is 0 wei, no shares remain locked, loss is 44 bps and vault residue
is 0.010061058998589904 ETH, including 1 wei of redemption rounding reserve. The rest is the
preserved dead-share seed slice. The partial-fill mirror separately leaves 6 wei after its
complete cycle; differing rounding residue is expected from differing histories.

| Regime | Base / tx gwei | Keeper ETH | Mint fees ETH | Claimed ETH | End active |
| --- | ---: | ---: | ---: | ---: | ---: |
| init | 0.15 / 0.2 | 0.000100 | 0.000000 | 0.000000 | 0 |
| max_load | 0.15 / 0.2 | 0.012394 | 0.009000 | 0.000000 | 29 |
| inactive_short | 0.15 / 0.2 | 0.002442 | 0.002000 | 0.000000 | 5 |
| inactive_long | 0.15 / 0.2 | 0.002442 | 0.002000 | 0.000000 | 5 |
| keeper_delay | 0.15 / 0.2 | 0.002172 | 0.002000 | 0.000000 | 4 |
| gas_spike | 1.95 / 2 | 0.000220 | 0.000000 | 0.000000 | 3 |
| oracle_change | 0.15 / 0.2 | 0.001623 | 0.001000 | 0.997496 | 0 |
| withdrawals | 0.15 / 0.2 | 0.004388 | 0.003000 | 1.494557 | 7 |
| settled_unclaimed | 0.15 / 0.2 | 0.004388 | 0.003000 | 0.999947 | 10 |
| distributions | 0.15 / 0.2 | 0.000200 | 0.000000 | 0.200000 | 0 |
| wind_down | 0.15 / 0.2 | 0.003792 | 0.003000 | 1.493347 | 0 |
| acquire_bid | 0.4 / 0.45 | 0.000198 | 0.000000 | 0.000000 | 0 |
| acquire_keep | 0.4 / 0.45 | 0.000198 | 0.000000 | 0.000000 | 0 |
| acquire_silent | 0.4 / 0.45 | 0.000198 | 0.000000 | 0.000000 | 0 |
| staged_activation | 0.4 / 0.45 | 0.000695 | 0.000000 | 0.000000 | 1 |
| tokens | 0.1 / 0.15 | 0.000000 | 0.000000 | 0.000000 | 20 |

The free-cash reserve is 0.005 ETH. Final keeper reserve need is 0.0042425 ETH; one full foreign
batch at the ceiling needs 0.0002825 ETH. This covers a bounded call, not ongoing funding.
The new cost is borne by free vault ETH within routine/essential budgets. `processingPool` and
all holder liabilities remain protected. Continuous global work is required even if our own
listings are never selected. Historical annual-return estimates do not include this funding model.

Unreversed costs are mint fees, bid backing spent, settlement fees and gas; removing the trigger
does not refund them. Acquisition cursor, allocation head, epochs and redemption indexes advance
for exactly-once accounting; the high-water mark and one-way wind-down retain their owner-approved
purpose. Receipt tags retire and can be reused rather than ratcheting backing upwards.

Things that don't make sense: available reserve and balanced buckets do not imply that the
recurring maintenance budget is sufficient. O2/O6 and the historical signature cannot be treated
as approval of these new costs.
