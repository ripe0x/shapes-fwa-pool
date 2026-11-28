# Local manager quote candidate rehearsal

The focused batch passed with **43 successful local Osaka transactions and 14 production keeper CLI runs**. This is an unapproved local candidate, not production acceptance or evidence of profitable manager ownership.

Only three quote settings changed from the immutable baseline: `selected` 180,000 → 225,000, `synced` 120,000 → 285,000, and `list` 280,000 → 380,000. Pack value remains 0.03 ETH, mask 8, backing 0.21 ETH, and accepted mint fee 0.001 ETH. The fork mint fee was set through its actual EOA admin to the observed current 0.0005 ETH. No public transaction occurred.

Command, exit status, result:

```text
CANDIDATE_RUN=1 /Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_calibration.py --execute --port 18784
exit 0
{"status":"PASS","transactions":43,"cliRuns":14}
```

The new owned node uses Osaka execution, mainnet parent 26,385,000 and Tenderly's public mainnet RPC. The unchanged authenticated allocated and returned native checkpoints were independently compared after import: 4,452 and 4,965 balance, nonce, code and storage fields respectively. The node remains available on local port 18784; prior nodes and checkpoints were preserved.

Every ordinary branch began with an empty counted transaction history. Actual parent blocks were primed so deterministic EIP-1559 inclusion base fees were exactly 0.15/0.45 gwei; included receipts assert effective prices 0.2/0.5 gwei and those base fees. Quote formulas were checked against the candidate settings. The production keeper performed its estimate, profitability gate, 80% signed `minPay`, signed-call reestimate, capped submission and receipt confirmation. The four resolved/combined sync, four renew/reuse list and two fresh build calls used the unmodified CLI. The two allocated-only sync calls used the production executor explicitly because the planner deliberately defers this state before settlement. Index bootstraps contain only actual contract getter results; no events were fabricated. Local unlocked EOA transport was used, not hardware or encrypted-key transport.

Amounts below are wei. Each row represents real work count one and actual billed gas, without excluding failed economics by assumption.

| Operation | Effective gas price | Quoted payment | Actual gas cost | Keeper net |
|---|---:|---:|---:|---:|
| Allocated sync | 0.2 gwei | 74,400,000,000,000 | 70,464,000,000,000 | 3,936,000,000,000 |
| Resolved sync | 0.2 gwei | 111,000,000,000,000 | 86,360,000,000,000 | 24,640,000,000,000 |
| Combined sync | 0.2 gwei | 160,400,000,000,000 | 104,489,400,000,000 | 55,910,600,000,000 |
| Fresh renew | 0.2 gwei | 487,000,000,000,000 | 368,308,400,000,000 | 118,691,600,000,000 |
| Reuse list | 0.2 gwei | 261,000,000,000,000 | 227,692,200,000,000 | 33,307,800,000,000 |
| Fresh build | 0.2 gwei | 415,000,000,000,000 | 378,153,400,000,000 | 36,846,600,000,000 |
| Allocated sync | 0.5 gwei | 186,000,000,000,000 | 176,166,000,000,000 | 9,834,000,000,000 |
| Resolved sync | 0.5 gwei | 247,500,000,000,000 | 215,900,000,000,000 | 31,600,000,000,000 |
| Combined sync | 0.5 gwei | 371,000,000,000,000 | 261,228,000,000,000 | 109,772,000,000,000 |
| Fresh renew | 0.5 gwei | 1,127,500,000,000,000 | 920,749,000,000,000 | 206,751,000,000,000 |
| Reuse list | 0.5 gwei | 622,500,000,000,000 | 569,236,500,000,000 | 53,263,500,000,000 |
| Fresh build | 0.5 gwei | 977,500,000,000,000 | 945,364,000,000,000 | 32,136,000,000,000 |

The owner-funded exit used the new configuration with routine and essential caps/rates set to zero through a real owner call. Four CLI steps exited, unlisted, liquidated and withdrew. Terminal cash, FWA credit, open listings, idle packs, recovery packs and pending receipts were all zero. Exit calls actually cost 179,592,200,000,000 wei; their signed maximum was 483,070,350,000,000 wei. Including the budget-zeroing owner transaction, the signed maximum was 533,754,550,000,000 wei (0.00053375455 ETH), below the 0.01 ETH limit. This amount is gas, not an additional keeper payment.

`manager-calibrated-cost-calibration.json` adds the candidate samples to the original billed envelope. Billed curves include all samples; estimate curves prefer actual RPC estimates and retain old signed upper bounds as provenance. Existing larger-batch limitations remain, including renew >1 and sync >1. The prior 69 receipts, original helper and original profile were not overwritten.

Frozen SHA-256 bindings:

- Helper: `e66ab79a094e08b78eff44b6dfbccdbaca0f43fe4dc375461b567bdc3ca28e79`.
- New raw packet: `2b8e6771aa2259c7a6782b109fa19a8ea15c325aba44be91c0366e18bc845099`.
- New combined profile: `3a1aa82707e1ef9e6116ad32b7bcdfb5ac6ae44c801a3b383cb3c169a3229137`.
- Exact executed helper source archive: `8eed7a5a26106678cf4e0d9dfc626e51a72a75eff2683f866ca472427fe7c359`; source text hash `cafe94a56831c66e65cf9988407716d25f16073c0a75069932fe2c44d92e3319`. Subsequent helper changes only strengthen source bindings and identify newly created accounts in metadata; no executed transaction behavior changed.
- Baseline helper: `9749cd2d15aa9ade8423dc08395aab6b37736e60b92a420af67903c201a805b5`; baseline profile: `e954c54974cf97f5d5aed9843df4137ef4be6df37bc05b6eb87a95981ea432af`; baseline raw: `eb1ff1c81cfe085e46515bbaf0c9d474284cd092271654efb4652fc5b63b5beb`.

Things that don't make sense:

- Higher fixed quotes solve these measured keeper shortfalls by increasing owner costs. They do not establish owner economic viability; the separate cohort assessment must include them.
- The unchanged 0.005 ETH reserve is below the candidate's conservative maximum-batch need of 0.0054805 ETH at 0.5 gwei. The real CLI reports `RESERVE_BELOW_NEED`; this is preserved, not relabelled as fully funded.
- Allocated-only sync acceptance is an explicit executor result, not a claim that the ordinary planner schedules that deferred job.
