# Launch audit request (candidate 8e9034d)

Launch audit per section 0b of `/Users/dd/.agents/skills/adversarial-audit/references/runbook.md`:
A informed, B uninformed in a stripped clone, C compare, D rehearsal. Step E (canary plan) is
omitted by owner decision: there is no canary. This supersedes `INDEPENDENT-AUDIT-PROMPT.md`
(the B-only audit of 0839459).

Two prompts follow. Paste the lead prompt into a fresh session. The lead prepares the clone and
starts step B in a separate fresh session with a different model, using the second prompt.

---

## Lead prompt (steps A, C, D and the report)

```text
Run a launch audit: follow section 0b of
/Users/dd/.agents/skills/adversarial-audit/references/runbook.md (re-read it; it changes), and the
standard it names. Step E is omitted: the owner has decided there is no canary.

Repo: /Users/dd/CascadeProjects/shapes-fwa-pool
Candidate revision: 8e9034d35131d29e6ed1f51a2ab0f09e3e3515a2 (branch claude/manager-launch-fixes). Confirm it with
`git rev-parse 8e9034d` and pin it in your own fresh worktree. Do not modify tracked files.
Last examined revision: none: whole candidate. (An uninformed audit of 0839459 exists; it is a
prior report. Do not open it, or audit/, test/audit/, test/research/, docs/receipts/ or
docs/release/history/, until your own attacks are written and run.)

Product being launched: personal pack managers only (PackManager clones from PackManagerFactory)
on the FWA V2 main pool. PackVault stays closed and undeployed: in scope only where it shares
library code with the manager.

Scope (A and B): src/PackManager.sol, src/PackManagerFactory.sol, src/PackAccount.sol,
src/StrategyLib.sol, src/VaultLib.sol, src/ScanLib.sol, src/interfaces/External.sol;
deploy/manager.json, deploy/manager-factory.json, script/Deploy.s.sol, script/DeployCore.sol,
script/deploy.sh; keeper/policy.py and the keeper code that builds, prices and signs
transactions (keeper/keeper.py and what it imports); the configuration-hash and postflight
checks in script/release.py and keeper/config.py.
External contracts (real mainnet, never mocked): FWA V2 0x958C41181182e76F221331b2755b77D9e1426A98,
Shapes 0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0, ShapePacks
0xf21514B090Da7dF4390803497d6ae673801E5cA7, FWA's floor oracle, VRF and token pool. Use their
verified deployed source.

Owner requirements: OWNER-REQUIREMENTS.md, A8 and A9 current, earlier sections where not
superseded. asset-flow.json is UNSIGNED and describes the closed vault at old numbers: there are
no signed outcomes for managers. Derive the outcomes to check from A8/A9 and report that gap.

Accepted by the owner, not findings (report an unforeseen consequence as a question only):
owner-key compromise (B3); unpaid exit work (A9.1); the build gate charging no gas or mint fee
(A9.5); the factory admin choosing the code future managers run (A9.8).

Rules that bind every step: no mocks of FWA, its VRF, the oracle, Shapes, ShapePacks or the token
pool; attacker and hostile-third-party contracts are fine. Selections only from replaying real
request and fulfillment calls (test/fork/ForkSelection.t.sol, sim/selection_fixture.py); do not
use vm.transact. Test actors from makeAddr("pack-vault-test-...") asserted to hold no code or
ETH; never anvil's dev accounts. Set vm.fee and vm.txGasPrice wherever gas matters. Mainnet RPC
only https://mainnet.gateway.tenderly.co with --fork-retries 30 --fork-retry-backoff 5000
--compute-units-per-second 100. No public transactions, no signing with real keys, no reading
.env files. Local anvil only on port 8545: it currently runs the owner's dashboard fork, so ask
the owner before stopping it and restore it afterwards; never touch the anvil on 18553.

Step B setup (you do this before starting A, and do not read B's output until C):
1. Make a history-free clone so commit messages and branch names cannot leak:
     mkdir -p /private/tmp/launch-audit-B && cd /private/tmp/launch-audit-B
     git -C /Users/dd/CascadeProjects/shapes-fwa-pool archive 8e9034d | tar -x
     cp -R /Users/dd/CascadeProjects/shapes-fwa-pool/lib .   # submodules are not in the archive
     git init -q && git add -A && git commit -qm candidate
2. Delete from it: docs/ (all of it), audit/, test/audit/, test/research/, sim/out/,
   deploy/manager-unsigned-history/, every deploy/*unsigned*, *readback*, *observation*,
   *manifest*, *dry-run* file, AGENTS.md, and any keeper/discovered-*.json. Keep src/, test/fork,
   test/utils, test/fixtures, test/scenario, sim/*.py, keeper/, script/, deploy/manager.json,
   deploy/manager-factory.json, deploy/mainnet.json, OWNER-REQUIREMENTS.md, asset-flow.json,
   foundry.toml and lib/. Commit the deletion. Source comments still name decision ids (D86,
   A9...); that residue is accepted and must be stated in B's report.
3. Start B in a new session (a different model from yours) with the "Step B prompt" in
   docs/release/LAUNCH-AUDIT-PROMPT.md, unchanged except the clone path if you changed it.

Budget: A 90 minutes, B 90, C 30, D 60. Caps, not targets; one continuation of at most a quarter
of a step's cap, only for a confirmed material finding or an untested path bearing on an A8/A9
outcome. Record time per step and one run-log line per step A to C.

Step D (rehearsal): one run on a fresh 8545 fork of the current block through the production
path: script/deploy.sh deploy/manager-factory.json --target manager on the local fork, then
script/release.py postflight-manager, a manager created through the balancer app's create flow
(/Users/dd/CascadeProjects/fwa-pool-balancer/.worktrees/manager-designer/app, pointed at the
fork), and the real keeper (keeper/keeper.py --factory <fork factory>) doing build, list and
sync, then an owner exit and full withdrawal. Real signed transactions and real gas fields, no
cheatcodes after setup. Rehearsal accounts are fresh, created for this run as encrypted
keystores; no plaintext key in any file, log or command. Reconcile every wei and pack of that run
with the fork-test regimes and explain every difference.

Report A, B and C as one document at audit/launch-8e9034d/REPORT.md in your worktree (untracked;
do not commit): findings ranked by consequence with which audit found each, executed or
reasoned, ETH impact and smallest fix; the economic section (scorecard and your own flow
breakdown under each regime) before security; the comparison table; what neither examined; the
rehearsal reconciliation; "Things that don't make sense". Write SOURCE_HASH only after repairs
are re-attacked. Never call the candidate safe, clean, complete or release-ready. Do not repair
code, push, merge, deploy or broadcast.
```

