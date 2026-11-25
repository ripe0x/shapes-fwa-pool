# Candidate settings inventory

This inventory describes the unsigned values in [manager.json](../../deploy/manager.json) and, separately, [mainnet.json](../../deploy/mainnet.json). **The manager is reuse-only with bounded measured compensation. These numerical defaults remain provisional and do not approve production economics.** The new shared vault is undeployed and its application remains closed. This work sends no public transaction, changes no public mint fee, and grants no signature, merge or live cutover authority.

Owner requirements in [OWNER-REQUIREMENTS.md](../../OWNER-REQUIREMENTS.md) supersede the historical quoted-payment/Fresh renewal design. The shared implementation remains in [PackAccount](../../src/PackAccount.sol), [StrategyLib](../../src/StrategyLib.sol), [VaultLib](../../src/VaultLib.sol) and [ScanLib](../../src/ScanLib.sol). The manager-only deployment and migration path is in [MANAGER-RUNBOOK.md](MANAGER-RUNBOOK.md). Current verification status belongs to [REPORT.md](../REPORT.md); old fixed-quote and Fresh economic studies retain their original settings and are historical.

Values SHA-256: manager `66423b7ed03e758fafe3b0a0b79a861f7894e97bf1885a8f13cfe887f38385cc`; main `99f8cc6f82530a0df9059b99b944ad6c67550a34ba8e7a7bf38948a666cb5f10`. The main values are listed for schema comparison, not as a refreshed or accepted pooled release.

## Dependencies and live fee

The constructor dependencies are FWA `0x958C41181182e76F221331b2755b77D9e1426A98`, Shapes `0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0`, and ShapePacks `0xf21514B090Da7dF4390803497d6ae673801E5cA7`. They are separate from mutable account economics. The factory is ownerless and cannot retune an existing manager.

The manager read-only refresh at Ethereum block **26,494,800** records **0.0005 ETH per primary Shape**, accepted maximum **0.001 ETH**. See [the pinned A10 readback](../receipts/manager-a10-public-readback.json), [the original fee observation](../../deploy/manager-mint-fee-observation.json) and [preserved legacy readback](../../deploy/manager-existing-main-readback.json). The task did not change the public fee. Current manager `expectedMintFeeWei` is 500,000,000,000,000; the main fixture retains 1,000,000,000,000,000. This deployment expectation is metadata outside Params and does not silently raise the accepted maximum.

The legacy deployment readback retains its 0.01 ETH balance and old factory manager count zero. Unsupported selectors and read errors remain recorded; old code is not relabelled as the new ABI. The new manager-only package deploys no pooled vault or seed and does not modify that legacy deployment.

## Complete Params inventory: 21 scalars

Settings belong to each account owner and change immediately within code bounds. Bps use 10,000 as denominator. Rates below are ETH per day. There is no renewal mode, renewal float, replacement eligibility or paid retirement-and-remint path.

