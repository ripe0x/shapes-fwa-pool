# Individual manager A8–A10 verification

**Candidate:** reuse-only 0.03 ETH packs, bounded measured keeper compensation, intact pack import, owner-paid exit. Contract source hashes are in [manager-measured-reconciliation.json](manager-measured-reconciliation.json); the receipt profile binds exact Solidity, keeper and model files. The newly deployed shared vault and live app were not changed.

## Executed checks

| Check | Command / recorded input | Result | Limit |
|---|---|---|---|
| Real-counterparty fork batch | `CANDIDATE_RUN=1 forge test --match-contract '^(CompleteCreditTest|CompleteForeignJournalTest|CompleteHarvestTest|EfficientJournalTest|ForkKeeperPayTest|ForkMainConfigurationTest|ForkMainReuseTest|ForkManagerCloseoutReuseTest|ForkManagerImportTest|ForkManagerMixedRecoveryTest|ForkManagerReuseFundingTest|ForkManagerTest|ForkMeasuredKeeperTest|ForkMeasuredSyncInputTest|ForkProductionReceiptsTest|ForkScanReconcileTest|ForkUnwindChargeTest|ForkVaultAdversarialTest|ForkVaultLifecycleTest|ReviewBootstrapTest|ScanGasTest|ScanPaidGasTest|ScanSyncForeignTest|ScanSyncSelectionTest)$' --rpc-url https://mainnet.gateway.tenderly.co --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100 --isolate -vv` | First batch: 165 pass, four fail, one skip; focused repairs then pass. The corrected splitting test records that 100,000 overhead can reward splitting at maximum markup, while the 50,000 candidate's measured cases do not. Separate real selection follow-up: three pass. | First batch log `/tmp/shapes-a8-final-forks.log`; focused logs `/tmp/shapes-a8-final-repairs.log`, `/tmp/shapes-a8-splitting-repair.log`, `/tmp/shapes-a8-manager-selections.log`. Aggregate receipt gas is never inferred from Forge test gas. |
| Actual 50,000-overhead work receipts | `CANDIDATE_RUN=1 /Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_measured.py --execute --export-existing --output docs/receipts/manager-measured-50k-receipts.json --port 18826` | 62 actual local transactions, 33 paid; paid work, reuse, migration and 1/3/8 pack batches passed. | Authenticated real FWA/Shapes/ShapePacks checkpoint, separate restored branches. A profile writer relative-path error occurred *after* transactions and was repaired without replaying them. |
| Paired sync/recovery receipts | `/Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_sync_contexts.py --starting-snapshot 0x14` | Six paid/unpaid pairs at 0.2/0.5 gwei, exact prestate digest and work event; three distinct operation contexts. | First attempt's base-fee setup failure is retained in `manager-measured-sync-contexts-attempt1.json`. The repaired run used the retained authenticated snapshot, not a new fabricated state. Other contexts remain unmeasured. |
| Exact cash reconciliation | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_reconcile.py --trace sim/out/manager-measured-final-reuse-trace.jsonl --output docs/receipts/manager-measured-reconciliation.json` | PASS, 16 actual traced steps; 0 wei unaccounted. | Source bound to the one-pack authenticated reuse trace, not a full operating return. |
| Model and receipt validity | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python -m unittest test_manager test_forward_randomness test_manager_operating_assessment` and `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --final --paths-per-window 1 --workers 1` | 41 tests pass; final input qualification passes and plans 144 rows. | Qualification checks inputs but does not run a financial path. Unknown sync contexts refuse a return rather than using quote coefficients as actual gas. |
| One bounded economic execution | `CANDIDATE_RUN=1 PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --execute --final --paths-per-window 1 --workers 1 --out sim/out/manager-measured-a8-bounded` | Stopped on the first recorded-month path before any financial row: `unmeasured sync context: 780000:1 count=1`. Failure/manifest retained in `sim/out/manager-measured-a8-bounded/`. | No annual or monthly owner-return figure follows. This is an explicit evidence gap, not a zero-return scenario. |
| Release/keeper focused checks | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python -m unittest script.test_release sim.test_manager_reconcile`; `/Users/dd/.pyenv/versions/3.11.8/bin/python keeper/test_config.py`; `python3 keeper/test_policy.py` | 26 unit tests, config and policy checks pass. | An initial umbrella unittest invocation used a non-package `keeper.test_config` path; that import-only failure was corrected with the script entrypoints. |
| Manager-only production postflight | `RPC_URL=http://127.0.0.1:18816 /Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py postflight-manager 0xdc9691d75dfc8d45fb44b5369dbb83e206aaf10b deploy/manager-factory.json 0x3e11af159fad319384f2908fce0d9d48f48ac22b 0x25EC2545E45989F754C67926a6e0Ff94D7e3C3f8 0` | PASS against a freshly created zero-funded local clone: runtime, owner, all 21 scalar and 29 gas settings, links, dependencies, fee, flags, budgets and zero inventory. | Local chain 31337, no shared vault. Creation receipt and pinned postflight readback retained. |
| Actual app interactions | Main pool affected Vitest batch: 81 pass/10 skip; migration focused: 13 pass; TypeScript check pass; `npm run build:app` pass. Local UI created two managers and migrated four intact packs in seven canonical writes, including a same-nonce reorganization recovery. | [Create](manager-measured-ui-create.json), [migration](manager-measured-ui-migration.json) and [canonical receipts](manager-measured-ui-canonical.json). The real-RPC Vitest paths require external environment and were skipped; the local UI used real local manager/FWA/Shapes/pack contracts. A >30-Shape unsupported recovery pack has a contract regression and app unit test, but no separate actual UI run. |
| Public read-only preplan | `RPC_URL=https://mainnet.gateway.tenderly.co /Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py existing-readback --target manager`; `cast nonce 0xCB43078C32423F5348Cab5885911C3B5faE217F9 --rpc-url https://mainnet.gateway.tenderly.co` | Block 26,493,799: 0.0005 ETH live fee; legacy vault 0.01 ETH; old factory manager count zero; known claims, reserves and fee credit zero; nonce still 4180. | Legacy unsupported selector remains an explicit read error. No public transaction. |

