# Independent review: kick check in pool pricing (b63d87a)

Scope: `src/ScanLib.sol` `requireAllocatedCurrent` and its callers, and the two tests
`ForkReceiptRecovery.t.sol` `test_forcedKickRefund_blocksPoolPricingUntilSynced` and
`ForkAllocationProof.t.sol` `test_activeCheckOnlyWhileKickableAndBounded`. Reviewer given the code,
the adversarial audit standard and the repository rules, not the builder's conclusions. Read-only.

Method: code reading; FWA's verified source; one live read
(`oracleExemptCollections(ShapePacks) == true`). The fork tests were not rerun by the reviewer
(Tenderly returned 429), so the builder's gas figures were not independently measured.

## Security

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| S1 | Low | Exemption lifted, kick refund force-sent with no receipt, exemption restored before sync: the exemption read skips the check and NAV counts the refund beside the booked position, one backing (0.0649 ETH) high per kick until `sync`. Not attacker-triggerable: needs two FWA owner actions around a failed `receive`. `checkpoint` is permissionless, so a third party can price in that window. The keeper itself syncs withdrawn listings before checkpointing (`keeper/policy.py`, `due`). | Accepted and documented (D84, U4). Closing it means scanning every open listing at every checkpoint. The owner declined that cost. |
| S2 | Low (known) | With the exemption lifted and more than 32 open listings, all pool pricing refuses, deposits included; in a healthy state only the owner's `startWindDown()` unblocks it. | Already accepted (D84, U4); the canary holds at most about 16. |

## Economic

| ID | Severity | Finding | Resolution |
|---|---|---|---|
| E1 | Info | An Allocated position sits in both `open` and the allocation queue, so the quote counts both iterations (6,000 gas each). Both loops do run, so this prices real work. `requestCharge` funds one 360,000 gas checkpoint, while a full proof can quote more; pay is capped by `processingPool`, so a large proof underpays the keeper and never overpays. | No change. Pre-existing for the allocation scan. Not reachable at canary scale with the exemption in place (0 open-listing reads). |

## Found sound

- FWA `kickListing` reverts while the collection is oracle-exempt (`ListingWithinFloorCap`), acts only on Active or Staged listings, sets `Withdrawn` and force-sends the value. The check (`!= LISTING_ACTIVE`) catches it.
- A kick is the only forced payment that can reach a never-allocated position. Keep, finalize and default pay only Allocated listings, which the allocation-queue scan covers.
- Every Active position is in `open`. Above 32 entries the proof refuses rather than scanning part of the list.
- `PackManager` never prices NAV; a forced kick there resolves through `_syncTerminal` (pack back to idle, backing removed).
- Both tests drive real FWA kicks and assert absolute amounts. The only cheatcode beyond setup etches the vault's own `receive` to fail. The counterfactual assertion (`navBefore + backing` with the exemption restored) is the S1 residual itself.
- Every vault call stays well under EIP-7825's 16,777,216 gas.

Limits: no full economic regime matrix; FWA behaviour as of its current implementation (an upgrade could change "exempt means no kick").
