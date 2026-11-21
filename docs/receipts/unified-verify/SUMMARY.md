# Candidate verification, unified system (final source)

Command: `script/verify.sh` (CANDIDATE_RUN=1), Foundry 1.8.1, Tenderly public gateway, run at
revision b63d87a (src, test and keeper as released; later commits change receipts, docs and the
manifest only, except 21f86a6, the image rehearsal script, and 2027570, a keeper-only exposure change after which keeper/test_policy.py and
keeper/test_index.py were rerun and pass). Every check passed, including the release check against the manifest committed
in b63d87a.

| Step | Result |
|---|---|
| build (`forge build --force --sizes`) | ok |
| sim/test_vault.py, sim/test_forward.py | ok |
| keeper/test_policy.py, keeper/test_index.py | ok (index test now includes 600-position exposure) |
| sim/replay.py (exact fee accumulator replay) | ok, 827,583 EarningsAccrued checked, 0 mismatches |
| forge-all (57 suites) | **278 passed, 0 failed, 1 skipped** |
| forge-scale (301 real listings, 10,000 model positions; 10B test gas) | **3 passed** |
| sim/reconcile.py | ok, every bucket to the wei on all three paths |
| release-check | ok |

Reconciler:
- reconciled: every vault number matches the fork run to the wei
- partial/wind-down: claim 985994993145538344, keeper pay 2146000000000000, mint fees 12000000000000000, remaining redemption-rounding reserve 6 wei
- reconciled: partial fill, wind-down, full exit and every bucket match to the wei
- scan: backlog 46 entries cleared, keeper paid 455000000000000, fee credit still on FWA 234690224500959
- reconciled: scan path, one selection applied over a 47-entry backlog, every bucket to the wei

Skipped: 1, `CompleteForeignJournal.test_exportSuccessfulForeignReceiptFixture` (runs only with
EXPORT_COMPLETE_FOREIGN=1; it exports a fixture, it checks nothing).

New since the previous candidate (review of e755307):
- `test_forcedKickRefund_blocksPoolPricingUntilSynced`: a real kick on the pool, refund force-sent
  with no receipt; pricing refuses until synced, then equals the pre-kick NAV less the sync pay.
  With the exemption in place the same unsynced state priced NAV one backing too high.
- `test_activeCheckOnlyWhileKickableAndBounded`: with the exemption lifted, 33 and 1,000 open
  listings refuse with `CatchUpFirst` at no more than 39,766 gas; with it in place nothing is read.
- Bounded allocation proof: 188,361 gas at the 32-entry bound (quote 222,000); a 2,000-entry
  history refused at a constant 34,519 gas.
