# Independent manager closeout review

Reviewed staged tree `f54a8bc22396e9f4774af219ecddbad1d15c6d47` against `6a21859`, read-only except this report. Scope: offline economic calculation, labels, source bindings, evidence inventory and unchanged deployment boundaries. No tests, model campaigns, network calls or transactions were run. Prior receipt execution and reconciliation were not independently rerun. This is bounded closeout review, not a security audit, release acceptance or profitability assessment.

## Actionable finding

**P2: the diagnostic calculation is outside the checked source inventory.** `sim/manager_closeout.py` calls `manager_standard_backing.diagnostic()`, which generates every quoted cycle result and calls `keeper/keeper.py:proposal_limits`. Its source checks cover the contract calibration and `manager-funded-reconciliation.json` source map, but that map omits both `sim/manager_standard_backing.py` and `keeper/keeper.py`. Changing either can change regenerated scorecard results while the existing source checks still pass. Bind and validate these calculation inputs against immutable hashes, and expose the complete calculation source inventory in the report. The new script itself should also be identified in its generated provenance. This does not establish that the current numbers are wrong.

## Economic assessment

The current actual-cash partition is consistent: owner funding less withdrawals is creator gross primary fees plus keeper compensation; owner wallet gas is additional, keeper net subtracts keeper wallet gas, and deployer startup is separate. The stated owner losses are negative .001940071586360229 ETH for the .5 ETH account and negative .005198947885644295 ETH for the 1 ETH account. Neither is described as a return-period comparison.

The quoted table explicitly treats k times backing as expected fee attribution under fixed proportional weights, not cash received on an acquisition. High-backing keep gains explicitly depend on a purchaser choosing to keep a .03 ETH pack instead of taking a larger bid. Standard .03 ETH backing is marked hypothetical for current manager admission. Conditional collection quotes, measured operation repricing, unmeasured paid renewal/harvest/list/sync and final-exit/startup exclusions are disclosed. The retained evidence therefore supports a limited sensitivity screen, not operating viability.

No contract, factory ownership, manager settings, participant rights or economics changed in the reviewed diff. Shared-vault and public-app gates remain closed; acceptance and signatures remain false/null. The unsigned package refresh is outside this immutable review and must retain its own binding and freshness checks. No production launch is recommended; no owner-approved outcome number is changed.

Things that don't make sense: complete accounting does not make the owner profitable; positive high-backing keep arithmetic is not evidence that purchasers will choose it; source-bound financial output must bind the code that actually calculates its rows. Authenticated billed operating costs and full-period returns remain unmeasured.

## Repair disposition

Reviewed the subsequent working-tree repair only, with no test execution. **P2 resolved.** `SOURCE_PINS` now validates the diagnostic helper, its campaign-module import, canonical keeper proposal code, configuration and payment policy before the diagnostic runs. The generated report exposes these hashes alongside the already checked reconciliation sources and the writer's own hash. Read-only SHA-256 comparison confirmed the added pins and generated writer hash match the reviewed files. The new regression changes actual diagnostic/proposal source bytes and expects source verification to reject them. The release evidence inventory includes the closeout writer, test and diagnostic helper. This disposition does not extend review to the subsequent unsigned-package preparation or establish production readiness.

Things that don't make sense: no new unresolved code finding from the repair; the economic limitations above remain, including absent billed operating costs and full-period return evidence.

## Refreshed unsigned package disposition

Reviewed immutable staged tree `b27668849b0ae85caa91dafb5829b9e6b39766eb` for package/data consistency only. No tests, builds, network calls or simulations were executed. **No actionable package finding.** Cutover `sourceSha256` and build records equal the manager manifest; all sixteen source hashes match the staged bytes. Chain IDs are 1, deployment nonces are contiguous 4178–4181, the recorded readback nonce is 4178, deployment gas limits are below 16,777,216, and deployment value is absent/zero. Only ScanLib, VaultLib, StrategyLib and PackManagerFactory deployments are present, with unsigned allowlisted fields. There is no PackVault deployment or vault seed.

Inspected the production validator's linked-initcode, CREATE2/CREATE address, constructor, nonce, chain and signed-field checks. Artifact link locations inspected in deployment calldata reference the package's library addresses; the factory constructor ends with the reviewed FWA, Shapes and ShapePacks addresses. These checks do not independently prove the current public nonce, deployed dependencies or future inclusion.

The creation template targets predicted factory `0xbb19536496e016ff33f15e8fae56bf17ccac9786`, funds .5 ETH from its reviewed owner, binds the .0005 ETH observed mint fee through the configuration hash, and retains the .001 ETH accepted maximum and explicit fixture-fee difference. It remains a template requiring refresh/estimation before signing. Keeper data is explicitly unsigned/non-live, names no vault, includes no secret and keeps sharedVaultOpen false. Acceptance retains null signature, release_ready false, economic approval false and no production recommendation. Manifest regeneration after this appended report remains the lead's final binding step.

Things that don't make sense: unsigned simulation and source matching cannot establish signing authority or production economics; freshness must be rechecked before any separately authorized signing. No new package inconsistency identified within this bounded review.
