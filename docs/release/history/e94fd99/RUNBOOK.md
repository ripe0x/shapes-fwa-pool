# Unified candidate: release runbook

**Status: not approved for mainnet.** The unified candidate (PR ripe0x/shapes-fwa-pool#5) is built,
verified and packaged unsigned. Nothing in this document has been broadcast. This file replaces the
earlier runbook (PR #2 candidate), which is kept in git history.

Two separate authorizations are needed, and neither follows from the other:

1. **Deploy the contracts** (the pooled vault and the factory). Signing the acceptance package
   ([acceptance.json](acceptance.json)) and authorizing the broadcast covers this only.
2. **Offer personal managers publicly.** The factory is permissionless once deployed, but nothing
   advertises it: no frontend, no announcement, and the keepers do not serve managers unless
   `FACTORY` is set in their Fly secrets. Turning that on is a later owner decision (section 9).

## 1. Candidate identity

| Item | Identity |
|---|---|
| Branch | `claude/unified-shapes-fwa-system-852d17` (PR ripe0x/shapes-fwa-pool#5, draft) |
| Release commit and manifest | named in [acceptance.json](acceptance.json): `commit`, `manifest_sha256` |
| Manifest | [deploy/release-manifest.json](../../deploy/release-manifest.json): source hashes, toolchain, normalized runtimes of PackVault, PackManager, PackManagerFactory, KeeperPolicyV1 and the libraries ScanLib, VaultLib, StrategyLib; deploy values; keeper image inputs; evidence |
| Compiler | solc 0.8.30, optimizer 200 runs, via IR, Cancun, no metadata hash; `lib/` pinned by git |
| Runtime sizes (EIP-170 limit 24,576) | PackVault 16,960; VaultLib 23,482; StrategyLib and ScanLib in the manifest; PackManager 12,494 (each clone 44); PackManagerFactory 1,365; KeeperPolicyV1 216 |
| Keeper image | `keeper/Dockerfile` (Python 3.12, Foundry 1.8.1 pinned, `keeper/requirements.txt` pinned); fork rehearsal passed in CI run 44948198556 |
| Deploy values | [deploy/mainnet.json](../../deploy/mainnet.json); manager defaults [deploy/manager.json](../../deploy/manager.json) |

`python3 script/release.py check deploy/mainnet.json` recomputes every hash and fails on any
difference. `script/deploy.sh` runs it, and with `--broadcast` also verifies the owner's signature.

## 2. Evidence

| Gate | Result | Receipt |
|---|---|---|
| Full candidate run (`script/verify.sh`) | at 3b4d9b3: 279 fork tests passed, 1 opt-in exporter skipped; scale 3/3; reconciler to the wei on three paths | [unified-verify/SUMMARY.md](../receipts/unified-verify/SUMMARY.md) |
| Asset flow, 16 regimes, outcomes O1-O11 | all pass; unsigned | [asset-flow.json](../../asset-flow.json), `docs/receipts/flow/` |
| Local production rehearsal (fresh fork) | all 17 steps pass on the final source (one warm fork, upstream Alchemy while Tenderly throttled) | [unified-production-rehearsal.json](../receipts/unified-production-rehearsal.json), [selection](../receipts/unified-selection-rehearsal.json) |
| Production image on a fresh fork (CI) | pass, vault and one factory manager served together | [ci-44948198556.json](../receipts/image-rehearsal/ci-44948198556.json) |
| Independent review | no critical, high or medium; the low kick residual is now fixed (D84) | [unified-review.md](../receipts/unified-review.md) |
| Independent review of the kick fix (b63d87a) | no critical, high or medium; one low residual across an exemption restore, accepted (D84, U4) | [kick-fix-review.md](../receipts/kick-fix-review.md) |
| Launch audit A (informed, b0e9c12) | R1 release-check binding repaired and re-attacked; E1, E2, S1 and the D84 test gap open | [launch-audit-A-repairs.md](../receipts/launch-audit-A-repairs.md) |
| Launch audits A and B compared (step C) | owner-key bound, O9 at maximum load and purchaser gas need owner decisions; stranded request charge and unsolicited pack need repairs | [launch-audit-comparison.md](../receipts/launch-audit-comparison.md) |
| Holder return (formal gate) and recipe comparison | see acceptance.json `economic` | [formal-assessment.json](../receipts/formal-assessment.json), [recipe-comparison.json](../receipts/recipe-comparison.json) |

## 3. Deployment values

| Value | Mainnet (`deploy/mainnet.json`) |
|---|---|
| Owner | `0xCB43078C32423F5348Cab5885911C3B5faE217F9` (owner-key risk accepted, B3) |
| Deposit cap | none (`tvlCapWei` is the uint128 maximum) |
| Seed | 0.01 ETH, minted to dead shares at deployment |
| Recipe | 0.06 ETH packs only (`packUnitsMask` 64): one 0.05 and one 0.01 Shape, two paid mints |
| Backing | 0.06489617486338 ETH, fixed by the rule (D80, D85) |
| Routine budget | cap 0.1 ETH, refills 0.02 ETH a day |
| Essential budget | 0 (redemption and wind-down work is run by withdrawers at their own gas) |
| Gas ceiling / essential / tip | 0.5 / 2 / 0.05 gwei |
| Work fee, reserve | 0.00002 ETH, 0.005 ETH |
| Allocated bound | 10% of NAV |

Spending bounds: routine keeper pay at most 0.12 ETH in the first 24 hours, then 0.02 ETH a day.
Checkpoint pay comes only from request charges (`processingPool`), at most one checkpoint per 12-hour
interval: 360,000 gas plus at most 32 allocation entries and, while the oracle exemption is lifted,
32 open listings (6,000 gas each), and their FWA reads (30,000 each), at the 2 gwei essential ceiling, plus one work fee.

## 4. Funding and deployment gas

| Item | Amount |
|---|---|
| One-time deployment, billed on a local fork through `script/deploy.sh` | **16,070,106 gas**: ScanLib 719,323; VaultLib 5,157,757; StrategyLib 2,817,411; KeeperPolicyV1 100,155; PackVault 4,144,141; PackManagerFactory with its implementation 3,131,319 |
| Deployment cost | 0.0080 ETH at 0.5 gwei, 0.0321 ETH at 2 gwei (send the larger plus the 0.01 ETH seed) |
| Deployer | holds the seed plus deployment gas |
| Primary keeper wallet | 0.05 ETH |
| Backup keeper wallet | 0.02 ETH |
| A personal manager, later | 474,175 gas to create (about 0.00024 ETH at 0.5 gwei), no fee |

## 5. Commands

Simulation (sends nothing):

```bash
FORGE_WALLET_ARGS="--sender <deployer>" script/deploy.sh deploy/mainnet.json
```

Candidate verification (long; Tenderly throttles):

```bash
script/verify.sh
```

Public deployment, only after acceptance.json is signed and the owner authorizes the broadcast.
`deploy.sh` refuses unless the release check and signature verify, then runs the onchain postflight
and prints the Etherscan verification commands:

```bash
FORGE_WALLET_ARGS="--account <keystore> --sender <deployer>" script/deploy.sh deploy/mainnet.json --broadcast
```

Postflight at any time (runtime identities, library links, owner, policy, every parameter, budgets,
seed shares, factory and its implementation):

```bash
python3 script/release.py postflight <vault> deploy/mainnet.json <owner> <factory>
```

## 6. Keepers

1. Write the deployed vault into both Fly configs (refuses unless postflight passes):
   `python3 script/release.py keeper-config <vault> deploy/mainnet.json`.
2. Two keystores: `cast wallet new ~/.foundry/keystores` (primary and backup, separate). Fund them.
3. Per config (`fly.keeper-primary.toml`, every 60 s; `fly.keeper-backup.toml`, hourly): create the
   `keeper_state` volume, set the secrets named in the toml header (keystore JSON and password, never
   a raw key), `fly deploy --config <toml>`. Leave `FACTORY` unset until managers are offered (section 9).
4. State: `/data/keeper-state.json` and one event index per account (`/data/index-*.sqlite`) survive
   restarts and machine replacement (rehearsed locally and in CI).
5. Health: `GET :8788/health` inside the machine; `python3 keeper/keeper.py <vault> --status` anywhere.
   Primary and backup can race for the same work; the loser's transaction reverts and costs its gas.

## 7. Holder and owner workflows

Holder exit, permissionless, holder pays the gas. `requestCharge()` is quoted at the basefee when the
call runs, so pay with headroom; the excess is refunded in the same call:

```bash
cast send <vault> "requestRedeem(uint256)" <shares> --value "$(( 2 * $(cast call <vault> 'requestCharge()(uint256)' | cut -d' ' -f1) ))" --account <holder>
python3 keeper/keeper.py <vault> --send --account <holder> --max-loss-wei 2000000000000000 --max-total-loss-wei 10000000000000000
# after the next blackout checkpoint (the keeper runs it, paid from the request charge):
cast send <vault> "claim()" --account <holder>
```

Owner wind-down (one way): `cast send <vault> "startWindDown()" --account <owner>`, then the same
`keeper.py --send` command unwinds, the keeper checkpoints, holders claim.

## 8. Monitoring and pause conditions

| Condition | Action |
|---|---|
| Balance below `pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool` | owner `startWindDown()`; investigate |
| `pendingReceipts()` nonzero for more than one keeper pass, or the checkpoint refusing with `PendingReceipts`/`CatchUpFirst` for more than one settlement window | read the keeper log; the next `sync` resolves it (D84) |
| A settled listing whose `receipts(id)` is empty (a payment FWA force-sent) | expected to be resolved by the next sync; investigate why `receive` failed (gas repricing?) and pause new exposure |
| Keeper pay above 0.12 ETH in 24 hours | owner sets routine cap and rate to 0 via `setParams`; investigate |
| Any keeper revert that is not a lost race | stop that worker; read its state file |
| FWA lifts the ShapePacks oracle exemption, moves its bid above about 94.4%, or changes fees or windows | new listings stop on their own (`QUOTE_UNAVAILABLE` / edge not ok); exits are unaffected; decide on wind-down. With the exemption lifted, pricing also checks every open listing up to 32 (D84) |
| `EXPOSURE_SHARE` above 10% of FWA selection weight | owner decision on a cap (D81) |
| Gas above the 0.5 gwei ceiling | routine work waits by design; holders may still exit at their own gas |

## 9. Personal managers

Activating public personal managers (a separate authorization from deploying the factory):
re-run the manager rehearsal against the deployed factory on a fork, set `FACTORY` in both keeper
Fly configs, publish `deploy/manager.json` as the default parameters, and announce. Until then the
factory exists but is unadvertised and unserved.

## 10. Owner acceptance

Items needing the owner are listed with numbers in [acceptance.json](acceptance.json) and
[ACCEPTANCE.md](ACCEPTANCE.md). Signing that file's sha256 (namespace `packvault-release`, key in
`deploy/allowed_signers`) accepts them; it authorizes no broadcast, funding or Fly deployment by
itself. Earlier signatures cover earlier candidates and are kept as history only.
