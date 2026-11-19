> **Current release instructions: [docs/release/RUNBOOK.md](release/RUNBOOK.md)** (2026-11-19). This document is history for the candidate it names; where it gives current instructions, the runbook replaces them.

# Current completion status

The integrated operating pass and final evidence are in [Complete operating pass](COMPLETE-OPERATING-PASS.md). This supersedes the implementation and evidence gaps described in the historical review sections below to the extent explicitly measured there. The original O2 failure and need for a new outcome acceptance remain visible. No historic signature approves this candidate.

---

# Efficient journal revision in progress

2026-11-18. Current scope and measured limits: `EFFICIENT-JOURNAL-RESULTS.md`.
The new128-record jobs, required-tail eligibility, routine sync, returned-bid discovery and restock
optimization supersede the16-record job and essential-sync descriptions below. Current runtime
is24,451 bytes. Numerical quotes and allowances remain unchanged pending actual receipts.
The earlier342,766 checkpoint deduction is withdrawn because it double-subtracted finalized
refunds; the current direct finalized sample is345,937. Standalone signed receipts remain pending.
The prepared new local batch needs separate owner approval. No milestone acceptance is claimed.

Everything below is prior revision evidence for its named source, retained as history.

---

# Production position accounting acceptance

## Review repair status, 2026-11-18

The empty-vault capital boundary, keeper dependencies and persistent index are repaired. The
milestone remains blocked by exposed-vault funding, complete journal compensation calibration,
and O2. Checkpoint's fixed gas component is reduced to 360,000 (D68), meeting the existing O6
limit. No journal quote, budget, accepted outcome or owner signature was changed.
Verified code and focused evidence: `6319d5e`; keeper packaging: `2f3ca40`.
Checkpoint calibration and final affected verification: `e948b1e`.

- The original Solidity drains 0.010000000000000001 ETH across 673 authentic foreign records,
  then panics on its first deposit checkpoint. The repair pays zero for an onchain-proven unexposed
  cursor advance and preserves that seed. Three bootstrap tests pass, including direct checkpoint,
  protected escrow, positive-minPay rollback and reserve zero.
- Five real exposure/admission regressions pass, including the new mutating checkpoint rejecting
  an unseen own selection and receipt. Two OWED/FIFO kernel checks are model evidence only.
- Four production receiver checks pass: cold keep 46,462 gas, difficult kick 69,730, and 99 sampled
  low-gas attempts record or revert atomically. The two refreshed fork lifecycles reconcile all
  financial buckets to the wei after correcting the model fixture's future-prefix chronology.
- The repaired vault runtime is **24,322 bytes**, with **254 bytes** below EIP-170; linked library
  runtime is 21,313 bytes. This replaces the earlier 27-byte-headroom observation for this source.
- The actual production image builds and starts; separate containers sharing `/data` retain both
  transaction state and index head. The isolated job passed at `bc39d63`, with exact packaging
  hashes recorded in `receipts/review-packaging-ci-evidence.json`. No live Fly machine was replaced.
- Eleven Python accounting tests, keeper policy checks and seven focused forward scenarios pass.
  The funding proposal includes eight illustrative 30-day scenarios with absolute cash and holder
  marks. They are not forecasts or realized exits.

The affected economic scenarios were refreshed: O2 remains **1,919,655 quoted gas/position**
versus 1,750,000; O6 now pays **0.0002 ETH**, meeting its unchanged limit. Even perfect amortization
leaves 1,810,000 marginal build/list quoted gas per position; batching alone cannot satisfy O2.
Fresh full-holder and essential-spike fork checks support the checkpoint calibration. Their
refund-adjusted call measurements remain distinct from actual billed full-holder receipts, which
are a release evidence gap. Above-ceiling caller gas can still exceed capped compensation.

After the preserved node disappeared, the owner approved a replacement at the same endpoint and
fork with the same six clean actors and exactly 3 simulated ETH initial funding. The batch passed:
**77/80 transactions**, **1.755867382438961584/3 ETH aggregate transaction value**, no topups.
It measured real refunded prefixes 1..16 and tails 1..15 with a real active vault listing, then
completed the caller-funded backlog exit. Six exit calls billed **1,919,103 gas / 0.0003838206 ETH**
at 0.2 gwei, with only **0.0001 ETH** checkpoint compensation; other essential work paid zero.
Those receipts bind the preceding 400,000-checkpoint source. Journal quotes are unchanged.

