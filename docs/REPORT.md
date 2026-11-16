# PackVault overnight run: results

2026-11-15/16. Plan: "FWA Depositor Vault" revision 2. Decisions taken without the owner:
`docs/DECISIONS.md`. Owner requirements and proposed outcomes: `OWNER-REQUIREMENTS.md`.

## Bottom line

- **Gate (your definition): GO.** +86%/yr at 30-day volume (609/day), 1.2 gwei, tokens at zero.
- **At the current run rate it is marginal.** 7-day volume 97/day: +13.8%/yr at 1.2 gwei, +7.2% at
  1.5 gwei, break-even 1.8 gwei. Last day: 15 acquisitions.
- **Built and tested, not deployed.** One immutable `PackVault` (24,508 bytes, 68 under the limit),
  31 mainnet-fork tests plus a fork invariant suite, independent review with all findings
  resolved or documented, a reference keeper, one deploy path, and a local rehearsal.
- **Not done, needs your authority:** any mainnet broadcast (Phase 1 test vault, canary),
  external audit and legal review (Phase 5).

## Phase 0 findings

| Item | Result |
|---|---|
| Live settings | All plan Part 1 values confirmed by RPC at block 26,424,971 (`sim/snapshot-26424971.txt`) |
| Fee model | Exact integer replay of FWA's accumulator matches all 827,583 `EarningsAccrued` amounts; reconstructed totalWeight matches all 96,801 requests |
| k (lifetime fees / backing) | Theory 1.0385 live. Measured after the crown cut: 1.0424 overall, 1.0576 for 0.03 to 0.04 ETH listings |
| Volume | 96,801 acquisitions since launch; 1 d 15, 7 d 97, 30 d 609, 60 d 1,565 per day |
| Exit windows | 120 of 121 blackouts had a drained queue; 59 of 60 in the last 30 days |
| Packs on the pool | 239 pack listings already live, most at the 0.0363 cap, from 4 EOAs plus one from the ShapePacks admin address |
| Settlement mix at r 1.15 to 1.25 | 78% ETH bid, 11% token bid, 11% keep (pool-wide) |
| Gas (fork) | listNFT 651k; restock about 1.01M per pack (mint 0.1 + split + pack); withdraw 310k; checkpoint 6.09M at 150 positions, 16.08M at 400 (0.0073 ETH at 150 and 1.2 gwei) |
| mergePacks | Live on mainnet (README line 124 is stale) |
| FWA token | Contracts can sell through the v4 pool (98% round trip up to 1 ETH; cost on the sell side) but cannot transfer it: in-kind fallback impossible (D5). Income immaterial: one buyback paid 20 listings 2.5e12 wei |
| Variance | Edge is 3.85% of B per selection while each selection costs B: P(losing year) about 25% at 150 positions and 7-day volume |

## What was built

`src/PackVault.sol`: inventory (mint 0.1 Shapes, split, pack), listing gated on live FWA reads
(k, oracle cap, keep outcome must not lose, admission), sync and reclaim (better outcome when the
purchaser is silent), checkpoints only in FWA's blackout with a drained queue, internal shares,
cancellable deposits, pro-rata redemption index, high-water-mark distributions to live shares,
FWA token sale through the v4 pool with an up-only floor, keeper pay from 5% of harvested fees,
guardian stops, bounded delayed admin parameters, one-way wind-down.

## Verification

All on a mainnet fork of real contracts, `vm.fee`/`vm.txGasPrice` set, no mocks. Selections
use real VRF words: historical requests found offline, replayed as their original calls.

| Suite | Tests | Covers |
|---|---|---|
| ForkMeasure | 2 | gas table, token route, transfer lock |
| ForkVaultLifecycle | 10 | round trip with absolute amounts, kick, crown raise, stale quote, guardian, delay, cancel, pro rata, wind-down |
| ForkSelection | 4 | bid, keep, silent purchaser, pre-admission candidate; fee share to 2 wei |
| ForkTokens | 1 | real buyback, claim, sale, floor guards |
| ForkVaultAdversarial | 9 | gas ceiling, forced ETH and inflation, hostile NFT, reentrancy, distribution, all-holders-exit, max positions, TVL cap, checkpoint window |
| ForkVaultInvariant | 4 invariants | reserves covered, claims within reserves, share and value conservation (16 x 25 calls) |

Bugs found and fixed overnight: uint16 overflow in the gate; NAV overstated when balance was
below the reserve; redemption reserve 1 to 2 wei short of claims (twice: test and invariant);
distributions lost on lazy deposit conversion; dead-share distribution stranding (review L1);
division by zero after all holders exit (re-review). Keeper: reverted transactions reported as
sent, gas estimates short by keeper pay, 10-pack restock above 9.9M gas.

Rehearsal: anvil fork of block 26,424,971, production deploy script, holder deposit, keeper-only
passes to 18 listed positions (list 3 = 1.85M gas, restock 3 = 3.05M gas).

## System map

Buckets: vault ETH (escrowed deposits, redemption reserve, distribution reserve, keeper pool,
free), FWA escrow (backing of open listings), FWA fee credit and pending fees, inventory (packs,
loose 0.01 Shapes), FWA tokens (valued zero).
Flows: deposit -> escrow -> (checkpoint) -> free; free -> Shapes (mint fee to Shapes) -> packs ->
FWA listing (backing to escrow); acquisitions -> pending fees -> fee credit on removal ->
(harvest) free, 5% keeper pool; selection: bid (pack back, backing to purchaser 90% / protocol
10%) or keep (backing less 1% back, pack to purchaser); kick and withdraw (pack and full backing
back); checkpoint -> redemption reserve and distribution reserve -> holder claims; tokens ->
(sale) free; keeper pool -> keepers.

## Gaps

- Mainnet-only questions: real keeper competition and timing, gas market, checkpoint misses
  from FWA queue activity (D15), wallet behaviour. Need the canary.
- Untested: `convert` once-per-interval guard with tokens still held; keeper pay caps on
  `sync` and `unlist`; long multi-era redemption drift (invariant runs are short); behaviour at
  a block newer than 26,424,971.
- No flow-breakdown helper shared by tests, sim and live reads; per-flow absolute assertions
  live in the individual tests instead.
- Phase 5: external audit of the final bytecode, legal review, canary.

## Things that don't make sense

1. **Volume.** The gate passes on a 30-day average driven by one week; the current rate is a
   sixth of it. Owner kept the 30-day window on 2026-11-16 (D17).
2. **Competition.** About 238 pack listings at the cap already exist from four EOAs. One came
   from the ShapePacks admin address. If that is you, the vault competes with your own manual
   positions for the same fee flow.
3. **Low-backing listings are selected 1.5 to 6% less than their weight predicts** (0.02 to 0.04
   ETH buckets, 2 to 3 sigma), which also makes their measured k higher (1.0576 vs 1.0385). It
   helps the vault, but the cause is unexplained.
4. **Variance versus edge.** A year-long loss is likely enough (about 25 to 35%) that the
   product needs to say so plainly to holders.
5. **Checkpoint cost is large next to the edge.** 0.0073 ETH per checkpoint at 150 positions
   equals about five selection-cycles of edge for one position. Fine when flows are batched;
   costly if holders deposit and redeem in small, frequent amounts.
6. **Bytecode margin is 68 bytes.** Any further feature needs a library split first.
