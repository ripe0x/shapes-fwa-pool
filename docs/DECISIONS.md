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
**Owner decision (2026-11-16):** keep 30-day volume for the gate. Gate stands at GO.

## D18. Keeper and deploy path choices

**Chose:** a Python reference keeper (`keeper/keeper.py`) that shells out to `cast`, signs only
through a cast keystore account (or an unlocked local node in rehearsal), restocks 3 packs and
lists up to 5 per transaction, pads gas 25%, and checks receipts. One Foundry deploy script reads
every value from a JSON file; `deploy/canary.example.json` proposes a canary: 2 ETH TVL cap,
30 positions, 1.5 gwei ceiling, 2-day parameter delay, guardian and admin left as placeholders.
**Why:** smallest thing that runs the real lifecycle. A production keeper would add scheduling,
alerting and nonce handling.
**Needs you:** guardian and admin addresses, and whether the canary caps are right.

# Repair review (2026-11-16)

Owner request: independent engineering and economic review of the overnight build, repair what
does not hold up, keep the 30-day gate unless evidence shows it misleads. Each entry says what
changed, the alternatives, and the tradeoff. Supersedes D6, D8 and D11 where noted.

## D19. Keeper pay is reimbursed gas, not a share of fees (supersedes D8)

**Found:** `keeperFeeBps = 500` routed 5% of every harvested fee to a keeper pool excluded from
NAV. Per bid cycle that is 0.05 x kB = 1.885 mETH against an edge of B (k - 1) = 1.396 mETH, so
holders lost 0.49 mETH per cycle at any volume and any gas price. Unspent pool ETH never returned
to NAV, even in wind-down. The old model subtracted estimated gas but not the skim; it overstated
holder returns by the whole difference.
**Chose:** no pool. Every paid call reimburses `(gasUsed + 30k) x min(tx price, basefee + maxTip,
ceiling) x (1 + keeperPremiumBps)` from free ETH, capped at `opGasCap`. Necessary work (sync,
list, restock, unlist, liquidate, a checkpoint with holder flows) is paid. Optional work (harvest,
token sale) is paid only if the pay is at most `keeperShareBps` of the ETH it realized, otherwise
nothing. A checkpoint with no flows is unpaid.
**Alternatives:** a smaller fee share (still a fixed skim: overpays at low gas, underpays at high
gas, strands the surplus); a pool swept back into NAV (more state, same mispricing).
**Tradeoff:** holders pay real gas plus a 10% premium (the keeper's margin). `maxTip` (0.05 gwei)
caps what a builder can pay itself through its own priority fee.

## D20. Listing and restock must clear their own gas

**Chose:** `list` requires `B (k - 1) > CYCLE_GAS x price x (1 + premium)` (800k gas: relist plus
shares of sync and harvest, measured 0.75M on the fork). `restock` requires the same, plus the
build (1.05M gas per pack and its mint fee share) repaid by one bid cycle, plus idle ETH for the
Shapes and the backing of every waiting pack. Before, restock spent ETH on packs whatever the gate
said and whether or not they could be listed.
**Tradeoff:** gas constants live in bytecode. If FWA's listing cost rises a lot they understate;
the hard `gasCeiling` remains as the backstop.

## D21. ETH owed to redeemers is not deployable

**Found:** a keeper could unlist positions to cover a redemption shortfall, then list the freed
ETH again, be paid both ways, and repeat while redeemers waited.
**Chose:** `_idle()` subtracts the owed estimate (`lockedShares x lastNav / totalShares`, rounded
up). Regression: `test_unlistListLoopClosed`.

## D22. Unlisting only for wind-down, redemptions, or a broken fee structure (supersedes D11)

**Found:** unlisting was allowed whenever the full listing gate failed, which includes a stale
oracle quote and (after D20) a gas spike. Anyone could then unwind every earning position and be
paid for it, and the vault would pay again to relist.
**Chose:** unlisting is allowed in wind-down, to cover a redemption shortfall, or when live k is
below 1 + minEdge. The keeper unwinds in that last case because every further cycle loses.

## D23. A pack FWA failed to deliver stays tracked until it arrives

**Found:** `_sync` treated a failed `recoverStuckNFT` as "pack gone" and forgot the position.
**Chose:** `_sync` reads FWA's own `stuckNFTRecipient`. If FWA owes the pack to the vault, the
position stays open, is valued at the pack's value at checkpoints, and any later `sync` retries
the pull (permissionless; unpaid until it succeeds). Ownership plus FWA's record decide the
outcome, never inference.
**Not tested for real:** with the deployed ShapePacks (no pause, no transfer hook) and FWA's
100k delivery stipend plus its 300k notifier admission check, a delivery failure cannot be
produced without replacing ShapePacks or FWA state, which the no-mock rule forbids. The path is
covered by review only. Normal bid, keep and silent-purchaser outcomes run on real VRF replays.

## D24. Bounded checkpoint: read-only per position, 300 positions (supersedes D6)

**Found:** checkpoint gas was 16.08M at 400 positions, 4% under EIP-7825's 16,777,216 per-tx cap,
and the loop also resolved positions and redeemed inventory, so its worst case was unbounded
(hundreds of allocations after a busy day, or redeeming hundreds of packs at ~190k each).
**Chose:** checkpoint values positions from FWA state only (no sync, no liquidation inside),
`MAX_POSITIONS = 300` bounds open plus idle packs, and inventory becomes ETH through a separate
`liquidate(maxCount)` (at most 40 per call, about 6.5M gas) that runs only while redeemers need
ETH or in wind-down. Measured worst case at 300 positions: 9.83M gas, 41% under the cap.
**Rejected:** incremental (cursor) reconciliation. It adds partially priced epochs and their
edge cases; the measurement shows the simple bound suffices up to 300 positions (about 20 ETH).
**Tradeoff:** capacity is capped at 300 positions. Section 3 of `sim/out/forward.md` shows
returns fall with size anyway.

## D25. Harvest claims active listings' fees too

**Chose:** `harvest(ids)` calls FWA's `claimListingFees` for active listings (fees stay earning)
as well as `withdrawEarnings` for credited fees, so redemptions do not need unlisting to free
fee income. A listing that moved on since the keeper looked is skipped, not fatal.

## D26. Economics read and token swap moved to a linked library (EIP-170)

**Chose:** `VaultLib` (external library, delegatecall) holds the FWA economics read and the v4
swap body. PackVault was 22,827 bytes then (23,904 after D32 to D41), VaultLib 2,945. The deploy script
deploys and links it. Behaviour is unchanged; there are two verified addresses instead of one.
**Alternative rejected:** dropping token conversion. The owner required it in the immutable
deployment, even though measured token income is about 2.5e12 wei per buyback.

## D27. One keeper policy for the live keeper and the simulation

**Chose:** `keeper/policy.py` decides every call from observed state; `keeper/keeper.py` only reads
the chain and sends. `sim/forward.py` runs the same policy for a simulated year, so the lifecycle
(resolve, harvest, unlist for redemptions, liquidate, checkpoint, relist, restock, unwind on a
broken edge, wind-down, gas above the ceiling) is exercised over long runs. `keeper/rehearse.sh`
runs the production deploy script and the real keeper on a local anvil fork.

## D28. Gate stays on 30-day volume; no on-chain volume pause

**Owner decision kept:** the formal gate uses trailing 30-day volume.
**Evaluated:** a pause triggered by short-term activity. Expected value per bid cycle,
B (k - 1) less gas, does not depend on volume; volume sets how many cycles a year happen, so the
return rate, not its sign. What volume can make harmful is fixed spending on new positions: a
restock costs ~1.05M gas plus 0.0003 ETH per pack up front. D20 already requires one cycle to
repay it, which bounds the damage at any volume. An on-chain volume signal would need new state
fed from FWA's request counter and adds a path keepers can game. The reference keeper has
`--slowdown-volume` (stop building new packs while 7-day volume is low; relisting continues);
section 4 of `sim/out/forward.md` measures what it changes.

## D29. Small accounting choices kept

- A checkpoint's own keeper pay leaves after it prices, so holders after that checkpoint
  (including the deposits it priced) bear it: about 4e13 wei per checkpoint at 0.2 gwei.
- `opGasCap` bound raised to the 16,777,216 transaction cap (default 15M): real checkpoints at
  scale use ~10M gas and the old 3M cap would have left them unpaid. Pay is still actual gas.
- `params` is read through `getParams()`; the struct (16 fields with `maxTip`) is too wide for an
  auto-getter.

## D30. Allocated-exposure bound default 10% (was 2%)

**Found (simulation):** a checkpoint reverts when positions selected but not yet settled exceed
`allocatedBoundBps` of NAV. At 2%, 100 positions and about 70 acquisitions a day, the bound
blocked a redemption checkpoint; at the 30-day rate (600/day) it would block most of them.
**Why the bound can be wide:** an allocated position is valued at the lesser outcome,
min(P, B (1 - s)) = P, which is exact when the purchaser takes the bid (the usual case). NAV is
never overstated; on a keep it is understated by 0.0059 ETH per position. At 10% the worst
understatement is about 2% of NAV, and only when purchasers keep packs.
**Chose:** recommended default 1,000 bps (the bytecode maximum). The simulation counts a blocked
checkpoint as missed and retries next blackout, as the keeper does.

## D31. Independent review of the repairs (2026-11-16)

A separate reviewer read b39568c, the keeper policy and the Python model against the deployed
FWA, Shapes and ShapePacks sources. No critical or high finding. Resolution:
- **S1 (medium, liveness): `maxTip` unbounded; a low cap underpays honest keepers when inclusion
  needs a higher priority fee.** Now bounded `maxTip <= gasCeiling`. The cap stays: without it a
  builder-keeper pays itself up to the ceiling through its own priority fee. Under congestion,
  necessary calls wait until tips fall or the admin raises `maxTip` through the delay;
  redemptions are delayed, never lost. Recommended 0.05 gwei, revisit at the canary.
- **E1 (medium): keeper pay for necessary work is uncapped by value; old O5 no longer
  describes it.** O5 is restated in OWNER-REQUIREMENTS B2. Lifetime gas per position (list, sync,
  harvest and checkpoint shares) is charged call by call at measured gas in `sim/forward.py`, so
  the reported returns already include it.
- **E2 (low): fragmenting work earns the 30k overhead and premium per call.** The overhead
  roughly equals a transaction's intrinsic cost; the leak is about 10k gas plus 10% per extra
  call (about 2e12 wei at 0.15 gwei). Accepted.
- **E3 (low): packs built while the edge held can sit idle if FWA's fees move before listing.**
  They list again when the edge returns or are redeemed at full value; the loss is the mint fee
  (0.0003 ETH per pack). Accepted.
- **S2 (low): one stale id makes `claimListingFees` skip the whole batch.** Only the caller's
  gas is wasted (unpaid when nothing arrives); the keeper passes active ids only. Accepted.
- **S3 (info): allocated positions are understated at checkpoints.** Kept the wider 10% bound
  (D30): the reviewer preferred 2%, which the simulation showed blocks checkpoints.
- **Larger packs are inert at today's cap.** The keep-outcome gate B (k - s) >= P with
  B = 0.0363 admits P <= 0.0373, so only 3-unit packs list. The allowed-P set works but has no
  effect until the oracle ask rises.

# Validation and repair pass (2026-11-16, second review)

Owner request: verify the automation, the performance claims and whether a small private canary
is technically justified. Hypotheses were checked against code and chain before fixing.

## D32. Settled but unclaimed ETH is a liability (critical custody fix)

**Found:** `_settleHolder` and `_settleDist` move an entitlement from `redemptionReserve` or
`distributionReserve` into `claimableEth[h]`, but `_free()` subtracted only the reserves. Any
holder action that settles without claiming (a new deposit, a cancel, another redeem) turned
that ETH into deployable capital and keeper pay. Reproduced on 847b3fe: 1.0 ETH owed to a holder,
`idleEth` 0.96 ETH, and after one keeper restock and list the vault held 0.35 ETH.
**Chose:** `claimableTotal`, maintained wherever `claimableEth` changes, counted in `_free()`.
Mirrored in `sim/vault.py`; regression `test_settledUnclaimedEthIsNotDeployable`; the invariant
suite now asserts `claimableTotal == sum(claimableEth)`.

## D33. Token rewards: one paid call that claims and sells, valued by simulation

**Found:** the keeper never read pending rewards (`token_pending_eth` stayed zero), valued held
tokens at `refPrice` (a protection floor, not a price), proposed selling the whole balance even
above `clipMax` (a sale that can only revert), and `harvestTokens` reverted for the whole batch
on one stale listing id, which also blocked credit from removed listings. Harvesting was unpaid.
**Chose:** `convert(ids, maxAmount, minOut)` claims active rewards (FWA's batch claim in a
try, so a stale id skips only that claim), withdraws settled credit, then sells
`min(maxAmount, clipMax, held)` once per interval against both the caller's `minOut` and the
reference floor. It is paid only if the pay is at most `keeperShareBps` of the ETH realized.
The keeper reads pending, credit and held amounts from the deployed rewards and token
contracts and values a sale by simulating that exact `convert` call from its own address
(pool fee, price impact, hook and transfer rules included). It plans a sale only when the vault
would pay for it, otherwise it states why it waits; `--subsidize-tokens` lets an operator pay.
**Result:** at canary size, token sales are not self-funding: one buyback paid 28 listings
8.2e12 wei of tokens against 5.0e13 wei of gas pay. Selling needs an operator subsidy or must
wait until enough accumulates. Rewards are never lost by waiting.

## D34. Oracle failure cannot block unlisting, wind-down or redemptions

**Found:** `unlist` read FWA's oracle through `edge()`. FWA's owner can repoint the oracle to any
contract (config key 64); one that reverts or returns malformed data made unlisting revert,
which also blocks wind-down and redemption liquidity.
**Chose:** the oracle read is a raw `staticcall`; a revert or short return means "no cap".
Unlisting needs only k. Regression `test_windDownSurvivesBrokenOracle` repoints the oracle
through FWA's real owner setter.

## D35. Pay for necessary work is bounded per position actually moved

**Found:** `sync` and `unlist` skip ids they cannot act on and reimbursed all gas used, so a keeper
could pad a call with junk ids and earn the 10% premium on the padding.
**Chose:** each pays at most `GAS_PER_MOVED` (300k) per position resolved or unlisted. The new
`activate` (D36) uses the same cap and requires strictly increasing ids. Regression
`test_paddedSyncPaysOnlyForWorkDone` (400 ids, one real kick).

## D36. Staged listings are activated by the vault

**Found:** FWA stages a new listing whenever its acquisition queue is not empty. A staged listing
earns no fees and no token rewards until FWA activates it, which happens through later
acquisitions' reserved batches or FWA's permissionless `activateListings`. At low volume a
relist can sit staged indefinitely.
**Chose:** `activate(ids, maxCount)` runs FWA's activation and pays per vault listing that moved
from staged to active. The keeper plans it whenever a vault listing is staged and the queue is
drained. Tested on a listing FWA really staged (ForkReconcile).

## D37. Keeper bids what the vault reimburses; re-reads after every call

**Found:** the keeper sent at the node's suggested price, which on anvil included a 1 gwei tip;
the vault reimburses at most basefee + `maxTip`, so the keeper lost money on every call. Its
plan was also computed once per pass, so dependent steps used stale state.
**Chose:** the keeper bids basefee + `maxTip` explicitly and sends one call at a time, re-reading
chain state before choosing the next. A call that fails is not retried in the same pass.
**Tradeoff:** when inclusion needs a priority fee above `maxTip`, an unsubsidized keeper waits
(redemptions are delayed, never lost). Each extra gwei of tip costs the keeper about 1 mETH per
million gas: a checkpoint at 100 positions (~3.4M gas) costs 3.4 mETH more per gwei.

## D38. Revenue counts only acquisitions that reached a selection

**Found:** the gate, the closed form, the backtest and the forward simulation counted acquisition
requests. In the last 30 days 28% of requests (5,090 of 18,281) were refunded, mostly during the
Oct 31 drain, and distributed no fees. Successful volume is 442 a day, not 611.
**Chose:** every volume figure uses NFTAllocated (successful selections). The owner's 30-day
window is unchanged; only what it counts is corrected.

## D39. The published backtest is a theoretical comparison, not a return estimate

**Found:** the historical backtest kept n vault listings active at all times. On Oct 31 FWA's pool
drained from about 2,100 active listings to 18; constantly relisted vault positions would have
taken up to 84% of selections, about 110 cycles per position in a day. The real vault cannot do
that: settlement takes minutes to hours, each relist needs fresh backing, and a relist made while
FWA's queue is busy is staged. `sim/out/backtest_audit.md` replays the event log removing each
assumption: the published +2,865% (30 positions, last 30 days) falls to +169% when only
successful acquisitions count and settlement, keeper timing, cash and staging apply; outside
Oct 31 every model agrees within noise.
**Chose:** holder-return claims use only the forward simulation (real cash, inventory, delays,
limits, liabilities) and the executable replay. The instant-relist replay stays only as a
labelled theoretical comparison.

## D40. Rehearsal actors are fresh addresses

**Found:** the overnight `keeper/rehearse.sh` used anvil's dev accounts. Those are real mainnet
addresses; dev account #2 carries an EIP-7702 delegation (`0xef0100...`), so ETH paid to it was
diverted and the keeper's economics in that rehearsal were wrong.
**Chose:** `keeper/rehearse_canary.py` uses keccak-derived addresses it checks are clean on the
fork. `rehearse.sh` is removed.

## D41. Second independent review (2026-11-16)

A separate reviewer read 9a9198b, the keeper, the Python mirror and the economic code against
the deployed sources; it confirmed the D32 custody fix complete and found no critical or high
issue. Resolution:
- **LOW-1: a no-op checkpoint used up the interval's only slot**, so anyone could delay a
  deposit or redemption that arrived later in the same blackout by 12 hours. Now a checkpoint
  reverts unless holders have flows or distributions are on. `test_idleCheckpointUnpaid`
  covers the refusal and the same-blackout pricing that follows.
- **LOW-2: `activate` drains FWA's global staging FIFO but pays only for vault listings**; with
  a long foreign backlog a keeper may pay for others' activations, or revert if `maxCount` does
  not reach the vault's. Accepted: nothing is stuck (FWA's activation is permissionless) and
  acquisitions also activate staged listings.
