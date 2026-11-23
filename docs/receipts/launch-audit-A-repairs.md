# Launch audit A: repairs

Audit A examined b0e9c12 (informed, whole candidate). This file records repairs and their re-attacks.

## R1: release check did not bind the deployed artifacts (repaired, a8b722e and d47c121)

Before: `script/deploy.sh` ran `release.py check` against the existing `out/` artifacts, then
`forge script` could recompile under an inherited `FOUNDRY_*` override or compiler flags passed in
`FORGE_WALLET_ARGS`, so a passing check could precede a broadcast of other bytecode.

Repair: `deploy.sh` runs `forge build` in its own environment before the check, and
`FORGE_WALLET_ARGS` accepts signer flags only (`--account`, `--sender`, `--keystore`,
`--password-file`, `--hd-paths`, `--ledger`, `--trezor`). Runtime build unchanged; manifest
`3a3e6cf9…` differs from the previous one only in the `script/deploy.sh` hash.

Re-attack, simulation on a local Anvil fork of mainnet (block 26,464,000), fresh funded deployer:

| Case | Result |
|---|---|
| `FORGE_WALLET_ARGS="--sender <deployer> --optimizer-runs 1"` | refused before compiling: `--optimizer-runs is not a signer flag`, exit 1 |
| `FOUNDRY_OPTIMIZER_RUNS=1` | check reports `build differs from the manifest` for PackManager, PackManagerFactory, PackVault, ScanLib, StrategyLib, VaultLib; `forge script` then skips compilation, so it would deploy the artifacts the check rejected. On a non-local broadcast that failure refuses |
| No override, committed manifest | `release check passed`, compilation skipped, postflight passed, simulation complete |

Limit: the non-local `--broadcast` refusal itself was not executed (it needs a non-Anvil chain and
the owner's signature); it is the existing `|| exit 1` branch, now preceded by the same build.

Open from audit A (owner decisions or later work): E1 purchaser gas by pack size, E2 owner-key
bound, S1 manager discovery bound, and the D84 forced-receipt tests that etch or fund the vault.
