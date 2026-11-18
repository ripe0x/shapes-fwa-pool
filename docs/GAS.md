# Position-accounting gas and compensation

**The locally verified candidate has a funding blocker and failed historical economic outcomes.** Current acceptance
and numerical outcomes are in `POSITION-INTEGRATION-ACCEPTANCE.md`. The tables below the separator
are historical and do not validate this candidate.

Compensation is a fixed quote for verified work. It is not reimbursement of measured transaction
gas. The replaceable policy offer is capped by the vault envelope, free cash, the applicable
routine/essential budget and `minPay`. Request-funded checkpoints use only their existing shared
processing charge. Foreign/refunded journal entries earn no flat work fee; operation 4 is retired.

| Component | Quoted gas |
| --- | ---: |
| Checkpoint | 400,000, independent of position count |
| Restock base | 280,000 |
| Pack assembly | 325,000 for three Shapes, plus 35,000 per additional Shape |
| Paid primary mint and split | 2,200,000 per ten 0.01 ETH Shapes |
| List | 280,000 base + 825,000 per admitted position |
| Sync | 85,000 base + 30,000 per completed global record |
| Own selection / terminal / head prune | 160,000 / 120,000 / 45,000 |
| Unlist | 340,000 base + 285,000 per moved position |
| Liquidate | 75,000 base + 80,000 per ordinary pack + 35,000 per actual packed Shape burned |
| Loose Shape redemption | 65,000 per Shape |
| Oversized gift recovery | 100,000 + 35,000 per actual Shape burned + 70,000 once for unseal, plus liquidation base |
| Harvest | 125,000 base + 80,000 per listing actually harvested |

The mandatory own-position sync components sum to 355,000. Recurring cycle economics include that
sum, relisting and fee harvesting exactly once. Entry charges retain build plus initial listing;
exit charges retain unlisting plus liquidation. Canary essential cap zero means self-serve exits
remain unpaid with zero unwind charge. No budget, reserve value, markup maximum or flat fee maximum
was raised.

Listing is capped at eight per call. Every real FWA `listNFT` receives at most 1.2 million gas;
ordinary Active identity, non-FWAIR classification and exactly one additional active listing are
required. Other caller work limits remain sixteen, with restock/liquidation capped at thirty
ordinary backing units and oversized gifts claimed in isolated thirty-Shape chunks.

## Evidence interpretation

Foundry gross meters include execution plus intrinsic/calldata before transaction refunds. They
bound the gas limit; they are not billed-gas or keeper-profit receipts. Actual local transaction
receipts are reported separately. `sim/out/gas-quotes-incremental.json` is the earlier partial
local calibration, not the final schedule or a profitability pass. Relevant fee tests set and assert both basefee and transaction
gas price inside an executed call. Pending RPC simulations use explicit fee fields and authenticate
executed BASEFEE against the deterministic next header.

Earlier focused complete-operation measurements include restock ten three-unit packs at 10,356,704
gross gas, a full holder checkpoint at 370,178, harvest sixteen at 1,084,228, unlist sixteen at
4,113,806, and thirty-Shape liquidation at 1,153,746. These pre-final measurements have explicit
input limitations in `receipts/integration-*`. Final focused measurements now include eight largest packs at 6,554,114 gross gas, eight mixed
packs with five crown tenures at 6,527,313, and restock ten small packs at 10,357,047. The largest
measured operation with 25% margin is 12,946,309, below 16,777,216. Runtime is 24,549 bytes for
PackVault (27 bytes spare) and 20,484 for VaultLib. Final receiver and linked deployment results are recorded below and in the acceptance report.

Final exact production receiver: 46,462 gas for the cold keep and 69,730 for the difficult kick
following a false settled-bid candidate. At least 30,270 gas remains below FWA's 100,000 stipend.
All 99 sampled low-gas limits recorded completely or failed atomically. This does not prove every
possible gas amount; exact traces and scope are in `receipts/integration-final-test-evidence.json`.

Normal approved local script deployment used 5,766,663 billed gas for the 24,549-byte vault and
100,155 for the 216-byte policy. The linked 20,484-byte library was reused; its actual prior
approved-deployer CREATE2 receipt used 4,490,075 gas. Its 20,516-byte initcode exactly matches the
frozen artifact. Only the compiler-declared self-address immutable is normalized for runtime
comparison. See `receipts/integration-keeper-context-correction.json` for factory, salt, receipts
and source attribution. No actual code or gas limit was increased.

The broad run exposed profitable listing-base splitting. Actual matched-fee receipts measured
650,969 extra billed gas for three singletons versus the same three-item batch. Q_LIST 280,000
makes the extra pay at maximum 10% markup 0.0001232 ETH, below the measured extra 0.0001301938 ETH
cost at 0.2 gwei. The previous 400,000 base was excessive; even 300,000 failed that billed bound.
Per-listing pay and work fees are unchanged. This sampled comparison does not bound all future
orderings or external protocol changes.

## Reserve and recurring funding

At a 0.5 gwei quote, one full foreign journal batch costs 0.0002825 ETH and the keeper's reserve
model requires 0.0042425 ETH against the retained 0.005 ETH reserve. That reserve can afford bounded
progress; it does not fund continuing activity.

Recorded 30-day global work requires at least 0.3227925 ETH of quotes at 0.5 gwei, before any own
position work, versus a maximum mainnet routine budget of 0.25 ETH. At 0.2 gwei the lower bound is
0.129117 ETH. Canary permits only 0.054 ETH over the same thirty days. Exact source/data context,
shortfalls and a narrow proposed owner decision are in the acceptance report and maintenance JSONs.

Batch quotes are conservative relative to some measured calls; a successful cold singleton can
still cost more than its quote. Do not claim every call profits or identify gross gas with actual
billed cost. The keeper estimates the real transaction and obeys its per-call and cumulative loss
limits. Delayed or concurrent state changes can still cause atomic rejection and real gas loss.

---

# Gas and keeper compensation

## Pay rule (contract, D56/D57)

```
price    = min(basefee + maxTip, ceiling)       ceiling = gasCeiling (routine, canary 0.5 gwei) or
           essentialCeiling (redemption and wind-down, canary 2 gwei); maxTip 0.05 gwei
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
| checkpoint | 225,000 | 33,000 per position | 221,860 (0 positions), 975,403 (23); quoted at measured cost (D61) |
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
