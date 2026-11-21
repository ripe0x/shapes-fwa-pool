# Matched recipe comparison (cash path, formal simulator)

Generated 2026-11-21. `python3 sim/recipe_comparison.py --seeds 100 --grid focused`. Pinned block 26,450,200; 100 seeds per sampled cell (zero-demand is deterministic, 1 seed). Every recipe runs through `sim/formal.py`/`sim/forward.run` (the `sim/vault.py` PackVault mirror + `keeper/policy.py` decisions) with the full cash path and a complete holder exit; matched capital, demand history, purchaser pool, gas and seeds. Return is net realized cash / paid-in after one operating year; the 10% annual net hurdle is the minimum gate. FWA tokens valued at zero.

Window: 10701 successful acquisitions in 30 days (357/day); purchaser responses {'DepositorBidAccepted': 7703, 'NFTKept': 2174, 'DepositorBidAcceptedAsTokens': 639, 'silent': 185}. Live FWA at the pin: settlement discount 9000, token discount 9150, acceptBidAsTokens True (best bid = token bid, so it counts).

## Backing and build gate (analytic, 0.5 gwei ceiling, 2 gwei purchaser gas)

| recipe | P | backing B | B/P | lists | keep adv. | creator fee/pack | build cost | build net | rebuilds after keep |
|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 0.06 | 0.06490 | 1.0816 | yes | +0.30 mETH | 2.00 mETH | 2.73 mETH | 6.07 mETH | yes |
| 0.03 bulk mint + split | 0.03 | 0.03203 | 1.0678 | yes | +0.30 mETH | 0.30 mETH | 1.03 mETH | 2.27 mETH | yes |
| 0.03 direct (3 Shapes) | 0.03 | 0.03203 | 1.0678 | yes | +0.30 mETH | 3.00 mETH | 3.80 mETH | 2.27 mETH | NO |

`build net < build cost` (rebuilds = NO) means a kept pack cannot be profitably replaced, so inventory depletes to zero and the account stops earning.

## Canary 1.96 ETH, by behaviour

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 1.96 | allbid | +34.4% | +22.8% | -59.7% | -55.3% | -66.5% | 45% | 50/100 | 0.033 | 0.0641 | 28.5726 | 0.3843 | 423 | 7 | 32 | 0.00 | 0.0022 |
| 0.03 bulk mint + split | 1.96 | allbid | +21.2% | +25.1% | -62.3% | -54.9% | -70.6% | 39% | 46/100 | 0.009 | 0.0185 | 42.5324 | 1.2050 | 1277 | 12 | 62 | 0.00 | 0.0015 |
| 0.03 direct (3 Shapes) | 1.96 | allbid | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 1.96 | observed | +54.5% | +34.3% | -85.1% | -75.3% | -91.3% | 33% | 37/100 | 0.153 | 0.3002 | 39.5045 | 0.5851 | 587 | 53 | 150 | 0.00 | 0.0020 |
| 0.03 bulk mint + split | 1.96 | observed | +36.0% | +37.5% | -70.0% | -46.4% | -91.8% | 31% | 37/100 | 0.061 | 0.1186 | 54.1157 | 1.7050 | 1629 | 156 | 395 | 0.00 | 0.0009 |
| 0.03 direct (3 Shapes) | 1.96 | observed | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 1.96 | value | +134.0% | +136.8% | -50.8% | -22.1% | -93.7% | 17% | 20/100 | 0.801 | 1.5696 | 50.9105 | 0.9621 | 754 | 414 | 785 | 0.00 | 0.0009 |
| 0.03 bulk mint + split | 1.96 | value | +125.9% | +122.2% | +8.8% | +29.9% | -55.9% | 4% | 7/100 | 0.290 | 0.5690 | 61.0200 | 2.3641 | 1833 | 828 | 1897 | 0.00 | 0.0002 |
| 0.03 direct (3 Shapes) | 1.96 | value | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |

