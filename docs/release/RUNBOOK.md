# PackVault mainnet canary: readiness and runbook

**Status: not approved for mainnet.** The candidate is built, verified and packaged. Public
deployment waits on the owner decisions in [Owner acceptance](#8-owner-acceptance). Nothing in this
document has been broadcast. This file replaces earlier current instructions; older documents
are history for their named candidates.

## 1. Candidate and artifact identities

| Item | Identity |
|---|---|
| Branch | `codex/incremental-position-integration` (PR ripe0x/shapes-fwa-pool#2, draft) |
| Release commit and manifest | named in [acceptance.json](acceptance.json): `commit`, `manifest_sha256` |
| Manifest | [deploy/release-manifest.json](../../deploy/release-manifest.json): source hashes, toolchain, normalized runtimes, values, keeper inputs, evidence |
| Compiler | solc 0.8.30, optimizer 200 runs, via IR, Cancun, no metadata hash; `lib/` tree pinned by git |
| PackVault | 24,489 runtime bytes (87 under EIP-170); initcode 27,262 |
| VaultLib | 24,304 runtime bytes (272 under); CREATE2 address `0xFb4f180f662f1c159D5eD7b99B76d32D45b19D43` (salt 0, factory `0x4e59…956C`) |
| KeeperPolicyV1 | 216 runtime bytes |
| Keeper image | `keeper/Dockerfile`, Python 3.12, cast/Foundry 1.8.1 (`FOUNDRY_DIR` pinned), dependencies pinned in `keeper/requirements.txt` |
| Deployment values | [deploy/canary.json](../../deploy/canary.json) |

`python3 script/release.py check deploy/canary.json` recomputes every hash and fails on any
difference, including uncommitted inputs. `script/deploy.sh` runs it before every public broadcast.

## 2. Gate results

### Engineering

| Gate | Result | Evidence |
|---|---|---|
| Clean build, both runtimes under 24,576 bytes | pass | `script/verify.sh` log, manifest |
| All contract, audit, research and fork suites; 16 asset-flow regimes; both fork reconciliations to the wei | see [acceptance.json](acceptance.json) `engineering.full_suite` | `docs/receipts/release-verify/` |
| Python model, policy and index tests | pass | same |
| Independent review of accounting and keeper changes since e9cee61 | no defects; three items for owner sign-off (section 8) | [review](../receipts/release-review.md) |
| Largest reachable sync: 128-record journal | 2,540,933 gas, padded 3,176,166 of 16,777,216 | [coverage](../receipts/allocation-burst-coverage.md) |
| Largest combined sync (128 + 16 own + 16 terminal + 16 prune + collection) | **bound, not a receipt**: 8,461,000 quoted, padded 10,576,250 | same |
| More than 16 simultaneous own allocations | **not reachable** by authentic VRF replay; keeper discovery across 18 real returned packs with restart and reorg passes | same |
| Fresh-block rehearsal at 26,450,200 (`0xda70…abc5`): deploy, list 25, holder exits, owner wind-down | pass | [release-rehearsal](../receipts/release-rehearsal/result.json) |
| Production image on a fresh fork: keystore signing, replacement on the same volume, lost RPC response, backup | pass (CI run 44577532617) | [image-rehearsal](../receipts/image-rehearsal/ci-44577532617.json) |

### Economic (owner requirements A.3, A.8, A.10; B2 "holder return")

Actual trailing 30 days to block 26,450,200: **11,604 successful acquisitions (386.8 a day)**, 5,090
refunded, replayed for 360 days plus exit, tokens at zero, every expense, complete claims only.
After D75 (scan proof); detail in [KEEPER-ECONOMICS.md](../KEEPER-ECONOMICS.md).

| Gate | Result |
|---|---|
| ≥10% a year net at 0.5 gwei, canary 1.96 ETH (400 seeds) | **pass**: median +40.5%, mean +62.7%; p10 −62%, 33% of years lose (selection luck) |
| Same at 6.8 ETH (32 seeds) | pass: median +68.9%, p10 +1.3%, 9% lose |
| Same at 20 ETH (32 seeds) | pass: median +41.2%, p10 +16.3%, 3% lose |
| At least one usable exit window a day | pass: 30 of 30 days |

Before D75 the canary failed (median −5.3%): 1.2 ETH a year paid keepers to read every global
FWA acquisition on-chain.

## 3. Deployment configuration and funding

| Value | Canary (`deploy/canary.json`) | Mainnet (`deploy/mainnet.json`, later) |
|---|---|---|
| Owner | `0xCB43078C32423F5348Cab5885911C3B5faE217F9` (one hot EIP-7702 key; see B3) | same |
| TVL cap | 2 ETH | none |
| Routine budget | 0.03 ETH, refills 0.01 ETH a day | 0.1 ETH, 0.02 ETH a day |
| Essential budget | 0 (exit work is caller funded) | 0 |
| Gas ceiling / essential / tip | 0.5 / 2 / 0.05 gwei | same |
| Work fee, reserve, seed | 0.00002 ETH, 0.005 ETH, 0.01 ETH | same |

Spending bounds (wei facts are in `src/VaultLib.sol` and tests):

- Routine pay, canary: at most 0.04 ETH in the first 24 h, then 0.01 ETH a day (0.33 ETH in 30 days). Mainnet: 0.12, then 0.02 a day.
- Contract maxima: routine 0.3 ETH cap and 0.02 ETH a day, essential 0.1 ETH and 0.005 ETH a day. Raising caps never refills at once, so a compromised owner can take at most the current balance plus 0.025 ETH a day: about **0.055 ETH in the first 24 h** at canary settings.
- Checkpoint pay is separate: paid only from `processingPool`, which request charges fund. At most once per 12 h interval: 360,000 gas at the 2 gwei essential ceiling plus one work fee, **0.00074 ETH per checkpoint** (0.01805 ETH at the 50 gwei maximum).

Funding before deployment: deployer holds the 0.01 ETH seed plus deployment gas, **11,096,220 gas**
measured (VaultLib 5,318,397, KeeperPolicyV1 100,155, PackVault 5,677,668): 0.0055 ETH at
0.5 gwei, 0.022 ETH at 2 gwei. The live simulation on 2026-11-19 (`script/deploy.sh deploy/canary.json`,
sender = owner) passed postflight; Forge's padded estimate was 14,857,203 gas and 0.01112 ETH
including the seed at a 0.75 gwei max fee. Primary keeper wallet 0.05 ETH, backup 0.02 ETH.

## 4. Commands

Simulation (sends nothing; prints the release check, gas and the onchain postflight in simulation):

```bash
FORGE_WALLET_ARGS="--sender <deployer>" script/deploy.sh deploy/canary.json
```

Verification of the candidate (long; Tenderly throttles):

```bash
script/verify.sh
```

Future public deployment, only after section 8 is signed and the owner authorizes the broadcast.
`deploy.sh` refuses unless the release check and the owner's signature verify, then runs the onchain
postflight and prints the Etherscan verification commands:

```bash
FORGE_WALLET_ARGS="--account <keystore> --sender <deployer>" script/deploy.sh deploy/canary.json --broadcast
```

Postflight again at any time (runtime identities, library link, owner, policy, every parameter,
budgets, seed shares, flags, seed balance):

```bash
python3 script/release.py postflight <vault> deploy/canary.json
```

Etherscan verification (printed by postflight with real addresses):
`forge verify-contract <lib> src/VaultLib.sol:VaultLib --chain mainnet --watch`, likewise
`src/KeeperPolicy.sol:KeeperPolicyV1`, and `src/PackVault.sol:PackVault --guess-constructor-args --libraries src/VaultLib.sol:VaultLib:<lib>`.

## 5. Keepers

1. Write the deployed address into both Fly configs; this refuses unless postflight passes:
   `python3 script/release.py keeper-config <vault> deploy/canary.json`. Until then both files hold the
   zero address and the entrypoint refuses to start.
2. Create two keys: `cast wallet new ~/.foundry/keystores` (separate primary and backup). Fund them.
3. Per config (`fly.keeper-primary.toml`, every 60 s, iad; `fly.keeper-backup.toml`, hourly, ams):
   `fly volumes create keeper_state --size 1`, then the secrets exactly as in the toml header (keystore
   JSON and password, never a raw key), then `fly deploy --config <toml>`.
4. Persistence: transaction state `/data/keeper-state.json` and event index `/data/keeper-index.sqlite`
   survive restarts and machine replacement (proven in CI). A first start reconstructs the index over
   several passes (`INDEX_CATCHUP`).
5. Monitoring: `GET :8788/health` inside the machine (ok, last pass, status codes, tx stats);
   `python3 keeper/keeper.py <vault> --status` from anywhere. Both workers can race for the same work;
   the loser reverts and pays its gas (seen in CI on a checkpoint). The hourly backup keeps that rare.

## 6. Holder and owner workflows

Holder exit, permissionless, holder pays every gas (rehearsed: claims 1.974983 of 1.990182 ETH
paid in, loss 0.81% with no selections; 8 exit calls cost the holder 0.000878 ETH):

```bash
# charge = requestCharge() (unwindCharge() is 0 with no essential budget); any excess is refunded
cast send <vault> "requestRedeem(uint256)" <shares> --value "$(cast call <vault> 'requestCharge()(uint256)' | cut -d' ' -f1)" --account <holder>
python3 keeper/keeper.py <vault> --send --account <holder> --max-loss-wei 2000000000000000 --max-total-loss-wei 10000000000000000
# after the next blackout checkpoint (the normal keeper runs it, paid from the request charge):
cast send <vault> "claim()" --account <holder>
```

`keeper.py` with a loss limit runs the unpaid unlisting and liquidation the redemption needs, one
receipt-checked call at a time, and stops at the per-call or total limit. No owner action or
allowlist is involved. Repeat for partial and complete redemptions.

Owner wind-down (one way): `cast send <vault> "startWindDown()" --account <owner>`, then the owner (or
any holder) runs the same `keeper.py` command to unwind, the keeper checkpoints, holders claim.
Rehearsed: 0 positions left, 0.010031 ETH seed residue.

## 7. Pause and recovery conditions

| Condition (read each pass or daily) | Action |
|---|---|
| `address(vault).balance < pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool` | owner `startWindDown()`; investigate |
| Keeper pay above 0.04 ETH in 24 h (canary) | owner sets routine cap and rate to 0 via `setParams`; investigate |
| Any keeper revert that is not a lost race | stop that worker; read its state file |
| FWA changes fees, oracle, exemption, minimum backing or settlement windows | keeper re-reads live; if listing stops (`QUOTE_UNAVAILABLE`), positions stay redeemable; decide on wind-down |
| `MAINTENANCE_UNFUNDED` (cash or permission named) | new exposure already waits; add permission (`setParams`) only if cash exists; otherwise let exits proceed |
| Redemption not priced within two blackouts with a drained queue | holder or owner runs the exit command above |
| Gas above 0.5 gwei | routine work waits by design; holders may still exit at their own gas |

## 8. Owner acceptance

All remaining items are listed with their numbers in [acceptance.json](acceptance.json) and
[ACCEPTANCE.md](ACCEPTANCE.md). Signing that file's sha256 (namespace `packvault-release`, key in
`deploy/allowed_signers`) accepts all of them; `deploy.sh` checks the signature. The 2026-11-17
asset-flow signature covers an older candidate and is kept as history only.
