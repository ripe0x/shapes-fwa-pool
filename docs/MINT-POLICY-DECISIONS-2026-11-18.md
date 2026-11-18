# 2026-11-18 research and implementation decisions

Status: research branch only. The existing audited vault is unchanged. This is
not a mainnet-ready redesign; the branch includes a keeper read optimization
and independent pack sizing stress model.

## Business goal

The owner earns on primary shapes mints. Optimize for sustainable demand for
freshly minted shapes, constrained by depositor returns and FWA purchaser
experience. Re-listing returned packs generates no new creator mint fee.
Never burn contributor capital just to mint identical backing again.

## Decisions made autonomously

1. Do not expand beyond 0.20 ETH pack values for the initial design.
2. Keep the current 0.1 ETH paid mint route, splitting into 0.01 parts only
   where necessary. Larger packs can contain whole 0.1 ETH shapes to reduce
   gas without reducing the number of paid primary mints.
3. Treat a 25% maximum share of the FWA selection weight as a modeling
   hypothesis, not an established optimum or production policy.
4. Choose the size for the full funding plan and preserve it across keeper
   batches. Choosing by remaining per-batch cash encourages small-pack flooding.
5. A footprint limit alone does not guarantee variety. Test a small deliberate
   fraction of medium and large packs, limited to 0.20 ETH, against the cost.
6. Keep buyer keep rates and cash-bid values as sensitivity inputs until
   verified by purchaser behavior and net-of-gas incentives.
7. Keep the existing 10% trailing-30-day formal return hurdle, zero token value,
   and explicit slowdown / adversarial tests. Do not lower primary mint fees
   to force a deployment to pass.
8. Prefer independent bounded vaults with shared exposure admission to a
   single uncapped checkpoint. The system-wide number of vaults can grow, but
   share accounting must remain independent.
9. Preserve current accounting, settlement, exit and keeper payment protections
   until each proposed deletion has fork witnesses and is reaudited.
10. New contract deployment and mainnet spending remain blocked pending
    validated Solidity implementation, full fork tests, independent security
    review and a fresh live-rehearsal.

## Evidence and caveats

- Existing forward simulation data came from the 2026-11-16 pool report:
  2,584 listings, harmonic backing 0.0514 ETH.
- The model in sim/mint_policy_research.py is intentionally a compact
  sensitivity tool; it omits inventory batch rounding, staggered FWA states,
  stochastic purchaser behavior, changing acquisitions, and actual keeper
  pricing across multiple vaults.
- Primary mint revenue scales with *new shape backing*, not every FWA
  listing or acquisition. Paid mints must be counted in receipts.
- The inverse-weight share should be enforced by a single coordinator,
  not separately on each vault. External FWA changes can cause the share
  to rise after admission; listings should pause, not automatically liquidate.
- First build and replacement costs depend on actual gas and shape packing.
- No claim of complete implementation or 100% reliability is appropriate.

## Next work before deployment

Implement and fork-test a whole-0.1-shape pack constructor and batch-listing
operation, full-capital size planning, shared-vault registry and guard, keeper
pagination, and corrected live economic gating. Run reconciliation to the
wei against the FWA fork for bid, keep, staged, stuck-NFT, zero-activity,
and full withdrawal cases, then re-review code size and invariants.
