# Candidate verification, unified system (final source)

Command: `script/verify.sh` (CANDIDATE_RUN=1), Foundry 1.8.1, Tenderly public gateway, run at
revision 40780743 (src and test identical through the final candidate; later commits change
receipts, docs and the manifest only). Every check passed except the last, which compares the
release manifest; it failed only because rehearsal receipts and `script/release.py` changed after
the manifest was written, and passes after the manifest is regenerated over the final evidence
(`python3 script/release.py check deploy/canary.json`, recorded in the acceptance package).

| Step | Result |
|---|---|
| build (`forge build --force --sizes`) | ok |
| sim/test_vault.py, sim/test_forward.py | ok |
| keeper/test_policy.py, keeper/test_index.py | ok |
| sim/replay.py (exact fee accumulator replay) | ok, 0 mismatches |
| forge-all (57 suites) | **276 passed, 0 failed, 1 skipped** |
| forge-scale (301 real listings, 10,000 model positions; 10B test gas) | **3 passed** |
| sim/reconcile.py | ok, every bucket to the wei on all three paths |
| release-check | stale manifest only, see above |

Reconciler:
- reconciled: every vault number matches the fork run to the wei
- partial/wind-down: claim 985994993145538344, keeper pay 2146000000000000, mint fees 12000000000000000, remaining redemption-rounding reserve 6 wei
- reconciled: partial fill, wind-down, full exit and every bucket match to the wei
- scan: backlog 46 entries cleared, keeper paid 455000000000000, fee credit still on FWA 234690224500959
- reconciled: scan path, one selection applied over a 47-entry backlog, every bucket to the wei

Skipped: 1, `CompleteForeignJournal.test_exportSuccessfulForeignReceiptFixture` (runs only with
EXPORT_COMPLETE_FOREIGN=1; it exports a fixture, it checks nothing).

New in this candidate: `ForkReceiptRecovery.t.sol` (forced keep, default and kick payments through
FWA's real SELFDESTRUCT fallback, low-gas sweep on the real receiver) and `ForkAllocationProof.t.sol`
(bounded proof: 32-entry boundary, a 2,000-entry history refused at a constant 31,763 gas, many
simultaneous unresolved allocations).
