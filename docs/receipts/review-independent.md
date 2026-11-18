# Independent affected review, 2026-11-18

What this change does: an unexposed vault advances past irrelevant completed FWA history without earning keeper compensation. Checkpoint and first admission share that proof, so a keeper need not accept a loss-making standalone sync before serving the first depositor. The production image installs its Python runtime and keeps both durable stores under `/data`.

This is a focused read-only review against `a4496adaba9048170ba39f1255783dccf891f163`, not an audit or release acceptance. The reviewer changed only this report, ran no fork tests, broadcasts or container jobs, and used Ponytail/Ponytail Review plus the holistic verification guidance. Commands were source/diff/caller reads and SHA-256 checks; the missing-file exploratory reads had exit status 1 and were corrected to the existing production test path.

## Immutable reviewed inputs

| File | SHA-256 |
|---|---|
| `src/PackVault.sol` | `1dc1ddb5d4c09057f34797efdff5d87929898c51bda671423de23625e7687af2` |
| `src/VaultLib.sol` | `259d85003ff2392be404ead8d067edc92b1277044ee905e4f3640235bc760aae` |
| `keeper/policy.py` | `0658aad4e2f07fe2acc29359c8915a9473bb681f22d65d0c03b212cb4d91d5d4` |
| `sim/vault.py` | `bc3784c2574e1b631b0971974a0913c85a2de691755cfabde1b1dfbee6c0c49a` |
| `sim/forward.py` | `d129f9cb4a644fcd011825be8b837714ab03d1b341ab2ba022e14010e046c105` |
| `sim/reconcile.py` | `cbbe9121e1a1bf6c68fb6ef2b8d430a761175d31a2cc727ff2e000a5fce9eaff` |
| `test/fork/ForkIncrementalProduction.t.sol` | `211071b3fb8f5d7057564e094ec948195e966719a324620e705fb47608558109` |
| `keeper/Dockerfile` | `7845bdb55c983071f21da2ccdc3562e1535b7fc6c80178b682d6336d20042a74` |
| `keeper/entrypoint.sh` | `ca352b88b678547c60b00148e9b9e656d068ceb53e614f3607165fe23aed6bab` |
| `keeper/requirements.txt` | `aed414c4157dd12cba962363a8c9f561a2e5dcddbf20ee4c2ea9ff41ad4e913c` |
| `keeper/test_packaging.py` | `ba913e579d563d7e2e32b1f8b6938f22d17f0f28581c3d5894dc41e3f1bb4c5e` |

## Correctness and authority result

No concrete new correctness or security regression was found in this bounded review.

- `_unexposed` requires empty open positions, zero reserved identifiers, zero active memberships/backing, zero allocated value and no pending receipt. `OWED` remains in `open` until actual custody recovery. Receipt identifiers remain reserved until authenticated terminal reconciliation. Thus missing a successful own allocation or an outstanding receipt prevents the shortcut, even before selection has reached the book.
- An exposed call still processes ordered entries through `_syncJournal`; terminal resolution and pruning stay bounded. A call that begins exposed cannot use an unpaid rebase after retiring its last position in the same call.
- A pure rebase returns both quoted gas and work units as zero. Even a replacement payment policy cannot exceed the zero vault envelope. Empty tracked inventory also cannot earn pay for stale-head cleanup. Positive `minPay` fails atomically after work and rolls back the cursor, pruning and any external state effects.
- Sync payment remains in PackVault after library work, and `_free()` is evaluated then. ETH returned during terminal reconciliation is visible; escrow, processing charges and holder reserves remain protected. No stale pre-operation balance was introduced by moving orchestration.
- Pre-admission rebase precedes creating the first live FWA identifier. In-flight acquisitions are not skipped beyond FWA's completed prefix; their later completion remains journal work. Existing strict `accountedNav` remains a view and still reports catchup required, while checkpoint alone may establish the approved proof before pricing.
- The keeper uses authoritative aggregate open count and pending receipt reads, rather than assuming that an empty bounded candidate list proves absence of exposure. Its shortcut is conservative when stale candidates remain. The onchain proof stays authoritative during preflight.
- The model retains OWED positions and pending receipts in its proof. Forward simulation separates rebased history from paid processed entries and drains rebased foreign entries after successful checkpoint/admission. No model/contract divergence was identified by static tracing; the updated simulation still requires its affected execution/reconciliation evidence.
- Runtime dependency pins include `eth-hash[pycryptodome]` and the backend itself. Both Fly configurations use the same Dockerfile and `/data` mount; the entrypoint supplies `/data/keeper-index.sqlite` explicitly. Index chain/vault/deployment identity checks are unchanged.

