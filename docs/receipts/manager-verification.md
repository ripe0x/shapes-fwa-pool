# Personal manager closeout: focused acceptance

**Correction, 2026-11-24:** the old return figures below are withdrawn as economic evidence. A depleted-float bug in the simulator could permit unpaid keeper work. The affected partial campaigns are preserved and marked invalid. Corrected cash protection, real-counterparty regressions and a fresh receipt calibration are being validated before the fixed-size comparison is restarted. Historical receipts retain their original code identity; they do not validate the current changed contracts. No public transaction or release is authorized.

Implementation candidate: `8463c52476246a6a669ae82a8346d36355347c83`; app: `6425e78`.
All eight Solidity source files remain exactly source set
`d85c926518a689c73c6575937fd7d3dcde0d1a484d5abfe6de6faa22a4ca8e39`.
The source hashes, complete settings, raw receipts and reconciliation are committed alongside this report.
This is implementation acceptance and unsigned preparation, not production release acceptance.
The shared vault remains closed. No public transaction, fee change, merge, live cutover or signature occurred.

| Outcome | Evidence | Result and limit |
|---|---|---|
| Individual ownership | Existing real manager ownership/isolation test; new pristine clone postflights | Factory/implementation/three linked libraries/dependencies verified; every23 scalar/28 gas setting checked; factory gains no clone authority |
| Launch recipe | Two actual local keeper builds | Six 0.03 ETH packs, 18 direct paid primary mints; six PrimaryMinted events each 1 pack / 3 Shapes/0.03 ETH/.0015 ETH fees |
| Owner-paid exits | Actual Chromium UI and CLI on new chain31337 fork26486686 | Both start with1 ETH, keeper capacities/refills all zero, genuine request waits, ownerprocess16 after real expiry, unlist/redeem/withdraw, final ETH, inventory, receipts and credit zero; no topups |
| Wallet limits | UI and CLI one-wei refusals; durable records | No submission on refusal; final signed reservationsUI.003356152646284337 ETH, CLI.000145770398408284 ETH, each below accepted .01 ETH |
| Acquired fresh/reuse cycles | Two new authentic historical-VRF traces |16 steps per mode, every accounting bucket and physical ledger reconcile0 wei; actual historical fee.001; three extra paid mints only in fresh mode; no exit minting |
| Quoted payments/receipt gas | KeeperPaid events and real billed local receipts | Two builders paid.001130826568290000 ETH, gas.000799171850776649 ETH, margin.000331654717513351 ETH at actual local prices; no payment to owner exit calls |
| Owner/creator economics | Same raw local transactions and 48 counterfactuals | Owners, keeper, creator and deployment costs reported separately; positive creator accrual does not imply owner profit |
| Manager-only deployment | SameDeploy.s.sol/deploy.sh with explicittargetmanager | Four unsigned mainnet deployment transactions, no PackVault or seed; independent encoding, dependency/link, current nonce and live-fee checks |
| Production container | Manager-only workflow | [Run 45460887589](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/45460887589) passes at 8463c52: actual factory-only entrypoint, persistent replacement/lost-response recovery and complete owner CLI exit; local Docker unavailable |

## Reproducible checks

Python runtime: the preserved `/tmp/packvault-review-packaging-venv/bin/python` environment
(eth_utils, eth_abi and numpy installed). The initial system-python attempt lacked eth_utils;
its failures are retained. No dependency cache was removed or rebuilt.

```sh
python3 script/test_release.py
python3 keeper/test_manager_exit.py
python3 keeper/test_entrypoint.py
python3 keeper/test_config.py
python3 keeper/test_policy.py
python3 sim/test_manager.py
python3 sim/test_forward.py
python3 sim/test_vault.py
python3 sim/manager_reconcile.py
CANDIDATE_RUN=1 forge test --match-path 'test/fork/ForkManager*.t.sol' \
  --match-test 'test_(managerFreshOwnerPaidExitReconcilesEveryWei|managerReuseOwnerPaidExitReconcilesEveryWei|createInitializesAtomically|onlyOwnerControls_andHandover|lifecycle_buildExitWithdrawEverything|coldKickRefundIdentifiedUnderStipend)' \
  --rpc-url https://mainnet.gateway.tenderly.co --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100
CANDIDATE_RUN=1 python3 sim/manager_assessment.py --execute --workers 4
```

Results: release 22 tests; manager exit 10; entrypoint 6; manager model 13; existing forward 2 and
vault 18; configuration/planner assert suites pass. Forge 6/6 pass. Reconciliation32/32 steps
passes to the wei. Final 48/48 modeled exits complete, with0 wei physical ledger gaps. Changed
branches were repaired and only affected checks repeated. The first completed model campaign
wrongly required draining the foreign global journal after own assets were gone; its original
38incomplete results and original costs are retained under manager-checks. The first metadata
exception and getter-display mismatch are retained too. They are not accepted economic results.