- **LOW-3: the 30k per-call overhead rewards splitting batches** (worst case about 0.015 ETH a
  year at the ceiling). Accepted, as in D31.
- **ECON-1 and ECON-2** (gas regime, Oct 31 sensitivity) are reported in docs/REPORT.md.

## D42. Gas ceiling 0.5 gwei; the gate is tested at the ceiling; no gas stop rule (owner, 2026-11-16)

**Owner:** "is the gate the max gas? if so use 0.5 gwei to start"; on a wind-down rule for high
gas: "no, don't wind down. admin should be able to raise the gwei limit as needed."
**Chose:** canary `gasCeiling` = 0.5 gwei, and the formal gate is evaluated at the ceiling, the
highest gas at which the vault builds or lists. No automatic or recommended wind-down on gas.
**Mechanism (unchanged code):** above the ceiling `restock` and `list` revert, keeper pay is
priced at most at the ceiling, and the keeper waits. Unlisting, sync, checkpoints and claims stay
callable by anyone. The admin raises the ceiling through `proposeParams` and the 2-day delay (up
to the 50 gwei bytecode bound); the guardian can lower it at once.
**Result:** gate passes at 0.5 gwei: +0.956 mETH per bid cycle, closed form +121%, forward
simulation +76% (p5 -8%) at 100 positions. 0.5 sits under the ~0.54 gwei build threshold, so
building stays viable at the ceiling. The low ceiling also protects holders when gas rises: with
1.0 gwei from day 30 the year is +2.9% (36% loss) instead of +2% (46%) at the old 1.5 ceiling,
because the keeper stops spending instead of running unprofitable cycles.
**Cost:** while gas sits above 0.5 gwei, redemptions wait for cheaper gas or for someone to
checkpoint at a loss, and raising the ceiling takes 2 days.

