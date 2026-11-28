# Independent manager quote calibration review

**Closed for the focused local calibration step.** The three revised manager quotes cover the measured cold keeper calls at 0.2 and 0.5 gwei, including exact signed-call estimates. This permits the lead's affected verification and the same 960-path assessment with the revised inputs. It establishes neither production approval nor manager-owner profitability.

## Scope and immutable inputs

Independent read-only review of the helper, raw receipts, combined gas profile, production keeper acceptance and transaction reservation code, configuration ABI/hash, and the two-file historical scorecard repair. No model, test, fork, network, transaction or production service was run by this reviewer. Read-only Python checked hashes, decoded actual calldata/logs, and recomputed integer arithmetic and profile curves.

| Input | SHA-256 |
|---|---|
| `keeper/rehearse_manager_calibration.py` | `e66ab79a094e08b78eff44b6dfbccdbaca0f43fe4dc375461b567bdc3ca28e79` |
| `docs/receipts/manager-calibrated-receipts.json` | `2b8e6771aa2259c7a6782b109fa19a8ea15c325aba44be91c0366e18bc845099` |
| `docs/receipts/manager-calibrated-cost-calibration.json` | `3a1aa82707e1ef9e6116ad32b7bcdfb5ac6ae44c801a3b383cb3c169a3229137` |
| `docs/receipts/manager-calibrated-executed-source.json` | `8eed7a5a26106678cf4e0d9dfc626e51a72a75eff2683f866ca472427fe7c359` |

The archive's source text hashes to `cafe94a56831c66e65cf9988407716d25f16073c0a75069932fe2c44d92e3319`, matching the raw packet's executed `scriptSha256`. Its diff against the reviewed helper only assigns newly created account metadata and expands profile source bindings. Transaction construction, calls, funding and assertions are unchanged. The current helper hash is the packet writer, not a claim that its later metadata edits were executed.

Runtime hashes in the profile match current files and the raw packet. The allocated and returned native checkpoint hashes remain respectively `901c621ef350f0902a946dc90c3d50186f7e770f2bbc740fb9d8f6c6891ed114` and `0df9ac947e8b5ca6696cac43ddfb4746e468b3c8980bf659c70a12825cc7f8f1`. Import code compares every recorded balance, nonce, code and storage field after loading: 4,452 allocated fields and 4,965 returned fields. The returned import starts from the untouched bare snapshot. This reuses the independently reviewed authenticated checkpoints; it does not fabricate counterparty state or events.

Historical inputs remain byte-for-byte unchanged:

- Baseline helper: `9749cd2d15aa9ade8423dc08395aab6b37736e60b92a420af67903c201a805b5`.
- Baseline 69-receipt Osaka packet: `eb1ff1c81cfe085e46515bbaf0c9d474284cd092271654efb4652fc5b63b5beb`.
- Baseline gas profile: `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`.

## Findings closed

**Only manager quote data changed:** selected 180,000 → 225,000; synced 120,000 → 285,000; list base 280,000 → 380,000. The deployed-value diff contains exactly those three edits. ABI-decoded parameter tuples match the baseline with those edits. Pack principal remains 0.03 ETH, backing remains 0.21 ETH, float remains one, accepted mint-fee maximum remains 0.001 ETH, and other economics remain unchanged. The local observed mint fee is set to 0.0005 ETH through the actual Shapes EOA admin. No shared-vault deployment is involved; the shared vault is undeployed.

The raw packet contains 43 successful receipt observations, with 29 distinct transaction hashes. Snapshot-restored independent branches can repeat an identical transaction hash; these observations are not one portfolio or 43 distinct broadcasts. All receipt statuses, transaction/receipt identities, gas limits, effective prices, gas-used costs and `KeeperPaid` event amounts reconcile. Execution is Osaka on chain 31337, with Tenderly mainnet parent 26,385,000. The owned node recorded PID 67678 and loopback port 18784 at execution; this review does not assert its continued liveness.

There are **10 ordinary cold-history CLI calls**, four owner-exit CLI calls sharing durable state, and two explicit allocated-only sync executor calls. Each ordinary CLI run starts with no counted transactions. Real getter results bootstrap the local position cache; subsequent logs use the unmodified production index. The explicit allocated-only samples prove executor acceptance, not that the planner schedules its deliberately deferred job.

The actual parent-block primer makes next-inclusion base fees exactly 0.15 and 0.45 gwei, with a 0.05 gwei tip. Every included receipt has the corresponding 0.2 or 0.5 gwei effective price. This avoids an estimate/payment comparison under an assumed future fee different from the executed fee.

Production acceptance uses the unpadded call estimate times `billed_ratio`, with zero requested loss, zero fail-rate allowance and zero minimum-return setting. Cold ratios are sync 0.93, list 0.98, build 0.92 and renew 1. The exact signed `minPay` is 80% of the quote; decoding each paid transaction confirms that floor and the current configuration hash. The signed call is reestimated before submission. Its gas limit is padded 25%, stays below 16,777,216 gas, and is distinct from the profitability estimate.

All amounts below are wei. Each operation is real work count one.

