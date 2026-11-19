# Efficient revision: independent affected review

What this change does: journal sync now executes one fixed job with independent limits of 128 global records, 16 own selections, 16 terminal IDs and 16 pruned heads. It uses routine compensation even during withdrawal and wind-down. Restock caches unchanged economics and retains newly split Shape IDs in memory until only genuine leftovers need storage. The keeper gains durable own-allocation/returned-bid discovery and an admission check for known journal funding insufficiency.

This is a read-only affected review against baseline `d1b59f1`, under Ponytail review and the holistic verification guidance. Only this report was edited. No tests, broadcasts, node operations or new remote jobs were run by this reviewer. Conclusions are bounded source review and inspection of other agents' archived evidence, not a full audit or release acceptance.

## Reviewed frozen inputs

| File | SHA-256 |
|---|---|
| `src/PackVault.sol` | `4e82d4428390dd909ec8749ba4dbd032ae3c60932fd0f65185a0098bc786461a` |
| `src/VaultLib.sol` | `ffe76e84dad7afcc48ce622334b6061131a1912761fc74f2b502d6ed7da49f00` |
| `keeper/index.py` | `4f037790c23e6ad51cb67d646c540bca39bb240eda9a0a7c5bdb69aac9910f63` |
| `keeper/keeper.py` | `3fa18566b9021ee35061ea2c7e40648e9fd4502c78e3bdd60a773a39dd98d75e` |
| `keeper/policy.py` | `de7401dab1cb2a34b83d3ce65bcd7daa646232fcae9c1ecab0db2f82200f0142` |
| `sim/forward.py` | `add21d9b695a7bf20603eeefd0c09200abcd4f39673126508d7a98e2d9c7a0fa` |

The exact latest seven user items were requested from the lead because the review follow-up did not inherit that new message. The source findings below do not depend on assigning authority to a paraphrase: one establishes a paid no-checkpoint case, and the other establishes a keeper liveness failure. The lead must bind the final repair to the owner's actual wording and record any consequential refinement.

## Must fix

1. **Distribution enabled is not an actual checkpoint need.** `src/PackVault.sol:332` marks a checkpoint due whenever `distributionBps != 0`, even with no holder flows or eligible distribution. `src/VaultLib.sol:703` then pays a foreign-only short journal tail in blackout with the external queue drained. A reachable case is a vault with real exposure, distributions enabled, no pending deposits or locked shares, and NAV per share below its high-water mark after build/list expenses. Sync earns its full 85,000 plus 30,000 per record quote, while the ensuing checkpoint distributes nothing and reverts `Nothing`. This makes an otherwise unpaid short job paid despite there being no actual checkpoint to complete. Checkpoint's own no-op protection does not roll back a separate paid sync. Make the distribution-only authorization match an authenticated eligible payout, or atomically condition that tail compensation on a checkpoint that performs real distribution work. Keep holder-flow and mandatory own-work paths separate. Add a real no-gain distribution-enabled counterexample and a gain-producing control.

2. **Keeper cannot discover a distribution whose checkpoint first requires a short tail.** `keeper/keeper.py:325` sets `distribution_due` only when an exact checkpoint simulation succeeds. With exposure and a foreign-only backlog smaller than 128, checkpoint reverts `CatchUpFirst` even if a gain would otherwise distribute. `keeper/policy.py:254` schedules that short tail only for an own event, pending/locked holder flow or `distribution_due`. With no other work, both actions wait for the other. Distribution can remain blocked until 128 records accumulate or a new holder/own event intervenes. Resolve eligibility and scheduling together, with a real gain-plus-short-backlog scenario. Do not simply equate the distribution setting with a payable payout. The current forward simulator never supplies `distribution_due`, so its results do not exercise this production branch.

Both findings concern a supported nonzero distribution setting; the current mainnet/canary values happen to use zero. Their zero configuration is not coverage of the permitted branch. These are source-traced concrete cases, not executed reproductions by this reviewer.

## Mechanisms that remain coherent in this review