| Parameter | ABI type | Main candidate | Manager candidate | Meaning |
|---|---|---:|---:|---|
| `minEdgeBps` | `uint16` | 100 | 100 | Minimum gross edge in bps |
| `bufferBps` | `uint16` | 0 | 0 | Oracle-cap discount in bps |
| `distributionBps` | `uint16` | 0 | 0 | Pooled gain distribution share; no manager share flow |
| `payMarkupBps` | `uint16` | 0 | 0 | Routine premium on reimbursed gas plus overhead |
| `keeperShareBps` | `uint16` | 2,500 | 2,500 | Maximum optional funding cost share of realized fees |
| `upliftBoundBps` | `uint16` | 25 | 25 | Pooled pricing exposure bound; no manager checkpoint gate |
| `packUnitsMask` | `uint64` | 8 | 8 | Bit 3 selects the 0.03 ETH / three-mint recipe |
| `gasCeilingWei` | `uint64` | 0.5 gwei | 0.5 gwei | Routine reimbursement-price ceiling |
| `essentialCeilingWei` | `uint64` | 2 gwei | 0.5 gwei | Essential reimbursement-price ceiling |
| `maxTipWei` | `uint64` | 0.05 gwei | 0.05 gwei | Maximum reimbursement above block base fee |
| `workFeeWei` | `uint64` | 0.00002 ETH | 0.00002 ETH | Per actual verified service unit |
| `routineCapWei` | `uint64` | 0.1 ETH | 0.03 ETH | Routine permission capacity |
| `routineRatePerDayWei` | `uint64` | 0.02 ETH | 0.01 ETH | Routine permission refill per day |
| `essentialCapWei` | `uint64` | 0 ETH | 0.01 ETH | Essential permission capacity |
| `essentialRatePerDayWei` | `uint64` | 0 ETH | 0.005 ETH | Essential permission refill per day |
| `reserveWei` | `uint128` | 0.005 ETH | 0.005 ETH | Cash withheld from new exposure |
| `tvlCapWei` | `uint128` | uint128 maximum | 0 ETH | Pooled admission cap; manager has no deposit shares |
| `backingRatioBps` | `uint32` | 70,000 | 70,000 | Separate backing target as bps of pack principal |
| `acceptedMintFeeWei` | `uint64` | 0.001 ETH | 0.001 ETH | Explicit maximum per newly minted Shape |
| `minDepositWei` | `uint64` | 0.01 ETH | 0.01 ETH | Pooled deposit threshold; shared schema in managers |
| `minDistributionWei` | `uint64` | 0.01 ETH | 0.01 ETH | Pooled distribution threshold; shared schema in managers |

The main TVL value is the exact uint128 maximum, 340282366920938463463374607431768211455 wei. Its storage-width bound is not a practical capital limit.

`setParams(next, expected)` accrues budgets at the old rates before applying new values and clamping capacities. Raising a cap does not refill spent permission. Budgets grant permission, not ETH. Settings updates retain the existing accepted fee; only `acceptMintFee(maximum, expected)` changes it. A lower external fee is paid at its actual amount. A fee above the accepted maximum blocks new mints while necessary unpaid recovery and owner withdrawal remain available.

At the selected recipe, principal is 0.03 ETH from three paid 0.01 ETH Shapes. Nominal separate FWA backing is **0.21 ETH** at 70,000 bps, before caps, unique backing tags and admission checks. The unresolved face-coverage floor is `ceil(P / 0.95)`: 31,578,947,368,421,053 wei for P = 0.03 ETH. This is an accounting bound, not a rule forcing a purchaser choice. The 0.18 ETH positive unresolved uplift at nominal backing implies 72 ETH NAV at a 25 bps pooled threshold; personal managers have no share-pricing checkpoint.

## GasSchedule: all 29 uint32 fields

The first 28 coefficients are **verified-operation gas caps** or planner inputs. `overhead` is separate gas units per paid transaction. They are not ETH amounts, full measured receipts, or community coefficients. Main and manager values differ where shown.

| Field | Main gas units | Manager gas units |
|---|---:|---:|
| `checkpoint` | 500,000 | 500,000 |
| `allocationEntry` | 6,000 | 6,000 |
| `allocationRead` | 30,000 | 30,000 |
| `build` | 360,000 | 360,000 |
| `buildPack` | 300,000 | 300,000 |
| `buildShape` | 130,000 | 130,000 |
| `list` | 280,000 | 380,000 |
| `listed` | 825,000 | 825,000 |
| `sync` | 125,000 | 125,000 |
| `requiredTail` | 120,000 | 120,000 |
| `distributionProof` | 80,000 | 80,000 |
| `journal` | 22,000 | 22,000 |
| `scan` | 30,000 | 30,000 |
| `selected` | 180,000 | 225,000 |
| `synced` | 120,000 | 285,000 |
| `pruned` | 45,000 | 45,000 |
| `unlist` | 340,000 | 340,000 |
| `unlisted` | 285,000 | 285,000 |
| `liquidate` | 75,000 | 75,000 |
| `liquidatePack` | 80,000 | 80,000 |
| `redeemShape` | 35,000 | 35,000 |
| `recoveryBase` | 100,000 | 100,000 |
| `recoveryShape` | 35,000 | 35,000 |
| `recoveryUnseal` | 70,000 | 70,000 |
| `harvest` | 125,000 | 125,000 |
| `harvested` | 80,000 | 80,000 |
| `credit` | 40,000 | 40,000 |
| `fund` | 40,000 | 40,000 |
| `overhead` | 100,000 | 50,000 |

