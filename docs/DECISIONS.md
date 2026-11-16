# Decisions made without the owner (overnight run, 2026-11-15)

The owner asked for the plan to be run end to end overnight without questions. Each entry is a
call I would normally have asked about: what I chose, why, and what changes if you disagree.
Ordered by when it came up.

## D1. Scope of "end to end"

**Chose:** Phase 0 in full (0.1 to 0.5), then Phases 1 to 4 as code and tests on a mainnet fork.
**Not done:** the Phase 1 throwaway mainnet deployment with 1 to 2 ETH, and all of Phase 5
(audit, legal review, launch).
**Why:** both are mainnet broadcasts that spend real funds. Global rules require owner authority
for any broadcast, and "don't ask me" is not a signing key.
**If you disagree:** say "deploy the Phase 1 test vault" and give the funding cap.

## D2. SQLite instead of Parquet for the event store

**Chose:** `sim/data/fwa.sqlite` (stdlib `sqlite3`), args as JSON with wei as decimal strings.
**Why:** pyarrow and duckdb are not installed. SQLite needs no new dependency, holds ~2M rows
easily, and supports the same queries. The plan named Parquet as a format, not a requirement.
**If you disagree:** a one-off export to Parquet is a few lines once pyarrow is installed.

## D3. Stay on Tenderly when it rate-limits

**Chose:** keep `https://mainnet.gateway.tenderly.co` only. When it returned HTTP 429 for every
call (including `eth_blockNumber`), ingest waits it out (up to 5 min sleeps, 8 h cap) rather
than switching to another public RPC.
**Why:** your global rule says always use Tenderly's public RPC for mainnet. Switching
providers silently would break it.
**Cost:** slower ingest and fork tests overnight.
**If you disagree:** allow a second RPC (or an API key) for bulk historical reads.

## D4. Floor oracle ABI from Sourcify, not vendored with checksums

**Chose:** fetched the `CollectionFloorOracle` ABI (0xaA4D...27DC, Sourcify full match) into
`sim/abi/oracle.json` for log decoding only.
**Why:** the settlement mix by backing / floor ask needs oracle events. Only the ABI is used,
for analytics, so the refs/ provenance process (sources + sha256) is more than this needs.
**If you disagree:** vendor its full sources under `refs/` with `fwa_refs.py` before any
contract code imports its interface.

## D5. No in-kind FWA token fallback

**Chose:** the vault sells FWA tokens through the token's own Uniswap v4 pool, or holds them at
zero NAV value. It has no "switch to in-kind and let holders pull FWA" mode (plan 2.7).
**Why:** FWAToken transfers are locked. A transfer succeeds only when the sender or receiver is a
distributor, the token owner, or the v4 PoolManager under the hook's transient allowance (sells
are never gated). The vault is not a distributor, so it could never hand tokens to holders; an
in-kind mode would strand them while claiming not to. Confirmed by `test_measureTokenRoute`.
**Cost:** if the pool route dies, tokens stay stranded at zero value. NAV never counted them.
**If you disagree:** FWA would need to grant the vault the distributor role; then in-kind is a
small addition.

## D6. Checkpoint values every position in one bounded pass

**Chose:** `checkpoint()` syncs and values all open positions itself; `MAX_POSITIONS = 400` in
bytecode bounds the loop. Measured on the fork: 6.09M gas at 150 positions, 16.08M at 400
(about 0.0073 ETH per checkpoint at 150 and 1.2 gwei, so keepers checkpoint only when flows are pending).
**Why:** the plan's incremental cursor exists to bound cost per call. A hard bytecode cap does the
same with far less state and no partially-synced epochs to reason about.
**If you disagree:** needed only if you want more than about 400 positions (about 26 ETH).

## D7. Distributions only when no shares are waiting to exit

**Chose:** a checkpoint distributes only if every locked redemption was filled in full.
**Why:** shares locked mid-redemption would otherwise either miss the payout (redeemers lose) or
need a second share class. Skipping the epoch keeps one price for everyone. Gains carry to the
next checkpoint; nothing is lost.

## D8. One keeper pool, no separate essential reserve

**Chose:** keeper pay comes from one pool funded by `keeperFeeBps` of harvested FWA fees, excluded
from NAV. Pay = min(gas used + 30k, opGasCap) x min(gas price, gasCeiling), capped by
`keeperShareBps` of value the call realized where measurable (sync, unlist, harvest, convert),
and by the pool balance. Calls that do nothing revert, so they pay nothing.
**Why:** pausing never touches the pool, so a second reserve for "essential" calls bought nothing.
Every call still works unpaid when the pool is empty.

## D9. Silent purchaser: the vault takes the better outcome

**Chose:** after FWA's 1 h settlement window, `sync` calls `depositorReclaimBacking` when
B (1 - s) >= P (true at the cap: 0.0359 > 0.03), else `depositorReclaimNFT`.
**Why:** at the cap the vault nets B (k - s) - P = +0.0073 on reclaiming backing versus
B (k - 1) = +0.0014 on reclaiming the pack.

## D10. Selection tests replay real VRF transactions

**Chose:** no VRF double. `sim/find_selection.py` searches history for real requests whose real
random word would select one of N vault listings posted just before the request (exact
segment-tree and free-slot reconstruction). Fork tests post those listings, then replay the real
request and fulfillment transactions with `vm.transact`. Purchaser choices, FWA's owner and the
oracle owner act through their real entry points with `vm.prank`.
**Why:** your rule forbids faking randomness. Pranking a real actor's call on the real contract
drives the real path; it replaces no contract.
**Judgment call:** for history before packs were admitted (block 26,415,582), the test has FWA's
owner whitelist packs and the oracle owner set the 0.033 ask first: the same calls they made
for real later. That widens the candidate set from about one day to about ten weeks.