## Closed affected verification finding

1. **Mutating checkpoint exposure gate: resolved.** The added `test_mutatingCheckpointCannotSkipUnseenOwnSelectionAndReceipt` reaches a real blackout with its external acquisition queue drained, pending holder deposit, book-ACTIVE selected own position and genuine keep receipt. Actual checkpoint rejects with `CatchUpFirst`; cursor, receipt, open count, reserved count, backing identifier, balance, escrow, charge pool and interval remain unchanged. Authenticated journal/receipt reconciliation then allows checkpoint in the same window. `review-bootstrap-exposure-guards.txt` reports all five selected real-fork regressions passing, exit 0, against the frozen Solidity hashes. The reviewer inspected the source, log and manifest, rather than rerunning them. Manifest SHA-256: `6777abf7628d3a4c78bee7d877256a20c79995c0ae0af56564ccf0adcf9b07f1`.

## Model chronology and funding instrumentation follow-up

The initial reconciler exposed the selected transaction's future completed prefix before creating modeled listings. The legitimate first-admission shortcut consequently advanced into future history, producing a cursor mismatch. Initializing the prefix to the real setup cursor during restock/list, then revealing the selected prefix afterwards, repairs input chronology without weakening comparisons. Both unchanged current fork traces subsequently reconcile every recorded vault bucket to the wei, according to `review-journal-receiver-reconciliation-evidence.json` and `review-journal-reconcile-python-fixed.txt`. The original failed replay remains archived.

The keeper's aggregate-count proof and the model's unpaid rebase accounting remain coherent under the final affected diff. The forward model now reports absolute paid-in principal/charges, holder end value before external gas, actual modeled fees/mint fees/backing lost, journal pay, and minimum free cash sampled initially and after successful keeper actions. Those metrics distinguish real modeled ETH from spending allowance. They add observation fields, not a new cash source or economic permission. Its daily stochastic journal still places that day's own selections before that day's foreign/refund records; it is an approximation and must not establish exact backlog timing or calibrated keeper profit. No new return or funding result follows merely from these fields.

## Independent economic pass

The changed asset map has no new destination: seed/free ETH stays in the vault, pending deposits stay escrowed until priced, processing charges fund checkpoint, holder liabilities stay reserved, and only verified paid maintenance reaches its caller. The approved shortcut removes a cost only when no live FWA exposure exists. Caller gas for the unpaid shortcut remains external; embedding it in a funded checkpoint or admission avoids requiring a separate willing unpaid keeper.

| Outcome or regime | Amount and context | Result at this review |
|---|---|---|
| Minimum seed, no positions/inventory | 0.01 ETH seed; foreign-history sync quote is 0 gas and 0 work units | Seed cannot be depleted by those calls under the reviewed code; real first-deposit regression execution belongs to affected verification |
| Pending first deposit | Deposit escrow and checkpoint pool excluded from pre-flow NAV; seed remains positive | Existing share price denominator is preserved against this particular drain |
| Exposed foreign history, old fixed quotes | 18,281 records / 30 days; 1,143 packed calls; `18,281 × 30,000 + 1,143 × 85,000 = 645,585,000` quoted gas | Still a running cost; startup rebase does not remove it while exposed |
| Mainnet allowance comparison | 0.3227925 ETH at 0.5 gwei versus 0.25 ETH initial-plus-refill allowance over 30 days | 0.0727925 ETH shortfall before own work, under that fully exposed recorded window and old quotes |
| Canary allowance comparison | 0.129117 ETH at 0.2 gwei versus 0.054 ETH initial-plus-refill allowance over 30 days | 0.075117 ETH shortfall before own work under the same assumptions |
| Exit with zero essential cap | Mandatory exposed catchup is caller-funded even with routine allowance remaining | Real backlog exit costs remain required evidence |
| O2 / O6 | Prior candidate 1,919,655 versus 1,750,000 quoted build/list gas; 0.00022 versus 0.0002 ETH gas-spike checkpoint payment | Existing owner outcomes remain unresolved; this review grants no revised acceptance |

These are payment/allowance calculations, not billed-gas profitability or net depositor return estimates. Actual funding cash is separate from allowance. No new gas quote, spending cap, participant right, acceptance signature or production deployment was approved by this report.

