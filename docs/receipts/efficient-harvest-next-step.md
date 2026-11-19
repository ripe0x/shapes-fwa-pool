# Next harvest scheduling decision

**Recommendation: make standalone harvesting serve a concrete cash need. Pull fee credit first; claim active-listing fees only when needed to fund required maintenance or an existing holder exit.** A ready checkpoint can absorb a credit-only withdrawal because checkpoint already withdraws fee credit; preserve cash-needed active harvesting and other liquidity work before a redemption checkpoint. Keep the existing quotes, 25% realized-fee gate, holder liabilities and keeper profitability checks unchanged in the first scheduling experiment.

This is a recommendation only. No source edits, tests, models, chain reads or transactions were performed for this follow-up. The frozen candidate and its existing evidence remain unchanged.

## What the current rule pays for

`keeper/policy.py:273` selects the 16 highest pending-fee active listings, adds all fee credit, and plans a harvest whenever its quote is at most `keeperShareBps` of that gross amount, or a redemption has a cash shortfall. It does not require a cash shortage during ordinary operation. Thus every 60-second poll can reconsider the same still-active memberships as fresh fees accrue.

`CYCLE_GAS` includes one 80,000-gas-equivalent `Q_HARVESTED` component per own bid cycle. It does not include repeated active-membership claims or every standalone 125,000 base. This is an expense-model mismatch: successfully collecting each fee once does not make collecting it often cheap.

The vault contract itself permits that frequency. `PackVault.harvest` pays the fixed quote from routine permission and free ETH when it is within the realized-fee share cap. `VaultLib.harvest` claims the supplied active listings, updates their fee debts, then withdraws fee credit. With an empty ID list it can withdraw credit without active-listing claims. `PackVault.checkpoint` calls `_harvest`, which withdraws credit only; active pending fees remain represented in authenticated NAV.

## Existing bounded scorecard

All figures below come from `efficient-operating-candidate-timed-checks.json`, not a new run: 6.8 ETH principal, two operating days plus at most two exit days, seed 8, 0.2 gwei total price, 609 successful global selections/day plus recorded refunds in busy cases. The modeled 0.3 ETH routine cap and 0.01 ETH/day refill are proposals within existing maxima, not deployed settings. Counterparty timing, selection and fees remain conditional approximations.

| Conditional regime | Completed holder exit | Fully paid routine operation | Underpaid holder harvest calls | Gross received fees ETH | Harvest payments ETH |
|---|---:|---:|---:|---:|---:|
| Zero demand | Yes | Yes | 0 | 0.000000000000000000 | 0.000000000000000000 |
| Timely 120-second response | Yes | No | 44 | 1.819168941380021572 | 0.266081233333330390 |
| Silent purchaser | No | No | 45 | 1.916686416113682250 | 0.270435433333330427 |
| Late 7,200-second response | Yes | No | 45 | 1.862151985294759769 | 0.258901433333330410 |

The timely path makes 990 harvest calls over 15,813 membership harvests. A membership can be harvested up to 198 times before selection. Those repeated marginal components alone total 15,840,000 quoted gas-equivalent, or 0.003168 ETH at 0.2 gwei for that membership, before allocating shared bases. This is compensation arithmetic, not measured EVM gas.

No duplicate fee inflow was found: the existing evidence asserts exactly `external_fees_generated_wei == fees_received_wei + unharvested_fee_credit_wei + unharvested_listing_fees_wei`. Pending fees and credit are cleared once per claim. Every asset ledger also has a zero-wei gap. These checks establish conservation on the conditional paths, not acceptable holder returns.

The timely completed exit pays its holder 6.664858448970310011 ETH of modeled claims. Holder keeper compensation is 0.000303233333330390 ETH, while the holder's gas proxy is 0.020276345400000000 ETH. Creator mint fees are a separate 0.027000000000000000 ETH expense, never operating income or a subsidy. Completion therefore does not imply fully funded upkeep or profitability.

