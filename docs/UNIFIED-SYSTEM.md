# Unified shapes FWA system

Branch `claude/unified-shapes-fwa-system-852d17`, from main `78ad729`. Owner brief: OWNER-REQUIREMENTS A3.
Decisions: D77–D83. Status: draft PR; nothing deployed, no real funds moved, mint fee unchanged.

## 1. Architecture

```
                          FWA V2 main pool (one depositor of record per listing)
                                ▲   listNFT / sync / withdraw / fees          ▲
                                │                                             │
   holders ──deposit/redeem──► PackVault ──┐                  ┌── PackManager (clone) ◄── one owner
                               (shares,    │                  │   (withdraw ETH, packs;
                                checkpoints,│                  │    pause, exit mode)
                                reserves)   │                  │
                                            ▼                  ▼
                                    PackAccount: one operating surface
                     build · list · sync · unlist · liquidate · harvest · burnTokens · views
                                            │ DELEGATECALL, account's own storage
                                            ▼
                      StrategyLib ──► VaultLib ──► ScanLib       (stateless, linked once)
                      operations      book, economics,  own-position scan
                                      journal, settlement,
                                      recovery, keeper pay
                                            │
                   ShapePacks.createPack (mint Shapes straight into the pack) · Shapes mint fee

   PackManagerFactory ── creates ERC-1167 clones of one PackManager implementation; no owner,
                         no fee, no authority after creation. KeeperPolicyV1: shared pay quote.
   keeper/ (one codebase) ── schedules the vault and every discovered manager independently.
```

Every account is the FWA depositor of record for its own listings and holds its own ETH, packs and
book. The libraries run in the account's context, have no state and no withdrawal path. There is
no central strategy contract, custodian, registry or keeper coordinator.

## 2. Shared versus ownership-specific

| Shared (one implementation: PackAccount + StrategyLib + VaultLib + ScanLib) | Pool only (PackVault) | Manager only (PackManager) |
|---|---|---|
| Direct-mint pack construction and atomic listing (`build`) | Shares, dead seed shares, high-water mark | Single owner custody, no shares or NAV |
| Live FWA economics, backing rule and admission gate (`edge`) | Escrowed deposits, cancellation, request charges | `withdraw` any ETH, `withdrawPacks` idle packs |
| Relisting returned packs (`list`) | Checkpoints in FWA's blackout, epoch pricing | `rescue` untracked NFTs |
| Position book, journal and own-position scan, settlement (`sync`) | Pro-rata redemptions, claims, distributions | `setListingPaused`, reversible exit mode |
| Fee collection inside paid work; caller-funded `harvest` | Protected liabilities in `_free` | `_free` = balance, `_idle` = balance − reserve |
| Settlement from FWA's own listing record and pack ownership; `receive` receipts gate pricing (D84) | Redemption shortfall and liquidation need | One-time factory initialization |
| Unlisting and liquidation, bounded recovery of oversized packs | One-way wind-down, deposit pause | |
| Keeper pay by quote, budgets, policy offer, `minPay` | Deploy and unwind charges | |
| Token claim and burn (never valued) | | |
| Parameters within bytecode bounds, policy, two-step ownership | | |

## 3. Recipe and backing

New packs: 0.06 ETH = one 0.05 Shape + one 0.01 Shape minted straight into the pack
(`ShapePacks.createPack([], [1, 1, 0, …])`): two paid primary mints, 0.002 ETH at the 0.001 fee.
Backing: 0.06489617486338 ETH (1.082 × P), fixed by the rule, not by keeper settings (D85). A
selected purchaser keeps a pack worth 0.06 rather than take FWA's best bid (the 91.5% token bid:
0.05938 ETH) by 0.0003 ETH after 160,000 gas to redeem it at up to 2 gwei. Each keep returns
B (1 − s) = 0.06424721 ETH to the account and triggers a replacement build with fresh mints; each bid
returns the pack for relisting without a mint. FWA pays keeps and kick refunds by pushing ETH; if
the account's `receive` ever fails, FWA force-sends it and `sync` still resolves the listing from
FWA's record (D84).
Rule and gates: D80. Measured construction gas: D79.

## 4. Contract and deployment costs

| Artifact | Runtime bytes (EIP-170 limit 24,576) | Deployed per |
|---|---:|---|
| PackVault | 16,970 | pool |
| PackManager implementation | 12,453 | once (factory constructor) |
| PackManager clone | 44 | user, 474,076 gas `create` (clone + initialize + discovery) |
| PackManagerFactory | 1,365 | once |
| StrategyLib | 12,758 | once (linked) |
| VaultLib | 23,409 | once (linked) |
| ScanLib | 1,935 | once (linked) |
| KeeperPolicyV1 | 216 | once, shared |

FWA pushes keep payments and kick refunds with a 100,000 gas stipend. Through the clone's extra
DELEGATECALL: keep payment 52,363 gas, cold kick refund 35,148 gas (`ForkManager.t.sol`).

