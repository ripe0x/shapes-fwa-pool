# Main pool keeper and caller-funded recovery

One keeper codebase services the pooled vault and discovered personal managers independently.
`keeper/policy.py` is the canonical planner; the simulation imports it. Every account supplies its
own Params/GasSchedule and configuration hash. The external main payment policy is removed.

Normal work is paid for bounded measured gas. Verified counts cap the gas span; account-owned
overhead covers the unmetered transaction tail. Quotes are maximum envelopes.
The keeper estimates the exact signed calldata, pads 25%, enforces the transaction cap, simulates
minPay and inspects receipt status. Receipt gasUsed is the keeper expense; the gasleft span is gross before refunds. Both must be
reported. Actual compensation also respects tx.gasprice, class ceiling, configured priority,
actual service units and source/cash/budget limits (exit work is unpaid).
Configuration hydration and pending preflight must agree. Each receipt triggers a fresh read/plan.

```sh
python3 keeper/keeper.py <vault> --rpc https://mainnet.gateway.tenderly.co --status
python3 keeper/keeper.py <vault> [<manager>...] --factory <factory> --send --account <existing-keystore> --loop 300 --confirmations 2
```

Each account has a durable bounded event index; factory discovery advances incrementally.
Failed accounts retain visible status and do not stop the others. Pending deposit escrow, holder
claims and contribution pools/refunds remain distinct from ordinary keeper cash.
Cash shortage and exhausted spending permission are separate waits. A zero recipe mask never
falls back to minting; old inventory may relist unless listing is paused.

The production entrypoint accepts `FACTORY` without `VAULT`. For encrypted signing, supply
existing read-only files through `KEEPER_KEYSTORE_PATH` and `KEEPER_PASSWORD_FILE`.
It rejects the former secret-materializing environment transport. Existing Fly services and
secret stores are not changed by preparing this image. `KEEPER_FROM` is only for a loopback
Anvil on chain 31337; it cannot select an unlocked public-network signer.

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

For a personal manager, the current owner uses the same bounded exit mode:

```sh
python3 keeper/keeper.py <manager> --rpc https://mainnet.gateway.tenderly.co --send --account <existing-owner-keystore> --state <existing-owner-exit-state-path> --caller-funded-exit --exit-spend-limit-wei <accepted-additional-wallet-limit>
```

It first sets exit mode, then reconciles returns, unlists and redeems inventory, collects final
FWA fee credit and withdraws all remaining ETH to the owner. A blocked FWA queue is processed
in batches of 16 only when a real simulation reports progress; otherwise the owner waits for
authenticated randomness, the request deadline or the crown delay. No keeper payment or new
mint is assumed. Managers have no checkpoint contribution or share-pricing charge. Factory
discovery never adds other managers to an explicit caller-funded run. A prior pending growth
or foreign-account transaction must be resolved separately; exit mode preserves its tracking
and refuses to sign a replacement for it.

For local rehearsal use fresh checked Anvil-impersonated actors on chain 31337. No secret files are
created, no mainnet RPC is used for writes, and production keystore transport remains separate
unless an existing suitable signer is explicitly exercised. The production deployment path is the
same DeployCore path. Public broadcast/cutover stays outside this task.

Things that don't make sense until measured: permission can exceed available cash; required tiny
jobs can be uneconomic; a full exit needs an actual willing gas payer and may cross real FWA windows.

## Minimal paid work and migration

Paid actions are fresh pack build/listing, relisting actually returned packs, incremental discovery
of own allocations, terminal settlement reconciliation, bounded allocation pruning, necessary fee
collection inside sync, and necessary unlisting/redemption. The pooled vault additionally funds
required pricing/checkpoint work from request contributions. Standalone harvest, NFT recovery and
owner migration are unpaid. FWA's own acquisition processing is not an account keeper reward.
Pure no-op calls earn nothing; paid unused inputs revert. The ordinary bot retains a zero-loss
acceptance rule and does not assume that an owner will subsidize its gas.

Intact manager migration uses owner-paid `unlistForWithdrawal`, `withdrawPacks` (or checked
`withdrawRecoveryPack` for a sealed recovery entry) and `importPacks`. Keep both managers paused;
do not enter exit mode, which authorizes liquidation. The app checks ownership and destination
identity before each transaction and does not silently transfer wallet ETH.