For verified eligible work:

```text
gasPrice = min(tx.gasprice, block.basefee + maxTip, applicableCeiling)
reimbursedGas = min(measuredGas, verifiedOperationAllowance) + overhead
gasPay = reimbursedGas × gasPrice × (10000 + routineMarkupBps) / 10000
paymentBeforeLimits = gasPay + actualWorkUnits × workFee
```

Essential work has zero routine markup. The final payment also obeys its cash source, routine/essential permission or explicit funded pool, and caller `minPay`. The gas frame starts before the account guard and prechecks. `KeeperWorkMeasured` exposes the actual span/cap/price/work units/class; `KeeperPaid` records actual payment after clipping. Measured gas is **before refunds**, with the event/payment/guard tail and intrinsic transaction cost covered by the named overhead. Keeper wallet cost is separately `receipt.gasUsed × effectiveGasPrice`.

Quotes and reserve/charge views remain conservative envelopes using the full work cap plus overhead. Lifecycle envelopes count overhead once for each distinct paid call; combining sync and list does not remove one call's overhead. Two build service units are paid per actual built/listed pack; a resolved sync and a relist each earn one applicable unit. Reusing a returned pack has no three-mint fee or replacement fee.

Zero eligible work earns neither compensation nor overhead. Standalone harvest, owner import and caller-funded recovery are unpaid. Paid inputs must all perform verified terminal work, necessary claimed fee funding, listing or unlisting; padding, duplicates and ignored hints cannot enlarge paid work. Unpaid recovery can tolerate stale hints.

The manager's **50,000 gas overhead is a provisional evaluation candidate**. Earlier 100,000-overhead receipts keep that original configuration and are not relabelled as 50,000 results. Splitting profitability depends on actual billed costs, markup and batch shape; a passing cap check alone does not settle it. [Current receipts and financial limits](../receipts/manager-measured-economics.md) name the tested overhead, gas prices and source hashes. The model refuses unmeasured sync patterns.

## Productive opening: no renewal float

At the observed 0.0005 ETH fee, principal plus separate backing is 0.24 ETH and three primary mint fees add 0.0015 ETH. For one three-Shape build/list call, the work cap is 1,875,000 gas; with the manager's 50,000 overhead the envelope uses 1,925,000 gas and two work fees.

| Stated total price | Build/list payment envelope | Opening with observed fee and 0.005 reserve | Opening using accepted maximum fee |
|---|---:|---:|---:|
| 0.2 gwei (0.15 base + 0.05 tip) | 0.000425 ETH | **0.246925 ETH** | 0.248425 ETH |
| 0.5 gwei (0.45 base + 0.05 tip) | 0.0010025 ETH | **0.2475025 ETH** | 0.2490025 ETH |

These are conditional funding envelopes, excluding wallet creation gas, not actual billed costs or profit forecasts. Actual payment uses the bounded meter and may be lower. There is **no separate 0.2141275 ETH float**. Returned packs are relisted intact without new mint fees; a purchaser keeping the pack consumes inventory and any replacement is a normal new build subject to real cash, permission and admission.

The factory can create an idle manager with less funding; the unsigned template's 0.5 ETH is an evaluation amount, not a contract minimum or return recommendation. Current UI preview requirements are interface behavior, not a mandatory factory funding value. FWA fee credit and pending fees become spendable only through real collection.

The unsigned manager values retain **0.005 ETH**, while **0.006 ETH is an evaluated alternative, not an approved production default**. The keeper's conservative one-maximum-listing-batch plus journal/prune need is **0.0055305 ETH** at 0.5 gwei, zero markup and 50,000 overhead on each paid call. The current reserve is short **0.0005305 ETH**; 0.006 ETH leaves **0.0004695 ETH** headroom if the owner funds the additional 0.001 ETH. The productive-opening envelopes with 0.006 ETH are **0.247925 / 0.2485025 ETH** at the observed fee and **0.249425 / 0.2500025 ETH** at the accepted maximum, for 0.2 / 0.5 gwei. The [expanded paired assessment](../receipts/manager-a10-economics.md) found zero owner-return difference across 160 matched path pairs at 0.5 ETH opening funding; this is a cash-capacity choice, not a remedy for bid-return losses.

