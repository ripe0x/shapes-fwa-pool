# Independent implementation review

2026-11-18. Read-only correctness and economic review by a reviewer who did not implement the
production contracts. No tests, broadcasts, staging, commits or source edits were performed by
this reviewer. This is bounded implementation review, not a formal security audit or release approval.

## Reviewed inputs

The complete initial production snapshot was reviewed at PackVault `7646074c…d03f6` and VaultLib
`28cbd416…6ae15`. The measured-work repairs were reviewed at PackVault `a62607f9…add3a6`, VaultLib
`604159ca…901366`, and External `d50229cf…6e499d`.

The subsequent staging repair artifact has SHA256
`e22509fe03ee18293e917772a3c178e39674387b61ec0067f3e0c772a53c030e`.
The final inspected source, including normalization of bounded admission failures, has SHA256:

```text
798e7ea0fc9968f8fe4d1ec14ce40275f47b5a10fb16872c73295929fc204fe9  src/PackVault.sol
612b06f37a7e58c4611943e6d939d74016dc08a1ad1b64b72586256735fb8464  src/VaultLib.sol
d50229cf80a4a036c9ba3f4f8bb60452129ee51dc7ca0263ad612b2ea76e499d  src/interfaces/External.sol
```

Review used the owner's milestone brief, requirements, D65/D66 and holistic verification guidance.
Cached deployed FWA source SHA256 `1b5dbbe6…40a425` and ShapePacks source `1425fabf…11e9` match
the archived source-identity evidence. Shapes redemption, recomposition and denomination source
were also inspected. This review did not make a fresh live bytecode or parameter read.

## Source conclusions and resolved findings

No confirmed production accounting or lifecycle defect remains from this review. The independently
derived asset map agrees with `docs/SYSTEM-MAP.md`: P is counted once across custody changes, B is
active-only, fee credit is counted once, and free cash excludes every protected holder bucket and
`processingPool`. Reviewed paths include selection/receipt ordering, lookup retirement and reuse,
fee debt updates, owed returns, extended gifts, bounded recovery and holder pricing order.

The former flat recovery quote overpaid a final one-Shape chunk. The repair authenticates actual
burn count using the immutable Shapes supply difference. `redeemBatchTo` burns exactly its IDs,
decreases supply, then makes its sole ETH callback. The guarded vault's callback cannot interleave
another supply mutation. Stored sampled Shape geometry is at most 25 bytes, so its deletion does
not conceal an unbounded per-Shape loop. Recovery pays unsealing once and retains exact residual P.

The staging repair correctly recognizes that drained acquisitions do not prove an empty foreign
staging FIFO. The postcondition requires our ordinary listing to be Active and global active count
to rise by exactly one. An incidental foreign activation therefore reverts the complete vault
call, including foreign progress, cash and NFT movement. Requested FWA admission gas is capped at
1,200,000 per attempt; list batches are capped at eight. These bounds do not independently prove
the complete transaction's gas margin. The receiver body is unchanged, but changed production
bytecode still requires its final receiver measurements.

Two affected caller issues were identified and repaired: `TestVaultOps.list` now reads the new
eight-item bound, and failure of the bounded `listNFT` call is normalized to `InvalidListing`.
The catch reverts atomically; it does not ignore a required receiver failure. Existing postcall
Active, ordinary and identity checks remain mandatory. Keeper policy and the gas meter use eight.
Final compilation and affected test results belong to the implementation evidence, not this review.

Listing cannot itself clear a foreign staging backlog because every incidental activation rolls
back. Another caller must clear it through FWA's permissionless activation path. That external work
has no restored vault activation payment. Existing journal processing, settlement and exits remain
available under their own rules. This admission liveness limitation must remain explicit.

## Economic conclusions

The quote schedule is fixed by verified work, not measured gas. At Q_SYNC=85,000 and Q_JOURNAL=30,000,
the supplied measurements show distinct contexts:

| Journal case | Measured gas | Quoted gas | Interpretation |
| --- | ---: | ---: | --- |
| Actual refunded startup, one | 131,980 | 115,000 | under by 16,980 |
| Actual refunded steady state, one | 112,080 | 115,000 | over by 2,920 |
| Actual refunded steady state, sixteen | 361,148 | 565,000 | over by 203,852, about 56% |
| Forge successful foreign gross, one | 158,787 | 115,000 | under by 43,787 |
| Forge successful foreign gross, sixteen | 440,499 | 565,000 | over by 124,501, about 28% |

The reviewer did not rerun these measurements. Startup, successful, refunded, gross and actual
receipt contexts are not interchangeable. The quote was retained for the frozen slice; a smaller
number chosen to fit a budget would not establish affordable or profitable maintenance.

