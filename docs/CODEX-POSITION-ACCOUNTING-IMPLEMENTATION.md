# Codex implementation prompt: remove the position ceiling

Implement the next milestone in https://github.com/ripe0x/shapes-fwa-pool: integrate the proven incremental position accounting into the existing production share vault and remove its arbitrary 300 position ceiling.

The accounting design is settled. Proceed with implementation, testing, and a reviewable branch. Resolve ordinary engineering choices yourself. Raise a question only if new evidence requires changing an explicit product decision or exposes a blocker you cannot resolve within this scope.

## 1. Baseline and authority

Read `AGENTS.md`, `OWNER-REQUIREMENTS.md`, `docs/DECISIONS.md`, `docs/POSITION-ACCOUNTING-PLAN.md`, and `docs/POSITION-ACCOUNTING-MILESTONE.md` before editing. Read the research source and its recorded test outputs.

Verified starting references:

* `main`: `063b6c7f148efdbf0f5770b97fb42e16b19ba467`.
* `research/incremental-position-accounting`: research proof commit `3b9cd65b192b9e54da665effa03eaff34dff290d`, containing the model, real FWA adapter, tests, and milestone report. Later documentation commits may follow it.
* `research/mint-revenue-adaptive-sizing`: earlier draft at `e21a69a71a66c01fdf246b68d796ae69aa951fb4`, containing factory work that is outside this milestone.

Fetch current references and inspect any subsequent changes. Create a new integration branch from `origin/research/incremental-position-accounting`. Preserve valid newer work and unrelated local changes. Do not broadly merge the earlier factory draft.

The owner decisions in this prompt supersede older proposals for factories, shared exposure contracts, different mint policy, or a fixed 0.03 eth pack value. Update contradictory current guidance when implementing, while retaining historical evidence as historical evidence.

## 2. Outcome and scope

Deliver one production vault with one capital pool and one authoritative accounting book. Required valuation and checkpoint work must be independent of the number of unchanged positions. Maintenance must process new external activity and specific changed positions in bounded batches.

Remove the arbitrary total position ceiling and all dependencies that recreate it. Keep transaction work limits, capital requirements, oracle constraints, allocated exposure limits, and existing economic protections. There is no promise of infinite protocol capacity or free maintenance.

Preserve these product decisions:

* Paid primary shapes mints generate the owner's revenue. Keep their fees and the current mint and pack construction behavior.
* Preserve current pack sizing rules. The research fixture's 0.03 eth packs are test data, not a production sizing decision.
* Preserve depositor pricing, redemption and distribution rules, holder reserves, claims, cancellation, dead shares, high water marks, and wind down.
* Preserve permissionless maintenance and the separate replaceable keeper payment policy, including the vault's caps on its offers.

Do not add a factory, sharding, multiple vaults, an external asset accounting service, or a shared exposure contract. Do not implement adaptive sizing, a broader mint strategy, distribution redesign, buyer participation, or a new coin strategy. Keep existing reward token claim and burn behavior working, with zero token value in NAV.

Do not merge to main, deploy to mainnet, transact with real funds, or provide an owner signature.

## 3. Integrate one accounting book

Use `test/research/IncrementalLedger.sol` and `IncrementalFWA.sol` as proven references. Integrate their invariants into production; do not import test files into `src/`, inherit the research adapter, or maintain a second parallel position book beside the existing one.

Maintain exact running values for:

* Tracked redeemable shapes backing across loose shapes, idle packs, active positions, allocated positions, and recoverable nft return claims.
* Immediately usable idle inventory backing for liquidity calculations.
* Active posted FWA backing.
* Active listing count, total fee debt, and counts by fee debt.
* Allocated conservative value and an ordered allocation queue with bounded head cleanup.
* Acquisition cursor, outstanding backing identifiers, and initialized receipt state with an unreconciled receipt count.

