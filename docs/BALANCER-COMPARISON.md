# What the vault took from shapes-pool-balancer

Compared at shapes-pool-balancer `05e6b60` (main) and this repository after `ae8fc54`. The two
products solve different problems: the balancer keeps a creator's prize board stocked and folds
keeper costs into player prices; the vault deploys holders' ETH into FWA listings and pays every
cost from its own earnings. Decisions D45 to D50.

| Area | Balancer | Vault before | Decision | Why | Cost |
|---|---|---|---|---|---|
| Keeper language | TypeScript/viem, one call (`performUpkeep`) whose simulation returns the reward | Python, many calls chosen by `policy.py`, which the simulation imports | **Adapted**: port the transaction design to Python (`keeper/tx.py`) | keeps one policy for keeper and simulation; the balancer code is a class, not a library | two implementations of the same design (about 250 lines here) |
| Persistent pending tx, saved before broadcast | yes (JSON state, atomic write) | none: `cast send` blocked per call | **Adopted** | restarts and lost responses never send work twice at a new nonce | a state file to keep |
| Same-nonce replacement | +25% after 3 blocks, 5 at most, under a cap, while still profitable | none | **Adopted**, also only while the call still preflights | stuck calls clear without duplicates | none |
| Lost response | entry kept; next tick waits or replaces | n/a | **Adopted + extended**: look the nonce up in recent blocks and count it if it was ours | accounting stays exact | block scan of up to 50 blocks, rarely |
| Profit check | reward from simulation + `MAX_LOSS_WEI` vs estimate x price | policy only | **Adapted**: expected pay from the vault's formula on the estimate; `--max-loss-wei` applies only above the ceiling | the vault's calls do not return their pay; below the ceiling pay exceeds cost by construction (measured +6% to +20%) | none |
| Receipt reconciliation | `KeeperPaid` event per receipt, spent/earned stats | printed gas and cost | **Adopted** | keeper P&L from receipts; rehearsal matches the chain to the wei | none |
| Reorgs | re-scan factory events over 64 blocks | none needed (stateless) | **Adapted**: counted receipts re-checked for 64 blocks | the keeper's books undo a reorged call; decisions already re-read chain state | one receipt read per recent call |
| Concurrency | one in-flight tx per pool; duplicates revert in simulation | none | **Adopted**: one in-flight tx per keeper, file lock per state file, preflight skips work already done | no double sends from one key; other keepers are harmless | none |
| Health | `/health` 200/503, errors per pool | none | **Adopted** plus `--status` and status codes | monitoring without a dashboard | none |
| Status codes | on-chain `admissionStatus()` | none | **Adapted**: computed by the keeper from chain state (14 codes, wait vs action) | no contract change; the vault has no admission gate to report | the keeper, not the chain, is the source |
| Fixed keeper reward (0.0001 ETH per call) | yes, priced into draws | 10% premium on measured gas | **Adapted** (D55): a flat fee per unit of work (0.00002 ETH canary, 0.0001 maximum), not per call | outside keepers need an absolute margin at low gas; per-unit pay cannot be farmed by splitting | about 0.1% of deposits over the canary lifecycle with no acquisitions; about 3% of the edge per bid cycle |
| Restocking fee in prices | yes | n/a | **Rejected** | no player price exists | none |
| Gas threshold per operation | one 5 gwei cap | one ceiling; keeper idle above it | **Adapted** (D45): liability work only above the ceiling; build below ~0.54, relist below the ceiling, both under the bid-cycle test | redemptions are not held hostage to gas; deployment still waits | keeper's own loss, bounded by `--max-loss-wei` |
| `requiredReserve()` | derived from the target board, draws in flight and keeper rewards | fixed 0.05 ETH parameter, exact liabilities | **Adapted** (D46): keep the parameter, size it from obligations (0.005 ETH at the canary), keeper warns when below need | liabilities were already exact; the board-restoring part has no vault analogue | admin must raise it with the ceiling |
| Target inventory and planner | target board, deficits restocked in batches of 5 | relist first, build in sized batches when a cycle repays the build | **Rejected** (D48) | no target mix exists; no waste found (87 of 90 minted Shapes used) | none |
| Asset-flow kit, scorecards, signed outcomes | yes | rehearsal ledger and reconciler | **Adopted** (D49) | regimes and outcomes the owner can sign | owner signs `asset-flow.json` |
| System map | `docs/SYSTEM-MAP.md` | none | **Adopted** | one page of buckets and flows | none |
| Gas doc | `docs/GAS.md` | REPORT section 3 | **Adopted**: `docs/GAS.md` with receipt-level keeper P&L | numbers per operation in one place | none |
| Creator profit split, curated NFTs, prize board, ENS, purchaser automation, draw markup | yes | none | **Not added** | out of the vault's scope | none |