Compiled runtime sizes in the unsigned package are PackManager **20,707 B**, factory **4,876 B**, StrategyLib **14,456 B**, VaultLib **22,422 B**, ScanLib **21,310 B**; every listed transaction limit is below 16,777,216 gas. The constrained callback remains below its 100,000 gas stipend in the named fork tests. [Unsigned runbook](../release/MANAGER-RUNBOOK.md) contains the production-path dry-run and predicted addresses.

Independent review of the combined core/app identified and closed two migration findings: mixed sealed/unsealed recovery needed checked indexed withdrawal, and UI import eligibility had to be checked before transferring an unsupported pack. Its review of actual cash receipts found no mismatch. That was a bounded review, not an exhaustive security audit or release approval. The later sync profile extension was independently bound to raw events by the executable verifier but has not received a separate human review.

## A9 focused completion

The A8 rows above preserve their original revision and limits. A9 added real-counterparty paired sync/recovery receipts for scan, fee-credit and two-allocation work, including the formerly missing `780000:1:1` context. The [cost profile](manager-measured-cost-calibration.json) now holds 16 exact sync contexts with count-aware keys. The [checkpoint exports](../../sim/out/manager-measured-multi-checkpoint-v2-metadata.json) use a real FWA five-proof selection fixture and three directly paid primary mints per new pack. The source and event verifier rehashes authenticated checkpoints and checks the successful transaction receipts, `KeeperWorkMeasured` frames and identical paid/unpaid prestates. One failed 1x buyer-acquire attempt is preserved; the real buyer required 2x quoted value in the successful fork setup.

