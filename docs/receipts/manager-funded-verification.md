# Manager funding correction and local exit

**The cash-protection correction passes focused checks. Economic results remain pending.**
The earlier −28.5% result is withdrawn. Both incomplete source `8e8d5e0` campaigns are preserved
and marked invalid. No public transaction, fee change, shared-vault opening, live cutover or merge
was performed. This is bounded implementation evidence, not release approval.

Incoming principal and fees now refill the protected cash shortfall before becoming spendable.
The contract chooses the first genuinely funded fee prefix and rechecks actual cash. The model
uses the same protection and rejects unpaid ordinary keeper work. No storage, ownership right,
economic setting or callback configuration load was added. The additive `fundingDeficit(bool)`
view is regenerated into the app ABI.

| Accepted step | Result | Limit |
| --- | --- | --- |
| Real funding boundaries | Three real-counterparty fork cases; 43 replayed steps, zero wei gaps | Historical authenticated draws and .001 ETH mint fees |
| Existing affected callers | 18 renewal, sync and owner-exit fork cases pass | Focused pass, not a full system audit |
| New model invariant | Nine funding and seven randomness/cache tests pass | Model equality alone does not establish real gas costs |
| Current receipt rehearsal | 23 real local transactions at fork block 26488707, exact dependencies and linked libraries | No public or hardware-signing proof |
| Owner exit | .5 ETH single-pack and 1 ETH three-pack accounts both end with zero cash, inventory, receipts and fee credit | Keeper budgets zero; no account topups |
| Wallet spending | Signed maxima .000115969148391740 and .000172231255521172 ETH, below each .01 ETH cap | Creation gas is separately included in total owner costs |
| Primary mint revenue | Four .03 ETH packs, twelve paid .01 ETH Shapes; .006 ETH creator accrual | Gross accrual, not creator net profit |
| Keeper | .000795905178295 ETH compensation, .000604073134372415 billed gas, .000191832043922585 margin | Actual local prices; renewal/harvest/variable paid sync curves unmeasured |
| Unsigned preparation | Three libraries plus factory/implementation; no vault or seed | Nonces and live fee must be refreshed before separately authorized signing |
| App integration | ABI/default export matches; typecheck and 14 affected tests pass | Existing browser flow evidence retains its original revision |

Same-receipt owner outcomes:

| Account | Funded | Withdrawn | Wallet gas | Net |
| --- | ---: | ---: | ---: | ---: |
| One pack | .5 | .498232923820000000 | .000172995406360229 | −.001940071586360229 |
| Three packs | 1 | .994971171001705000 | .000170118887349295 | −.005198947885644295 |

Amounts are ETH. These unselected round trips measure costs, not a month of investment returns.
The combined principal shortfall is exactly .006 ETH paid primary fees plus keeper compensation.
Owner, account, keeper, purchaser and deployer ledgers close independently. The genuine external
request pays .050964405021789943 ETH and reclaims .050756405021789943 ETH after expiry;
.000208 ETH pays the real VRF service. No fabricated fulfillment is used.

Raw current receipts: [manager-r2-closeout.json](manager-r2-closeout.json).
Calibration: [manager-r2-cost-calibration.json](manager-r2-cost-calibration.json).
Accounting: [manager-funded-reconciliation.json](manager-funded-reconciliation.json).
Commands, source hashes, statuses and preserved failed attempts:
[input-manifest.json](manager-funded-checks/input-manifest.json).
Independent bounded review: [manager-monte-carlo-independent-review.md](manager-monte-carlo-independent-review.md).

PackManager runtime is 17,853 bytes; VaultLib 22,486; StrategyLib 18,279; ScanLib 22,993.
The closed PackVault is 24,235 bytes, leaving 341 bytes below EIP-170. All submitted local
transactions fit 16,777,216 gas. Aggregate Forge test gas is not billed receipt gas.

Failures remain preserved: the legacy recipe fee-count assertion, two invalid historical selection
setups, insufficient initial index catch-up passes, and a gas-price-sensitive external fee quote.
The last two were repaired on the same fork with the existing receipts and actors. The final
acquisition uses the same explicit .2 gwei legacy price for quote, estimate and execution.

Things that don't make sense: fees below the held float are not maintenance funding; a positive
creator accrual is not owner profit; a complete model exit does not prove the caller accepts its
wallet cost. The real CLI/app spending cap remains mandatory. The corrected fixed-size backing
study and final numerical review remain open.
