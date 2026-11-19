# Final affected journal and keeper review

What this change does: the vault chooses a bounded journal job, independently processes terminal IDs and cleanup, and pays short foreign tails only under a checkpoint-related condition. Ordinary sync always uses routine permission. The keeper waits for useful jobs and checks the actual simulated offer against its estimated cost before sending.

This is a focused read-only review of the lead's journal/tail and keeper changes against OWNER-REQUIREMENTS 22–27 and `docs/EFFICIENT-JOURNAL-REVISION.md`. It excludes my restock implementation and does not independently re-review the original unexposed predicate. Only this report was written; no tests, transactions, node operations or new agents were used. Ponytail Review and the holistic verification guidance apply. This is not an audit or release acceptance.

## Immutable inputs

| File | SHA-256 |
| --- | --- |
| `src/PackVault.sol` | `448106b8915413badef411355a5cb729ca15046743be768919d74e9349ddcd8b` |
| `src/VaultLib.sol` | `1a5407f1044f0e79b874ee77cd6936bb53438b020f4c8e093db200909990490f` |
| `keeper/policy.py` | `cba78633858db621b48bf729571673f84693e503d6d49eecda0cb905730703a2` |
| `keeper/keeper.py` | `30c1af8cc1483561ebefa3b36c110cb7ede200e9b36f8ca922b08e53594d3d0e` |
| `keeper/tx.py` | `da9b69933c0c17368df323c725c051cc78fb908e92001fe82f6b5e713bc6a230` |
| `keeper/index.py` | `4f037790c23e6ad51cb67d646c540bca39bb240eda9a0a7c5bdb69aac9910f63` |

All six match the prepared plan `docs/receipts/efficient-journal-local-plan.json`, SHA-256 `1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd`. Its status is **PREPARED; NOT APPROVED**. This review grants no batch authority and does not review a future quote candidate within the plan's ranges.

## Source conclusions

No new actionable correctness regression was found in this bounded scope.

- **Fixed job and completeness:** `sync(ids,witnessId,minPay)` exposes no journal/prune size controls. Journal processing is capped at 128 completed entries and 16 actual own selections; the seventeenth own selection remains unconsumed. Up to 16 supplied terminal IDs and 16 head removals are independently bounded. Irrelevant or duplicate IDs cannot shrink the journal job or manufacture completed transitions. An exposed vault still authenticates ordered acquisitions and live listing identity.
- **Payment eligibility:** full 128-record jobs and verified own selection/terminal changes qualify. Prune work earns its own component, while an unqualified short foreign tail contributes no journal quote. Pure unexposed advancement earns zero. No completion bonus was added; the initial ordinary and qualified-tail bases are both85,000. A refused positive `minPay` rolls back the whole operation.
- **Holder tails:** a pending deposit or locked redemption, an unused checkpoint interval, purchase blackout and a drained external request queue provide the holder-flow condition. This is necessary bookkeeping toward an actual holder request, not a guarantee that one sync clears every independent receipt, allocation or exposure gate. Those pricing gates remain enforced by checkpoint.
- **Distribution-only tails:** merely enabling distributions no longer proves a need. The helper requires the strict current NAV/witness/receipt checks, a usable allocation head, post-expense allocated exposure within its bound, live shares and gain above the high-water mark. It subtracts the maximum routine envelope, including markup and prune work, before proving the 0.01 ETH distribution minimum. Wrong witnesses or inadequate gain disable this journal component.
- **Post-harvest liquidity:** the helper adds actual fee credit to `freeEth()` before subtracting reserve and maximum sync cost. This closes the prior reserve-shortfall clamp error. Protected escrow, processing charges and holder reserves remain excluded. Actual payment reads `_free()` after work, so genuine terminal recoveries are not lost through a stale balance snapshot.
- **Keeper scheduling:** configured distributions may propose a short tail without first requiring a successful checkpoint simulation. Onchain qualification and the ordinary offer/profitability preflight determine whether it is sent. This removes the previous checkpoint/catchup circular wait without treating the percentage setting as proof of payment. Sync stays routine even with locked shares; unlist/liquidate keep their existing exit class. Known backlog quote, free cash and routine permission are displayed separately. Insufficient known maintenance funding suppresses new exposure reversibly, without setting permanent wind-down or disabling holder actions.
- **Profitability helper:** extracting `profitability_gate` preserves the prior arithmetic: billed-ratio-adjusted estimate at the bid, failure allowance, required return, and explicit permitted loss. Defaults remain zero loss, zero failure allowance and zero minimum return. The exact 80%-`minPay` call is preflighted again, including a higher-estimate profitability check; transaction limits retain 25% padding separately. Neither the helper nor an authorized operator's `minPay=0` measurement proves an ordinary keeper would accept a losing call. The current ordinary path and prepared measurement path use the three-argument ABI.

## Independent economic check

These are fixed quote calculations at matched prices, before markup, with no flat fee for foreign records. They are not actual billed expense or return estimates.

| Regime | Quote or allowance | Consequence |
| --- | ---: | --- |
| Full 128 foreign records | `85,000 + 128 × 30,000 =3,925,000` gas | 0.000785 ETH at 0.2 gwei; 0.0019625 ETH at 0.5 gwei |
| Archived 18,281 records, 143 efficiently packed jobs with a qualifying final tail | `560,585,000` gas | 0.2802925 ETH over 30 days at 0.5 gwei; 0.0093430833 ETH/day |
| Mainnet configured routine refill | 0.005 ETH/day | 0.15 ETH over 30 days,0.1302925 ETH below that global-work quote before own work |
| Mainnet initial allowance plus 30 days refill | 0.1+0.15 ETH | 0.0302925 ETH below that quote; allowance is permission, not a cash inflow |

The monthly calculation assumes continuous exposure, efficient packing and a qualifying final tail; it is not an unconditional payment obligation for every historical record. Default V1 does not take the vault's optional markup. No quote, allowance or O2 limit was changed by this review. Operating cash, all own work and complete holder exits/returns still need the planned evidence and funding proposal.

## Limits and verdict

The three prior distribution-tail findings are closed in the reviewed mechanisms: false no-gain eligibility, the keeper's circular scheduling dependency, and reserve-shortfall liquidity. I read their affected controls and current focused tests, but did not independently execute them. Simultaneous maximum own selections/terminal recovery, current successful-foreign billed tails, full-holder signed receipts and ordinary keeper acceptance remain bounded by their actual archived or pending evidence. Accounting replay takes observed payouts as inputs and is not independent payment-formula proof.

Verdict: no new source issue blocks the prepared calibration step in this review. Owner approval, actual receipts, O2 and complete operating economics remain separate gates. No release or broadcast is approved.

## Things that don't make sense

- `keeper/policy.py` still says every below-ceiling planned call pays for itself. A configured distribution with no gain can deliberately produce a proposed sync whose onchain offer is zero; the executor correctly declines it. The header should describe the profitability check rather than promise universal reimbursement.
- A128-record batch reduces repeated bases but does not supply operating ETH or remove the recorded recurring allowance shortfall.
- Favorable estimates, fixed quotes, isolated-frame measurements and actual billed receipts answer different questions; none should silently replace another.
