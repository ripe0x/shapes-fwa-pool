# Allocation-burst and journal coverage

Fork base: PR 2 branch tip `f4ed47a` (`Record complete operating and signed receipt evidence`).
Closes the release-blocking transaction-coverage items the operating pass named open in
`docs/COMPLETE-OPERATING-PASS.md` line 118: a pure 128-successful-record receipt, the combined
maximum of 16 own transitions with journal and collection work, and live returned-pack keeper
discovery across restart and reorg.

The bounds under test are the ones already fixed in `VaultLib`: one `sync` processes at most
`MAX_JOURNAL = 128` global journal records, `MAX_SELECTIONS = 16` own selections (it stops before
the 17th own transition), `MAX_TERMINALS = 16` supplied terminal/funding IDs, and `MAX_PRUNES = 16`
allocation-head cleanups, each an independent bound. Every vault call must fit EIP-7825's
16,777,216 gas with the keeper's 25% padding on the exact estimate (`estimate * 5 / 4 <= 16,777,216`,
i.e. `estimate <= 13,421,772`).

## Goal 1 — more than 16 outstanding own allocations: UNREACHABLE (authentic)

A `sync` records an own selection when a journal record has status 2 and its `listingId` is one of
the vault's `ACTIVE` positions. Seventeen own selections therefore need seventeen real FWA
acquisitions, each selecting a distinct vault listing, accumulated in one journal on one fork
pre-state with the vault holding all its listings active across the whole burst and no `sync`
between them.

`sim/find_selection.py` is the only authentic way to make FWA's real VRF word select a vault
listing: it reconstructs the exact active-slot weights from real `NFTListed`/`BackingUpdated`/
`NFTAllocated` logs and reports requests where, with the vault's listings inserted, `word %
totalWeight` lands on a vault slot. A candidate is valid **only** when the acquisition queue is
empty at the request (so the vault's listings activate deterministically into known slots) and
nothing activates, reprices or leaves between the insertion and the selection.

Running that scan over the full history (`sim/out/selection_candidates.json`, summarized in
`allocation-burst-candidates.json`) yields **47 candidates across 251,713 blocks**, each a single,
queue-empty selection. The closest two are **17 blocks apart** (26,311,241 and 26,311,258), with
**different purchasers** and disrupting listing activity between them — that disruption is exactly
why `find_selection` emits them as two separate candidates rather than one chainable burst. The
busiest real day had ~11,817 acquisitions and still produced no cluster.

Why this is a hard unreachability, not a tooling gap:

> 1 → With a non-empty queue, FWA's private staging FIFO reorders activation, so the slot and
>     weight the VRF word selects against cannot be reconstructed or controlled. Vault selection is
>     only replayable with an empty queue — one outstanding request at a time.
> 2 → `vm.createSelectFork` re-forks and drops local state (AGENTS.md forbids `vm.transact`), so
>     candidates at different blocks cannot be chained onto one fork. The suite is single-fork
>     replay by design.
> 3 → No window in real history has 17 queue-empty requests, each selecting a distinct vault
>     listing, with the vault's other listings undisturbed throughout.

Reaching 17 would require inventing an overlapping-burst fork state (fabricated weights/words) that
the tooling explicitly cannot produce and that real history does not contain. Per the task's own
rule, work was stopped here rather than inventing state. The **authentic ceiling is one own
selection per fork** (`ForkSelection.t.sol`), and the contract's 16-own bound is exercised at the
boundary another way — 16 real kicked/settled receipts resolved in one `sync`
(`ForkMaxBatchGas.t.sol::test_maximumLargePackOperationsFitTransactionCap`).

This unreachability also blocks the *authentic-vault* premise shared by Goal 2's 16 own transitions
and Goal 4's ">16 vault allocations from a real vault run": no authentic PackVault fork run can
produce 17 own `ALLOCATED` positions.

## Goal 2 — largest reachable combination in one sync

**Largest authentically reached and measured:** a full 128-record foreign journal plus attached
active-fee collection in one `sync`, from `CompleteForeignJournal.t.sol` replaying real request and
VRF-fulfillment transactions (`docs/receipts/complete-foreign-journal.json`):

| Reached single sync | Records | Measured billed gas | Padded (×5/4) | Fits 16,777,216 |
| --- | ---: | ---: | ---: | :---: |
| 128-record journal (125 success + 3 real refunds) | 128 | 2,512,081 | 3,140,101 | yes |
| 128-record journal + 1 real active-fee claim | 128 | 2,621,560 | 3,276,950 | yes |

The new in-process receipt-equivalent measurement is
`CompleteForeignJournal.t.sol::test_full128ForeignJournalSyncReceiptGasFitsCap` (cold state, normal
transaction gas accounting, Tenderly mainnet fork): **2,540,933 gas**, padded `(2,540,933·125+99)/100
= 3,176,166 < 16,777,216` — ~5.3× headroom. Pay `580,200,000,000,000` wei =
`(Q_SYNC + 128·Q_JOURNAL)·0.2 gwei`, confirming one call drained all 128 records
(`acquisitionCursor == begin + 128`). (Independent of the `complete_foreign_receipts.py` local-node
figure 2,512,081; the small difference is calldata intrinsic plus the receipt-equivalent cold model.)

**The 16 own transitions cannot be added authentically** (Goal 1). Their contribution is bounded
analytically, never presented as a receipt. The gas the keeper estimates and the contract charges
for the maximal sync is its own quoted gas, `VaultLib._syncChanges`:

```
gasQ_max = Q_SYNC + 128·Q_JOURNAL + 16·Q_SELECTED + 16·Q_SYNCED + 16·Q_PRUNED (+ Q_CREDIT)
         =  85,000 + 2,816,000    + 2,880,000      + 1,920,000     +   720,000  (+   40,000)
         =  8,461,000 quoted gas
