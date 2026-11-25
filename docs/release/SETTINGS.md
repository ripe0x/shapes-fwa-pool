# Candidate settings inventory

This inventory records the unsigned evaluation candidate in [`deploy/mainnet.json`](../../deploy/mainnet.json) and [`deploy/manager.json`](../../deploy/manager.json). **These are provisional evaluation settings, not approved or recommended production economics.** The selected launch recipe is fixed by the owner's requirement: 0.03 ETH packs containing three directly minted 0.01 ETH Shapes. Backing, uplift, funding, calibration and depositor-return acceptance remain subject to the final economic scorecard. No signature, public transaction, mint-fee change, application cutover or merge is authorized by this document.

Source configuration SHA-256:

- Main: `e9a5ca7b80c8e67cb2d0bfef5be4d2539129fcf078da488e52253cd9a2aaefd0`.
- Manager: `f216770efacfe587770fe3d3821d0f2489d40c4e4f7758a051be77195ac0c026`.

The authoritative behavior is shared by [`PackAccount`](../../src/PackAccount.sol), [`VaultLib`](../../src/VaultLib.sol), [`StrategyLib`](../../src/StrategyLib.sol) and [`ScanLib`](../../src/ScanLib.sol). See [the completion requirements](../MAIN-POOL-COMPLETION.md), [owner requirements A5](../../OWNER-REQUIREMENTS.md), [the unsigned runbook](RUNBOOK.md) and [acceptance status](ACCEPTANCE.md). The final [economic scorecard](../receipts/completion-economics.md) and [receipt-backed verification](../receipts/completion-verification.md) accompany this inventory; historical scorecards do not accept this candidate.

For the completed personal-manager scope, use [the manager runbook](MANAGER-RUNBOOK.md) and [final focused verification](../receipts/manager-final-verification.md) and [bounded manager scorecard](../receipts/manager-closeout-economics.md). The new shared vault remains undeployed and its app launch stays disabled.

## Deployment inputs and fee observation

| Input | Main evaluation candidate |
| --- | --- |
| FWA | `0x958C41181182e76F221331b2755b77D9e1426A98` |
| Shapes | `0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0` |
| ShapePacks | `0xf21514B090Da7dF4390803497d6ae673801E5cA7` |
| Initial vault owner | `0xCB43078C32423F5348Cab5885911C3B5faE217F9` |
| Vault seed | 0.01 ETH |
| `expectedMintFeeWei` | 1,000,000,000,000,000 wei, or 0.001 ETH per Shape |

These addresses are constructor dependencies, not mutable account economic settings. A manager's individual owner is supplied on creation; the factory retains no authority over previously created managers. Its parameter file supplies economics, not a shared manager owner or a mandatory creation funding amount. Creating an idle account is distinct from funding a productive first position.

The historical combined-candidate read is **0.001 ETH per Shape at Ethereum block 26,484,850**, block hash `0xb74960f39c4f4971c0e3732837afb49ecdfd20153c3d9d0631796f1d6e086f7c`. See the [pinned fee observation](../../deploy/mint-fee-observation.json) and [existing-main readback](../../deploy/existing-main-readback.json). The read used `https://mainnet.gateway.tenderly.co`; it changed no public state. The existing deployment's readback describes its historical implementation, not the new candidate ABI.

At that observed fee, one launch pack requires exactly 0.03 ETH redeemable principal plus **3 × 0.001 = 0.003 ETH actual primary mint fees**. Creator revenue is counted only from successful paid mint events, including eligible fresh replacements. That observation remains historical evidence. The manager closeout read now observes **0.0005 ETH at block 26,489,769**, so a current pack pays **0.0015 ETH** actual primary fees. See [the new observation](../../deploy/manager-mint-fee-observation.json), [fresh legacy readback](../../deploy/manager-existing-main-readback.json) and [manager-only bounded evaluation](../receipts/manager-closeout-economics.md). The public fee changed externally; this task sent no fee transaction. The accepted maximum remains 0.001 ETH and the old combined deployment expected-fee fixture is not refreshed or approved by this manager-only task.

## Account economics

All values below are account-owned and adjustable immediately within the code bounds. Bps use 10,000 as the denominator. The two files agree except where shown.

