# Gas and keeper compensation

## Pay rule (contract)

```
price = min(tx.gasprice, basefee + maxTip, gasCeiling)          canary: maxTip 0.05 gwei, ceiling 0.5 gwei
pay   = min(measured gas + 30,000, opGasCap) x price x 1.10    from vault ETH (free ETH, never liabilities)
      + workFee x units                                         canary 0.00002 ETH, max 0.0001 (D55)
units = positions listed, resolved (sync), activated or unlisted; items liquidated; 1 per checkpoint that
        priced flows or distributed. restock, harvest and burnTokens earn none.
```

Bounds on what a caller can extract:
- `harvest` pays only if pay <= 25% of the fees it realized.
- `sync`, `unlist` and `activate` pay at most 300,000 gas per position they moved.
- A no-op call pays nothing:
  - every paid call reverts `Nothing` without work;
  - `checkpoint` refuses when no flows or distributions are pending.
- No call is refused for gas price (D51). Above the ceiling every call is paid at the ceiling price and the caller pays the rest.
- `burnTokens` pays nothing.
- Splitting work into more calls earns at most the 30,000-gas overhead per call. Worst case is about
  0.015 ETH a year at the ceiling (D41 LOW-3).

## Keeper P&L per call (canary rehearsal receipts, selected; repeated batches omitted)

Canary rehearsal setup:
- anvil fork of block 26,418,539
- `keeper/keeper.py` bidding basefee + 0.05 gwei
- receipts from `keeper/rehearse_canary.py`, run after `ae8fc54` with the D45 to D47 changes
- "net" = KeeperPaid - gasUsed x effectiveGasPrice

| Call | Bid gwei | Gas used | Estimate | Est / used | Keeper net (wei) | Net / cost |
|---|---|---|---|---|---|---|
| checkpoint (first pricing) | 0.168 | 199,390 | 200,892 | 1.01 | +1.93e12 | +6% |
| restock 10 packs | 0.168 | 9,147,348 | 10,014,151 | 1.09 | +2.64e14 | +21% |
| list 10 | 0.168 | 5,791,220 | 5,921,520 | 1.02 | +9.55e13 | +12% |
| sync (kicked listing) | 0.070 | 153,283 | 164,385 | 1.07 | +5.25e11 | +5% |
| list 1 | 0.070 | 817,371 | 836,073 | 1.02 | +6.53e12 | +12% |
| burnTokens (29 listings) | 0.088 | 415,963 | 443,664 | 1.07 | -3.47e13 | unpaid |
| unlist 14 (spike) | 0.925 | 2,891,554 | 3,608,343 | 1.25 | -3.78e14 | -16% |
| liquidate (spike) | 0.925 | 2,088,512 | 2,604,541 | 1.25 | -9.68e13 | -6% |
| checkpoint (spike, redemption) | 1.050 | 685,990 | 707,392 | 1.03 | -2.50e14 | -39% |
| unlist 15 (wind-down) | 0.138 | 2,628,768 | 3,279,860 | 1.25 | +1.14e14 | +37% |
| liquidate (wind-down) | 0.138 | 2,222,010 | 2,771,414 | 1.25 | +8.87e13 | +36% |
| checkpoint (final) | 0.103 | 184,619 | 206,021 | 1.12 | +3.18e12 | +18% |

Results:
- **Whole rehearsal:** 18 transactions. Keeper paid 0.011194 ETH, spent 0.010840 ETH, **net +0.000353 ETH**. That includes the
  spike work, a loss of 0.000779 ETH, and the token burn, 0.0000347 ETH.
- **Below the ceiling every paid call profits.** The margin is +5% to +37%.
- **Unlisting and liquidation earn more than their gas.** They are paid on measured gas before EIP-3529 refunds, which the
  sender gets back.
- **Above the ceiling the keeper's loss is (bid - ceiling x 1.1) x gas.** It is accepted only within `--max-loss-wei`.

## Thresholds per operation (D45)

| Operation | Planned when | Gas limit for it |
|---|---|---|
| New packs (`restock` + `list`) | one bid cycle repays the build: 1.05M gas + 0.0003 ETH mint share | below about 0.54 gwei, and under the ceiling |
| Relist idle packs | a bid cycle nets positive: B(k-1) = 1.396 mETH against 0.8M gas | break-even 1.59 gwei, capped by the 0.5 gwei ceiling |
| Harvest fees | pay <= 25% of fees realized; or redemption cash needed | under the ceiling; above it only for redemptions |
| Activate staged listings | FWA's queue drained | under the ceiling |
| Burn token rewards | operator opt-in | under the ceiling; unpaid |
| Checkpoint | FWA blackout, queue drained, flows pending | deposits under the ceiling; redemptions at any gas |
| Sync (recovery of settled, kicked, expired positions) | due | under the ceiling; above it only for redemptions or wind-down |
| Liquidity release (`unlist`, `liquidate`) | redeemers short of ETH; wind-down; edge gate failed | any gas (keeper's loss above the ceiling) |
| Wind-down | guardian started it | any gas |

## Measured gas per unit

These are the policy constants (`keeper/policy.py`), measured on fork tests and confirmed by the receipts above.

| Unit | Gas |
|---|---|
| restock, per 3-unit pack | 921,000 measured (1,050,000 build constant) |
| list, per position | 499,000 to 570,000 |
| sync | 60,000 + 100,000 per listing |
| harvest | 90,000 + 15,000 per listing |
| unlist, per position | 201,000 |
| liquidate, per pack | 160,000 |
| checkpoint | 220,000 + 32,100 per position (300 positions all kicked: 10.17M, under EIP-7825's 16.78M) |
| bid cycle (sync + relist + harvest share + 2 x 30k overhead) | 800,000 |

## Reserve (D46)

```
reserve need = (checkpoint at max positions + one 10-pack listing batch) x ceiling x 1.10
             = (220k + 32.1k x 30 + 30k + 570k x 10 + 30k) x 0.5 gwei x 1.10 = 0.0038 ETH   (canary)
```

The canary reserve is 0.005 ETH, down from 0.05 ETH. The 2 ETH canary now builds 29 positions instead of 28. At 300 positions the need is 0.0086 ETH.
