# Independent final receipt and harvest-evidence review

What this evidence establishes: the approved local Option C candidate completed its specified refund-history calibration, with positive observed keeper margins in all 24 measured sync cases. **No actionable inconsistency was found in the reviewed stored records or their bounded narrative claims.** This closes this local measurement step, not the remaining economic or release requirements.

Review method: source reading and independent arithmetic over archived JSON, without importing the launcher, running tests/models, making RPC calls or performing transactions. Only this report was written.

## Candidate authority, counters and restoration

The run records revision `aa38fabb2ec60573d7393933839d066426c6059f`, preserved node PID 96649 and exact approved amendment `23aaa40e8dd8d8cdaac03ba3662bb83dc39b3ef64d5b17c8d5a5a7687af99089`. Its source/artifact freeze matches that descriptor; current source hashes also matched during review. The final ledger and result agree:

| Boundary | Recorded result | Approved limit |
|---|---:|---:|
| Candidate transactions |199: 196 actions plus 3 deployment transactions|199 planned|
| Cumulative transactions |517|540|
| Candidate external transaction value |10.367984145737372672 ETH|Within cumulative cap|
| Cumulative external transaction value |27.869594973162081536 ETH|32 ETH|
| Initial wallet funding |8.3 ETH, unchanged|8.3 ETH once|
| Candidate topups / broadcast repairs |0 / 0|No topups|

Both cumulative amounts independently reconcile to the baseline plus archived candidate actions/deployments. The sole action missing `value_wei` is the named PolicyGreedy CREATE, whose frozen send path uses zero value; the deployment seed contributes 0.01 ETH. The first analysis schema failure is preserved in `efficient-candidate-analysis-first-schema-failure.txt`, rather than discarded or treated as a transaction failure.

All 196 action receipts and three deployment receipts have successful status and gas within the transaction limit. The final six actor balance/nonce/code records equal both entry and baseline records; entry head hashes match. The executed frozen runner checks empty transaction pool and automine before recording passed status. This review inspected those records and source checks, not fresh node state. Runtimes are 24,451 bytes for PackVault and 23,001 for VaultLib; the recorded normalized artifact/library checks pass.

## Actual measured payment cases

The 24 sync rows are exactly 20 holder cases: counts 1/16/32/64/128, two prices 0.2/0.5 gwei and two policy regimes; plus four distribution cases: counts 1/32 at 0.5 gwei under both regimes. Default V1 uses zero markup; the 1000 bps cases use the explicitly installed owner-replaceable PolicyGreedy test role.

For every row I checked actual transaction input/hash/chain/gas binding, receipt price against authenticated preflight context, quote/payment arithmetic, gas-cost arithmetic, signed 80%-minPay estimate, default shared-gate acceptance, cursor movement and unchanged protected buckets. Balance and free-ETH decreases equal compensation. All actual margins and full signed-estimate margins are positive. Examples under default V1:

| Actual path | Billed gas | Ordinary 80%-minPay estimate | Fixed gas quote | Actual keeper net |
|---|---:|---:|---:|---:|
| Holder 1, 0.2 gwei |122,417|127,445|132,000|0.0000019166 ETH|
| Holder 1, 0.5 gwei |122,417|127,457|132,000|0.0000047915 ETH|
| Distribution 1, 0.5 gwei |202,270|207,310|212,000|0.000004865 ETH|
| Full 128, 0.5 gwei |2,233,071|2,238,123|2,901,000|0.0003339645 ETH|

The two no-gain probes offer zero and record real preflight/default-gate rejection, unchanged actor nonces/head/counters and no broadcast. The 24 calibration broadcasts themselves use operator `minPay=0`; the ordinary 80% calls were preflighted, not broadcast. Signed-estimate positivity is not an actual signed-call receipt or race guarantee. The 25% gas-limit padding is not billed gas.

Candidate exposure is one Active position versus 40 in the baseline. The displayed baseline comparisons cannot establish matched-state source-only gas savings. Successful foreign acquisitions remain unmeasured; these are genuinely expired/refunded records. Original standalone full-holder Q360 receipts retain their named baseline source binding and were not repeated on this candidate. The matrix itself does not demonstrate completed holder exits or distribution claims after each tail.

## Conditional harvest attribution

I independently matched every listed attribution index against the candidate timed raw trace. Timely has 32 fee-gate-forced-zero calls among 44 underpaid holder harvests; late and silent each have 33 among 45. Each satisfies quoted payment greater than 25% of realized fees, and its vault cash delta equals the entire fee inflow, proving zero deduction in that recorded call. The existing contract/model gate therefore forces zero on these states regardless of additional spending permission. This does not rerun or predict an alternative larger-budget trajectory.

