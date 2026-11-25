# Independent manager operating-model review

2026-11-25. **The two identified exit-liveness source defects are repaired on static review.**
Both repairs have permanent regressions present; their execution remains the lead's verification
step. This review accepts no operating return, gas calibration, production setting or release.
No tests, models, public RPC calls or transactions were run for this review. The reviewer's
keeper-readiness slice was excluded.

## Immutable inputs and scope

| File | Reviewed Git blob |
| --- | --- |
| `sim/forward.py` | `592ee1bc092b6a814c1bfbf2937a87988579ea50` |
| `sim/test_manager.py` | `5c6d9557c4054e9cfa73601e1eafa96797096246` |
| `sim/manager_operating_assessment.py` | `eec064fed654dd0cf6ff355af40a35ae772ef0ef` |
| `sim/test_manager_operating_assessment.py` | `7c6b1760dbae8bde9a20f815ba567c51d4d99355` |

The reviewer read the changes and connected model, manager adapter, payment/cash protection,
keeper profitability and signed-spend functions, archive response/burst construction, relaxed
admission helper, result qualification and summaries. This is a focused off-chain model review,
not a new contract security audit or an independent execution of the calibration campaign.

## Findings and repair status

| Finding | Status in reviewed source | Evidence limit |
| --- | --- | --- |
| An unsent `setExiting` intent stopped ordinary keeper work, although the actual manager remained active. A later gas drop could make work payable. | **Source closed.** The intent-based phase suppression is removed; only an executed exit changes strategy flags. | The added quiet high-gas-to-low-gas regression asserts that the unpaid exit attempt does not stop a later paid build. The reviewer did not run it. |
| A denied pending-prefix reservation latched all recovery off forever, including after real archived completions cleared the queue. | **Source closed.** `owner_processing_blocked` clears when actual event processing makes `market_pending == 0`, before the next keeper phase or final cash claim. | The new regression uses an actual archived pending request, a 0.001 ETH cap and a gas spike/drop. It asserts processing-reservation refusal, actual callback completion, later recovery, zero remaining assets and signed spending within the cap. The reviewer did not run it. |
| Empty managers could be charged for unrelated pending foreign requests. | **Source closed.** The owner-prefix reserve requires manager positions or receipts; empty, idle-only and recovery-only accounts skip it. | An actual archived request straddles cutoff in the added empty-account test. No execution claim is made here. |
| An owner recovery reservation could be consumed before a later keeper-payment check rejected the operation. | **Source closed.** Owner recovery returns directly from its final signed-spend preflight, before the modeled operation mutates assets. | Subsequent invariant failures abort the path rather than supporting accepted returns. |

No further concrete cash-partition, keeper-payment or paired-regime source blocker was
substantiated in this bounded pass. Implementation verification belongs to the lead's single
affected test batch; regression presence and source review do not establish that it passed.

## Economic and authority checks

Every path starts with exactly **0.5 ETH** of owner funding and permits no account topup. The
qualifier checks owner withdrawals, physical assets, external credit and unharvested fees
separately. Account expenses partition into keeper compensation, paid primary mint fees,
backing lost and settlement fees; consumed-but-unreconciled keep face is retained separately.
Owner wallet gas includes clone creation and recovery and stays outside account cash. Creator
amounts are gross paid-mint accrual, without assuming a common economic owner.

The independent test partition is: 500 units funded plus 20 earned equals 470 returned, 5 keeper,
6 creator and 39 backing loss. Seven units of separate owner wallet gas make owner net -37;
two units of keeper gas make keeper net +3. This is an arithmetic check, not an observed return.

Ordinary work requires both the fully funded quote and a zero-loss screen against the larger of
the work allowance and billed-receipt floor. Declined work does not mutate the account or invent
a volunteer keeper. This conservative model can decline work that a production keeper, using
its own estimate and billed ratio, might accept. It does not establish future inclusion profit.

The default **0.01 ETH** owner-exit limit excludes clone creation and reserves padded signed
maxima at `2 * basefee + tip`. Owner billing is separate from those maxima. Rejected preflight
does not consume the reservation. Missing owner estimate provenance, unmeasured executed gas,
negative keeper net, hidden funding or broken cash partitions refuse final qualification.

The paired design retains both actual archived monthly request tapes, observed choices and a
separate forced-responsive-bid stress, Fresh and Reuse, 0.21 ETH and hypothetical 0.03 ETH
backing, total gas prices 0.2/0.5 gwei, and mint fees 0.00025/0.0005/0.001 ETH. The first fee is
a fork-only half-current sensitivity. No public fee change is authorized. The 0.03 ETH adapter
changes only admission and is restored after each run; current manager admission still refuses
that configuration. Both backing choices use the same keyed request randomness. No paired
owner-return mean is accepted unless every planned pair has a qualified complete exit.

The live minimum-backing continuity check binds the selected file and verifies its read-only
Tenderly origin, key 22, retained routing, archive baseline, intervening logs and exact
observation block/hash. A stale or mismatched minimum cannot silently enter the hypothetical.

## Remaining limits

The new billed operating calibration packet was not complete when this review ran. No claim is
made that its measurement, size-curve, authenticated-renewal or final operating-result gaps are
closed. Final qualification must bind successful actual receipts, separate owner estimates or
signed-limit upper proxies, and the exact current contract/model sources. Source review does
not replace that execution evidence.

Recorded foreign demand and weights do not react to the manager. Response follow-up is unequal
and right-censored. The recorded month repeats through the exit tail; the quiet and two-day burst
regimes use their stated separate tapes. The fixed descriptive cohort is agent-selected; it
establishes no future-market confidence, APR or owner-required sample size. Gas floors plus
work allowances remain proxies rather than exact bills for every batch.

The shared vault is undeployed. Public transactions, production fee changes, live application
or keeper cutover, acceptance signatures and merges remain outside this evidence.

Things that don't make sense: treating source review as completed calibration; treating a cap
refusal as an executed exit; charging an empty manager for unrelated foreign work; or calling
the isolated 0.03 ETH hypothesis a production configuration. Completed operating calibration and
the lead's affected verification remain explicit follow-ups.
