# Independent review of accounting and keeper changes (release pass, 2026-11-19)

Reviewer: a separate agent given the code and the owner requirements, not the builder's conclusions.
Scope: `git diff e9cee61` over `src/`, `keeper/policy.py`, `keeper/keeper.py`, `keeper/tx.py`,
`keeper/index.py`, `keeper/entrypoint.sh`, `sim/vault.py` (commit 96f5ef0 plus this pass's keeper
startup guards). Read `_fundSync`, `_syncChanges`, `pay`, `quote`, `budgetNow`, `_free`, the sim
mirror `sync_fee_plan`/`distribution_tail`, and keeper `plan`/`run_pass`/`compensation` in full.
Ran `sim/test_vault.py`, `keeper/test_policy.py`, `forge build --sizes`.

Changes after the review: `keeper/policy.py` status text only (cash versus permission), the
configurable health port in `keeper/entrypoint.sh`, and test, rehearsal and release tooling. No
contract or accounting source changed, so the review applies to the release's `src/` and `sim/vault.py`.

## Result

No defect found. No extraction, protected-balance leak, padded-list gain or instant budget
refill could be constructed. Confirmed correct: standalone `harvest` is unpaid; `_fundSync` pays
only through `_free()`, which excludes all five protected pools, and bounds marginal pay to the
fee share of fees actually claimed; duplicate and zero-fee IDs earn nothing; the first
cash-covering prefix is final; `sim/vault.py sync_fee_plan` matches `_fundSync` (hand-traced);
`setParams` cannot refill a budget instantly; the zero-VAULT and no-code startup guards work.

## Items for the owner (no code change)

1. Values that only ratchet up, raised in 96f5ef0 and funded from holder NAV: `MAX_ROUTINE_RATE`
   0.01 to 0.02 ETH a day (D71, sized from the 90-day operating case); `Q_PACK_UNIT` 35,000 to
   100,000 quoted gas per unit beyond three (the four-shape leftover branch underpaid at 0.5 gwei;
   inactive while only three-unit packs are allowed by `packUnitsMask` 8); `Q_SELECTED` 160,000 to
   180,000 and `Q_REQUIRED_TAIL` 110,000 to 120,000 (measured receipts in
   `COMPLETE-OPERATING-PASS.md`). Listed in the acceptance package.
2. PackVault has 440 bytes of EIP-170 margin.
3. Maximal sync with funded collection had no receipt; the coverage pass measured the largest
   reachable sync (2,540,933 gas) and bounded the full combination at 10,576,250 padded gas.

Things that don't make sense: `keeper/policy.py` keeps `Q["harvest"] = 125000` for comparing an
unpaid harvest with an unlist although the contract no longer quotes harvest. Harmless.
