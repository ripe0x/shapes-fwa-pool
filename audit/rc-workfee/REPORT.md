# Release-candidate review: work fee (D55) and guardian repairs, on top of 3e600e5

Scope: the change from `audit/rc-3e600e5` (full release-candidate audit) to this source: the flat
`workFee` per unit of work, `MAX_WORK_FEE`, `lowerCaps` lowering the fee and cancelling a queued
proposal, and the policy and simulation mirrors. Tier: release-candidate, scoped to one change.
Two independent reviewers with fresh context; informed runs, not blind. Report text condensed by the lead from the
reviewers' messages (their harness could not write files). Not a safety or release certification.

## Review 1: the work fee (about 40 minutes)

**No high or critical finding.**

Executed on a mainnet fork with no mocks:
- `test/audit/AuditWorkFeeManufacture.t.sol`, 2 tests, both pass. A checkpoint earns 1 unit per 12 h interval and is refused without a real holder flow. A healthy listing cannot be unlisted, so a list-then-unlist fee loop is impossible. restock earns 0 units; list earns 1 per pack.
- `test_workFeePerUnitNotPerCall` passes: splitting a job into more calls earns no extra fee.
- `test_guardianZeroCeilingDoesNotTrapHolderFunds` and `test_adminMaxParamsSelfKeepExtraction` pass.
- PackVault is 22,643 bytes at review time.

Findings:
- **LOW-1:** the guardian could not stop the work fee, because it was admin-only behind the delay. **Fixed:** `lowerCaps` now takes `workFee`.
- **LOW-2:** a 0.01 ETH deposit creates one paid checkpoint per interval: at most 2 units a day, 0.0146 ETH a year at the canary fee and 0.073 ETH at the maximum. It is a net loss to the caller above about 0.4 gwei at the canary fee. **Accepted** (D55).
- **NIT-1:** the keeper counts only units it is sure of, so its loss check is stricter than the vault's pay. **Accepted.**
- **NIT-2:** O2 named only the listing unit. **Fixed:** O2 now states the units for each step.

Worst case for holders:

| Scenario | Canary fee | Maximum fee |
|---|---|---|
| Wind-down churn, once | ~0.0012 ETH at 30 positions | ~0.06 ETH at 300 |
| Every position resolved and relisted every interval (theoretical ceiling) | 0.89 ETH a year | 43.9 ETH a year (~14% of the edge those cycles earn) |

No overflow; EIP-7825 effect negligible (reasoned).

Reasoned only, not executed:
- re-staging a listing to earn the activate unit again (FWA's lifecycle is one-way)
- holding a redemption unfilled to farm checkpoints (same bound as the deposit route)
- a full scorecard rerun (the lead reran it, below)

## Review 2: the guardian repair (`lowerCaps`)

- **MEDIUM-equivalent risk, pre-existing:** a proposal queued before a guardian stop restored the old values when applied. **Fixed:** `lowerCaps` now cancels any queued proposal. Test: `test_workFeeBounded` (applying after the stop reverts `TooEarly`; the fee stays 0).
- **Nit:** after `lowerCaps(…, 0, 0)` the stored maxTip exceeds the ceiling. Harmless: the price is clamped and bounds are checked only on proposals.
- **Question for the owner:** with the ceiling and fee both at 0, nobody is paid to run checkpoint or liquidate. Holders can still call them. This is the intent of a guardian stop.

## Lead's verification after the repairs (source hash in SOURCE_HASH)

- **Fork and audit tests:** 47 pass (`forge test --match-path "test/{fork,audit}/*.t.sol"` with the Tenderly flags).
- **Model check:** `sim/reconcile.py` matches to the wei.
- **Asset flow:** 16 regimes, 10 outcomes OK. The gate reports INCOMPLETE only because the outcome text changed and needs the owner's signature (hash f5100bae…7740bd).
- **Size:** PackVault 22,774 bytes.
- **Canary rehearsal:** run on the bytecode before the final `lowerCaps` repair, which the rehearsal never calls. Ledger gap 0; keeper books equal the chain; keeper net +0.00225 ETH; holder −0.0221 ETH on 1.99 ETH with no acquisitions.
- **Simulation** (`sim/forward.py 400`): 100 positions at last-14-day activity, +21.0% a year, P(loss) 17%.
