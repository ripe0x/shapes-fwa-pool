# Manager-only unsigned deployment and operations

**Current step: prepare and review an unsigned manager-only package.** The strategy is reuse-only with bounded measured keeper compensation. The numerical candidate, including **50,000 gas overhead**, remains provisional. No public transaction, signature, acceptance, live keeper cutover or merge is authorized by this record. The shared vault is undeployed and its application remains closed.

The complete 21-scalar/29-gas schema, values, bounds and opening arithmetic are in [SETTINGS.md](SETTINGS.md). [OWNER-REQUIREMENTS.md](../../OWNER-REQUIREMENTS.md) supersedes the historical fixed-quote and Fresh renewal design. [REPORT.md](../REPORT.md) records current verification; receipt claims must retain their exact source and configuration.

## Scope and money

One manager owns its assets and uses the shared PackAccount/StrategyLib/VaultLib/ScanLib strategy. The ownerless factory creates an immutable implementation and personal clones; it has no authority to change an existing manager's owner or economics. Owner numerical controls act immediately within bounds. Algorithm changes require a new deployment and actual asset migration.

The current recipe is 0.03 ETH principal from three primary Shapes, with mask bit 3 and nominal separate backing of 0.21 ETH. Returned packs are relisted intact. A kept pack leaves inventory, and any replacement is a normal build using actual cash and permission. There is no Fresh mode, renewal float, replacement-eligibility balance or paid retirement/remint path.

The accepted fee is 0.001 ETH per Shape. Read-only public refresh at block 26,493,799 and the creation template at block 26,493,803 show an actual fee of 0.0005 ETH. These reads change no fee. The 0.5 ETH creation template is an evaluation funding amount, not a contract minimum or return recommendation.

At zero markup, the maximum one-pack build/list funding envelope plus reserve is 0.246925 ETH at 0.2 gwei or 0.2475025 ETH at 0.5 gwei using the observed fee. Using the accepted maximum gives 0.248425 / 0.2490025 ETH. Wallet creation gas is separate. Actual compensation uses bounded measured work and can be lower; these envelopes are not billed costs or profit predictions.

## Production path and recorded unsigned result

Deployment inputs are [manager-factory.json](../../deploy/manager-factory.json) for dependencies and [manager.json](../../deploy/manager.json) for manager economics. The manager target deploys libraries and PackManagerFactory with its implementation. It deploys no PackVault, transfers no seed and creates no funded manager.

The wrapper compiles its actual deploy inputs, checks the manifest, and then simulates through the same DeployCore production path. A simulation reports a failed release gate and continues; it is not release acceptance. Do not add a second build merely for documentation changes.

Recorded preparation commands, using the existing Git and deployment identities and Python 3.11.8:

```sh
python3 script/release.py manifest --target manager

CANDIDATE_RUN=1 RPC_URL=https://mainnet.gateway.tenderly.co \
  FORGE_WALLET_ARGS="--sender 0xCB43078C32423F5348Cab5885911C3B5faE217F9" \
  script/deploy.sh deploy/manager-factory.json --target manager

python3 script/release.py manager-package deploy/manager-measured-dry-run.json

RPC_URL=https://mainnet.gateway.tenderly.co python3 script/release.py manager-create \
  0x308f258b47c406a820790fa8a8894e92b02cc3ab \
  0xCB43078C32423F5348Cab5885911C3B5faE217F9 500000000000000000
```

The wrapper was run **without broadcast**, with exit status 0 in **11.67 seconds**. Its only reported release-gate failure was uncommitted release inputs in the shared draft worktree. The candidate manifest is intermediate; the lead refreshes it after final source-bound artifacts. No acceptance or signature was generated or reused.

The validated public Forge dry-run was preserved as [manager-measured-dry-run.json](../../deploy/manager-measured-dry-run.json), SHA-256 `46d737aeb953a2ee156b0bee7cbbb87325ff1f1127a4eb58608d0b4fc09fc660`. The preparation log is [manager-measured-unsigned-dry-run.log](../receipts/manager-measured-unsigned-dry-run.log). Forge's sensitive cache is not an input to this package and was not copied.

[manager-unsigned-cutover.json](../../deploy/manager-unsigned-cutover.json) records Ethereum chain 1, refreshed nonce readback **4180** at block **26,493,843**, contiguous unsigned nonces 4180–4183, validated compiled links and dependency values:

