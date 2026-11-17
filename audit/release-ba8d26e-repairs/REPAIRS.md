# Repairs for launch audit A at ba8d26e

Audit report: `audit/release-ba8d26e/REPORT.md` (copied from the auditor's worktree). Every
contract finding below is proven fixed by the auditor's own witness, kept in
`test/audit/release/` and rewritten to assert the repaired behaviour on the same fork state.

| Finding | Repair | Evidence after repair |
|---|---|---|
| S1 malformed or gas-burning oracle blocks exit | `VaultLib.economics`: 100,000-gas staticcall, manual four-word read, out-of-range words mean no cap | `AuditOracleGas`: one-position exit, claim and three-position unlist all succeed with the hostile oracle installed (three positions under 3M gas) |
| E1 keeper pays gas for reverted work under a fee-sensitive policy | keeper simulates and estimates at its signed fee fields and re-estimates the exact call with `minPay` before sending | `hostile_policy_keeper.py` on a local anvil fork with the production keeper: skipped, 0 sent, 0 wei lost (audit run: 2 reverts, 0.0000309 ETH lost) |
| E2 distribution-only checkpoint never scheduled | keeper simulates a no-flow checkpoint and plans it when it succeeds | `keeper/test_policy.py` (planned; not above the ceiling) |
| E3 empty checkpoint consumes the interval | `checkpoint` reverts `Nothing` when nothing settles and nothing distributes | `IndependentChallenge`: empty call reverts, slot stays free, redemption prices in the same interval |
| E4 keeper counts `processingPool` as free | keeper subtracts it | `keeper/test_policy.py` at the auditor's exact balances: liquidation planned before the checkpoint |
| E5 activation batch exceeds EIP-7825 | batches of 20 IDs, `maxCount` 20 | `keeper/test_policy.py` (100 staged: 5 calls of 20) |
| E6 expired allocation priced at its lower bound | `checkpoint` reverts `SyncFirst` while an allocation past FWA's window is unsynced; keeper syncs first, also above the ceiling when shares are locked | `AuditAllocatedValuation`: checkpoint refuses, slot untouched; after a sync the deposit prices in the same blackout. FWA lets the purchaser act during allocation even after the window, so marking at the higher value would be wrong |
| E11 63-unit pack cannot be built | `MAX_PACK_UNITS` 30; keeper builds nothing unless 3-unit packs are enabled | `AuditMaxPackGas`: 63 and 31 rejected; a 30-unit pack builds from empty inventory under 12M gas |
| V1 value invariant underflows for a profitable holder | signed net inflow | `AuditInvariantHarness`; extended campaign 64 runs x 64 calls, all four invariants pass |
| E10 one-wei reserve dust | not changed | accepted: rounding direction keeps reserves covering claims |

Independent review of the repairs: all close their findings; one residual (E6 makes redemption
pricing depend on FWA's past-window reclaim) checked against FWA's verified source and found not
blockable by a purchaser (D60).

Not repaired here (owner decisions): E7 forward model omits FWA staging (the return gate is not
validated until it is modelled and matched to a fork); E8 owner-compromise bound and the raisable
TVL cap; E9 outcome signature.

Verification at the repaired tree: 92 Solidity fork, audit and scenario tests; reconciler exact;
`keeper/test_policy.py`, `keeper/test_tx.py` (11 scenarios); canary rehearsal closes to the wei;
`CANDIDATE_RUN=1` invariant campaign 64 runs, 4,096 calls. PackVault 22,346 bytes.