The entry snapshot was restored after preserving receipts; owned Anvil PID 98279 remains with an
empty transaction pool. The refunded singleton billed 112,515 gas against 115,000 quoted; a full
batch billed 361,632 against 565,000. Raising the base to 105,000 would already reward splitting
in the actual refunded series. Successful-foreign billed small/full/tail receipts remain missing,
so no new journal payment rule or blanket quote cut was adopted.

Current evidence: `receipts/review-bootstrap-results.json`,
`receipts/review-journal-receiver-reconciliation-evidence.json`, `receipts/review-python-evidence.json`,
`receipts/review-journal-focused-evidence.json` and `receipts/review-independent.md`.
The actual matrix and replacement proof are `receipts/review-journal-local-results.json` and
`receipts/review-journal-replacement-startup.json`; fresh Q360 evidence is
`receipts/review-bootstrap-q360-results.json`. Current outcomes and immutable repair inputs are
`receipts/review-q360-outcomes.json` and `receipts/review-repair-manifest.json`.
The complete funding options and remaining measurement limits are in `REVIEW-FUNDING-PROPOSAL.md`.

Things that don't make sense: exposure to a small part of FWA obliges a vault to fund global work;
zero essential budgets move that unrelated backlog cost to withdrawing callers; an allowance
provides no ETH; and a positive ending model mark does not establish continuous keeper operation.

## Earlier integration evidence

The sections below describe the previous candidate. Their immutable manifest and broad test counts
remain historical evidence for those exact inputs, not fresh release verification of this repair.

Candidate: `codex/incremental-position-integration`, based on `f75ee770d0f0bce55a5f2607a23a3ee0104d1df1`.
Date: 2026-11-18. Production commit `909e761`. **The milestone is blocked by maintenance funding and changed economic outcomes.** Keeper and simulation commit `c93ac2f`. Local verification is complete within the limits below; no acceptance or release approval is claimed.

## Implementation boundary

One production vault and one `VaultLib.Book` replace the portfolio valuation scans. The book holds
exact redeemable Shapes backing P, usable idle backing, active posted backing B, active fee debts
and their histogram, ordered allocation exposure, acquisition cursor and authenticated receipts.
No total position ceiling or spare-slot backing spread remains. The ordinary keeper reconstructs
events in SQLite and hydrates bounded candidates at a pinned block.

The paid recipe remains a 0.1 ETH primary Shape mint, split into ten 0.01 ETH Shapes, then assembly
using the existing pack-size mask. Mint fees leave cash as before. Holder checkpoint ordering,
protected liabilities, dead shares, high-water mark, claims, partial redemption indexes,
distribution and wind-down behavior remain in the production share vault. Token rewards retain
zero NAV value and are claimed and burned.

The API changes intentionally: restock and list take backing proposals, sync takes bounded journal,
terminal and prune work, and checkpoint takes an authenticated fee witness. All operational callers
migrate with the ABI. Full enumeration exists only in independent test references.

## Funding blocker and proposed decision

The recorded 30 days ending at block 26,425,092 / 2026-11-16 04:07:59 UTC contain **18,281 completed
global acquisitions: 13,191 successful and 5,090 refunded**. The window is historical, not a claim
about today's activity. With 16 entries per call, perfect packing needs at least 1,143 calls.
The final journal quote is 85,000 per call plus 30,000 per completed record: **645,585,000 quoted gas**.
Foreign/refunded records receive no flat work fee. The fixed quote is conservative, not literal
gas reimbursement: final Forge successful-foreign gross costs were 158,812 for startup one,
138,930 for steady one and 420,622 for steady sixteen, versus quotes 115,000 and 565,000.
Thus it underquotes the singleton and overquotes the batch. Sixteen split calls used 2,181,216
gross gas; their additional 0.000255 ETH pay was below their additional 0.0003521188 ETH gross
cost at 0.2 gwei. Actual refunded receipt costs are reported separately. This calculation excludes
all own selection, terminal, prune, harvest and listing work, so it is an optimistic lower bound, not an income model.