- The caller supplies only terminal IDs and `minPay`. Irrelevant or duplicate terminal IDs cannot lower the journal read bound, selection bound or pruning quota. A duplicate resolved ID becomes `NONE` and does not earn a second unit.
- The journal stops before advancing past a seventeenth own selection. It still authenticates every consumed request and external position. One lookahead at the next own record remains within the 128-read loop; that unconsumed record stays at the cursor.
- Full 128-record work or an actual own selection/terminal return earns journal compensation. Pruning alone can earn its verified prune component while an unrelated short foreign tail does not earn per-record pay. No completion bonus was introduced. Small unqualified work can advance unpaid with `minPay=0`; positive refused payment reverts its state effects.
- Sync always reaches `_pay` with `essential=false`, including locked shares/wind-down. The model uses the same class. Processing charges and holder reserves remain excluded from `_free`; zero essential budget no longer switches journal compensation off. Unlisting/liquidation funding rules remain separate.
- The keeper pauses new listing/build proposals when the known foreign-only packed backlog quote exceeds either actual free cash or routine permission. That value is explicitly a floor: own transitions/returns, less efficient packing and future work may cost more. It is not evidence of complete funded operation.
- Restock computes one `BackingTerms` before any mint or pack creation, validates every actual backing proposal, and keeps reservation/capital checks. The earlier code already performed all those validations before external mutations, so caching does not span a new mutation boundary. Newly split IDs are consumed in the same reverse order as the old storage stack; old loose IDs are used after fresh IDs, and only true fresh leftovers enter persistent storage. Paid primary mints, mint fees and actual principal accounting remain required.
- The index authenticates FWA source address and depositor for allocation/bid discovery, retains actual bid distinctions, and does not invent an ETH receipt for a token bid. Independent returned/selected/expired/OWED quotas bound candidate hydration. OWED recovery rotates; a delayed older allocation no longer hides a later returned bid.
- Financial and discovery prefixes have canonical-hash checks and transactional compare-before-write protection. Backfill enriches legacy allocation payloads and appends new bid events without resetting the financial index or transaction state. Rollback replays retained events; current position state controls whether historical discovery still requires work. No concrete canonical upgrade/concurrent-repair regression was found in the reviewed changes.

## Gas evidence correction and economic pass

The earlier `342,766` checkpoint calculation, including its use in this reviewer's prior Q360 addendum, is invalid and superseded. In the installed Foundry 1.8.1 isolated mode, `lastCallGas().gasTotalUsed` is finalized transaction gas; its refund has already been applied. Subtracting the refund again understated cost. `restock-efficiency-meter-correction.json` binds the correction to the installed commit and primary implementation. Historical emitted values remain evidence of what was measured, with their former labels/math withdrawn. Actual Anvil billed receipts are unaffected.

Correct current full-holder evidence asserts isolated mode and explicit executed 0.15 gwei basefee/0.2 gwei transaction price. It reports 345,937 receipt-equivalent gas, 29,600 finalized refund and 375,537 reconstructed pre-refund gas. The direct `345,937 <= 360,000` sample guard passes. Component headroom is 14,063 gas, about 4.07%, not the earlier asserted 5.03%. At a matched hypothetical 0.5 gwei, sample cost is 0.0001729685 ETH versus default compensation 0.0002 ETH. The actual 2 gwei essential branch pays 0.00074 ETH from its real request pool and leaves both maintenance budgets unchanged. These are executed-fork receipt-equivalent measurements, not actual signed receipt or keeper-estimate profitability proof. The current full-holder signed receipt remains a release evidence gap.