## 20 ETH, by behaviour

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 20.00 | allbid | +37.7% | +39.3% | -4.5% | +13.8% | -12.8% | 8% | 5/48 | 0.030 | 0.6100 | 310.1597 | 4.7561 | 4585 | 44 | 305 | 0.00 | 0.0004 |
| 0.03 bulk mint + split | 20.00 | allbid | +16.6% | +17.0% | -6.4% | -2.2% | -21.9% | 12% | 13/48 | 0.008 | 0.1502 | 267.5747 | 6.9376 | 8033 | 68 | 501 | 0.00 | 0.0001 |
| 0.03 direct (3 Shapes) | 20.00 | allbid | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 20.00 | observed | +52.1% | +45.9% | +24.4% | +32.2% | -10.5% | 4% | 2/48 | 0.137 | 2.7357 | 348.7125 | 5.5157 | 5158 | 269 | 1368 | 0.00 | 0.0001 |
| 0.03 bulk mint + split | 20.00 | observed | +25.9% | +25.4% | +6.3% | +8.7% | -17.5% | 2% | 7/48 | 0.032 | 0.6364 | 263.9601 | 7.2658 | 7922 | 306 | 2121 | 0.00 | 0.0003 |
| 0.03 direct (3 Shapes) | 20.00 | observed | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 20.00 | value | +89.2% | +88.2% | +59.6% | +63.4% | +14.3% | 0% | 0/48 | 0.546 | 10.9215 | 348.9268 | 6.6386 | 5168 | 1812 | 5461 | 0.00 | 0.0000 |
| 0.03 bulk mint + split | 20.00 | value | +47.2% | +48.7% | +24.2% | +31.3% | +16.8% | 0% | 0/48 | 0.100 | 1.9963 | 210.8557 | 7.2985 | 6333 | 977 | 6654 | 0.00 | 0.0000 |
| 0.03 direct (3 Shapes) | 20.00 | value | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |

## Capacity curve (6.8 and 50 ETH)

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|

## Fixed keep-rate (50%) and keep sweep

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 1.96 | keep 0.5 | +87.8% | +80.7% | -87.8% | -53.6% | -95.8% | 29% | 32/100 | 0.375 | 0.7358 | 45.6226 | 0.7572 | 676 | 179 | 368 | 0.00 | 0.0014 |
| 0.03 bulk mint + split | 1.96 | keep 0.5 | +72.1% | +65.4% | -38.4% | -13.0% | -67.6% | 17% | 22/100 | 0.144 | 0.2828 | 58.5081 | 2.0208 | 1758 | 422 | 943 | 0.00 | 0.0008 |
| 0.03 direct (3 Shapes) | 1.96 | keep 0.5 | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 20.00 | keep 0.5 | +68.9% | +69.4% | +25.8% | +38.5% | -4.7% | 2% | 1/48 | 0.296 | 5.9261 | 359.0654 | 6.0883 | 5311 | 977 | 2963 | 0.00 | 0.0000 |
| 0.03 bulk mint + split | 20.00 | keep 0.5 | +35.2% | +37.3% | +11.1% | +15.8% | -12.3% | 2% | 2/48 | 0.061 | 1.2111 | 240.7204 | 7.2941 | 7223 | 680 | 4037 | 0.00 | 0.0002 |
| 0.03 direct (3 Shapes) | 20.00 | keep 0.5 | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |

## Stress: quieter (last 10 days) and zero demand

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 1.96 | allbid | +4.5% | +0.6% | -38.4% | -35.7% | -50.9% | 49% | 64/100 | 0.016 | 0.0320 | 5.2888 | 0.0806 | 78 | 3 | 16 | 0.00 | 0.0045 |
| 0.03 bulk mint + split | 1.96 | allbid | +1.2% | -3.2% | -37.5% | -31.0% | -53.3% | 53% | 63/100 | 0.005 | 0.0102 | 10.2820 | 0.3204 | 310 | 6 | 34 | 0.00 | 0.0035 |
| 0.03 direct (3 Shapes) | 1.96 | allbid | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 1.96 | value | +15.4% | +9.8% | -32.5% | -26.1% | -46.3% | 36% | 51/100 | 0.115 | 0.2252 | 6.7941 | 0.1369 | 101 | 81 | 113 | 0.00 | 0.0040 |
| 0.06 direct (current) | 1.96 | value | -2.3% | -2.3% | -2.3% | -2.3% | -2.3% | 100% | 1/1 | 0.015 | 0.0300 | 0.0000 | 0.0117 | 0 | 2 | 15 | 0.00 | 0.0100 |
| 0.03 bulk mint + split | 1.96 | value | +24.5% | +24.1% | -30.6% | -19.0% | -47.1% | 26% | 34/100 | 0.067 | 0.1323 | 13.7534 | 0.5705 | 414 | 308 | 441 | 0.00 | 0.0028 |
| 0.03 bulk mint + split | 1.96 | value | -2.1% | -2.1% | -2.1% | -2.1% | -2.1% | 100% | 1/1 | 0.005 | 0.0093 | 0.0000 | 0.0235 | 0 | 4 | 31 | 0.00 | 0.0099 |
| 0.03 direct (3 Shapes) | 1.96 | value | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.03 direct (3 Shapes) | 1.96 | value | -0.1% | -0.1% | -0.1% | -0.1% | -0.1% | 100% | 1/1 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 20.00 | allbid | +4.4% | +4.2% | -11.9% | -10.1% | -20.0% | 33% | 35/48 | 0.015 | 0.3086 | 54.3213 | 0.9618 | 804 | 20 | 154 | 0.00 | 0.0033 |
| 0.03 bulk mint + split | 20.00 | allbid | +4.8% | +5.3% | -9.6% | -7.1% | -14.7% | 31% | 33/48 | 0.004 | 0.0891 | 102.9014 | 2.7902 | 3094 | 40 | 297 | 0.00 | 0.0013 |
| 0.03 direct (3 Shapes) | 20.00 | allbid | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |
| 0.06 direct (current) | 20.00 | value | +15.4% | +16.7% | -1.0% | +1.0% | -8.9% | 8% | 16/48 | 0.113 | 2.2517 | 67.7928 | 1.4896 | 1005 | 779 | 1126 | 0.00 | 0.0032 |
| 0.03 bulk mint + split | 20.00 | value | +24.6% | +25.4% | +11.4% | +14.1% | +4.2% | 0% | 2/48 | 0.059 | 1.1761 | 121.4258 | 4.4207 | 3656 | 2172 | 3920 | 0.00 | 0.0008 |
| 0.03 direct (3 Shapes) | 20.00 | value | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0004 | 0 | 0 | 0 | 0.00 | 0.0100 |

