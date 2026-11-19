# Operating costs and complete holder exits

Thirty operating days plus at most thirty exit days. All amounts are ETH. Three seeds per active-volume regime; one zero-demand seed. No subsidy or minimum TVL. Permission changes below are model proposals only.

| Size | Permission | Price gwei | Successful/day | Complete exits | Claimed-return range | Routine spend range ETH |
|---|---|---:|---:|---:|---:|---:|
| first-position | configured | 0.2 | 439.7 | 3/3 | -30.19% to -18.69% | 0.004857 to 0.042670 |
| first-position | configured | 0.2 | 71 | 3/3 | -24.33% to +13.55% | 0.009274 to 0.019322 |
| first-position | configured | 0.2 | 0 | 1/1 | -1.57% to -1.57% | 0.000822 to 0.000822 |
| first-position | configured | 0.5 | 439.7 | 2/3 | -39.11% to -37.28% | 0.012053 to 0.076310 |
| first-position | configured | 0.5 | 71 | 3/3 | -36.57% to -5.00% | 0.023095 to 0.048245 |
| first-position | configured | 0.5 | 0 | 1/1 | -2.86% to -2.86% | 0.001995 to 0.001995 |
| first-position | existing-hard-max-proposal | 0.2 | 439.7 | 3/3 | -30.19% to -20.64% | 0.004857 to 0.045810 |
| first-position | existing-hard-max-proposal | 0.2 | 71 | 3/3 | -24.33% to +13.55% | 0.009274 to 0.019322 |
| first-position | existing-hard-max-proposal | 0.2 | 0 | 1/1 | -1.57% to -1.57% | 0.000822 to 0.000822 |
| first-position | existing-hard-max-proposal | 0.5 | 439.7 | 3/3 | -39.11% to -37.28% | 0.012053 to 0.164908 |
| first-position | existing-hard-max-proposal | 0.5 | 71 | 3/3 | -36.57% to -5.00% | 0.023095 to 0.048245 |
| first-position | existing-hard-max-proposal | 0.5 | 0 | 1/1 | -2.86% to -2.86% | 0.001995 to 0.001995 |
| canary | configured | 0.2 | 439.7 | 0/3 | incomplete | 0.076592 to 0.077137 |
| canary | configured | 0.2 | 71 | 2/3 | +4.60% to +6.27% | 0.048885 to 0.050344 |
| canary | configured | 0.2 | 0 | 1/1 | -1.09% to -1.09% | 0.010448 to 0.010448 |
| canary | configured | 0.5 | 439.7 | 0/3 | incomplete | 0.075930 to 0.076578 |
| canary | configured | 0.5 | 71 | 0/3 | incomplete | 0.076865 to 0.077140 |
| canary | configured | 0.5 | 0 | 1/1 | -1.86% to -1.86% | 0.022965 to 0.022965 |
| canary | existing-hard-max-proposal | 0.2 | 439.7 | 1/3 | +7.46% to +7.46% | 0.158400 to 0.166016 |
| canary | existing-hard-max-proposal | 0.2 | 71 | 2/3 | +4.60% to +6.27% | 0.048885 to 0.050344 |
| canary | existing-hard-max-proposal | 0.2 | 0 | 1/1 | -1.09% to -1.09% | 0.010448 to 0.010448 |
| canary | existing-hard-max-proposal | 0.5 | 439.7 | 1/3 | -47.13% to -47.13% | 0.331465 to 0.390415 |
| canary | existing-hard-max-proposal | 0.5 | 71 | 2/3 | -5.38% to +2.24% | 0.111310 to 0.115047 |
| canary | existing-hard-max-proposal | 0.5 | 0 | 1/1 | -1.86% to -1.86% | 0.022965 to 0.022965 |
| larger | configured | 0.2 | 439.7 | 1/3 | +33.70% to +33.70% | 0.248311 to 0.249660 |
| larger | configured | 0.2 | 71 | 1/3 | +14.02% to +14.02% | 0.120270 to 0.126591 |
| larger | configured | 0.2 | 0 | 1/1 | -1.07% to -1.07% | 0.036826 to 0.036826 |
| larger | configured | 0.5 | 439.7 | 3/3 | -4.75% to -0.47% | 0.278690 to 0.357463 |
| larger | configured | 0.5 | 71 | 2/3 | -5.33% to +10.49% | 0.246718 to 0.250665 |
| larger | configured | 0.5 | 0 | 1/1 | -1.89% to -1.89% | 0.082185 to 0.082185 |
| larger | existing-hard-max-proposal | 0.2 | 439.7 | 1/3 | +50.96% to +50.96% | 0.276134 to 0.335606 |
| larger | existing-hard-max-proposal | 0.2 | 71 | 1/3 | +14.02% to +14.02% | 0.120270 to 0.126591 |
| larger | existing-hard-max-proposal | 0.2 | 0 | 1/1 | -1.07% to -1.07% | 0.036826 to 0.036826 |
| larger | existing-hard-max-proposal | 0.5 | 439.7 | 3/3 | -22.75% to +30.74% | 0.601295 to 0.838727 |
| larger | existing-hard-max-proposal | 0.5 | 71 | 1/3 | +13.79% to +13.79% | 0.272960 to 0.291780 |
| larger | existing-hard-max-proposal | 0.5 | 0 | 1/1 | -1.89% to -1.89% | 0.082185 to 0.082185 |

Initial-cap versus steady refill: configured canary0.03ETH/0.0008ETHperday; mainnet0.1ETH/0.005ETHperday. Proposed comparison0.3ETH/0.01ETHperday for both. No new ETH enters the vault. Per-run permission upper bounds use actual elapsed modeled time, independently of cash.

Caller gas figures are labeled historical/quote proxies, not current standalone receipts. Raw results retain actual claimed ETH, remaining entitlements, every operation expense, creator fees, sampled cash, budget stalls and exact zero-gap asset ledgers. No annual-return or launch acceptance is claimed.

## Things that don't make sense

- A generous allowance can pay expenses from depositor principal; that does not make the strategy profitable.

- Successful bookkeeping can end in a blocked exit or a loss.

- Actual receipt profitability and the current fork reconciliation remain separate evidence requirements.