Store exact wei amounts as the accounting authority. Rounded unit counts can remain strategy inputs. Keep inventory stacks or indexes where useful for bounded operations, but remove the need to rediscover inventory value by enumerating them.

Let P be redeemable shapes backing and B be posted FWA backing. Connect every production transition:

1. Minting adds the newly created redeemable backing once. Mint fees leave cash and remain a real cost.
2. Splitting shapes changes their representation. It does not create additional principal.
3. Assembling a pack moves existing backing from loose inventory into the pack without counting it again.
4. Listing preserves P and exchanges actual cash B for active backing B.
5. Selection removes B and that listing's active fee membership, preserves P, and records its allocation.
6. A cash or token bid return preserves P, including when the nft is temporarily owed back.
7. A keep removes the old P after its identified payment is accounted for. The received eth already exists in the cash balance.
8. A kick or direct withdrawal removes active B, preserves P, and accounts for returned cash exactly once.
9. Redemption removes P while actual cash arrives.

Cover the existing restock recipe, including paid shapes mints, splits, and leftover loose shapes. The prototype has no loose inventory and must not redefine this behavior.

## 4. Preserve NAV and holder accounting

Use this valuation:

```text
NAV = _free()
    + tracked shapes backing
    + active posted FWA backing
    + aggregate pending active fees
    + live FWA feeCredit(vault)
```

`_free()` must continue excluding pending deposits, redemption reserves, distribution reserves, claimable balances, and `processingPool`. Do not use the research adapter's raw eth balance as production free cash.

Do not add uncredited crown rewards or change the treatment of other assets. If checkpoint harvests fee credit first, count the resulting cash once. If credit remains unharvested, include it once in NAV and distinguish it from immediately spendable cash.

Preserve the current checkpoint ordering: price redemptions from the appropriate preflow NAV, apply eligible distributions, then price deposits from the resulting state. Preserve partial redemption indexes and every protected liability throughout maintenance, settlement, cancellation, and wind down.

Replace full inventory valuation in `_redemptionShortfall` with maintained usable inventory value. Conservative unsynchronized returns may temporarily reduce apparent liquidity or overstate allocation exposure. They must not overstate NAV.

## 5. Prove completeness with bounded journal processing

Use the deployed FWA at `0x958C41181182e76F221331b2755b77D9e1426A98` and its ordered acquisition journal: `nextSequenceToProcess`, `lastIssuedSequence`, `requestIdAtSequence`, and `acquisitions`.

Initialize the cursor at the existing completed prefix when deploying an empty vault. Process every subsequent completed global entry in order, including foreign selections and refunded records. Apply our selection transitions exactly once.

A selective keeper supplied list of our IDs cannot prove completeness. Checkpoint must verify the cursor has reached FWA's current completed prefix, alongside the existing blackout and drained request queue requirements.

Bound work per call. Retain completed progress across calls and when new acquisitions arrive between them. If a supplied terminal ID is ahead of the cursor, defer that item without reverting valid prefix progress. Keep its identifying data until the selection is applied.

A keep receipt can arrive before the vault processes its acquisition entry. Record it immediately, but consume the terminal transition only after selection accounting is complete. Stale IDs, duplicate IDs, and repeated calls must not alter totals or earn payment twice.

This design processes each new global acquisition once. It does not reread all outstanding positions each time a checkpoint is requested.

## 6. Constrain and authenticate receipt identifiers

Each outstanding ordinary listing must reserve a unique B divisible by 10,000 wei. Select a proposed amount offchain and verify it in constant work onchain.

Retain the existing live economic calculation in `VaultLib.edge`, removing only its cap dependent spread. Use this bounded engineering default for identifier proposals:

1. Calculate the existing desired backing from live economics.
2. Accept an unused 10,000 wei multiple within `(outstanding reserved backing identifiers + 1) * 10,000 wei` of that target, allowing either side.
3. Validate the actual proposal against all existing hard economic requirements: current oracle validity, buffered ceiling, minimum edge, cash bid coverage, positive cycle economics, available capital, and liquidity reserves.
4. Also require `B >= ceil(P * 10000 / 9500)`. This preserves P as the conservative allocation floor under the maximum ordinary 5% keep fee. Use correct integer rounding.
5. Preserve paid mint and build payback checks for newly created packs. Relisting returned inventory retains its existing positive cycle gate; do not require every relist to repay a hypothetical rebuild.
6. Update restock's funding checks for actual bounded identifier proposals instead of assuming every future listing uses an identical B.

Use the outstanding reserved count, not a lifetime issuance count. Release and reuse identifiers after full reconciliation. Do not search for unused amounts in an onchain loop, monotonically increase B forever, or allocate a fixed identifier range. If the economically valid interval has no available identifier, wait or choose another valid quote without relaxing the economic gates.

Reject FWAIR classification atomically at admission. Require each new listing to be our ordinary Active listing with the correct depositor, collection, pack, and backing. Reject Staged results even if a queue precheck passed. Remove obsolete staged activation support and its payment path once production cannot create that state. Preserve existing keeper operation identifiers or explicitly update all consumers without silently changing their meaning.

Apply current oracle, admission, and edge gates to new capital deployment and listing. Their failure or later parameter changes must not block journal processing, receipt consumption, settlement recovery, withdrawal, or redemption. Preserve existing exit protections, including the crown exit rule. Do not reuse admission validation to reject an existing position during recovery.

## 7. Preserve the receiver invariants exactly

FWA transfers plain eth with a 100,000 gas receiver stipend and can force delivery if its receiver call fails. Receipt reliability is a correctness gate for the exact production bytecode.

Only interpret unsolicited payments from the immutable FWA address. At most two backing lookups are needed:

1. Invert `received = B * (10000 - feeBps) / 10000` using the live ordinary fee at payment and validate the result exactly.
2. Treat the received amount itself as a possible kick backing.

Authenticate each candidate synchronously against deployed FWA state. A keep candidate must be our newly Settled ordinary listing, with no old receipt, no stuck nft recipient, and the original pack still owned by FWA during payment. A kick candidate must be our newly Withdrawn listing with no previous receipt. A matching amount alone is insufficient.

Record the identity, outcome, and payment data needed for exact later reconciliation. Emit discovery events and increment an unreconciled count. The mapping and count establish completeness; do not add an onchain pending receipt array without a demonstrated need. Checkpoint requires zero pending receipts.

Carry these invariants into production:

* Prepare nonzero receipt storage before a backing lookup becomes live. Keep the stored pending counter biased by one. Receipt recording must update existing nonzero storage, preserving the proven gas behavior.
* Every live backing lookup points to initialized receipt storage. Retire the lookup before clearing that storage.
* Retire an old bid return's lookup before its pack can be redeemed, transferred, or relisted. A burned old pack must never disrupt a later receipt, and an old settled bid must never resemble a fresh keep.
* Retain receipt data from payment time. A later fee change must not change its interpretation.
* A kept pack can be burned before synchronization. Receipt consumption must still succeed. If it is extended and gifted back, remove old P and adopt its actual current backing once after retirement.
* Keep required synchronous ownership checks strict under the lifecycle invariant. Optional later gift adoption can tolerate a burned pack. Do not catch and ignore a required receiver failure.
* Unrelated gifts remain donations and cannot fabricate position transitions.
* Use a narrowly scoped operation flag for known vault initiated fee claims and withdrawals. Do not suppress genuine keep payments from expiry resolution.
* Do not put a normal `nonReentrant` modifier on `receive()`: legitimate FWA payments occur during guarded vault operations. Preserve reentrancy protection on the external operations themselves.

Do not add a low gas early return that allows money to arrive without a receipt. At tested gas boundaries, an FWA payment must record the receipt or revert atomically. Inspect the fallback call path as well as testing it.

## 8. Aggregate active fees exactly

Use the proven debt histogram, rather than scanning listings, estimating fees, or harvesting every position before pricing.

