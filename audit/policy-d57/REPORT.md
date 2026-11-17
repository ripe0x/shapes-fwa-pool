# Keeper payment policy (D56, D57): independent reviews

Source hash: see `SOURCE_HASH` (`asset_gate.py --print-source-hash`). Two independent reviewers,
read-only, given the code and the owner's brief, not the implementer's conclusions. Neither ran
the fork suites (Tenderly throttling); findings are from code and arithmetic, then reproduced and
fixed by the implementer with fork tests.

## Security review

Policy payment is bounded: `VaultLib.pay` pays `min(offer, envelope, cap, free, budget)`; the policy
is reached only by a 50,000-gas `staticcall` reading one word, so no policy (reverting, gas-burning,
odd return, or a proxy changing after activation) can pay above the envelope, touch a liability or
reenter. The corrected `offer` Yul is right (call result bound before `returndatasize`). `_free()`
excludes every liability. The guardian is stop-only. Budget casts are safe.

| Id | Severity | Finding | Resolution |
|---|---|---|---|
| H1 | High | `PendingDeposit.charge` was uint64; a deployment charge above 18.4 ETH truncated, so shares minted on more than the checkpoint added to the supply, and cancel could leave `pendingChargeTotal` above `pendingDepositTotal`, reverting every later checkpoint with deposits | Fixed: `uint96 amount, uint64 epoch, uint96 charge`; `test_largeDepositChargeNotTruncated` (20.5 ETH charge) |
| L1 | Low | `lowerCaps` could leave `maxTip` above the lowered ceiling (inflates the deployment charge only) | Fixed: `lower` clamps `maxTip`; asserted in `test_guardianCancelsPendingPolicy` |
| I1 | Info | `activatePolicy` does not re-check the policy; one that loses its code before activation offers 0 | Accepted: liveness only; work still runs unpaid; admin re-proposes |

Manufactured work (self-deposit, dust, split, repeat) yields no profit: checked against restock,
list, activate, harvest and checkpoint paths.

## Economic review

No accounting error in the envelope, policy and charge math; `keeper/policy.py` and `sim/vault.py`
match the Solidity. Gates (`cycleNet`, the restock build, the 25% harvest gate) use the envelope, so
a cheaper policy cannot loosen them; markup 0 keeps the envelope equal to V1's pay.

| Check | Result |
|---|---|
| Quoted gas vs billed | 3% to 19% under billed by design (split-proof bases); the 0.05 gwei tip allowance and the work fee cover it below about 0.45 gwei basefee |
| Keeper at or above the ceiling | single-unit list, unlist, checkpoint and restock-from-loose lose (list 1: -17 µETH); batches stay positive longer |
| Manufactured paid work | none profitable |
| Holder round trip | 1.1% to 1.9% (1 to 2 ETH); 5.9% to 13.3% for a 0.01 ETH deposit (fixed checkpoint charges) |
| Worst keeper spend | canary 0.041 ETH / 24 h, 0.405 ETH / year; maxima 0.415 / 24 h, 5.875 / year |

Owner notes (not defects): a checkpoint loses money for its caller at the ceiling; the 0.5 gwei
ceiling idles routine work at typical mainnet gas; batched depositors each pay a full checkpoint
charge; cancelling forfeits the checkpoint charge; about 0.5% of NAV-lifting charges accrue to the
dead shares.

## Limits

These reviews do not establish that the code is safe or that review was exhaustive. Acquisitions
selecting vault listings are exercised only in Solidity fork tests with real VRF replays, not in
the keeper rehearsal.
