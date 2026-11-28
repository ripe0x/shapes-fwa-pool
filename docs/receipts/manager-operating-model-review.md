# Independent manager operating-model review

2026-11-25. **The identified exit-liveness and gas-accounting source defects are repaired on
static review.** Permanent regressions cover the disputed states; their execution remains the
lead's verification step. This review accepts no operating return, production setting or release. The completed
calibration packet is reviewed separately below, with its remaining size limits.
No tests, models, public RPC calls or transactions were run for this review. The reviewer's
keeper-readiness slice was excluded.

## Immutable inputs and scope

| File | Reviewed Git blob |
| --- | --- |
| `sim/forward.py` | `f1ed9f7f0da97f7271c5b17a5067913e0be69a33` |
| `sim/test_manager.py` | `abbfd1fbb77476c55849e956c6c6b0d58d95d0d6` |
| `sim/manager_operating_assessment.py` | `3aab6ade10c75cd116a8fa8c2949d99c2556c4f6` |
| `sim/test_manager_operating_assessment.py` | `8b0512dcac67009dd8bea8274657751713f1f724` |

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
| An operation-wide large-batch bill could price a single item as the large batch. | **Source closed.** Per-operation curves use a single-work baseline plus the maximum observed incremental slope and retain the physical work allowance. | Counts are checked against actual operation limits; one/eight-item arithmetic and sample-envelope qualification are covered by regressions. This is an envelope over recorded samples, not every future state. |
| Payment eligibility could be zero while a sync still consumed physical journal work. | **Source closed.** Physical base, consumed entries, scanned positions, selections, resolutions, pruning and actual fee collections are counted before reward eligibility can zero the payment basis. The same physical basis reaches preflight and billing. | The 127-record refunded-archive regression asserts zero reward, 2,919,000 units of physical work allowance, positive owner gas and an intact journal/position when the cap refuses the call. |
| Billed-gas profitability was substituted for the keeper's estimate-based acceptance. | **Source closed.** Ordinary acceptance reuses production estimate-based receipt-history ratios, with an additional known billed/physical cost floor. The ledger still uses billed gas. | Positive actual receipt margin alone is insufficient; the concrete combined-sync counterexample is retained below. The final mode reuses production ratios; the earlier ratio-1 control is retained as a deliberately conservative comparison. |
| Independently fitted estimate and billed curves could cross between measured counts. | **Source closed.** The owner helper takes both curves. Ordinary admission checks the estimate/history decision and the known billed/physical floor independently, preventing an accepted modeled loss. | A pure crossing example has billed 500 versus estimated 452 at count 3; payment 475 is refused and 510 accepted. |
| An old signed-limit upper could inflate a current actual-estimate baseline. | **Source closed.** Every estimate has an explicit kind. If actual RPC samples exist for an operation, the estimate curve uses those and requires an actual RPC single-work sample; signed-limit uppers are fallback only. Billing retains all recorded samples. | Raw receipt wrappers bind actual RPC estimates; signed uppers must match signed/transaction gas. Mixed-kind and falsely relabeled-RPC regressions are present. |

No further concrete cash-partition, keeper-payment or paired-regime source blocker was
substantiated in this bounded pass. Implementation verification belongs to the lead's single
affected test batch; regression presence and source review do not establish that it passed.

The lead's [history-check packet](manager-operating-history-checks.json) binds the reviewed source
hashes and records exit status 0 for the focused manager and assessment suites, funded/historical
reconciliation, closeout tests and regenerated prior cost scorecard. The lead reports 25 manager
and 11 assessment tests, 43 funded plus 32 historical reconciliation steps, and four closeout
tests. This reviewer checked the source identities and recorded statuses, without rerunning them.

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

Ordinary work requires the fully funded quote, the production estimate/history acceptance
check and a separate known billed/physical cost floor. Declined work does not mutate the account
or invent a volunteer keeper. The model directly reuses `keeper.billed_ratio`: initial sync 0.93,
build 0.92, list 0.98 and unlist/liquidate 0.80; after three same-label receipts it uses
`min(1, sum(gas_used) / sum(est))` over the last 20. Each cell starts with a fresh keeper and no
other-account history. Accepted ordinary calls add calibrated bill/estimate pairs; owner recovery
adds none. This is proxy receipt history, not a replay of an existing operator's history.