App command batch in the separate app checkout:

```sh
npm run typecheck
npx vitest run app/src/main-pool.test.ts app/src/main-pool-settings.test.ts \
  app/src/main-pool-exit.test.ts app/src/main-manager-exit.test.ts app/src/errors.test.ts \
  app/src/creation .test.ts app/src/creation-replacement.test.ts app/src/chain.test.ts app/src/policy.test.ts
npm run build:app
SHAPES_FWA_POOL=/Users/dd/CascadeProjects/shapes-fwa-pool-completion node scripts/export-main-pool-abi.mjs --check
```

App 60 tests pass; 10 optional tests skip without their opt-in network/creation settings. Those
include unchanged community live-creation/replacement, policy/mainnet backup and wallet-fallback
checks. Their separate prior evidence is preserved; no success is claimed from a skip.
A changed banner received focused navigation checks 24 pass/3 skip and a fresh typecheck. An isolated
staleABI copy is rejected. Actual Chromium actions on the manager-only preview passed creation,
pause/resume, settings, cap refusal, settlement wait and complete withdrawal. The initial driver
reconnect race failed before settings submission, was repaired, and its failure is retained.

The local production entrypoint ran with FACTORY and no VAULT. Its canonical event index resumed
bounded backfill across passes. Two real receipts minted three packs each. The fresh deployment
used the same target-manager wrapper as unsigned public preparation; two pristine account
postflights checked all 51 settings. The UI and CLI exit controllers sent only real protocol calls.
Raw transaction gas, effective price, attached ETH and receipt status are in manager-closeout.json .
Forge aggregate test gas is never billed transaction gas. Contract bytecode is unchanged; the
manager remains17742 bytes, ScanLib22993, VaultLib22260, StrategyLib18090, all below EIP-170.
Every actual submitted local transaction fits16777216 gas.

## Same-scenario cash flows

| Local path | Owner funds | Owner receives | Owner wallet gas | Owner net | Notes |
|---|---:|---:|---:|---:|---|
| UI |1 ETH |.994736320288405000 ETH |.002967689025801520 ETH |−.008231368737396520 ETH |Includes creation,pause,resume,settings and exit; actual wallet priority about1 gwei |
| CLI |1 ETH |.995132853143305000 ETH |.000166905134205993 ETH |−.005034051990900993 ETH |Includes creation,settings and exit; actual configured.05 gwei tip plus localbasefee |

Each account's net wallet change independently equals withdrawals−funding−wallet gas.
The two accounts' principal shortfall equals actual.009 ETH primary fees plus actual
.00113082656829 ETH keeper compensation . Keeper wallet change independently equals compensation
minus billed gas. Shapes pending-fee accrual independently matches all 18 paid mint events.
One-time factory/library deployment gas was.002622035765244119 ETH on this fork, separate from
per-owner returns. Public simulation estimates are price-sensitive: approximately.01587124 ETH
at its.591164821 gwei maximum, not a billed cost. Purchasers fund their own genuine requests;
no purchaser cash is credited as a manager subsidy. No creator withdrawal/net-profit claim is made.

Historical matched acquired cycles, before owner wallet gas: fresh returns.783057722058121371 ETH;
reuse .786303722058121371 ETH from 1 ETH. Both lose.21 ETH actual listing backing after a bid.
Fresh pays .006 ETH primary fees, reuse .003 ETH. Difference .003246 ETH is .003extra paid mint fees
plus .000246extra quoted compensation . These genuine transitions use historical.001mint fees.

The final 48-run current-fee study is in manager-economics.md. Its gas prices.2/.5 gwei are fixed-price
sensitivities applied to billed gas units/conservative allowances, not the actual UI wallet prices.
Recorded-month fresh cells at current .0005fee have two-draw medians−28.4847%/−28.8455% on .5 ETH
and−20.7879%/−21.3863% on 2 ETH, for .2/.5 gwei respectively. Every fresh baseline draw loses.
All quiet-demand cells lose; favorable one-draw synthetic bursts do not validate an expected return.
Neither the pooled 10% hurdle nor its former 72 ETH pricing constraint applies to one-owner managers.

## Settings and recommendation

The full creation inventory is deploy/manager.json: 23 scalars and 28 named gas coefficients.
All are hashed for sensitive work and immediately adjustable by each manager owner. Ownership
handover retains its separate 48 hour acceptance window. Factory deployment stores dependencies,
not a global manager owner or economic policy. Existing inventory retains its actual face/shape
counts. Owner recovery and withdrawal remain available independently of stale economic previews.

