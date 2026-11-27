# Manager-only unsigned deployment and operations

**Current step: prepare and review an unsigned manager-only package.** The strategy is reuse-only with bounded measured keeper compensation. The numerical candidate, including **50,000 gas overhead**, remains provisional. No public transaction, signature, acceptance, live keeper cutover or merge is authorized by this record. The shared vault is undeployed and its application remains closed.

The complete 21-scalar/29-gas schema, values, bounds and opening arithmetic are in [SETTINGS.md](SETTINGS.md). [OWNER-REQUIREMENTS.md](../../OWNER-REQUIREMENTS.md) supersedes the historical fixed-quote and Fresh renewal design. [REPORT.md](../REPORT.md) records current verification; receipt claims must retain their exact source and configuration.

## Scope and money

One manager owns its assets and uses the shared PackAccount/StrategyLib/VaultLib/ScanLib strategy. The ownerless factory creates an immutable implementation and personal clones; it has no authority to change an existing manager's owner or economics. Owner numerical controls act immediately within bounds. Algorithm changes require a new deployment and actual asset migration.

The current recipe is 0.03 ETH principal from three primary Shapes, with mask bit 3 and nominal separate backing of 0.21 ETH. Returned packs are relisted intact. A kept pack leaves inventory, and any replacement is a normal build using actual cash and permission. There is no Fresh mode, renewal float, replacement-eligibility balance or paid retirement/remint path.

The accepted and live Shapes mint fee is 0.0005 ETH per Shape (`acceptedMintFeeWei` 500,000,000,000,000 in [manager.json](../../deploy/manager.json)). At block 26,508,708 the signer nonce was **4259** and the owner/signer wallet held **0.007998370385103725 ETH**. Earlier nonce-4180 and nonce-4181 packages remain in Git history and [manager-unsigned-history](../../deploy/manager-unsigned-history/). The 0.5 ETH creation template is an evaluation funding amount, not a contract minimum or return recommendation; this wallet cannot fund it now (it lacks about 0.492 ETH plus wallet gas).

At zero markup, the maximum one-pack build/list funding envelope plus reserve is 0.246925 ETH at 0.2 gwei or 0.2475025 ETH at 0.5 gwei using the observed fee. Using the accepted maximum gives 0.248425 / 0.2490025 ETH. Wallet creation gas is separate. Actual compensation uses bounded measured work and can be lower; these envelopes are not billed costs or profit predictions.

## Production path and recorded unsigned result

Deployment inputs are [manager-factory.json](../../deploy/manager-factory.json) for dependencies and [manager.json](../../deploy/manager.json) for manager economics. The manager target deploys libraries and PackManagerFactory with its implementation. It deploys no PackVault, transfers no seed and creates no funded manager.

The wrapper compiles its actual deploy inputs, checks the manifest, and then simulates through the same DeployCore production path. A simulation reports a failed release gate and continues; it is not release acceptance. Do not add a second build merely for documentation changes.

Recorded preparation commands, using the existing Git and deployment identities and Python 3.11.8:

```sh
/Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py manifest --target manager

CANDIDATE_RUN=1 RPC_URL=https://mainnet.gateway.tenderly.co \
  PATH="/Users/dd/.pyenv/versions/3.11.8/bin:$PATH" \
  FORGE_WALLET_ARGS="--sender 0xCB43078C32423F5348Cab5885911C3B5faE217F9" \
  script/deploy.sh deploy/manager-factory.json --target manager

/Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py manager-package deploy/manager-measured-dry-run.json

RPC_URL=https://mainnet.gateway.tenderly.co /Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py manager-create \
  0x0cEc235560B81Bf0568A1cFc07D9491fE3d9EC4B \
  0xCB43078C32423F5348Cab5885911C3B5faE217F9 500000000000000000
```

The wrapper was run **without broadcast**, with exit status 0, at block 26,508,708 after the manifest was regenerated; the Forge simulation and local postflight passed. The release check then reported only the uncommitted manifest, which is committed with this package. No acceptance or signature was generated or reused.

The validated public Forge dry-run was preserved as [manager-measured-dry-run.json](../../deploy/manager-measured-dry-run.json), SHA-256 `b2cd8ae949910519e996ce5fa0afff14d9b240f3a60b38a40f61cac01e0694db`. The [A10 preparation log](../receipts/manager-measured-unsigned-dry-run-a10.log) preserves the Python gate error as well as the successful Forge simulation/postflight. Forge's sensitive cache is not an input to this package and was not copied.

