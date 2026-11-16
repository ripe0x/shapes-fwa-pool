#!/usr/bin/env bash
# Local rehearsal of the production deploy path and the reference keeper on an anvil fork of
# mainnet (no selections: those need replayed VRF transactions, see test/fork/ForkSelection).
# Start the fork first:
#   anvil --fork-url https://mainnet.gateway.tenderly.co --fork-block-number 26424971 --port 8547
# Uses anvil's own unlocked dev accounts only. Never point this at a public network.
set -euo pipefail
RPC=${RPC:-http://127.0.0.1:8547}
cd "$(dirname "$0")/.."
[ "$(cast chain-id --rpc-url "$RPC")" = "1" ] || { echo "expects a mainnet fork"; exit 1; }
case "$RPC" in http://127.0.0.1:*|http://localhost:*) ;; *) echo "local fork only"; exit 1;; esac

DEPLOYER=0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266 # anvil dev account 0
HOLDER=0x70997970C51812dc3A010C7d01b50e0d17dc79C8   # anvil dev account 1
KEEPER=0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC   # anvil dev account 2
GUARDIAN=0x0000000000000000000000000000000000000001 # placeholder in deploy/canary.example.json

warp_to() { # seconds offset inside FWA's 12 h interval: 42,360 = 11:46 (blackout), 60 = open
  local now next
  now=$(cast block latest --field timestamp --rpc-url "$RPC")
  next=$(( now - now % 43200 + $1 )); [ "$next" -gt "$now" ] || next=$(( next + 43200 ))
  cast rpc evm_setNextBlockTimestamp "$next" --rpc-url "$RPC" >/dev/null
  cast rpc evm_mine --rpc-url "$RPC" >/dev/null
}
keeper() { python3 keeper/keeper.py "$VAULT" --send --from "$KEEPER" --rpc "$RPC"; }
send() { local r; r=$(cast send "$@" --rpc-url "$RPC" --json); [ "$(echo "$r" | jq -r .status)" = "0x1" ] || { echo "reverted: $*"; exit 1; }; }

DEPLOY_VALUES=deploy/canary.example.json forge script script/Deploy.s.sol --rpc-url "$RPC" \
  --broadcast --unlocked --sender "$DEPLOYER" >/dev/null
VAULT=$(jq -r '.transactions[] | select(.contractName=="PackVault") | .contractAddress' \
  broadcast/Deploy.s.sol/1/run-latest.json)
echo "vault $VAULT"

echo "== deposit 1.5 ETH, price it at the blackout"
send "$VAULT" "deposit()" --value 1.5ether --from "$HOLDER" --unlocked
warp_to 42360; keeper
echo "== open interval: build and list"
warp_to 60; keeper; keeper
echo "open: $(cast call "$VAULT" 'openListings()(uint256[])' --rpc-url "$RPC")"

echo "== holder redeems everything: keeper frees liquidity, prices at the blackout"
SHARES=$(cast call "$VAULT" "shareBalance(address)(uint256)" "$HOLDER" --rpc-url "$RPC" | cut -d' ' -f1)
send "$VAULT" "requestRedeem(uint256)" "$SHARES" --from "$HOLDER" --unlocked
keeper
warp_to 42360; keeper
warp_to 60; keeper
warp_to 42360; keeper
send "$VAULT" "claim()" --from "$HOLDER" --unlocked
echo "locked after: $(cast call "$VAULT" 'lockedShares()(uint256)' --rpc-url "$RPC")"

echo "== second holder, redeploy capital, then wind-down"
send "$VAULT" "deposit()" --value 1ether --from "$HOLDER" --unlocked
warp_to 42360; keeper
warp_to 60; keeper
cast rpc anvil_impersonateAccount "$GUARDIAN" --rpc-url "$RPC" >/dev/null
cast rpc anvil_setBalance "$GUARDIAN" 0x16345785D8A0000 --rpc-url "$RPC" >/dev/null
send "$VAULT" "startWindDown()" --from "$GUARDIAN" --unlocked
keeper
SHARES=$(cast call "$VAULT" "shareBalance(address)(uint256)" "$HOLDER" --rpc-url "$RPC" | cut -d' ' -f1)
send "$VAULT" "requestRedeem(uint256)" "$SHARES" --from "$HOLDER" --unlocked
warp_to 42360; keeper
send "$VAULT" "claim()" --from "$HOLDER" --unlocked
echo "end: open $(cast call "$VAULT" 'openListings()(uint256[])' --rpc-url "$RPC"), idle packs" \
  "$(cast call "$VAULT" 'idlePacks()(uint256[])' --rpc-url "$RPC"), locked" \
  "$(cast call "$VAULT" 'lockedShares()(uint256)' --rpc-url "$RPC"), vault balance" \
  "$(cast balance "$VAULT" --rpc-url "$RPC"), lastNav $(cast call "$VAULT" 'lastNav()(uint256)' --rpc-url "$RPC")"