| Candidate value | Status |
|---|---|
| Mask 8, pack0.03 ETH, three directly paid0.01 ETH Shapes |Selected launch recipe; owner adjustability retained |
| Actual mintfee.0005 ETH at26486686; accepted maximum.001 ETH |Read-only observation and explicit acceptance limit; no public fee transaction |
| Backing70000 bps=.21 ETH |Provisional evaluation value, no production approval |
| FreshAfterAcquisition, one float .2141275 ETH at accepted limit |Explicit evaluated mode; reuse alternative evaluated; no silent fallback |
| Maintenance reserve.005 ETH |Candidate; greater than zero, not a perpetual expense guarantee |
| Routine/essential ceiling.5 gwei; tip.05 gwei |Candidate quoted work calibration; direct owner wallet fees are separate |
| Routine cap/refill .03 ETH/.01 ETH per day; essential .01 ETH/.005 ETH per day |Spending permission, never funding; owners can set0 and still pay exit gas |
| Workfee.00002 ETH/unit, markup 0, keeper share 2500 bps |Candidate; verified-progress payment code unchanged from source R |
| Edge 100 bps; buffer 0; distributions 0; TVL cap 0 |Candidate; unlimited total positions with existing bounded incremental work |
| Uplift 25 bps |Provisional shared Params field; no manager share-pricing gate |

Current-fee fresh opening cash is .4610425 ETH at.2 gwei or.461605 ETH at.5 gwei, excluding clone
wallet gas. It includes .03pack,.21backing,.0015actual mint fees, initial quoted work,.005reserve
and the conservative accepted-fee float. One float cannot fund arbitrary repeated early acquisitions.
Cash shortage and permission exhaustion remain distinct waits. Increasing an allowance supplies no ETH.

Engineering acceptance is met within this focused evidence. Keep the unsigned package and PRs draft:
there is no approved manager return hurdle, and this small conservative activity evaluation does
not justify recommending these production economics. The main tradeoff is actual bid backing loss
and repeated paid fresh mints against uncertain fee income; more opening funding and lower actual
mint fees do not remove that risk. Reuse avoids replacement mint fees but changes creator revenue
and capital exposure. The current app creation threshold is a UI restriction, not a contract minimum.

## Remaining evidence limits

The model also flags paid list and sync gas as unmeasured for its call sizes; their quote allowances
are proxies, not newly billed receipt curves. Standalone genuine-credit harvest and authentic-VRF
renewal have real-contract functional proofs
but no new billed standalone local receipts. Hardware/encrypted-keystore signing is not exercised;
existing read-only signer mounts are required and live secret stores/Fly services are untouched.
Recovery-only oversized inventory was not reached in the new UI run; its existing source R contract
regressions and new bounded calldata checks remain separate evidence. Two draws are not confidence
bounds or demonstrated APR. Ordinary archived VRF/processing is funded by the historical external
actors. Model pending-prefix gas is a conservative optional reserve, including accounts whose own
book may already be empty; ceil(N/16) is an ideal full-batch count and staggered readiness may need
more smaller calls. Charging each pending record a full single-request sample is a conservative
cost proxy, not an exact necessary-call count. The legacy vault has 0.01 ETH and supported holder-liability getters return zero; its
chargeRefundReserve selector is unsupported and is not reported as zero. No legacy asset is moved.
No public transaction or live cutover is validated.

Things that don't make sense: positive creator fee accrual coexists with substantial owner losses;
a funded allowance creates no cash; a perfect ledger is not evidence of attractive returns.

The independent Docker fork has one explicitly owner-funded growth contribution of 0.5 ETH after initial 1 ETH funding. This is not an exit topup. Fifteen paid primary mints accrue 0.0075 ETH; the owner receives 1.491851969525290000 ETH and pays 0.000247415615501588 ETH wallet gas, for net −0.008395446090211588 ETH. Exit alone pays no keeper and spends 0.000137615198924166 ETH gas, with signed maxima 0.000217617245239094 ETH under the 0.01 ETH cap. No owner funds are added during exit. The final manager has zero cash, inventory, pending receipts and credit. Raw CI evidence is manager-image.json.

The existing shared-app CI also passed on `6425e785269fc7a4178a381162180b08fdf83cc0`: [run 45460841268](https://github.com/ripe0x/shapes-pool-balancer/actions/runs/45460841268). It ran the configured full TypeScript/app checks and existing real-fork community suites without changing community contracts or CI. The focused manager evidence above remains separate. The unsigned target fingerprint check passed at documentary revision c83a429; the broadcast authorization check correctly returned exit1 for the absent owner signature. Raw tool logs retain original whitespace; source and document diff checks exclude those untouched raw-output bytes.
