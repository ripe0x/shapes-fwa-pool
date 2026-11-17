# Independent source discovery, sealed 2026-11-17 18:20 UTC

Target: ba8d26e, source hash 91ad994fd2c1175b18fd8197b3469d04797fb33db7cfcea9d126ead7c476e1b2. This pass read the scoped code and owner requirements before prior audit reports. It also read the system map and selected shipped test comments while preparing harnesses, so it is informed, not blind. No prior audit/ report or DECISIONS Found/Evidence body was consulted before this seal; a title grep inadvertently surfaced short Found/Evidence snippets. The leads below were authored from code first.

## Asset map derived from code

Holder ETH enters escrow plus a nonrefundable checkpoint charge in processingPool. At a checkpoint, deposits net of deployment charge mint shares at post-redemption NAV; deployment charge joins free NAV. Cancels refund escrow. Shares become locked on a redemption request, with checkpoint and unwind charges paid by the holder. A checkpoint moves free ETH and incoming escrow to redemptionReserve, or free ETH to distributionReserve; holder settlement moves either reserve to claimableEth/claimableTotal; claim transfers ETH to the holder. Free ETH buys Shapes plus mint fees, builds packs, posts FWA backing, and pays keepers. FWA returns backing on a keep/silent outcome or unlist, sends bid backing to the purchaser/FWA on bid, and sends fees back to the vault. Packs either return to inventory or go to purchaser. Token rewards go to burn, with no ETH paid.

One-way values: epoch, redeemEra, lastCheckpointInterval, highWaterMark, distribution accumulator, owner pauses/windingDown, cumulative mint fees, FWA bid backing and settlement cuts, burn total. Budgets refill and deplete; they do not solely ratchet.

## Candidate harms to falsify

- H1: FWA owner can repoint floorOracle to a gas-burning contract. VaultLib.economics forwards unbounded gas in staticcall; unlist always calls edge, so wind-down and redemption exits may run out of gas even though oracle failure is meant not to block them. Need fork with hostile oracle and real FWA setter, realistic gas and EIP-7825 limit.
- H2: keeper/policy.py only plans checkpoints with deposits or locked shares; distribution-only checkpoint may be due and payable, but keeper never invokes it. Need fork state with actual due distribution, and policy plan on that state.
- H3: keeper/keeper.py reads free ETH without subtracting processingPool, possibly understating redemption shortfall and skipping unlisting. Need quantify with onchain state and policy plan.
- H4: allocated positions valued at min(pack, net backing) during checkpoint; a later keep outcome yields extra net backing. If checkpoint can run with an allocated listing, exiting holder may receive less than eventual entitlement. Need real selection fixture and holder exit sequence.
- H5: allowed pack size 63 or large activate batch may exceed EIP-7825; need measured gas at accepted settings and determine whether keeper has smaller viable calls.
- H6: deployment JSON casts before bounds checks may silently truncate values; canary sample is in range. Need assess actual failure impact.
- H7: rounding of pro-rata redemption index could strand ETH or overpay; need executable multi-holder partial-fill sequence.
- H8: owner with immediate parameters and policy may drain at most budget plus refill, subject to available free ETH and actual completed work; derive 24-hour/year ceilings and seek manufactured work.

No candidate is a confirmed finding at this stage. Security and economics will be assessed separately. No absence-of-bugs claim follows from this inventory.
