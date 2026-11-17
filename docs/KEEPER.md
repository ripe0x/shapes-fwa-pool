# Keeper operations and recovery

`keeper/keeper.py` runs the vault. `keeper/policy.py` decides what is worth doing from chain state
(the year-long simulation runs the same file). `keeper/tx.py` gets each call mined exactly once.
Anyone may run a keeper; every vault call is permissionless and the vault pays the caller.

## Run

```sh
# print status and the plan, send nothing
python3 keeper/keeper.py <vault> --rpc https://mainnet.gateway.tenderly.co

# operate: signs through a cast keystore (cast prompts for its password or reads ETH_PASSWORD)
python3 keeper/keeper.py <vault> --send --account <keystore> --rpc https://mainnet.gateway.tenderly.co \
  --loop 300 --confirmations 2 --health-port 8788 --burn-tokens

# status, in-flight transaction and keeper P&L from the state file
python3 keeper/keeper.py <vault> --status
```

| Flag | Default | Meaning |
|---|---|---|
| `--state` | `keeper/state-<vault>.json` | in-flight transaction, counted receipts, P&L; gitignored |
| `--confirmations` | 1 | blocks before a receipt counts; use 2+ on mainnet |
| `--replace-after` / `--max-replacements` | 3 / 5 | same-nonce replacement at +25% fees |
| `--max-fee-gwei` | none | never bid a max fee above this |
| `--max-loss-wei` | 0 | expected loss accepted per call, judged at the signed fees. Not an absolute bound: a state change between the final check and inclusion can still revert a sent call and cost its gas |
| `--burn-tokens` | off | claim and burn FWA token rewards; unpaid, the operator pays |
| `--pending-timeout` | 120 s | how long a pass waits for a receipt before leaving it for the next pass |
| `--health-port` | off | `GET /health` on 127.0.0.1: 200 healthy, 503 stale or errors in the last pass |
| `--slowdown-volume` | 0 | stop building new packs while trailing 7-day acquisitions/day are below this |