The real keeper also rechecks a larger exact signed-call estimate. Its profitability gate uses
the unpadded estimate; the 25% pad belongs to the signed gas limit and owner cap. Failed inclusion,
replacement/minPay-specific estimate changes and other-account history are not modeled. The
known-cost floor can still decline a call that the production keeper's expected-cost gate accepts.
Neither version establishes future inclusion profit.

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

## Actual billed margin versus cold-keeper acceptance

The Osaka calibration's one-listing combined sync shows why these quantities remain separate.
Amounts below are ETH. Both receipts succeeded at the recorded actual basefee/tip context;
neither was sent by the production keeper's acceptance loop.

| Total price / basefee, gwei | Estimate / billed gas | Compensation | Actual bill | Actual net | Cold sync cost at ratio 0.93 | Cold acceptance shortfall |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 0.2 / 0.15 | 672,484 / 522,121 | 0.0001184 | 0.0001044242 | +0.0000139758 | 0.000125082 | 0.000006682 |
| 0.5 / 0.45 | 672,496 / 522,131 | 0.000266 | 0.0002610655 | +0.0000049345 | 0.0003127105 | 0.0000467105 |

The cold acceptance costs are `int(estimate * 0.93) * actual total gas price`, with zero
accepted loss or minimum return. The receipt hashes are
`0x01077b84fce41cba8299539f7bfa173ef29198524ac8f891606b0fd52c72849b` and
`0x091683a70f54179b355f23d16088a9be3f89a48ef297d7440d17937e8ca82928`, respectively,
in `manager-operating-osaka-receipts.json`. Actual positive margin does not make either cold
keeper send acceptable. No candidate compensation value or production setting was changed to
remove these measured gaps. These gaps are specific to the measured call and its quote, not a claim that every sync
variant or every future receipt history refuses the job.

## Single-build control and final keeper mode

The actual 0.5 ETH fresh-clone samples at the current 0.0005 ETH mint fee have positive actual
margin and pass the production cold build ratio 0.92. Amounts are ETH:

| Total price, gwei | Estimate / billed gas | Compensation | Actual bill | Actual net | Cold build cost at 0.92 |
| --- | --- | ---: | ---: | ---: | ---: |
| 0.2 | 2,107,303 / 1,907,889 | 0.000415 | 0.0003815778 | +0.0000334222 | 0.0003877436 |
| 0.5 | 2,107,326 / 1,907,906 | 0.0009775 | 0.000953953 | +0.000023547 | 0.0009693695 |

The common actual-estimate baseline is 2,107,326 gas. At ratio 1 it costs 0.0004214652/
0.001053663 ETH and refuses both quoted one-pack builds. Therefore idle Fresh/0.21 cells under
that control would be a conservative modeling artifact, not evidence of actual keeper refusal.
The final receipt-history mode passes the cold build check without changing production settings.
The billed proxy baseline retains the larger historical 1,924,916-gas sample, so its ledger remains
conservative relative to these particular new receipts. Operating-period returns await execution;
none is inferred from these four fresh-clone samples.

## Independent calibration and native-import review

The reviewed calibration inputs are immutable in commit
`72a9586fbf100b4e3c3b3bea472968e264902f56`:

| Input | Reviewed Git blob |
| --- | --- |
| `keeper/calibrate_manager_operations.py` | `2cbe58996e33348d10e792931612cd06d23168bb` |
| `test/fork/ManagerOperationsCheckpoint.t.sol` | `4667a47bd148403d49fbec634235098169ed8e8d` |
| `docs/receipts/manager-operating-cost-calibration.json` | `a1a31dd606f6d396d1cb3c0c8d8f2a6f07f0126c` |
| `docs/receipts/manager-operating-osaka-receipts.json` | `e386e67bda22485a3ff03049d890fb9336a19db0` |

The raw packet SHA256 is `eb1ff1c81cfe085e46515bbaf0c9d474284cd092271654efb4652fc5b63b5beb`;
the cost packet is `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`.
Read-only arithmetic over existing artifacts checked these hashes, current writer/source bindings,
all referenced receipt-packet hashes, both preserved executed-writer files and exact native
JSON/compressed-byte agreement. No calibration, fork, test suite or model was rerun.