The example realizes 0.0002448343339482 ETH across 12 IDs, quotes 0.000217 ETH and has 4.280354594496935382 ETH free. Insufficient permission is not necessary to explain its zero payment.

The timely model's 990 harvests over 15,813 membership occurrences collect exactly 1.819168941380021572 ETH and pay 0.266081233333330390 ETH, 14.6265268% of gross fees. Pending fees/credit clear once; independent archived asset and fee conservation gaps are zero. Holder claims 6.664858448970310011 ETH, keeper compensation 0.000303233333330390 ETH and personal gas proxy 0.0202763454 ETH match the proposal. These remain conditional model amounts and historical/quote gas proxies, not new harvest receipts or a return forecast.

`efficient-harvest-next-step.md` is accurately labeled a scheduling recommendation, not implemented or tested work. It preserves cash-needed upkeep/exits and identifies the expense-model mismatch. It also correctly warns that changing one bot cannot prevent permissionless callers from earning current onchain harvest payments. Funding/O2/holder-return acceptance, revised-rule regimes and authentic prepriced-holder cash-cycle proof remain open.

## Current funding prefix and PR narrative

I also reviewed only the new current prefix of `docs/REVIEW-FUNDING-PROPOSAL.md` and the current `docs/POSITION-INTEGRATION-PR.md`. Their packed-window quotes independently equal 0.0828884/0.207221 ETH at 0.2/0.5 gwei under the stated one-final-distribution-tail assumption. The 0.5 gwei daily amount exceeds 0.005 ETH refill before own work; the 0.2 gwei canary amount is 4.14442% of its 2 ETH cap. Raw conditional realized holder results match zero −0.073071229658515459, timely −0.155298663096359599 and late +0.095939180762570863 ETH. Timely harvest payment exceeds gross fees minus transferred backing by exactly 0.054841310531998818 ETH. None is presented as an expected return or allowance recommendation.

The PR separates calibration `minPay=0` receipts from 80% preflights, one-versus-40 exposure, baseline-only full-holder receipts and successful-foreign/combined-own gaps. Its baseline 346,017-gas full-holder figures, accepted default gate at 0.2/0.5/2 gwei and 0.0002 ETH payment at 0.5 gwei match the baseline archive. The 24-journal-row signed-estimate headroom claim should not be extended to the full-holder 2 gwei path. The draft status and unresolved O2/funding/return outcomes are explicit. No numerical correction or overclaim was found within these reviewed current sections.

Funding file SHA-256: `c6f5d1bde0e8c4231c1b56e7637303fc1f70fca98025e76a2af8cdb122f18f9a`; PR body: `d7b48882a65f61d7e0b66fc68905a50c9734e105e64134e28d0df1d74113bcff`.

## Evidence bindings

- Candidate result: `2e9f459dd783833cef7c938eebf2d229e3198ba06c85f366bc994de54e4b5942`.
- Candidate summary: `7e4b5acddbf932d9d660d3d8720c88c8b203cf5630283d9bb90215d3ffbc62b4`.
- Final ledger: `3b184047ba54785b08f87a203b6a936b5007703f85109f539bec0471105623f3`.
- Run log: `4b186fdc0503f898f979828406ac9228dc8f01d82f47b7d6d80167e6759c9136`.
- Candidate analysis source/log: `dffda1ccb2b7df290f032ea1bf10aab73ad77692bf63430b3d9fc94d5aa8399c` / `6258ad5f204da0ceb1ae319d7614d66442531639dae52fc5ec958b0068dc9a16`.
- Candidate timed raw: `de028017ab4c807b49443a82cad04817aaf131228f7ccc54e3a1e2eac0c26d83`.
- Harvest attribution: `65c27efa23ca599756e9aae71085c728639c28a15edf6bab4715ac9318be9d58`.
- Harvest proposal reviewed: `13cd2e9e3dca7c6f53e4707e5fd6c79ecfc3cc5e0491d5a19748892ff5ec5984`.

## Things that don't make sense

- More permission cannot override the 25% realized-fee gate on the identified calls; an allowance-only fix does not reimburse those recorded holder actions.
- Positive local keeper margins, fee conservation and a completed conditional exit do not establish acceptable depositor returns or sustained funding.
- One-off fixture gains and restored wallets are not recurring earned income. A source-only gas-saving claim also needs matched states, which this baseline/candidate comparison does not provide.
