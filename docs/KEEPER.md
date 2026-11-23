> **Current release instructions: [docs/release/RUNBOOK.md](release/RUNBOOK.md)** (2026-11-19). This document is history for the candidate it names; where it gives current instructions, the runbook replaces them.

# Keeper operations and recovery

Current operation is documented in [Complete operating pass](COMPLETE-OPERATING-PASS.md). The final journal schedule is 22,000 per record,120,000 for a required tail,80,000 for its qualified distribution proof and 85,000 for an ordinary sync. Own selections quote 180,000. Actual successful foreign and full holder checkpoint receipts include signed 80% minimum payments and ordinary profitability preflight.

Standalone `harvest` is unpaid. Eligible sync may sweep economical credit or claim only the active fee prefix needed to fund its completed work. The ordinary keeper tries the basic sync first, then bounded funding prefixes through exact contract preflight. Declining one prefix does not discard the operation. Full exits collect fees through unlisting and checkpoint; a cheaper manual partial redemption claim remains available.

`keeper/keeper.py` executes one operation, checks its receipt, then replans. `policy.py` owns the
economic decisions and is imported by the simulation. `tx.py` retains nonce, replacement, restart,
lost-response and receipt-reorg handling. The vault authenticates financial facts independently.

**One keeper, many accounts.** The keeper services every account from one signer: explicit
PackVault and/or PackManager address(es), plus every personal manager a `--factory`
(`PackManagerFactory`) has created. Discovery is bounded — each pass reads `managerCount()` and
fetches only indices not yet in `keeper/discovered-<factory>.json`; no pass rescans the whole set.
One signer means one nonce stream and at most one in-flight transaction across all accounts, so they
are serviced in turn and resume the same pending transaction first. Each account keeps its own event
index and plan, and is fully isolated: one account's revert, empty budget, paused listing or stuck
position never stops work on the others (`/health` reports per-account status). `read_state` branches
on account type (detected via `factory.isManager` or by probing a pool-only view): a personal
manager has no shares, deposits, redemptions, checkpoints or distributions, so those pool-only views
are never read and `checkpoint` is never planned for it; `windingDown` is the owner's reversible exit
mode (`setExiting`).

```sh
python3 keeper/keeper.py <vault> --rpc https://mainnet.gateway.tenderly.co
python3 keeper/keeper.py <vault> [<manager>...] --factory <factory> --send --account <keystore> \
  --rpc https://mainnet.gateway.tenderly.co --loop 300 --confirmations 2 --health-port 8788 --burn-tokens
python3 keeper/keeper.py <vault> --factory <factory> --status
```

Signing uses the existing cast keystore. No raw key belongs in an argument or file. The keeper
needs its own ETH for gas. Token burns remain unpaid and require operator opt-in.

**Selection-weight exposure (monitoring only).** `/health` reports the keeper's combined share of
FWA selection weight across every account it runs: the sum over its own Active listings of each
listing's FWA weight `1e36 / backing`, over `FWA.totalWeight()`. It surfaces as an `EXPOSURE_SHARE`
info line, and as an `EXPOSURE_SHARE_HIGH` action once the share reaches `EXPOSURE_SHARE_HIGH_BPS`
(10%, `policy.py`). Backings come from each account's event index (every open listing, no cap,
reorg-repaired), not from chain reads; an account whose pass fails still counts from its saved index, and one with no index yet raises `EXPOSURE_INCOMPLETE`. It never changes a plan — at a high share the operator widens backings or adds
independent listers.