One-time deployment, billed on a local Anvil fork through `script/deploy.sh` (receipts,
`docs/receipts/unified-local-rehearsal.json`): ScanLib 471,981; VaultLib 5,094,213; StrategyLib
2,817,411; KeeperPolicyV1 100,155; PackVault 4,146,177; PackManagerFactory with its implementation
3,122,421; **total 15,752,358 gas** (0.0079 ETH at 0.5 gwei). A personal manager then costs its
owner 462,707 gas to create (0.00023 ETH at 0.5 gwei) and nothing else; there is no fee.

Billed operation gas against the fixed quotes (`ForkMaxBatchGas.t.sol`): build 1 pack 1,667,571 vs
1,685,000; build 8 packs 9,466,009 vs 11,380,000; unlist 8 2,224,463 vs 2,620,000; liquidate 8
(16 Shapes) 1,129,652 vs 1,275,000; relist 8 6,198,724 vs 6,880,000. Largest batch (build 8 × 30
units) 10.40M gas, 13.0M with the keeper's 25% pad, under EIP-7825's 16,777,216.

## 5. Economics

Two models, both with tokens at zero. Numbers are model results, not forecasts.

**Formal gate (`sim/formal.py`, `docs/receipts/formal-assessment.json`).** The owner's hurdle: 10% a
year net at trailing-30-day volume, 0.5 gwei ceiling, every expense included, complete exit. The
actual 30 days at block 26,450,200 replayed for 360 days plus exit, 16 seeds, purchasers sampled from
recorded responses and, conservatively, every responder bids in time:

| Pool | Median | p10 | Worst | Losing runs | Creator mint fees / yr |
|---|---:|---:|---:|---:|---:|
| 1.96 ETH (canary values) | **+50.2%** | −51% | −61% | 6 / 16 | 0.077 ETH |
| 6.8 ETH | **+50.7%** | +16% | −49% | 1 / 16 | 0.24 ETH |
| 20 ETH | **+37.9%** | +17% | +6% | 0 / 16 | 0.61 ETH |

The hurdle passes at every size on the median. Diagnostics at 1.96 ETH: recorded choices (keeps
stay keeps) median +162%, 0.66 ETH mint fees; last 10 days' volume +9.4% median (7 / 16 lose);
zero demand −2.3%; with FWA's oracle cap restored nothing lists (−0.05%). Since D80 a value-aware
purchaser keeps, so the formal case is a lower bound for both returns and creator revenue.

**Comparative study (`sim/unified.py`, `sim/out/unified.md`, 256 seeds per cell).** Event replay of
the latest 30 days of mature FWA history with every account's listings inserted into FWA's weights,
counts and fee split; used for comparisons, not for the gate. Recipes at 2 ETH, designed behaviour:

| Recipe | Mean | p5 | Loss probability | Creator mint fees per ETH a year |
|---|---:|---:|---:|---:|
| 0.03 bulk mint + split, bid backing (main) | +80% | −82% | 25% | 0.004 |
| 0.03 bulk mint + split, keep backing | +380% | +226% | 0% | 0.58 |
| 0.03 direct mint | −1.8% | −1.8% | 100% | 0.05 |
| **0.06 direct mint (chosen)** | **+186%** | **+30%** | **2.3%** | **0.96** |
| 0.07 direct mint | +146% | −12% | 7% | 1.08 |

- Direct 0.03 packs fail the build gate: one keep cannot repay three fresh mints, so kept packs are
  never replaced. Direct 0.07 packs pay the creator slightly more per ETH with a worse tail.
- The 0.03 split recipe returns more because each pack pays 0.0003 ETH in fees, but it keeps the
  bulk-mint construction, pays the creator 40% less and takes twice the FWA weight per ETH. The 0.06
  recipe is the best simple design for both creator and capital provider; no dynamic sizing.
- Purchaser behaviour dominates: the 0.06 recipe falls to +83% mean (23% loss) if nobody keeps. The study has no cash path: losses are truncated at −100% (ruin) and an account's pack count is fixed, so small-account tails are approximate; the formal gate above has the cash path.

**Pool versus personal managers.**

| Question | Answer (model) |
|---|---|
| Same capital, pool or managers? | Pool, always in these runs: 10 ETH pool +181% vs ten 1 ETH managers +162%, from one reserve (0.005 vs 0.05 ETH idle) and higher utilisation (0.98 vs 0.88). |
| Smallest useful manager | ~0.14 ETH (one pack: reserve + B + P + build). Below it nothing lists. With one pack the outcome is a lottery; 0.5 to 1 ETH gives a usable tail. |
| Value of shared inventory and cash | Utilisation 0.63 (50 × 0.2 ETH managers) / 0.88 (10 × 1 ETH) vs 0.98 pooled; mean +117% / +163% vs +172% at 10 to 20 ETH. |
| Cost of pooled accounting | ~0.00007 ETH a year of checkpoint pay plus a 0.0002 ETH request charge per flow; negligible beside pooling's benefit. |
| Creator mint fees per ETH | Set by the recipe and the keep rate, not the product: 0.96 ETH per ETH a year for 0.06 packs when purchasers keep; managers pay slightly less because more of their ETH sits idle. |
| Aggregate participation | Our combined share of FWA weight 0.26% → 2.5% → 11% → 34% → 56% moves each account's mean +179% → +170% → +145% → +97% → +64%: negligible below ~2.5%, large above ~10% (D81). |