| Check | Command / evidence | Result | Limit |
|---|---|---|---|
| Real-counterparty sync gas receipts | `keeper/rehearse_manager_sync_scan.py` on isolated Tenderly-backed Anvil forks; nine included raw packets in the profile | Paid and owner-unpaid pairs at 0.2/0.5 gwei; exact scan/credit/two-allocation contexts, 0 public transactions | Four packet writer revisions were not preserved. Their billed receipts and work events are checked, but recorded RPC estimates have weaker provenance. Calibration overrides are gas-path evidence only. |
| Canonical cash reconciliation | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_reconcile.py --trace sim/out/manager-measured-final-reuse-trace.jsonl --output docs/receipts/manager-measured-reconciliation-a9.json` | PASS, 16 steps, 0 wei unexplained | One authenticated reuse trace, not the archived month. |
| Final input qualification | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --final --paths-per-window 1 --workers 4 --reconciliation docs/receipts/manager-measured-reconciliation-a9.json` | PASS, planned 96 rows | Verifies bounded receipt support and exact source inputs before the model. |
| Frozen economic execution | `CANDIDATE_RUN=1 PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --execute --final --paths-per-window 1 --workers 4 --reconciliation docs/receipts/manager-measured-reconciliation-a9.json --out sim/out/manager-measured-a9-final` | PASS, 96/96 rows, 96 qualified owner exits, all 24 reserve pairs had 0 owner-net difference, 0 wei aggregate ledger gap | Two archived windows and synthetic buyer response/quiet/burst assumptions; not demonstrated APR. The first frozen execution before the reviewer assertion repair had identical financial rows, matched by task key. |
| Affected unit and syntax pass | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python -m unittest test_manager test_forward_randomness test_manager_operating_assessment script.test_release sim.test_manager_reconcile`; `/Users/dd/.pyenv/versions/3.11.8/bin/python -m py_compile keeper/rehearse_manager_sync_scan.py keeper/rehearse_manager_measured.py sim/forward.py sim/manager_operating_assessment.py script/release.py`; `git diff --check` | Initial batch: 66 of 67 passed. One stale test expected only one measured sync position; after updating it to reject count 3, the focused failing test passed. Syntax and whitespace checks passed. | No new Solidity runtime or app source in A9; the earlier real-counterparty fork and UI interaction evidence remains tied to unchanged code. |
| Public read-only refresh | `cast block 26494440 --json --rpc-url https://mainnet.gateway.tenderly.co` and pinned `cast` reads | 0.0005 ETH live mint fee, signer nonce 4180, old factory manager count 0, legacy vault 0.01 ETH with no listed packs or known claim/processing liabilities; predicted new factory has no code | [Pinned raw readback](manager-a9-public-readback.json); old ABI's unsupported selectors remain explicit. |

The [independent A9 review](manager-a9-independent-review.md) found a keeper sync bootstrap/liveness problem and the measurement-script assertion issue. The assertion is fixed. The keeper issue and raw-estimate provenance limit remain visible; neither the model nor a positive isolated receipt proves unattended production service. No contract bytecode or app source changed in A9, so the prior A8 bytecode, callback, ABI, owner-exit and UI interaction checks remain tied to the same compiled code.

**Things that don't make sense.** A keeper can decline a profitable sync because its initial estimate ratio is too high, then never gather the three successful calls needed to adjust it. The 0.006 ETH reserve adds liquidity but does not cover bid-return losses. The archived return model cannot establish future demand, buyer choice or production readiness.

## A10 expanded path and packet binding

The A9 two-seed result above is historical. A first eight-seed-per-window attempt stopped after 104/320 rows on `960000:1:2`; its [failure](../../sim/out/manager-measured-a9-multiseed/failure.json) and source-bound manifest are preserved. A new [real FWA later-first packet](manager-measured-sync-multi-later-first.json) settled the later of two actual manager allocations first and measured that exact context at 0.2 and 0.5 gwei, paired with unpaid owner recovery from identical prestates. The packet passed four pairs and verified 3,598 exported fork-state fields. A public prerequisite read initially received HTTP 429; the writer now retries that read only.

Adding this packet exposed identical transaction hashes in two separate local forks with different surrounding states. The profile and verifier now identify each sample by **source packet and transaction hash**. The [independent review](manager-a10-independent-review.md) found no remaining cross-packet substitution in the scoped change.

