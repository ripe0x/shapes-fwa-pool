> SUPERSEDED by sim/out/forward.md (2026-11-16): these returns omit the 5% keeper fee skim the contract then took (D19).

# Phase 0.3 model

Pool at block 26,425,092: 2,584 active listings, harmonic backing 0.0514 ETH.
Volume (acquisitions/day): 1 d 15, 7 d 97.1, 30 d 609.4, 60 d 1565.4.
Gas table: measured: fork block 26424971 + estimates for vault_overhead, harvest_per_id.

Assumptions: pack P = 0.03 ETH; backing at the oracle cap 0.0363; FWA tokens valued at zero; pool composition and volume stationary; volume does not respond to vault size.

## Base case and capacity (30-day volume, 1.2 gwei)

| scenario | acq/day | positions | B | k | purchaser | cycle days | net/cycle mETH | APR | capital ETH | selection share |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 positions | 609 | 1 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +88.6% | 0.1 | 0.1% |
| 10 positions | 609 | 10 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +88.2% | 0.7 | 0.5% |
| 50 positions | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +86.3% | 3.3 | 2.7% |
| 150 positions | 609 | 150 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +81.9% | 9.9 | 7.6% |
| 500 positions | 609 | 500 | 0.0363 | 1.0385 | bid | 4 | +0.483 | +69.6% | 33.1 | 21.5% |

## Volume

| scenario | acq/day | positions | B | k | purchaser | cycle days | net/cycle mETH | APR | capital ETH | selection share |
|---|---|---|---|---|---|---|---|---|---|---|
| 15/day | 15 | 50 | 0.0363 | 1.0385 | bid | 125 | +0.483 | +2.1% | 3.3 | 2.7% |
| 50/day | 50 | 50 | 0.0363 | 1.0385 | bid | 38 | +0.483 | +7.1% | 3.3 | 2.7% |
| 97/day | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +0.483 | +13.7% | 3.3 | 2.7% |
| 250/day | 250 | 50 | 0.0363 | 1.0385 | bid | 8 | +0.483 | +35.4% | 3.3 | 2.7% |
| 609/day | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +86.3% | 3.3 | 2.7% |

## Stress (50 positions, 30-day volume)

| scenario | acq/day | positions | B | k | purchaser | cycle days | net/cycle mETH | APR | capital ETH | selection share |
|---|---|---|---|---|---|---|---|---|---|---|
| live | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +0.483 | +86.3% | 3.3 | 2.7% |
| gas 0.15 gwei (pinned block) | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +1.282 | +229.3% | 3.3 | 2.7% |
| gas 0.5 gwei | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +1.015 | +181.6% | 3.3 | 2.7% |
| gas 2 gwei | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | -0.127 | -22.6% | 3.3 | 2.7% |
| gas 5 gwei | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | -2.411 | -431.2% | 3.3 | 2.7% |
| gas 20 gwei | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | -13.831 | -2474.0% | 3.3 | 2.7% |
| crown share back to 5% | 609 | 50 | 0.0363 | 0.9875 | bid | 3 | -1.366 | -244.4% | 3.3 | 2.7% |
| crown 0.5% | 609 | 50 | 0.0363 | 1.0343 | bid | 3 | +0.332 | +59.3% | 3.3 | 2.7% |
| floor ask cut to 0.0300 | 609 | 50 | 0.0330 | 1.0385 | keep | 3 | +1.513 | +312.6% | 3.1 | 2.9% |
| floor ask cut to 0.0275 | 609 | 50 | 0.0303 | 1.0385 | keep | 3 | -1.315 | -308.9% | 3.0 | 3.2% |
| floor ask cut to 0.0265 | 609 | 50 | 0.0292 | 1.0385 | keep | 2 | -2.446 | -606.8% | 3.0 | 3.3% |
| 20% irrational keeps | 609 | 50 | 0.0363 | 1.0385 | bid | 3 | +1.367 | +244.6% | 3.3 | 2.7% |
| 15/day and 5 gwei | 15 | 50 | 0.0363 | 1.0385 | bid | 125 | -2.411 | -10.6% | 3.3 | 2.7% |

## Current run rate (7-day volume) by gas price, 50 positions

| scenario | acq/day | positions | B | k | purchaser | cycle days | net/cycle mETH | APR | capital ETH | selection share |
|---|---|---|---|---|---|---|---|---|---|---|
| 0.15 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +1.282 | +36.6% | 3.3 | 2.7% |
| 0.5 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +1.015 | +29.0% | 3.3 | 2.7% |
| 1.0 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +0.635 | +18.1% | 3.3 | 2.7% |
| 1.2 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +0.483 | +13.8% | 3.3 | 2.7% |
| 1.5 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | +0.254 | +7.2% | 3.3 | 2.7% |
| 2.0 gwei | 97 | 50 | 0.0363 | 1.0385 | bid | 19 | -0.127 | -3.6% | 3.3 | 2.7% |

Break-even gas price for the bid outcome: 1.8 gwei (gas per cycle 761,340).

## Realized-return spread (Monte Carlo, one year)

| volume | positions | p5 | median | p95 | P(loss) |
|---|---|---|---|---|---|
| 30 d 609/day | 1 | -990.4% | +76.0% | +1086.3% | 43% |
| 30 d 609/day | 10 | -244.2% | +87.0% | +406.9% | 33% |
| 30 d 609/day | 50 | -61.1% | +86.0% | +227.4% | 16% |
| 30 d 609/day | 150 | -0.6% | +81.8% | +161.5% | 5% |
| 7 d 97/day | 1 | -411.7% | +37.3% | +374.1% | 48% |
| 7 d 97/day | 10 | -119.7% | +15.1% | +138.5% | 43% |
| 7 d 97/day | 50 | -45.4% | +14.1% | +70.2% | 35% |
| 7 d 97/day | 150 | -20.1% | +13.2% | +45.0% | 25% |
