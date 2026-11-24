# Main pool keeper and caller-funded recovery

One keeper codebase services the pooled vault and discovered personal managers independently.
`keeper/policy.py` is the canonical planner; the simulation imports it. Every account supplies its
own Params/GasSchedule and configuration hash. The external main payment policy is removed.

Normal work is paid by verified counts and quoted allowances, not measured gas reimbursement.
The keeper estimates the exact signed calldata, pads 25%, enforces the transaction cap, simulates
minPay and inspects receipt status. Actual billed gas is a separate calibration/viability measure.
Configuration hydration and pending preflight must agree. Each receipt triggers a fresh read/plan.

```sh
python3 keeper/keeper.py <vault> --rpc https://mainnet.gateway.tenderly.co --status
python3 keeper/keeper.py <vault> [<manager>...] --factory <factory> --send --account <existing-keystore> --loop 300 --confirmations 2
```

Each account has a durable bounded event index; factory discovery advances incrementally.
Failed accounts retain visible status and do not stop the others. Pending deposit escrow, holder
claims, contribution pools/refunds and renewal float remain distinct from ordinary keeper cash.
Cash shortage and exhausted spending permission are separate waits. A zero recipe mask never
falls back to minting; old inventory may relist unless listing is paused.

Explicit holder-funded exit, using the holder's existing signer and a stated gross spending cap:

```sh
python3 keeper/keeper.py <vault> --send --account <holder-keystore> --caller-funded-exit --exit-spend-limit-wei <accepted-limit> --refund-contributions <known-ids>
```

The CLI handles pending cancellation, redemption request, required bounded maintenance, settlement
recovery, unlisting, liquidation, checkpoint funding, partial fills and claims. Necessary recovery
uses unpaid contract paths; the holder accepts wallet gas instead of assuming keeper service.
The limit is checked again against the final signed maximum and replacements. Durable state retains
the maximum reserved spend for each chain/sender/nonce, including replacement increases. A receipt,
revert or reorganization never releases that reservation. Actual wallet cost is reported separately.
Each invocation limits additional reservations relative to its starting state. Legacy state without
recoverable signed maxima fails closed; use a separate explicitly selected state path rather than
overwriting it. A window or external settlement wait requires a later explicit run with its own
stated limit. No automatic new funding or signature is implied. Refund IDs are discovered from
payer events; claims never enumerate payers.

The app applies the same monotonic reservation rule. A user can override fees directly in their
wallet; the app cannot prevent that external action. It detects a larger replacement, reserves the
increase and blocks further steps if the stated limit is exceeded, until the user explicitly raises it.

For local rehearsal use fresh checked Anvil-impersonated actors on chain 31337. No secret files are
created, no mainnet RPC is used for writes, and production keystore transport remains separate
unless an existing suitable signer is explicitly exercised. The production deployment path is the
same DeployCore path. Public broadcast/cutover stays outside this task.

Things that don't make sense until measured: permission can exceed available cash; required tiny
jobs can be uneconomic; a full exit needs an actual willing gas payer and may cross real FWA windows.