| Parameter | Main candidate | Manager candidate | Meaning |
| --- | ---: | ---: | --- |
| `packUnitsMask` | 8 | 8 | Bit 3 enables units 3: three paid 0.01 ETH mints per pack |
| `minEdgeBps` | 100 | 100 | Minimum gross acquisition multiplier edge, 1% |
| `bufferBps` | 0 | 0 | Discount from the live oracle cap |
| `distributionBps` | 0 | 0 | Distribution share of eligible gain; disabled here |
| `payMarkupBps` | 0 | 0 | Markup on routine quoted gas compensation |
| `keeperShareBps` | 2,500 | 2,500 | Optional funding compensation may use at most 25% of verified realized value |
| `backingRatioBps` | 70,000 | 70,000 | Provisional 7× pack-face backing target |
| `upliftBoundBps` | 25 | 25 | Provisional shared-vault unresolved positive keep uplift limit, 0.25% of NAV; no manager share-pricing gate |
| `renewalMode` | 0 | 0 | `FreshAfterAcquisition`; mode 1 is `ReuseReturned` |
| `renewalFloatCount` | 1 | 1 | One separately funded fresh-renewal float |
| `acceptedMintFeeWei` | 0.001 ETH | 0.001 ETH | Explicitly accepted maximum per paid fresh Shape |
| `gasCeilingWei` | 0.5 gwei | 0.5 gwei | Routine gas price ceiling |
| `essentialCeilingWei` | 2 gwei | 0.5 gwei | Essential gas price ceiling |
| `maxTipWei` | 0.05 gwei | 0.05 gwei | Allowance above block base fee |
| `workFeeWei` | 0.00002 ETH | 0.00002 ETH | Fee per actual verified service unit |
| `reserveWei` | 0.005 ETH | 0.005 ETH | Maintenance reserve, separate from renewal float |
| `tvlCapWei` | 340282366920938463463374607431768211455 wei | 0 | Vault uses the uint128 maximum, not a practical TVL cap; manager has no depositor admission flow |
| `routineCapWei` | 0.1 ETH | 0.03 ETH | Maximum routine spending allowance |
| `routineRatePerDayWei` | 0.02 ETH/day | 0.01 ETH/day | Routine allowance accrual |
| `essentialCapWei` | 0 | 0.01 ETH | Essential spending allowance capacity |
| `essentialRatePerDayWei` | 0 | 0.005 ETH/day | Essential allowance accrual |
| `minDepositWei` | 0.01 ETH | 0.01 ETH | Minimum gross escrow after the shared checkpoint contribution; shared schema on managers |
| `minDistributionWei` | 0.01 ETH | 0.01 ETH | Smallest eligible aggregate distribution |

`setParams(next, expected)` changes settings under the account owner's authority. It accrues budgets at the old rates first, then clamps to the new capacities. Raising a capacity does not refill already spent allowance. A zero essential budget makes ordinary exit maintenance unpaid; callers can still carry out necessary recovery with their own transaction gas. Explicit checkpoint contributions have their own protected funding source and payer refunds, separate from routine/essential allowance.

`setParams` must retain the existing accepted mint-fee maximum. Only the separate `acceptMintFee(maximum, expected)` explicitly changes that maximum. A live fee above the accepted maximum blocks paid fresh minting; unrelated owner updates do not silently accept it. A lower live fee is charged at the actual lower amount. Acceptance is account authority, not authority to change the Shapes contract's public mint fee.

The 7× target gives a nominal **0.21 ETH backing** for a 0.03 ETH pack before oracle caps, quantization and unique backing tags. Backing remains owner-adjustable and is independently validated against current FWA admission and profitability. A backing floor of `ceil(P / 0.95)` preserves the face-value mark of an unresolved allocation even at FWA's immutable 5% maximum settlement fee. For P = 0.03 ETH that floor is **31,578,947,368,421,053 wei**. This is a NAV accounting floor, not a compulsory purchaser keep preference or FWA's minimum listing backing.

Unresolved uplift accumulates `max(backing − actual pack face, 0)` incrementally when allocated and clears on actual resolution, including owed recovery. No full position-book scan is needed. At nominal launch backing this is 0.18 ETH per unresolved position; 25 bps requires 72 ETH NAV for one such position at the threshold. That arithmetic is not a claim that an entrant or incumbent's completed return is accepted.

