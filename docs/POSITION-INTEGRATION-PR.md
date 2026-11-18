# Remove the position ceiling with incremental production accounting

## Draft status

Local implementation branch only. Do not merge or deploy: the existing routine budgets do not
fund the measured global journal workload at the configured gas ceiling. Full acceptance results
and remaining gaps are recorded in `docs/POSITION-INTEGRATION-ACCEPTANCE.md`.

## Change

PackVault now keeps exact running Shapes backing, active FWA backing and fee debt membership in
one authoritative book. Checkpoints authenticate an ordered global acquisition cursor, pending
receipt count and one live fee witness instead of valuing the portfolio by scanning it. Maintenance
processes bounded journal entries, supplied changed positions and allocation cleanup. The total
position ceiling and spare-slot backing spread are removed.

Outstanding ordinary listings use unique 10,000 wei backing tags checked against live economics,
capital and the maximum keep-fee floor. The production receiver authenticates keep and kick
payments synchronously, retaining payment-time interpretation until ordered reconciliation.
Listing admission rejects staged, FWAIR and incidental foreign activation results atomically.
Each external listing call is gas-bounded, and listing batches are capped at eight.

The keeper uses a durable, reconstructible SQLite event index, pinned financial reads, bounded
candidates and a minimum-debt witness. Pending inclusion fee authentication avoids quoting a
basefee-sensitive backing target at the wrong block. Existing transaction restart, replacement,
lost-response and reorg behavior is preserved.

Paid primary mints, the mint/split/pack recipe and existing pack sizing remain. Holder pricing,
protected liabilities, redemption indexes, distributions, claims, dead shares and wind-down rules
remain. Token rewards are still claimed and burned with zero NAV value. Fixed work quotes and
request charges are updated; budgets, reserve values and holder charge policies are preserved.
Deployment, keeper, simulation, rehearsals, tests and current documentation migrate with the ABI.

## Validation

Final affected fork/audit/scenario checks pass 52/52, including all sixteen asset-flow regimes and
both Python reconciliation traces. The exact production receiver uses 46,462 gas for a cold keep
and 69,730 for the difficult kick; all 99 sampled low-gas limits record completely or fail
atomically. Eight production-model tests cover 40,960 randomized steps and 301/1,000/10,000
bookkeeping positions. A separate 301-real-FWA-listing fixture passes with a 300,454-gas complete
checkpoint. Model scale is not external listing scale.

All measured maximum operations fit EIP-7825 with the required 25% margin. The largest measured
complete operation is 10,357,047 gas (ten small packs, thirty total Shapes). PackVault is 24,549
bytes and VaultLib 20,484 under normal limits. Script deployment, linked-library CREATE2 provenance
and immutable/artifact matches are recorded. The approved quiet local lifecycle listed 29 packs,
ran twenty keeper transactions with zero reverts, fully exited and closed its ledger to the wei.
Real transaction-manager recovery, replacement uncertainty/cap and index reorg checks pass.

Ten Python accounting tests, seven focused forward scenarios and both exact fork reconciliations
pass. Independent bounded source/keeper review findings are repaired. Exact inputs, preserved
failures, command receipts and limits are in `docs/POSITION-INTEGRATION-ACCEPTANCE.md`.

## Blocking economics and limits

At 0.5 gwei total quote price, 18,281 actual completed global records over 30 days need at least
0.3227925 ETH of global-only keeper pay. Mainnet budget permits at most 0.25 ETH in that period,
before own position work. The 0.01 ETH/day hard refill maximum is also below the global-only
0.01075975 ETH/day lower bound. No budget was raised or protected balance spent to hide the gap.

PackVault runtime is 24,549 bytes, only 27 below EIP-170. Existing asset-flow numerical outcomes
and historical signature are preserved. The gate exits 2: O2 is 1,919,655 quoted gas versus the
1,750,000 bound; O6 is 0.00022 ETH versus 0.0002 ETH. Balanced buckets do not approve these changed
costs. The journal quote is conservative for full batches while some singleton calls can lose
money; keeper profitability is not guaranteed. Independent focused
review is not a security audit. No public-network transaction, owner signature, push or merge is
part of this change.