| State | Default or behavior |
| --- | --- |
| Transaction state | `keeper/state-<factory-or-first-account>.json` (one per signer, shared across accounts); `--state` overrides it |
| Manager discovery | `keeper/discovered-<factory>.json`; bounded — only new `managerAt` indices are fetched per pass |
| Event index | `keeper/index-<chain>-<vault>-<deploymentBlock>.sqlite`; `--index` overrides it |
| Initial reconstruction | starts at the earlier of deployment and the trailing-seven-day volume boundary |
| Log ingestion | at most eight ranges of 2,000 blocks per pass; saved progress resumes on the next pass |
| Ordinary candidates | independent returned/receipt, unseen-selection, expired, inside-window booked-Allocated status checks and rotating OWED candidates, at most 16 per class; at most 80 hydrated positions including active witnesses |
| Discovery upgrade | replay missing allocation/bid history in at most eight adaptive ranges per pass, independently of the financial head |
| Reorg repair | verify both saved canonical prefixes, roll back affected ranges and replay retained events |
| Financial authority | onchain acquisition cursor, pending receipt count, listing authentication and exact book |

The index tracks active fee debt, outstanding backing identifiers, idle packs, allocations,
receipts and oversized gift recovery. Its minimum-debt active listing is the preferred fee witness.
Successful acquisition events supply trailing volume; refunded requests do not count as revenue.
A large initial reconstruction may take several passes. Deleting the index does not remove any
onchain state; it requires reconstruction before ordinary operation resumes.

The production entrypoint stores transaction state at `/data/keeper-state.json` and the event index
at `/data/keeper-index.sqlite`. Both Fly workers mount `/data`. Runtime dependencies, including the
Ethereum Keccak backend, are pinned in `keeper/requirements.txt` and installed by the Dockerfile.
`python3 keeper/test_packaging.py` builds that image and checks startup plus both stores across
separate containers sharing the volume. This check does not broadcast or replace a live Fly worker.

Related financial reads use one pinned block and a final canonical-hash check. New events are
indexed once; unchanged positions are not enumerated each pass. Optional token reads rotate through
a bounded candidate set. Complete portfolio getters are absent from the production ABI.

| Call | Required inputs and bounds |
| --- | --- |
| `build(units, backingProposals, minPay)` | allowed pack size (mask); each pack mints its Shapes straight into ShapePacks (6 units = one 0.05 + one 0.01 Shape, two paid mints) and is listed at once; at most 8 packs per call; capital must cover maintained waiting-inventory funding, every pack's mint cost and every backing |
| `list(backingProposals, minPay)` | relists only idle (returned) packs; at most 8 proposals, each an unused 10,000 wei multiple inside the live target interval and every economic gate |
| `sync(ids, witnessId, minPay)` | automatic job: at most 128 global records, 16 actual own selections, 16 supplied terminal or active funding IDs and 16 pruned heads; independent bounds |
| `checkpoint(witnessId, minPay)` | one authenticated live fee witness when active count is nonzero; complete journal, no receipts, clean nonexpired allocation head, blackout and drained requests |
| `unlist(ids, minPay)` / `harvest(ids, minPay)` | at most 16 IDs; harvest IDs strictly ascending; crown exit protection remains |
| `liquidate(maxCount, minPay)` | at most 16 items and 60 ordinary backing units per call; oversized gifts use an isolated claim of at most 30 Shapes |
| `burnTokens(ids)` | at most 16 candidates; unpaid; stale IDs cannot block credit withdrawal and burning |

Operation identifier 4 (old staged activation) is retired. New admission atomically requires an
ordinary Active listing, even after a drained-queue precheck. Operation7, standalone paid harvesting, is also retired. Other operation identifiers retain
meaning. An unconsumed old identifier is retired before its returned pack can be reused.

When authoritative onchain aggregates prove no outstanding FWA exposure, checkpoint and first
admission advance past irrelevant completed history without journal compensation (D67). The keeper
can propose that checkpoint directly and avoids a standalone unpaid sync. Any open position,
including OWED custody, or pending receipt keeps strict ordered processing. Idle inventory is
allowed by the proof. The public `accountedNav` view remains strict until a state-changing operation
advances the cursor.

