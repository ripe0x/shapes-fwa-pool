# Repairs after launch audit B (step C comparison)

Audit B's 7 fork tests reproduced on main, were kept in `test/audit/release-b/AuditB.t.sol`, and
those that showed a defect were rewritten to assert the repair on the same fork state.

| Finding | Repair | Evidence |
|---|---|---|
| 1 High: exits read FWA economics | `unlist` reads them only for non-essential (edge-broken) unwinding; wind-down and redemption exits never do. Keeper tolerates an unreadable `edge`. | `test_hugeOracleAskDoesNotBlockExit` (all unlisted, liquidated, holder exits fully under the hostile oracle), `test_hugeSurchargeDoesNotBlockUnlist` |
| 2 Medium: harvest repeated ids | ids must be strictly ascending; keeper sorts | `test_harvestRefusesRepeatedIds` |
| 3 Medium: charge-funded pay drew on budgets | checkpoint pay from the request-charge pool skips the budgets (precheck and debit) | `test_unpaidWorkWhenBudgetsAreEmpty` (paid from the pool with budgets at 0) |
| 4 Medium: unbounded spread | spare capital raises backing to at most twice what the other rules need | `test_spareCapitalSpreadAndCapped` (exactly 2 x floor) |
| 5 Medium: basefee rise | keeper prices cost at the next block's highest basefee (+12.5%) | `keeper/test_policy.py`, rehearsals |
| 6 Medium: no stop-loss | past `--max-total-loss-wei` (default 0.005 ETH) the keeper accepts no further loss; paid work continues | code; rehearsals stay inside it |
| 7 Medium-low: busy-queue listing | `list` refuses while FWA's queue is busy, so nothing the vault lists is staged | `test_noListingIntoBusyQueue`, `test_busyQueueRefusesListing`, regime `staged_activation` |
| 9 Low: permanent pauses | owner can resume deposits and listing (wind-down stays one-way) | code |
| 11 Low: deploy values | range-checked casts; owner must not be a placeholder or precompile | rehearsals deploy through it |
| 3 (liveness part): essential budget 0.01 ETH empties after one full exit at ~1 gwei | **owner decision**: canary essential cap and rate | `test_oneExitEmptiesEssentialBudget` kept |
| 8 Low: quotes below billed gas | not changed: bases stay under measured cost / 1.1 so splitting never pays | - |
| 10 Low: allocated bound blocks small vaults for an interval | not changed: clears when the allocation resolves (1 h window, then `SyncFirst`/sync) | unproven |
| 12, 13 | not changed (quote moot while exempt; cancel-refund behaviour as designed in D61) | - |

Also found while repairing: the invariant harness let the fuzzer use tracked holders as
transaction senders, whose balances then moved by gas; senders are now excluded (harness only).
