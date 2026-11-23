# Launch audit, step C: comparison of A (informed) and B (uninformed)

Both audits examined b0e9c12, timebox 90 minutes each (A about 65, B about 59). B used a stripped
export without history; it is uninformed, not blind (B records two procedural deviations: it read
Git metadata of the original checkout and `asset-flow.json` before finishing its own map).
Neither is a clean, complete or release-readiness result. Step C checked each one-sided finding
against the code at d47c121; every one-sided finding had already been executed by its finder, so
no new execution was needed. Items both left reasoned are named gaps.

| Finding | A | B | Status at d47c121 |
|---|---|---|---|
| Release check did not bind deployed artifacts | R1, executed | not reachable (manifest removed) | **Repaired** a8b722e, re-attacked (`launch-audit-A-repairs.md`) |
| Owner-key pay above the B3 bound | E2, executed 0.005 ETH, 0.0546 ETH available on day 1 | S0, executed: 0.3726 ETH to the owner over 30 days; holder loses 0.4075 ETH of 1.96 (20.8%); `requestRedeem` demands 0.361 ETH upfront | **Owner decision.** B3 (0.045 ETH, then 0.015/day) is wrong for this bytecode: maxima are routine 0.3 cap / 0.02 a day, essential 0.1 / 0.005, ceiling 50 gwei |
| Zero-demand loss at maximum load exceeds O9 | not found (ran max_load and wind_down separately) | E1, executed: 178 bps at 0.2 gwei, 212 bps at 0.5 gwei vs O9's 150 | **Owner decision.** Structural: 15 packs' mint fees alone are 0.03 ETH = 153 bps of 1.96 ETH |
| Purchaser redeem gas fixed at 160,000 for every pack size | E1, executed: 7 Shapes 304,115 gas, keep advantage 0.0000118 ETH vs 0.0003 required | not found (tested 3 and 30 units for build only) | **Owner decision**; no effect at canary values (6-unit only) |
| Request charge stranded after all requests cancel and wind-down | not found | E2, executed: 0.000092 ETH canary, 0.01805 ETH at maxima | Confirmed by reading `PackVault.cancelDeposit` (last canceller refunds only its own charge). Repair needs a payer rule |
| Unsolicited ShapePack accepted, untracked, unrecoverable | not found | E3, executed: 0.06 ETH pack stuck | Confirmed: `onERC721Received` accepts any ShapePacks transfer. Rejecting foreign safe transfers is a small repair; a recovery right for unsafe transfers is an owner decision |
| Factory usable once deployed; keeper discovery unbounded | S1, precondition executed (32 managers), overload reasoned | L1, executed creation and cross-manager denial; overload reasoned | Both reasoned on keeper overload: **gap**, repair before `FACTORY` is set |
| Kick refund unrecorded across an exemption restore | K1 re-executed (32-entry bound); residual taken from the prior review | S1 reasoned; 45 gas limits on real `kickListing` never produced an unrecorded refund | Both reasoned: **gap**, accepted residual (D84), now with no real-path witness |
| Shipped tests etch or fund the vault itself | found | found | Both: forced-receipt evidence (A4.1) is synthetic. **Gap** |
| Seed outside the 2 ETH cap | not raised | L2: NAV 2.01 ETH at a full cap | Matches runbook ("2 ETH of holder deposits"; seed separate). Owner to confirm the reading |
| Stale ShapePacks floor quote; exemption differs by block | noted live quote 708,996 s old | exemption false at block 26,424,971, true at 26,474,789 | Monitoring row exists; listing depends on FWA's exemption |

Neither audit executed: a real failed FWA callback; the annual multi-seed formal gate; intermediate
pack sizes with fee and parameter extremes; the signed multi-account production keeper rehearsal
(step D); full external source-to-bytecode equivalence (A: 10 of 11 runtimes; B: 9 of 9 via
Sourcify).
