# Owner requirements

The owner's own words, numbered and dated. Later decisions are appended, never rewritten.
Section B2 lists outcomes proposed for the owner's sign-off; none is approved yet.

## A. Requirements (owner's words)

Source: "FWA Depositor Vault: live findings and implementation plan", revision 2, 2026-11-15.

1. (2026-11-15) "main pool only."
2. (2026-11-15) "One immutable deployment with full functionality (distributions, token
   conversion, keeper compensation all in). Phases below are build and validation order, not
   product versions."
3. (2026-11-15) Gate: "10% a year net of gas at trailing-30-day volume with tokens at zero.
   Capacity at that hurdle is reported, not a pass or fail condition."
4. (2026-11-15) "No minimum TVL to start. The vault operates from the first deposit: small
   minimum deposit (first-issuance protection only), and it lists whenever idle ETH above
   reserves covers one position."
5. (2026-11-15) "Fixed costs must therefore scale down: a checkpoint runs only when there are
   pending deposits, redemptions or a distribution due, and sync and harvest batches are skipped
   when their gas exceeds the value they realize."
6. (2026-11-15) "RPC: Tenderly's public mainnet gateway (https://mainnet.gateway.tenderly.co) as
   the default MAINNET_RPC_URL."
7. (2026-11-15) "Larger packs: yes. ... The vault carries a governed allowed-P set bounded in
   bytecode; canList already rejects any size the live cap makes unprofitable."
8. (2026-11-15) Gate conditions (plan 0.5): "Go only if net of gas the bid outcome is positive at
   the gas ceiling, annualized return at last-30-day volume clears the hurdle with tokens at
   zero, and there is at least one usable exit window a day."
9. (2026-11-15, overnight instruction) "complete the entire process e2e without asking me for
   more info ... create a list of decisions you made that you normally would have asked me
   about" (see docs/DECISIONS.md).
10. (2026-11-16) Gate volume window: "Keep 30-day" (answer to D17; 7-day not adopted).
11. (2026-11-16, repair review) "Keep the owner's existing decision to use trailing 30-day volume
    for the formal economic gate, unless new evidence demonstrates that it produces materially
    misleading decisions." "Do not deploy contracts to mainnet or spend real funds." "If the
    corrected economics no longer justify the vault, state that clearly."

## B. Proposed outcomes (2026-11-15; superseded by B2)

Numbers measured at block 26,424,971 unless stated. P = 0.03 ETH pack, B = 0.0363 ETH backing.

| # | Outcome | Proposed number | Measured by |
|---|---|---|---|
| O1 | Holder return at the gate | >= 10%/yr at 30-day volume, 1.2 gwei, tokens zero | model: +86% (30 d), +13.8% (7 d) |
| O2 | Edge per selection, bid outcome | +B (k - 1) = +1.40 mETH before gas; gas per cycle about 0.73M | fork: k 1.0385 live, 1.0378 to 1.0576 measured by bucket |
| O3 | Purchaser on a bid outcome | receives 0.9 B = 0.03267 ETH; vault gets the pack back | ForkSelection bid test (absolute) |
| O4 | Vault on a keep or silent outcome | +B (1 - s) = 0.035937 ETH back; pack goes to purchaser | ForkSelection keep and silent tests |
| O5 | Keeper pay | at most gas x min(price, 1.5 gwei), from 5% of harvested fees, at most 25% of value realized | ForkSelection harvest test |
| O6 | Cheapest way to stall holders | keep FWA's queue busy through a blackout: about 0.054 ETH per 12 h delayed; self-heals | reasoning (D15); 120 of 121 historical blackouts drained |
| O7 | User pays | mint fee 0.001 ETH per 0.1 ETH of Shapes (about 0.0003 per pack); no vault fee | lifecycle round trip (absolute) |
| O8 | End state | wind-down with zero acquisitions returns every holder's NAV share; only the 0.01 ETH seed's share remains | lifecycle wind-down test |
| O9 | Token income | counted as zero; one real buyback paid 20 listings 2.5e12 wei in total | ForkTokens |
## B2. Revised proposed outcomes (2026-11-16, supersede section B; awaiting sign-off)

Section B's O2 and O5 rested on a 5% keeper fee skim that exceeded the edge (D19). Numbers at
block 26,424,971 unless stated; P = 0.03 ETH pack, B = 0.0363 ETH backing, k = 1.0385.

| # | Outcome | Proposed number | Measured by |
|---|---|---|---|
| O1 | Holder return at the gate | >= 10%/yr at trailing-30-day volume of successful acquisitions, tokens zero, after every expense; met at 0.15 gwei (+123% simulated), not from a cold start at 1.2 or 1.5 gwei | sim/out/forward.md section 1 |
| O2 | Edge per bid cycle | B (k - 1) = 1.396 mETH before gas; cycle gas 0.8M: net 1.264 mETH at 0.15 gwei, 0.516 at 1.0, 0.076 at 1.5; break-even 1.59 gwei | fork gas (ForkReconcile), D20 |
| O3 | Purchaser on a bid outcome | receives 0.9 B = 0.03267 ETH; the vault keeps the pack | ForkSelection bid test (absolute) |
| O4 | Vault on a keep or silent outcome | B (1 - s) = 0.035937 ETH back; pack goes to purchaser | ForkSelection keep and silent tests |
| O5 | Keeper pay | (gas + 30k) x min(tx price, basefee + 0.05 gwei, 1.5 gwei) x 1.10, from vault ETH; at most 300k gas per position moved for sync, unlist and activate; harvest and token sales paid only if pay <= 25% of ETH realized; no-op checkpoints refused. Rehearsal: keeper +18% over gas spent | ForkVaultAdversarial, ForkSelection, canary rehearsal |
| O6 | New packs | built only when one bid cycle repays the build (1.05M gas + 0.0003 ETH): below ~0.54 gwei | D20, test_restockGated |
| O7 | User pays | mint fee 0.001 ETH per 0.1 ETH of Shapes; keeper gas; no vault fee | lifecycle round trip (absolute, every wei) |
| O8 | End state | wind-down returns every holder's NAV share; only the seed's dead-share slice remains | lifecycle wind-down test, keeper rehearsal |
| O9 | Size | at most 300 positions (about 20 ETH); worst-case checkpoint 10.17M gas; the 2 ETH canary holds 28 positions | checkpoint gas tests, canary rehearsal |
| O10 | Liabilities | escrow, redemption and distribution reserves and settled claimables are never deployable or payable to keepers | test_settledUnclaimedEthIsNotDeployable, invariants |
| O11 | Token rewards | claimed and sold only when the sale pays for itself, or by operator subsidy; never lost by waiting | ForkTokens, canary rehearsal |