## GasSchedule: all 28 named fields

The named account-owned schedule is identical in both candidate files. Values are quoted gas units, not wei and not measured reimbursement. This inventory does not claim every operation's final calibration is accepted. The `harvest` field is account-owned planner calibration for unpaid standalone fee collection. The keeper compares its allowance with unlisting when choosing a partial-redemption liquidity path; the forward simulation mirrors that choice. Standalone harvest has no onchain compensation or charge calculation, and positive `minPay` reverts. Attached paid funding separately uses `fund`, `harvested` and `credit`. Actual caller wallet gas is evaluated from the receipt-based cost proxy, not as keeper compensation.

| Field | Quoted gas units |
| --- | ---: |
| `checkpoint` | 500,000 |
| `allocationEntry` | 6,000 |
| `allocationRead` | 30,000 |
| `build` | 360,000 |
| `buildPack` | 300,000 |
| `buildShape` | 130,000 |
| `list` | 280,000 |
| `listed` | 825,000 |
| `sync` | 125,000 |
| `requiredTail` | 120,000 |
| `distributionProof` | 80,000 |
| `journal` | 22,000 |
| `scan` | 30,000 |
| `selected` | 180,000 |
| `synced` | 120,000 |
| `pruned` | 45,000 |
| `unlist` | 340,000 |
| `unlisted` | 285,000 |
| `liquidate` | 75,000 |
| `liquidatePack` | 80,000 |
| `redeemShape` | 35,000 |
| `recoveryBase` | 100,000 |
| `recoveryShape` | 35,000 |
| `recoveryUnseal` | 70,000 |
| `harvest` | 125,000 |
| `harvested` | 80,000 |
| `credit` | 40,000 |
| `fund` | 40,000 |

The common payment calculation sums the applicable bases and verified completed-work counts, prices the gas allowance at `min(basefee + maxTip, applicable ceiling)`, applies routine gas markup consistently, and adds `workFee × actual service units`. Envelope checks, actual compensation and relevant charge quotes use this basis. Cash availability, protected liabilities, source caps, spending permission and `minPay` then limit execution/payment. Repeated calls without new verified work earn no second reward. Actual transaction receipts calibrate coefficients; measured transaction gas does not replace the fixed-count payment model.

Fresh construction cost includes the actual selected initial recipe's paid mint fees and full build/list quote. Reuse-mode relisting excludes another fresh mint expense; its initial construction still counts once. Fresh-mode continuing admission prices the currently enabled replacement recipe and the actual old inventory's retirement work. `relistEdgeFor(packId)` and `renewalQuote(...)` expose bounded inventory-specific quotes. Changing the numerical calibration requires only the owner's settings update. Changing the algorithm requires new implementation code and deployment; the external keeper-policy address, quote call and factory policy initializer are removed.

## Derived operating cash

For fresh renewal, the separate float is the maximum across enabled recipes of backing plus paid mint fees at the accepted maximum plus the full retirement/build/list quoted payment at the routine ceiling, multiplied by `renewalFloatCount`. Returned principal is redeemed before construction, so it cancels rather than being reserved a second time. Ordinary routine payment preserves this float. An eligible fresh renewal can consume it while preserving maintenance reserve and all liabilities; routine growth also preserves it. Renewal eligibility is single-use and comes only from verified acquisition outcomes, not ordinary unlisting or gifted inventory. Mode 1 relists returned inventory without fresh minting and derives zero fresh-renewal float.

For the current single enabled recipe and schedule:

- Retirement/build/list allowance is 2,135,000 quoted gas units; three verified service units add 0.00006 ETH work fee.
- At the 0.5 gwei routine ceiling and zero markup: renewal quote is 0.0011275 ETH; float is **0.2141275 ETH**; maintenance plus float is **0.2191275 ETH**.
- At a stated base fee of 0.15 gwei and priority allowance 0.05 gwei: initial build/list allowance is 1,875,000 gas, quoted compensation is 0.000415 ETH. Conditional one-position opening funding is **0.4625425 ETH** including principal, backing, actual mint fees, maintenance and float. At the 0.5 gwei ceiling it is 0.463105 ETH.

