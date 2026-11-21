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
| Authenticated keep/kick receipt identification (`receive`) | Redemption shortfall and liquidation need | One-time factory initialization |
| Unlisting and liquidation, bounded recovery of oversized packs | One-way wind-down, deposit pause | |
| Keeper pay by quote, budgets, policy offer, `minPay` | Deploy and unwind charges | |
| Token claim and burn (never valued) | | |
| Parameters within bytecode bounds, policy, two-step ownership | | |

## 3. Recipe and backing

New packs: 0.06 ETH = one 0.05 Shape + one 0.01 Shape minted straight into the pack
(`ShapePacks.createPack([], [1, 1, 0, …])`): two paid primary mints, 0.002 ETH at the 0.001 fee.
Backing at the 0.5 gwei ceiling: 0.06515847 ETH (1.086 × P). A selected purchaser keeps a pack
worth 0.06 rather than take FWA's best bid (91.5% token bid: 0.05962 ETH) by 0.0003 ETH after the
gas to redeem it. Each keep returns B (1 − s) = 0.06451 ETH to the account and triggers a
replacement build with fresh mints; each bid returns the pack for relisting without a mint.
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

<!-- ECONOMICS, VERIFICATION, BLOCKERS AND NEXT STEPS: filled from the study and test results -->