Let `n` be active count, `D` total active debt, and `countByDebt[d]` the number of active listings at debt d. The caller supplies only a witness ID. Read its live listing state, fee debt, and `FWA.pendingFees(witnessId)` inside the transaction, and authenticate them against the cached book. Never accept a caller supplied pending fee amount.

For witness debt d and positive pending fees p, let `A = d + p`:

```text
aggregate pending fees = n * A + countByDebt[A + 1] - D
```

FWA writes the ceiling of its accumulator at activation and the floor at harvest. The correction is required. If witness pending fees are zero, accept zero aggregate fees only if `countByDebt[d] + countByDebt[d + 1] == n`; otherwise require another valid witness. No witness is needed when n is zero.

Update aggregates on every active membership or debt change. Read FWA fee credit separately and prevent double counting. If `claimListingFees` fails, retain the old debt accounting and do not compensate failed work. Invalid or stale witness data must fail safely, never become a zero fee valuation.

## 9. Retain bounded allocation recovery

Append our allocations in journal order, maintain allocated P as a running sum, mark resolved items, and prune resolved queue heads in bounded calls. Checkpoint inspects only the oldest unresolved allocation against the current settlement window and enforces the existing allocation exposure bound.

Do not require all nonexpired allocations to settle before pricing. Require any overdue allocation or stale queue head to be resolved before checkpoint.

Preserve permissionless expiry resolution and recovery of nfts owed back by FWA. The prototype's ability to reconcile already terminal positions is insufficient. Reconcile the receipts and accounting created by these production recovery operations, including keep payments during resolution. Do not import the prototype's operator restriction.

## 10. Remove every cap dependency

Search the entire repository and remove or update:

* `MAX_POSITIONS`, `Params.maxPositions`, count based restock and listing admission, keeper `max_positions`, deployment room calculations, and cap status handling.
* `_spread` and any strategy rule whose sole purpose is allocating spare capital across a fixed number of remaining slots.
* Runtime `VaultLib.valueOpen` and `valueIdle` scans, including checkpoint and redemption liquidity paths. Full enumeration belongs in an independent test reference.
* `Q_CHECKPOINT_POS`, the position count argument to request charge calculation, and cancellation logic that retains processing charges using portfolio size.
* Mandatory full array getters and every operational caller that depends on them. Expose counts, bounded getters, cursor, pending receipt count, allocation head, and recovery state as needed.

Keep unrelated controls such as capital limits, reserves, minimum edge, allocated exposure, and per call batch bounds. Do not replace 300 with a larger constant or disguise a full portfolio scan as paginated checkpoint preparation.

Explicitly bound every caller requested work loop, including restock, listing, journal processing, terminal recovery, unlisting, harvesting, token claims, liquidation, and queue cleanup. The current restock count relies on the portfolio ceiling for its bound. Calibrate replacement per call limits against complete operations at the largest permitted pack size, including the keeper's required gas margin. A bounded batch must remain usable however many other positions the vault holds.

## 11. Make ordinary keeper work incremental

The current `keeper/keeper.py::read_state` reads all open listings and fees, all idle packs, and all active token candidates. Replace those mandatory scans.

Use a small durable local event index. Reuse suitable existing code; otherwise Python's standard library SQLite is sufficient. No new hosted service is needed.

Requirements:

1. Identify the index by chain, vault, and deployment block. Consume new logs in bounded block ranges, persist block hashes, and support reorg rollback and replay.
2. Index active IDs and fee debt ordering, idle inventory, reserved backing identifiers, allocations, and receipt candidates.
3. Read aggregate contract state and hydrate only bounded candidate IDs. Pin related reads to one block.
4. Choose an appropriate active fee witness, preferably the minimum debt listing. Authenticate it onchain. Refresh and retry stale witnesses or backing collisions, including when another keeper wins a race.
5. Preserve `keeper/tx.py` restart, lost response, same nonce replacement, and reorg behavior. Confirm transaction receipt status.
6. Bound optional token claim and burn candidate reads. Do not keep a hidden full active inventory scan for tokens.
7. Keep economic decisions in `keeper/policy.py`; the simulation imports that policy.

