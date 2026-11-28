# Combined implementation verification

This is engineering evidence for the draft implementation, not production acceptance or an
exhaustive audit. The final contract source set is
`d85c926518a689c73c6575937fd7d3dcde0d1a484d5abfe6de6faa22a4ca8e39`;
individual hashes are in `completion-final-source.json`. The accompanying input manifest binds
tests, fixtures, scripts, keeper and simulation inputs. Git commits in the draft PRs identify the
combined repository revisions. Historical receipts retain their original configuration.

## Scope and counterparties

Launch is mask 8: three directly paid 0.01 ETH primary Shape mints into each 0.03 ETH pack.
The main dependencies are FWA `0x958C41181182e76F221331b2755b77D9e1426A98`, Shapes
`0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0` and main ShapePacks
`0xf21514B090Da7dF4390803497d6ae673801E5cA7`. The community pack collection is different.
Fork calls use `https://mainnet.gateway.tenderly.co`; local writes use checked actors on chain 31337.
Authentic recorded requests and Chainlink proofs drive contract acquisition tests. No replacement
counterparty, receiver code substitution or coordinator impersonation supplies integration evidence.

The live fee was 0.001 ETH per Shape at study block 26484850. The pre-plan readback at block
26485995 confirms the same fee, old vault balance 0.01 ETH, no pending/locked/claim/processing
liabilities exposed by its supported views, and factory manager count zero. Unsupported new refund
selectors are recorded as unsupported, not interpreted as zero. See `deploy/existing-main-readback.json`.
The 0.0005 ETH fee exists only in isolated fork sensitivities.

## Commands and results

All exits below are process exit statuses. Commands' complete argument arrays and output are kept
under `completion-checks/`. Failed exploratory runs are preserved under `history/`; they are not
represented as passing final runs. The dedicated Python interpreter is
`/tmp/shapes-completion-python/bin/python`, with the pinned keeper dependencies plus NumPy.

| Check | Result and identity |
|---|---|
| Final changed contract paths | 66/66 passed, exit 0, final source set; `forge-proceeds-final.json` records exact selected names and command |
| Final affected fairness/callback paths | 10/10 passed, exit 0, final source set; `final-fairness-callback.json` records three live-incumbent/late-allocation cases, manager keep/cold kick, receipt recovery and funded tail |
| Asset flows and real credit funding trace | 17/17 passed, exit 0, final source set; 11 production three-unit regimes plus five intentionally historical six-unit proof regimes and the conditional renewal trace |
| Full earlier calibrated suite | 297 passed, five failed; historical source and failures preserved. Four affected fixtures/calibration assumptions repaired; the historical O6 comparison remains economically failed as explained below |
| Scale | Real 301-position checkpoint and two 301/1,000/10,000 model-book cases passed in `forge-repairs-scale-v2.log`; its three unrelated failures remain visible. Final source also passes the real >300-position zero-priced-scan case in the 66-case pass |
| Python | Config, policy after failing-only fixture repair, 18 vault, 12 completion, two forward and 13 independent deployment-input cases passed; exact commands/exits in `verified-python-batch.json` and repair logs |
| Canonical replay | 876,437 earnings events, zero accumulator mismatches; refreshed archive through study block 26484850. Archive is local input, not committed |
| Bounded economic campaign | Exit 0; 89/89 modeled exits across 23 cells. Both median conventions fail the preserved return gate; all raw rows, means and standard medians independently checked |
| Six-group reconciliation | Every account, position, contribution, issuance and permission bucket matches to the wei; `final-reconcile.log` and committed `sim/out/reconcile-*-trace.jsonl` |
| Local production-path rehearsal | Exit 0, errors `{}`, pooled full exit and three manager exits; `unified-production-rehearsal.json` |
| CI production image | Run 45427099371 passed on 49da810: Docker build, image smoke/shared-volume replacement, actual isolated fork, vault/manager work and lost-response recovery; `completion-image.json` |
| Billed gas | 103 successful final-source transaction receipts in `completion-calibration.json`; aggregate Forge test gas is not used as a receipt |
| Unsigned deployment simulation | Exit 0, five transactions, simulated independent postflight passed; no `--broadcast`, no signature. `deploy/unsigned-cutover.json` includes filtered public unsigned calldata |
| App integration | Commit c83cf8f, draft PR 37: freshness/typecheck/build passed, 51 tests passed, 10 opt-in service cases skipped, 16 actual UI wallet transactions and all tested refunds completed; `completion-app.json` |

The 17-case command is:

```sh
SOURCE_HASH=d85c926518a689c73c6575937fd7d3dcde0d1a484d5abfe6de6faa22a4ca8e39 \
CANDIDATE_RUN=1 forge test --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100 \
  --match-test 'test_flow_|test_managerRenewalCollectsRealCreditOnlyWhenCashNeedsItAndPermissionAllows' \
  --gas-limit 10000000000 -vv
```