## D43. FWA token rewards are claimed and burned, never sold (owner, 2026-11-16)

**Owner:** "we shouldn't sell" ... "i'd rather claim + burn them". Supersedes requirement A2's
"token conversion" and D33.
**Chose:** `convert`, the v4 swap (`VaultLib.swapTokens`, `unlockCallback`), the `refPrice`,
`clipMax` and `clipSlippageBps` parameters and the guardian's conversion switch are removed.
`burnTokens(activeIds)` claims pending rewards (stale ids tolerated), withdraws token credit and
calls `token.burn` on the whole balance. It is permissionless and unpaid: burning realizes no ETH,
so holders never pay gas for it. The keeper burns only with `--burn-tokens` (operator pays).
**Why burn works:** FWAToken transfers are locked for non-distributors (D5), but probing the fork
showed `burn(uint256)` and transfers to the zero or dead address succeed from a non-distributor
contract; `test_burnClaimsActiveRewards` asserts total supply falls by exactly the claimed amount.
**Result:** PackVault 22,206 bytes (was 23,904); holders' economics unchanged (tokens were
already zero in NAV). Canary rehearsal: 4.87 tokens burned, keeper gas 3.4e13 wei.
**Cost:** holders forgo token value (about 8.2e12 wei per buyback at canary size).

## D44. One address may hold both roles (owner, 2026-11-16)

**Owner:** "why do we need both? seems overly complex".
**Chose:** no code change; the deploy takes the same address for `guardian` and `admin`. That key
can stop things at once and change parameters after the 2-day delay. Neither role has a path that
moves assets to itself.
**Cost:** with one key, nobody can cancel a malicious parameter proposal from a stolen key; holders
must exit within the 2-day delay. Roles are immutable, so splitting them later means redeploying.

## D45. Gas classes: liability work is the only work planned above the ceiling (2026-11-16)

**Found:** above the vault's gas ceiling the keeper planned nothing, so a redemption requested
during a long spike waited for gas to fall even when a keeper would accept a small loss to honour
it. The contract never blocked that work (only `restock` and `list` check the ceiling), so this
was a keeper rule, not a vault rule.
**Chose:** `policy.plan` keeps every rule below the ceiling. Above it, it plans only work that
honours an existing liability: sync, fee harvest, liquidation and unlisting while redeemers are
short of ETH or the vault winds down, and the checkpoint that prices a redemption. New packs,
relists, activation, optional harvests, deposit pricing (depositors can cancel) and token burns
wait. Whether to pay the difference is the executor's choice: `--max-loss-wei` (default 0) bounds
the loss per call. The vault still reimburses at most the ceiling price, so the vault's cost is
unchanged and no new extractable pay exists.
**Per operation (classes):** new inventory: only when one bid cycle repays the build (below about
0.54 gwei) and under the ceiling. Relist existing packs: when a bid cycle nets positive (break-even
1.59 gwei), under the ceiling. Harvest: when pay <= 25% of fees realized, or for redemption cash.
Token burn: operator opt-in, unpaid, under the ceiling. Checkpoint: in FWA's blackout with flows;
above the ceiling only for redemptions. Recovery (sync) and liquidity release: below the ceiling
when due; above it only for redemptions or wind-down. Wind-down: always planned.
**Evidence:** canary rehearsal step 7 at 1.05 gwei: a no-loss keeper waits (status
GAS_ABOVE_CEILING, two calls skipped for loss); a keeper allowing 0.01 ETH per call released
0.96 ETH of liquidity and priced the redemption for a total keeper loss of 0.00078 ETH.

## D46. Reserve: keep the fixed parameter, size it from obligations (2026-11-16)

**Compared:** the balancer's `requiredReserve()` derives its reserve from a target board the
creator must keep restored. The vault has no target to restore, and its liabilities are already
exact and excluded from every spend path (`_free` subtracts escrow, redemption and distribution
reserves and settled claimables; `_idle` also keeps the owed estimate for unpriced redemptions).
What the reserve buys is keeper pay for necessary work when everything else is deployed: unlists
and syncs pay from the backing they return, so only a checkpoint and a listing batch need it.
**Chose:** no contract change. The canary reserve drops from 0.05 to 0.005 ETH: one checkpoint
at 30 positions plus one 10-pack listing batch at the 0.5 gwei ceiling needs 0.0038 ETH
(`policy.reserve_need`). The keeper reports RESERVE_BELOW_NEED when the parameter falls under the
need for the current ceiling and position limit (raising the ceiling should raise the reserve in
the same proposal).
**Result:** the 2 ETH canary builds 29 positions instead of 28 (rehearsal). A dynamic on-chain
reserve would track the ceiling automatically but costs a contract change, a mirror change in
`sim/vault.py` and reconciliation for about 0.004 ETH of difference at canary scale; rejected.

## D47. Keeper execution: extend the Python keeper with a persistent transaction manager (2026-11-16)

**Compared:** the balancer's TypeScript/viem keeper (one function, `performUpkeep`, whose
simulation returns the reward) against this keeper (many functions chosen by `keeper/policy.py`,
which `sim/forward.py` also imports). Moving to TypeScript would split the policy from the
simulation or require porting both; the balancer's transaction code is about 150 lines inside its
Keeper class, not a library, so no shared package exists to reuse.
**Chose:** `keeper/tx.py` ports the balancer's execution design to Python: pending entry saved
before broadcast, same-nonce +25% replacement after 3 blocks (5 at most, under a bid cap, only
while the call still preflights), receipts reconciled against `KeeperPaid`, reorg re-check of
counted receipts, a lock per state file, `/health` and `--status`. Kept from this keeper: one call
at a time with a fresh read after each, the policy as the only economic logic.
**Cost:** the two repositories keep separate transaction managers; they share the design and its
test list, not code. Extracting a shared package is worth it only if a third keeper appears.
**Evidence:** `keeper/test_tx.py`, 10 scenarios on a local anvil; rehearsal: the state file's
keeper pay and gas spent equal the chain's to the wei over 18 transactions.

## D48. Inventory planning stays in the policy (2026-11-16)

**Reviewed:** the balancer keeps a target board and restocks deficits in bounded batches because
its creator chooses a fixed prize mix. The vault has no target mix; its target is "every position
the capital, the position limit and the gas allow". The policy already relists returned packs
before building, builds only in whole 0.1 ETH Shape mints split into packs, sizes each build to
the capital check, stops building while trailing volume is under the slowdown floor, and deploys
nothing in a pass that frees redemption cash. No waste found in the rehearsal (9 mints for 29
packs: 87 Shapes used of 90 minted, 3 loose Shapes carried to the next build). No change.

## D49. Asset-flow verification uses the owner's kit (2026-11-16)

**Chose:** the same asset-flow kit the balancer uses (`~/.agents/guidance/asset-flow-kit`):
`test/utils/FlowBreakdown.sol`, regime scenarios in `test/scenario/`, `asset-flow.json` with
DRAFT outcomes for the owner to sign, scorecards in `docs/receipts/flow/`, and
`docs/SYSTEM-MAP.md`. Not imported: the balancer's creator profit, player price, prize restocking
and board-shape regimes.

## D50. The burn calls stay unpaid and public (owner, 2026-11-16)

**Owner:** "we shouldn't reimburse for the claim and burn calls. just make that public that anyone
can call whenever they want." Already so since D43: `burnTokens` has no caller check and pays
nothing. The keeper sends it only with `--burn-tokens`, at the operator's own cost.

## D51. No gas-price refusal; the ceiling only caps reimbursement (owner, 2026-11-16)

**Owner:** on new positions refused above the ceiling: "can't those still go through, just not gas
reimbursed?" ... "remove it". Supersedes the gas-price revert described in D42.
**Chose:** `_requireOperating` no longer reverts when `tx.gasprice > gasCeiling` (error `GasPrice`
removed). `restock` and `list` are accepted at any gas price and, like every paid call, reimbursed
at `min(tx price, basefee + maxTip, gasCeiling)`; the caller pays the rest. The build's own
profitability gate (`EdgeGate`) prices gas the same capped way.
**Effect:** holders' cost per build is capped at the ceiling price, the same as a build at 0.5
gwei, which the policy already accepts. The keeper still does not build or list above the ceiling
(D45). The guardian can no longer stop building by lowering the ceiling; `guard(pauseListing)`
does that. Keeper default `--max-loss-wei 0`: above the ceiling it waits for all work (owner,
same day); anyone may still call any step.
**Evidence:** `test_buildAboveCeilingPaidAtCeilingPrice` (built at 6 gwei with a 5 gwei ceiling,
pay = gas x 5 gwei x 1.10 exactly); VaultFlow `gas_spike` (build and checkpoint at 2 gwei, both
paid at 0.5 gwei x 1.10). PackVault 22,171 bytes.

## D52. Asset-flow outcomes tightened before signature (2026-11-16)

Three DRAFT outcomes checked a weaker fact than they stated; now each measures the claim itself:
- **O3 (wind-down):** each holder's claim equals their share of the vault's value to the wei
  (measured gap 0), against an independent calculation from the vault's ETH.
- **O5 (liabilities):** after every keeper call in every regime the test asserts the balance covers
  liabilities and spendable ETH is zero or fits under balance less liabilities, owed estimate and
  reserve; the settled-unclaimed regime reports 0 wei of overlap.
- **O8 (oracle failure):** after the oracle is repointed the kicked pack is in inventory and a
  holder redeeming everything is paid 0.9975 ETH of a 1 ETH deposit.
Also: O2 states the bound, not a position count; O9 (distributions on, not the canary setting)
is replaced by the zero-demand holder cost, at most 1.5% of deposits (measured 0.46%).

**Found while tightening O3:** a checkpoint prices redemptions before paying its own keeper, so
that pay (about 0.00005 ETH per checkpoint at 0.2 gwei) falls on the shares that stay, not on
those leaving or entering. Kept: it is one call's gas, bounded by the ceiling price, and moving
the payment ahead of pricing would change the checkpoint's accounting for no material gain.

