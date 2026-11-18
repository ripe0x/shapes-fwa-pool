# Operating costs and complete holder exits

**Timing limitation: these112model cases are illustrative accounting and expense scenarios. Their exit counts and returns do not establish authentic expiry behavior, continuous keeper availability, achievable exits or a recommended operating budget.** The model passes `settlement_window=10**12` seconds to keeper policy, while the authentic FWA fixtures report3600seconds. It runs open and blackout policy phases with the same `now=d*86400`, and resolves sampled own selections on the next modeled day, before the next day’s policy pass. This suppresses real one-hour allocation expiry and its competition with the later checkpoint window. It can materially change terminal work, backing disposition, cash-return timing, the need for caller rescue, total expenses and whether an exit completes. The direction and magnitude are not established here. Exact asset conservation remains a claim about the modeled path only.

Provenance: this daily settlement/window surrogate already exists in baseline commit `d1b59f1`; the operating comparison inherited it. Its apparent purpose is to keep the coarse daily simulator from expiring every allocation before its synthetic next-day purchaser response. That purpose is an inference from code, not an owner-approved timing assumption. The real3600second readings and the incompatible prepriced-holder/checkpoint ordering are recorded in `efficient-exit-cash-reachability.md`. Fresh accounting reconciliation validates matching executed paths, but does not validate this external timing surrogate or transfer112scenario results into real timing evidence. No matrix or executable code was changed for this disclosure.

Thirty operating days plus at most thirty exit days, with foreign activity continuing until the modeled claim completes. All amounts are ETH. Three seeds per active-volume regime; one zero-demand seed. No subsidy or minimum TVL. Permission changes below are model proposals only.

| Outcome | Bounded result |
|---|---|
| Exact model asset ledger | 112/112 zero-gap cases |
| Primary complete exits | 56/84; incomplete cases retain explicit rights/assets |
| Primary fully paid routine work without funding stalls | 40/84 |
| Separate final-holder rescue | 28/28 finish; these are not funded-operation passes |
| Creator operating subsidy | 0 in every case; mint fees remain expenses |
| Annual return/release acceptance | Not established; caller gas proxies and stochastic timing remain limitations |

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

Initial-cap versus steady refill: configured canary 0.03 ETH / 0.0008 ETH per day; mainnet 0.1 ETH / 0.005 ETH per day. Proposed comparison 0.3 ETH / 0.01 ETH per day for both. No new ETH enters the vault. Per-run permission upper bounds use actual elapsed modeled time, independently of cash.

Caller gas figures are labeled historical/quote proxies, not current standalone receipts. Raw results retain modeled claim payments, remaining entitlements, every operation expense, creator fees, sampled cash, budget stalls and exact zero-gap asset ledgers. No annual-return or launch acceptance is claimed.


Separate holder-rescue diagnostics: 28/28 primary incomplete cases finish by allowing holder-paid zero-minimum-pay sync after exit is requested. These are rescued exits, not fully funded operating passes. Their full caller gas proxy and actual clipped pay remain in the raw results.

## Things that don't make sense

- A generous allowance can pay expenses from depositor principal; that does not make the strategy profitable.

- Successful bookkeeping can end in a blocked exit or a loss.

- Actual receipt profitability and the current fork reconciliation remain separate evidence requirements.

Execution assumptions: daily successful selections are sampled from the recorded pool snapshot. Own selections precede that day’s foreign journal records and settle on the following modeled day. Default own settlement is a bid return, rather than a randomized keep; recorded global refunded records are included using their30day ratio. This models bounded journal/position interactions but does not replay actual historical ordering or onchain receipts.

One cash availability finding is visible despite a0.3ETH allowance: the larger vault,0.2gwei,71successful selections/day,seed3 reaches a partial redemption with cash3wei, protected1wei and free2wei. Six returned packs carry0.18ETH, but paid synchronization is required before that value is usable for liquidation. The strict run stalls; the separate holder rescue accepts2wei for sync and pays the full caller gas proxy, then liquidates and finishes the claim. This is model plus source-traced evidence. The attempted genuine-fork reproduction could not reach the needed prepriced-holder/settlement/checkpoint ordering with the available real fixtures; see efficient-exit-cash-reachability.md.

The first-position case also has a liquidity distinction:0.15ETH,configured canary permissions,0.2gwei,439.7successful selections/day,seed3 ends its30day operating period with0.012156369441514957ETH cash,0.1ETH idle asset value including0.07ETH in loose Shapes, and0.04616219782149ETH required for the next idle relisting commitment. Only one operating day has active exposure. More spending permission supplies no cash for that commitment. No new product minimum or inventory liquidation rule is assumed.
