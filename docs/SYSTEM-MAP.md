# System map: where PackVault's assets sit and how they move

One page. Rules and economics: `OWNER-REQUIREMENTS.md`, `docs/DECISIONS.md`. Measured numbers per regime:
`docs/receipts/flow/` (written by `test/scenario/VaultFlow.t.sol`); the gate: `asset-flow.json`.

PackVault pools depositor ETH, mints Shapes, packs them into ShapePacks and lists each pack on the FWA
V2 main pool at the oracle backing cap to earn FWA's flat per-listing acquisition fees. Holders own
non-transferable internal shares priced at checkpoints.

## Actors

| Actor | Brings | Takes |
| --- | --- | --- |
| Depositors (holders) | ETH deposits | shares; redemptions and distributions on claim |
| Keepers (anyone) | gas for restock/list/sync/harvest/checkpoint/unlist/liquidate/activate/burn | quoted gas per operation at the capped price plus a flat work fee per unit of work (D56), offered by the replaceable policy and capped by the vault (D57); nothing for padding, repeats or dust |
| Purchasers (FWA buyers) | an FWA acquisition that selects a listing | the pack (keep/silent) or the bid (0.9 x backing) |
| FWA main pool (holds vault backing) | custody of listed packs, backing escrow, flat fee shares | 10% of backing on a bid, 1% settlement fee on keep/silent |
| FWA rewards module | FWA token rewards to depositors | nothing (tokens are burned) |
| Shapes / ShapePacks | ETH-backed prize tokens | 0.001 ETH mint fee per 0.1 ETH minted |
| Admin / guardian (may be one key, D44) | nothing | nothing, except what any keeper earns for verified work, inside the budgets (D54 F1, D56); admin changes apply at once (D58) |

## Buckets (A asset, L liability, R accounting representation of the same ETH)

| Bucket | Where | Kind | Own stated need |
| --- | --- | --- | --- |
| Depositor escrow (`pendingDepositTotal`) | vault ETH | L | the whole amount (refundable until priced) |
| Redemption reserve (`redemptionReserve`) | vault ETH | L | the whole amount (owed to redeemers) |
| Distribution reserve (`distributionReserve`) | vault ETH | L | the whole amount (owed to holders) |
| Claimable (`claimableTotal`) | vault ETH | L | the whole amount (settled, unpaid) |
| Vault free ETH (`_free`) | vault ETH above the four liabilities | A | `reserve` + ETH locked redemptions will need |
| Shares (`totalShares`, `sharesOf`) | — | R | priced claim on NAV, not an asset itself |
| Backing on FWA (active/staged/allocated listings) | FWA pool, `value` | A | the target listings |
| Pack value in FWA custody (listed packs) | Shapes, pack held by FWA | A | — |
| Inventory (idle packs + loose Shapes) | Shapes / ShapePacks held by vault | A | — |
| FWA fees uncollected (`pendingFees` + `feeCredit`) | FWA pool | A | — |
| FWA token entitlements (pending/credit/held) | FWA rewards / token | A at zero ETH value | burned, never valued in NAV (D43) |

NAV = vault free ETH + each open position's value (pack + backing + pending fees, by FWA status) + inventory,
minus nothing else; escrow and the three reserves and claimable are excluded from NAV. Keeper pay has no
bucket: it leaves `_free` after a call does necessary work or realizes more than its cost.

## Flows

| # | Flow | Trigger | Reverses? |
| --- | --- | --- | --- |
| 1 | Depositor -> vault: deposit + checkpoint charge (to `processingPool`); the deployment charge stays escrowed with the deposit and earns no shares (D56) | `deposit` (escrowed), priced at the next `checkpoint` | yes: `cancelDeposit` before pricing refunds the escrow, not the checkpoint charge; `requestRedeem` (plus checkpoint and unwind charges) + `claim` after |
| 2 | Vault -> Shapes/Packs: mint value + 0.001 fee, build pack | `restock`, only when one bid cycle repays the build | value yes (`liquidate` redeems); mint fee no |
| 3 | Vault -> FWA: post backing, list pack | `list`, idle ETH above reserve covers one backing and the edge clears gas | yes: `unlist` (wind-down, no edge, or to fund redemptions), kick, keep/silent |
| 4 | FWA -> each active listing: flat fee share | any FWA acquisition | no |
| 5 | FWA fees -> vault ETH | `harvest` (credited fees) and `checkpoint` (`_harvest`) | no |
| 6a | On a bid: backing -> 0.9 purchaser + 0.1 FWA; pack -> vault | purchaser `acceptDepositorBid`, then `sync` | no (backing gone; vault keeps the pack) |
| 6b | On keep/silent: backing x 0.99 -> vault; pack -> purchaser; 1% -> FWA | purchaser `keepNFT`, or `sync` past the window | no |
| 7 | Vault -> keeper: quoted gas at the capped price + work fee per unit (checkpoints from the request-charge pool) | any paid keeper call | the fee share inside a listing returns when harvested; gas does not |
| 8 | Vault -> holder: redemption + distribution | `checkpoint` fills pro rata, `claim` pays | deposit again |
| 9 | FWA rewards -> vault -> burned | `burnTokens` (permissionless, unpaid) | no (supply falls by the claimed amount) |

## One-way ratchets and stuck states to watch

- `highWaterMark` only rises: distributions pay only on new gains above it.
- `redeemEra` / `epoch` / `lastCheckpointInterval` only advance; a checkpoint uses the interval's one slot, so a
  no-flow checkpoint is refused (LOW-1) to avoid delaying a deposit later in the same blackout.
- `windingDown`, `depositsPaused`, `listingPaused` are one-way raises (guardian).
- Mint fees (0.001 ETH per 0.1 ETH minted) never return; holders bear them pro rata.
- Backing on a bid never returns (the vault keeps the pack instead); the 1% FWA settlement fee on keep/silent never
  returns.
- A staged relist earns nothing until activated; FWA's activation is permissionless, so it never sticks (D36).
- Every call stays callable by anyone above the gas ceiling, reimbursed at the ceiling price (D51); unlisting, sync,
  checkpoints, claims and `burnTokens` also when the oracle is broken (D34). `restock`/`list` gate on the edge only.