## Retained bounds and structural work

| Bound | Limit |
|---|---|
| Minimum edge / cap buffer | 0–1,000 / 0–2,000 bps |
| Distribution / routine markup | 0–5,000 / 0–1,000 bps |
| Optional keeper funding share / unresolved uplift | 0–5,000 / 0–1,000 bps |
| Backing target | 10,000–1,000,000 bps; live admission and face-coverage checks still apply |
| Routine and essential price ceilings | Each ≤50 gwei; maxTip ≤ routine ceiling |
| Work fee | ≤0.00005 ETH per actual service unit |
| Routine permission | Capacity ≤0.3 ETH; refill ≤0.02 ETH/day |
| Essential permission | Capacity ≤0.1 ETH; refill ≤0.005 ETH/day |
| Deposit / distribution minima | Each ≤1 ETH, including zero |
| Reserve / TVL | uint128 storage width; no additional policy maximum |
| Explicit accepted fee | uint64 storage width; unchanged except by the separate owner acceptance call |
| Every named gas field, including overhead | 0–16,777,216 gas units |
| Construction mask | Zero disables builds; otherwise enabled bits 3–30 |

Work bounds are independent of price: at most four packs per build; eight per list; 16 supplied sync/unlist/terminal/prune IDs; 128 journal entries; 96 own positions per rebase scan; 32 allocation queue entries plus the separately bounded active pricing check. Ordinary liquidation handles at most 16 packs, 60 principal units and 60 actual burned Shapes per call. Oversized recovery is isolated to a chunk of at most 30 Shapes. Total positions remain unlimited and progress incrementally; no full-book or holder enumeration is required.

## Import and owner migration

Only the owner can call `importPacks(ids, expected)`, up to 16 IDs per call. The manager pulls an approved pack from that owner or adopts a sealed canonical pack already held by the account. It rejects tracked/third-party/unsealed packs and verifies canonical Shape custody, pack membership, exact backing and at most 30 actual Shapes before recording inventory. Contents reads are bounded to 150,000 gas and 1,024 bytes of returndata. Import neither mints, redeems nor pays a keeper.

Ordinary imported value is at most 0.30 ETH; larger pack values enter recovery inventory. Composition counts remain exact for inherited and imported recipes. More than 30 Shapes cannot be imported through this bounded path; untracked NFTs retain the owner's rescue path.

`unlistForWithdrawal(ids)` is owner-only and caller-funded, leaves pause/exit flags unchanged and performs no liquidation. Live FWA and crown/settlement windows still apply. `withdrawPacks(to, count)` transfers at most 16 intact packs. `withdrawRecoveryPack(to, index, expectedPackId)` selects one sealed recovery pack with checked index and identity, so an unrelated unsealed gift cannot block it. An unsealed recovery item is a claim, not a transferable pack NFT, and uses bounded recovery instead.

The old account's owner must first withdraw actual assets through that account's supported APIs and then approve/import into the new manager. This is not an upgrade of old storage or authority. No creator, factory or administrator gains rights over the manager's assets.

## Configuration hash and remaining limits

The reviewed expectation is `keccak256(abi.encode(Params, liveMintFee, listingPaused, windingDown))`; creation uses both flags false. The hash includes all 21 scalars and 29 gas fields, but excludes moving balances, time and base fee. Execution revalidates current FWA admission and economics; a matching hash promises neither inclusion nor profit. Owner numerical changes and pause/exit controls are immediate. Claims, refunds and necessary unpaid recovery do not require a fresh ordinary-operation expectation. Ownership uses the preserved two-step handover.

Things that don't make sense: a larger permission budget supplies no ETH; the 0.005 ETH maximum-work reserve shortfall remains despite successful smaller calls; the keeper's initial sync estimate ratio can decline profitable actual work; gross measured gas is not billed gas after refunds; and conditional modeled returns or a gas calibration cannot approve production economics.