| Operation | Payment at 0.2 gwei | Actual gas cost at 0.2 | Payment at 0.5 gwei | Actual gas cost at 0.5 |
|---|---:|---:|---:|---:|
| Allocated sync | 74,400,000,000,000 | 70,464,000,000,000 | 186,000,000,000,000 | 176,166,000,000,000 |
| Resolved sync | 111,000,000,000,000 | 86,360,000,000,000 | 247,500,000,000,000 | 215,900,000,000,000 |
| Combined sync | 160,400,000,000,000 | 104,489,400,000,000 | 371,000,000,000,000 | 261,228,000,000,000 |
| Fresh renewal | 487,000,000,000,000 | 368,308,400,000,000 | 1,127,500,000,000,000 | 920,749,000,000,000 |
| Reuse listing | 261,000,000,000,000 | 227,692,200,000,000 | 622,500,000,000,000 | 569,236,500,000,000 |
| Fresh build | 415,000,000,000,000 | 378,153,400,000,000 | 977,500,000,000,000 | 945,364,000,000,000 |

Every sample has positive actual compensation less gas cost and passes its production cold acceptance threshold using the exact signed estimate. The smallest actual keeper margin is 3,936,000,000,000 wei; the smallest signed-estimate acceptance margin is 2,743,000,000,000 wei, both allocated sync at 0.2 gwei. These are positive measured margins, not a guarantee under competing transactions, state changes or different work sizes. The 80% floor alone does not guarantee a profitable inclusion.

Both opening clones are created with exactly 0.5 ETH through the real factory. Decoded calldata matches candidate parameters, intended owner and `keccak256(abi.encode(params, actualMintFee, false, false))`; emitted `ManagerCreated` account and funding match the packet. The source enforces that quote hash before clone initialization. Creation is a separately billed setup call and is not included in the owner's exit cap.

The 0.2 gwei clone then sets all routine/essential caps and daily rates to zero through a decoded real owner call. Four owner-funded CLI calls set exiting, recover-unlist, recover-liquidate and withdraw. Each pays zero keeper compensation. Their actual wallet gas is **179,592,200,000,000 wei**; summed signed gas-limit times max-fee reservations are **483,070,350,000,000 wei**. Including the budget-zeroing call gives **533,754,550,000,000 wei**, below 0.01 ETH. Durable state and receipt arithmetic agree. Terminal cash, credit, open listings, idle packs, recovery packs and pending receipts are zero.

The withdrawal event returns **0.498085 ETH** to the owner: 0.5 ETH minus 0.0015 ETH in three primary mint fees and 0.000415 ETH keeper compensation. Owner wallet gas is an additional cost, and the factory creator is a separately funded actor. This branch is not presented as a single-wallet owner return proof or a monthly assessment.

The combined profile contains **73 samples**: all 59 historical samples preserved in order, plus 14 new samples (12 paid operations and two creations). Every input hash matches. Recomputing every curve gives the recorded single-work maxima and maximum ceiling slopes. Billed envelopes retain all samples; estimate envelopes prefer genuine RPC estimates when present. Historical signed-limit upper bounds remain explicit provenance. Independent billed/estimate crossing and physical-work protections belong to the already reviewed model; this helper does not alter them.

The historical scorecard repair is limited to `sim/manager_closeout.py` blob `257a3152e77f3bb15b875e033cea7e91e040a4c6` and `sim/test_manager_closeout.py` blob `4c74480debfeec215be2e7901c4b37a0e031350e`. It reads manager values from the immutable, hash-checked R2 receipt instead of requiring equality with today's candidate. Output is explicitly historical R2; receipt, runtime, reconciliation and accounting checks remain. No financial formula changes. The added regression checks that revised candidate quotes cannot rewrite historical receipt settings. The lead owns execution of that affected test.

## Remaining limits and next acceptance

- The same 960-path design must charge these higher quotes with the new profile. The old 960 baseline and its review remain historical; their financial outcomes are not outcomes for this candidate.
- Sync above one completed position and fresh renewal above one pack remain unmeasured. Existing measured counts and extrapolation limits are retained; larger owner scan counts are not multiple completed settlements.
- The 0.005 ETH reserve remains below the conservative maximum listing-plus-sync batch need of 0.0054805 ETH at 0.5 gwei. The CLI honestly reports `RESERVE_BELOW_NEED`. These actual one-work calls pass; this evidence does not prove every maximum batch is reserve-funded.
- The simulation's receipt-history and physical-gas approximations still require disclosure. Separate restored branch samples cannot establish long-run keeper history, owner returns or operational continuity.
- Unlocking task-owned local EOAs exercises the production CLI's fee, quote and reservation path. Hardware/encrypted-keystore transport, live deployment/discovery after a public factory deployment, public canary and live keeper operation remain outside this proof. No public transaction, merge, live cutover or shared-vault deployment is authorized by it.
- The prior image evidence covers the source-bound production runtime. This newer offline calibration helper was not part of the earlier image run; no additional runtime/image claim is inferred.

## Things that don't make sense

- Raising quotes fixes these measured keeper shortfalls by transferring more manager cash to the keeper. Treating that as owner economic viability would be wrong; the revised assessment must include the expense.
- A maximum-batch reserve warning remains despite successful single-work operations. It must stay visible rather than being reported as universally funded capacity.
