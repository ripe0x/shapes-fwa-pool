# Launch audit step B at c884959 (uninformed, timeboxed)

Recorded by the coordinator from the auditor's final message: the auditor reported writing this
file, but it was not present in its worktree; only `AuditB.t.sol` (7 fork tests), `SOURCE_HASH`,
`logs/` and scratch folders were. Model: Fable 5.2. About 37 of 90 minutes used. Uninformed (prior
findings, reports and decision notes were removed from its worktree), not provably blind.
Not clean, not complete, not release-ready.

| # | Question | Auditor's answer |
|---|---|---|
| 1 | Take or strand assets? | Strand: FWA's owner (uncapped surcharge or a huge oracle ask) made `unlist` revert, wind-down included. Take: small (harvest padding). No principal theft path found. |
| 2 | Blocked work | `unlist` (above); essential budget empty after one 30-position exit at 0.95 gwei; checkpoint blocked for small vaults by one allocated position (reasoned); pauses permanent. |
| 3 | Every wei to the right party | Round trip 1.9 ETH, 10 positions, 0.15 gwei: holder -0.41%. All 10 draft outcomes within bounds in 16 regimes. |
| 4 | Pay vs billed gas | 0.15 gwei: all above cost at 0 tip; 0.5 gwei routine loses; 1.0-1.5 only exit work covered. |
| 5 | Backing rule | Floor right; spread unbounded when exempt. |
| 6 | Owner key | 24 h: at most 0.055 ETH (0.03555 executed); 365 d: 5.515 ETH of pay capacity. |
| 7 | Keeper | Restart, replacement, lost response, reorg handled; basefee rise and no cumulative stop-loss open. |

Findings: (1) High, `unlist` read FWA economics and overflowed; (2) Medium, harvest counted
repeated ids; (3) Medium, charge-funded checkpoint pay drew on the budgets; (4) Medium, unbounded
spread backing when exempt; (5) Medium, keeper unguarded against a basefee rise; (6) Medium, keeper
had no cumulative stop-loss; (7) Medium-low, listing into a busy queue paid twice; (8) Low, quotes
below billed gas for some operations; (9) Low, pauses permanent; (10) Low, allocated bound blocks
small vaults for an interval; (11) Low, placeholder owner and silent truncation in the deploy
script; (12) Low, listing needs a fresh quote (moot while exempt); (13) Info, cancel-refund rules.
