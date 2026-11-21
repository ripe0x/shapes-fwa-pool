# Candidate verification, unified system

Command: `script/verify.sh` (CANDIDATE_RUN=1), Foundry 1.8.1, Tenderly public gateway, run at source revision 749503c (src, script, deploy and keeper identical through 566c65c; later commits change docs and the comparative study only). Exit 0.

    == build: forge build --force --sizes
       ok
    == model-vault: python3 sim/test_vault.py
       ok
    == model-forward: python3 sim/test_forward.py
       ok
    == keeper-policy: python3 keeper/test_policy.py
       ok
    == keeper-index: python3 keeper/test_index.py
       ok
    == archive-replay: python3 sim/replay.py
       ok
    == forge-all: forge test --rpc-url https://mainnet.gateway.tenderly.co --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100 --no-match-test test_checkpointGasWith301RealListings|test_scale301_1000_10000MatchesReferenceAndHasConstantValuationGas -vv
       ok
    == forge-scale: forge test --rpc-url https://mainnet.gateway.tenderly.co --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100 --match-test test_checkpointGasWith301RealListings|test_scale301_1000_10000MatchesReferenceAndHasConstantValuationGas --gas-limit 10000000000 -vv
       ok
    == reconcile: python3 sim/reconcile.py
       ok
    == release-check: python3 script/release.py check deploy/canary.json
       ok
    all checks passed; logs in $LOG_DIR (local scratch)

Fork suites:
- forge-scale.log:Ran 3 test suites in 45.89s (76.79s CPU time): 3 tests passed, 0 failed, 0 skipped (3 total tests)
- forge-all.log:Ran 54 test suites in 29.78s (364.09s CPU time): 268 tests passed, 0 failed, 1 skipped (269 total tests)

Reconciler:
- reconciled: every vault number matches the fork run to the wei
- partial/wind-down: claim 985994993145538344, keeper pay 2146000000000000, mint fees 12000000000000000, remaining redemption-rounding reserve 6 wei
- reconciled: partial fill, wind-down, full exit and every bucket match to the wei
- scan: backlog 50 entries cleared, keeper paid 455000000000000, fee credit still on FWA 25114899283272
- reconciled: scan path, one selection applied over a 47-entry backlog, every bucket to the wei

Skipped: 1, `CompleteForeignJournal.test_exportSuccessfulForeignReceiptFixture` (runs only with EXPORT_COMPLETE_FOREIGN=1; it exports a fixture, it checks nothing).