| Configuration and quote price | Global-only quote / 30 days | Maximum budget / 30 days | Shortfall |
| --- | ---: | ---: | ---: |
| Mainnet, 0.2 gwei (0.15 basefee + 0.05 tip) | 0.129117 ETH | 0.25 ETH | 0 ETH before own work |
| Mainnet, 0.5 gwei (0.45 basefee + 0.05 tip) | 0.3227925 ETH | 0.25 ETH | **0.0727925 ETH** |
| Canary, 0.2 gwei | 0.129117 ETH | 0.054 ETH | **0.075117 ETH** |
| Canary, 0.5 gwei | 0.3227925 ETH | 0.054 ETH | **0.2687925 ETH** |

Budget is spending permission, not ETH funding. The mainnet 0.005 ETH/day refill cannot sustain
the 0.01075975 ETH/day global-only quote at the ceiling. Even the contract's existing maximum
0.01 ETH/day refill is below that lower bound. Canary's 0.0008 ETH/day refill is below the
0.001075975 ETH/day global-only quote even at zero basefee and its 0.05 gwei tip.

One full foreign batch costs 0.0002825 ETH at the ceiling and fits the retained 0.005 ETH reserve.
The keeper's modeled reserve need is 0.0042425 ETH. **Affording a batch does not fund repeated
maintenance.** No protected holder bucket or processingPool is used to cover the gap.

| Option | Effect and cost | Recommendation |
| --- | --- | --- |
| Retain the existing settings | Budget eventually exhausts; unpaid callers can progress, but a paid ordinary keeper is not continuously funded at the measured activity. | Preserve as an unaccepted candidate. |
| Narrow funding revision | Authorize a routine refill above 0.01075975 ETH/day plus measured own-work allowance at 0.5 gwei, raise its 0.01 hard maximum accordingly, and identify actual free-ETH funding. Recompute return and owner-authority outcomes. | Preferred subject of a separate owner decision; the lower bound alone is insufficient to choose the final amount. |
| Restrict paid operation to a lower gas regime | Global-only break-even for the existing mainnet refill is approximately 0.23235 gwei total quote price; own work lowers it. Higher gas leaves maintenance waiting or unpaid. | An availability change requiring an explicit owner outcome, not an implementation fix. |

Receipts: `receipts/integration-maintenance-mainnet.json` and
`receipts/integration-maintenance-canary.json`. Reproduce with:

```sh
python3 sim/maintenance.py --database /path/to/recorded/fwa.sqlite --values deploy/mainnet.json
python3 sim/maintenance.py --database /path/to/recorded/fwa.sqlite --values deploy/canary.json
```

## Listing split-payment repair

The first broad candidate run passed 120 tests and failed thirteen. Twelve failures concerned
fixture/API assumptions or cumulative setup gas; one found a real payment regression. Three
singleton listings earned 0.00016 ETH extra base pay at 0.2 gwei, against 0.0001406222 ETH extra
gross gas cost. The assertion was retained.

Approved local transactions then compared the same three listings, in the same order and starting
with four idle packs, so both branches left one idle pack. Every included block had basefee
0.15 gwei and effective/quote price 0.2 gwei. Billed gas was 2,624,113 for the batch versus
1,063,186 + 1,114,498 + 1,097,398 = 3,275,082 for the singletons. The extra **650,969 billed gas**
cost 0.0001301938 ETH. A 300,000 base would still overpay splitting at 10% markup.

The source repair following that broad run lowers `Q_LIST` from 400,000 to **280,000**. Per-listing gas, work fees,
policy caps and budgets remain unchanged. At maximum markup the extra two bases offer
0.0001232 ETH, below the measured extra cost by **0.0000069938 ETH**. This is one measured
three-versus-singleton context, not a guarantee for every ordering, future protocol change or gas
price. Final targeted regression and local deployment receipts bind the repaired artifact.

## Evidence and scope

Frozen production source SHA256:

```text
798e7ea0fc9968f8fe4d1ec14ce40275f47b5a10fb16872c73295929fc204fe9  src/PackVault.sol
a13b42c4ce02aebfa5e19e5fd3536c6c3da4caa2965f2e11d5952ed82bc158d9  src/VaultLib.sol
d50229cf80a4a036c9ba3f4f8bb60452129ee51dc7ca0263ad612b2ea76e499d  src/interfaces/External.sol
```

PackVault runtime is 24,549 bytes, VaultLib 20,484. Only 27 bytes remain below EIP-170 for the
vault. Compilation uses solc 0.8.30, optimizer 200, via IR and Cancun with no raised size limit.
Asset-flow source/evidence hash is
`e2e2d2c3965d511c48587a04a135f2f8eaccdfb7d2b5dd3e218cb05e10b16895`.

Final candidate focused tests passed two staging and four maximum/journal gas tests. Eight
largest packs cost 6,554,114 gross gas; a mixed three/thirty-unit batch with five actual crown
tenures cost 6,527,313. Restock ten three-unit packs, thirty total units, cost 10,357,047 gross,
the largest measured operation; its 25% margin is 12,946,309, below 16,777,216. A full holder-mix
checkpoint cost 370,178. These are complete gross meters including intrinsic/calldata, before
transaction refunds, not billed-gas receipts.

The staging counterexample created a real pack and admitted it while activating fifteen foreign
entries plus the entrant. That complete fixture operation used 5,227,714 gross gas, including pack
creation; it is not an isolated FWA-call measurement. The repaired maximum-eight admission rejected it atomically in 1,409,430
gross gas. No foreign FIFO progress, cash, custody or book mutation survived the rejection.

The first broad run was 120 passed / 13 failed across 34 suites. After repairs, the final selected
run passed **52/52 across 19 suites**. A separate real 301-listing setup and the two detailed cold
receiver traces passed. Counts overlap and must not be added as unique tests. All thirteen original
failures are retained and mapped to their affected passing repairs. Exact commands, input hashes,
pass/failure counts, tools and dependency revisions are in:

- `receipts/integration-broad-inputs.json` and `integration-broad-results.txt`;
- `receipts/integration-final-affected-inputs.json` and `integration-final-affected-results.txt`;
- `receipts/integration-final-test-evidence.json`, `integration-repair-index.json` and
  `integration-final-receiver-traces.txt`.

The final callback uses **46,462 gas for a cold keep** and **69,730 for the difficult kick after a
false settled-bid candidate**, leaving at least 30,270 of FWA's 100,000 stipend. Forty keep and
59 kick gas limits sampled 22/40 atomic failures and 18/19 complete receipts, respectively. Every
sampled success recorded the receipt. Samples and fallback inspection do not prove every possible
gas amount, future protocol version or adversarial execution context.

Both normal and maximum 10% policy-envelope split regressions pass after the listing-base repair.
The complete holder cycle paid 0.005811 ETH to the keeper. A manufactured attacker cycle at maximum
parameters lost 0.080062249940729552 ETH using conservative basefee-only gas costing, with no
remaining attacker shares, locked redemption or claimable balance. Protected buckets were checked
through the changed holder, settlement, cancellation, distribution and wind-down paths.

`receipts/integration-economic-scorecard.md` is the one-screen outcome/bucket summary. All sixteen
regimes have zero bucket mismatches. **The asset gate exits 2**, retaining the old signature and
numerical requirements: O2 measures 1,919,655 quoted gas versus a 1,750,000 bound; O6 pays
0.00022 ETH versus a 0.0002 bound. At a 0.5 gwei quote and 0.00004 ETH build/list work fees, the
observed O2 allowance is about 0.0009998275 ETH per position. No new outcome is approved by a test.
Wind-down loss is 44 bps, claim gap is 0 wei, locked shares are zero and residue is
0.010061058998589904 ETH. Exact buckets and round trips are in `receipts/flow/*.json`.

The requested initial `forge build --force` ran and failed on an obsolete checkpoint caller; the
failure is retained in `integration-force-build-initial-failure.txt`. A later complete consumer
build passed; final changed-source compilation and normal deployment postflight verify the new
Params ABI. No force-build PASS is claimed. A test-only serializer stack-depth failure and the
RPC sandbox failure are also preserved. No cache was deleted to evade a failure.