## D53. Canary size 2 ETH confirmed; O2 measured in gas per position (owner, 2026-11-16)

**Owner:** "approved" (2 ETH deposit cap, about 29 positions, roughly 1 to 1.5 selections a day at
recent activity). O2 was an ETH total at the test's 0.2 gwei, built one pack per call; it is now
keeper gas per position with the keeper's batches of 10: 1.60M measured, bound 1.75M (at most
0.00096 ETH per position at the 0.5 gwei ceiling).

## D54. Release-candidate audit at 3e600e5: open owner decision on F1 (2026-11-17)

Independent audit report and source hash in `audit/rc-3e600e5/`. No critical or high finding.
**F1 (low, new):** keeper pay lets a compromised admin pay itself. At the bytecode maxima (50%
premium, 50 gwei ceiling) self-keeping a dust-deposit checkpoint nets +0.0028 ETH each, about
0.0056 ETH a day, after a visible 2-day delay that holders can exit through. At canary values it is
about 1e-5 ETH per checkpoint, the ordinary keeper margin. The natspec and D44 claim "neither role
has any path that moves assets to itself" is wrong as stated. **Open:** tighten
MAX_KEEPER_PREMIUM_BPS (contract change, re-review of the change) or reword the claim only.

## D55. Flat work fee per unit of work, for permissionless keepers (owner, 2026-11-17)

**Owner:** "the vault is permissionless too. or should be" ... "do this" (add a per-unit flat fee).
**Why:** gas plus 10% lets anyone run the vault without loss, but at today's gas the absolute
margin is too small for strangers to bother (a checkpoint earned about 0.000003 ETH). The pool
balancer pays 0.0001 ETH per call; per call would let a vault keeper earn more by splitting work.
**Chose:** `workFee` (Params, admin through the delay, bytecode maximum `MAX_WORK_FEE` 0.0001 ETH,
canary 0.00002 ETH) paid per unit of work on top of the gas reimbursement: positions listed,
resolved by sync, activated or unlisted; items liquidated; 1 for a checkpoint that priced flows or
distributed. restock, harvest and burnTokens earn none. Pay stays capped by `_free()`. The guardian
can lower the fee at once through `lowerCaps` (with the ceiling at 0, no keeper pay remains).
Policy and simulation include the fee (bid-cycle cost +2 units, build +1, reserve need +11).
**Evidence:** `test_workFeePerUnitNotPerCall` (every pay is gas x 0.22 gwei + units x fee exactly;
3 packs in 1 call or 3 calls earn the same 3 units), `test_workFeeBounded` (admin bound; guardian
lowers, never raises), auditor's `test/audit/AuditWorkFeeManufacture.t.sol`. Canary rehearsal:
keeper net over the lifecycle +0.00225 ETH (was +0.00035); holder result -0.0221 ETH on 1.99
(was -0.0201) with no acquisitions. Simulation, 100 positions, last 14 days: +21.0%, P(loss) 17%.
**Accepted (review LOW-2):** a 0.01 ETH deposit can create one paid checkpoint per 12 h interval:
at most 2 units a day, 0.0146 ETH a year at the canary fee (0.073 at the maximum); a net loss to
the caller above about 0.4 gwei at the canary fee.
**Not changed (review NIT-1):** the keeper counts only units it is sure of (list n, checkpoint 1),
so its loss check is stricter than the contract's pay.
**Repair from the second review (same day):** `lowerCaps` also cancels any queued admin proposal,
which would otherwise restore the old caps, ceiling or fee when applied after a guardian stop
(pre-existing for the caps and ceiling). Covered in `test_workFeeBounded`.

## D56. Quoted keeper pay, request charges and refilling budgets (owner brief, 2026-11-17)

**Owner:** "Implement keeper reimbursement redesign" (brief 1), then "why would we do a % and a flat
fee?!" (no percentage on top of the flat fee). Supersedes D55's premium-plus-fee rule, D51's
"reimbursed at min(tx price, ...)" wording, the 30,000-gas overhead and the per-position gas caps
(V7), and closes D54's F1 by construction.
**Chose:**
- Pay never reads `gasleft()` or `tx.gasprice`. Each operation has a quoted gas figure: a base plus
  a per-unit amount (`VaultLib.Q_*`), measured as billed gas on fork receipts
  (`keeper/measure_gas.py`, `sim/out/gas-quotes.json`). Each base is at or under the measured fixed
  cost divided by 1.1, so splitting a job never earns a second base worth its transaction.
- The vault's envelope: `quotedGas x min(basefee + maxTip, gasCeiling)`, times `1 + payMarkupBps` on
  routine work (bytecode maximum 10%, canary 0), plus `workFee x units`. Gates and charges use it.