Fund the keeper address with ETH for gas (a 10-pack restock uses about 9.2M gas: 0.005 ETH at
0.5 gwei). Use a plain account: an address with code that forwards ETH (an EIP-7702 sweeper, as
anvil's public dev keys carry on mainnet) passes the vault's pay on.

## Each pass

1. Re-check receipts counted in the last 64 blocks (reorgs) and settle the in-flight transaction.
2. Read the vault, FWA and rewards state; `policy.plan` returns the calls worth making, in order.
3. For the first call: preflight (`eth_estimateGas` from the keeper's address). A vault error that
   means the state moved on (Nothing, NotCheckpointWindow, AlreadyCheckpointed,
   Paused, WindingDown, AllocatedExposure) is a quiet skip; any other revert is an error.
4. Expected pay is read by simulating the exact call (`cast call` returns the pay the active
   policy and the vault's caps give), so a policy swap needs no keeper change. Execution cost is
   the estimate x the billed/estimate ratio calibrated from the keeper's own receipts, at the bid.
   Send when pay + `--max-loss-wei` covers that cost; `minPay` is 80% of the simulated pay, and a
   replacement re-quotes before re-bidding. Pay is simulated, and the final call (minPay included)
   re-estimated, with the fee fields the keeper signs, so a policy that prices on `tx.gasprice`
   is seen as it will act (audit E1). Activation goes in batches of 20; a distribution-only
   checkpoint is planned when simulating it succeeds. `--status` and `/health` show the active policy and
   any queued replacement.
5. Save the pending entry, broadcast at basefee + maxTip (max fee 2 x basefee + maxTip), wait for
   the receipt, count it, re-read the chain, repeat.

## Status codes

`--status`, every pass's log and `/health` report these. "wait" clears by itself; "action" needs
someone.

| Code | Kind | Meaning | What to do |
|---|---|---|---|
| OK | ok | operating normally | none |
| GAS_ABOVE_CEILING | wait | bid above the vault's gas ceiling; only liability work is planned | none; to process redemptions now, run with `--max-loss-wei`; if gas stays high, the admin raises the ceiling and the reserve with it (immediate, D58) |
| WAITING_SETTLEMENT | wait | a purchaser is inside FWA's settlement window | none |
| WAITING_CHECKPOINT_WINDOW | wait | deposits or redemptions wait for FWA's blackout with its queue drained | none; anyone may call FWA `processAcquisitions` to drain the queue |
| QUOTE_UNAVAILABLE | wait | FWA admission is off or its floor quote is invalid: nothing new lists | none; existing positions keep earning and can be unlisted |
| BID_CYCLE_UNPROFITABLE | wait | gas too high for a relist to repay itself | none |
| STAGED_PENDING_ACTIVATION | wait | listings FWA staged; activated once its queue drains | none |
| REDEMPTION_LIQUIDITY_SHORT | wait / action | ETH owed to redeemers beyond free ETH; "action" when nothing is planned to release it | if gas is above the ceiling, run with `--max-loss-wei`; if FWA's queue never drains, call FWA `processAcquisitions` |
| TOKENS_UNBURNED | info | FWA token rewards not yet burned | optional: `--burn-tokens`, or anyone calls `burnTokens(ids)` |
| EDGE_GATE_FAILED | action | FWA's live fees leave less than the minimum edge; the keeper unlists positions | owner considers `startWindDown()` |
| RECOVERY_REQUIRED | action | FWA holds a pack owed to the vault (failed delivery) | the keeper retries through `sync`; if it persists, see D23 |
| LISTING_PAUSED | action | the owner paused listing | owner decision |
| RESERVE_BELOW_NEED | action | the reserve is below one checkpoint plus one listing batch at the ceiling | admin raises `reserve` (immediate, D58) |
| WINDING_DOWN | info | wind-down in progress | keep the keeper running until no positions remain |

A malfunction shows as `/health` 503: no pass for 3 loop intervals, an RPC failure, a preflight
revert outside the list above, an on-chain revert, a replacement that failed, a reorged receipt,
or a transaction still pending after 5 replacements.

## Recovery

| Situation | What the keeper does | Operator action |
|---|---|---|
| Process killed or host restarted | state file holds the in-flight nonce; the next run waits for it or replaces it at the same nonce | restart it |
| RPC lost the broadcast response | the entry is saved before broadcasting; the keeper looks the nonce up, counts the transaction if it landed, resends at the same nonce if it did not | none |
| Transaction stuck | same-nonce +25% replacement every 3 blocks, up to 5 times and under `--max-fee-gwei` | if still stuck, raise `--max-fee-gwei` or wait |
| Another keeper did the work first | our preflight reverts with an expected error; a stuck transaction of ours is not bumped | none |
| Two keeper processes on one state file | the second exits (lock) | run one per state file; separate keepers need separate keys |
| Nonce used outside this process | counted if it was our call, otherwise tracking is dropped; nothing is resent | do not share the key |
| Reorg | receipts in the last 64 blocks are re-checked; a vanished one is uncounted and reported; the plan is re-read from chain | none |
| State file deleted | the keeper starts fresh; the vault's state is on chain | wait for any in-flight transaction to clear first |
| Keeper down for days | positions keep earning; deposits and redemptions wait; anyone may run a keeper or call any function | restart; or call `checkpoint()`, `unlist(ids)`, `liquidate(n)` by hand |
| Gas above the ceiling for long | only liability work, and only with `--max-loss-wei` | admin raises `gasCeiling` and `reserve` together if the market moved |

## Wind-down

Owner `startWindDown()` (one way). The keeper unlists every position (FWA's queue must be
drained), liquidates packs and Shapes back to ETH, and checkpoints redemptions in each blackout.
Holders `requestRedeem`, then `claim` after the next checkpoint. Anyone can run every step.

## Rehearse locally

```sh
anvil --fork-url https://mainnet.gateway.tenderly.co --fork-block-number 26418539 --port 8547 --base-fee 150000000
python3 keeper/rehearse_canary.py      # canary values, production deploy script and this keeper
python3 keeper/test_tx.py              # restart, replacement, lost response, reorg, lock (plain anvil)
```
