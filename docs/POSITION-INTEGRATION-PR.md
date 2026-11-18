# Remove the position ceiling with incremental production accounting

PackVault prices one authoritative book of exact inventory, active backing, fee debt, allocations
and authenticated receipts. It removes the 300-position ceiling and portfolio valuation scans.
Maintenance and ordinary keeper reads are bounded; the keeper reconstructs candidates in SQLite.
Paid primary mints, the mint/split/pack recipe, pack sizing and protected holder liabilities remain.

An owner-approved completeness refinement advances past completed history without journal pay
only when onchain state proves no outstanding FWA exposure. Checkpoint and first admission share
that proof. This prevents irrelevant global work from exhausting the minimum seed before the
first deposit. Exposure, including OWED custody and pending receipts, retains ordered processing.

The production image installs pinned Python dependencies and the Ethereum Keccak backend. Both
transaction state and SQLite now use the mounted `/data` directory. Checkpoint's gas component is
calibrated to 360,000, meeting O6's existing limit. No journal quote, budget, reserve, accepted
outcome or owner signature was changed during these repairs.

## Verification

- Real old-source reproduction: 673 foreign records exhausted 0.010000000000000001 ETH and caused
  first-deposit division by zero. Repaired source passes three bootstrap and five real
  exposure/admission regressions, including the actual mutating checkpoint gate.
- Refreshed exact receiver: 46,462 gas keep / 69,730 difficult kick; 99 sampled low-gas attempts
  record or fail atomically. Both fresh fork traces reconcile every financial bucket to the wei.
- Actual production Docker image builds and starts; transaction state and index head survive
  separate containers sharing `/data`. [Isolated verification job](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/44393965532).
  This does not claim a live Fly machine replacement.
- Eleven Python accounting tests, keeper policy checks and seven focused forward scenarios pass.
  Refreshed asset-flow scenarios retain O2's failure and meet O6's unchanged 0.0002 ETH limit.
- Approved local calibration completed in **77/80 transactions**, using 1.7559/3 simulated ETH
  aggregate transaction value. Real refunded prefixes/tails and a complete exposed backlog exit
  have billed receipts on the preceding Q400 source. Six exit calls cost **0.0003838206 ETH** at
  0.2 gwei, with **0.0001 ETH** checkpoint pay; other essential exit work paid zero.
- Current runtime: **24,322 / 24,576 bytes**, 254 spare; linked library 21,313 bytes.

The earlier candidate's 52 affected checks, 301 real listings, 1,000/10,000 bookkeeping-position
models and quiet local lifecycle remain archived evidence for their exact inputs. They were not
rerun as broad release verification of this repair. New source hashes, commands, preserved failures
and limits are in the [acceptance report](docs/POSITION-INTEGRATION-ACCEPTANCE.md).

## Things that don't make sense

| Observation | Consequence |
| --- | --- |
| Exposed vaults pay for all global FWA history. | The recorded 18,281 entries require at least **0.3227925 ETH / 30 days at 0.5 gwei**, versus **0.25 ETH** mainnet permission, before own work. Canary needs **0.129117 ETH at 0.2 gwei** versus **0.054 ETH** permission. Empty-vault rebasing removes this cost only while provably unexposed. |
| Budget permission provides no cash. | Global-only refill need **0.01075975 ETH/day** exceeds the configured **0.005** and hard maximum **0.01**. The funding proposal distinguishes actual cash, harvested income and allowances. |
| Balanced books still fail O2. | **1,919,655 vs 1,750,000 quoted gas/position.** Perfect batching still leaves 1,810,000 marginal quoted build/list gas. O6 is now **0.0002 ETH**, meeting its existing limit; actual billed full-holder calibration remains a release evidence gap. |
| The journal schedule poorly matches batch costs. | A refunded singleton bills **112,515 vs 115,000 quoted gas**; sixteen bill **361,632 vs 565,000**. A larger base can reward splitting. Successful-foreign billed small/full/tail costs are still missing, so journal quotes remain unchanged. |
| Essential budgets are zero while exposed exits require foreign catchup. | The measured caller-funded exit includes unrelated refunded history despite routine allowance remaining. Its gas cost exceeds checkpoint compensation by **0.0002838206 ETH**. |
| FWA's drained request queue can retain foreign staging. | Incidental foreign activation reverts admission atomically. Another actor must clear staging before listing can resume. |

[Funding and return proposal](docs/REVIEW-FUNDING-PROPOSAL.md) includes eight illustrative 30-day
regimes with absolute costs, cash and holder marks. Positive marked value does not establish
continuous keeper operation or realized returns. Historical annual-return claims remain historical.

**Keep this PR draft.** Funding, complete journal calibration and O2 remain acceptance blockers.
Focused independent repair review is not a full security audit or release approval. No public
network transaction, real-fund spending, owner signature or merge is included.