[manager-unsigned-cutover.json](../../deploy/manager-unsigned-cutover.json) records Ethereum chain 1 at block **26,508,708**, signer nonce **4259** read live, contiguous unsigned nonces 4259–4262, validated compiled links and dependency values. It includes the owner pack mix (`PackAccount.design`), backing of 11053 bps, the audit B E1 fix (a build cannot spend backing booked for returned packs) and D86 (payMarkupBps, bufferBps, the essential keeper budget, unwindCharge, seven unused GasSchedule fields and op tags removed; exit work unpaid), the shortfall-unlist early-stop fix the 540,000 build gas allowance and removal of the write-only ordinaryShapeCount:

| Contract | Predicted address | Transaction gas limit |
|---|---|---:|
| ScanLib | `0xec0900db74bd6d969fb07721e89a206bb484527f` | 5,252,228 |
| VaultLib | `0xef12326555c672ecb83cff05f83f2bb12e441ebf` | 6,483,835 |
| StrategyLib | `0x7498846c29c16050128db80ac2d3514dccf61636` | 4,244,527 |
| PackManagerFactory | `0xBFfF9760EC41a3a9167f641E17AF8d93503C79a4` | 7,023,105 |

The implementation predicted by the factory is `0xEB1B5F61e1b4D4cd379DF9aA0421fb25cB34b52F`. Every transaction is below EIP-7825's 16,777,216 limit. The script's aggregate estimate is 23,003,695 gas; its estimated total of 0.01072990601984301 ETH at a 0.466 gwei estimate is simulation output, not gas spent. The signer held **0.007998 ETH** at that block: enough only below about 0.347 gwei.

Compiled runtime sizes in this package are PackManager 20,116 bytes, factory 4,311, StrategyLib 13,150, VaultLib 21,423 and ScanLib 17,314. The package binds their exact runtime/initcode hashes. The dry-run [manager-measured-dry-run.json](../../deploy/manager-measured-dry-run.json) has SHA-256 `bd6b32bba620839b58477cbd4828b4e80581e25f518da0564d190cb0a533d7a6`. The release ABI guard requires exactly two factory creates, `(owner, p, expected)` and `(owner, p, design, expected)`, and `initialize(owner_, p, design_)`.

## Creation template and final refresh

[manager-create-unsigned.json](../../deploy/manager-create-unsigned.json) is unsigned calldata to the current predicted factory, using `create(owner, p, design, expected)`. At block **26,508,708**, the factory is not deployed, the reviewed owner is `0xCB43078C32423F5348Cab5885911C3B5faE217F9`, the sample design is 2 x 0.03, 1 x 0.05 and 1 x 0.10 ETH packs (`0x100000000010002000000`, packUnitsMask 1064), funding is 500,000,000,000,000,000 wei, the live mint fee is 0.0005 ETH and backing is 11053 bps and the configuration expectation is `0x545eb7a046d3ec9cc39a4773c7b380a55c1b24652bf33905999c5490ea722818`. Manager values SHA-256 is `0fe601682911596eee480e150ebb3de72d7745e3786c3171cc66bdf88f3d0284`; template SHA-256 is `3851beb3a2d2ec0448bc0233886b3818ab316d315991ec75cf57b86b89b7f0aa`. The design and funding are evaluation samples; the owner sets both at creation. The prior template remains available in the previous Git revision and [manager-unsigned-history](../../deploy/manager-unsigned-history/).

A prior template attempt timed out during the pinned live mint-fee read before replacing its output. [The failure record](../receipts/manager-measured-unsigned-create-attempt1.json) is retained. Only template generation was retried; the successful deployment simulation was not repeated. The final template uses the current package's factory, rather than a historical predicted address.

Before any separately authorized signing, refresh nonce, dependency/code identity, live fee, preview and exact-calldata estimate. Source or linker changes require a matching compiled package; metadata-only manifest refreshes can reuse the preserved validated dry-run while those compiled inputs remain identical. Numerical manager changes require regenerating the creation expectation. Final manifest preparation does not itself authorize a transaction.

The release ABI guard requires the exact owner APIs `importPacks(uint256[],bytes32)`, `unlistForWithdrawal(uint256[])` and `withdrawRecoveryPack(address,uint256,uint256)`, with no return values. Missing or wrongly typed methods fail package preparation. The measured event is additive; `KeeperPaid(address,uint256)` remains unchanged.

## Owner migration and recovery

`importPacks(ids, expected)` is owner-only and accepts at most 16 canonical sealed packs per call. It pulls approved owner-held packs or adopts eligible account-held packs. Each actual composition is bounded to 30 Shapes, a 150,000-gas contents read and 1,024 bytes of returndata. Custody, membership, exact backing and bookkeeping are checked. Import mints nothing, redeems nothing and pays no keeper.

Imported principal up to 0.30 ETH is ordinary inventory; larger principal is recovery inventory. More than 30 Shapes is unsupported by bounded import, with the untracked-NFT rescue path retained. Existing inventory and actual Shape counts remain preserved.