| Check | Exact command | Result and limit |
|---|---|---|
| Later-first real-counterparty packet | `RPC_URL=https://mainnet.gateway.tenderly.co /Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_sync_scan.py --multi --resolve-later-first --scan-positions 2 --block-fork --port 18840 --output docs/receipts/manager-measured-sync-multi-later-first.json` | PASS, 4 paid/owner pairs; no public transaction. The packet records the authenticated fork-state restoration, billed receipts and writer hash. Its fee-share override reaches the credit-sweep gas path and is not candidate payment economics. |
| Receipt profile and final input check | `PYTHONPATH=keeper /Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_measured.py --profile-only --output docs/receipts/manager-measured-50k-receipts.json`; `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --final --paths-per-window 8 --workers 4 --reconciliation docs/receipts/manager-measured-reconciliation-a9.json` | PASS, 17 raw packets and 17 exact sync contexts. The verifier keys billed gas, meters, estimates and paired prestates by packet/hash. Four older writer revisions and writer-recorded RPC estimates retain the A9 provenance limit. |
| Expanded frozen execution | `CANDIDATE_RUN=1 PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py --execute --final --paths-per-window 8 --workers 4 --reconciliation docs/receipts/manager-measured-reconciliation-a9.json --out sim/out/manager-measured-a10-release` | PASS, 320/320 rows, 320 qualified exits, largest ledger gap 0 wei, 160 complete paired reserve comparisons with zero difference. These are 16 recorded selection paths on two demand tapes, plus quiet/burst stress, not 320 independent market trials. There are zero ordinary keeper syncs and 288 owner syncs during exit. |
| A10 affected unit and source pass | `PYTHONPATH=sim:keeper /Users/dd/.pyenv/versions/3.11.8/bin/python -m unittest test_manager test_forward_randomness test_manager_operating_assessment script.test_release sim.test_manager_reconcile`; `/Users/dd/.pyenv/versions/3.11.8/bin/python -m py_compile keeper/rehearse_manager_sync_scan.py keeper/rehearse_manager_measured.py sim/forward.py sim/manager_operating_assessment.py script/release.py`; `git diff --check` | Initial 67-test batch had 65 passes and two legacy single-packet tests that lacked a packet label. The verifier now allows that omission only when exactly one raw packet exists; both focused failing tests passed. The final full affected pass had **67/67 tests pass** after the reviewer-found proxy fallback repair. Syntax and whitespace checks passed. | The final 320-row replay after this repair has identical financial rows by scenario key to the prior complete run, and its source hashes match the final files. No broad test suite was repeated. |
| A10 public readback and refreshed manager-only dry-run | `RPC_URL=https://mainnet.gateway.tenderly.co /Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py existing-readback --target manager`; pinned `cast` reads; `CANDIDATE_RUN=1 RPC_URL=https://mainnet.gateway.tenderly.co FORGE_WALLET_ARGS='--sender 0xCB43078C32423F5348Cab5885911C3B5faE217F9' script/deploy.sh deploy/manager-factory.json --target manager` without `--broadcast` | [Block 26,494,800](manager-a10-public-readback.json): mint fee 0.0005 ETH, nonce **4181**, old manager count zero, legacy vault 0.01 ETH, known liabilities zero; new predicted factory has no code. The Forge production-path simulation and local postflight passed; dry-run nonces 4181–4184. [The log](manager-measured-unsigned-dry-run-a10.log) records a release-check Python import error from the shell's default interpreter; the final committed release check is reported separately. | The prior nonce-4180 unsigned package is historical and must not be signed. The simulation had no public transaction or signature. |

No Solidity runtime, ABI or app source changed in A10. The earlier real-counterparty fork, bytecode/callback, owner-exit and UI interaction checks remain applicable to that unchanged code. The expanded study is a conditional replay; it does not demonstrate unattended renewal, future fee income or APR.

**Things that don't make sense.** A positive model mean accompanies zero ordinary sync/relist cycles. Repeated local transaction hashes are possible across separate isolated forks, so a receipt hash alone is not a unique evidence key. More selection seeds on two archived months do not create new demand histories.

## Current-source rebind (D88 launch-audit repairs)

Rebinds the profile after D88: `_setDesign` rejects 0 and the factory has only the design-carrying
`create`; keeper gas is re-anchored in each library frame (`spent` across calls) so the caller's gas
limit no longer inflates `measured`; `preview` returns `configHashFor`. Same three-packet procedure on
a fresh 8545 checkpoint; the writers now create with an exact mix (`full_design`: 255 of each admitted
size). [main](manager-measured-50k-receipts-v4.json) PASS 64 tx, [sync-contexts](manager-measured-sync-contexts-v4.json)
PASS 18, [owner-exit](manager-measured-owner-exit-v4.json) PASS 13; zero public transactions.

