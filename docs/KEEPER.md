# Keeper operations and recovery

`keeper/keeper.py` executes one operation, checks its receipt, then replans. `policy.py` owns the
economic decisions and is imported by the simulation. `tx.py` retains nonce, replacement, restart,
lost-response and receipt-reorg handling. The vault authenticates financial facts independently.

```sh
python3 keeper/keeper.py <vault> --rpc https://mainnet.gateway.tenderly.co
python3 keeper/keeper.py <vault> --send --account <keystore> --rpc https://mainnet.gateway.tenderly.co \
  --loop 300 --confirmations 2 --health-port 8788 --burn-tokens
python3 keeper/keeper.py <vault> --status
```

Signing uses the existing cast keystore. No raw key belongs in an argument or file. The keeper
needs its own ETH for gas. Token burns remain unpaid and require operator opt-in.

| State | Default or behavior |
| --- | --- |
| Transaction state | `keeper/state-<vault>.json`; `--state` overrides it |
| Event index | `keeper/index-<chain>-<vault>-<deploymentBlock>.sqlite`; `--index` overrides it |
| Initial reconstruction | starts at the earlier of deployment and the trailing-seven-day volume boundary |
| Log ingestion | at most eight ranges of 2,000 blocks per pass; saved progress resumes on the next pass |
| Ordinary candidates | bounded active, terminal, inventory and optional token candidates, at most 16 per class |
| Reorg repair | verify saved canonical hashes, roll back affected ranges and replay retained events |
| Financial authority | onchain acquisition cursor, pending receipt count, listing authentication and exact book |

The index tracks active fee debt, outstanding backing identifiers, idle packs, allocations,
receipts and oversized gift recovery. Its minimum-debt active listing is the preferred fee witness.
Successful acquisition events supply trailing volume; refunded requests do not count as revenue.
A large initial reconstruction may take several passes. Deleting the index does not remove any
onchain state; it requires reconstruction before ordinary operation resumes.

Related financial reads use one pinned block and a final canonical-hash check. New events are
indexed once; unchanged positions are not enumerated each pass. Optional token reads rotate through
a bounded candidate set. Complete portfolio getters are absent from the production ABI.

| Call | Required inputs and bounds |
| --- | --- |
| `restock(units, backingProposals, minPay)` | allowed pack size; at most 30 total new units; actual proposed funding plus maintained waiting-inventory funding |
| `list(backingProposals, minPay)` | at most 8 proposals, each an unused 10,000 wei multiple inside the live target interval and every economic gate |
| `sync(maxJournal, ids, maxPrune, minPay)` | `maxJournal + ids.length <= 16`, `maxPrune <= 16`; verified completed global entries, own selections, terminal transitions and queue cleanup |
| `checkpoint(witnessId, minPay)` | one authenticated live fee witness when active count is nonzero; complete journal, no receipts, clean nonexpired allocation head, blackout and drained requests |
| `unlist(ids, minPay)` / `harvest(ids, minPay)` | at most 16 IDs; harvest IDs strictly ascending; crown exit protection remains |
| `liquidate(maxCount, minPay)` | at most 16 items and 30 ordinary backing units; oversized gifts use an isolated claim of at most 30 Shapes |
| `burnTokens(ids)` | at most 16 candidates; unpaid; stale IDs cannot block credit withdrawal and burning |

Operation identifier 4 (old staged activation) is retired. New admission atomically requires an
ordinary Active listing, even after a drained-queue precheck. Other operation identifiers retain
meaning. An unconsumed old identifier is retired before its returned pack can be reused.

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
| `JOURNAL_CATCHUP` | process completed global entries in bounded sync calls |
| `RECEIPTS_PENDING` | sync the event-discovered IDs after their acquisition entries |
| `ALLOCATION_CLEANUP` | prune resolved queue heads through bounded sync |
| Overdue allocation / owed NFT | permissionless sync resolves expiry or retries FWA's real return claim |
| `InvalidBacking` / `BadWitness` | refresh index and live candidates; retry within the bounded race allowance |
| Gas above routine ceiling | routine work waits; holders may accept bounded losses for necessary exits |
| Essential budget zero | D64: withdrawer or owner executes exit work unpaid; no unwind charge |
| Policy failure | work can run for zero pay; the policy cannot release protected holder balances |
| Stuck transaction | same-nonce replacement under configured fee, retry and cumulative-loss limits |
| Lost response / restart | durable nonce tracking reconciles the original transaction before resending |
| Reorg | transaction accounting and event projections both roll back and replay |

Owner `startWindDown()` remains one-way. Process journal/receipts, resolve allocations, unlist with
crown protection, liquidate in bounded calls, and checkpoint redemptions in blackout. Holders claim
their own balances. Oracle or admission failures cannot block the recovery paths.

Local rehearsal is prepared by `python3 keeper/rehearsal_batch.py --plan`. Its execution entry is
reserved for an explicitly approved isolated local batch. Current command receipts and remaining
launch gates are recorded in `docs/REPORT.md`; historical keeper profit tables do not validate the
new quote schedule.
