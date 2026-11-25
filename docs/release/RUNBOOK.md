# Main pool completion: unsigned deployment package

> The shared vault remains closed. The current individual-manager package and postflight are in
> [MANAGER-RUNBOOK.md](MANAGER-RUNBOOK.md); this combined route is retained for a separately
> authorized pooled-vault release.

This candidate is for local validation and draft review. Public transactions, production mint fee
changes, live application cutover and merges are outside its authorization. Previous instructions,
signatures and measurements are preserved in `history/e94fd99/` and their original receipts.
They do not approve this code or configuration.

## Configuration and authority

Launch units 3, mask 8: three directly paid 0.01 ETH primary mints per 0.03 ETH pack. The shared
vault and personal managers use PackAccount, StrategyLib, VaultLib and ScanLib. The factory has no
authority over created managers. There is no external keeper policy contract.

`deploy/mainnet.json` and `deploy/manager.json` contain the full account configuration, including the
named gas schedule and explicitly accepted maximum mint fee. They describe the local evaluation:
backing 70,000 bps, unresolved keep uplift 25 bps, reuse-only returned packs and a
0.005 ETH maintenance reserve. **Backing and uplift are not approved production defaults.** The
live fee observation, with block and hash, is `deploy/mint-fee-observation.json`.

Numerical settings apply immediately under each account owner's authority. Verified operation
counts cap measured work; account-owned overhead and actual transaction pricing determine pay.
Quotes remain conservative spending envelopes. Receipt gas calibrates viability separately.
Changing numbers needs an owner settings transaction. Changing the algorithm needs new code and
a replacement deployment. The two-step ownership acceptance window remains 48 hours.

## Local verification and rehearsal

Run from the implementation checkout with pinned dependencies. All Ethereum mainnet reads use
`https://mainnet.gateway.tenderly.co`. A local fork must remain chain 31337.

```sh
CANDIDATE_RUN=1 script/verify.sh
python3 script/release.py manifest
python3 script/release.py check deploy/mainnet.json
python3 keeper/rehearse_unified.py --fork-block <recorded-recent-block> --port <unused-local-port>
```

Use the exact commands and interpreter recorded in the completion evidence. Archive replay and
economic simulation require the refreshed, uncommitted `sim/data/fwa.sqlite`. Rehearsal exercises
DeployCore with the main Shapes and main ShapePacks, fresh checked actors and real local transactions.
The community pack collection must not be substituted.

The manifest binds source, deploy values, compiler, normalized runtime, every library, keeper inputs
and evidence. Postflight reads every setting back, plus owner, dependencies, library addresses,
budgets, balances and liabilities. Wrong recipe, omitted settings, stale ABI or wrong linkage must
fail. A local receipt does not establish public gas markets, randomness timing, ordering or live
keeper behavior.

## Funding, checkpoints and recovery

Growth preserves holder liabilities and the maintenance reserve. Returned packs are relisted
intact; there is no fresh-return mode or renewal float. A kept pack may be replaced by a funded
paid build. Cash and spending permission are separate. Zero mask disables fresh builds while old
inventory may relist; listing pause stops both sources of new exposure.

Deposits hold gross cancellable escrow. Construction previews are estimates until the committing
checkpoint applies its current configuration and live fee. Contribution IDs retain their payer and
era. Unused sponsorship becomes a protected lazy refund. Zero quotes never close a live era;
successful checkpoints, including partial fills, close their funding era. Required pricing work has
an explicit contribution source. Topups return excess funding.

The CLI and app expose caller-funded bounded exits with a stated wallet spending cap. They refresh
after every receipt and handle settlement/window waits, unlisting, redemption, checkpoint funding,
partial fills and claims. Recovery does not depend on keeper profitability or an obsolete
configuration hash. Contribution refunds and holder claims remain independently recoverable.

## Unsigned replacement and future cutover

Immediately before a replacement plan, read existing cash, pending deposits, locked shares, all
claim/refund reserves and the factory manager count at one recorded current block. Preserve old
claims and existing managers. Changing an app address does not migrate assets or authority.

The package contains values, source/build/ABI identities, independent readbacks, rehearsal receipts,
settings inventory, economic scorecard and an unsigned action plan. New acceptance and owner
decisions must name this candidate. Existing signatures remain historical;
`deploy/release-acceptance.sig` is absent.

`deploy/unsigned-cutover.json` contains five unsigned transactions produced by the same production
wrapper's read-only mainnet simulation. `deploy/keeper-unsigned.json` contains their predicted
addresses as data. They are not live deployment or keeper configuration. Nonce, gas and CREATE
addresses must be refreshed before separately authorized signing. Existing Fly targets are preserved.

Public broadcast, production fee changes, live app cutover and merges require separate owner
authority. The owner's recorded “no canary, ever” decision remains intact. Local tests supply no public action authority.

Things that don't make sense until measured: overhead can favor splitting necessary work;
a small pool may miss pricing windows at 25 bps; creator revenue can be positive while net holder
returns fail the existing 10% annual hurdle.

## A8 manager-only package

A8 supersedes earlier fixed-quote/Fresh configuration. Use `deploy/manager-factory.json` and
`script/deploy.sh deploy/manager-factory.json --target manager` for an unsigned read-only dry run.
Do not pass `--broadcast` on a public RPC. Current manager creation takes the complete Params
and configuration expectation, with no external policy. Re-export ABIs after compiling final code.
The manager ABI must include import, owner unlisting and checked sealed recovery withdrawal.
Historical acceptance/economic outputs do not validate the changed compensation model.
