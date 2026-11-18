# Incremental position accounting milestone

November 18, 2026

## Result

The accounting prototype passes the next milestone. Running totals match an independent valuation of all positions, and valuation work stays constant as bookkeeping grows from 301 to 1,000 to 10,000 positions.

The external integration also passes 25 distinct fork tests against the deployed FWA and shape pack contracts. Those tests cover the acquisition cursor, receipt completeness, fee accounting, settlement ordering, returned inventory, identifier retirement and reuse, and several adverse buyer actions.

This is a research implementation under `test/research/`. Production `PackVault`, strategy rules, keeper code, deployment scripts, and mint policy are unchanged. The production 300 position ceiling remains until this accounting is integrated into the share vault and its existing flow tests pass.

## What was built

| File | Responsibility |
| --- | --- |
| `IncrementalLedger.sol` | Pure accounting: tracked backing, idle inventory, active backing, fee aggregates, allocated exposure, and a bounded allocation queue. |
| `IncrementalFWA.sol` | Authenticates changes against the real deployed contracts, advances the acquisition cursor, reconciles identified receipts, and provides a checkpoint valuation with completeness guards. |
| `IncrementalLedgerModel.t.sol` | Independent full valuation model, randomized histories, rounding checks, duplicate rejection, owed claims, and scale measurements. |
| `IncrementalFWAFork.t.sol` | Real FWA integration and independent valuation by enumerating actual listing records and unique pack ownership. |
| `IncrementalAdversarial.t.sol` | Independent tests for burned or modified kept packs, later fee changes, and retired identifiers interacting with later payments. |
| `ReceiptIdentity.t.sol` | The earlier receipt probe and historical replay fixture, reused by the integrated adapter. |

The prototype has one accounting book. It introduces no pool factory or separate vaults.

### Running value

The ledger maintains the total backing of tracked shapes through their different custody states. Listing, selection, bid return, and a recoverable return claim preserve the pack's conservative value P. A keep removes P. A redemption exchanges P for actual cash.

Active FWA backing B is separate. A selection or withdrawal removes B from that active total. Real cash and live FWA fee credit supply the other value components.

Idle value is cached separately for inventory operations. An unsynchronized bid return still has the correct NAV even though its pack is not yet available for redemption or relisting through the ledger.

### Complete processing of outside changes

The adapter reads FWA's ordered acquisition journal from its saved cursor. Only completed new entries are processed. A selected listing belonging to the vault leaves the active aggregates exactly once.

The receipt handler identifies keep and kick payments using unique quantized backing and synchronous checks against FWA. The adapter inherits the same prepared receipt storage and initialized counter that resolved the earlier receiver stipend failure.

When a keep receipt arrives before its acquisition entry has been processed, it stays pending. A supplied terminal ID ahead of the cursor is deferred. Once its selection is accounted for, its receipt can be consumed and its old identifier retired.

The adapter clears the backing lookup before clearing its receipt slot or permitting a returned pack to leave custody. Every remaining live lookup therefore refers to intact receipt storage and a valid lifecycle.

### Constant work valuation

The valuation reads cached principal and backing, actual cash, live FWA fee credit, and one authenticated active fee witness. A fee debt histogram supplies the exact correction for FWA's floor and ceiling rounding.

Checkpoint guards additionally require the current journal cursor, zero pending receipts, the existing FWA window and drained request queue, a current allocation queue head, no overdue allocation, and the allocation exposure bound.

There is no portfolio loop on the checkpoint path. Catchup work is bounded per call. The prototype limits a call to 16 acquisition and terminal items combined, plus at most 16 queue cleanup entries. That bounds transaction work without limiting the total number of positions.

## Independent reference and scale evidence

The model reference stores custody and debt per asset. It derives principal, idle inventory, active backing, active count, debt sum, allocated value, and individual fees by scanning its complete asset array. It does not use the ledger's aggregate balances or fee histogram to calculate expected totals.

Seven model test functions passed. The randomized test exercised 256 histories of 160 steps, totaling 40,960 steps, with an independent comparison after each step. The three scale cases also performed 64 randomized steps each, plus measured selection, keep, and queue cleanup transitions.

Cold kernel gas was identical at all three sizes:

| Operation | 301 positions | 1,000 positions | 10,000 positions |
| --- | ---: | ---: | ---: |
| NAV with zero pending fees | 18,576 | 18,576 | 18,576 |
| NAV with positive pending fees | 18,660 | 18,660 | 18,660 |
| Apply one selection | 124,129 | 124,129 | 124,129 |
| Apply one keep | 32,514 | 32,514 | 32,514 |
| Prune one resolved allocation | 35,418 | 35,418 | 35,418 |

These figures measure calls to the accounting kernel through its test harness. They exclude external FWA reads and production share processing. The meter uses a fresh call frame and explicitly cooled target storage, so reference array growth and warm setup reads do not distort the comparison.

The scale cases contain bookkeeping positions. They do not create 10,000 actual FWA listings. There are no external contract or VRF mocks. Deployed contract behavior is tested separately on a real mainnet fork.

