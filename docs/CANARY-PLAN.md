# Mainnet canary plan (launch step E) — DRAFT for owner approval

Nothing here is authorized until the owner approves it in writing. Every broadcast below needs its
own confirmation immediately before sending: chain, signer, target, decoded arguments, value and
consequence (chain operations rule 2).

## Preconditions (all must hold)

1. Audit B and the A/B comparison are complete, every executed finding is repaired or explicitly
   accepted by the owner, and the candidate commit is frozen.
2. The owner has signed the current asset-flow outcomes (`asset_gate.py` reports PASS).
3. `keeper/rehearse_current.py` passes on a fork of the block the deployment will use: positions
   listed, ledger closes to the wei, zero reverted keeper transactions.
4. Owner key: a multisig or hardware wallet (accepted risk B3). Its address goes in the values file.
5. Keeper key: a fresh hot wallet funded with at most 0.05 ETH, used only by `keeper/keeper.py`.

## Deployment (broadcasts 1 and 2)

- Values: `deploy/canary.example.json` with the real `owner`; seed 0.01 ETH. Same script as every
  rehearsal (`script/Deploy.s.sol`), signed with the existing keystore (`--account`), never a raw key.
- Readback after the receipt: bytecode hash equals the frozen build; `owner`, `keeperPolicy`, every
  `getParams()` field and `budget()` equal the values file; `edge(3)` returns ok and a backing.

## Stages

| Stage | TVL cap | Positions | Runs until | Then |
|---|---|---|---|---|
| 1 | 0.5 ETH (owner deposit only) | 10 | one full cycle: deposit, priced, built and listed, one real selection resolved and relisted, a partial redemption claimed | owner raises cap |
| 2 | 2 ETH | 30 | 14 days or 5 real selections, whichever is later | review against the scorecard |

Stage 1 sets `tvlCap` 0.5 ETH and `maxPositions` 10 in the deploy values; stage 2 raises them with
`setParams` (immediate, D58).

## Checks read from the live chain (each keeper pass and daily)

| Outcome | Live check | Band |
|---|---|---|
| Liabilities never spent (O5) | `address(vault).balance >= pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool` | always |
| Keeper pay bounded (O2) | sum of `KeeperPaid` per day | <= 0.041 ETH in any 24 h |
| Backing rule (D62) | backing of each new listing | 0.0333 to 0.0363 ETH at canary gas |
| Exits work (O3, O6) | each redemption request priced within 2 blackouts with a drained queue | always |
| No staging by the keeper (O10) | keeper listings with FWA status Staged | 0 |
| Holder cost (O9) | holder result after a round trip with no selections | > -1.5% |
| Keeper P&L | keeper state file: spent vs paid | no unaccepted loss |

## Stop conditions (owner calls `startWindDown()` or pauses)

Any of: a liability check fails; keeper pay above its band; a keeper transaction reverts for a
reason other than state moving on; a listing posted outside the backing band; FWA's owner changes
fees, the oracle, exemption, minimum backing or settlement rates (read each pass); a holder
redemption not priced within 2 blackouts with a drained queue; any unexplained balance change.
Wind-down is one way; holders redeem and claim as usual (they keep their shares until they do).

## What cannot be capped

- FWA's owner can change fees, the oracle, the exemption and settlement rates at any time; the vault
  reads them live. The worst observed effect in testing is listing pausing, not loss of holder ETH.
- A compromised owner key: at most the budgets' balance plus refill (about 0.055 ETH the first day,
  0.015 ETH a day after) until wind-down (B3).
- Real VRF timing, transaction ordering and the gas market: covered only by running the canary.

## After the canary

Compare live results with the scorecard; record measured times per phase; raise caps only with a
new owner decision.
