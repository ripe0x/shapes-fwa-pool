# Individual manager operating closeout, 2026-11-25

This package completes a focused individual-manager follow-up. The Solidity runtime remains
`1bbe54c94eed34818d5e2c7ccd95d5f83a892b90`; the app ABI/interaction source remains
`1330b18ee3bb38b85e9439b3c7213ac37fc9f1d8`. No new shared vault, public transaction, mint-fee
change, live keeper/application cutover, production/acceptance signature or merge is included. The owner removed the
execution-time cap in A7. The removed guard was not reinstalled.

## Actual operating receipts

[Osaka receipts](manager-operating-osaka-receipts.json) contain **69 successful transaction observations across restored local branches (53 distinct hashes)**.
This is the preserved baseline packet. It exercises authenticated acquired-pack renewal, explicit returned-pack reuse,
nonzero owner-paid harvest, separate/combined synchronization, paid one/three/eight-pack listing,
and fresh one/four-pack builds. Each launch pack contains three paid primary 0.01 ETH Shapes.
Renew/reuse fee cases are 0.001, 0.0005 and 0.00025 ETH per Shape, at total gas prices 0.2 and
0.5 gwei, with explicit base fees 0.15/0.45 gwei and 0.05 gwei priority allowance. The last fee is
an agent-chosen isolated half-current sensitivity, not a proposed public change.

The actual historical request and genuine coordinator proof run in the existing real-counterparty
Foundry path. Its execution-derived state is exported, imported into the task-owned Anvil fork,
and checked account by account and slot by slot before billed operations. The original backing
fork/prefix is preserved. This is a verified checkpoint continuation, not a billed end-to-end VRF
request rehearsal. Setup harness gas is not a production transaction receipt and establishes no
transaction-cap result. The runtime execution hardfork is Osaka; the compiler target stays Cancun.

[Cost calibration](manager-operating-cost-calibration.json) binds the raw receipts and current
source hashes. Billed curves cover every included sample. Estimate curves use genuine RPC
estimates when available, and otherwise explicitly use signed-limit upper bounds. No old signed
limit is reverse-divided into a purported estimate. The older Cancun measurements and failed
attempts are retained but excluded from the Osaka operating envelope.

Measured work counts: build 1/3/4; list/unlist 1/3/8; liquidation 1/3; fresh renewal 1;
paid sync 1, including selection and resolution in one call. Larger fresh-renewal and sync batches
remain unmeasured. Their modeled cost is a declared work-allowance/curve proxy. A contract-owned
oracle was not impersonated to fabricate kick fixtures. A fixed owner recovery scan with several
inspected IDs is not reported as several completed settlements.

## Keeper and owner exit

The actual production image passed [manager-only CI run 45619850908](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/45619850908)
at `a81a11cc77e0129a3739597664b492f969df3c3b`. Image build/smoke/shared-volume checks and the
factory-only fork rehearsal passed. [Raw artifact](manager-operating-image-raw.json) and
[independent readback/ledger checks](manager-operating-image.json) preserve the result.
All eight runtime keeper input hashes and all Solidity hashes match this follow-up. Later offline
model/calibration/evidence files are not claimed to have been present in that earlier image.

| Same image receipt set | ETH |
| --- | ---: |
| Initial funding plus explicit growth funding | 1 + 0.5 |
| Owner withdrawal | 1.49185190960227 |
| Owner wallet gas, including creation and exit | 0.000247555822532839 |
| Owner net | -0.008395646220262839 |
| Creator primary mint-fee accrual, fifteen actual mints | 0.0075 |
| Keeper compensation | 0.00064809039773 |
| Keeper billed gas | 0.000398315631865707 |
| Keeper net | 0.000249774765864293 |
| Final manager cash, inventory, receipts and credit | 0 |

The deliberate 0.5 ETH growth funding is explicit. This operational restart/lost-response test is
not the separately modeled 0.5 ETH no-topup return case. Both keeper budgets are zero during the
owner's exit, exit keeper compensation is zero, and cumulative signed exit maxima are
0.000217622712330074 ETH under the caller's 0.01 ETH limit. No unpaid permissionless keeper is
assumed. The separately recorded [host keeper readiness](manager-keeper-readiness.md) preserves its
own original inputs and receipt ledger, rather than borrowing this image's revision.

The baseline exposed cold-keeper underquotes. The corrected manager candidate changes only
selected 180000 → 225000, synced 120000 → 285000 and list base 280000 → 380000. Pack size,
backing, fee acceptance, renewal/float, reserve, markup, ceilings and budgets remain unchanged.
[Corrected execution](manager-calibrated-verification.md) records **43 successful branched receipt
observations (29 distinct hashes)**: ten ordinary cold CLI jobs, two explicit allocated-only
production-executor jobs, and four caller-funded exit CLI steps, plus their real setup calls.
All twelve ordinary cases accept and cover actual costs at matched 0.2/0.5 gwei. Allocated-only
sync is deliberately deferred by the planner; its explicit executor test does not claim scheduling.
All signed ordinary minPay values and exact-call re-estimates are verified. There are no fake
index events: imported positions are bootstrapped from actual pinned getters.

The corrected zero-budget 0.5 ETH account fully exits at actual 0.2 gwei. All six cash/inventory/
receipt/credit buckets end at zero. Exit calls cost **0.0001795922 ETH**; their signed maximum is
0.00048307035 ETH, or **0.00053375455 ETH** including the budget-zeroing setup, below the caller's
0.01 ETH limit. [Independent repair review](manager-calibrated-review.md) binds the exact source,
receipts and 73-sample combined profile. Larger sync/renew batches remain unmeasured.