Request-funded checkpoints bypass holder budgets under the existing charge policy. At maximum
parameters their quote is 400,000 × 50 gwei + 0.00005 ETH = **0.02005 ETH**, funded by request
charges. Any owner-compromise summary must distinguish this source from budget-limited free-cash
maintenance. The preceding budget-only extraction statement does not bound every keeper payment.

## Limits and remaining acceptance

This review did not validate the final receiver stipend, low-gas samples, maximum complete-operation
gas, linked deployment receipts, model/fork equality, keeper reorg execution or the final asset-flow
scorecard. Those require the recorded implementation runs. No source review establishes exhaustive
coverage, affordable continuous operation, an owner signature or mainnet readiness.

Things that don't make sense: recurring global journal cost still exceeds the existing canary
funding policy in the parent's analysis, including at the tip floor. The branch must not be called
a completed funded milestone until that measured shortfall is resolved or explicitly reported as
the blocking outcome. Singleton underquotes and batch overquotes also remain distinct limitations.

## Listing base quote repair

The subsequent VaultLib SHA256 is
`a13b42c4ce02aebfa5e19e5fd3536c6c3da4caa2965f2e11d5952ed82bc158d9`.
Restoring only `Q_LIST = 400_000` in its bytes reproduces the previously reviewed
`612b06f3…fb8464` hash. The sole source change is therefore the listing base quote from 400,000
to 280,000. PackVault remains `798e7ea0…04fe9`; per-listing gas remains 825,000 and the work fee
rules and bounds are unchanged. This changes no accounting transition or admission condition.

The supplied local receipt comparison uses the same three pack IDs and order from four idle
packs, at basefee 0.15 gwei and effective price 0.2 gwei. One batch billed 2,624,113 gas; three
singletons billed 1,063,186 + 1,114,498 + 1,097,398 = 3,275,082 gas. Splitting therefore cost
650,969 extra gas, or 130.1938 microETH. Per-listing components and three work fees cancel.

| Base quote and payment context | Extra payment for splitting | Extra payment less measured extra cost |
| --- | ---: | ---: |
| Old 400,000, V1 without markup | 160 microETH | +29.8062 microETH |
| Old 400,000, maximum 10% envelope markup | 176 microETH | +45.8062 microETH |
| Rejected 300,000, maximum 10% envelope markup | 132 microETH | +1.8062 microETH |
| Final 280,000, maximum 10% envelope markup | 123.2 microETH | -6.9938 microETH |

The final quote removes the observed splitting profit in this comparison, including the maximum
envelope markup at the same gas price. The default V1 offer itself contains no markup. These
receipt contexts must not be conflated.

The Python policy schedule mirrors 280,000. `reserve_need` and the forward simulator consume that
shared schedule. At the policy test's 0.5 gwei ceiling and 10% markup, the eight-listing quote is
6,880,000 × 0.55 gwei = 0.003784 ETH; adding the 0.00070675 ETH routine catchup allowance gives
0.00449075 ETH before listing work fees. With 0.00016 ETH in listing work fees, unpaid essential
work gives 0.00465075 ETH. The funded 2 gwei essential case gives 0.006514 ETH. The inspected test
assertions match these amounts. Its nearby explanatory comment still names the former 400,000
base and needs a wording update; the runtime formula is correct.

The reviewer checked receipt arithmetic and source/policy propagation, but did not rerun the
comparison, compile the final bytecode or verify other split sizes, fee contexts or FWA states.
Reported runtime sizes of 24,549 and 20,484 bytes remain implementation evidence. This repair
does not establish continuous paid operation or remove the maintenance funding blocker.

Things that don't make sense: the existing journal singleton/batch quote asymmetry and canary
funding shortfall remain. The listing-base repair closes a measured incentive defect, not those
separate limits.

## Keeper integration and affected repairs

The independent review covered the complete immutable keeper snapshot
`/private/tmp/position-keeper-review-3799h666`, then the affected deltas in
`position-keeper-repair-review-ecr6r5c8` and `position-keeper-final-review-gi2h8d_g`.
Their patch SHA256 values are respectively
`532f0997c1aa0c65abc581f60f011ec729c9da6018f68916bd8ad86c5e3c8862`,
`1f709dd28544db2ef8c9ac418e7734520b5e489c158ea589aca8e572ee1b99c3` and
`77c75c83fdb8dacc03f1938d218759ba36ca2b7aaf1cc9b674ed0e8ad9321da2`.
The final reviewed runtime source identities are:

```text
df14148c2626e7bc58d4728ce6e66a9d3ff8466475625813d363c66cc77fa6a9  keeper/index.py
a4f017ba65715a1dcc6b942ae47ecb6cef82f95e2ab19449df50ab0f9d94a3d1  keeper/keeper.py
3eb4837f583a268b3e13d352ca142a9350517ddcce5e9e99350b1df57d648129  keeper/policy.py
da9b69933c0c17368df323c725c051cc78fb908e92001fe82f6b5e713bc6a230  keeper/tx.py
```

