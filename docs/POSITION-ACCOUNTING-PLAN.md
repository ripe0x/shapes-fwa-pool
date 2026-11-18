# Position accounting without a portfolio scan

## Decision and scope

Use one vault with running accounting totals. Read a position when it changes. Process the deployed FWA contract's new acquisition records in sequence. Price shares from those totals after proving that all relevant changes have been accounted for.

The current 300 position ceiling exists because checkpoint pricing reads every open position and every idle pack. Removing that ceiling requires removing those scans from required runtime paths. Dividing the same scan across transactions would preserve unnecessary work and introduce snapshot consistency problems.

This document concerns position accounting only. Mint policy, fee revenue, pack size selection, distributions, and the broader architecture cleanup remain outside this work.

Status: the isolated running ledger milestone has now passed. The accounting kernel matches an independent reference through 40,960 randomized steps and at 301, 1,000, and 10,000 bookkeeping positions, with identical valuation gas. Twenty five distinct real FWA fork tests cover the adapter and lifecycle. See `POSITION-ACCOUNTING-MILESTONE.md` for exact evidence and limits. Production contracts remain unchanged; production share flow integration and removal of the 300 position ceiling are the next milestone.

## 1. Preserve value instead of rediscovering it

Let P be a pack's redeemable shapes backing and B its posted FWA backing.

Maintain a total of tracked shapes backing across loose shapes, idle packs, active listings, allocated listings, and packs owed back by FWA. Moving a pack between these states does not change P.

Maintain active posted backing separately. Only genuinely active listings contribute B.

The resulting valuation is:

```text
NAV = free actual eth
    + tracked shapes backing
    + active posted FWA backing
    + aggregate pending active fees
    + live FWA fee credit
```

Free actual eth excludes pending deposits, holder claims, redemption reserves, distribution reserves, and the checkpoint charge pool, as in the current accounting. Do not add uncredited crown rewards or change other valuation policy in this work.

| Change | Accounting action |
| --- | --- |
| Mint shapes | Add their redeemable backing to tracked shapes backing. Paid mint fees leave cash and remain a real cost. |
| Assemble or list a pack | Keep its P unchanged. Listing exchanges cash B for active backing B. |
| FWA selects a listing | Remove B from active backing and remove that listing from the active fee aggregates. Keep P and mark the allocation. |
| Buyer accepts the eth or token bid | Keep P. The returned pack, or the claim to its return, has the same conservative value. |
| Buyer keeps or relists the pack | Reconcile the identified eth receipt and remove the old P. The cash is already in the actual eth balance. |
| FWA kicks an active listing | Reconcile the identified receipt, remove active B and active fee membership, and retain P. |
| Vault withdraws a listing | Update the same totals within that call. |
| Redeem a pack or loose shape | Remove its backing from the tracked total while the actual cash balance increases. |

For an unresolved allocation, P must be a valid floor under every allowed settlement fee. Require B >= ceil(P * 10000 / 9500), because the deployed FWA caps the ordinary keep fee at 5%. The existing requirement that the buyer's cash bid cover P already implies this bound when combined with FWA's 95% maximum cash settlement rate. This does not require fixing all packs at 0.03 eth.

A separate cached idle inventory value supports redemption liquidity estimates. It changes when individual packs enter or leave usable inventory. An unsynchronized bid return can understate immediately usable inventory or overstate allocated exposure, but does not overstate NAV.

## 2. Prove selection completeness with FWA's journal

The deployed FWA exposes an ordered acquisition sequence:

* `lastIssuedSequence`
* `nextSequenceToProcess`
* `requestIdAtSequence(sequence)`
* `acquisitions(requestId)`, including the selected listing ID

Initialize a local cursor at the current processed prefix when the empty vault is deployed. Process subsequent completed entries in order, using a caller supplied maximum count. Skip refunded acquisitions and selections belonging to other depositors. For one of our listings, apply the selection transition exactly once.

The cursor proves completeness. A keeper cannot omit an unfavorable selection by supplying a selective list of our changed IDs.

