# Approved baseline receipts and prepared quote candidate

The approved baseline passed on the owned 8559 Anvil fork at 26,418,539. It used 318 of 540 transactions and 17.501610827424708864 of 32 simulated ETH aggregate transaction value, including all restored branches. Initial funding was 8.3 ETH once; no topups. The entry head and six funded actor balances/nonces/code were restored; automining is on and the pool empty. 8557 was untouched. Full evidence: `efficient-journal-baseline-results.json`, its cumulative ledger and preserved failure/resume records.

The baseline used 85,000 ordinary/tail base and 30,000 per record. Authentic new requests expired at their actual 30-block deadlines and were processed/refunded, not supplied successful service answers. Natural prefixes 1–128, 40 actual Active positions, 0.2/0.5 gwei and default/maximum 10% policy offers were exercised. These are refunded foreign records. They do not establish exposed successful-foreign execution costs.

## Actual standalone transactions

| Baseline path, default policy | Estimate | Billed gas | Payment at 0.5 gwei | Ordinary profitability gate |
|---|---:|---:|---:|---|
| Holder singleton |127,391|122,411|0.0000575 ETH|Declines|
| Distribution singleton |207,233|202,253|0.0000575 ETH|Declines|
| Holder32 |643,029|638,049|0.0005225 ETH|Accepts|
| Distribution32 |722,877|717,897|0.0005225 ETH|Accepts|
| Full128 holder |2,238,040|2,233,060|0.0019625 ETH|Accepts|
| Full holder checkpoint |377,803|346,017|0.0002 ETH|Accepts|

The same default singleton bills and gate outcomes occur at 0.2 gwei. Maximum policy markup makes the holder singleton acceptable under the ordinary shared gate, but the distribution singleton remains declined. An operator deliberately sending a loss-making measurement is not keeper willingness. Recorded preflight uses the actual sender, exact calldata, signed80% `minPay`, inclusion fees,25% transaction-limit padding and unchanged shared profitability gate. Padding is not billed gas.

The full-holder checkpoint was prepared through separate transactions, with an existing partial redemption and protected reserve, a new deposit, a gain fixture and a payable distribution. Its billed gas is346,017 at 0.2/0.5/2 gwei. Payments are 0.000092/0.0002/0.00074 ETH; costs 0.0000692034/0.0001730085/0.000692034 ETH. Protected buckets and claim readbacks pass. The1 ETH owner transfer creates this test gain; it is not earned income or an operating subsidy. Q360 has13,983 gas (4.04%) headroom against this one bill; total compensation also includes the existing work fee. This closes the named standalone fixture gap, not every checkpoint state.

Inventory receipts at 0.2 gwei billed2,754,533/599,757/2,928,345 gas for first primary mint/leftover-only/mixed-two-pack cases. All corresponding0.5 gwei proposals were economically unavailable and sent no transaction. The original plan therefore forbids lowering Q_PACK; it stays 325,000. O2 remains 1,919,655 versus 1,750,000. O6 remains0.0002 ETH versus its 0.0002 limit in the fresh affected scenario.

## Exact candidate, not yet broadcast

The distribution proof costs 79,842 more billed gas than the holder singleton and 79,848 more at 32. The original candidate family allowed a tail base of at most 160,000 and records at most 30,000. Its maximum singleton 190,000 still underpays the202,253 distribution bill. This is why a new owner amendment is necessary.

| Option | Singleton holder / distribution quote | Consequence |
|---|---:|---|
| Original family maximum |190,000 /190,000|Distribution remains12,253 gas short of the measured bill|
| Common200,000 tail plus22,000/record |222,000 /222,000|Pays99,589 gas above the holder bill|
| Recommended separate proof work |132,000 /212,000|Pays9,589 /9,747 above the observed bills|

Prepared source keeps ordinary base 85,000 and Q_PACK 325,000, sets records 22,000 and holder-tail base 110,000, and adds 80,000 only for a successful qualified distribution-only tail proof. Full jobs, actual own work, failed proofs and unexposed advance receive no proof component. The augmented quote also enters the distribution's cost test. At0.5 gwei holder/distribution singletons pay0.000066/0.000106 ETH, against baseline costs 0.0000612055/0.0001011265 ETH. Candidate execution/estimates may differ and remain unmeasured.

No predicate, storage, Params, ABI, request charge, deployment charge or unwind charge changes. A higher proof cost can reject marginal distributions; a lower cycle quote changes numerical edge/backing floors. These economic effects are explicit. The contract/model mirrors, five focused real-counterparty tests, fourteen accounting tests, keeper policy, two fork/Python reconciliations and two affected economic scenarios pass. Runtime is24,451/23,001 bytes, leaving125/1,575. Independent source review found no actionable defect. The exact amendment and reviewed launcher preserve the same node, actors, original 540/32 cumulative bounds, initial funding and one candidate; no candidate broadcasts have run.

## Funding and return decision stays open

Perfect packing of the archived 18,281 records into 143 jobs costs 0.207221 ETH at 0.5 gwei with one final qualified distribution tail (0.207181 with a holder tail), before actual own work or additional tails. This remains above mainnet's0.15 ETH steady refill over30 days. It is arithmetic, not measured billed gas or a return forecast. Vault cash supplies expenses; permission supplies no ETH. Creator mint revenue is separate and not an assumed subsidy.

The new opt-in timed model uses actual 3600-second expiry and distinct open/blackout timestamps. Its short paths remain conditional, not fork-matched operating-return evidence. The historical 112 daily-model outputs remain hypothetical diagnostics. Repeated active-fee harvesting and underpaid holder harvests are additional economic blockers: complete exits do not establish funded routine operation. No allowance, minimum TVL, outcome signature or harvest policy was changed.

## Preserved execution repairs

- ABI-only Deploy cache failure occurred before any transaction. Exact frozen bytecode was restored with the installed pinned compiler; clean wallets/nonces/head proved the provisional reservation could be released.
- Pending timestamps changed mint gas estimates. The operator pins the next timestamp to parent+1 while retaining exact-estimate, affordability, normal gas/code and receipt checks.
- A no-gain dry CLI legitimately prints a candidate; actual preflight sees zero offer and the unchanged profitability gate declines. The operator records that genuine decline rather than falsely requiring no candidate.
- The public fork RPC returned HTTP2 `too_many_data_frames` before sending. Read-only retries resumed only unfinished cases; cumulative prior receipts remain counted. Snapshot IDs are now recorded when actually returned.

These are operator/test repairs, not production behavior changes. Logs and source-specific evidence remain immutable. No public transaction, real fund, reset, new signer, merge or owner acceptance signature occurred.

## Things that don't make sense

- Global upkeep follows unrelated activity while income follows vault capital.
- Frequent harvesting can spend much of gross fees even when the assumed cycle margin is small.
- More spending permission cannot release protected cash or establish acceptable holder returns.
- Refunded receipts cannot fill the successful-foreign gap; accounting equality cannot fill the return gap.
