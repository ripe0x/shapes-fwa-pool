# Manager operating calibration

**69 successful local Osaka transactions complete this bounded operating-cost pass. No production recommendation or full-period return follows.** Runtime contracts remain unchanged. The shared vault, public app gates and public transaction authority are unchanged.

The new exporter executes the real historical request and authenticated Chainlink proof through the existing `MainRenewalBase` fixture. Its recorded state diff contains 1,510 distinct written slots, including 114 zero values. The initial bridge checks each recorded write against the exported allocation, imports over the identical pre-request transaction prefix, and verifies accounts, slots and critical views before operating transactions. The final Osaka node restores the exact derived native checkpoints: allocated state has 458 accounts and 4,452 verified fields; returned state has 460 accounts and 4,965 verified fields. It restores its untouched base snapshot before importing returned state, preventing Anvil's maximum-nonce merge from retaining a later sender nonce. Transport chunks only unchanged native account rows; native block metadata is gzip encoded to fit the HTTP limit.

The final operation evidence is [manager-operating-osaka-receipts.json](manager-operating-osaka-receipts.json). The [calibration packet](manager-operating-cost-calibration.json) combines those receipts with immutable R2 evidence for the other operation names. Both inputs remain bound by SHA-256. Its twelve operation groups distinguish actual billed gas, actual RPC estimates, and R2 signed gas limits retained as conservative upper bounds. Actual RPC estimates supply estimate curves when available; signed limits are not presented as old successful estimates. Each curve uses the maximum measured single-work value and a conservative observed slope for additional work, with billed and estimate curves derived separately.

Measured scope:

| Work | Measured cases |
| --- | --- |
| Selected/terminal sync | Separate and combined transitions, one position, at .2/.15 and .5/.45 gwei price/basefee |
| Fresh renewal | One genuinely selected returned pack, .001/.0005/.00025 ETH mint fees at both gas contexts |
| Reuse listing | One pack at all fee/gas contexts; owner unlist/relist round trips at 1, 3 and 8 packs |
| Opening build | Genuine fresh clones funded with .5 ETH, one pack at .0005/.001 fees and both gas contexts; four-pack batches also measured |
| Standalone harvest | Actual nonzero 25,122,058,121,371 wei fee credit, caller funded |
| Other named operations | Existing immutable R2 receipts; actual event counts or fixed operation counts retained |

The .00025 ETH fee is an agent-selected fork sensitivity. Fee changes use the genuine delegated-EOA admin with its EIP-7702 code intact on Osaka. No public fee change occurred. The floor oracle's owner is a contract; it was not impersonated. Consequently sync batches above one remain unmeasured. Fresh renewal above one and listing above eight also remain explicit gaps. R2 owner recovery is a fixed scan with one or three inspected IDs, not a claim of one or three completed settlements.

The fresh-build single-work envelope is 1,924,916 billed gas and 2,107,326 actual estimate gas. Combined single-position sync used 522,121/522,131 billed gas at .2/.5 gwei. Separate allocated and terminal sync samples lose keeper money at their fixed quotes; combined sync's positive billed margin still does not prove that the production estimate-based preflight accepts it. Calibration deliberately executes such quoted work to measure cost. These are independent restored branches, not one economic lifecycle.

The final focused continuation command was:

```sh
CANDIDATE_RUN=1 /Users/dd/.pyenv/versions/3.11.8/bin/python \
  keeper/calibrate_manager_operations.py --execute --finish-matrix --port 18783
```

It exited 0 with `PASS`, 69 receipts. The authenticated exporter previously passed its one focused fork test. No broad suite, new proof campaign or production broadcast was run. Final packet formatting and immutable-input qualification were separate offline checks. Executed source revisions are pinned in `executedSources`; later changes only corrected metadata and packet representation. All setup/import/caller failures, the interrupted runner and thirteen excluded Cancun receipts remain archived beside these files. They establish neither accepted returns nor final Osaka gas measurements.

Frozen SHA-256 values:

- Calibrator: `9749cd2d15aa9ade8423dc08395aab6b37736e60b92a420af67903c201a805b5`
- Exporter: `b53090e0da0bc1f6f394504fd4e867663a46d18597847a72639345eab2806d7c`
- Osaka receipt packet: `eb1ff1c81cfe085e46515bbaf0c9d474284cd092271654efb4652fc5b63b5beb`
- Cost calibration: `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`

Owned nodes were preserved: Osaka PID 63188 on 18783, and historical Cancun nodes 53557/18782 and 38987/18781. The latter's already-dispatched mining was not reset or killed. No other process or cache was modified.

Things that don't make sense: positive creator revenue is not owner profit; positive billed keeper margin can still fail a conservative estimate-based preflight; named-operation coverage does not measure every batch size or establish production viability.