| Economic outcome | Reviewed result | Acceptance implication |
|---|---|---|
| Seed with no FWA exposure | Existing authoritative unpaid rebase predicate preserved | No new foreign-history seed drain identified |
| Efficient restock | Corrected identical-profile comparisons retain principal, mint count/fee and keeper payout assertions; example first pack saves 36,025 receipt-equivalent gas, about 1.28%, without reducing pay | Real cost optimization; unchanged quotes do not reduce holder payment |
| O2 build/list quote | No component quote changed; ideal marginal 1,810,000 remains above 1,750,000 before bases/mint rounding | O2 remains unresolved |
| Checkpoint quote | Corrected current 345,937 sample below 360,000 component; named O6 formula remains 0.0002 ETH | Bounded support only; actual full-holder receipt still needed |
| Full foreign sync job | `85,000 + 128 × 30,000 = 3,925,000` quoted gas; 0.000785 ETH at 0.2 gwei or 0.0019625 ETH at 0.5 gwei, before markup | Routine allowance and real cash must fund this; larger jobs reduce base count, not per-record cost |
| Fully exposed 18,281-record archived window | At best 143 full/tail jobs: `18,281 × 30,000 + 143 × 85,000 = 560,585,000` quote gas; 0.2802925 ETH at 0.5 gwei before own work | Still above mainnet 0.25 ETH 30-day initial-plus-refill allowance; no new funded outcome established |
| Reserve model | Full listing batch plus 128 global records/16 prunes at configured 0.5 gwei and zero markup is 0.0059225 ETH including listing work fees | Above configured 0.005 ETH reserve; review the resulting status/operating assumptions rather than silently increasing reserve |
| Exit | Routine sync may now be paid while other exit work remains caller-funded under D64 | Existing old-class exit receipts cannot be relabeled as this new class/API |

The 143-job arithmetic assumes a qualifying final tail and efficient packing. If that tail is unpaid and no checkpoint is due, it is not an unconditional payout obligation; actual exposure timing, own work and cadence determine expense. The same quoted global records at 0.2 gwei cost 0.112117 ETH. Budgets are spending permission, not ETH inflows. A routine classification change changes which permission bucket pays, not the underlying recipient or actual cash source. Distributions, requester charges and escrow must not become implicit global subsidies.

The actual earlier refund split counterexample is still useful against a 105,000-base proposal: two-part splitting added 95,878 to 95,902 billed gas, below an extra 105,000 gas-equivalent base even at zero markup. The new fixed full-job API removes the caller's arbitrary batch-size control, so those old 16-record results are not proof of the new 128-record API's complete profitability or anti-splitting behavior. Actual current successful-foreign paid small/full/tail receipts remain missing; the authentic fulfillment route must not be replaced with fabricated VRF success.

## Verification limits and verdict

Inspected evidence includes `restock-efficiency-results.json`, its corrected historical comparison/current full-holder/recent-head/edge-caller logs, `restock-efficiency-meter-correction.json`, and `efficient-return-index-results.json`. The corrected restock comparison reports seven historical cases plus a separately pinned block 26,444,840 recent restock; the executed fee values are declared overrides, not that block's market-price observation. The index evidence uses actual historical ETH/token bid payloads with explicitly synthetic internal SQLite projection setup, real canonical hash reads for the optional check, and no substituted successful service answers. No real 16-own-selection burst or seventeenth-own stop was reached by this reviewer. New journal tests and the approved local receipt scope remain the lead's affected verification responsibility.

Verdict: repair the paired distribution-only tail eligibility/scheduling cases before accepting this efficient slice. The bounded job/restock/index mechanisms otherwise show no concrete new regression in this review. Keep calibration, O2, complete operating funding and release claims separate.

## Things that don't make sense

- Distribution configuration authorizes paid onchain tails when no payout exists, while the keeper cannot unlock a real distribution behind the same tail.
- A larger journal job lowers call overhead but leaves the global per-record expense and actual ETH source unresolved.
- The updated reserve model exceeds the configured reserve even before proposing any reserve increase.
- The historical checkpoint double-refund deduction must be corrected wherever its derived numbers were reused, including this reviewer's earlier report; actual transaction receipts must remain separately attributed.

## Distribution-tail repair review

The owner's seven items are now recorded in `docs/EFFICIENT-JOURNAL-REVISION.md` and appended OWNER-REQUIREMENTS items 22–27. They require enforceable useful paid jobs and actual checkpoint tails, default funding from vault operating cash, unchanged quotes until measurement, and no silent outcome increase. This closes the earlier missing-input qualification.