Constructing 11,301 total model positions through separate calls and repeatedly performing the reference scans consumed 3,735,359,199 total test gas. The enclosing scale fixture therefore uses a 10,000,000,000 gas test budget. This is not an onchain transaction proposal. Individual measured ledger operations are separately checked against the 16,777,216 transaction limit. The scale run took 118.56 seconds.

Exact outputs, commands, and source hashes are in `docs/receipts/incremental-model-results.txt` and the adjacent JSON file.

## Real FWA integration evidence

The fork reference independently enumerates:

1. Actual vault cash and FWA fee credit.
2. Each unique known pack currently owned by the vault, at its actual live value.
3. Actual FWA Active and Allocated records and return claims.
4. Each active listing's individual pending fees.

It never consults the kernel's position state to decide whether an asset exists. This prevents a missed kernel transition from also disappearing from the expected valuation.

Twenty tests passed in the integrated suite. A followup added one distinct cursor progress test and strengthened the existing checkpoint window test. Four additional independent adversarial tests passed. The total is 25 distinct fork test functions.

### Confirmed behaviors

* Both selection before settlement and settlement before selection bookkeeping produce the same correct final valuation.
* Missing acquisition processing or an unconsumed payment blocks pricing.
* Repeated terminal IDs do not consume a payment or update principal twice.
* A bid return preserves NAV before its inventory record is synchronized.
* Returned packs cannot be redeemed or relisted before the old position retires.
* The same backing amount can safely identify a later listing after retirement.
* A kick updates accounting even though it does not add an acquisition record.
* Real fee accrual and harvesting match the direct per listing fee sum. A zero fee witness cannot conceal another active listing's earned fees.
* Blackout, request drain, and expired allocation guards remain enforced.
* Completed cursor progress survives a later FWA journal entry arriving between maintenance calls.
* A buyer can keep and burn the pack before synchronization; the recorded payment remains consumable.
* A buyer can extend a kept pack from 0.03 to 0.04 eth and gift it back; the old P is removed and the actual new value is registered once.
* A payment recorded at a 100 basis point fee remains correct after FWA changes its live fee to 500 basis points.
* Burning a retired bid return cannot make its stale ownership lookup disrupt a later colliding kick.

The prototype's complete checkpoint valuation and guards used 82,918 gas in the measured cold real FWA case. This excludes the production vault's share issuance, redemption settlement, and keeper payment.

### Receiver budget

The exact integrated adapter was measured again because inheritance and compilation can change receiver gas.

| Path | Receiver logic | Including conservative logging allowance | FWA stipend |
| --- | ---: | ---: | ---: |
| Ordinary keep | 44,905 | 47,905 | 100,000 |
| Kick after a false settled bid candidate | 67,992 | 70,992 | 100,000 |

The keep sweep tested 40 gas limits: 22 atomic failures and 18 recorded successes. The kick sweep tested 59 limits: 40 atomic failures and 19 recorded successes. Every successful payment at the tested limits was recorded. This is sampled execution evidence, not an exhaustive proof for every possible gas amount.

The compiled research adapter runtime is 14,068 bytes. This does not establish the eventual production vault's size, because share and keeper logic have not yet been combined with it.

Exact outputs are in `incremental-fork-results.txt`, `incremental-cursor-results.txt`, and `incremental-adversarial-results.txt` under `docs/receipts/`.

## Limits of this milestone

The pure kernel covers owed pack claims and recovery. A failed delivery of the fixed shape pack contract was not manufactured on the real fork. The repository prohibits external mocks, and the real fixed transfer path did not fail in the tested gas sweeps.

The prototype values its actual cash balance because it has no depositor escrow or holder liabilities. Production integration must pass `_free()` after its protected balances are excluded. It must also preserve the existing share pricing, partial redemption, claim, and wind down rules.

This milestone establishes the accounting mechanism and its scaling behavior. It does not change the production ceiling, establish a production gas quote, complete a security audit, or justify mainnet deployment.

## Next integration milestone

Integrate this accounting into the existing single vault, retaining the current holder flow rules:

1. Connect minting, inventory, listing, selection, settlement, withdrawal, harvest, and redemption to the running totals.
2. Use actual free eth after protected liabilities, and read or harvest FWA fee credit consistently so it cannot be counted twice.
3. Carry the receiver storage and identifier lifecycle invariants into the exact production receiver, then measure that bytecode again.
4. Replace the open position and idle inventory scans on all required paths, including redemption liquidity estimates.
5. Remove the position count ceiling and its dependent checks and per position checkpoint charge.
6. Add bounded journal and receipt processing to the keeper. Keep its payment fixed by verified work and existing policy caps.
7. Update the production simulator and reconcile deposits, partial redemptions, claims, fee costs, and wind down against real fork executions.
8. Verify runtime bytecode size and each complete production operation's gas.

The other project changes remain paused. Paid shapes mint fees remain part of the system's actual costs and the creator's revenue.
