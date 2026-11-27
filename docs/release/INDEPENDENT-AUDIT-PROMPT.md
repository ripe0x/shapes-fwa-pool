# Independent re-audit prompt (frozen candidate 0839459) — superseded by LAUNCH-AUDIT-PROMPT.md

Paste everything below the line into a fresh session with no prior context. The session must not
read earlier chats, memory, audit reports or builder notes during discovery.

---

You are an independent auditor. Run an uninformed whole-candidate audit of the personal pack
manager system, then report. This is step B of a launch audit: you get only the code, the owner's
requirements and the signed outcomes. You are uninformed, not provably blind; say so in the report.

**Target (immutable).** Repository `ripe0x/shapes-fwa-pool`, commit
`08394595651a61a374f7bee8737f2954a8424d6c`. Check out that exact commit in a fresh worktree and
confirm `git rev-parse HEAD` before starting. Do not modify the source.

**In scope.** `src/PackManager.sol`, `src/PackManagerFactory.sol`, `src/PackAccount.sol`,
`src/StrategyLib.sol`, `src/VaultLib.sol`, `src/ScanLib.sol`, `src/interfaces/External.sol`, the
unsigned deployment values `deploy/manager.json`, `deploy/manager-factory.json`, the deployment
path `script/Deploy.s.sol`, `script/DeployCore.sol`, `script/deploy.sh`, and the keeper decision
code `keeper/policy.py`. `PackVault.sol` is out of scope (closed and undeployed) except where it
shares library code with the manager.

**External integrations (real mainnet contracts, never mocked).** FWA V2 main pool
`0x958C41181182e76F221331b2755b77D9e1426A98`, Shapes `0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0`,
ShapePacks `0xf21514B090Da7dF4390803497d6ae673801E5cA7`, FWA's floor oracle, VRF and token pool.

**Read for requirements, and nothing else for intent.** `OWNER-REQUIREMENTS.md` (A8 and A9 are
current; earlier sections stand where not superseded) and the signed outcomes in
`asset-flow.json`. Do NOT read `docs/DECISIONS.md`, `docs/REPORT.md`, `docs/receipts/`,
`docs/release/` (other than this file), any `*AUDIT*` or review file, PR descriptions or commit
messages until your findings are final. They are builder notes.

**Standard.** Read and apply `/Users/dd/.agents/guidance/adversarial-security-audit-standard.md`
(launch tier, step B) and `/Users/dd/.agents/guidance/holistic-verification.md`. The economic pass
comes first and is reported separately from security, with the one-screen scorecard and your own
flow breakdown under each regime.

**Accepted, do not report as findings.** Owner-key compromise (B3). Unpaid exit work (A9.1). The
build gate not charging gas or mint fees (A9.5). You may still report a consequence of these that
the owner may not have foreseen, labelled as a question.

**Permitted methods.** Manual review, static analysis, and Foundry fork tests against Tenderly's
public gateway only:

```sh
forge test --match-path <file> --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100
```

Write new tests in a scratch directory or new files; attacker and hostile-third-party contracts are
allowed, mocks of FWA, Shapes, ShapePacks, the oracle, VRF or the token pool are not. Set `vm.fee`
and `vm.txGasPrice` wherever gas matters. Test actors come from
`makeAddr("pack-vault-test-...")` and must hold no code or ETH. Never use anvil's dev accounts. Do
not start a local anvil node (port rules apply on this machine); use `forge test` forks only. No
public transactions, no signing, no reading `.env` files.

**Budget.** 90 minutes, one continuation of up to 20 minutes only for a confirmed material finding
or an untested path that bears on an owner-approved outcome. Record time per phase.

**Questions you must answer with executed evidence or an explicit gap.**
1. Can anyone other than the owner move a manager's ETH, packs or Shapes out of it, or make it pay
   more than bounded measured keeper work?
2. Does every wei and every pack have a destination at rest across build, list, selection
   (bid, keep, silent purchaser), sync, unlist, exit, liquidation, import and withdrawal? Trace one
   full cycle at launch-scale numbers with absolute amounts.
3. Can keeper pay exceed its bound, be extracted without useful work, or starve routine work?
4. Can a manager be bricked (owner cannot recover all packs and ETH) by FWA state changes,
   including whitelist removal, oracle failure or exemption changes, kicks, blackout and queue
   states, or by a hostile caller?
5. Does the factory create managers exactly as the owner configured, with no later authority over
   them?
6. Does every manager call fit EIP-7825's 16,777,216 gas cap, and does every runtime fit EIP-170?

**Report.** Economic section (scorecard, flow breakdown, findings), security section (findings
ranked by severity, each with the counterexample attempt, commands, result), property-to-evidence
map, untested paths with what would decide them, time spent, and a "Things that don't make sense"
list. Never call the system safe, complete or release-ready.