A full historical event replay is acceptable for initial construction or repair. Normal operation must consume new events plus bounded relevant records. The index is reconstructible convenience; onchain cursor, receipt counts, and authentication remain the financial authority.

## 12. Pay for verified maintenance and preserve reserves

Processing foreign or refunded acquisition records performs necessary work without returning backing. Account for that explicitly.

Use the existing fixed quote payment system with calibrated components for completed global journal entries, our selection updates, terminal and receipt work, and bounded queue cleanup. Pay for verified completed work only. Do not reimburse measured `gasleft()`, requested batch size, duplicates, or zero progress.

Cheap foreign entries get their measured gas quote component. They must not receive the full own position sync quote or a flat work fee for each foreign acquisition. Preserve `_pay`, keeper policy offers, routine and essential ceilings, budgets, available cash checks, and `minPay`. Use essential classification where catchup is necessary for locked exits or wind down.

Fund maintenance from actual free vault cash within those controls. Keep `processingPool` for the fixed checkpoint charge. Remove position dependent checkpoint billing and calibrate the complete production checkpoint, including holder flow processing and keeper payment.

Propagate recalibrated mandatory own position journal, receipt, and terminal costs through the existing `cycleNet`, build payback, deployment and unwind quote formulas, and Python mirrors exactly once. Avoid double counting combined operations or batch overhead. Analyze foreign acquisition overhead separately in the reserve and budget model. Keep the existing charge policies while updating their measured cost inputs.

Update `reserve_need` and show that a bounded catchup batch remains affordable when deployable capital is invested. Measure foreign only prefixes, refunded prefixes, backlog, and higher gas conditions. Separate aggregate maintenance cost, which grows with new global activity, from checkpoint cost, which must not grow with total positions.

If realistic maintenance cannot fit the existing budgets and reserve policy, report the measured shortfall and a narrow proposed adjustment. Do not silently cut shapes mint fees, spend protected holder balances, create new holder charges or change their policy, or redesign the strategy.

## 13. Keep the implementation coherent

Update affected production contracts, interfaces, keeper policy and transactions, simulation, deploy scripts, parameter JSON, rehearsal scripts, fixtures, tests, and current documentation together.

Likely affected areas include `src/PackVault.sol`, `src/VaultLib.sol`, `src/interfaces/External.sol`, `src/KeeperPolicy.sol`, `keeper/`, `sim/vault.py`, `sim/reconcile.py`, `script/Deploy.s.sol`, `deploy/`, and fork and scenario fixtures. Let actual dependencies determine the final file set.

Use the existing linked library where useful to keep production bytecode within its limit. Prefer a cohesive implementation with few new abstractions. Remove superseded production code and avoid permanent compatibility layers for unused APIs. Do not increase code size limits to make a build appear deployable.

After changing `Params`, run `forge build --force` and update every constructor, ABI encoder, and parameter consumer. Keep the simulation's vault accounting aligned with production and rerun its independent reconciler.

## 14. Required acceptance evidence

Implement meaningful tests alongside the changes. Follow the repository's real fork rules: no mocked FWA, VRF, oracle, shapes, shape packs, or token pool. Use real recorded request and fulfillment replay. Do not use `vm.transact`, which loses local state. Use fresh `makeAddr("pack-vault-test-...")` actors and verify their code and balances; avoid anvil development accounts with real mainnet delegations.

Prove all of the following:

1. Production accounting matches an independent full valuation to the wei through minting, loose inventory, splitting, pack assembly, listing, selection, cash and token bid returns, keeps, kicks, harvests, withdrawals, redemption, and supported gifts.
2. Deposits, partial redemptions, distributions, claims, cancellation, dead shares, reserves, and wind down retain their intended behavior. Test favorable and unfavorable external changes around pending holder requests.
3. Missing journal work or receipts blocks pricing. Settlement before selection bookkeeping, repeated IDs, foreign and refunded entries, new entries between batches, stale witnesses, and failed harvests behave correctly without duplicate accounting or payment.
4. Receiver tests use the exact integrated production bytecode and cold relevant storage. Measure the difficult kick after a false settled bid candidate as well as keeps, fees 0 and 500, relisting, expiry resolution, later fee changes, burned kept packs, extended gifts, retired identifiers, and identifier reuse.
5. The complete receiver fits FWA's 100,000 gas stipend with headroom. Sweep low gas boundaries and require complete recording or atomic failure. Explain the remaining limits of sampled evidence.
6. Independently compare valuation and transition behavior at 301, 1,000, and 10,000 bookkeeping positions using the production accounting implementation. Show constant checkpoint valuation work and bounded transition work. Do not claim that model fixtures create 10,000 real FWA listings. Fixture setup gas must be separated from individual operation gas.
7. Every supported production operation at its maximum allowed batch fits 16,777,216 gas, including the required keeper gas margin. Runtime bytecode fits 24,576 bytes. Perform a fresh deployment through the normal linked library and deployment script path, with normal code size limits. Record deployed vault and library sizes and deployment transaction gas. Measure the final production artifacts, not only the research adapter.
8. Ordinary keeper RPC work remains independent of total unchanged inventory. Test restart, reorg rollback, index reconstruction, lost responses, another keeper winning a race, stale fee witnesses, and backing collisions.
9. Actual backing proposals obey quantization, uniqueness, economic floors, oracle ceilings, available cash, and paid mint payback checks. Test proposals near both ends of the valid interval.
10. Keeper compensation follows verified work, honors both budget classes, preserves holder reserves and `processingPool`, and funds necessary global journal progress without duplicate payment.
11. Updated Python policy tests, transaction tests, simulation reconciliation, relevant real fork suites, and the existing asset flow scenarios pass, or have precise documented blockers.

The research milestone already passed 40,960 randomized model steps and 25 distinct real FWA fork tests. It does not establish the integrated production receiver cost, bytecode size, share fairness, keeper funding, or a security audit. Use it as regression evidence and rerun affected tests.

The research tests cover owed claims in the pure model but did not manufacture a failed delivery from the real fixed nft contract. Preserve that disclosure. Test permissionless production recovery as far as the real contracts permit, document any unreachable fork scenario, and do not invent coverage or add forbidden mocks.

Use the repository's Tenderly fork settings and retries. Record exact commands, source commit or hashes, fork blocks, pass and failure counts, gas measurements, and runtime sizes. Infrastructure failures must be distinguished from passing tests.

## 15. Delivery and completion

Work in reviewable stages: production accounting and lifecycle, keeper and simulation integration, then final integrated verification and documentation. Write tests with each stage. Do not defer all holder flow testing until after the keeper rewrite.

Deliver:

1. A reviewable implementation branch with coherent commits and a prepared draft PR description.
2. A concise explanation of the accounting changes, removed code, and preserved mint revenue behavior.
3. An acceptance report with exact test evidence, production gas and bytecode measurements, keeper reserve and budget analysis, and the distinction between model scale and real fork coverage.
4. Updated current owner requirements, decisions, keeper instructions, gas documentation, system map, and asset flow artifacts where the implementation changes them.
5. A clear list of remaining launch gates, including independent review and any owner signature required by the asset flow gate. Prepare the evidence first. Do not manufacture the signature or label an unsigned gate PASS.

The milestone is complete only when the production vault has no arbitrary position ceiling, no required full portfolio valuation or ordinary keeper scan, correct holder accounting, and verified bounded maintenance. If a concrete receiver, size, accounting, or funding failure prevents that result, preserve the working branch and explain the exact failure. Do not substitute a factory, weaker valuation, or lost mint revenue to claim completion.