Reviewed repair inputs are PackVault SHA-256 `5c37dfacbb5e3b7caff12ebdeb2380afc84846d59e46d74c828ef701eca89e12`, VaultLib `4bc92c5cf76dcb51597ee07674a578dcab704dce8bdba8dfb04b1e6c3935f87e`, keeper `30c1af8cc1483561ebefa3b36c110cb7ede200e9b36f8ca922b08e53594d3d0e`, policy `dec3000c2514cc0888c8d2f9c1d2f97344d026984f7b714757fde929ac36422f`, model `a61c38a1ee0747b12b207152087ed359c2fde59a893497150bd9c7763d9a230d`, forward simulator `a028c342a40b8acf9f2fde60198d89be11f60e95c0e6d942745d9a0ef7f95864`. Only this report was edited by the reviewer.

The basic two findings are addressed by mechanism: the keeper may propose a configured distribution tail without requiring an already-successful checkpoint, while the contract authenticates its witness and actual post-tail gain. `sync(ids,witnessId,minPay)` still exposes no batch-size knobs. Holder-flow mode is separate from distribution-only mode. The latter checks completed cursor/receipts/live witness through the trusted vault's strict `accountedNav`, rejects stale/expired allocation heads, subtracts the maximum routine envelope including markup before evaluating allocated exposure and high-water-mark gain, excludes dead-share-only supply, and requires the actual 0.01 ETH distribution minimum. Self view calls remain static and use this immutable vault/library code; no new trusted oracle or accounting storage was added. An incorrect witness disables journal-tail compensation. Other independently verified pruning can still earn its own pay; final `minPay` atomicity applies to the total payout, not solely to the journal component.

**One additional liquidity error remains in this frozen repair.** The helper and model use `idleEth() + feeCredit` as post-harvest available cash. `idleEth()` has already clamped `free - reserve` to zero. Adding credit afterwards loses any reserve shortfall and may overstate actual checkpoint liquidity. For example, with free cash 0.001 ETH, reserve 0.03 ETH, genuinely earned fee credit 0.03 ETH, a sufficient roughly 0.03 ETH gain, 50% distribution and 0.000023 ETH sync cost, the helper sees almost 0.03 ETH liquidity and authorizes the tail. Checkpoint harvests the credit but has only about 0.000977 ETH above reserve after sync, below the 0.01 ETH minimum, and cannot perform the promised distribution. This is a permitted reserve setting and does not require fabricated protocol state; the same clamp error can occur near the threshold with the default reserve. The model mirrors the error, so agreement alone would not discover it.

Compute post-harvest idle cash from the unclamped free cash plus actual harvestable credit before subtracting reserve, or conservatively require already-available idle cash to cover the distribution and let the existing profitable harvest action run first. Keep fee credit in NAV either way. Add a reserve-shortfall/credit model boundary and, where reachable through authentic fee earning, a real checkpoint control. This is a source-traced finding; the reviewer has not executed the counterexample.

The maximum-envelope subtraction is deliberately conservative and correctly prevents sync's own payment from erasing a marginal gain. It does not establish keeper profitability: the required single-tail witness/gain checks add work whose actual estimate and billed cost still need calibration. Mode 0 and wrong-witness paths may still advance unpaid under `minPay=0`; the keeper's real offer/profitability gate must decline those calls automatically unless other legitimate work pays.

Verdict for these frozen hashes: fix the remaining reserve-shortfall liquidity calculation, then review the affected repair and its focused proof. The two original distribution defects are addressed in design, but are not closed as complete while this false-positive distribution case remains.

Things that don't make sense: adding income after a clamped reserve calculation loses the cash needed to refill that reserve; a shared Solidity/model formula can agree while authorizing a checkpoint that cannot distribute.

## Reserve-clamp repair: affected source findings closed

Reviewed final repair inputs: PackVault `448106b8915413badef411355a5cb729ca15046743be768919d74e9349ddcd8b`, VaultLib `1a5407f1044f0e79b874ee77cd6936bb53438b020f4c8e093db200909990490f`, model `e958d86859ff9ddd9e2766459683f77cf9caea9ac87691be6360d2e92614ba7a`, model tests `b8234fa12d05967abfe7cc92a636d98a3ec46b5eed9f82b40c91b0bbf181e508`, keeper policy `f81b900b60371f59ddfb93c92e65baea364184a0100e1a35c3b3aabedd55bd4d` (all SHA-256). This section supersedes the prior verdict that the liquidity calculation still needed repair.