Scan proof (D75). With at most 93 open positions the vault reads its own open listings instead of
FWA's global journal whenever that costs no more than the next journal batch, and the keeper never
syncs for FWA's global activity alone. It waits until an own selection settles (bid, keep) or its
settlement window expires, then one `sync([id])` applies the selection, resolves the outcome and is
paid `85,000 + 30,000 per Active position read + 180,000 per selection + 120,000 per resolution`.
Other terminal or cleanup work waits for that paid call unless holders are waiting, a checkpoint is
due or the vault is winding down; in a checkpoint window the keeper sends `sync([])` (paid as the
required tail) first and the terminals after it. A scan with no own selection outside a checkpoint
window earns nothing. Larger vaults keep the journal rules below.

Journal compensation is enforced onchain. A full 128-record batch, actual own selection or
terminal reconciliation qualifies. A shorter foreign-only tail qualifies only in a fresh checkpoint
window with a drained queue and pending holder flows, or an authenticated distribution that can
still exceed its minimum after the maximum sync payment. Distribution-only tails require the live
fee witness. A distribution setting alone is insufficient. The cursor stops before a seventeenth
own transition; supplying terminal IDs cannot shrink the journal job. No completion bonus exists.

An optional short foreign tail can advance unpaid with `minPay=0`; positive `minPay` rolls back
insufficient payment atomically. The normal keeper waits for useful batches or an actual checkpoint
candidate. All sync, including mixed jobs during redemption/wind-down, spends routine permission.
D64 still leaves unlisting and liquidation to callers when essential permission is zero.

Terminal-work discovery never depends on a `CashReceipt` event. A booked-Allocated position is
surfaced for a live FWA-status check every pass while it is still inside its settlement window (a
bounded rotating class, the complement of the expiry class), so an early keep or a kick whose
payment FWA force-sent by `SELFDESTRUCT` — the account's `receive` reverted, no `CashReceipt`,
`pendingReceipts()` stays zero — is synced promptly instead of waiting for expiry. Because the
keeper surfaces it, `sync` runs before any `checkpoint` (checkpoint plans only when nothing is
`due`), so the keeper never loops a checkpoint the vault reverts with `PendingReceipts` while a
booked-Allocated position is not Allocated at FWA. A booked-Active position FWA shows withdrawn
(kicked) sorts first in the active set by zero debt and is caught the same way.

Returned-pack discovery authenticates FWA's `NFTAllocated`, `DepositorBidAccepted` and
`DepositorBidAcceptedAsTokens` events and this vault's depositor identity. It retains selections
until the book catches up; an ETH or token bid independently prioritizes that return. Expiry
and rotating OWED discovery stay independent. Upgrades replay the newly subscribed history without
resetting transaction state or the ordinary financial head. Both projections retain identity,
canonical-hash and transactional stale-writer checks.

The keeper compares the known packed journal quote with actual free ETH and routine permission.
If either is insufficient it pauses new builds/listings, reports `JOURNAL_FUNDING` and continues
reconciliation and holder actions. This is a reversible planning pause, not automatic wind-down.
The quote covers known global entries; additional own work and future records may cost more.
The theoretical full-job reserve envelope is informational and supplies no ETH.

FWA's private staging FIFO has no public head getter, and can remain nonempty after requests drain.
The vault caps each `listNFT` call at 1.2 million gas and requires exactly one added active listing.
Incidental foreign activation, a staged result or insufficient external call gas reverts admission
atomically. The keeper's bounded pending preflight waits on such rejection. Another actor must
perform FWA's permissionless activation; there is no paid vault activation operation. This admission
condition does not prevent journal catchup, eligible checkpoints or exits.

Restock may repeat a valid unreserved funding quote. Listing then chooses fresh unique identifiers
from current outstanding reservations; it never assumes future tags are already reserved. Collisions,
stale fee witnesses and another keeper winning a race trigger bounded refresh/replanning. No keeper
can bypass the live economic floor, oracle ceiling, capital check or liquidity reserve.