The production accounting kernel has independently matched 40,960 randomized steps and fixtures
at 301, 1,000 and 10,000 bookkeeping positions. This is production-library model coverage, not
10,000 real FWA listings. Setup/reference gas is separate from individual measured operations.
Kernel valuation gas was identical across all three sizes: 18,553 with zero pending fees and
18,652 with positive fees. The final harness/meter bytecode hashes still match this eight-test
run, so its evidence is reused. Separately, **301 actual FWA listings** passed with 9.1 ETH real
minted principal including seven loose Shapes and more than 10 ETH posted backing. Cumulative
fixture setup used 1,159,919,975 gas under a separate 10-billion test allowance. Its cold complete
checkpoint was **300,454 gas**, with the normal transaction cap and 25% margin asserted. This is
not a production gas-limit increase. See `receipts/integration-production-model-inputs.json`,
`integration-production-model-results.txt` and `integration-complete-exits-real301.txt`.

Both final Python/fork cycles reconcile every financial bucket, exact fee debt, cursor, receipt
count and idle funding to the wei. The real selected cycle received 0.000024976235593068 ETH fees,
paid 0.001889 ETH keeper compensation and 0.001 ETH mint fees, and spent 0.0363 ETH bid backing.
The partial/wind-down cycle claimed **0.992779091300853720 ETH**, paid 0.004388 ETH keeper and
0.003 ETH mint fees, leaving **6 wei** of redemption-index rounding reserve. All amounts are
independently conserved across holder cash, remaining assets and expenses. The preserved rounding
rules explain the residue. Reproduce with `python3 sim/reconcile.py` after both trace fixtures;
see `receipts/integration-python-reconcile-final.txt`.

Ten Python accounting regressions and seven focused forward-model scenarios pass. The latter
include empty/depleted budgets and delayed pricing, with no annual return gate claimed. The
model retains waiting inventory funding and the keeper may build valid packs above an unlistable
extended gift only when there is no viable listing proposal. See `integration-python-vault-final.txt`
and `integration-forward-self-check-final.txt`.

The owner approved the isolated local batch in `receipts/position-local-batch-plan.json`: one named
Anvil node, six fresh signers and at most 60 simulated ETH total, with normal contract and transaction
limits. No public-network transactions, real funds, push, merge or signature are authorized.
The named oracle owner is a contract; the rehearsal guard rejected treating it as an EOA. Oracle
changes dependent on that impersonation are not local-rehearsal evidence.

The normal linked script path deployed final vault
`0xe7709640478bbf1b1d7fc5bac840ba3d657782d1` with **5,766,663 billed gas** and the 216-byte policy
with 100,155. It reused the 20,484-byte library at `0x00c6B6d3C70270040d0390938853A58Bacd9A190`.
That library's actual earlier CREATE2 transaction from the approved deployer through the real
0x4e59 factory used **4,490,075 gas** at block 26,418,540. The complete 20,516-byte initcode matches
the frozen artifact; runtime comparison normalizes only its compiler-declared self-address.
No code injection was used. See `integration-keeper-context-correction.json` for the full canonical
receipt, salt, initcode and derived-address proof. Vault runtime SHA256 is
`81066a9b2cbdfcb1c2af4dacdb906732f6c760f13a50649529d1a2f8340d91e2`.

The final quiet flow passed: **29 listings, zero staged, 20 keeper transactions, zero reverted
receipts**, partial then complete holder exit and wind-down. Its exact vault ledger is:

| Inflow | ETH | Outflow / remaining | ETH |
| --- | ---: | --- | ---: |
| Seed | 0.01 | Holder claims | 1.976995382678932508 |
| Deposits and request charges | 1.990121185 | Keeper pay | 0.0041259867898 |
| | | Nine primary mint fees | 0.009 |
| | | Remaining vault balance | 0.009999815531267492 |

