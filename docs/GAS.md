# Gas and keeper compensation

## Pay rule (contract, D56/D57)

```
price    = min(basefee + maxTip, gasCeiling)                     canary: maxTip 0.05 gwei, ceiling 0.5 gwei
quoted   = base + perUnit x units (VaultLib.Q_*)                  fixed per operation, never gasleft()
envelope = quoted x price x (1 + payMarkupBps, routine only)      canary markup 0, bytecode max 10%
           + workFee x units                                      canary 0.00002 ETH, max 0.00005
offer    = active policy's quote(...)                             50,000-gas staticcall; failure = 0
pay      = min(offer, envelope, funding cap, free ETH, budget)    reverts if pay < minPay
V1 offer = quoted x price + workFee x units                        = the envelope at canary values
```

Units: packs built (restock), positions listed, resolved (sync), activated or unlisted, items
liquidated, positions harvested, 1 per checkpoint that priced flows or distributed. burnTokens is
unpaid.

Quoted gas (VaultLib, measured as billed gas on fork receipts, `sim/out/gas-quotes.json`):

| Operation | Base | Per unit | Measured billed |
|---|---|---|---|
| checkpoint | 180,000 | 32,000 per position | 221,860 (0 positions), 975,403 (23) |
| restock | 280,000 | 200,000 per pack + 2,200,000 per mint | 2,635,830 (1 pack, 1 mint), 9,121,461 (10 packs, 3 mints) |
| list | 255,000 | 530,000 | 858,779 (1), 5,790,861 (10) |
| sync | 75,000 | 75,000 | 158,661 (1), 300,695 (3 kicked); bid outcome ~181k |
| activate | 50,000 | 450,000 | ~518,000 (1) |
| unlist | 240,000 | 170,000 | 480,141 (1), 1,667,172 (8) |
| liquidate | 75,000 | 150,000 per pack, 65,000 per Shape | 250,185 (1) |
| harvest | 80,000 | 15,000 | |

Bounds on what a caller can extract:
- Pay is fixed by the operation and its completed units: gas limit, gas used and tip change nothing.
- Each base is under the measured fixed cost / 1.1, so splitting a job across calls loses money.
- A no-op call reverts `Nothing`; `checkpoint` without flows or distributions pays 0.
- A checkpoint with flows is paid from `processingPool`, filled only by the request charges.
- `harvest` pays only if its envelope is at most 25% of the fees it realized.
- Routine and essential budgets cap total pay per day (canary 0.0008 / 0.0002 ETH a day refill,
  0.03 / 0.01 ETH caps).
- Above the ceiling every call is accepted and paid at the ceiling price (D51).

## Keeper P&L per call (canary rehearsal receipts)

Setup: anvil fork of block 26,418,539 with an empty-block basefee that decays from 0.15 gwei;
`keeper/keeper.py` bidding basefee + 0.05 gwei; `keeper/rehearse_canary.py` (D57 run). Rows from
the first liquidate on run under V2, the test policy the rehearsal swaps in (3 work fees per unit,
no gas component), capped by the vault's envelope. "net" = KeeperPaid - gas x effective price.

| Call | Price gwei | Gas | Estimate | Est / gas | Keeper net (wei) | Net / cost |
|---|---|---|---|---|---|---|
| checkpoint (first pricing) | 0.154 | 229,097 | 245,621 | 1.07 | +1.24e13 | +35% |
| restock 10 | 0.141 | 9,176,506 | 10,055,643 | 1.10 | +1.58e14 | +12% |
| list 10 | 0.133 | 5,815,375 | 5,948,288 | 1.02 | +1.65e14 | +21% |
| burnTokens | 0.084 | 415,966 | 443,664 | 1.07 | -3.49e13 | unpaid |
| sync (kicked) | 0.067 | 179,877 | 199,197 | 1.11 | +1.80e13 | +148% |
| list 1 | 0.065 | 840,200 | 861,525 | 1.03 | +1.64e13 | +29% |
| V2: liquidate (spike) | 0.925 | 211,135 | 266,098 | 1.26 | -1.53e13 | -7% |
| V2: unlist 14 (spike) | 0.816 | 2,919,001 | 3,648,131 | 1.25 | -1.48e15 | -62% |
| V2: checkpoint (spike, redemption) | 0.925 | 707,889 | 742,375 | 1.05 | -5.95e14 | -90% |
| V2: unlist 15 (wind-down) | 0.118 | 2,657,521 | 3,318,422 | 1.25 | +2.76e14 | +88% |
| V2: checkpoint (final) | 0.096 | 209,368 | 241,007 | 1.15 | +1.72e13 | +85% |

Results:
- Under V1 below the ceiling every paid call profits: +12% to +148% (the work fee dominates small
  calls at sub-0.1 gwei prices).
- The spike rows ran under V2, which pays no gas: the keeper accepted the loss only because the
  rehearsal passes `--max-loss-wei 0.01 ETH`. The default keeper waits.
- Every payment's receipt matched the keeper's simulation except where basefee fell between the
  simulation and inclusion (each empty anvil block lowers it); the paid amount was then lower,
  never higher.

## Thresholds per operation (D45)

| Operation | Planned when | Gas limit for it |
|---|---|---|
| New packs (`restock` + `list`) | one bid cycle repays the build: 1.39M quoted gas + 0.0003 ETH mint share + 1 work fee | quoted price below about 0.52 gwei, and under the ceiling |
| Relist idle packs | a bid cycle nets positive: B(k-1) = 1.396 mETH against 0.62M quoted gas + 2 work fees | break-even 2.19 gwei, capped by the 0.5 gwei ceiling |
| Harvest fees | pay <= 25% of fees realized; or redemption cash needed | under the ceiling; above it only for redemptions |
| Activate staged listings | FWA's queue drained | under the ceiling |
| Burn token rewards | operator opt-in | under the ceiling; unpaid |
| Checkpoint | FWA blackout, queue drained, flows pending | deposits under the ceiling; redemptions at any gas |
| Sync (recovery of settled, kicked, expired positions) | due | under the ceiling; above it only for redemptions or wind-down |
| Liquidity release (`unlist`, `liquidate`) | redeemers short of ETH; wind-down; edge gate failed | any gas (keeper's loss above the ceiling) |
| Wind-down | owner started it | any gas |

## Reserve (D46)

```
reserve need = one 10-pack listing batch x ceiling x (1 + markup) + 10 work fees
             = (255k + 530k x 10) x 0.5 gwei + 10 x 0.00002 = 0.0030 ETH   (canary)
(checkpoints are paid from request charges; unlisting and syncs from the backing they return)
```

The canary reserve is 0.005 ETH. The need no longer grows with positions.