- Request charges pay for the work a request causes, so a dust deposit or redemption cannot
  manufacture paid work: a checkpoint charge (quote of one checkpoint plus one unit) into
  `processingPool`, which funds the checkpoint's pay and releases the rest to holders; a deployment
  charge escrowed with each deposit (no shares, joins NAV at pricing, refunded on cancel, floored at
  the builder's maximum margin); an unwind charge on redemptions. The high-water mark is raised after
  deposits so charges are never distributed.
- Budgets: routine and essential buckets refill linearly to immutable bytecode maxima. Essential work
  (unlist, liquidate, checkpoints with redemptions, syncs during redemptions or wind-down) carries no
  markup and draws only on the essential bucket, so routine work cannot starve redemptions.
- `minPay` on every paid call: the call reverts if pay would be lower; with 0 the work runs for
  whatever is paid, so maintenance is never blocked by pay.
**Evidence:** `test/fork/ForkKeeperPay.t.sol` (11 tests: pay ignores caller gas and tip, splitting
loses, repeats pay nothing, dust deposit and tiny redemption, manufactured cycle at the maxima loses,
budgets bound spend, routine cannot drain essential, pay never uses liabilities, minPay atomic).

## D57. Replaceable keeper payment policy (owner brief, 2026-11-17)

**Owner:** "Implement a replaceable keeper payment policy". No proxy, plugin framework, registry or
governance token.
**Chose:** PackVault stays immutable and enforces everything (asset custody, work validation, the
envelope, budgets, liabilities, paying). A separate `IKeeperPolicy` contract only proposes a payment
from facts the vault established (operation, completed units, quoted gas, essential flag, ceiling,
tip, fee). The vault calls it with a 50,000-gas `staticcall` after the work and pays
`min(offer, envelope, funding cap, free ETH, budget)`. A revert, gas exhaustion or short return
offers 0: the work stands, the call pays 0, and `minPay` decides whether the caller accepts that.
The admin proposes a policy (must have code and a nonzero `policyVersion()`); anyone activates it
after `paramDelay`; `PolicyChanged(old, new)` is emitted. The guardian cancels a queued policy
(`guard(.., .., true)` or `lowerCaps`) and can stop all pay at once (budget caps 0, or ceiling and
fee 0). A policy cannot loosen a gate or a charge: those use the envelope.
**V1** (`KeeperPolicyV1`): `quotedGas x min(basefee + maxTip, gasCeiling) + units x workFee`. No
premium. Canary: ceiling 0.5 gwei, maxTip 0.05 gwei, fee 0.00002 ETH, markup 0, so the envelope
equals V1's pay.
**Found while testing:** Yul evaluates `and(staticcall(..), gt(returndatasize(), 31))` right to left,
so the size check read the previous call's return data; every offer read 0. Fixed by binding the
call result first. Pay was never above the envelope; the bug paid too little.
**Evidence:** `test/fork/ForkKeeperPolicy.t.sol` (swap to a different formula preserves balance,
shares, NAV, positions, pool and charges, then pays V2's own quote to the wei; invalid policies
rejected; greedy policy capped at the envelope; reverting, gas-burning and short-return policies pay
0 while work runs and `minPay > 0` reverts; guardian cancels and disables). Canary rehearsal swaps V1
to a 3-fee-per-unit V2 mid-run with the unchanged keeper; ledger and keeper accounting close to the wei.

## D58. No delay on admin changes (owner, 2026-11-17)

**Owner:** "remove all delays on changes." Supersedes the parameter delay (`paramDelay`, D-records
from the original design onward) and D57's propose/activate flow for the keeper policy.
**Chose:** `setParams(p)` and `setPolicy(policy)`, admin only, take effect in the same
transaction; bounds (`checkBounds`, `checkPolicy`) are unchanged. `proposeParams`, `applyParams`,
`proposePolicy`, `activatePolicy`, the pending state, `TooEarly` and the constructor's `paramDelay`
are removed; `guard` keeps only its two pause flags. A parameter change still accrues the budgets at
the old rates and only clamps after, so raising a cap never refills it.
**Effect for holders:** they no longer get warning time to exit before a change. The guardian can
still lower caps or stop pay at once, but the admin can raise them back at once. A compromised admin
acting as keeper can take, at most, the budgets' current balance (canary 0.04 ETH) plus their refill
at the bytecode maximum rates (0.015 ETH a day): about 0.055 ETH on the first day of a 2 ETH canary,
then 0.015 a day, until holders exit or the guardian winds down. The guardian's `lowerCaps` and
policy stop no longer hold against the admin, who can undo them in the next transaction; only the
pause flags and wind-down are durable, and wind-down does not freeze `setParams`. Mitigations not
taken (owner's call): lower the bytecode budget maxima; a guardian freeze on admin setters; keep a
delay only on raises. Independent diff review: no code defect.
**Evidence:** 80 fork, audit and scenario tests; `test_swapToDifferentFormulaPreservesAccounting`
(instant swap, non-admin refused, state unchanged); `test_paramsBoundsAppliedAtOnce`; canary
rehearsal swaps the policy instantly with the ledger closing to the wei. PackVault 22,809 bytes.

## D59. One owner role (owner, 2026-11-17)

**Owner:** "why do we still have the guardian and admin roles? ... seems like overkill", then "do it".
Supersedes D44 (one address may hold both roles) and the guardian half of D58.
**Chose:** one immutable `owner` with `setParams`, `setPolicy`, `guard` (one-way pauses) and
`startWindDown`. `lowerCaps` and `VaultLib.lower` are removed: with no delay, `setParams` lowers
anything at once. Constructor takes one address; the canary values file has `owner`.
**Given up:** a separate stop-only key (for example a hot emergency key beside a cold admin key).
**Evidence:** 80 fork, audit and scenario tests; canary rehearsal (owner swaps the policy and starts
wind-down) closes to the wei; reconciler exact. PackVault 22,364 bytes.

## D60. Repairs from launch audit A (2026-11-17)

**Source:** external launch audit step A at `ba8d26e` (`audit/release-ba8d26e/REPORT.md`).
**Chose:** fix every code finding with the smallest change that closes it (table in
`audit/release-ba8d26e-repairs/REPAIRS.md`). Two contract rules are new:
- A checkpoint that neither settles holder flows nor distributes reverts whole (`Nothing`), so it
  never consumes the interval's one slot (E3).
- A checkpoint refuses to price (`SyncFirst`) while an allocation past FWA's settlement window is
  unsynced (E6). Rejected alternative: marking such a listing at its reclaimable backing. FWA's
  verified `keepNFT`/`acceptDepositorBid` stay open "the whole time the listing is allocated", so
  the purchaser can still choose the lower outcome after the window; only `sync` makes it certain.
Liveness check (repair review F1): `SyncFirst` makes redemption checkpoints depend on resolving
the allocation. FWA's verified `depositorReclaimBacking`/`depositorReclaimNFT` cannot be blocked
by the purchaser: NFT delivery is non-strict (`_deliverNFT` records a stuck-NFT claim on failure),
ETH leaves by force-send, and only FWA's own immutable notifier can revert the settlement; either
way the listing leaves `Allocated`, so a stuck pack no longer blocks pricing.
Pack sizes above 30 units are out of bounds (E11). The oracle read cannot revert or burn the
call's gas (S1).
**Open, owner's call:** E7 (return gate unvalidated until the forward model handles FWA staging),
E8 (owner-compromise bound and raisable TVL cap), E9 (outcome signature).

## D61. Checkpoint quote, essential ceiling, shared checkpoint charge (owner, 2026-11-17)

**Owner:** "yes approved. do your recs."
**Chose:**
- Checkpoint quoted at measured billed gas: 225,000 + 33,000 per position (was 180,000 + 32,000).
  One checkpoint per interval cannot be split, so the split-proof discount does not apply.
- `essentialCeiling` (canary 2 gwei, bytecode max 50 gwei): essential work (redemption and
  wind-down: unlist, liquidate, checkpoints with redemptions, syncs during them) is priced at
  `min(basefee + maxTip, essentialCeiling)`; routine work stays at `gasCeiling`. Paid only from
  the essential budget, so worst-case spend is unchanged.
- `requestCharge()` tops `processingPool` up to one checkpoint's cost (whole gwei); later
  requests in the interval pay 0. A cancel refunds its charge beyond what still-waiting flows
  need. `PendingDeposit` stores the charge as `uint32` gwei (max ~4.29 ETH; a checkpoint at the
  maxima costs ~0.51 ETH).
**E8 accepted (owner):** a compromised owner can take at most the budgets' balance plus refill
at the bytecode maxima (canary: 0.055 ETH the first day, 0.015 ETH a day after); raising
`tvlCap` exposes more holders to bad settings but does not raise that rate. Mitigation is
operational: the owner key is a multisig or hardware wallet. Bytecode budget maxima are not
lowered: 300 positions at full volume could need about 0.02 ETH a day of routine pay.
**Evidence:** `test_requestChargeTopsUpOnce`, `test_cancelKeepsPoolForOtherFlows`,
`test_essentialCeilingPaysExitsInSpikes`, `test_cancelCyclesRetainNothing`; 95 fork, audit and
scenario tests; reconciler exact; rehearsal closes to the wei; invariant campaign 64 x 64.

## D62. Backing rule: floor, gas-optimal, spare capital; oracle exemption (owner, 2026-11-17)

**Context:** FWA's owner made ShapePacks oracle-exempt (no floor cap, no kicks). PackVault read
exemption as "no price" and would have listed nothing on mainnet (found by the current-block
rehearsal, launch step D). FWA's minimum backing is 0.025 ETH (owner-set; the source default is
0.01).
**Analysis:** FWA splits each fee evenly across listings and selects by 1/B, so a position's
profit per acquisition, (k - 1)/W, does not depend on its backing; capital per position is B + P.
Backing only matters through capital (lower is better), gas per cycle (fewer cycles is better)
and idle capital when the position count, not capital, binds. Mixed pack sizes never help:
larger packs only add capital.
**Chose (owner: "do your rec. don't add the list argument"):** the vault computes backing at
listing, no new argument, as the largest of:
- the floor max(P / d, P / (1 - s)), d = FWA's bid payout rate (90%): a purchaser then prefers
  the bid to keeping a pack worth P, so packs keep cycling (a keep forces a rebuild), and a keep
  never loses. 0.0333 ETH for a 3-unit pack;
- build repayment (build + cycle cost) / (k - 1) at today's quoted price, so one bid cycle repays
  a new pack (the approved build gate) as gas rises: 0.0360 ETH at 0.5 gwei;
- the gas-optimal (c + sqrt(c^2 + a c P)) / a at the routine ceiling (binds above ~1 gwei);
- spare capital spread over open slots when the position count binds;
capped at FWA's oracle cap less the buffer unless the collection is exempt. 3-unit packs.
**Corrected the same day:** the first version used only P / (1 - s) = 0.0303; the forward model
then built nothing at 0.5 gwei, and at 0.0303 a rational purchaser keeps the pack (0.9 x 0.0303
< 0.03), so every cycle would need a rebuild. Lower backing also sits below most oracle cuts, so
listings are rarely kickable.
**Evidence:** `test/fork/ForkBacking.t.sol` (exempt lists at the floor; spread when count binds;
oracle cap when not exempt; gas-optimal above the floor at a 1 gwei ceiling); 98 fork, audit and
scenario tests; reconciler exact; pinned rehearsal; current-block rehearsal lists 30 positions,
ledger exact.

## D63. Repairs from launch audit B (2026-11-17)

**Source:** uninformed whole-candidate audit at `c884959` (`audit/release-c884959-B/`), then the
A/B comparison (step C): every executed B finding reproduced on main and became a regression.
**Chose:** exits (wind-down, redemption unwinding) never read FWA's economics; harvest ids strictly
ascending; checkpoint pay funded by request charges is outside the holder budgets; spare-capital
backing at most twice the rule's need; `list` refuses while FWA's queue is busy (nothing the vault
lists is ever staged); the owner can resume pauses (wind-down stays one-way); the deploy script
range-checks values and refuses a placeholder owner; the keeper prices cost at the next block's
highest basefee and past a cumulative loss limit (`--max-total-loss-wei`, default 0.005 ETH) accepts no further loss while paid work continues. Independent repair review: all sound.
Table in `audit/release-c884959-B/REPAIRS.md`.
**Open, owner's call:** the canary essential budget (cap 0.01 ETH, refill 0.0002 ETH a day) is
emptied by one full exit at about 1 gwei; holders can still exit unpaid.

## D64. Exit work unpaid at canary values (owner, 2026-11-17)

**Owner:** "i don't think it's crazy to make withdrawers pay their gas/execute the txs" ... "don't
over complicate this".
**Chose:** canary essential budget 0 (cap and refill), so unlisting and liquidating for
redemptions or wind-down pay no keeper; withdrawers (or the owner in a wind-down) run those calls at
their own gas. With no essential budget `unwindCharge()` is 0, so redeemers are not charged for
work nobody is paid to do. Checkpoints stay paid from the request charges. Paid exits return by
setting an essential budget with `setParams` (instant). Owner-compromise first-day bound falls
from about 0.055 to 0.045 ETH. Supersedes the essential-budget sizing question in D63.
**Evidence:** `test_selfServeExitWithoutEssentialBudget`; 106 fork, audit and scenario tests;
rehearsals at the pinned and current block, where the withdrawer and owner run the exit steps
(ledgers exact; current-block holder round trip -0.0151 ETH, was -0.0169).


## D65. Incremental production position accounting (owner, 2026-11-18)

The owner accepted the accounting design in `POSITION-ACCOUNTING-PLAN.md` and requested integration
from research proof `3b9cd65`, preserving the newer documentation handoff `f75ee77`.
One vault retains all holder and mint behavior. Exact running Shapes backing, active FWA backing,
a fee-debt histogram, ordered acquisition cursor, authenticated payment receipts and an allocation
queue replace valuation scans. This supersedes D6/D24's count cap and D62's spare-slot spread and
no-list-argument instruction. Backing proposals are offchain, quantized to 10,000 wei, unique among
outstanding identifiers, and authenticated against current economics and capital onchain. The max
ordinary 5% keep fee requires B >= ceil(P * 10000 / 9500).

Staged listing admission is rejected atomically, so D36's production activation operation is
retired. Operation identifier 4 is left unused; other keeper operation identifiers retain meaning.
D61's shared checkpoint charge remains, with fixed measured work replacing the portfolio component.
New global journal work is funded only from actual free ETH within existing budgets; foreign and
refunded entries earn only their completed-work gas component, without a per-entry flat fee.

Implementation API intentionally changes. Operational callers migrate together; no permanent unused
full-array getters or compatibility wrapper remains in production. Bounded test-only enumeration
remains an independent reference. The existing signature and historical audit evidence do not approve
this candidate. Final measurements, fork reconciliation, independent review and outcome approval
remain separate gates. No production broadcast or remote publication is authorized.

## D66. Measured work quotes and prospective keeper context (engineering, 2026-11-18)

Production bookkeeping adds real work to listing, fee harvesting, withdrawal and redemption.
Update the measured cost inputs while retaining the entry build/list charge, exit unlist/liquidate
charge, shared checkpoint charge and recurring-maintenance funding policies. No budget maximum,
refill, reserve, mint fee, pack mask or allocated exposure limit is loosened by this decision.

Ordinary pack redemption and oversized gift claims authenticate actual burned Shape count through
`Shapes.totalSupply()` immediately before/after the immutable redemption path. The path burns
exactly its actual batch before its sole ETH callback, and the guarded vault cannot interleave a
second supply mutation. Recovery pays an unseal component once, then components for completed
actual work; a final one-Shape claim no longer receives a thirty-Shape quote. No unbounded pack
contents getter is used onchain or required by the normal keeper.

Both the ordinary keeper and production list at most eight packs per transaction. The other
sixteen-item work limits remain. The local event index bounds RPC candidate hydration independently
of total unchanged inventory. Reserve analysis distinguishes funded essential work from D64's unpaid
self-serve exits and includes global work that returns no backing.

A proposal within a few 10,000 wei tags of a live target is sensitive to basefee when the build
repayment term binds. The keeper authenticates a prospective pending header against the pinned
parent's deterministic next basefee and uses explicit fee fields for price and pay simulations.
Actual Tenderly reads showed that omitting fees could execute `BASEFEE` as zero despite a nonzero
pending header. The parent hash is checked before submission; later state/head changes can still
reject a transaction atomically. No admission tolerance or economic gate is relaxed.

The owner explicitly approved the isolated local batch in `receipts/position-local-batch-plan.json`:
127.0.0.1:8557, fork 26,418,539, six named fresh test signers, 60 simulated ETH total, normal code
and transaction limits, plus the named oracle owner's local calls with zero added funding. This
approval authorizes no public-network transaction, merge, owner signature or real-fund spending.

Gas setup correction: the inherited 8,000-block expiry wait was unnecessary for the deployed
30-block word timeout. Rehearsal helpers now use each request's actual snapshotted deadline. The
already-started mining operation and its node were preserved; no protocol state was fabricated.
Final receipts, quote calibration and funding conclusions belong in the acceptance report.

FWA's acquisition queue can be drained while its private staging FIFO still contains foreign
listings. FWA exposes no public staging-head getter. Each production admission forwards at most
1.2 million gas to `listNFT` and requires the active count to increase by exactly one, alongside
the ordinary Active identity checks. Incidental foreign activation or a staged result reverts the
whole vault transaction, including earlier batch work. The eight-listing limit reserves transaction
headroom for this bounded external work; the vault does not pay to drain foreign staging. This can
leave admission waiting for FWA's permissionless activation to be performed by another actor.
Journal processing, pricing eligibility and exits do not depend on a staging-head read.

The broad integration run exposed profitable splitting of the 400,000-gas listing base. Actual
matched-fee receipts measured 650,969 additional billed gas for three singleton calls versus the
same three listings in one batch. The base is now 280,000, leaving 6.9938 microETH of loss for the
split at 0.2 gwei even at the maximum 10% markup. Per-listing gas and work fees are unchanged.
This is measured sample evidence, not a universal future gas guarantee. The final O2 build/list
cost and O6 checkpoint cost exceed their historical signed amounts; those bounds and the signature
are retained, with gate failure reported rather than changing them without owner approval.

## D67. Unpaid cursor advance with no FWA exposure (owner, 2026-11-18)

The owner approved refining D65's requirement to process every completed entry. The book may
advance directly to FWA's completed prefix only when it has no open position, reserved identifier,
active membership or backing, allocated value, or pending receipt. An OWED position still counts
as open. Idle inventory alone is not FWA exposure. An unseen own allocation therefore cannot be
skipped, and outstanding receipts must still be reconciled in order.

This constant-work advance earns zero gas quote and zero work units. It is available during sync,
checkpoint, and immediately before first admission. Checkpoint and admission can include it in
their existing funded operation; the keeper need not execute a separate unpaid catchup call.
Empty tracked inventory cannot earn keeper pay for stale allocation-head cleanup either. Positive
`minPay` still reverts the whole operation if its payment is unavailable.

The change protects the minimum seed from unrelated history and preserves first-deposit pricing.
It does not protect exposed capital from its existing maintenance costs, change the reserve or
budgets, fund essential exits, or approve revised O2/O6 outcomes. The strict public valuation view
still requires an up-to-date cursor; checkpoint establishes the approved proof before pricing.

## D68. Checkpoint compensation calibration within O6 (engineering, 2026-11-18)

Reduce the fixed checkpoint gas component from 400,000 to 360,000. Keep one work unit, the
configured work fee, gas ceilings, budgets, processing-pool funding and the owner's 0.0002 ETH
O6 limit. At the configured 0.5 gwei routine ceiling and 0.00002 ETH work fee, checkpoint pay is
0.0002 ETH. Shared request charges use the reduced component as well.

The current full-holder fixture combines a redemption remainder, distribution and new deposit.
The original interpretation of 372,366 caller-meter gas minus a 29,600 refund as a
342,766 upper bound was incorrect: isolated Foundry calls had already finalized refunds.
That derived bound is withdrawn, with raw evidence preserved. The current direct finalized
meter is 345,937 gas, below 360,000 by 14,063 (4.07%). See
`receipts/restock-efficiency-meter-correction.json` for installed Foundry source and meter
provenance. Actual signed full-holder receipts remain separate required evidence.

This is a bounded sample, not a universal keeper profit guarantee. Foundry original-slot/refund
context can differ from a standalone transaction. Actual billed full-holder receipts remain a
release evidence gap. Above-ceiling caller gas can still exceed capped compensation. Journal
quotes are unchanged: new real refund receipts show that raising their call base can reward
splitting even when an older successful-foreign gross series suggested otherwise. O2 and exposed
global funding remain acceptance blockers.


## D69. Enforce efficient journal jobs and fund sync as routine upkeep (owner, 2026-11-18)

The owner's detailed seven-item next revision request is recorded in
`EFFICIENT-JOURNAL-REVISION.md` and OWNER-REQUIREMENTS items22–27. The global read job has its
own128-record bound; actual own transitions, supplied terminal IDs and head pruning each retain
independent16-item bounds. A seventeenth own transition remains unconsumed. Callers cannot select
a smaller paid prefix or reduce the journal with irrelevant terminal IDs. Full jobs and verified
own work qualify; residual foreign work qualifies only for a fresh, drained checkpoint window
with actual holder flows or an authenticated post-cost distribution. Unexposed advance remains
unpaid. Optional unqualified tails can advance unpaid. No completion bonus is introduced.

`sync(ids,witnessId,minPay)` intentionally replaces the earlier four-argument interface. Normal
keeper/test callers migrate together. Historical receipt drivers remain tied to their old ABI.
All sync uses routine cash and spending permission, including during redemption and wind-down.
D64's caller-funded unlisting/liquidation remains. The keeper reversibly pauses new exposure if
the known journal quote exceeds free cash or routine permission. Reconciliation and holder paths
remain permissionless. No reserve, budget, cap, refill or permanent wind-down policy changes.

Default funding is vault operating cash, reducing holder returns. Mint revenue is not an assumed
subsidy, principal movements are not income, and no minimum TVL is introduced. Any allowance
proposal must show ETH/day, actual vault cash, all remaining work, completed exits and net holder
returns. A separately approved capped experiment subsidy must be excluded from earned return.
O2 and other accepted outcome numbers and the existing signature are unchanged.

Keep the85,000 ordinary base while measuring the new boundaries. `Q_REQUIRED_TAIL` initially
names the same85,000 base for qualified foreign tails, replacing rather than adding the base.
Numerical calibration must follow real estimates/bills, including keeper willingness. The
memory-only consumed mint IDs and shared pre-mutation restock context preserve paid mints,
ten-way splitting, recipes and creator fees; execution savings alone do not reduce holder pay.

Bid settlement events now independently identify returned packs, with historical upgrade replay,
retained unseen selections, independent expiry/OWED discovery and canonical rollback checks.
This index supplies candidates, not completeness or accounting authority.


## D70. Fee collection follows verified work (engineering, 2026-11-18)

The owner asked to finish the remaining design and implementation autonomously in one integrated pass. Keep one vault and the incremental book, preserve primary mint revenue, and resolve harvesting, recurring funding and verification together.

Standalone harvesting is now caller funded. Positive minimum payment reverts, while zero retains manual fee collection. Verified paid sync may sweep economical credit and, only if its actual protected free cash remains insufficient, collect the first distinct active fee prefix that funds the completed job. The incremental fee collection quote must fit the existing fee share restraint and the whole payment must fit routine permission. Terminal proceeds arrive first. Distribution eligibility uses the full combined cost. No optional tail, duplicate, padding or empty call can create compensated collection.

The keeper tries the ordinary sync and bounded funding alternatives through the contract's exact preflight. It sends the shortest profitable call and replans after the receipt. This avoids maintaining a separate approximate eligibility formula. Full exits collect fees through unlisting and checkpoint. A cheap manual partial redemption claim remains available.

Required tail and own selection quotes become 120,000 and 180,000 after measurement. The ordinary base remains 85,000 and each journal record remains 22,000. New collection components are 40,000 for credit and 40,000 plus 80,000 per actual active fee claim. The extra shape slope becomes 100,000 after a signed four shape leftover receipt exposed underpayment. Three shape construction, mint, listing and checkpoint quotes remain unchanged. The original O2 failure remains explicit.

## D71. Refill operating permission at the measured spending rate (engineering, 2026-11-18)

The completed operation and exit model separates actual cash from permission. Larger initial buckets concealed a recurring deficit. The mainnet high activity case spends about 0.0155 ETH per day in the thirty day test, while the old hard maximum replenished 0.01 ETH per day. Raising capacity alone is temporary.

Choose mainnet capacity 0.1 ETH with 0.02 ETH per day refill, and canary capacity 0.03 ETH with 0.01 ETH per day refill. Raise only the routine refill hard maximum from 0.01 to 0.02 ETH per day. Other hard caps, protected liabilities, mint fees and the routine gas ceiling remain unchanged. There is no minimum TVL or recurring creator subsidy.

These are spending permissions, funded only by real unencumbered vault cash. They increase authorized maintenance outflow over time and do not create operating income. The larger vault's ninety day stress case pays every routine job, keeps permission near capacity at each monthly observation and completes the holder exit. Small vault losses and zero demand remain visible. Results are conditional engineering scenarios with explicit pool, volume, purchaser timing and caller gas inputs.

No original acceptance threshold or outcome signature is silently changed. Current evidence and limits are in `COMPLETE-OPERATING-PASS.md`. PR 2 remains draft; this decision records implementation work, not a public deployment or merge.


## D72. Formal holder-return assessment replays the actual window (engineering, 2026-11-19)

The owner's gate (A.3, A.8, A.10) is measured by `sim/formal.py`: the actual trailing 30 days at a
pinned block, replayed for 360 days plus exit through the timed model, 16 seeds, complete claims
only, no annualization. Purchasers respond at recorded delays but bid inside the settlement window,
because a vault pack's bid beats keeping it and the vault reclaims at expiry; recorded late answers
and keeps are diagnostics that show a large upside the gate does not count. Result at 26,450,200:
fails at the 2 ETH canary (median −5.3%), passes at 6.8 and 20 ETH. Shared journal cost is the cause.

## D73. One release identity and a signed gate before any public broadcast (engineering, 2026-11-19)

`deploy/release-manifest.json` binds sources, toolchain, normalized runtimes (with the library's
CREATE2 address), values, keeper image inputs and evidence. `script/deploy.sh` simulates freely and
broadcasts to anything but a local Anvil only when `script/release.py check --broadcast` passes,
including the owner's ssh signature over `docs/release/acceptance.json`; it then runs the onchain
postflight. This replaces `I_AM_THE_OWNER=yes`. Keeper configs keep a zero VAULT that the
entrypoint refuses until `release.py keeper-config` writes a postflight-checked address.

## D74. Keeper image toolchain stays Foundry 1.8.1 (engineering, 2026-11-19)

All tests and rehearsals of this candidate ran with Foundry 1.8.1, the version the image installs;
the image itself passed the fork rehearsal in CI. Earlier 1.9.0 receipts remain valid for their
contract gas: bytecode depends on solc settings, not on the Foundry version. `FOUNDRY_DIR` is pinned
because the current installer otherwise writes to `~/.config/.foundry`.

## D75. A scan of the vault's own positions replaces the global journal for small vaults (engineering, 2026-11-19)

The D72 gate failed at the 2 ETH canary (median −5.3%, 9 of 16 seeds lose). Root cause, reproduced
exactly from `sim/formal.py`: 1.203 of the 1.525 ETH a year of routine keeper pay bought on-chain
reads of FWA's global acquisition journal: 92,120 records a year were read at the 22,000 quoted gas
each (16.6k marginal measured), whatever the vault's size. The journal proves that no own selection
was missed, but it costs in proportion to FWA's global activity, not to the vault's own work.

`src/ScanLib.sol` `rebase` proves the same completeness by reading `listings(id)` for every open
position the book holds Active (29,337 gas each, measured, `docs/receipts/scan-gas.json`), selecting
in allocation order each one FWA shows Allocated or Settled (at most 16; otherwise no state change and
the journal runs), then moving the cursor to `nextSequenceToProcess`. It is sound because FWA allocates
a listing only inside `processAcquisitions` while advancing that counter, and an Allocated listing can
only become Settled. VaultLib takes it automatically whenever `open * Q_SCAN <= min(backlog, 128) *
Q_JOURNAL`, so it never costs more than the next journal batch and stays inside that batch's gas
envelope; vaults with more than 93 open positions keep the journal. `Q_SCAN = 30,000`. The scan
component is paid only when the call applied an own selection or is the required checkpoint tail, so
a cycle's terminal work split into later calls cannot earn a second scan. PackVault is unchanged; the
read loop lives in a second library only for EIP-170 size (VaultLib 24,440 bytes, ScanLib 1,935).
`script/release.py` derives both CREATE2 addresses and checks the VaultLib→ScanLib link.

Keeper (`keeper/policy.py`): a scan vault does no work for FWA's global activity alone. It waits for
each own selection to settle or expire and then selects and resolves it in one paid call; other
terminal and cleanup work rides along with the next paid scan unless holders are waiting, a checkpoint
is due or the vault is winding down. In a checkpoint window the paid scan runs first and terminals
follow without a scan.

Unchanged: the payment formula (quoted gas x min(basefee + 0.05 gwei, 0.5 gwei) + 0.00002 ETH per
work unit, no premium), ceilings, budgets, the canary's D71 refill (0.01 ETH a day; main's 0.0008 is
assessed as an alternative), essential pay disabled (D64), liabilities, the trailing-30-day gate.
Results and limits: `docs/KEEPER-ECONOMICS.md`.

