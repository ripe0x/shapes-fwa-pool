#!/bin/sh
# Writes the keeper's encrypted keystore and its password from Fly secrets into files only this
# container can read, then runs the keeper. The key itself is never in argv, env or a log.
set -eu
umask 077
: "${VAULT:?VAULT address}" "${KEEPER_KEYSTORE_JSON:?secret}" "${KEEPER_KEYSTORE_PASSWORD:?secret}"
# The Fly configs ship with a zero VAULT until script/release.py keeper-config writes the deployed one.
case "$VAULT" in
  0x[0-9a-fA-F]*[1-9a-fA-F]*) ;;
  *) echo "refusing to start: VAULT is unset or zero" >&2; exit 1 ;;
esac
printf '%s' "$KEEPER_KEYSTORE_JSON" > /tmp/keystore.json
printf '%s' "$KEEPER_KEYSTORE_PASSWORD" > /tmp/keystore.pw
unset KEEPER_KEYSTORE_JSON KEEPER_KEYSTORE_PASSWORD
# FACTORY (optional): also run every personal manager the PackManagerFactory has created.
FACTORY_ARGS=""
if [ -n "${FACTORY:-}" ]; then FACTORY_ARGS="--factory $FACTORY"; fi
# shellcheck disable=SC2086
exec python3 keeper/keeper.py "$VAULT" $FACTORY_ARGS --send --keystore /tmp/keystore.json --password-file /tmp/keystore.pw \
  --rpc "${RPC_URL:-https://mainnet.gateway.tenderly.co}" --state /data/keeper-state.json --index /data \
  --loop "${POLL_SECONDS:-60}" --confirmations 2 --health-port "${HEALTH_PORT:-8788}" ${KEEPER_ARGS:-}