These are derived funding estimates, not measured transaction costs, productive-admission guarantees, depositor-profit results or recommended production capital. Extra bounded fee-claim funding, unique backing tags and actual inventory retirement composition can change a specific renewal's need. Funding status must distinguish missing cash from missing budget permission; fees at FWA are not automatically spendable cash.

## Retained bounds and bounded work

These numerical limits preserve the current quoted-payment and accounting envelope. They do not establish profitable or sustainable economics. Within them, owners retain immediate numerical control.

| Bound | Limit and reason |
| --- | --- |
| Minimum edge / cap buffer | 0–1,000 bps / 0–2,000 bps; bounded admission margin and oracle discount |
| Distribution / routine markup | 0–5,000 bps / 0–1,000 bps; bounded gain allocation and routine gas premium |
| Keeper funding share / uplift | 0–5,000 bps / 0–1,000 bps; bounded optional fee-funded compensation and unresolved positive-uplift exposure |
| Backing ratio | 10,000–1,000,000 bps, or 1×–100×; the separate NAV floor and live admission can reject a particular target |
| Gas ceilings / priority allowance | Each ceiling ≤50 gwei; `maxTip ≤ gasCeiling`; these bound quoted prices, not transaction gas consumption |
| Work fee | ≤0.00005 ETH per verified service unit; bounds exposed per-unit compensation |
| Routine allowance | Capacity ≤0.3 ETH; accrual ≤0.02 ETH/day; bounds the spending burst and continuing refill |
| Essential allowance | Capacity ≤0.1 ETH; accrual ≤0.005 ETH/day; separately bounds exit-work spending permission |
| Deposit/distribution minima | Each ≤1 ETH; limits how high an owner can set the small-flow threshold; zero is allowed by the configuration bounds |
| Reserve / TVL | uint128 amounts; storage-width limit only, with no additional policy maximum; vault candidate TVL uses uint128 maximum |
| Accepted mint-fee maximum | uint64 wei storage-width limit; the operative spending limit is the owner's explicit accepted maximum |
| Renewal float count | 0–16; cash reserve scale is adjustable independently of operation size |
| Every GasSchedule field | 0–16,777,216 gas units; lowering a price never increases structural work limits |
| Pack mask | Zero disables fresh construction; otherwise enabled unit bits 3–30; owner may adjust future recipes |

Structural work bounds are separate from economic coefficients: build **at most 4 packs**, list at most 8, renewal at most 4, sync/unlist/terminal/prune work in bounded batches of 16, journal at most 128, rebase scan at most 96 positions, allocation proof at most 32 queue entries (plus its separate bounded active check), and renewal funding harvest at most 16 supplied fee IDs. Liquidation processes at most 16 ordinary packs, at most **60 units of principal**, with an additional actual-burn check of at most 60 Shapes per ordinary call. Oversized recovery is isolated to a chunk of at most 30 Shapes; each returned pack retired for renewal also checks at most 30 Shapes. Manager pack withdrawal is at most 16 per call. Total positions remain unlimited; a small account may scan its own bounded book, while larger books advance incrementally through the journal. There is no holder enumeration or required full-book scan.

Claims, cancellation, refund claims and necessary unpaid recovery remain available when the mint fee or ordinary economic configuration changes. Their availability does not bypass protected-liability accounting or make a formerly invalid admission profitable.

## Expected configuration and owner authority

The reviewed hash is `keccak256(abi.encode(Params, live Shapes mintFee, listingPaused, windingDown))`. `Params` includes the full named gas schedule and explicitly accepted fee maximum. Creation hashes use the supplied parameters and the reviewed live fee with both flags false. The vault constructor and factory creation verify the expected hash; tooling carries `expectedMintFeeWei` separately from the accepted maximum. Spending/commitment calls and owner settings changes validate the caller's expected hash before proceeding.

The hash intentionally excludes continuously changing balances, block time and base fee. It also does not pin every external FWA setting; current FWA admission, fees, oracle bounds and profitability are revalidated at execution. A hash match is not a promise that a reviewed operation remains profitable or executable. Owner pause/exit controls take effect immediately. Claims, cancellations and necessary unpaid recovery do not require a fresh hash. Two-step ownership handover preserves individual ownership; the factory cannot retune existing managers.