The current image runtime hashes are unchanged by these account-owned numerical inputs. Its CI
run used the earlier settings for unselected build/restart/exit; the additional host CLI proof
executes the identical keeper runtime with the new settings and settlement/renewal work. Those
two scopes remain separate rather than calling the old image receipt a new calibrated job.

## Focused verification and preserved evidence

The final affected batch passed 25 manager tests, 11 assessment tests, 5 historical-scorecard tests,
10 owner-exit tests and 22 deployment tests. Exact source hashes, commands and statuses are recorded in
[manager-calibrated-checks.json](manager-calibrated-checks.json), together
with the earlier affected checks. Repaired cases include physical costs for 127 genuine archived
foreign journal records despite a zero payment quote, refusal before an owner cap would be
exceeded, estimate-versus-bill rejection, crossing gas curves, explicit estimate provenance and
receipt/source binding. The independent review binds its exact reviewed blobs.

The current accounting replay checks **43 funded and 32 historical compatibility steps** to the
wei in [manager-calibrated-reconciliation.json](manager-calibrated-reconciliation.json).
The earlier eighteen focused fork cases, three funding regressions, cold callback and 23 billed
R2 closeout receipts remain valid for their unchanged runtime and named assumptions. They were
not rerun as another broad campaign. Runtime sizes are unchanged: PackManager 17,853 bytes,
VaultLib 22,486, StrategyLib 18,279 and ScanLib 22,993, all below EIP-170.

The uncalibrated 960-case baseline is preserved at `ce0950c` with its original settings. Its
positive conditional means did not excuse the quote defects. The same design completed against
the corrected profile: 960 cases in 1236.431 seconds, exit 0, with 957 completed exits. All 480
cases using 0.21 ETH backing complete; three hypothetical 0.03-backing cases stop before
exceeding the caller cap and retain their assets. Details and suppressed group means are in
[manager-operating-economics.md](manager-operating-economics.md).
The withdrawn two-draw result and incomplete older campaigns supply no financial conclusions.

## Unsigned manager-only preparation

[Exact preparation commands/status](manager-calibrated-unsigned-checks.json) record the refreshed
existing-deployment readback, cached production-path public dry run, unsigned transaction
verification and owner creation preview. The corrected-candidate simulation took 5.524 seconds and sent no transaction.
The package contains four unsigned transactions: three linked libraries and the manager factory,
whose constructor creates the implementation. No PackVault or vault seed is included.

The legacy main readback at block **26,492,785**, hash
`0xfdd9ca3770178440e23ec47076e4b76d2d181dc0cbb88e425f7a30bfbe7f859e`,
finds 0.01 ETH in the existing vault and zero managers in its existing factory. Supported pending
requests/claim/reserve views and fee credit remain explicitly recorded; unsupported selectors
are not inferred to be zero. The live Shapes fee is **0.0005 ETH**, below the unchanged accepted
maximum of 0.001 ETH. Creation data is pinned at block 26,492,787; the final package nonce
and source rebind is pinned at block 26,492,948. These are separate read-only observations.

Final manifest identity is checked after committing. Acceptance remains unsigned and
`release_ready: false`. Predicted addresses, nonce, balance, fees and dependency code require a
fresh check before any separately authorized signing. Current encrypted-keystore/hardware
transport, Fly production mounts/networking, public inclusion and a real mainnet lifecycle remain
outside this package. No public keeper can be serving the replacement factory before deployment.

Things that don't make sense: one renewal float cannot fund an arbitrary early acquisition burst;
increased spending permission creates no ETH; the 0.005 ETH reserve is below the configured
0.0054805 ETH maximum-batch need; higher quotes fund the measured keeper jobs by increasing owner costs. These remain visible economic and operating limits.

## Corrected cohort command

```sh
CANDIDATE_RUN=1 /Users/dd/.pyenv/versions/3.11.8/bin/python sim/manager_operating_assessment.py \
  --execute --final --costs docs/receipts/manager-calibrated-cost-calibration.json \
  --reconciliation docs/receipts/manager-calibrated-reconciliation.json \
  --live-observation docs/receipts/manager-operating-live-observation.json \
  --minimum-continuity docs/receipts/manager-operating-min-backing-continuity.json \
  --workers 2 --out sim/out/manager-calibrated-assessment
```

No recorded source, data, fee baseline or result was changed during that run. The fixed design
was retained after the measured quote repair. The prior uncalibrated result remains separate.
The associated app follow-up is `f037af2`: three generated default values plus their digest, with
TypeScript, fourteen focused tests and ABI/default freshness passing. Interaction code and
community contracts/routes/deployment selection are unchanged; older preview evidence retains
its original revision. No new browser-interaction claim is made for numerical defaults.

The final app branch then incorporated current community main `3217bb36`, resolving three UI
conflicts and preserving that release's contracts, keeper, deployment selection, ABI and legacy
files exactly. App revision `1f2ea06a5cdb803f5655701791c16c629589debd` includes the independently
reviewed integration tree `9543190395d7982ec5177c51a17fc0bb5e787ed9`. Its compilation check,
199 affected app/shared tests and main ABI/default freshness pass; twelve existing opt-in RPC
cases skip and are not reported as passes. A read-only desktop/mobile preview on the retained
real fork checks manager discovery/settings, one-wei cap refusal, bounded cost review and manager
selection, plus community design/help navigation. It observes no send/sign RPC and no owner nonce
change. Two mistaken terminal-branch harness expectations and their failed attempts are retained.
See the app's [refresh evidence](https://github.com/ripe0x/shapes-pool-balancer/blob/codex/main-pool-app-completion/docs/receipts/manager-community-refresh/README.md).
Both public main launch switches remain false. No community transaction or live cutover follows.