```

(The 16 terminal resolutions and any harvest claims share the one `MAX_TERMINALS = 16` argument
array — an ID is either a non-ACTIVE terminal resolution or an ACTIVE harvest claim, never both —
so the resolved count already caps that slot budget; `Q_CREDIT` is the one credit-sweep add-on
independent of the ID list.) Padded: **8,461,000 × 5/4 = 10,576,250 < 16,777,216**, headroom
6,200,966.

This quoted-gas figure is a *conservative* bound on actual billed gas: for every measured path the
quote exceeds billed gas (e.g. the 128-record journal is quoted 2,901,000 against 2,512,081 billed,
a 15.4% margin; `docs/COMPLETE-OPERATING-PASS.md` compensation table). So the maximal 128 + 16 own
+ 16 terminal + 16 prune + credit sweep sync fits EIP-7825 with the keeper's 25% pad and ~6.2M gas
to spare. **Labeled a bound, not a measured receipt.**

## Goal 3 — pure 128-successful-record foreign batch

The measured 128-record batch above (2,512,081 billed) is **125 successful foreign records + 3 real
deadline refunds**. A pure 128-of-128-success batch is bounded above by it to within ~3 cold SLOADs:
in `VaultLib._syncJournal` every journal record — success (status 2) or refund (status 3/4) — runs
the same bounded per-record path and `++processed`; a foreign status-2 record adds only one
`positions[listingId].value` SLOAD over a refund (~2,100 cold each). So
`pure-128-success ≈ 2,512,081 + 3·2,100 ≈ 2,518,381` billed (padded ≈ 3,147,976 < 16,777,216). The
per-record *quote* (`Q_JOURNAL`) is identical for both, so the signed payment basis is unchanged.

Producing a *new* fixture of 128 consecutive status-2 completions is more than modest work and was
not done: it needs the full FWA log archive (`sim/data/fwa.sqlite`, rebuilt only by the slow
`sim/ingest.py`) or hand archaeology over a busy day's `AcquisitionRequested`/`AcquisitionProcessed`
hashes to locate 128 consecutive refund-free completions whose VRF words all select foreign
listings while one vault witness stays Active — the same reason the existing fixture settled for
125 + 3. The gas question it would answer is already bounded above by the measured mixed batch.

## Goal 4 — keeper discovery across more than 16 allocations

`keeper/index.py`'s `EventIndex` already hands the keeper bounded candidate classes (≤16 per class),
and `keeper/test_index.py::discovery_tests` already proves >16-allocation discovery, independent
expiry quota, upgrade replay, restart, prefix rollback, retirement and optional canonical-hash
repair — all on authentic mainnet allocation/bid records (`keeper/fixtures/returned-events.json`,
18 real allocations per row from one real depositor).

Added `keeper/test_index.py::rotation_tests` to close the specific gap the operating pass named
(live returned-pack discovery across restart and reorg across successive passes). Using the same 18
authentic mainnet allocation identifiers as OWED (state 3) positions — the one candidate class that
rotates by a persisted cursor, so successive passes need no fabricated resolution events — it
asserts:

> - each `candidates(16, 16)` pass is bounded to ≤16 per class;
> - across bounded successive passes **every one of the 18 returned packs surfaces**, with a process
>   restart (close + reopen the same SQLite file) mid-rotation that preserves the `owed_after`
>   cursor in `meta`;
> - a reorg (prefix `rollback` + replay of the retained events) clears and then **restores the same
>   projection**, and the full 18-pack set surfaces again.

No fabricated events: only the recorded allocation records, plus the index's existing cursor
rotation and prefix rollback. `python3 keeper/test_index.py` passes all three suites. The authentic
>16-*vault*-allocation logs the task envisioned exporting from Goal 1's fork run do not exist
(Goal 1 unreachable), so this reuses the sanctioned discovery-fixture standard (real external
records, reconstructed vault bookkeeping) rather than inventing a vault run.

## Things that don't make sense

1. **Goal 1 as written assumes a burst that real history does not contain.** The brief expected a
   historical burst whose replayed requests select ≥17 vault listings; the full-history scan shows
   vault selection is only authentically replayable one queue-empty request at a time (47 sparse,
   non-chainable candidates). The 16-own bound is real and worth asserting, but the only honest way
   to hit it is 16 kicked/settled receipts, not 16 VRF selections. Flagged rather than faked.
2. **Goals 2 (16 own transitions) and 4 (>16 vault allocations) inherit Goal 1's blocker.** Both
   silently assume an authentic vault run with >16 own allocations. That run is impossible, so both
   are delivered with the strongest authentic substitute (measured 128+collection and a bound for 2;
   real-record rotation for 4) and the dependency is called out, not papered over.
3. **The measured maximum (2,621,560 billed) is ~6.4× under the EIP-7825 cap.** With padding it uses
   ~20% of the budget. The 16,777,216 limit is nowhere near binding for real journals; the bound
   only matters as a guard against a pathological maximal combination, which also fits with ~6.2M
   gas to spare. No sync is close to the ceiling.
4. **The foreign fixture runs at zero work fee and zero markup.** Its pay figures are gas-only, so a
   production parameter set with a work fee and markup pays strictly more than these receipts show;
   the gas measurements (which are parameter-independent) carry over, the pay numbers do not.
