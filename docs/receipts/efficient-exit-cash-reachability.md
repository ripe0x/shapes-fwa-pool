# Cash-cliff fork reachability gap

**The requested partial-redemption → purchaser bid → cash-starved reconciliation cycle was not reproduced on a real fork.** No new test was created or reported passing. This bounded investigation stopped rather than change protocol timing, impersonate the vault or fabricate pre-existing shares/approvals.

## Frozen inputs

| File | SHA-256 |
| --- | --- |
| `src/PackVault.sol` | `448106b8915413badef411355a5cb729ca15046743be768919d74e9349ddcd8b` |
| `src/VaultLib.sol` | `1a5407f1044f0e79b874ee77cd6936bb53438b020f4c8e093db200909990490f` |
| `test/fork/ForkSelection.t.sol` | `bbab3d70af0fa573832824fb15ad66852dd9c84b1a69c7dee11935381f63cd12` |

The locally inspected FWA source SHA `1b5dbbe6a2c1d15e8df38c075da85036659aacb38936ccd94619b86a8240a425` matches `audit/release-ba8d26e/external-source-match.json` for the deployed integration.

## Why the existing authentic fixtures are insufficient

`SelectionBase._select` deploys a fresh vault with a 3 ETH dead-share seed and no priced live holder, then posts the exact listing fixture and replays the real request/fulfillment. It supplies no hook for a holder checkpoint before that selection. Shares are non-transferable; a new holder must first price a deposit, then request redemption, then reach another checkpoint to obtain a partial fill.

Checkpoint is limited to once per 12-hour interval and FWA's last-15-minute purchase blackout. Two usable checkpoint windows are therefore at least 11 hours 45 minutes apart. Both authentic selection fixtures have a **3,600-second purchaser-exclusive settlement window**. Once the own allocation is that old, checkpoint rejects `SyncFirst`; it cannot leave that allocation unresolved while producing the requested partial fill.

The early fulfillment is 1,429 seconds before the next blackout, so one pre-expiry checkpoint is possible in principle. Its actual request timeout is only 30 blocks. The late fulfillment is 37,213 seconds before blackout, already beyond the allocation window. Neither supplies a pre-priced live holder, so neither establishes the requested two-checkpoint cycle.

Preserving only a cash-priced vault across fork history loses its genuine Shapes/ShapePacks approvals. Recreating them by impersonating the vault is forbidden. Preserving or editing protocol state, reversing time, changing the settlement window, spending dead shares or building a historical replay project was not attempted.

## Read-only RPC evidence

These three commands exited 0; each used the required public Tenderly RPC. No transactions, new signers, actor funding or protocol configuration changes occurred.

```sh
cast call 0x958C41181182e76F221331b2755b77D9e1426A98 'settlementWindow()(uint256)' --block 26417091 --rpc-url https://mainnet.gateway.tenderly.co
# 3600
cast call 0x958C41181182e76F221331b2755b77D9e1426A98 'selectionTimeoutBlocks()(uint256)' --block 26405708 --rpc-url https://mainnet.gateway.tenderly.co
# 30
cast call 0x958C41181182e76F221331b2755b77D9e1426A98 'settlementWindow()(uint256)' --block 26405708 --rpc-url https://mainnet.gateway.tenderly.co
# 3600
```

## Source-traced economic cycle, not fork proof

With an already priced holder and sufficient non-cash assets, a partial checkpoint can move nearly all unencumbered ETH into the protected redemption reserve. The exact remainder depends on fill rounding and any request-charge surplus. A later actual purchaser bid returns the pack while paying backing to the purchaser/protocol, so it need not replenish vault cash. The book still needs authenticated terminal reconciliation before that pack is idle inventory.

`sync` uses routine permission, but `VaultLib.pay` also caps payment by actual `_free()`. A positive routine allowance therefore cannot pay the quote when holder liabilities encumber nearly all ETH. A `minPay` above available payment reverts the sync; `minPay=0` permits the work for whatever remains. Protected redemption cash is not a maintenance subsidy. Unpaid or inadequately paid reconciliation/liquidation may thus be required before the remaining assets can fund another checkpoint and claim.

This finding remains **model plus Solidity/FWA source tracing**, not a verified real-fork cash-cliff result. No actual protected-cash boundary, holder gas bill, complete claim amount or full exit result was obtained for this case. A new authentic selection fixture with a previously priced holder would be needed to close it. Earlier successful accounting traces cover their own flows and do not substitute for this missing regime.

## Things that don't make sense

- Budget permission is not available ETH. A positive routine budget cannot spend protected redemption reserves.
- Reporting this fixture as a successful cash-cliff regression would require hiding its missing pre-priced holder or changing its timing assumptions.
- The complete operating model must disclose this unverified cycle and who funds any required caller-paid work.