| Paid op | receipts | keeper-loss receipts | min keeper net (wei), v4 (v3) | single-work gasUsed, v4 (v3) |
|---|---|---|---|---|
| build | 6 | 0 | 67,506,800,000,000 (77,459,400,000,000) | 1,816,369 (1,815,697) |
| list | 9 | 0 | 26,156,000,000,000 (32,502,600,000,000) | 1,152,811 (1,152,578) |
| sync | 4 | 0 | 5,448,000,000,000 (7,729,400,000,000) | 353,066 (352,806) |

Keeper net falls because pay no longer includes the withheld forwarding gas; work gas rises by the
design check and re-anchoring (233 to 672 gas). `test_gasLimitDoesNotChangeMeasuredPay` measured
1,880,167 vs 2,246,424 gas at 3M vs 15M gas limits on the old code and identical values after the fix.

## Current-source rebind (A9.8 replaceable factory implementation)

Rebinds [`manager-measured-cost-calibration.json`](manager-measured-cost-calibration.json) to `src/**/*.sol`
after D87 (`PackManagerFactory.setImplementation`, two-step admin; `PackManager` takes its factory as a
constructor argument). The same three-packet procedure as the D86 rebind below, freshly executed on a
retained 8545 Anvil with a freshly exported checkpoint (the prior checkpoint files are in Git history):
[main](manager-measured-50k-receipts-v3.json) PASS 64 tx, [sync-contexts](manager-measured-sync-contexts-v3.json)
PASS 18 tx, [owner-exit](manager-measured-owner-exit-v3.json) PASS 13 tx; zero public transactions.

| Paid op | receipts | keeper-loss receipts | min keeper net (wei) | single-work gasUsed (v2) |
|---|---|---|---|---|
| build | 6 | 0 | 77,459,400,000,000 | 1,815,697 (1,815,758) |
| list | 9 | 0 | 32,502,600,000,000 | 1,152,578 (1,152,578) |
| sync | 4 | 0 | 7,729,400,000,000 | 352,806 (352,806) |

Exit unlist and liquidate stay unpaid (D86) with gasUsed identical to v2. The manager runtime and its
libraries are unchanged by D87, so keeper work gas matches v2 within 61 gas; only factory creation changed.

## Current-source rebind (D86 unpaid exit)

Rebinds [`manager-measured-cost-calibration.json`](manager-measured-cost-calibration.json) to the current
`src/**/*.sol` at HEAD (audit B2 I-2, `ordinaryShapeCount` removed from `VaultLib`/`PackManager`;
`gasSchedule.build` now 540,000) from three freshly executed real-counterparty packets, and makes the sim
model match the contract's D86 decision that **exit work is unpaid**. No mocks; authenticated
FWA/Shapes/ShapePacks checkpoint re-exported with the current manager bytecode; all local chain 31337;
zero public transactions.

**Packets (all PASS, `contractSourceSha256` == current `src`):**

| Packet | Command | Result |
|---|---|---|
| [main measured](manager-measured-50k-receipts-v2.json) | `CANDIDATE_RUN=1 python keeper/rehearse_manager_measured.py --execute --output docs/receipts/manager-measured-50k-receipts-v2.json --port 8545` | PASS, 64 tx. build 6 / list 9 / sync 4 **paid** (metered); unlist 8 / liquidate 6 **unpaid** (D86); a keeper exit call with nonzero `minPay` reverts `Payment` (`exitUnpaidMinPayRevertsPayment`). |
| [sync-contexts](manager-measured-sync-contexts-v2.json) | `python keeper/rehearse_manager_sync_contexts.py --port 8545 --base <main-v2> --output <sync-v2>` | PASS, 6 paid sync / unpaid owner recover pairs on identical prestates, 6 contexts. |
| [owner-exit](manager-measured-owner-exit-v2.json) | `python keeper/rehearse_manager_owner_exit.py --port 8545 --base <main-v2> --sync <sync-v2> --output <owner-exit-v2>` | PASS, owner `recoverUnlist`/`recoverLiquidate` at batch 1/3/8, billed gas only (caller-funded, pay 0). Drains the one authenticated FWA acquisition before building. |

The three runs share one retained Anvil on 8545 by reverting the main run's post-setup snapshot
(recorded as `postSetupSnapshot`, threaded through each packet). The checkpoint was re-exported fresh
(no `--export-existing`) because the `VaultLib`/`PackManager` change alters the manager bytecode.