No gas-spike, maximum-size, paused-dependency, large-win or prolonged-idle result for a revised harvest rule exists. These missing regimes remain acceptance gaps; the four short cases are not a forecast or annual-return gate. Raw annualized `ret` is not presented as achieved or expected annual return.

## Why an allowance increase alone cannot pay every exit call

An additional read-only attribution checks the actual integer trace cash deltas. In the timely case, 32 of 44 underpaid holder harvest calls necessarily receive zero from the existing 25% fee-share gate, regardless of spending permission. All 32 vault cash increases equal the entire fee inflow, confirming no keeper payment was deducted. Late has 33 such calls among 45 underpaid holder harvests; silent has 33. Other clipped payments are not attributed by this check. Exact cases and derivation are in `efficient-harvest-payment-attribution.json`.

For example, one timely exit harvest realizes 0.0002448343339482 ETH across 12 active IDs. Its fixed quote at 0.2 gwei is 0.000217 ETH, exceeding 25% of those fees. The gate forces zero even though the vault has over 4.28 ETH of free cash. Changing only the refill cannot reimburse this path under the existing rule. These remain conditional model amounts, not measured harvest receipts.

## Smallest concrete next rule

Keep the decision in the existing pure keeper policy, with no persistent cooldown, second budget or new reserve system:

1. **Avoid a separate credit-only harvest immediately before a ready checkpoint that can perform the intended holder settlement.** Checkpoint already withdraws credit as part of pricing. Preserve cash-needed active harvest, unlisting and liquidation before a redemption checkpoint; prioritizing a partial checkpoint simply because it is executable could protect the remaining cash and delay the rest of the exit. Do not claim active pending fees merely to price NAV; they are already accounted for. All journal, receipt, queue and allocation gates still apply.
2. **Outside that case, remove “pending fees are large enough” as a standalone reason to harvest active IDs.** A harvest should close an observed liquid-ETH gap for an eligible required synchronization job or an existing redemption shortfall. Keep new restocking out of this first cash target; cash for optional expansion is a separate economic choice.
3. **Try `harvest([])` first.** Use it only when fee credit is sufficient to make useful net progress after its own payment and the normal realized-fee gate. If credit alone covers the cash target, do not attach active IDs merely because they are available.
4. **If credit is insufficient, add the fewest bounded highest-fee active IDs needed for that target, including the increased harvest quote.** The current candidate set and 16-ID bound suffice for this selection. Require net cash after harvest payment to close the identified gap, or state explicitly that more bounded work remains. Do not repeatedly harvest toward an unattainable target because routine permission itself is exhausted.
5. **Stop harvesting once that gap is closed.** An expired own allocation that returns backing in the intended sync may fund that same sync; account for that verified inflow before declaring a separate harvest necessary. Preserve caller-funded holder actions where existing D64 policy requires them, with actual clipped pay and caller expense reported separately.

“Required synchronization job” must mean an eligible next bounded job, not the entire lifetime backlog or a hypothetical future listing batch. Its target must use the existing exact quote/preview inputs for that job. `journal_backlog_floor` is expressly a lower bound excluding some own transition/terminal work; treating it as a sufficient all-in cash target would be incorrect. If the bounded observed state cannot establish the next job's cash need, expose that limitation rather than introduce a large reserve target or silently harvest everything.

At the current quotes, simple arithmetic illustrates the incentive to keep active IDs out of a credit-only job:

| Harvest quote | Gas-equivalent | Payment at 0.2 gwei | Payment at 0.5 gwei | Minimum gross realization at 25% cap, 0.2 / 0.5 gwei |
|---|---:|---:|---:|---:|
| Credit only | 125,000 | 0.000025 ETH | 0.0000625 ETH | 0.0001 / 0.00025 ETH |
| One active ID | 205,000 | 0.000041 ETH | 0.0001025 ETH | 0.000164 / 0.00041 ETH |
| Sixteen active IDs | 1,405,000 | 0.000281 ETH | 0.0007025 ETH | 0.001124 / 0.00281 ETH |

