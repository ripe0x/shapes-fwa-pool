# Mainnet canary plan (launch step E) — DRAFT for owner approval

Nothing here is authorized until the owner approves it in writing. Every broadcast below needs its
own confirmation immediately before sending: chain, signer, target, decoded arguments, value and
consequence (chain operations rule 2).

## Preconditions (all must hold)

1. Audit B and the A/B comparison are complete, every executed finding is repaired or explicitly
   accepted by the owner, and the candidate commit is frozen.
2. The owner has signed the current asset-flow outcomes (`asset_gate.py` reports PASS).
3. `keeper/rehearse_current.py` passes on a fork of the block the deployment will use: positions
   listed, ledger closes to the wei, zero reverted keeper transactions.
4. Owner key: `0xCB43…17F9`, a Calibur (Uniswap wallet) EIP-7702 account. Accepted risk B3 assumed a
   multisig or hardware wallet; this is a single hot key, so the owner-compromise bound depends on it.
5. Keeper key: a fresh hot wallet funded with at most 0.05 ETH, used only by `keeper/keeper.py`.

## Deployment (one command, three transactions)

- Values: `deploy/canary.json` (owner `0xCB43078C32423F5348Cab5885911C3B5faE217F9`, a Calibur
  EIP-7702 smart-wallet EOA; seed 0.01 ETH; stage 1 caps 0.5 ETH and 10 positions).
- The one deploy path: `script/deploy.sh` runs `script/Deploy.s.sol`, which deploys through
  `DeployCore` (the same code every fork and scenario test and both rehearsals deploy with) and
  runs its postflight (owner, policy, every parameter, budgets, seed shares, flags).
- Simulate first (sends nothing; prints the gas estimate):
  `FORGE_WALLET_ARGS="--sender <deployer>" script/deploy.sh deploy/canary.json`
  Dry run on 2026-11-17: postflight passed, 10,410,290 gas, about 0.0024 ETH at 0.116 gwei, plus
  the 0.01 ETH seed (VaultLib, KeeperPolicyV1, PackVault).
- Broadcast, signed with a keystore or hardware wallet, never a raw key:
  `I_AM_THE_OWNER=yes FORGE_WALLET_ARGS="--account <name> --sender <deployer>" script/deploy.sh deploy/canary.json --broadcast`

## Keepers (apeball's setup)

The apeball bot itself is game-specific; this vault reuses its infrastructure: a primary
(`fly.keeper-primary.toml`, iad, every 60 s) and a backup (`fly.keeper-backup.toml`, ams, hourly)
built from `keeper/Dockerfile`, separate keys, a volume for the transaction manager's state.
Keys are encrypted keystores plus a password, as Fly secrets (never a raw key). Before mainnet, run
the keeper once against a local fork with the real keystore (`--keystore`, `--password-file`): the
container's keystore path is not exercised by the tests.

## Stages

| Stage | TVL cap | Positions | Runs until | Then |
|---|---|---|---|---|
| 1 | 0.5 ETH (owner deposit only) | 10 | one full cycle: deposit, priced, built and listed, one real selection resolved and relisted, a partial redemption claimed | owner raises cap |
| 2 | 2 ETH | 30 | 14 days or 5 real selections, whichever is later | review against the scorecard |

Stage 1 sets `tvlCap` 0.5 ETH and `maxPositions` 10 in the deploy values; stage 2 raises them with
`setParams` (immediate, D58).

## Checks read from the live chain (each keeper pass and daily)

| Outcome | Live check | Band |
|---|---|---|
| Liabilities never spent (O5) | `address(vault).balance >= pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool` | always |
| Keeper pay bounded (O2) | sum of `KeeperPaid` per day | <= 0.031 ETH in any 24 h (routine only; exits unpaid, D64) |
| Backing rule (D62) | backing of each new listing | 0.0333 to 0.0363 ETH at canary gas |
| Exits work (O3, O6) | each redemption priced within 2 blackouts after the withdrawer (or owner, in wind-down) runs the unpaid unlist and liquidate steps | always |
| No staging by the keeper (O10) | keeper listings with FWA status Staged | 0 |
| Holder cost (O9) | holder result after a round trip with no selections | > -1.5% |
| Keeper P&L | keeper state file: spent vs paid | no unaccepted loss |

## Stop conditions (owner calls `startWindDown()` or pauses)

Any of: a liability check fails; keeper pay above its band; a keeper transaction reverts for a
reason other than state moving on; a listing posted outside the backing band; FWA's owner changes
fees, the oracle, exemption, minimum backing or settlement rates (read each pass); a holder
redemption not priced within 2 blackouts with a drained queue; any unexplained balance change.
Wind-down is one way; holders redeem and claim as usual (they keep their shares until they do).

## What cannot be capped

- FWA's owner can change fees, the oracle, the exemption and settlement rates at any time; the vault
  reads them live. The worst observed effect in testing is listing pausing, not loss of holder ETH.
- A compromised owner key: at most the budgets' balance plus refill (about 0.045 ETH the first day,
  0.015 ETH a day after) until wind-down (B3).
- Real VRF timing, transaction ordering and the gas market: covered only by running the canary.

## After the canary

Compare live results with the scorecard; record measured times per phase; raise caps only with a
new owner decision.