No further actionable financial or correctness defect was confirmed in these bounded inputs.
The index authenticates its chain/vault/deployment identity, stores canonical range endpoints,
and incrementally hydrates bounded active and terminal candidates. Financial reads may use a
canonical ancestor; authenticated prospective pending execution checks the complete call and
current eligibility. A final parent check precedes submission. Requiring that the earlier
financial ancestor always equal the latest head would create unnecessary starvation and is not
part of this repair. Changes after submission can still cause a revert.

The gift-head policy permits building a viable three-unit pack when an existing four-unit gift
produces no listable proposal. It retains inventory priority when proposals exist and includes
existing `idle_funding` in new-restock funding. The keeper does not change protected cash,
liabilities, quotes, payment policy or spending authority.

Four review findings were repaired and their affected code re-read:

1. `keeper.py:473` now submits the exact signed-call estimate and rechecks affordability when
   it exceeds the first estimate, including the configured return and loss limits.
2. `tx.py:306` uses the fresh replacement estimate, pads it by 25%, enforces the 16,777,216
   transaction gas ceiling, and persists the new estimate and gas limit.
3. `tx.py:326` persists the replacement attempt and fee/gas fields before broadcasting. A real
   accepted transaction whose RPC response is lost therefore consumes the replacement cap.
4. `index.py:135` obtains `BEGIN IMMEDIATE` and rechecks the head within that transaction. A
   concurrent stale append returns false for the bounded sync loop to retry. The supplied
   four-writer SQLite regression passed; it is a local database test, not chain evidence.

The same-hash re-inclusion repair removes the old counted entry before applying its new receipt.
The corrected OWED fixture checks the actual 20,000-unit reservation before release and the same
tag afterward. Synthetic successful protocol/payment emitters were removed. The final recovery
test drives the actual vault/token route; its injected failures discard successful real RPC
responses rather than supplying successful service answers.

## Keeper evidence and economic scorecard

The reviewer read the supplied executed evidence and did not run tests or broadcast transactions.
`/private/tmp/position-approved-final3-and-quiet.txt` records `FINAL_RECOVERY` with every reported
flag true. Loaded source hashes match the reviewed runtime above; final `test_tx.py` is
`737b3df7e1ddb641928188f137097fc9ab63c0a5eca21069e57b81d843a02a58`.
Its final fixture delta SHA256 is
`c8d22463aa6a7416cbfafe1a721a12ce10c0a4e98bb288a8fea9fabf5fda333d`.

| Outcome or limit | Observed or reviewed result | Boundary |
| --- | --- | --- |
| Exact accepted replacement after restart | Hash `0x40e88a5c1507a93adfd6006c18bbbaa8f16573e635c818b56490ff9d7694e405`, nonce 21, attempt count 1; exactly one matching pending entry and no queued entry | Actual approved local fork transaction and pool read |
| Replacement and loss accounting | Same hash mined at 184,132 gas; cost 0.000134862304871632 ETH, keeper payment zero | Explicitly unpaid token burn; not representative paid-maintenance margin |
| Round trip through branch removal | Token supply, canonical index and keeper P&L restored; duplicate hash not counted twice | Exercised local reorg/re-inclusion cases |
| Existing held backing released | Actual 20,000-unit OWED tag held, then released | Corrected pure index projection fixture; actual withdrawal/reorg has separate real-vault evidence |
| Capital and work bounds | Existing protected-cash gates and idle funding preserved; 25% gas pad, 16,777,216 transaction ceiling; configured replacement cap persists | Source review plus focused supplied evidence; no new owner spending approval |
| Continuous paid operation | Existing canary funding shortfall remains | These keeper repairs do not change that economic outcome |

The first final recovery fixture failed on an overly strong Anvil pool-retention assumption;
`position-keeper-real-recovery-final.txt` remains preserved. Final2 proved the runtime with an
earlier fixture; final3 binds the exact pending hash and nonce to the final permanent test.
The later quiet child had started but had no completion result in the inspected final3 log.
Recorded loaded-code hashes are diagnostic evidence, not an exhaustive Python state identity.
The transaction manager's historical tracking limits remain 64 reorg blocks, 200 counted
receipts and a 5,000-block lost-nonce search. No deep reorg, long-offline, all-concurrency or
adversarial RPC guarantee follows from the exercised samples.

Things that don't make sense: the already identified journal quote asymmetry and continuous
maintenance funding shortfall remain. There is no additional unresolved issue from this affected
keeper review. Neither these findings nor the passing local recovery witness establish safety,
audit exhaustiveness, full product acceptance or mainnet readiness.
