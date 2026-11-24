#!/bin/sh
# Signer files are supplied read-only by the operator; never materialize secrets from env.
set -eu
umask 077
valid_address() {
  [ "${#1}" -eq 42 ] && [ "${1#0x}" != "$1" ] || return 1
  case "${1#0x}" in *[!0-9a-fA-F]*|0000000000000000000000000000000000000000) return 1 ;; esac
}
set --
if [ -n "${VAULT:-}" ]; then
  valid_address "$VAULT" || { echo 'VAULT must be a nonzero address' >&2; exit 1; }
  set -- "$@" "$VAULT"
fi
if [ -n "${FACTORY:-}" ]; then
  valid_address "$FACTORY" || { echo 'FACTORY must be a nonzero address' >&2; exit 1; }
  set -- "$@" --factory "$FACTORY"
fi
[ "$#" -gt 0 ] || { echo 'Set FACTORY and/or VAULT' >&2; exit 1; }
if [ -n "${KEEPER_KEYSTORE_JSON:-}${KEEPER_KEYSTORE_PASSWORD:-}" ]; then
  echo 'Supply existing read-only KEEPER_KEYSTORE_PATH and KEEPER_PASSWORD_FILE mounts; secret env materialization is disabled' >&2
  exit 1
fi
if [ -n "${KEEPER_FROM:-}" ]; then
  [ -z "${KEEPER_KEYSTORE_PATH:-}${KEEPER_PASSWORD_FILE:-}" ] || { echo 'Choose one signer transport' >&2; exit 1; }
  valid_address "$KEEPER_FROM" || { echo 'KEEPER_FROM must be a nonzero address' >&2; exit 1; }
  # keeper.py checks loopback Anvil chain31337 before using an unlocked actor.
  set -- "$@" --from "$KEEPER_FROM"
else
  : "${KEEPER_KEYSTORE_PATH:?existing encrypted keystore path}" "${KEEPER_PASSWORD_FILE:?existing password file path}"
  [ -r "$KEEPER_KEYSTORE_PATH" ] && [ -r "$KEEPER_PASSWORD_FILE" ] || { echo 'Signer mounts must be readable' >&2; exit 1; }
  set -- "$@" --keystore "$KEEPER_KEYSTORE_PATH" --password-file "$KEEPER_PASSWORD_FILE"
fi
# KEEPER_ARGS contains operator flags, never signing material.
# shellcheck disable=SC2086
exec python3 keeper/keeper.py "$@" --send \
  --rpc "${RPC_URL:-https://mainnet.gateway.tenderly.co}" --state /data/keeper-state.json --index /data \
  --loop "${POLL_SECONDS:-60}" --confirmations 2 --health-port "${HEALTH_PORT:-8788}" ${KEEPER_ARGS:-}
