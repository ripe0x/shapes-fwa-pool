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
| PackVault | 16,960 | pool |
| PackManager implementation | 12,494 | once (factory constructor) |
| PackManager clone | 44 | user, 474,175 gas `create` (clone + initialize + discovery) |
| PackManagerFactory | 1,365 | once |
| VaultLib | 23,482 | once (linked) |
| StrategyLib, ScanLib | in `deploy/release-manifest.json` | once (linked) |
| KeeperPolicyV1 | 216 | once, shared |

FWA pushes keep payments and kick refunds with a 100,000 gas stipend. Through the clone's extra
DELEGATECALL: keep payment 52,363 gas, cold kick refund 35,148 gas (`ForkManager.t.sol`). If a future
repricing ever pushed `receive` past the stipend, FWA force-sends the ETH and `sync` still resolves
the listing from FWA's record (D84).

One-time deployment, billed on a local fork through `script/deploy.sh` at the final source: ScanLib
634,563; VaultLib 5,140,640; StrategyLib 2,817,411; KeeperPolicyV1 100,155; PackVault 4,143,997;
PackManagerFactory with its implementation 3,131,319; **total 15,968,085 gas** (0.0080 ETH at
0.5 gwei, 0.032 ETH at 2 gwei). A personal manager costs its owner 474,175 gas to create and nothing
else; there is no fee.

Billed operation gas against the fixed quotes (`ForkMaxBatchGas.t.sol`): build 1 pack 1,667,571 vs
1,685,000; build 8 packs 9,466,009 vs 11,380,000; unlist 8 2,224,463 vs 2,620,000; liquidate 8
(16 Shapes) 1,129,652 vs 1,275,000; relist 8 6,198,724 vs 6,880,000. Largest batch (build 8 × 30
units) 10.40M gas, 13.0M with the keeper's 25% pad, under EIP-7825's 16,777,216. The checkpoint's
allocation proof reads at most 32 queue entries: 186,274 gas at the bound against a 222,000 quote,
and a constant 31,763 gas refusal beyond it whatever the history (D84).

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

Final source (manifest `deploy/release-manifest.json`, acceptance package unsigned). Every claim names its run.

- **Full candidate run** (`docs/receipts/unified-verify/SUMMARY.md`): `script/verify.sh` with
  `CANDIDATE_RUN=1`; **276 fork tests passed, 0 failed, 1 opt-in exporter skipped**; the 301-listing
  and 10,000-position scale tests 3/3; `sim/replay.py` 0 mismatches; the reconciler matches every
  bucket to the wei on the full cycle, the partial fill and wind-down, and the scan path. All on the
  real FWA, Shapes, ShapePacks, oracle and token pool; selections only from replayed real VRF.
- **Payment receipt recovery** (`ForkReceiptRecovery.t.sol`): the account's `receive` is made to fail
  around one real FWA call, FWA's own SELFDESTRUCT fallback delivers the ETH with no receipt, and the
  forced keep, the forced default (`finalizeUnsettled`) and a manager's forced kick refund each resolve
  exactly once, with the same book, cash and NAV as the recorded path; a stranger's payment of the
  exact amount creates no receipt; the checkpoint refuses to price until the sync. With the real
  receiver, a sweep over transaction gas never forces an unrecorded payment (65 limits reverted,
  26 completed and recorded). Removing the checkpoint gate makes the forced-keep test fail.
- **Bounded pricing** (`ForkAllocationProof.t.sol`): 32-entry boundary, 2,000 tombstones behind an
  unresolved head refused at the same 31,763 gas as 33, many simultaneous unresolved allocations.
- **Asset flow:** 16 regimes, outcomes O1–O11 pass (`asset-flow.json`, unsigned).
- **Production rehearsal** on a fresh mainnet fork (`docs/receipts/unified-production-rehearsal.json`,
  `keeper/rehearse_unified.py`): all 17 steps pass on the final source: deploy through `script/deploy.sh`,
  three managers from the factory, one keeper discovering all four accounts, building and listing,
  pooled deposit, checkpoint, redemption and claim, keep, bid (then relist without a mint), expiry and a
  forced keep from a real request and its historical VRF word (`keeper/rehearse_selection.py`; only the
  coordinator's proof check is skipped), manager withdrawals and full exits, keeper restart, a new
  worker on the same volume, the backup keeper working alone and contending, a paused account not
  stopping the others, per-account index persistence, a lost transaction response, same-nonce
  replacement and a reorg; every account reconciles at the end. Encrypted keystores throughout.
- **Production image** (CI run 44930570759, `docs/receipts/image-rehearsal/ci-44930570759.json`): the
  pinned image against a fresh fork: keystore signing, primary and backup, a replacement container on
  the same volume, a lost RPC response. Push CI only builds and smokes the image (under a minute); the
  fork rehearsal runs on manual dispatch for a release candidate.
- **Independent review** (`docs/receipts/unified-review.md`): no critical, high or medium finding.
  Confirmed: the factory has no access to a manager's funds after creation; no manager can move or
  account another's assets; the pool cannot subsidise managers. A second review of 958b924 found the
  unbounded allocation proof, fixed in 4794bf5.

## 7. Remaining launch blockers and owner decisions

1. **Owner signature.** The restated `asset-flow.json` outcomes and `docs/release/acceptance.json`
   are unsigned. No broadcast until the owner signs (D73).
2. **Canary is a technical deployment.** At 2 ETH the formal gate's loss tail is wide (see section 5);
   the canary verifies operation and exit, not returns. Capital is not raised to improve modeled
   returns (A4.7).
3. **Third-party levers on new investment** (exits are unaffected): FWA keeping ShapePacks
   oracle-exempt and its best bid below about 94.4% (D80). Each stops new building and listing in every
   account at once. The keeper gas ceiling no longer affects listing (D85).
4. **Accepted residual (D84):** a kick refund force-sent while `receive` fails is not caught by the
   checkpoint gate; it needs FWA to lift the exemption and a gas repricing at once, and the keeper
   syncs on `ListingKicked`.
5. **Monitored assumptions:** FWA's 100,000 gas stipend; our combined FWA weight share (keeper flags
   10%); FWA's owner-set economics (surcharge, discounts, fees) staying near today's values.

## 8. Next steps that need the owner

1. Review this document, D77–D85, OWNER-REQUIREMENTS A3 and A4, and `docs/release/ACCEPTANCE.md`.
2. Sign `docs/release/acceptance.json` (which binds the manifest, values and outcomes) if accepted.
3. Authorize the public canary broadcast (`script/deploy.sh deploy/canary.json --broadcast` from the
   owner's keystore), keeper funding (primary 0.05, backup 0.02 ETH) and the Fly deployment with
   `VAULT` set and `FACTORY` unset (`docs/release/RUNBOOK.md`).
4. Separately, after the canary assessment, decide whether to offer personal managers publicly
   (set `FACTORY` for the keepers, publish the factory and `deploy/manager.json`).