| Contract | Predicted address | Transaction gas limit |
|---|---|---:|
| ScanLib | `0x8148d8b4621ce009275d88e5dfdf1302a700cbc0` | 6,827,830 |
| VaultLib | `0x1e7a9cd8acf72f5dffda172497d41f5471d15317` | 7,181,954 |
| StrategyLib | `0xc3ab28505d386ea4f77b4b121e0e8c4b8b828a30` | 4,399,705 |
| PackManagerFactory | `0x308f258b47c406a820790fa8a8894e92b02cc3ab` | 7,348,688 |

The implementation predicted by the factory is `0xb8d36f767363e16ae9775c22a03de14d24ba8e06`. Every transaction is below EIP-7825's 16,777,216 limit. The script's aggregate estimate is 25,758,177 gas across transactions, not one transaction. Its estimated required total of 0.018060026196089784 ETH at a 0.701137592 gwei estimate is simulation output, not gas spent or a fixed future price.

Compiled runtime sizes in this package are PackManager 20,707 bytes, factory 4,876, StrategyLib 14,456, VaultLib 22,422 and ScanLib 21,310. The package binds their exact runtime/initcode hashes. Historical unsigned inputs and the earlier public dry-run are retained in [manager-unsigned-history](../../deploy/manager-unsigned-history/); their predicted addresses and nonces are not current.

## Creation template and final refresh

[manager-create-unsigned.json](../../deploy/manager-create-unsigned.json) is unsigned calldata to the current predicted factory. At block **26,493,803**, the factory is not deployed, the reviewed owner is `0xCB43078C32423F5348Cab5885911C3B5faE217F9`, funding is 500,000,000,000,000,000 wei, and the configuration expectation is `0x2c8bed5338b295b8aa543711ce5b97f774557239742a91ec1e96702b7f66b0c6`. Manager values SHA-256 is `66423b7ed03e758fafe3b0a0b79a861f7894e97bf1885a8f13cfe887f38385cc`; template SHA-256 is `12c871f80c554d9f56e24be2ecc9667d2b8942fd7ed05370f1313c1e6c3413d4`. The prior template is preserved in [manager-unsigned-history](../../deploy/manager-unsigned-history/).

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

The account captures gas before the guard/prechecks. Payment uses `min(measuredGas, verifiedOperationAllowance) + overhead`, multiplied by `min(tx.gasprice, basefee + maxTip, classCeiling)`, with routine markup and actual work fees. Cash/source/permission and caller minimum protection still apply. The meter is gross before refunds; actual wallet gas is the receipt's billed gas. Quotes use the upper envelope, with overhead once per actual paid call.

`KeeperWorkMeasured(uint256 measuredGas,uint256 gasAllowance,uint256 gasPrice,uint256 workUnits,bool essential)` records the work frame; `KeeperPaid` records payment after clipping. Paid padding, duplicates and unused fee hints are rejected. Unpaid owner recovery can tolerate stale hints. Import and standalone harvest pay no keeper.

[manager-keeper-unsigned.json](../../deploy/manager-keeper-unsigned.json) is address/environment data only: current predicted FACTORY, explicit Tenderly RPC, no VAULT and placeholders for existing read-only keystore/password mounts. It contains no secrets and changes no live service. Discovery begins at the separately authorized factory receipt block, not a guessed historical block.

After an authorized real deployment, independent postflight must verify the factory runtime, implementation, links and dependencies before discovery. A newly created manager must be checked for actual owner, all Params, accepted/live fee expectation, flags, balance, initial permissions and zero initial liabilities/inventory. Do not apply modern selectors to old contracts and silently turn read errors into zero.

Production signer transport, service start/restart and live discovery remain unexecuted until that factory exists and the applicable authority is given. The [local production-path postflight](../receipts/manager-measured-postflight-readback.json) checked a fresh zero-funded clone against the complete settings and linked code. The unsigned public dry-run is separate; neither deployed anything publicly.

## Evidence limits

The 50,000 overhead is an evaluation candidate. Earlier 100,000-overhead packets keep their executed metadata. Fixed-quote/Fresh studies and their old native checkpoints do not validate the new storage, reuse-only behavior, meter, operating returns or current overhead. The [focused verification](../receipts/manager-measured-verification.md) and [economic scorecard](../receipts/manager-measured-economics.md) identify current inputs and limits. No current annual return or live keeper image run is claimed.

The preserved [legacy readback](../../deploy/manager-existing-main-readback.json) records the old vault's 0.01 ETH and old factory's manager count zero. Unsupported selectors and RPC errors remain explicit; this does not establish modern postflight or open the shared vault. No conditional mean, source review or calibration is a production recommendation.

Things that don't make sense: increasing permission supplies no cash; the current 0.005 ETH reserve is below the 0.0055305 ETH maximum-work keeper envelope; gross metered gas differs from refunded billed gas; a profitable or accepted isolated job does not establish full-cycle economic viability.
