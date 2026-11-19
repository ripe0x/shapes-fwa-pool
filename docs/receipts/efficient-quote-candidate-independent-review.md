# Independent review of prepared Option C

What this change does: lowers the global-record quote to 22,000, separates the 110,000 holder-tail base from 80,000 of distribution-proof work, and mirrors those amounts offchain. **No actionable payment-eligibility defect was found in this bounded source review.** This supports presenting the exact amendment for owner approval; it authorizes no broadcast or economic acceptance.

## Immutable scope

Reviewed against commit `15348d1e89c18eefe00349615a9092911c123d17`:

| Input | SHA-256 |
|---|---|
| `src/VaultLib.sol` | `8223991816433e0aff0b50253d6daa212d822f5545ad53ca04482efbf94d5252` |
| Unchanged `src/PackVault.sol` | `448106b8915413badef411355a5cb729ca15046743be768919d74e9349ddcd8b` |
| `keeper/policy.py` | `8e6ee88e5a1b86712c11c1d6d264844c48d820f576646631ed14bdec681061d0` |
| `sim/forward.py` | `f36f9295aec5c41583e2c6a6763134c2f1dc30a33f5e8790e55c96747685daa7` |
| `test/fork/EfficientJournal.t.sol` | `1a042d2d45780fb241a416058ac0405e9d83189430d4035a172a69adf2d3720b` |

The timed calendar additions in `forward.py` were separately reviewed under its prior `d34620fc…` hash; this review checks its additional tail-base mirror. Prior timed results retain their old source binding and are not candidate economics.

## Payment and grief boundaries

The implementation adds 80,000 only inside the existing mode 2 proof branch, after ordinary/full/own/terminal work has already been excluded. The same augmented base enters `_distributionTail`'s maximum-envelope subtraction and the eventual payment. Failed proof leaves `requiredTail=false`: with no other work payment is zero; with genuine pruning the normal 85,000 base and actual pruning remain payable, without journal or proof compensation. Full 128, actual own transitions and terminal recovery use the ordinary 85,000 base. Unexposed advancement and empty bootstrap protection remain unchanged.

No caller chooses a journal size. The fixed journal/own/terminal/prune bounds, authenticated completeness, blackout/drained-queue requirement, unused checkpoint interval, witness, gain, post-cost liquidity and exposure checks remain. A qualified foreign tail clears its current prefix, so callers cannot split that same backlog into repeated proof premiums. Invalid-witness work can be performed unpaid under `minPay=0`; positive refused payment reverts the journal progress atomically.

The policy mirrors the constants and correctly describes the estimate/offer profitability check instead of promising reimbursement. The simulator charges the proof base only for a qualifying distribution-only required tail. Its ordinary/full/own paths retain the ordinary base. The displayed backlog floor omits possible proof/own/terminal costs; it is not a complete cash requirement or an unconditional bill for an unqualified tail.

## Economic scorecard

Supplied baseline bills are measurements of their executed paths, not candidate receipts:

| Path | Candidate quote | Supplied billed gas | Difference |
|---|---:|---:|---:|
| Holder singleton |132,000|122,411|9,589|
| Distribution singleton |212,000|202,253|9,747|
| Full 128 |2,901,000|2,233,060|667,940|

At 0.5 gwei these quotes pay 0.000066, 0.000106 and 0.0014505 ETH. The observed 79,842-gas singleton difference supports the work distinction, not a universal 80,000 bound. Fresh candidate receipts and the normal keeper gate remain necessary; successful-foreign billed paths are not established by refunded-journal tests.

Higher proof cost can make a marginal distribution fail qualification. Lowering the record quote also lowers `Q_POSITION_SYNC`/`CYCLE_GAS` by 8,000, affecting numerical edge/backing and cycle-net gates. Predicates and Params are unchanged; numerical admission outcomes need not be identical. Request, deployment and unwind charges remain unchanged, as does the 325,000 pack quote.

Perfectly packing 18,281 records with one qualifying final distribution tail implies 0.207221 ETH/30 days at 0.5 gwei, above 0.15 ETH of configured refill before other work. Permission supplies no cash. O2 and complete holder economics remain unresolved.

## Evidence and limits

The supplied journal log reports five passing focused tests, including invalid-witness rollback/unpaid advancement, valid-proof payment and full 128 payment with distributions enabled. The supplied reconciliation log reports both fork tests passing. I inspected these logs and test assertions without rerunning them. The producer separately reports 14 model tests, policy checks and to-the-wei Python reconciliation; accounting replay takes observed payouts as inputs, not independent payment-formula proof. Failed-proof-plus-prune and own-work premium exclusion are source-traced here, not newly executed mixed-case regressions.

Existing artifacts contain 24,451-byte PackVault and 23,001-byte VaultLib runtimes, below 24,576. No tests, model execution, node operations or candidate broadcasts were performed for this review. Only this report was written. The original literal-only approval does not cover the new proof component; the exact owner amendment remains required.

Journal log SHA-256: `a0ae9a3e2032e61d2dfa6d8031d7c14ddf7d94d3a0f3f97b5536e4e9b9128049`. Reconciliation log: `b33f1696969b060626463e54e9fcfbfd63eb2ac28594854cbd9db1f2183da530`.

## Things that don't make sense

- Measured singleton margins are small enough that other states, races or estimates can change keeper acceptance; they cannot become universal profitability claims.
- Reduced quotes do not resolve recurring funding, repeated harvesting expense or depositor returns. None is accepted by this review.
