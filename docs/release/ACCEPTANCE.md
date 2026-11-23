# Owner acceptance: checkpoint timing candidate

**Unsigned. No broadcast authority.** [acceptance.json](acceptance.json) binds the current source
revision, release manifest, mainnet values and asset-flow outcomes. The former acceptance signature
was removed because D86 changes the vault's bytecode and refund accounting. The prior formal return,
image rehearsal and production rehearsal receipts remain historical; they do not verify this
candidate's production image or deployment path.

| Item | Current evidence and decision boundary |
|---|---|
| Holder return | The earlier formal assessment reports a 1.96 ETH pool median +70.6%, p10 −55.3% and 5/16 losing years. D86 does not re-run that model's demand assumptions. |
| Recipe and purchaser | 0.06 ETH direct-minted packs, 0.06489617486338 ETH backing and fixed 2 gwei purchaser gas assumption remain unchanged. |
| Timing transfer | In a real FWA allocation replay, pricing a 1 ETH new deposit before a purchaser keep shifts 1,057,625,183,394,753 wei of marked value to it. Its claim remains below its entry payment before exit and gas. The 10% allocated exposure limit bounds gross keep revaluation at 0.707869% of pre-flow NAV at a 1% settlement fee, or 0.816029% if FWA's owner sets the fee to zero. The live incumbent and realized-exit cases remain open. |
| Cancellation repair | Refundable deposit escrow no longer suppresses liquidation needed for an existing redemption. Unused checkpoint charges become protected, payer-specific refunds if all flows cancel. A sponsor still pays when another holder's request reaches checkpoint. |
| Checkpoint pay | The fixed 360,000-gas component plus configured work fee remains at the approved 0.0002 ETH ceiling in the 0.5 gwei case. The new full holder-flow fork sample is 361,202 gas and costs 0.000180601 ETH at that ceiling; the total quote covers it. Signed receipt evidence remains open. |
| Payment receipts | D84's bounded 32-entry valuation and forced-kick residual remain. A forced refund after FWA owner changes its oracle exemption can overstate NAV until a permissionless sync; an ordinary depositor cannot lift that exemption. |
| Assets and spending | Asset-flow outcomes O1–O11 and keeper routine/essential caps are unchanged. Their old signature is invalid for this bytecode. Current approval is absent. |
| Release readiness | Fresh production image rehearsal, deployment rehearsal, owner acceptance and broadcast authorization are outstanding. This PR authorizes none of them. |

The executed attack matrix, exact fork values, economic scorecard and independent review limits are in
[checkpoint-timing-adversarial.md](../receipts/checkpoint-timing-adversarial.md). Earlier packages
remain in `docs/release/history/` and git history.