This does require reading each new global FWA acquisition record once, including acquisitions that select someone else's listing. FWA does not expose a separate complete journal for each depositor. Work therefore scales with new global acquisition activity, plus our other changed positions. It does not scale with our unchanged inventory.

Keep the existing blackout and drained acquisition queue requirements for checkpoint pricing. Also require the vault cursor to equal FWA's completed prefix.

## 3. Identify unsolicited settlement and kick payments

The acquisition sequence does not record oracle kicks. FWA's plain eth transfer also omits the listing ID. The narrow adapter proposed here gives every outstanding ordinary listing a unique backing amount, in multiples of 10,000 wei.

For settlement fee s in basis points, an ordinary keep pays exactly:

```text
received = B * (10000 - s) / 10000
```

Because B is divisible by 10,000, the receiver can invert this formula without rounding. A kick returns exactly B.

When the immutable FWA address sends eth, the vault checks at most two backing lookups:

1. The backing decoded from an ordinary keep payment.
2. The received amount itself as a possible kick backing.

The amount alone is insufficient. Validate the candidate against FWA state during the payment:

* A keep candidate is our ordinary listing, newly `Settled`, with no previously recorded cash receipt, no stuck nft claim, and its original pack still owned by FWA. FWA pays before delivering or relisting that pack.
* A kick candidate is our newly `Withdrawn` listing with no previous receipt.

Record the exact listing ID and receipt outcome immediately. Increment an unreconciled receipt count. Emit an event for keeper discovery. A keeper later supplies the changed IDs, and the contract verifies and consumes each receipt once. Checkpoint requires the count to be zero.

There is no need for an additional onchain array of pending receipts. The mapping and count prove completeness; events provide discovery.

Vault initiated withdrawals and fee claims use a narrowly scoped operation flag so their known receipts are accounted for by the calling function. Unrelated eth gifts remain cash donations and must not create a false position transition.

The keeper proposes an unused backing within the ordinary economic and oracle bounds. The contract verifies divisibility, uniqueness, and those bounds in constant work. Do not search for a free tag in an onchain loop or allocate a fixed tag range that creates another arbitrary position ceiling. One thousand consecutive 10,000 wei tags span only 0.00000000001 eth. If an economic price interval has insufficient room, select another valid proposal or wait; never bypass its price constraints.

### Required receipt invariants

1. Reject FWAIR classification at listing admission for this ordinary strategy. Its snapshotted zero fee has different receipt rules.
2. Require a newly created listing to be Active. Do not introduce an untracked staged activation path.
3. Keep each backing lookup reserved until the old position is fully reconciled.
4. Retire an old bid return's lookup before its pack can be relisted, redeemed, or transferred. Otherwise old terminal state can resemble a new keep, or a burned pack can make an ownership read revert.
5. Record a receipt even if the acquisition cursor has not yet processed that position's selection. Consume it only after the selection transition has been applied. If a bounded journal batch has not reached a supplied terminal ID yet, defer that ID instead of reverting the completed prefix work.
6. Do not delete a selected position's identifying data before its acquisition entry has been processed.
7. Clear and reuse a backing atomically so it can identify only one outstanding position.
8. Exclude `stuckNFTRecipient != 0` from the keep candidate. A failed bid return can otherwise resemble a keep before delivery.

FWA uses a 100,000 gas eth receiver stipend and can force an eth transfer if the receiver fails. This makes receiver reliability a release gate. Its complete worst path must fit the stipend. Insufficient transaction gas must either record the receipt or revert the entire FWA transaction. No successful payment may bypass the ledger through the forced transfer fallback. Do not add gas based early exits or catch and ignore a failed required getter.

Prepare a nonzero receipt storage slot when the position is created, and store the pending count with a permanent bias of one. Receipt processing then changes existing nonzero slots. Every live backing lookup must point to initialized receipt storage. Retire the lookup before clearing its receipt slot, and preserve the count bias when consuming receipts. The initial probe without this preparation failed the difficult kick case because the receiver exceeded the stipend; FWA committed the cash transfer without recording a receipt. This preparation is therefore a correctness requirement, not optional tuning.