## Things that don't make sense / awaiting evidence

- The provisional 0.21 ETH backing, 25 bps uplift bound, renewal float and budget rates need their final completed holder/creator cash-flow comparison at current and isolated half fee. This inventory supplies no acceptance result.
- The final receipt-calibrated gas coverage and economic scorecard must identify any changed owner outcome limits explicitly. Updating a coefficient is not approval to relax a net depositor-return requirement.
- The 0.01 ETH deployment seed creates an idle vault; it does not fund the derived first productive position. Production funding and launch economics remain unapproved.

## Manager operating evaluation, 2026-11-25

The manager-only public readback now observes **0.0005 ETH per primary Shape at block 26,492,785**
(`deploy/manager-mint-fee-observation.json`). The accepted maximum remains 0.001 ETH. No
production setting was changed. The 0.03 ETH/three-Shape recipe and mask 8 remain selected.

| Setting | Evaluation value | Production status |
| --- | --- | --- |
| Pack principal / mint count | 0.03 ETH / 3 | Selected launch recipe; future owner adjustment preserved |
| Separate FWA backing | 0.21 ETH / 70,000 bps | Provisional evaluated candidate |
| Renewal mode | FreshAfterAcquisition | Evaluated alongside explicit ReuseReturned |
| Renewal float | One; 0.2141275 ETH at configured ceiling | Provisional; conservative accepted fee, separate from actual mint spending |
| Operating reserve | 0.005 ETH | Provisional; below 0.0054805 ETH current maximum-batch need |
| Routine / essential ceiling | 0.5 / 0.5 gwei | Existing unsigned candidate, not newly approved |
| Priority allowance / work fee / markup | 0.05 gwei / 0.00002 ETH / 0 bps | Existing unsigned candidate |
| Routine capacity / daily rate | 0.03 / 0.01 ETH | Permission only, creates no funding |
| Essential capacity / daily rate | 0.01 / 0.005 ETH | Permission only; owner exits remain separately wallet funded |
| Evaluation caller exit cap | 0.01 ETH cumulative signed maxima | Local evaluation choice, not a required production cap |
| Unresolved uplift threshold | 25 bps | Shared-vault pricing input; no manager shares/checkpoint gate |
| Gas schedule | All 28 fields in `deploy/manager.json` | Owner adjustable; current values independently verified by postflight |

The full setting inventory is the values file, including zero-value fields; the unsigned creation
calldata includes every scalar and gas coefficient. No factory policy argument or authority over
previously created managers is added. Numerical calibration stays immediate under each owner.
Algorithm changes require new code. The recorded-period evaluation keeps initial funding at
0.5 ETH without topups and compares both renewal modes, 0.21 and hypothetical 0.03 ETH backing,
three explicitly labeled fee cases, and 0.2/0.5 gwei gas scenarios. Current manager coverage/admission
rejects 0.03 ETH backing; the protocol-admitted comparison is isolated and cannot be selected for
production through the current manager. Its returns do not establish a deployable configuration.

At the observed fee, independent arithmetic gives 0.24 ETH principal plus separate backing before
fees/reserves. One productive Fresh position needs 0.461605 ETH at 0.5 gwei or 0.4610425 ETH at
0.2 gwei, including actual opening mint fees, quoted initial work, the conservative float and
reserve, excluding wallet creation gas. Reuse requires no fresh-renewal float; actual productive
position counts, funding waits, receipts and owner/keeper/creator outcomes are reported in the
operating assessment rather than inferred from this opening arithmetic.

The measured manager quote repair changes only `gasSchedule.selected=225000`,
`gasSchedule.synced=285000` and `gasSchedule.list=380000`. All twelve one-work ordinary cases
cover actual keeper costs at matched 0.2/0.5 gwei, including exact minPay re-estimation. The
current keeper reserve-need view is 0.0054805 ETH at the 0.5 gwei ceiling; the candidate reserve
remains 0.005 ETH and the informational warning remains visible. These measured corrections
are evaluated local defaults, not owner production acceptance or a profit promise.