The checkpoint exporter reaches one selected manager listing by replaying the recorded actual
request and authenticated fulfillment against the real MAIN contracts. The fixture pays for its
Shapes and filler listings through real entry points. Its export settings equal the complete
candidate Params ABI. The original same-base bridge checked 1,510 recorded changed storage slots,
including 114 explicit zero writes, plus code, nonce, balance and financial views. Independently
reading the export found all 1,510 slots present with their recorded values. This is execution-derived
state transport, not a replacement counterparty or invented protocol balance.

The Osaka importer checks all serialized fields: 458 accounts/4,452 fields in the allocated native
checkpoint and 460/4,965 in the returned checkpoint. It restores the untouched bare snapshot
before importing returned state, avoiding nonce-max merge contamination. Transport chunking keeps
native account rows intact; metadata is compressed separately. The native artifacts and original
bridge remain preserved with their hashes in the packet. These recorded checks do not prove every
unrecorded external state assumption.

The raw packet contains **69 successful local branched transaction receipts**, with 53 distinct
transaction hashes because restored branches can execute identical signed transactions again.
They are independent samples, not one aggregate cash lifecycle. Read-only checks found no mismatch
in receipt status, transaction chain 31337, gas-limit cap 16,777,216, gas-used/cost multiplication,
or actual transaction gas price. Actual price/basefee pairs are exactly 0.2/0.15 and 0.5/0.45 gwei;
execution is Osaka and compiler target Cancun. Historical Cancun-only bills remain excluded from
new operating calibration.

The final curves use **59 samples: 44 new Osaka samples plus 15 immutable R2 samples**. New
metadata records actual RPC estimates; historical signed-limit upper bounds remain explicitly
labeled. Actual RPC estimates are selected where available, with a required actual single-work
baseline; no upper bound is silently unpadded into an invented estimate. Billing retains all
samples. Fresh and Reuse are measured at all three fees and both prices. Four genuinely new
0.5 ETH accounts have exactly 0.5 ETH opening cash and one paid three-Shape build; all external
wallet setup funding and restored-branch preparation remain separate from owner return claims.

Measured work counts are build 1/3/4, list and unlist 1/3/8, liquidation 1/3, and one work item for
renewal, allocated/resolved/combined sync, harvest, owner recover_sync, processing, creation,
setExiting and withdrawal. Owner recover_sync samples inspect 1/3 IDs but do not establish 1/3
completed settlements. Multi-position paid sync and multi-pack fresh renewal remain unmeasured.
The oracle's owner is a contract; the builder correctly did not impersonate that contract to
invent kick fixtures. The required operation names are covered; size gaps and extrapolated work
allowances are still explicit. No additional substantiated calibration source or packet blocker
was found in this bounded review.

The separate manager-only image record reports CI run 45619850908 at revision
`a81a11cc77e0129a3739597664b492f969df3c3b`. Its eight Solidity and eight actual keeper runtime input
hashes match current files. That image predates later unused offline helpers and evidence files.
Its 1 ETH initial plus explicit 0.5 ETH growth funding is operational restart/exit evidence, not
the no-topup 0.5 ETH operating-return assessment. No claim is made that later offline helpers ran
inside that image. Production signer transport and Fly configuration remain separate gaps.

## Remaining limits

Completed operation-name calibration does not close unsampled work-size or future-state gas
uncertainty. Curves and physical work allowances remain proxies. The completed billed packet
supports executing the fixed conditional assessment; it does not establish its returns, economic
acceptability, release readiness or live keeper profitability.

Recorded foreign demand and weights do not react to the manager. Response follow-up is unequal
and right-censored. The recorded month repeats through the exit tail; the quiet and two-day burst
regimes use their stated separate tapes. The fixed descriptive cohort is agent-selected; it
establishes no future-market confidence, APR or owner-required sample size.

The shared vault is undeployed. Public transactions, production fee changes, live application
or keeper cutover, acceptance signatures and merges remain outside this evidence.

Things that don't make sense: treating actual positive billed margin as guaranteed keeper
acceptance; treating conservative ratio-1 idleness as actual production failure; combining
restored calibration branches into a portfolio return; or calling the isolated 0.03 ETH hypothesis
a production configuration. Unsampled sizes and final operating results remain explicit limits.