## 6. Verification

Candidate source `749503c` (manifest `deploy/release-manifest.json`, unsigned). Every claim below names its run.

- Fork tests on the real FWA, Shapes, ShapePacks, oracle and token pool; no mocks. Manager and
  factory (`ForkManager.t.sol`, 15 tests): lifecycle to the wei, initialization, owner-only controls
  and two-step handover, pause and zero budgets, isolation from other managers and the pooled vault,
  cold kick refund under FWA's stipend, reentrant keeper, real-VRF keep, bid and silent outcomes.
  Ported suites: vault lifecycle 16, adversarial 18, keeper pay 17, keeper policy 7, selection 4,
  backing 3, tokens 3, invariants 4, asset-flow regimes 16 (0 conservation mismatches), audits 23,
  production 25, journal/scan/harvest/measure suites, max-batch gas 4. Full candidate run: section 6a.
- `sim/reconcile.py`: every bucket of the three reconcile fork runs matches the integer model to the
  wei. Python: `keeper/test_policy.py`, `test_index.py`, `test_inclusion.py`, `sim/test_vault.py`,
  `test_forward.py`, `test_unified.py` pass.
- Local deployment rehearsal (Anvil fork, no public writes): deploy and postflight; a manager from
  the factory; the one keeper built and listed 7 packs in one call, then on owner exit unlisted and
  redeemed them; the owner withdrew 1 ETH − 0.014 mint fees − 0.001852 keeper pay, to the wei. It
  found three keeper bugs, all fixed: repeated build proposals, one index file for all accounts, one
  account's error stopping the pass.
- Independent security and economic review of the contract diff: no critical or high finding.
  Holder protections in PackVault are unchanged from main. Low/informational items: see section 7.

### 6a. Full candidate run

`script/verify.sh` with `CANDIDATE_RUN=1` at source revision `749503c` (`docs/receipts/unified-verify/SUMMARY.md`):
exit 0. Build with sizes; `sim/test_vault.py`, `sim/test_forward.py`, `keeper/test_policy.py`,
`keeper/test_index.py`, `sim/replay.py`; **268 fork tests passed, 0 failed, 1 skipped** (a fixture
exporter that runs only on request); the 301-listing and 10,000-position scale tests 3/3; the
reconciler matches every bucket to the wei on the full cycle, the partial fill and wind-down, and the
scan path; `release.py check deploy/canary.json` passes (no signature checked). The first run at
`86edea6` failed one test from a test-helper timing bug (via_ir cached `block.timestamp`), fixed in
`749503c` and covered by the rerun.

## 7. Remaining launch blockers and owner decisions

1. **Owner signature.** `docs/release/acceptance.json` and `asset-flow.json` outcomes describe the
   pre-A3 candidate (bid-favouring backing, 0.03 packs). The restated outcomes and the acceptance
   package need the owner's review and signature before any public broadcast (D73).
2. **Canary size.** The formal gate passes at 1.96 ETH on the median, but 6 of 16 runs lose and p10
   is −51%. At 20 ETH no run loses. Choose the canary's size with that tail in view.
3. **Third-party levers on new investment** (exits are unaffected): FWA keeping ShapePacks
   oracle-exempt; FWA's best bid below about 94.4%; the routine gas ceiling below about 11.9 gwei
   (D80). Each stops new building and listing in every account at once.
4. **Release rehearsal tooling.** `keeper/rehearse_canary.py`, `rehearse_current.py`,
   `rehearsal_batch.py`, `measure_gas.py` and the old calibration scripts target the pre-A3 candidate
   (restock, loose Shapes) and were not ported; the image rehearsal (`rehearse_image.py`, CI) must be
   rerun for the new keeper. The local rehearsal above used `script/deploy.sh` and `keeper/keeper.py`
   directly.
5. **Monitored assumptions:** FWA's 100,000 gas push stipend (keep payment 52,363 gas today; no
   fallback if a repricing ever exceeded it); our combined FWA weight share (keeper reports it,
   flags 10%); the keep incentive counts FWA's token bid at face value.

## 8. Next steps that need the owner

1. Review this document, D77–D83 and OWNER-REQUIREMENTS A3; decide the canary size (item 7.2).
2. Restate and sign `asset-flow.json` outcomes and `docs/release/acceptance.json` for this candidate.
3. Approve a current-block rehearsal with the ported rehearsal tooling and the keeper image.
4. Authorize the public broadcast (`script/deploy.sh deploy/canary.json --broadcast` from the owner's
   keystore), then keeper funding and Fly deployment with `VAULT` and `FACTORY` set.
5. Separately decide whether to publish the factory address for personal managers at launch or after
   the pooled canary has run.