An extended returned gift can be too large for the current oracle cap while new three-unit packs
remain viable. If the idle head has no valid listing proposal, the keeper can build valid packs
above it, retaining the vault's maintained `idleFunding()` commitment for older inventory. A viable
but currently unaffordable listing retains relist priority. No inventory scan or new liquidation
strategy is needed; the gift remains fully accounted for and redeemable through normal exits.

A backing target can depend on basefee. The keeper authenticates the deterministic pending header
against its pinned parent and checks executed `BASEFEE` with explicit fee fields. It uses that
context for proposals, payment simulation and gas estimation, then checks the parent before sending.
Later inclusion or concurrent changes can still reject atomically. See
`POSITION-INTEGRATION-ACCEPTANCE.md` for the verified context and remaining limits.

Payment remains a fixed verified-work quote, capped by the replaceable policy offer, vault envelope,
free cash and the applicable budget. Foreign/refunded entries earn no flat work fee. `processingPool`
funds the fixed shared checkpoint charge only. With `minPay=0`, maintenance remains permissionless
when unpaid; higher `minPay` reverts the whole operation if payment is insufficient.

| Condition | Recovery |
| --- | --- |
| `INDEX_CATCHUP` | run another bounded index pass; persistent progress is retained |
| `JOURNAL_CATCHUP` | process a qualified bounded journal job; optional short foreign tails wait |
| `MAINTENANCE_UNFUNDED` / `JOURNAL_FUNDING` | compare known backlog, free cash and routine permission; new exposure waits while reconciliation stays available |
| `RECEIPTS_PENDING` | sync the event-discovered IDs after their acquisition entries |
| `ALLOCATION_CLEANUP` | prune resolved queue heads through bounded sync |
| Overdue allocation / owed NFT | permissionless sync resolves expiry or retries FWA's real return claim |
| `InvalidBacking` / `BadWitness` | refresh index and live candidates; retry within the bounded race allowance |
| Gas above routine ceiling | routine work waits; holders may accept bounded losses for necessary exits |
| Essential budget zero | D64: withdrawer or owner executes unlisting/liquidation unpaid; sync remains routine; no unwind charge |
| Policy failure | work can run for zero pay; the policy cannot release protected holder balances |
| Stuck transaction | same-nonce replacement under configured fee, retry and cumulative-loss limits |
| Lost response / restart | durable nonce tracking reconciles the original transaction before resending |
| Reorg | transaction accounting and event projections both roll back and replay |

Owner `startWindDown()` remains one-way. Process journal/receipts, resolve allocations, unlist with
crown protection, liquidate in bounded calls, and checkpoint redemptions in blackout. Holders claim
their own balances. Oracle or admission failures cannot block the recovery paths.

Local rehearsal (unified system, D77) is one command on a fresh local mainnet fork, no public write:

```sh
python3 keeper/rehearse_unified.py --fork-block <recent> --port <free, not 8545>
```

It deploys the pooled vault and factory through `script/deploy.sh`, creates several personal
managers for different owners, runs this keeper signing through an encrypted keystore on a durable
`/data` volume exactly as `keeper/entrypoint.sh` does, and exercises discovery, build/list, the
pooled deposit/checkpoint/redeem/claim cycle, manager withdrawals and owner exit, restart and
container replacement on the same volume, the backup worker, and the lost-response/race/reorg and
event-index paths through `keeper/test_tx.py` and `keeper/test_index.py`. It writes
`docs/receipts/unified-production-rehearsal.json`. Real-FWA-VRF keep/bid/expiry needs the vault to
list at the exact backing `sim/find_selection.py` searched `test/fixtures/selection.json` against;
when a recipe or purchaser-gas change moves `edge(6)` the fixtures are stale and the rehearsal
records that gap with the regeneration command instead of fabricating a selection (those outcomes
are proven in the Forge `ForkSelection`/`ForkManager`/`VaultFlow` suites). It is launched through
`keeper/rehearsal_batch.py`, which owns the Anvil node, the fresh label-derived actors and the
manifest. Historical keeper profit tables do not validate the new quote schedule.
