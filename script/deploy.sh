#!/usr/bin/env bash
# Usage: script/deploy.sh <values.json> [--broadcast]
# Runs script/Deploy.s.sol, which deploys the vault, its policy and the manager factory through DeployCore (the same code every fork and scenario
# test deploys with) and runs its postflight. Without --broadcast it only simulates against the
# chain at RPC_URL and prints the gas estimate and cost: nothing is sent.
# Release gate: script/release.py check compares sources, build, values, keeper and evidence with
# deploy/release-manifest.json. A simulation reports the result and continues. A broadcast to any
# node other than a local Anvil also needs the owner's signature on docs/release/acceptance.json,
# and is followed by the onchain postflight (runtime identities, owner, policy, parameters,
# budgets, seed shares, flags).
# Signing: FORGE_WALLET_ARGS, e.g. FORGE_WALLET_ARGS="--account deployer --sender 0x..." (a forge
# keystore account) or "--ledger --sender 0x...". Never a raw key. The simulation also needs
# --sender: the deploying address must hold the seed (seedWei) plus gas.
set -euo pipefail
VALUES="${1:?values file, e.g. deploy/canary.json}"
BROADCAST="${2:-}"
RPC_URL="${RPC_URL:-https://mainnet.gateway.tenderly.co}"
export RPC_URL
CHAIN_ID="$(cast chain-id --rpc-url "$RPC_URL")"
LOCAL=0
if [[ "$RPC_URL" =~ ^http://(127\.0\.0\.1|localhost)(:[0-9]+)?/?$ ]] \
  && cast rpc web3_clientVersion --rpc-url "$RPC_URL" | grep -qi anvil; then
  LOCAL=1
fi
# FORGE_WALLET_ARGS reaches forge script; only signer flags, so it cannot change compiler settings.
read -r -a WALLET <<< "${FORGE_WALLET_ARGS:-}"
for ((i = 0; i < ${#WALLET[@]}; i++)); do
  case "${WALLET[i]}" in
    --ledger|--trezor) ;;
    --account|--sender|--keystore|--password-file|--hd-paths) ((++i)) ;;
    *) echo "FORGE_WALLET_ARGS: ${WALLET[i]} is not a signer flag" >&2; exit 1 ;;
  esac
done
# Compile in this environment before the check, so the check covers the artifacts forge script
# below deploys (an inherited FOUNDRY_* override changes them, and the check then fails).
forge build
if [[ "$BROADCAST" == "--broadcast" && "$LOCAL" == 0 ]]; then
  python3 script/release.py check "$VALUES" --broadcast || {
    echo "Refusing to broadcast to chain $CHAIN_ID: the release check above must pass." >&2
    exit 1
  }
else
  python3 script/release.py check "$VALUES" || echo "release check failed (reported only: simulation or local Anvil)"
fi
echo "chain $CHAIN_ID, values $VALUES, $([[ "$BROADCAST" == "--broadcast" ]] && echo BROADCAST || echo 'simulation only')$([[ "$LOCAL" == 1 ]] && echo ' (local Anvil)')"
ARGS=(script/Deploy.s.sol:Deploy --rpc-url "$RPC_URL" --slow -vv)
if [[ "$BROADCAST" == "--broadcast" ]]; then ARGS+=(--broadcast); fi
DEPLOY_VALUES="$VALUES" forge script "${ARGS[@]}" ${WALLET[@]+"${WALLET[@]}"}
if [[ "$BROADCAST" == "--broadcast" && "$LOCAL" == 0 ]]; then
  RUN="broadcast/Deploy.s.sol/$CHAIN_ID/run-latest.json"
  pick() { python3 -c "import json,sys;r=json.load(open(sys.argv[1]));print(next(t['contractAddress'] for t in r['transactions'] if t.get('contractName')==sys.argv[2]))" "$RUN" "$1"; }
  VAULT="$(pick PackVault)"
  FACTORY="$(pick PackManagerFactory)"
  python3 script/release.py postflight "$VAULT" "$VALUES" "" "$FACTORY"
fi