These are fixed-quote payments with the current zero markup and no harvest work-unit payment. They are not actual billed receipts or proof that any keeper accepts a credit-only call. Actual signed-call estimates, receipts and profitability remain required before accepting the operating case.

## Cash and participant tradeoffs

| Choice | Cash availability | Holder/keeper implication | Assessment |
|---|---|---|---|
| Current active-fee profitability trigger | Rapidly liquidates active fees even with ample cash | Repeated paid work can consume routine permission and gross fees before net holder margin is known | Keep only as comparison baseline |
| Routine credit-only harvesting, no active exception | Simple and cheap; active fees wait for selection, unlisting or a manual claim | A long-lived active portfolio can have positive NAV but insufficient cash for mandatory foreign journal work | Too restrictive as a complete operating rule |
| Credit first, active IDs only for a concrete required cash gap | Preserves cash access for upkeep/exits while reducing unnecessary active claims | May reduce optional reinvestment speed; requires correct next-job cash target and actual keeper profitability | Recommended next focused experiment |

Pending active fees stay with FWA and remain in the vault's authenticated asset value; they are not lost or donated. When a listing is selected, repriced or removed, its accrued fees move to depositor credit; a later credit claim/checkpoint moves them to vault ETH. Exit-related active harvest remains available when needed. When the cash shortage ends, the trigger disappears and routine active harvesting stops. There is no new ratcheting timer, new minimum TVL, fee waiver, creator-revenue subsidy or use of protected holder cash in this proposal.

The ordinary keeper would execute profitable maintenance and cash-raising calls. A withdrawing holder remains the actor for explicitly underpaid self-service work. The model must not invent a third operator accepting losses. Less discretionary restocking can also reduce creator mint revenue; that is a consequence to report separately, not a reason to spend holder assets collecting fees unnecessarily.

**Scheduling alone does not enforce a vault-wide expense guarantee.** Another permissionless caller can still submit repeated active-fee harvests and collect the current onchain quote within its 25% gate, available cash and routine allowance. A cheaper primary-bot path would establish that path only. If acceptance requires preventing unnecessary paid active claims by every caller, a later explicitly scoped contract payment-eligibility change is required, with renewed gas/size/exit verification. No such change is authorized here.

The next experiment should compare the existing rule and this rule on identical timed external inputs, then clear backlog and complete claims, attributing every paid/underpaid call. Measure credit-only and cash-needed active jobs through the real keeper. Retain positive-NAV/low-cash, budget-exhausted, small first-position and exit cases so a scheduling saving cannot hide a liveness regression. This is work to propose after the frozen candidate batch; none was executed in this follow-up.

## Evidence and limitations

Reviewed source: `keeper/policy.py` harvest selection and `CYCLE_GAS`; `src/PackVault.sol` harvest/checkpoint; `src/VaultLib.sol` active fee claims and credit-only harvesting. The external fee-credit behavior is source-traced in the archived FWA implementation at `0x958C41181182e76F221331b2755b77D9e1426A98`; the repository external-source match evidence supports that archived integration, and no new live verification was attempted here. Existing candidate timed source hashes, commands and integer outputs are in `efficient-operating-candidate-timed-results.json`. Existing timed evidence assumes instantaneous modeled inclusion at a fresh read with 36 seconds before the next confirmed read, static foreign pool, conditional purchaser responses, approximate per-completion fees and historical/quote caller-gas proxies. It does not reproduce a live keeper's race/latency behavior or the missing authentic prepriced-holder cash-cycle fixture.

## Things that don't make sense

- The 25% cap applies to gross realized fees; gross receipts also compensate backing transferred out. A small fraction of gross revenue can still exceed net strategy income.
- A one-per-cycle expense gate cannot stand in for repeated active-membership harvests.
- A better-behaved primary keeper does not prevent permissionless callers from earning existing onchain harvest payments.
- Completed exits with underpaid holder harvest work cannot be labeled fully funded operation.