---

## Step B prompt (uninformed; paste into a fresh session with a different model)

```text
You are an independent auditor. Run an uninformed whole-candidate launch audit (step B of
section 0b of /Users/dd/.agents/skills/adversarial-audit/references/runbook.md; re-read it) of
the code in /private/tmp/launch-audit-B, then report. You get only the code, its tests and the
owner's requirements. You are uninformed, not provably blind: say so.

Do not read: earlier chats, memory, any other checkout of this repository on this machine
(including /Users/dd/CascadeProjects/shapes-fwa-pool and its worktrees), audit or review reports,
decision logs, PR descriptions, or anything outside the clone except the audit standard, the
runbook and /Users/dd/.agents/guidance/holistic-verification.md. Paths removed from the clone on
purpose: docs/, audit/, test/audit/, test/research/, sim/out/, the unsigned deployment packages
and AGENTS.md. Source comments still name decision ids; treat them as code comments, not intent.

Product: personal pack managers (PackManager ERC-1167 clones from PackManagerFactory) that list
ShapePacks on the FWA V2 main pool. PackVault is closed and undeployed: in scope only where it
shares library code with the manager.

Scope: src/PackManager.sol, src/PackManagerFactory.sol, src/PackAccount.sol, src/StrategyLib.sol,
src/VaultLib.sol, src/ScanLib.sol, src/interfaces/External.sol; deploy/manager.json,
deploy/manager-factory.json, script/Deploy.s.sol, script/DeployCore.sol, script/deploy.sh;
keeper/policy.py and the keeper code that builds, prices and signs transactions; the
configuration-hash and postflight checks in script/release.py and keeper/config.py.
External contracts (real mainnet, never mocked): FWA V2 0x958C41181182e76F221331b2755b77D9e1426A98,
Shapes 0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0, ShapePacks
0xf21514B090Da7dF4390803497d6ae673801E5cA7, FWA's floor oracle, VRF and token pool.

Requirements: OWNER-REQUIREMENTS.md (A8 and A9 current; earlier sections stand where not
superseded). asset-flow.json is unsigned and describes the closed vault; managers have no signed
outcomes, so derive the outcomes to check from A8/A9 and report that gap. Derive your own system
map, flow breakdown and attack list from the code.

Accepted by the owner, not findings (report an unforeseen consequence as a question only):
owner-key compromise; unpaid exit work (A9.1); the build gate charging no gas or mint fee (A9.5);
the factory admin choosing the code future managers run (A9.8).

Methods: manual review, static analysis, and Foundry fork tests:
  forge test --match-path <file> --rpc-url https://mainnet.gateway.tenderly.co \
    --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100
Write new tests in new files inside the clone. Attacker and hostile-third-party contracts are
allowed; mocks or stubs of FWA, its VRF, the oracle, Shapes, ShapePacks or the token pool are not,
and no vm.mockCall, vm.store or vm.deal on those contracts. Selections only from replaying real
request and fulfillment calls (see test/fork/ForkSelection.t.sol and sim/selection_fixture.py);
do not use vm.transact (it re-forks and drops local state). Set vm.fee and vm.txGasPrice wherever
gas matters. Test actors from makeAddr("pack-vault-test-...") asserted to hold no code or ETH;
short labels map to real mainnet addresses. Never use anvil's dev accounts. Do not start any
anvil node; use forge test forks only. No public transactions, no signing, no reading .env files.

Budget: 90 minutes; one continuation of up to 20 minutes only for a confirmed material finding or
an untested path bearing on an A8/A9 outcome. Record time per phase.

Answer each with executed evidence or an explicit gap:
1. Can anyone other than a manager's owner move its ETH, packs or Shapes out, or make it pay more
   than bounded measured keeper work?
2. Does every wei and every pack have a destination at rest across build, list, selection (bid,
   keep, silent purchaser), sync, unlist, exit, liquidation, import and withdrawal? Trace one full
   cycle at launch-scale numbers from deploy/manager.json with absolute amounts.
3. Can keeper pay exceed its bound, be extracted without useful work, or starve routine work?
4. Can a manager be bricked (its owner cannot recover all packs and ETH) by FWA state changes,
   including whitelist removal, oracle failure or exemption changes, kicks, blackout and queue
   states, or by a hostile caller?
5. Does the factory create managers exactly as the creator reviewed (including across an
   implementation change), and does the factory or its admin have any authority over a manager
   after creation?
6. Does every manager call fit EIP-7825's 16,777,216 gas cap, and every runtime fit EIP-170?

Report at /private/tmp/launch-audit-B/REPORT.md: economic section first (scorecard, flow
breakdown under each regime, findings), then security findings ranked by severity, each with the
counterexample attempt, command and result; property-to-evidence map; untested paths with what
would decide them; time spent; a "Things that don't make sense" list. Never call the system safe,
complete or release-ready. Do not repair code outside new test files.
```
