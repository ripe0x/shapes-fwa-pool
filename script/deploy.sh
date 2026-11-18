#!/usr/bin/env bash
# Usage: script/deploy.sh <values.json> [--broadcast]
# Runs script/Deploy.s.sol, which deploys through DeployCore (the same code every fork and scenario
# test deploys with) and runs its postflight. Without --broadcast it only simulates against the
# chain at RPC_URL and prints the gas estimate and cost: nothing is sent.
# Signing: FORGE_WALLET_ARGS, e.g. FORGE_WALLET_ARGS="--account deployer --sender 0x..." (a forge
# keystore account) or "--ledger --sender 0x...". Never a raw key. The simulation also needs
# --sender: the deploying address must hold the seed (seedWei) plus gas.
set -euo pipefail
VALUES="${1:?values file, e.g. deploy/canary.json}"
BROADCAST="${2:-}"
RPC_URL="${RPC_URL:-https://mainnet.gateway.tenderly.co}"
CHAIN_ID="$(cast chain-id --rpc-url "$RPC_URL")"
if [[ "$CHAIN_ID" == "1" && "$BROADCAST" == "--broadcast" && "${I_AM_THE_OWNER:-}" != "yes" ]]; then
  echo "Refusing to broadcast to mainnet without I_AM_THE_OWNER=yes." >&2
  exit 1
fi
echo "chain $CHAIN_ID, values $VALUES, $([[ "$BROADCAST" == "--broadcast" ]] && echo BROADCAST || echo 'simulation only')"
ARGS=(script/Deploy.s.sol:Deploy --rpc-url "$RPC_URL" --slow -vv)
if [[ "$BROADCAST" == "--broadcast" ]]; then ARGS+=(--broadcast); fi
# shellcheck disable=SC2086
DEPLOY_VALUES="$VALUES" forge script "${ARGS[@]}" ${FORGE_WALLET_ARGS:-}