## D76. The owner moves only by two-step handover and cannot be renounced (owner, 2026-11-20)

`owner` was immutable, so moving the role to a hardware wallet or Safe needed a new vault and every
holder exiting. PackVault now inherits Solady `Ownable` (already a dependency) and allows only its
two-step handover: the new key calls `requestOwnershipHandover`, then the current owner calls
`completeOwnershipHandover` within 48 hours (a Safe makes the request as one of its own
transactions). One-step `transferOwnership` and `renounceOwnership` always revert: either could
leave the vault with no controllable owner (a mistyped or uncontrollable address, or zero), and then
nothing could ever pause, stop keeper pay or wind down. The constructor rejects a zero owner.
`owner()` keeps its ABI; checks use Solady's `onlyOwner`, so non-owner calls revert `Unauthorized()`
instead of `NotOwner()`.

What it solves: planned migration, and moving away from a key suspected of exposure before an
attacker uses it. It does not recover a key already used by an attacker (the attacker can hand the
role on, and nothing reverses that) or a lost key; there is no second recovery authority.

Unchanged: the owner's powers (D58, D59): parameters within bytecode bounds, keeper policy, pauses,
wind-down; it still cannot take assets, and the keeper-pay bound (current budget plus 0.025 ETH a
day) moves with the role without growing. Solady's handover functions are `payable`; ETH sent with
them becomes holder NAV at once and is not refundable, exactly like a plain transfer to `receive()`.
`script/release.py postflight|keeper-config <vault> <values> [owner]` takes the current owner after a
handover. PackVault runtime in the manifest. Tests: `ForkVaultLifecycle.test_ownerHandoverOnly`,
`test_zeroOwnerRejectedAtDeploy`.

