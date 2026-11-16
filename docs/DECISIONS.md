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