### O6: 400,000 to 360,000 is not a demonstrated optimization

At the scenario's 0.5 gwei quote ceiling and 0.00002 ETH work fee, a 360,000 gas component pays exactly `360,000 × 0.5 gwei + 0.00002 ETH = 0.0002 ETH`. It would pass the existing metric. The archived full holder checkpoint used 370,178 complete gross gas on the earlier source. Gross gas is not billed gas, and the work fee is part of actual caller compensation. At a matched 0.5 gwei effective price, the proposed total payment equals 400,000 gas, exceeding that gross sample's 0.000185089 ETH cost. Thus that sample alone does **not** demonstrate that a 360,000 component underpays a default caller. At the actual gas-spike scenario's 2 gwei effective price, the same sample would cost 0.000740356 ETH; both existing 0.00022 ETH and proposed 0.0002 ETH payments intentionally leave caller cost above the routine ceiling unpaid.

The sample also does not establish that 360,000 is a calibrated fixed component across current code, holder mixtures and permitted work-fee settings. D61 says checkpoint is quoted at measured cost, and no current matched-context billed full-mix receipt or demonstrated source optimization supports this replacement. Recommendation: retain 400,000 and the visible O6 failure until focused receipt/optimization evidence supports a lower schedule, or request explicit acceptance of the revised outcome. Reducing the constant solely to satisfy the test would conceal an unresolved economics decision.

### O2: removing call overhead alone cannot pass

Even with ideal whole-mint utilization and zero restock/list call bases, the existing three-unit components sum to `325,000 + (3/10 × 2,200,000) + 825,000 = 1,810,000` quoted gas per built/listed position, above 1,750,000. For the 29-position archived maximum-load result, nine whole mints make that component-only floor `(29 × 325,000 + 9 × 2,200,000 + 29 × 825,000) / 29 = 1,832,758.62`. The observed 1,919,655 therefore cannot be repaired purely through better batching or deleting fixed bases.

At least a component quote must change, supported by actual operation savings/calibration, or the owner must explicitly accept a higher outcome. The read-only source review identified no narrow, verified source optimization that supplies the required reduction while preserving paid primary minting, pack construction and authenticated FWA admission. This is not a claim that further optimization is impossible. A simple per-listing quote cut is not proven safe by gross evidence: the archived three-position batch bills 2,624,113 gas; cutting 169,655 per position with unchanged 280,000 base would pay only `(280,000 + 3 × (825,000 - 169,655)) × 0.5 gwei + 3 × 0.00002 ETH = 0.0011830175 ETH`, below that batch's 0.0013120565 ETH cost at a matched 0.5 gwei price. Current-state receipt evidence must precede such recalibration.

## Packaging evidence inspected

The archived [isolated image verification](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/44393965532) reports success for commit `bc39d6392ef04a55d7faefc9725bc7c5c02f914a`. Its four relevant source hashes match this checkout. Raw log SHA-256 is `f8be5b7f7a7ec995e5f71d882d9ca9118b43a8c325899ca5f55c1551e6382908`.

It builds the real production Dockerfile, starts the parser, checks Ethereum Keccak, and preserves a transaction-state marker and SQLite head 104 across two distinct containers sharing one `/data` volume. It rejects all three index identity mismatches. The workflow has read-only repository content permissions and the stored fixtures are local serialization inputs, with no successful RPC replies supplied. This establishes image startup and mounted-store persistence; it does not establish a running Fly machine replacement or healthy live keeper execution. The reviewer inspected the archived artifacts and did not independently rerun that job.

Verdict: the source repair is coherent in this bounded review, and the identified mutating-checkpoint verification gap is closed. The model chronology correction preserves exact reconciliation. This does not close the broader draft PR's calibration, funding and O2/O6 economic blockers.

Not checked: compilation, bytecode size, receiver gas, fork execution, reconciliation or new calibration runs by this reviewer; the lead owns those affected checks. No broad audit, live deployment or canary was performed.

## Things that don't make sense

- A fully exposed vault still pays to process unrelated global history. The recorded-window allowance deficit and zero-funded essential exit path need the pending measured proposal; an empty-vault fix alone does not resolve them.
- Lowering fixed quotes until outcome checks pass does not establish that a keeper will perform the work. Source optimization and actual matched-context payment/cost evidence must support recalibration.
- O2 and O6 remain above approved limits. Balanced accounting and successful container startup do not resolve those outcomes.