## Low gas (0.2 gwei), value-aware

| recipe | capital | behaviour | mean | median | p5 | p10 | worst | loss% | <10% hurdle | creator/ETH-yr | creator ETH | fees ETH | keeper ETH | sel/yr | builds | mint# | util | min free |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 1.96 | value | +193.8% | +183.6% | -41.3% | -8.0% | -94.9% | 13% | 15/100 | 0.950 | 1.8611 | 60.3346 | 0.4948 | 893 | 511 | 931 | 0.00 | 0.0008 |
| 0.03 bulk mint + split | 1.96 | value | +357.0% | +369.2% | +148.2% | +178.1% | +46.5% | 0% | 0/100 | 0.529 | 1.0375 | 111.0389 | 1.8265 | 3335 | 1571 | 3458 | 0.00 | 0.0000 |
| 0.03 direct (3 Shapes) | 1.96 | value | -0.0% | -0.0% | -0.0% | -0.0% | -0.0% | 100% | 2/2 | 0.000 | 0.0000 | 0.0000 | 0.0002 | 0 | 0 | 0 | 0.00 | 0.0100 |

## Purchaser-gas-price sensitivity (1 / 2 / 3 gwei), 1.96 ETH value-aware

Backing (analytic) and simulated return per recipe.

| recipe | gwei | backing | B/P | keep adv. | lists | mean | median | loss% |
|---|---|---|---|---|---|---|---|---|
| 0.06 direct (current) | 1 | 0.06507 | 1.0845 | +0.30 mETH | yes | +140.3% | +130.0% | 15% |
| 0.03 bulk mint + split | 1 | 0.03225 | 1.0749 | +0.30 mETH | yes | +153.0% | +154.5% | 4% |
| 0.03 direct (3 Shapes) | 1 | 0.03225 | 1.0749 | +0.30 mETH | yes | -0.1% | -0.1% | 100% |
| 0.06 direct (current) | 2 | 0.06490 | 1.0816 | +0.30 mETH | yes | +134.0% | +136.8% | 17% |
| 0.03 bulk mint + split | 2 | 0.03203 | 1.0678 | +0.30 mETH | yes | +125.9% | +122.2% | 4% |
| 0.03 direct (3 Shapes) | 2 | 0.03203 | 1.0678 | +0.30 mETH | yes | -0.1% | -0.1% | 100% |
| 0.06 direct (current) | 3 | 0.06472 | 1.0787 | +0.30 mETH | yes | +124.4% | +116.6% | 18% |
| 0.03 bulk mint + split | 3 | 0.03182 | 1.0607 | +0.30 mETH | yes | +101.2% | +97.6% | 10% |
| 0.03 direct (3 Shapes) | 3 | 0.03182 | 1.0607 | +0.30 mETH | yes | -0.1% | -0.1% | 100% |

