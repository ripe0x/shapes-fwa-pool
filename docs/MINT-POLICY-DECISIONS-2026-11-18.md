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

## Second-pass review (original request revisited)

The first PR was mostly a research artifact and could not satisfy "implement and
simplify the complete vault". This pass intentionally favors small changes
that can be validated against the existing system instead of shipping an
unreviewed factory, global NAV rewrite, or persistent optimization engine.

### Bugs corrected

- FWA exposes `stagingHead` separately from its unsettled acquisition count.
  A zero acquisition count does not imply that a freshly listed pack will
  become active immediately. Both `restock` and `list` now refuse to spend
  paid mint or listing capital while an old staging backlog exists.
- The keeper maintains `queue_drained` and `staging_empty` as separate
  fields: exits, checkpoints and activation remain possible while the
  staging backlog exists. Conflating these gates deadlocks activation.
- Liquidation planning uses original per-position pack units and recorded
  backing when withdrawals are pending, not a new 3-unit pack's backing
  quote. The extra RPC calls are omitted from normal keeper passes.
- The research model now charges rounded whole initial mints, construction
  and listing gas, keeper fees and seeds for independently deployed vaults.
  Initial construction costs are subtracted from net-year P&L, including
  when there are no acquisitions.

### What remains deliberately unimplemented

- Any onchain systemwide cap on FWA selection share; a second vault can
  otherwise bypass the first vault's quota.
- New whole-shape pack construction and combined mint/list operation.
  These require bytecode-size and gas measurements and fork reconciliation.
- A genuinely uncapped one-vault NAV. Current 300 position bound is retained
  to avoid an impossible checkpoint.
- A factory of multiple independent vaults. This is the likely least invasive
  capacity solution, but its seed requirements and global admission contract
  have not been implemented or audited.
- Production adaptive sizing or a guaranteed mix of 0.05/0.1/0.2 packs.
  The current live keeper still builds 0.03 packs only.

### Release condition

Do not merge as deploy-ready until full FWA mainnet fork tests, the
accounting reconciler, measured worst-case gas, asset-flow signature updates,
and independent security review pass. A successful Python CI job alone is
insufficient. Never claim any percentage of certainty on a new mainnet
fund-holding contract.