**Writer behaviour bound into the profile source hashes:**
- Real Shapes-admin `setMintFee(0.0005)` + owner `acceptMintFee(0.0005)` before `setParams`, because the
  authenticated checkpoint block runs the live fee at 0.001 ETH while this candidate accepts 0.0005
  (historical fork alignment, recorded as a limitation, not a candidate input).
- Exit `unlist`/`liquidate` exercised **unpaid** (`minPay` 0 while winding down; pay 0, billed gas
  recorded), with an explicit check that a nonzero `minPay` reverts `Payment`.
- List/build backing proposals read live from `preview().backing` (**0.033159 ETH** at `backingRatioBps`
  11053), replacing a stale `0.21 ETH` constant from the earlier 70000 bps config.

**Model (`sim/manager_operating_assessment.py`):** `METERED_OPERATIONS` is `('build','list','sync')`. Exit
`unlist`/`liquidate` are priced through the owner (caller-funded) curves as an owner expense;
`qualify_costs` keeps requiring their owner curves. `sim/test_manager.py` and
`sim/test_manager_operating_assessment.py` assert the unpaid-exit rule (`essential_keeper_paid_wei == 0`;
owner unlist/liquidate samples carry no work meter) rather than a metered exit payment.

**Routine unlist — explicit gap (not a proxy):** a non-exit, underwater paid `unlist` stays a paid op in
the contract but is unreachable for a personal manager (no holder shortfall) without forcing FWA
economics, which is forbidden. Left as an explicit untested gap; `qualify_costs` runs without it. No proxy
gas was invented.

**Dropped context coverage.** The 3-packet set drops the 12 superseded multi-packet sync files (kept on
disk as history), removing **14 sync contexts and 14 owner-recover contexts** — the two-position
multi-allocation keys (`1005000:1:2`, `1035000:1:2`, `1080000:2:2`, `1295000:2:2`, `1335000:2:2`,
`1365000:2:2`, `705000:1:2`, `960000:1:2`, `965000:1:2`) and the single scan allowances
(`710000`/`740000`/`750000`/`780000`/`810000`:1:1) — plus the build-splitting comparison and two extra
single build/list samples. The kept profile covers single-position sync only, so `supported_work['sync']`
is **1**; a broad economic replay would refuse any sync landing in a dropped context.

**Measured vs allowance (current source, build allowance 540,000 → 2,055,000 per 3-Shape pack; main-run
prices 0.2 / 0.5 gwei):**

| Paid op | receipts | measured > allowance (clipped) | max excess gas | comp < gas cost (keeper loss) | min keeper net (wei) |
|---|---|---|---|---|---|
| build | 6 | 0 | 0 | 0 | 77,460,000,000,000 |
| list | 9 | 0 | 0 | 0 | 32,502,600,000,000 |
| sync | 4 | 0 | 0 | 0 | 7,192,000,000,000 |

Single-work gas: build billed 1,815,758 / estimate 2,016,729 / meter 1,953,058 vs build allowance
**2,055,000**; list 1,152,578 / 1,219,076 / 1,165,079; sync 459,240 / 748,106 / 549,308. Exit (unpaid, owner
expense) billed single-work: keeper-caller unlist 501,238, liquidate 267,424; owner recover 586,669 /
249,356. Overhead 50,000.

**Build clipping resolved.** With `gasSchedule.build` 540,000 the per-pack build allowance (2,055,000) now
exceeds the build meter (1,953,058) **and** its estimate (2,016,729), so build compensation is no longer
clipped: 0 clipped receipts, 0 keeper-loss receipts across build/list/sync, and build keeper net stays
positive on its own allowance rather than only on the work fee. The earlier 360,000 rebind clipped build by
~101k gas; that is fixed. (`test_unmeasured_127_foreign_tail_...` keeps its committed 5x build budget.)

**Things that don't make sense.** Exit work pays the keeper nothing, so a personal manager's owner must
self-serve `recoverUnlist`/`recoverLiquidate`; there is no paid keeper fallback during an owner-absent
shortfall. Dropping the multi-allocation packets leaves the model unable to price any multi-position sync.
The three-packet snapshot handoff is single-use per snapshot; a clean main -> sync-contexts -> owner-exit
sequence threads it automatically, but an interrupted run needs the post-setup snapshot recovered by id.