The reconciler command is `python3 sim/reconcile.py`. The bounded formal command and every cell's
inputs/results are recorded in `formal-assessment.json` and `completion-economics.md`. Simulation
results are counterfactual finite-history sensitivities, not demonstrated APR.

One gate invocation mistakenly omitted `--no-run`, repeated its configured flow suite, then failed
on malformed `explained` metadata. That failure is retained. The metadata was corrected to an empty
list without exemptions or changed outcome limits. A subsequent `--no-run` check exits 2: unsigned
approval and the retained O6 failure. The regenerated flow files use the gate's composite input hash
`bf148279857b04c8249528401507d38765dbd81b901d6b22cf588ce173aebcf2`; `asset-gate-source.json`
maps it to the same final contract source. The earlier explicit 17-case command/log remains the
passing test record. This extra regeneration was unnecessary; no broad rerun is needed to relabel it.
Subsequent metadata, manifest and tracked-file additions change the gate's composite source hash.
Its scorecards are therefore not represented as a fresh gate pass for the final package. The exact
runtime source and executed input maps remain independently recorded; release acceptance is unsigned.

## Receipt measurements and protection

| Actual local transaction | Gas used |
|---|---:|
| Four maximum 29-unit fresh packs | 7,707,907 |
| Unlist 16 | 4,429,675 |
| Liquidate 16 | 2,819,156 |
| Checkpoint maximum observed | 415,691 |
| Unpaid recovery checkpoint | 207,013 |
| Holder deposit | 317,405 |
| Holder redemption request | 312,173 |
| Holder claim | 90,786 |
| Refund collection | 316,146 |
| Required small scan tail | 234,147, against quoted 240,000 |

Every observed production transaction fits 16,777,216 gas. This is bounded evidence, not a
guarantee of future execution under arbitrary external state. Runtime bytes: PackVault 24,095,
PackManager 17,742, StrategyLib 18,090, VaultLib 22,260, ScanLib 22,993. PackVault has 481 bytes
of EIP-170 headroom. The manifest independently checks normalized runtime, creation code and links.

The real same-hash reverted-to-successful reorganization test sent 100,000,000,000,000 wei,
contributed 45,020,287,500,000 wei and retained the signed maximum 112,530,198,000,000 wei while
orphaned. A new nonce was refused. Refund/claim liabilities remain excluded from general cash.
The app detects manual wallet replacement increases; it cannot prevent a user overriding fees
outside the app.

Rehearsal phases record their loaded client hashes separately. Contract receipts all match the
final contract source. The complete earlier client campaign is not represented as a rerun of the
last four offchain repairs. Funding-subset and proposal-shadowing repairs have focused planner
regressions; the final nonce-cap repair has a fresh-process real-node reorganization check.

## Economic acceptance and limits

The historical O6 absolute expense target remains 0.0002 ETH. A required checkpoint at a 2 gwei
essential price quotes **0.00102 ETH**, exceeding that target by **0.00082 ETH**. Its regression
now asserts the independently calculated configured payment and conservation. The target was not
raised, signed or declared passing. Increasing spending permission supplies no ETH.

The depositor 10% annual net-return requirement remains in force. Read the economic scorecard for
the measured candidate result, creator fees and holder/keeper costs together. Backing 70,000 bps
and unresolved uplift 25 bps remain provisional, unsigned evaluation values. A passing integration
test is not acceptance of those economic outcomes.

Known evidence limits:

- No billed production-path authentic-VRF renewal transaction. Local deployment changes the
  request block hash needed by a historical proof. Forge exercises actual coordinator verification;
  receipt-calibrated gas proxies are labelled separately in the economic model.
- No Docker executable on this host. The local full-exit rehearsal ran outside Docker; the existing
  remote CI image/fork workflow passed after its first failure was preserved and its local chain
  identity pin repaired. Production encrypted-keystore transport remains untested.
- Main ShapePacks normally returns to these accepting accounts synchronously. A genuine owed-return
  failure could not be reached without faking a relied-on counterparty. Recovery code preserves
  eligibility, but that forced integration branch remains untested.
- Large-book 1,000/10,000 cases use the contract's book/reference model; 301 cases use actual FWA
  listings. This is not 10,000 paid real listings.
- No public transaction, production mint-fee change, live application cutover, merge or release
  signature. The owner declined canaries. Historical approvals are archived and do not apply.

Things that don't make sense: creator revenue can rise while depositor returns fail; a 25 bps
pricing tolerance can make small pools wait for settlement; one float cannot fund unlimited early
acquisitions; the historical 0.0002 ETH target cannot cover the configured required checkpoint at
2 gwei. These are disclosed economic constraints, not hidden funding sources.
