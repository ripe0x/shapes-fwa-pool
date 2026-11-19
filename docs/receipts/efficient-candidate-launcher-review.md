# Independent review of the amended candidate launcher

What this change does: prepares an exact owner amendment for one measured-work candidate, then reuses the completed baseline's node, entry state and cumulative spending ledger. This is a bounded static review of the launcher, recovery helper and affected runner calls. No reviewed module was imported; no test, RPC, process or chain action was executed by this reviewer.

## Findings and repairs

1. **Toolchain freeze repaired:** preparation originally recorded tool versions without requiring equality to the approved original. It now compares all three versions to the original plan and requires the complete original artifact key set.
2. **Optimized-Python authority bypass repaired:** mandatory approval/freeze checks use assertions. The launcher now rejects optimized Python before importing execution modules, preserving those assertions. The producer's archived optimized-mode refusal reports exit 1 with the descriptor unchanged and no RPC/broadcast. I inspected the guard and that record without rerunning it.
3. **Concurrent double-start repaired:** the launcher now acquires a nonblocking exclusive `fcntl.flock` on the fixed baseline directory’s `candidate-execution.lock` before reloading the execution-side baseline. The open file remains held across construction, attachment, all actions and failure handling; a concurrent invocation fails closed. Sequential reuse still fails the completed-baseline phase check. The producer archived a successful two-independent-opens lock refusal and preserved an invalid shared-open-description probe as such. I inspected source and that evidence, without executing a concurrency test.

## Authority and preserved execution checks

`--prepare` records a descriptor; it does not start a node or fund actors. Execution requires the explicit amendment flag/hash, the on-disk descriptor and freshly prepared descriptor to match. The original plan hash remains fixed. Source exceptions are confined to the reviewed library/policy amendment; all other original execution dependencies remain frozen, with the launcher/helper added to the new freeze. Full source hashes replace the old literal-only normalization intentionally: the extra 80k proof component requires exact new owner approval.

The runner loads the completed, restored baseline and preserves its counters. The candidate constructor uses the original candidate profile, then the launcher sets its PID before installing the helper. `attach_candidate` checks the same node/fork and actual entry head, actor balances, nonces and code. It follows the candidate branch, never `start()`, so there is no new node, balance funding or topup. Sequential reuse stops after the global phase advances; failures preserve node and counters rather than restart automatically.

The timestamp adapter changes only the pending timestamp to parent+1, retaining the existing executed fee-context checks. The no-gain adapter records the genuine planned candidate, exact sender preflight, zero offer and default profitability rejection. It checks all six actor nonces, head and cumulative counters remain unchanged. It does not fake candidate absence or broadcast a zero-offer call. Snapshot logging observes existing snapshot results; the historical snapshot-number derivation is not used by this candidate.

The HTTP2 retry wrapper repeats only dry dispatch, at most three attempts, retains attempts and verifies unchanged transaction/value/action counters. Send-time preflight equality, signed-minPay estimate, nonce, receipt status, actual fee, payment/native inflow and padded transaction-gas limits remain in the original runner. Calibration measurements using operator `minPay=0` remain distinct from normal keeper acceptance.

Vault runtime comparison masks only compiler-declared immutable/link ranges, checks all remaining bytes and length, and supplements the original deployment/library checks. Normalization alone does not authenticate masked addresses; frozen production deployment inputs and existing postflight/getter checks remain necessary.

## Economic scorecard

| Boundary | Preserved value |
|---|---:|
| Completed baseline broadcasts |318|
| Candidate planned maximum |199|
| Included repair allowance |20|
| Combined planned plus repairs |537, below 540|
| Baseline cumulative external call value |17.501610827424708864 ETH|
| Remaining under 32 ETH hard limit |14.498389172575291136 ETH|
| Original initial wallet funding |8.3 ETH|
| Additional funding/topups |0|

The baseline result and global ledger agree on 318 transactions, that call value and PID 96649. Gross external call value counts repeated snapshot branches; it is not net spending or earned income. The original runner reserves cumulative limits before sending, without restoring them with chain snapshots. A one-off owner gain is a fixture contribution, not recurring strategy funding. This launcher does not resolve O2, repeated harvest expense, sustainable cash funding or depositor returns.

## Reviewed bindings and status

- Original plan: `1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd`.
- Original unchanged runner: `bd54f4eabd3fe7239fc8c1f0694c48c4ada7d835e55ae281eb765fedfda65b0c`.
- Baseline result: `36456b7191f6b9b47c9d609636ecbd461ebb18afaaed5a65462678d4ded6252f`.
- Recovery helper: `e9186a9fa591260d6d00be1573c0f1287d64c4c73b9c5660c212760801ae175b`.
- Final launcher: `abaa9f45ef303829f2bd7350cd482132f5d9a49da829648bf9237b5e6979ca88`.
- Final still-unapproved descriptor: `23aaa40e8dd8d8cdaac03ba3662bb83dc39b3ef64d5b17c8d5a5a7687af99089`.

**Verdict:** the three identified guard gaps are closed in the final reviewed source. All 19 source hashes and all four current artifact-template hashes matched the final descriptor during read-only inspection. No remaining actionable defect was found in this bounded launcher review. The exact descriptor still needs owner approval before any candidate broadcast; this report supplies no such authority.

## Things that don't make sense

- The required file lock must remain held for the full run; a phase flag alone cannot enforce a once-only cumulative budget.
- Measurement refunds, fixture gains and restored wallet balances cannot be treated as strategy yield or new funding authority.
