# Candidate verification, unified system

Command: `script/verify.sh` (CANDIDATE_RUN=1), Foundry 1.8.1, Tenderly public gateway, run at
revision 3b4d9b3 (mainnet values, no deposit cap; purchaser redeem gas by Shape count; kick check
skipped above 32 open listings). Every check passed, including the release check against the
manifest committed in 3b4d9b3. Later commits change only receipts, docs, the O9 outcome number and
the manifest.

| Step | Result |
|---|---|
| build (`forge build --force --sizes`) | ok |
| sim/test_vault.py, sim/test_forward.py | ok |
| keeper/test_policy.py, keeper/test_index.py | ok |
| sim/replay.py (exact fee accumulator replay) | ok, 827,583 EarningsAccrued checked, 0 mismatches |
| forge-all (57 suites) | **279 passed, 0 failed, 1 skipped** |
| forge-scale (301 real listings, 10,000 model positions; 10B test gas) | **3 passed** |
| sim/reconcile.py | ok, every bucket to the wei on all three paths |
| release-check (`deploy/mainnet.json`) | ok |

Reconciler:
- reconciled: every vault number matches the fork run to the wei
- partial/wind-down: claim 985994993145538344, keeper pay 2146000000000000, mint fees 12000000000000000, remaining redemption-rounding reserve 6 wei
- reconciled: partial fill, wind-down, full exit and every bucket match to the wei
- scan: backlog 46 entries cleared, keeper paid 455000000000000, fee credit still on FWA 234690224500959
- reconciled: scan path, one selection applied over a 47-entry backlog, every bucket to the wei

Skipped: 1, `CompleteForeignJournal.test_exportSuccessfulForeignReceiptFixture` (runs only with
EXPORT_COMPLETE_FOREIGN=1; it exports a fixture, it checks nothing).

New since the previous candidate (b63d87a):
- `test_purchaserRedeemGasWithinQuote`: cold redeems of 2, 5 and 7 Shapes at 157,014, 245,262 and
  304,165 gas, within the 160,000 / 250,000 / 310,000 quote.
- `test_activeCheckOnlyWhileKickableAndBounded`: with the exemption lifted, 32 open listings are
  checked; 33 and 1,000 price at a constant 32,712 gas instead of refusing.
- Bounded allocation proof: 190,494 gas at the 32-entry bound (quote 222,000).