The ledger gap is **0 wei**. Value-only holder loss is 0.013125802321067492 ETH; adding the holder's
0.000032626147394605 ETH wallet transaction gas makes wallet loss 0.013158428468462097 ETH.
The operator explicitly accepted unpaid exit gas through its existing loss option. Across all
keeper calls, actual gas cost was 0.003466504165788461 ETH and net compensation was
+0.000659482624011539 ETH. This is one variable-basefee local run, not a claim of profit for every
call. Its 29-pack, nine-mint deployment differs from the smaller fixed-fee wind-down regime;
44 bps in that regime is not the local maximum-load wallet result.

Root independently read the final state at block **26,418,606**: all six book totals, positions,
idle/recovery/loose inventory, reserved tags, pending receipts, locked shares, escrow, processing
pool, distributions and claimables are zero. Only dead shares and **2 wei** of redemption rounding
remain beside the seed's current value. See `integration-final-quiet-readback.json`.

The real transaction-manager witness covers restart, discarded real RPC responses, same-hash
re-inclusion uniqueness, status-0 gas debit, fresh replacement estimate, one-attempt replacement
cap and exact accepted hash/nonce in the actual pool. Real withdrawal/index restart/reorg restores
the canonical projection, token supply and P&L. The replacement mined at 184,132 gas and cost
0.000134862304871632 ETH, with zero pay for token burning. It used the existing Q400 vault
`0x2113...`; that is a valid older quote instance. Only the two inlined list-base operands differ
from the final artifact after declared links/immutables are normalized. Library bytecode is
identical because Q_LIST is inlined into PackVault, not executed by VaultLib. This is client
recovery evidence, not final-Q280 listing compensation evidence. The Q280 final quiet run and
separate billed listing comparison provide the latter.

Independent keeper review found and verified repairs for exact signed-call gas padding,
replacement gas refresh, durable uncertain-attempt counting and concurrent SQLite writers. The
10,000-entry pure index fixture tests bounded candidate sets, reconstruction and debt ordering;
actual real-vault reorg evidence is separate. Synthetic successful payment/event counterparties
were removed. Loaded-code fingerprints are diagnostic; the immutable source hashes captured at
import and fresh process boundaries are the recorded code inputs, not exhaustive Python-memory
attestation. `receipts/integration-independent-review.md` records the bounded review.

Archived local evidence and raw receipts: `integration-keeper-final-evidence.json`,
`integration-local-artifact-map.json`, `integration-approved-actions.jsonl` and
`integration-keeper-final3-and-quiet.txt`. The final optional canary buyback was already consumed
on an earlier approved branch and failed honest preflight; no failed buyback was sent. Local
oracle/kick and 30-unit branches were not reached within the named signer authority. Actual VRF,
large-pack and kick evidence remains the separate real Forge fork evidence. The original pool
fixture failure and intermediate canary are retained. The node (PID 10583) and old paused driver
(PID 10551) remain at the approved endpoint, with empty pending/queued pools and no second funding
credit. Further process cleanup is not performed by this task.

## Remaining gates and limitations

Funding above is a concrete milestone blocker. Existing asset-flow outcome amounts and the old signature are preserved;
the signature does not approve this changed candidate. A changed numerical outcome needs owner
approval, and no unsigned or failed gate may be labeled PASS.

Independent implementation review is narrower than a security audit. No audit, public-network
rehearsal, canary, annual return gate or release-readiness claim follows from these tests.
Dynamic coverage gaps remain: fixed-contract failed NFT delivery, forced FWAIR classification,
a real sixteen-allocation/expiry burst, and synthetic oracle values outside the deployed oracle's
bounds. The tests use a real two-active fee-witness fixture, one selected own listing plus 29
foreign fillers preserving historical VRF weight, and sixteen actual kicked receipts. No mock
manufactures missing cases. Current-block real-key rehearsal, a fresh frozen release audit,
approved updated economic outcomes/signature and a capped public-network canary remain separately
authorized launch gates. The prior annual return report is marked historical.

Things that don't make sense:

- A global journal paid by every vault creates a recurring cost even when no vault position is selected.
  The retained reserve covers individual calls, but the existing refills do not cover the measured workload.
- A drained acquisition queue does not prove FWA's private staging FIFO is empty. Admission needs a
  bounded real FWA call and an atomic postcondition on incidental activations.
