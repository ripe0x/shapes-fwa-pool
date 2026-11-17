# Release-candidate audit: PackVault @ 3e600e5

Auditor: independent subagent with fresh context; it did not write this code. Informed run (not blind). The report text below is
the auditor's, saved by the lead because the auditor's harness could not write files; the lead's
note at the end is marked. Tier: release-candidate audit, 90-minute cap; about 82 minutes used, no
continuation. Not a safety or release certification.

## Scope and revision

- Commit 3e600e5902665465a2ac9aa69559c219cb6fc0fc. Asset-flow source hash
  ee2b4d57f169aed8ed51c4378ed28582b022c7aa2255eac67a9416f34ba27c78 (src/, script/, foundry.toml);
  the signed asset-flow.json and every docs/receipts/flow/*.json carry this hash.
- Files: src/PackVault.sol (22,171 B runtime), src/VaultLib.sol, src/interfaces/External.sol,
  script/Deploy.s.sol, deploy/canary.example.json.
- Integrations: FWA V2 0x958C…6A98, its rewards module and token, Shapes 0x6fE9…FAf0, ShapePacks
  0xf215…5cA7, FWA floor oracle. Addresses not re-verified against live bytecode this run.

## Time per phase

| Phase | Work | min |
|---|---|---|
| 0 | standards, scope source, requirements, outcomes, system map, keeper policy, harnesses | 30 |
| 1 | economic pass: independent bucket and flow derivation, compared with SYSTEM-MAP and receipts | 15 |
| 2 | security pass; wrote and ran test/audit/AuditRoleAndKeeper.t.sol; reproduced ForkSelection, ForkVaultAdversarial, ForkVaultInvariant | 22 |
| 3 | challenge of negative conclusions; comparison with DECISIONS; report | 15 |

## Findings

### F1: LOW (trust boundary). A malicious admin can pay itself vault ETH through keeper pay

- **Where:**
  - the natspec says "neither role has any path that moves assets to itself" (PackVault.sol L42, repeated in D44)
  - `_reimburse`, `_gasCost` and `_checkBounds`
  - the bytecode bounds: MAX_KEEPER_PREMIUM_BPS 5000, MAX_GAS_CEILING 50 gwei, opGasCap ≤ 16,777,216
- **Scenario:** the admin first sets the parameters to their maximum: premium 50%, gas ceiling and maxTip 50 gwei, opGasCap 16.78M. After the 2-day delay it acts as keeper itself. It creates paid checkpoint work every 12 h with a dust deposit, and each checkpoint pays more than the gas it costs.
- **Executed:** `test/audit/AuditRoleAndKeeper.t.sol::test_adminMaxParamsSelfKeepExtraction` passes on a ~1 ETH vault:

  | One checkpoint at maximum parameters | ETH |
  |---|---|
  | Pay | 0.01062 |
  | Real gas cost at 50 gwei | 0.00781 |
  | Admin net | +0.00280 |

  Pay never exceeds the formula cap.
- **Mitigations:** the admin needs a compromised key and must wait the parameter delay. The guardian can cancel the proposal or lower the ceiling, but cannot lower the premium. Under D44 one key may hold both roles.
- **Suggested fix:** lower MAX_KEEPER_PREMIUM_BPS to roughly the design margin, or reword the claim to "bounded, delayed and guardian-dampened".
- **New:** yes.

### F2: INFORMATIONAL. Keeper premium is the largest one-way ETH cost in several regimes

In wind_down, keeper pay takes 27 bps of inflow against 20 bps for mint fees. Already disclosed (O2, D19).

### F3: INFORMATIONAL. A crown-holding listing cannot be unlisted for up to 12 h, even in wind-down

This avoids FWA's 1% early-exit fee. It is bounded and heals itself.

## Economic section

**Independent derivation, from the code alone.**

Assets:
- free ETH: balance minus escrow, redemption reserve, distribution reserve and claimables
- backing posted on FWA
- pack value in FWA custody
- inventory
- FWA fees not yet collected
- FWA token entitlements, valued at zero and burned

Liabilities, all excluded from NAV and from `_free`:
- escrow
- redemption reserve
- distribution reserve
- claimables

Shares: a non-transferable claim on NAV; 1e15 dead shares are seeded at deploy.

One-way costs:
- Shapes mint fee
- backing paid out on a bid
- FWA's 1% settlement cut on a keep or silent purchaser
- keeper gas plus premium
- the high-water mark, which only rises

Everything else round-trips.

**Comparison with the builder's map:** agrees with docs/SYSTEM-MAP.md on every bucket, flow and ratchet. The wind_down receipt agrees to the wei:

| wind_down, of inflow | bps |
|---|---|
| Redemptions to holders | 9953 |
| Keeper gas | 27 |
| Mint fees | 20 |

End vault ETH was 0.01048, holder_claim_gap 0, no mismatches.

| Property | Evidence | Result |
|---|---|---|
| Bid, keep, silent economics on real VRF | ForkSelection 4/4 | pass |
| Liabilities never spendable | ForkVaultAdversarial, INV01-04 | pass |
| No fee skim | ForkVaultAdversarial | pass |
| Reserves covered, shares and value conserved | ForkVaultInvariant 1/1 | pass |
| Checkpoint under EIP-7825 at 300 positions | ForkVaultAdversarial | pass |
| Donation and first-depositor inflation | ForkVaultAdversarial | pass |
| Guardian zeroing the ceiling does not trap holders | AuditRoleAndKeeper (0.99996 of 1 ETH redeemed) | pass |
| Role self-payment | AuditRoleAndKeeper | exists (F1) |

## Property map

| Property | Attack | Outcome | Evidence |
|---|---|---|---|
| Only the admin moves parameters | permissionless applyParams after the delay | applies only what the admin proposed | code |
| Guardian can only stop things | zero the gas ceiling | redemption still priced and claimed | executed |
| No role pays itself | maximum parameters, self-keeping | +0.0028 ETH per checkpoint (F1) | executed |
| Reentrancy on ETH send | re-enter from `receive` | reverts; claim paid once | executed |
| Reentrancy on FWA callbacks | every mutator is nonReentrant; onERC721Received is view | reasoned safe | code |
| Share inflation | 10 ETH donation before the victim is priced | victim keeps their deposit | executed |
| Keeper padding and splitting | pad the id lists | pay capped per position moved; the 30k overhead leak is accepted | code |
| Gas-price manipulation | bid far above the ceiling | reimbursed at the capped price | executed |
| Oracle failure trapping assets | repoint the oracle | exits survive | D34 regression (not re-run) |
| Token burn | stale and active ids | tolerant; unpaid | ForkTokens (not re-run) |
| Allocated exposure blocks a redemption checkpoint | over 10% of NAV allocated | reverts until settlement | reasoned only |

## Not run or untested

- **External bytecode:** live source-to-runtime correspondence of FWA, its rewards module and the oracle was not rechecked.
- **Allocated-exposure liveness:** reasoned only; it needs several VRF replays.
- **Stuck-NFT recovery:** review only (D23).
- **Invariant handler:** it skips harvest, sync, activate, burnTokens and all selections.
- **Suites not re-run:** ForkTokens, ForkReconcile, ForkMeasure, ForkVaultLifecycle, VaultFlow and the sim replay.
- **Live conditions:** the rehearsal and canary are still required.

## Things that don't make sense

1. The absolute natspec and D44 claim is contradicted by the bytecode bounds (F1).
2. MAX_KEEPER_PREMIUM_BPS 5000 and MAX_GAS_CEILING 50 gwei are 5 to 100 times the operating values, and no reason is stated.
3. The invariant handler never crosses the FWA boundary.
4. FWA-side changes since the pinned block cannot be shown on a pinned fork.

## Lead's note (not part of the auditor's text)

F1's threshold claim, "at ≤ ~15% premium self-keeping is no longer net-positive", does not match the
canary rehearsal receipts (docs/GAS.md). At the canary's 10% premium every paid call already nets the
keeper +5% to +37% of its gas, by design. Any keeper, the admin included, earns that margin.

What the bound decides is how far a malicious admin could raise it. At the canary parameters (10%,
0.5 gwei) one dust-deposit checkpoint per 12 h nets the keeper about 1e-5 ETH. At the bytecode
maxima the auditor measured +0.0028 ETH per checkpoint, about 0.0056 ETH a day if repeated every
interval. The owner decides the response (see docs/DECISIONS.md D54).