The old account must first release actual assets through its own supported APIs. Then its owner approves and imports those assets into the new manager. This does not rewrite old storage, fabricate historical events or transfer someone else's authority.

For intact migration, the owner can pause listings or enter exit mode, call `unlistForWithdrawal(ids)` when real FWA settlement/crown windows permit, then `withdrawPacks(to, count)` for up to 16 packs. Owner unlisting is caller-funded, changes no pause/exit flags, and performs no liquidation. Checked `withdrawRecoveryPack(to, index, expectedPackId)` selects one sealed recovery item even when an unrelated unsealed gift remains elsewhere. An unsealed item is a claim and uses bounded recovery instead of an NFT transfer.

An owner-paid cash exit stops new exposure, performs necessary bounded settlement/recovery, unlisting and redemption, collects real fee credit, then withdraws actual cash. It can wait for protocol settlement. Leaving exit mode does not automatically resume listing. Wallet gas is separate from account compensation; an owner-selected wallet limit must include still-live signed reservations through replacement and reorganization. An evaluation's 0.01 ETH limit is not a universal contract rule.

## Measured compensation and keeper operations

The account captures gas before the guard/prechecks. Payment uses `min(measuredGas, verifiedOperationAllowance) + overhead`, multiplied by `min(tx.gasprice, basefee + maxTip, classCeiling)`, plus actual work fees (no markup). Cash/source/permission and caller minimum protection still apply. Exit work (wind-down / shortfall unlist and liquidate, recovery) is unpaid: the work runs, the caller is paid 0, and a nonzero `minPay` on it reverts. The meter is gross before refunds; actual wallet gas is the receipt's billed gas. Quotes use the upper envelope, with overhead once per actual paid call.

`KeeperWorkMeasured(uint256 measuredGas,uint256 gasAllowance,uint256 gasPrice,uint256 workUnits,bool essential)` records the work frame; `KeeperPaid` records payment after clipping. Paid padding, duplicates and unused fee hints are rejected. Unpaid owner recovery can tolerate stale hints. Import and standalone harvest pay no keeper.

[manager-keeper-unsigned.json](../../deploy/manager-keeper-unsigned.json) is address/environment data only: current predicted FACTORY, explicit Tenderly RPC, no VAULT and placeholders for existing read-only keystore/password mounts. It contains no secrets and changes no live service. Discovery begins at the separately authorized factory receipt block, not a guessed historical block.

After an authorized real deployment, independent postflight must verify the factory runtime, implementation, links and dependencies before discovery. A newly created manager must be checked for actual owner, all Params, accepted/live fee expectation, flags, balance, initial permissions and zero initial liabilities/inventory. Do not apply modern selectors to old contracts and silently turn read errors into zero.

Production signer transport, service start/restart and live discovery remain unexecuted until that factory exists and the applicable authority is given. The [local production-path postflight](../receipts/manager-measured-postflight-readback.json) checked a fresh zero-funded clone against the complete settings and linked code. The unsigned public dry-run is separate; neither deployed anything publicly.

## Evidence limits

The 50,000 overhead is an evaluation candidate. Earlier 100,000-overhead packets keep their executed metadata. Fixed-quote/Fresh studies and their old native checkpoints do not validate the new storage, reuse-only behavior, meter, operating returns or current overhead. The [focused verification](../receipts/manager-measured-verification.md), [expanded A10 economic scorecard](../receipts/manager-a10-economics.md) and [bounded independent review](../receipts/manager-a10-independent-review.md) identify current inputs and limits. The frozen 320-row assessment contains 16 recorded selection paths on only two demand tapes; its positive conditional mean does not establish a profitable reuse cycle or production default. It found a keeper sync bootstrap problem despite a positive measured margin on that exact work, and **zero ordinary keeper syncs** in all modeled rows. The **0.006 ETH reserve** covers the stated maximum-work cash envelope if funded, but remains an evaluated alternative; the unsigned values still have **0.005 ETH**. No annual return or live keeper image run is claimed.

The preserved [legacy readback](../../deploy/manager-existing-main-readback.json) records the old vault's 0.01 ETH and old factory's manager count zero. Unsupported selectors and RPC errors remain explicit; this does not establish modern postflight or open the shared vault. No conditional mean, source review or calibration is a production recommendation.

Things that don't make sense: increasing permission supplies no cash; the current 0.005 ETH reserve is below the 0.0055305 ETH maximum-work keeper envelope; a new keeper can decline a profitable sync before it has enough receipts to recalibrate; gross metered gas differs from refunded billed gas; a profitable or accepted isolated job does not establish full-cycle economic viability.