## 4. Aggregate active fees exactly

FWA applies one shared fee accumulator to every active listing. Its individual fee calculation is max(0, A - debt), where A is the floored accumulator.

Store:

* n, the active listing count
* D, the sum of active fee debts
* `countByDebt[d]`, the number of active listings with debt d

Update these only when a listing enters or leaves the active set, or when the vault harvests or reprices that listing.

The keeper supplies one tracked Active listing as a witness. Read its live debt d and pending fees p.

If p > 0, A = d + p, and:

```text
aggregate pending fees = n * A + countByDebt[A + 1] - D
```

The correction is necessary because FWA writes the ceiling of its accumulator on activation and the floor on harvest. Monotonicity ensures every active debt is at most A + 1, so the formula is exact.

If p = 0, accept zero total fees only when:

```text
countByDebt[d] + countByDebt[d + 1] == n
```

Otherwise use an older listing with positive pending fees. A suitable witness always exists. When n is zero no witness is required.

Read `feeCredit(vault)` separately. FWA already aggregates fees from listings removed from its active set into that credit. This preserves fees earned before a new depositor joins, without harvesting or reading every listing.

The arithmetic has passed independent exhaustive and randomized checks. That supports this formula; it is not a substitute for integrated accounting tests.

## 5. Preserve allocation safeguards with an ordered queue

Append our allocations while processing the acquisition journal. Allocation timestamps arrive in nondecreasing order.

Maintain allocated exposure as a running sum. Mark terminal allocations as resolved when processing their changed IDs. Advance a queue head past resolved entries in bounded maintenance calls.

Checkpoint reads only the oldest unresolved allocation. That one timestamp determines whether any unresolved allocation has passed the current global settlement window. A heap or a portfolio scan is unnecessary.

Bid returns can remain conservatively classified as allocated until their individual IDs are synchronized. This can require extra cleanup before an exposure or expiry check passes, but does not make the NAV too high. Do not require every allocation to settle before allowing a checkpoint.

## 6. Constant work checkpoint

The final checkpoint verifies:

1. The existing blackout and drained FWA request queue conditions hold.
2. The acquisition cursor has caught up.
3. There are no unreconciled identified cash receipts.
4. The allocation queue head is current, and no unresolved allocation is expired.
5. The existing allocated exposure bound holds.
6. One valid active fee witness establishes aggregate pending fees, when needed.

Then calculate NAV from the stored totals and live cash and fee credit, and execute the existing deposit and redemption pricing.

Catchup calls may be split across transactions. If more activity arrives, process its new records. Previously completed work is retained. There is no portfolio scan to restart.

## 7. Implementation sequence

### Gate 1: validate the FWA adapter in isolation

Use the existing deployed FWA and pack contracts in fork tests. Verify a cold ordinary keep and a cold kick whose amount first matches an old settled bid candidate. Measure receipt gas, and test low gas boundaries for complete recording or atomic reversion. Cover fee changes, fee zero, fee 500, relisting, default resolution, gifts, failed nft delivery, tag retirement, and reuse.

The isolated probe is research code. Passing its tests does not complete the vault integration.

### Gate 2: connect running totals to the existing lifecycle

Add the cursor, receipt handling, aggregate balances, active fee arithmetic, and allocation queue to the one vault. Enforce the ordering rules above. Keep the existing full valuation logic only in the test harness as an independent reference.

### Gate 3: prove accounting equivalence and scaling

At 301, 1,000, and 10,000 positions, compare the incremental valuation with a full reference valuation to the wei after randomized changes. Check the aggregate fee correction separately at rounding boundaries. Include selections and settlements arriving before their earlier bookkeeping is processed.

Verify these properties:

* More unchanged positions do not increase checkpoint work.
* Omitted journal entries or receipts prevent pricing.
* Replayed IDs and repeated calls cannot change accounting twice or earn duplicate keeper pay.
* Bid returns and stuck claims retain P without requiring an inventory scan.
* A keep followed by a gift cannot be attributed to another listing.
* Catchup can span blocks and survive new activity without restarting.
* Deposits, partial redemptions, and wind down preserve existing protected balances.
* Deployed runtime bytecode fits its limit.

### Gate 4: remove the obsolete ceiling and its dependencies

Delete the 300 constant, the configured maximum position count, admission checks based on that count, and runtime calls to `valueOpen` and `valueIdle`. Replace idle valuation in redemption liquidity estimates too. Remove any spare slot calculation that exists only because positions had a ceiling. Replace the checkpoint quote's per position component with measured fixed checkpoint work, and separately quote verified bounded catchup work.

Keep per call work limits. They bound transaction gas and do not limit total positions. Use paginated getters and event based keeper state so a full array response does not become a new operational dependency.

All unrelated work remains paused until these gates pass.

## Current probe results and remaining proof

The revised probe passed all 12 tests. Measured receiver logic used 44,740 gas for a cold keep and 67,737 gas for a cold kick that first checks a false settled bid candidate. Including a conservative 3,000 gas instrumentation allowance gives 47,740 and 70,737, respectively, below FWA's 100,000 gas stipend.

The suite covered ordinary keep fees of 0, 100, and 500 basis points; buyer relisting; depositor resolution after the settlement window; a cash bid; controlled fee collection and withdrawal; unrelated protocol and external eth gifts; and the ambiguous kick lookup.

Two gas sweeps tested 99 call limits in total. The keep sweep tested 40 limits from 20,000 through 800,000 in 20,000 increments, with 22 atomic failures and 18 recorded successes. The kick sweep tested 59 limits from 20,000 through 600,000 in 10,000 increments, with 39 atomic failures and 20 recorded successes. Every successful tested payment was recorded. These sampled limits are evidence, not an exhaustive proof of every possible gas amount.

The original receipt probe alone does not implement the ledger. The subsequent `IncrementalFWA` and `IncrementalLedger` prototype now covers acquisition ordering, receipt consumption, lookup retirement and reuse, later fee changes, nft gifts and burns after a keep, differential valuation, and model scale tests. Owed claims are covered in the pure model; failed delivery was not manufactured on the real fork. Production share flow integration remains outstanding, and its exact receiver must be measured again. The production 300 position limit has not yet been removed.

Reproduce the adapter suite with:

```sh
forge test --rpc-url https://mainnet.gateway.tenderly.co \
  --match-path test/research/ReceiptIdentity.t.sol \
  --fork-retries 10 --fork-retry-backoff 1000 \
  --compute-units-per-second 100 -vv
```

The successful run used Foundry 1.9.0 and Solidity 0.8.30. Its output is recorded in `docs/receipts/position-accounting-probe.txt`.

## Practical limit and evidence

The intended result is no arbitrary position count ceiling in this vault. Creation and actual changes still consume gas and require capital. The deployed FWA itself has a finite active tree capacity of 2^32, far beyond the current 300 limit.

Code reviewed:

* Current repository branch at `e21a69a71a66c01fdf246b68d796ae69aa951fb4`: `src/PackVault.sol` and `src/VaultLib.sol`.
* Isolated probe based on main `063b6c7f148efdbf0f5770b97fb42e16b19ba467`: `test/research/ReceiptIdentity.t.sol`.
* Verified deployed FWA source at `0x958C41181182e76F221331b2755b77D9e1426A98`, including acquisition sequencing, settlement order, kicks, fee accounting, and `SafeTransferLib`.
* Verified shape pack contract at `0xf21514B090Da7dF4390803497d6ae673801E5cA7` and fixed FWA rewards module.

Source locations:

* https://github.com/ripe0x/shapes-fwa-pool
* https://etherscan.io/address/0x958C41181182e76F221331b2755b77D9e1426A98#code
* https://sourcify.dev/server/v2/contract/1/0x958C41181182e76F221331b2755b77D9e1426A98?fields=sources,runtimeMatch,creationMatch
