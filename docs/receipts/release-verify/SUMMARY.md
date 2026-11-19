# Release candidate verification, 2026-11-19

Command: `script/verify.sh` (Foundry 1.8.1, solc 0.8.30, `CANDIDATE_RUN=1`, Tenderly public gateway).
Source: the release commit named in `docs/release/acceptance.json`; contract sources unchanged since f4ed47a.

| Step | Result |
|---|---|
| `forge build --force --sizes` | pass; PackVault 24,136, VaultLib 24,304, KeeperPolicyV1 216 runtime bytes |
| `sim/test_vault.py`, `sim/test_forward.py`, `keeper/test_policy.py`, `keeper/test_index.py` | pass |
| `sim/replay.py` (archive to block 26,450,200) | 853,661 of 853,661 accruals exact; sequences contiguous |
| `forge test` (all 47 suites, fork) | 237 passed, 4 failed, 2 skipped (243) |
| Repairs, rerun | `test_buildAboveCeilingPaidAtCeilingPrice`: test premise outdated (see below), ceiling 0.3 → 0.25 gwei, pass. `test_checkpointGasWith301RealListings` and `test_scale301_1000_10000MatchesReferenceAndHasConstantValuationGas` (listed twice): fixture setup needs `--gas-limit 10000000000` as documented before; pass. `verify.sh` now runs them as their own step |
| `sim/reconcile.py` after both fork reconciliations | every bucket matches to the wei (6 wei redemption rounding in the partial cycle) |
| Asset-flow gate, 16 regimes | zero bucket mismatches; O3-O10 within bounds; **O2 1,919,655 fails 1,750,000**; unsigned |

The outdated test: under the 0.0363 ETH oracle cap at its historical block, the quote increases of
96f5ef0 lower the gas price at which one bid cycle repays a new pack's build to about 0.33 gwei
(0.30 gwei with the fixture's 10% markup), from about 0.52 gwei before. The contract correctly
refused to build at 0.3 gwei. With the current oracle exemption, backing is not capped and this
limit does not bind; if FWA restores the cap, new packs are built only below about 0.33 gwei.

Skipped: 2 tests opt-in by environment (receipt exports). Raw lines: `forge-all-results.txt`.
