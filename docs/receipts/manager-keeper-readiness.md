# Manager keeper operational readiness

Scope: current-source, factory-only keeper operation against a local mainnet fork. The shared
vault is undeployed. This record grants no public transaction, production signer use, Fly launch,
live application change, merge or deployment approval.

**PASS: 11 actual local receipts in 117.829 seconds**, exit status 0. Command:
`CANDIDATE_RUN=1 /Users/dd/.pyenv/versions/3.11.8/bin/python keeper/rehearse_manager_operations.py --execute --port 18741`.
Fork block 26,489,769, hash
`0xa319c41fe38ed0cc0e0adc23e2c14738b7c13973c7d9bc0c9350c40bd6fb978d`;
final local block 26,489,821. Contract hashes match the corrected R2 implementation; the receipt
binds every runtime keeper input and the executed harness/helper. No runtime source changed.

The executable proof is `keeper/rehearse_manager_operations.py`. Its assertions cover an empty
factory start, discovery of a newly created manager, a paid build, durable restart without a
duplicate transaction, and the owner's bounded exit after setting both keeper budgets to zero.
It checks three real paid 0.01 ETH Shape mints, actual receipt gas, creator accrual, account cash
and every external actor's wallet. The owner supplies 0.5 ETH once; wallet gas is separate.
The execution result, exact frozen inputs, transaction fee fields, receipt gas and block basefee
are preserved in [manager-keeper-readiness.json](manager-keeper-readiness.json).

| Same-receipt outcome | ETH |
| --- | ---: |
| Owner's single account funding | 0.5 |
| Owner withdrawal | 0.49836482704375 |
| Owner wallet gas, including creation/configuration/exit | 0.000144517236111875 |
| Owner net after all wallet gas | **-0.001779690192361875** |
| Creator gross primary mint-fee accrual | 0.0015 |
| Keeper compensation | 0.00013517295625 |
| Keeper billed gas | 0.0000959724090825 |
| Keeper net | 0.0000392005471675 |

The manager's 0.00163517295625 ETH principal shortfall equals creator mint fees plus keeper pay.
Account and all four external-actor wallet gaps are zero. No extra manager funding occurred.
Cash, packs, open listings, pending receipts and fee credit all end at zero. The initial foreign
request queue was already empty, so no calibration actor paid for hidden queue work. Creation,
configuration and closeout wallet costs all enter owner net; deployer gas is separate startup
cost, 0.002648751303475634 ETH. These unselected round trips are costs, not monthly returns.

The keeper build used 1,890,750 gas at an actual effective price of 0.050758910 gwei, with
0.000758910 gwei block basefee. Local block mining lowered basefee from the node's 0.15 gwei
initial setting; the table uses actual receipts rather than that starting label. The earlier R2
one-pack build used 1,924,916 gas at its recorded block and price. Neither sample establishes
all work-size gas curves or future inclusion margins.

The combined configuration and closeout signed maximum was 0.000077429852259078 ETH under the
0.01 ETH cap, excluding creation. Both keeper budgets were zero during closeout; exit keeper
compensation was zero. After restart the persisted counted transaction was unchanged, no nonce
was duplicated, and `/health` reported one non-pooled manager and no pass errors. The bounded
seven-day event index caught up before the build. The informational `RESERVE_BELOW_NEED` status
reported 0.005 ETH reserve against a 0.0054 ETH maximum-batch quote; that configuration limit was
not changed and did not prevent this bounded owner exit.

The task-owned node was alive at rehearsal completion at `http://127.0.0.1:18741`, PID 11675;
`ownedNodeRetained: true` records that completion-time observation. A later scoped check found
that PID absent and its loopback port closed. The execution runtime automatically closed the
non-detached child after the helper completed; no manual stop was performed. The task-owned
keeper processes were stopped by the helper. No other node, process, cache or service was reset
or stopped. The retained work directory and actual receipts remain in the JSON.

The executed harness is the version in commit `797dc15222b194076d822a950f0a2ec957b99edf`, bound by
the receipt's `scriptSha256`. A post-run lifecycle fix adds `start_new_session=True` when starting
future owned Anvil nodes. Only Python compilation was checked for that fix; the successful
rehearsal was not repeated and does not claim to execute the revised harness.

## Production preparation

`deploy/manager-keeper-unsigned.json` is address and environment data. Its predicted factory must
be replaced or independently confirmed from the separately authorized actual deployment and
`script/release.py postflight-manager` readback before any production keeper starts. The mainnet
factory has not been deployed. There is no live manager service to start now.

For that later step, use `FACTORY` and `RPC_URL=https://mainnet.gateway.tenderly.co`, with no
`VAULT`. Existing encrypted signer files are mounted read-only and referenced by
`KEEPER_KEYSTORE_PATH` and `KEEPER_PASSWORD_FILE`. Preserve `/data`, including keeper transaction
state, discovery JSON and per-account SQLite indexes, across restarts. `POLL_SECONDS` selects the
poll interval; the production entrypoint uses two confirmations and serves `/health` on
`HEALTH_PORT` (default 8788). Check its factory-discovered accounts and per-account status,
pending transaction, errors and last-pass freshness. Healthy polling alone does not establish
profitable or fundable work. Do not use local `KEEPER_FROM` actors in production.

An owner exits an explicit manager through the documented `--caller-funded-exit` path with an
existing owner signer, dedicated durable state and an explicit additional wallet-spending cap.
Discovery does not silently extend that exit to other managers. Preserve pending and replacement
reservations between invocations. Real randomness, request deadlines and listing windows can
require waiting; no topup or accepted keeper loss is assumed.

## Evidence limits

The previous `manager-image.json` remains compatibility evidence for its original image revision.
Current `keeper/policy.py` includes the later protected-cash correction; the other runtime image
inputs are unchanged. Docker is unavailable on this host. This focused run uses the actual current
production shell entrypoint and Python keeper, and does not claim to rebuild or run a current
container. Production encrypted-keystore and hardware signing, Fly networking/mounts, mainnet
inclusion, authenticated-VRF renewal and broader gas curves remain separate limits.

Things that don't make sense: treating an undeployed factory's predicted address as a live
service; equating healthy polling with profitable work; or reporting old container execution as
proof that the corrected policy ran inside that image. The configured reserve is also below its
maximum-batch quote; this successful one-pack closeout does not erase that visible limit.
