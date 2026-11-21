# Independent review: unified candidate (2026-11-21)

Scope: all of `src/` at da332fb plus the bounded proof repair in 4794bf5, read against FWA V2's
verified deployed source (0x958C41181182e76F221331b2755b77D9e1426A98). Informed, not blind, about
three hours. Applied the adversarial audit standard: a security pass and a separate economic pass.
The reviewer built the tree and read the existing fork suites but wrote no new proof of concept: every
candidate defect was refuted by deployed-source facts or already covered by a test. This is scoped
evidence, not proof that no defect exists.

## Result: no critical, high or medium findings

| ID | Severity | Finding | Disposition |
|---|---|---|---|
| S1 | Low | A kick refund forced in while `receive()` fails is not caught by the checkpoint gate; with the ShapePacks oracle exemption lifted, pool NAV can count the refund and the booked position until the kicked listing is synced | Accepted and documented (D84). The full gate would read every open listing per checkpoint. Needs a gas repricing (cold kick receive is 35,148 of 100,000 gas) and FWA lifting the exemption; the keeper syncs on `ListingKicked` |
| R1 | Process (second review, of 958b924) | `requireAllocatedCurrent` walked every tombstone behind an unresolved allocation: unbounded checkpoint and NAV gas | Fixed in 4794bf5: at most 32 entries, constant 31,763 gas refusal, pay per entry and read (`ForkAllocationProof.t.sol`) |
| N1 | Info | A manager owner set to the factory or the manager itself would lock the funds | Fixed: `initialize` rejects both (`test_createRejectsOwnersThatCannotAct`) |
| N2 | Info | `PendingDeposit.checkpointGwei` is `uint32` accumulated per epoch | Not exploitable: the charge is zero once `processingPool` is funded |
| N3 | Info | A checkpoint's unspent `processingPool` joins vault NAV | By design: request charges are not refundable; a small holder gain |

## Confirmed

- Settlement classification from FWA's record is correct and exactly once for every FWA path: keepNFT,
  relistNFT, depositorReclaimBacking, finalizeUnsettled (keep, cash B (1 - s)); acceptDepositorBid,
  acceptBidAsTokens, depositorReclaimNFT (bid, pack back); kickListing (B refunded, pack back);
  withdrawListing (the account's own call). A pushed amount cannot be matched to a different open
  listing: B and B (1 - s) differ by about 6.5e14 wei, far outside the uniqueness window.
- No reentrancy path: every state-changing entry point is `nonReentrant`; keeper pay is the last action.
- Clone initialization cannot be taken over; the implementation is sealed in its constructor.
- `rescue` cannot move a tracked pack.
- **The factory has no access to a manager's funds after creation.**
- **No manager can move or account for another manager's assets.**
- **The pool cannot subsidise managers:** no shared custody or call path exists.
- Backing is bounded by FWA's own clamps (both settlement discounts in [8000, 9500], owner settlement
  fee at most 500 bps): B/P at most about 1.24, and a keep never returns less than the pack's value.

## Economic notes

- FWA's owner can move the surcharge (uncapped), discounts and fees within those clamps. The failure
  mode is "stop building and listing", never a forced loss; sync, exits and withdrawals never read
  FWA economics. The holder-return hurdle is contingent on FWA keeping today's parameters.

## Not covered

No new fork test or reconciliation by the reviewer; share math (redemption index, high-water mark,
dead shares) read but unchanged since B2 and covered by `ForkVaultInvariant` and `ForkReconcile`.
