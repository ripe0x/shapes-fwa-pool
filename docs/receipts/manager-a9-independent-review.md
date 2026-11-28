# A9 manager economics and receipt review

An independent read-only reviewer examined the uncommitted A9 calibration script, model changes, real-counterparty receipt packets and first-path cash flow. This was a bounded review, not a security audit or release approval. The reviewer ran no tests.

## Findings

1. The initial keeper sync acceptance ratio is 0.93 of the RPC gas estimate. For the measured `780000:1:1` context, this predicts 0.0002192938 ETH gas cost against a 0.0001520186 ETH payment at 0.2 gwei, so the keeper declines. The paired fork receipt bills 501,096 gas, or 0.0001002192 ETH, and would have been profitable. The ratio only self-calibrates after three successful sync calls. Other measured sync contexts bill 84–91% of their estimates, so lowering one global ratio enough to admit this job could make other jobs lose money. **Open operating blocker:** a new manager may need owner-paid sync intervention before the ordinary keeper has usable history. Production RPC estimation may differ from this Anvil fork.
2. Four included raw packets were written by intermediate versions of `keeper/rehearse_manager_sync_scan.py` whose exact source was not preserved. The verifier independently checks the authenticated checkpoint hashes, successful billed receipts, exact work events, signed gas limits, source contract hashes and identical paid/unpaid prestates. The RPC estimate is a writer-recorded field rather than a value in the transaction receipt. The billed gas and work events have stronger provenance than the estimate used for acceptance modeling. A strictly reproducible future release packet should rerun the required contexts with one frozen writer.
3. The measurement script exempted every `multi-` branch from its positive-margin assertion, including branches using candidate settings. That assertion is now keyed to an actual calibration override. Candidate-setting packet margins already recorded as positive; this repair changes no gas, payment or model arithmetic.

## Independent cash identity

For the first recorded-month path at 0.0005 ETH mint fee and 0.2 gwei, the reviewer independently reconciled the owner's ETH: 0.5 funding + 0.198837898425720412 FWA fees − 0.42 backing consumed by two bid returns − 0.003 paid primary mint fees − 0.000768 keeper payment = **0.275069898425710412 ETH withdrawn**. The modeled 0.0003430236 ETH owner wallet gas yields **−0.225273125174289588 ETH net**. This is a model path based on archived request timing, not a month of transactions executed by a deployed manager.

The 0.006 ETH reserve withholds an extra 0.001 ETH from new exposure and keeps it available for maintenance when funded. It is returned at exit. It does not replace backing consumed by a bid return or fix the keeper acceptance issue.

**Things that don't make sense.** An inherited estimate ratio can block measured profitable work before it gathers the three samples that would correct it. A reserve increase addresses cash capacity but not the much larger bid-return backing loss. Archived demand and buyer choices cannot establish a future owner return.
