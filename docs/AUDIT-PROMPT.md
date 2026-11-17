# Release audit prompt: PackVault at ba8d26e

Paste everything below the line into a fresh session (no access to this repository's chat history).

---

You are auditing PackVault, an immutable pooled vault on Ethereum mainnet that takes holders' ETH,
builds Shape packs and lists them on the FWA V2 main pool. Treat it as code that holds and moves
other people's assets. Your job is to find what is wrong, not to confirm that it is right.

## Target

- Repository: `/Users/dd/CascadeProjects/shapes-fwa-pool`, branch `main`, commit `ba8d26e`.
  Freeze it: work in a fresh worktree at that commit (`git worktree add ../pv-audit ba8d26e`), and
  record `python3 ~/.agents/guidance/asset-flow-kit/asset_gate.py <worktree> --print-source-hash`
  (expected `91ad994fd2c1175b18fd8197b3469d04797fb33db7cfcea9d126ead7c476e1b2`).
- In scope: `src/PackVault.sol`, `src/VaultLib.sol`, `src/KeeperPolicy.sol`,
  `src/interfaces/External.sol`, `script/Deploy.s.sol`, `deploy/canary.example.json`, and the
  off-chain keeper that moves money: `keeper/keeper.py`, `keeper/policy.py`, `keeper/tx.py`.
- Out of scope: FWA, Shapes, ShapePacks, the FWA token and rewards contracts. They are deployed,
  immutable third parties; read them to understand behaviour, report a defect in them only where it
  harms the vault.

## Standard and method

- Tier: **launch audit, step A** (a whole-candidate release-candidate audit) under
  `~/.agents/guidance/adversarial-security-audit-standard.md`, following runbook section 0b of
  `~/.agents/skills/adversarial-audit/` (not the isolated audit: no runner, sealed lanes or source
  manifest). Order: economic pass first (`~/.agents/guidance/holistic-verification.md`: scorecard,
  breakdown under each regime, independent derivation), then the security pass, then one
  fresh-context challenge of the consequential claims. Report economic and security findings
  separately. The run is informed; label it so.
- Do your own analysis before reading `audit/`, `docs/REPORT.md` sections 1 and 14 to 16, or the
  "Found" and "Evidence" parts of `docs/DECISIONS.md`; then use them only to reconcile.
- Read for requirements: `OWNER-REQUIREMENTS.md`, `asset-flow.json` (outcomes O1 to O10 with
  numeric bounds), `docs/SYSTEM-MAP.md`, `docs/GAS.md`, `docs/KEEPER.md`, the decision titles and
  "Owner"/"Chose" parts of `docs/DECISIONS.md`, and `AGENTS.md` (commands and repo rules).

## Rules

- No mocks of FWA, its VRF, oracle, Shapes, ShapePacks or the token pool; no `vm.mockCall`,
  `vm.mockCallRevert`, or `vm.store`/`vm.deal` faking a protocol's own state. Attacker contracts and
  hostile policies you write and deploy are fine. Acquisitions that select vault listings come only
  from replaying real request and fulfillment calls (`test/fork/ForkSelection.t.sol`).
- Mainnet fork RPC: `https://mainnet.gateway.tenderly.co` only, with
  `--fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100`. Local anvil forks on
  port 8547 for the keeper (`keeper/rehearse_canary.py` shows how). Never anvil's default dev
  accounts; use fresh `makeAddr` actors asserted to hold no code or ETH.
- Foundry runs at gas price 0 unless you set `vm.fee` and `vm.txGasPrice`; set them wherever a
  result depends on gas. Every vault call must fit EIP-7825's 16,777,216 gas.
- Do not broadcast to any live network, deploy, sign, or spend real funds. Do not edit the
  repository outside your worktree. Do not fix code; report.
- Caps: **90 minutes elapsed and 3,000,000 tokens**, whichever comes first. One continuation of at
  most 22 minutes, sized before it starts, only for a confirmed material finding whose impact needs
  sizing or an untested path that bears on an asset-flow outcome. Every other untested path is an
  open gap with what would decide it. Record time per phase. A timeboxed run is never reported as
  clean, complete or release-ready.

## What the owner has decided (requirements, not findings)

Test against these; a defect is code that breaks them, or a requirement that does not make sense.
- One immutable `owner` sets parameters (within bytecode bounds) and the keeper payment policy with
  no delay, pauses deposits and listing (one way) and starts wind-down (one way). The owner has no
  path to take assets other than what any keeper is paid. (D58, D59)
- Keeper pay: the vault's envelope is quoted gas per operation x `min(basefee + maxTip, gasCeiling)`
  (plus `payMarkupBps` on routine work) + `workFee` per completed unit. A replaceable policy
  contract proposes pay through a 50,000-gas staticcall; the vault pays
  `min(offer, envelope, funding cap, free ETH, budget)` and reverts below the caller's `minPay`.
  Pay never depends on the caller's gas use or price. A failing policy must never block work.
  (D56, D57)
- Deposits pay a checkpoint charge; the deployment charge is escrowed with the deposit and earns no
  shares; redemptions pay checkpoint and unwind charges. Routine and essential budgets refill to
  bytecode maxima; raising a cap never refills. (D56)
- Liabilities (escrowed deposits, redemption and distribution reserves, settled-but-unclaimed ETH,
  the processing pool) are never deployable or payable to keepers. (D32)
- FWA token rewards are claimed and burned, never sold; the burn is unpaid and public. (D43, D50)
- Canary: 2 ETH TVL cap, 30 positions, 0.5 gwei ceiling, 0.05 gwei tip, 0.00002 ETH work fee,
  markup 0, budgets 0.03/0.01 ETH refilling 0.0008/0.0002 ETH a day.

## Questions to answer, with numbers

1. Can anyone (holder, keeper, purchaser, FWA's owner, a hostile policy, the owner) take ETH, packs,
   Shapes or shares they are not owed, or make holders' assets unrecoverable? Show the path and a
   fork test.
2. Can maintenance or exits be blocked: by gas, a policy, FWA's queue or oracle, a pause, wind-down,
   budget exhaustion, or EIP-7825? What restarts each?
3. Share accounting: does every wei that enters leave to the right party across deposit, cancel,
   checkpoint, redeem, claim, distribution and wind-down? Trace each bucket in
   `asset-flow.json` through full cycles under each regime, and run each one-way flow as a round
   trip. List every value that only ratchets up.
4. Keeper economics at 0.15, 0.5, 1.0, 1.5 and 5 gwei basefee: pay vs billed gas per operation;
   any profitable manufactured work (dust deposits, splitting, repeats, induced syncs)?
5. Owner compromise: worst-case extraction in the first 24 hours and per year at canary values
   and at the bytecode maxima; anything beyond keeper pay?
6. Off-chain keeper: can it lose money it did not accept (`--max-loss-wei`), double-send, mis-sign
   after a restart, replacement, lost response or reorg, or follow a malicious policy into a loss?
7. Does `sim/vault.py` still mirror PackVault (`python3 sim/reconcile.py` after
   `test/fork/ForkReconcile.t.sol`)?

## Deliverable

Write `audit/release-ba8d26e/REPORT.md` and `audit/release-ba8d26e/SOURCE_HASH` in your worktree,
following the report contract:
- a one-screen scorecard first (security findings by severity, economic outcomes against
  `asset-flow.json` bounds, coverage and what was not examined);
- security findings and economic findings in separate sections, each with file:line, a concrete
  failure scenario with absolute amounts, and the fork test that proves it (or "unproven" and why);
- the commands you ran with exit status;
- a "Things that don't make sense" list, including doubts about the requirements themselves.

Your conclusions bound what you examined; do not state that the code is safe or the audit exhaustive.