## D11. Unlisting rules

**Chose:** keepers may withdraw active listings only in wind-down, when the live edge gate fails,
or to cover locked redemptions that idle ETH and inventory cannot (stopping once covered). A
listing holding FWA's crown inside its 12 h window is skipped (exit would cost 1%).
**Why:** unlisting forfeits fee income, so it should happen only when something requires it.

## D12. Token sales need an admin-set first reference price

**Chose:** `convert` requires `minOut >= amount x refPrice x (1 - clipSlippageBps)`. `refPrice`
starts at zero (no sales) until the admin sets one through the delay; after that each fill
updates it. One sale per FWA 12 h interval, at most `clipMax` tokens.
**Why:** without a reference a keeper could sell into a sandwich. The trailing fill can drift
down at most `clipSlippageBps` per interval.

## D13. Distributions go to live shares only

**Chose:** the distribution accumulator divides by supply less the 1e15 dead seed shares.
**Why:** the reviewer flagged (L1) that the dead shares' slice would sit in
`distributionReserve` forever, which breaks "assets never stranded". The dead seed's NAV is
protocol-owned and unclaimable anyway, so moving its distribution slice to live holders costs
no one.

## D14. Gas ceiling default 1.5 gwei

**Chose:** recommended deployment `gasCeiling` = 1.5 gwei (bytecode max 50 gwei). Above it,
`restock` and `list` revert and keeper pay is priced at the ceiling.
**Why:** with measured gas (listNFT 651k), the bid outcome breaks even near 1.8 gwei; 1.5 gwei
leaves +0.25 mETH per cycle. Tests use 5 gwei only to exercise the rule.

## D15. Checkpoints can be delayed by anyone keeping FWA's queue busy (accepted)

**Chose:** keep the rule that checkpoints run only in FWA's blackout with FWA's global queue
drained. Reviewer M2: a stranger can keep `unsettledAcquisitionCount > 0` through a blackout,
delaying deposit pricing and redemption fills by 12 h per blackout.
**Why:** a drained queue during blackout is the only state in which no listing can be selected
mid-pricing; pricing outside it lets a holder trade against a known pending selection. The
attack costs the griefer about one acquisition fee (0.054 ETH at the pinned block) per blackout
held and self-heals. Historical data: 120 of 121 blackouts had a drained queue.
**Watch at canary:** how often real checkpoints miss their blackout.

## D16. Token-sale floor ratchets up only; max slippage 5%

**Chose:** after a sale, `refPrice` moves to the fill only if the fill is higher.
`MAX_CLIP_SLIPPAGE_BPS` is 500 (was 3,000). `convert` stays permissionless.
**Why:** reviewer M1: a keeper could sandwich a sale down to the floor and the old code then
lowered the next floor to that fill. Token income measured on the fork is about 2.5e12 wei per
buyback across 20 listings, so a stalled sale after a genuine price fall (until the admin lowers
the reference) costs almost nothing.

## Review findings not changed

- L4: `reserve`, `tvlCap`, `clipMax`, `refPrice` have no bytecode bounds. Only the delayed admin
  sets them; large `reserve` or `tvlCap` cannot move assets, and `refPrice` now only matters as
  a floor that ratchets up. Left as is.
- L5: `_redemptionShortfall` values idle packs at the 3-unit minimum, so it can allow unlisting
  slightly early when larger packs are held. Safe direction (unwinds to idle ETH); size margin
  is 90 bytes, so left as is.
- L3: `restock` now respects `listingPaused`. Spending is still bounded by `maxPositions`.

## D17. Phase 0.5 gate read as written, then built

**Chose:** GO, using your gate exactly as defined (30-day volume, tokens at zero, bid outcome
positive at the gas ceiling, one usable exit window a day), then built Phases 1 to 4.
**The numbers:** 30-day volume is 609/day, giving +86%/yr at 1.2 gwei; but that average leans on
one late-October week (1,527/day). The last two weeks ran 51 and 85/day; 7-day is 97/day
(+13.8%/yr at 1.2 gwei, +7.2% at 1.5 gwei); the last day was 15/day (+3.8%).
**Why build anyway:** you asked for the whole process, the gate as written passes, and the code
has value if volume returns or FWA raises the pack cap. Nothing is deployed.
**What I'd want you to decide:** whether the gate should use 7-day volume instead. On 7-day
volume it clears 10% only below about 1.35 gwei (13.8% at 1.2, 7.2% at 1.5).

## D18. Keeper and deploy path choices

**Chose:** a Python reference keeper (`keeper/keeper.py`) that shells out to `cast`, signs only
through a cast keystore account (or an unlocked local node in rehearsal), restocks 3 packs and
lists up to 5 per transaction, pads gas 25%, and checks receipts. One Foundry deploy script reads
every value from a JSON file; `deploy/canary.example.json` proposes a canary: 2 ETH TVL cap,
30 positions, 1.5 gwei ceiling, 2-day parameter delay, guardian and admin left as placeholders.
**Why:** smallest thing that runs the real lifecycle. A production keeper would add scheduling,
alerting and nonce handling.
**Needs you:** guardian and admin addresses, and whether the canary caps are right.