`freeEth()` is one new read-only view of the existing `_free()` calculation, with no new authority or accounting state. The helper reads it after sync work and calculates `free + harvestable feeCredit - reserve - maximum sync cost` in the correct order, with explicit insufficient-liquidity guards. Distribution-only mode has no locked redemption estimate or pending deposit to treat as cash. Existing redemption, distribution and claimable reserves plus the processing pool remain excluded by `_free()`. Credit remains part of NAV, and its later withdrawal merely changes custody. The public view avoids carrying a stale pre-operation balance into the payment or proof.

The model uses the same unclamped expression and explicitly rejects holder-flow states in its distribution-only helper. Its regression constructs the reported boundary through a genuine model deposit, five paid ten-Shape mints, fourteen three-unit packs/listings and exact backing, leaving 0.001 ETH free. Raising reserve to 0.03 ETH and adding 0.03 ETH fee credit no longer authorizes a 0.000023 ETH tail: after actual model receipt, only 0.001 ETH is idle and checkpoint still rejects `Nothing`. This is pure accounting-model evidence, not a real FWA fee-credit counterparty test. The real no-gain and 1 ETH gain controls use actual FWA refund history and actual vault calls.

`Q_REQUIRED_TAIL` is initially 85,000, exactly equal to `Q_SYNC`. This names a distinct already-qualified short foreign checkpoint job, not a completion bonus or an increased payment. Its base is used only after actual qualification; full 128-record jobs, own selection/return work and prune-only work retain the ordinary sync base. The distribution proof subtracts the same selected tail base, actual record component and actual prune component with the maximum routine envelope. The forward model selects the same base and checks the same gain/liquidity boundary. A future numerical tail change would need its own measured cost and anti-splitting analysis; this review grants none.

Source finding status: both original distribution eligibility/scheduling defects and the subsequent reserve-clamp defect are closed in these reviewed mechanisms. No new actionable correctness regression was found in this narrow repair. The lead reports fourteen model tests and five real FWA journal tests passing on these hashes; those runtime claims remain subject to their archived command/source/log binding, which the lead is preparing. This reviewer did not rerun them.

Verdict: no remaining source repair is requested by this affected review. Numerical compensation, current signed receipt profitability, complete funding/holder return evidence, legacy caller migration, bytecode limits and release readiness remain the lead's separate work. The current reported 24,451-byte vault has 125 bytes of EIP-170 space; future source changes require a fresh size check.

Things that don't make sense: maintaining a reserve in code does not supply recurring operating ETH; the 128-record current quote still exceeds the configured steady refill under the recorded high-price window; unmeasured successful-foreign tails and actual full-holder receipts cannot be replaced by a passing accounting model.


## Lead evidence binding after the affected review

The lead archived the reported runtime checks in `efficient-focused-results.json` and its hashed
logs: five real FWA journal/distribution regressions, fourteen accounting model tests, affected
production caller repairs, seventeen lifecycle/selection callers, authentic unexposed historical
processing and five minimum-seed/cash-only callers. `current-three-arg-reconciliation-results.json`
binds both refreshed exact accounting traces and receiver samples to the final production hashes
above. Its full-cycle executed0.4gwei BASEFEE/0.45gwei TXGASPRICE probe now closes the fixture gap;
observed keeper payouts remain inputs to reconciliation rather than independent quote proof.

After review, the keeper's theoretical reserve warning became informational, while the actual
known-backlog cash/permission admission gate remains. The essential-budget status now names
unlisting/liquidation precisely, since sync is routine. A pure shared `profitability_gate` extracts
the unchanged cost/minimum-return comparison from `run_pass` for the signed receipt runner.
The lead inspected that extraction; no new independent reviewer execution is claimed here.

No numerical quote has changed at this binding point. Current combined-limit and authentic
successful-foreign billed gaps remain. The standalone receipt batch requires separate owner
approval of its concrete limits. This binding is by the lead and does not extend the independent
reviewer's scope or establish economic acceptance.

Things that don't make sense: finalized Foundry refunds cannot be subtracted twice; unchanged
quotes pass execution savings to keepers until a measured numerical calibration reduces holder
expense; bookkeeping agreement alone cannot establish complete profitable operation.
