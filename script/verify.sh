#!/usr/bin/env bash
# One entry point for the frozen release candidate. Runs, in order, every check the release
# package cites; the first failure stops. Fork suites use Tenderly's public gateway, which
# throttles: expect a long run. Logs go to $LOG_DIR (default /tmp/packvault-verify).
#   script/verify.sh            all checks
#   script/verify.sh --quick    build, sizes and the offline Python checks only
set -euo pipefail
cd "$(dirname "$0")/.."
LOG_DIR="${LOG_DIR:-/tmp/packvault-verify}"
mkdir -p "$LOG_DIR"
FORK=(--rpc-url https://mainnet.gateway.tenderly.co --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100)
step() {
  local name="$1"; shift
  echo "== $name: $*"
  "$@" > "$LOG_DIR/$name.log" 2>&1 || { echo "FAILED $name (log $LOG_DIR/$name.log)"; tail -20 "$LOG_DIR/$name.log"; exit 1; }
  echo "   ok"
}
export CANDIDATE_RUN=1
step build forge build --force --sizes
step model-vault python3 sim/test_vault.py
step model-forward python3 sim/test_forward.py
step keeper-policy python3 keeper/test_policy.py
step keeper-config python3 keeper/test_config.py
step release-inputs python3 script/test_release.py
step model-completion python3 sim/test_completion.py
step keeper-index python3 keeper/test_index.py
if [[ "${1:-}" == "--quick" ]]; then exit 0; fi
if [[ -f sim/data/fwa.sqlite ]]; then step archive-replay python3 sim/replay.py; fi
# Every suite: contract, audit and research tests, the 16 asset-flow regimes and both reconciliations.
SCALE='test_checkpointGasWith301RealListings|test_scale301_1000_10000MatchesReferenceAndHasConstantValuationGas'
step forge-all forge test "${FORK[@]}" --no-match-test "$SCALE" -vv
# 301 real listings and 10,000 model positions need more than the default test gas for fixture
# setup; the measured production calls inside still assert the 16,777,216 transaction cap.
step forge-scale forge test "${FORK[@]}" --match-test "$SCALE" --gas-limit 10000000000 -vv
step reconcile python3 sim/reconcile.py
step release-check python3 script/release.py check deploy/mainnet.json
echo "all checks passed; logs in $LOG_DIR"