## D77. One strategy implementation, two ownership models (owner brief A3, 2026-11-21)

**Chose:** the strategy lives in three linked libraries that run by DELEGATECALL in the calling
account: `StrategyLib` (build, list, sync, unlist, liquidate, harvest, burn, receipt
identification, keeper pay entry), `VaultLib` (position book, live FWA economics and backing rule,
journal, settlement, recovery, keeper pay) and `ScanLib` (own-position scan). The split is for
EIP-170 only. `PackAccount` is the one abstract operating surface both accounts inherit: the same
entry points, views, receive hook, NFT hook, parameter and policy setters, two-step ownership. The
concrete account defines only what it owes: `_free`, `_idle`, and the facts only it knows
(`_checkpointMode`, `_shortfall`, `_need`). `PackVault` adds shares, escrow, checkpoints,
redemptions, distributions and wind-down; `PackManager` adds owner withdrawals and exit mode.
**Why:** a library executing against the caller's storage keeps each account the FWA depositor and
sole owner of its assets; a central strategy contract would have to custody or be trusted by every
account. One shallow base removes the otherwise duplicated 40 entry points and views; no deeper
hierarchy, no plugin system.
**Isolation argument:** the libraries have no state and no withdrawal path. ETH leaves an account
only as FWA backing for its own listing, the exact ShapePacks mint price, or keeper pay capped by
that account's quote, budgets and `freeEth()`. NFTs leave only to FWA on listing, to ShapePacks on
redeem, or by the owner functions in `PackManager`. Library functions that change state revert when
called directly (Solidity's library call guard). Receipts are matched by backing inside the
receiving account's own book; FWA pays the depositor of record, so one account cannot be credited
with another's ETH.
**Size:** PackVault 16,970 bytes (was 24,136 at main), PackManager 12,453, StrategyLib 12,758,
VaultLib 23,409, ScanLib 1,935, factory 1,365, KeeperPolicyV1 216.

## D78. Personal managers are ERC-1167 clones from a permissionless factory (2026-11-21)

**Chose:** `PackManagerFactory` deploys one `PackManager` implementation in its constructor and
creates each manager as a Solady 44-byte clone, initialized in the same call with the chosen owner,
bounded parameters (same `checkBounds` as the vault) and the factory's default keeper policy, and
funded with the call's ETH. The implementation sets its own `_initialized` in its constructor, and
`initialize` accepts only the factory, once. The factory has no owner, no fee, keeps no ETH and has
no function that reaches a manager after creation. Discovery: `ManagerCreated` event,
`managerAt(i)`, `managerCount()`, `isManager(a)`.
**Measured:** `create` 474,076 gas (clone, initialize, approval, discovery storage) against roughly
3 million for a full 12.5 KB deployment; the clone's extra DELEGATECALL keeps FWA's pushed payments
inside the 100,000 gas stipend: keep payment 52,363 gas, cold kick refund 35,148 gas
(`ForkManager.t.sol`).
**Owner controls:** withdraw any ETH, withdraw idle packs, rescue untracked NFTs, pause listing,
exit mode (reversible: unlisting and liquidation become essential and permissionless), parameters
and policy within bytecode bounds, two-step handover only (D76 applies). Stopping paid automation is
setting both budgets to zero; the owner can run any operation unpaid.
**Not built:** per-owner manager index (ownership moves; the event and `isManager` suffice), an
upgradeable implementation, per-manager keeper or policy deployments.

## D79. Direct-mint build-and-list replaces bulk mint, split and restock (owner brief A3.31)

**Chose:** `build(units, proposals, minPay)` calls `ShapePacks.createPack([], mintCounts)` with the
fewest Shapes for the pack value (0.06 ETH = one 0.05 + one 0.01: two paid primary mints, 0.002 ETH
at today's 0.001 fee) and lists each new pack in the same transaction, validating each proposal
after the previous admission. Returned packs are relisted with `list`, never redeemed to remint.
Removed: 0.1 ETH mints, splits, the loose-Shape stack, the Shapes approval, `restock`, `Q_MINT`,
`Q_PACK`, `Q_PACK_UNIT`, `Q_RESTOCK`, `Q_LIQ_SHAPE`. Kept: bounded recovery of oversized returned
packs. New quotes from `ForkDirectMint.t.sol`: createPack 381,427 / 534,411 / 626,504 gas for one /
two / three Shapes, so `Q_BUILD_PACK` 300,000 + `Q_BUILD_SHAPE` 130,000 per Shape; build call base
300,000 (raised from 280,000 after `ForkMaxBatchGas` billed a one-pack build at 1,667,619 gas, 2,619 over the old 1,665,000 quote; eight packs bill 9,466,009 against 11,380,000); two work units per built and listed pack.
**Why:** the old route quoted about 1.0M gas per 0.03 ETH pack before listing and left idle packs
and loose Shapes between transactions; minting into the pack is one call per pack and needs no
intermediate inventory. Creator revenue per new pack rises from 0.0003 to 0.002 ETH because each
Shape pays its own fee.

## D80. Backing makes keeping the pack the purchaser's best choice (owner brief A3.32)

**Chose (VaultLib.edge):** backing B = floor to 10,000 wei of (P − 0.0003 ETH − 160,000 gas ×
gasCeiling) × 10,000 / max(ETH bid rate, token bid rate), both read live from FWA (9,000 and 9,150
today). At P = 0.06 and the 0.5 gwei ceiling, B = 0.06515847 ETH (ratio 1.086): a purchaser keeping
the pack holds 0.06 against at most 0.05962 from either bid, 0.0003 ETH more after redeeming at the
ceiling price (`ShapePacks.redeem` of the pack measured at 157,023 gas). It lists only when B ≥
P / 0.95 (a keep never loses at FWA's immutable 5% settlement-fee cap), k ≥ 1 + minEdge, a bid
cycle B (k − 1) and a keep cycle B (k − s) − P each clear the cycle's keeper pay, and for a new
build the keep cycle also repays the build including its mint fees. Otherwise the account stops
building and listing; sync, exits and withdrawals are unaffected. The token bid's enable flag has no
getter, so its rate always counts (conservative).
**Supersedes:** D62's floor max(P / d, P / (1 − s)), which made bids the purchaser's best choice,
and its gas-optimal and spare-capital terms (they raise B, which would break the keep incentive).
**Consequence:** a keep now returns B (1 − s) for a pack worth P: +0.0045 ETH per keep after the
replacement build at canary gas, more than the bid cycle's B (k − 1) = +0.0025 ETH. Expiry
resolution reclaims backing (B (1 − s) ≥ P), which is also a keep.
**Constraints the owner should know:** the purchaser's redeem gas is priced at the routine
`gasCeiling` (a stable parameter, so proposals stay inside the 10,000 wei identifier band), so a
0.06 pack lists only while gasCeiling is below about 11.9 gwei: raising the ceiling for keeper pay
above that stops new listings. The 0.06 recipe also lists only while FWA keeps ShapePacks
oracle-exempt (backing 0.065 exceeds the floor cap of about 0.036), and only while FWA's best bid
stays below about 94.4% (FWA may set its discounts up to 95%). In each case building and listing
stop; sync, exits and withdrawals do not.

## D81. No shared exposure registry (owner brief A3.33)

PR #1's `FWAExposureRegistry` is not adopted. FWA's own formulas make a listing's expected fees
before selection k B whatever the number of listings (each fee splits over N listings, selection
odds are 1/B over the sum of 1/B), so per-cycle economics, and therefore every account's admission
gate, are independent of how many listings our accounts add. What aggregate participation dilutes
is the rate: fees per listing per day fall with total listings, which lowers capital turnover and
annual return for every listing, ours and others'. A registry would add shared state, a call per
listing and coupling between accounts without changing either fact.
**Measured (`sim/unified.py`, section B):** scaling 1 ETH managers so our combined share of FWA's
selection weight rises 0.26% → 2.5% → 11% → 34% → 56% moves each account's mean return
+179% → +170% → +145% → +97% → +64%. Below about 2.5% (tens of managers, or a 20 ETH pool) the
dilution is small; above about 10% it is large. A registry would not raise anyone's return; it would
only ration admission between accounts. **Decision:** no registry at launch scale. The keeper reports
our combined share each pass; if it nears 10%, a cap is an owner decision (it couples accounts and
adds one call per listing). Per-account admission already stops any account whose cycle stops
paying.

## D82. One keeper for all accounts (owner brief A3.34)

The keeper treats the pooled vault and every factory manager as independent work accounts: own
index, state, plan, budgets and failures, one signing nonce stream per keeper address. Managers are
discovered from the factory's `managerCount()`/`managerAt(i)`, reading only new indices each pass.
No onchain coordinator. Details: `docs/KEEPER.md`.

## D83. PR #1 review: reused, replaced, rejected (2026-11-21)

Reused: direct minting through `createPack` mint counts (generalised to the 0.05/0.01 recipe and
made the only construction path); using each listing's own recorded units and backing when planning
redemption unlists (already on main as `Listing.value`/`backing`); the lesson that FWA's staging
must be checked by the returned listing status (main already reverts unless the listing is Active
and the active count rose by one). Replaced: the factory of full `PackVault` copies (each would
carry share accounting and a seed) by clones of a share-free `PackManager`; the owner-only factory
by a permissionless one; supplied-creation-code hashing (unnecessary: the implementation is deployed
by the factory). Rejected: `FWAExposureRegistry` (D81), the 300-position limit and spare-slot spread
(already superseded by A2.15), staged-listing activation (FWA has no public `activateListings`;
staged listings activate inside acquisition processing, and accounts never list while it is busy), adaptive sizing and 0.1/0.2 ETH ladders (no evidence of a
material advantage; see the recipe comparison), `sim/mint_policy_research.py` (replaced by the event
replay in `sim/unified.py`).

## D84. FWA's record, not the receipt, resolves a settlement (owner brief A4.1)

**Found:** FWA pays depositors with Solady's `forceSafeTransferETH`: a call with a 100,000 gas
stipend, and if that call fails, a `CREATE` of a contract that `SELFDESTRUCT`s the ETH to the
depositor, so the FWA transaction still succeeds (verified source, `FWAV2.sol` lines 1285 kick,
2069 keep/relist/expiry/default). If an account's `receive()` ever failed (for example after a gas
repricing pushed it past the stipend), the keep payment or kick refund would arrive with no receipt.
`_syncTerminal` then reverted `MissingReceipt` for ever: the position could never resolve, a pooled
vault's wind-down could never finish, and its NAV would count both the cash and the booked position
at any checkpoint.
**Chose:** settlement is classified from FWA's own record, which FWA writes in the same transaction
as the payment: a Settled listing whose pack is neither the account's nor owed to it
(`stuckNFTRecipient`) was a keep, relist, expiry or default and paid B (1 - s); a Settled listing
whose pack came back was a bid and paid nothing; a Withdrawn listing the book holds Active was a
kick and refunded B with the pack. Amounts are never inferred from balances. The receipt recorded in
`receive()` stays only as the checkpoint gate it already was, and a checkpoint now also proves that
every position the book holds Allocated is still Allocated at FWA (`ScanLib.requireAllocatedCurrent`),
so a settlement without a receipt still blocks pricing until it is synced. The proof reads at most
`MAX_ALLOCATION_SCAN` = 32 allocation queue entries from the head and otherwise refuses with
`CatchUpFirst` at a constant 31,763 gas, so pricing never scans allocation history (review of
958b924: the first version walked every tombstone behind an unresolved allocation). The queue from
the head holds only allocations newer than the oldest unresolved one, and a checkpoint already
refuses any allocation older than FWA's settlement window (`SyncFirst`), so a refusal lasts at most
one window plus a sync. Checkpoint pay adds 6,000 gas per entry read and 30,000 per FWA listing read
(32 entries with one read measured 186,175 gas against a 222,000 quote; `ForkAllocationProof.t.sol`). Sync is permissionless and resolves each listing exactly once (its position retires).
**Bound with the real receiver:** too little transaction gas cannot force an unrecorded payment: when
`receive()` runs out of gas inside the call, FWA keeps at most 1/64 of it, far below the 32,000 gas a
`CREATE` needs, so the whole transaction reverts (`test_lowGasKeepNeverForcesAnUnrecordedPayment`).
**Residual:** a kick refund forced in while its receipt is missing is not caught by the checkpoint
gate (that would need a read of every Active listing per checkpoint). It needs FWA to lift the
ShapePacks oracle exemption and `receive()` to fail at the same time, and lasts until anyone syncs the
kicked listing, which the keeper does on FWA's `ListingKicked` event. In that one case the pool's
NAV correctness, not only liveness, relies on the keeper; the independent review rated it low and the
full gate (a read of every open listing per checkpoint, up to 300) costs more than it protects.
**Tested (fork, real FWA forced-send):** `test/fork/ForkReceiptRecovery.t.sol`.

## D85. The purchaser's gas is a fixed bound, not the keeper's ceiling (owner brief A4.3)

**Found:** the keep incentive priced the purchaser's 160,000 gas redeem at the account's routine
keeper gas ceiling, so raising keeper pay lowered backing and stopped fresh listing above about
11.9 gwei even when purchasers' costs had not changed.
**Chose:** `PURCHASER_GAS_PRICE = 2 gwei`, a bytecode constant: B = floor_1e4((P - (0.0003 ETH +
160,000 x 2 gwei)) x 1e4 / max(ETH bid, token bid)). For 0.06 ETH, B = 0.06489617486338 ETH. Keeping
beats FWA's best bid for any purchaser paying up to 2 gwei; above that a purchaser may prefer the bid,
which the bid-outcome gate already requires to be profitable. Backing no longer moves with keeper
settings, so a proposal stays valid across parameter changes. No oracle, role or setting is added.
Keeper pay keeps its own ceilings.
