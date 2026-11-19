# shapes-fwa-pool

PackVault: pooled depositor vault listing Shape packs on the FWA V2 main pool. Owner
requirements: `OWNER-REQUIREMENTS.md`. Decisions: `docs/DECISIONS.md`. Status: `docs/REPORT.md`.
Keeper operations: `docs/KEEPER.md`. Gas: `docs/GAS.md`. Assets: `docs/SYSTEM-MAP.md`, `asset-flow.json`.

## Commands

```sh
# Fork tests: mainnet fork on Tenderly's public gateway only. It throttles, so pass the retries.
forge test --match-path test/fork/<File>.t.sol --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100
CANDIDATE_RUN=1 forge build --sizes  # PackVault 24,136 bytes, 440 under EIP-170; VaultLib 24,304

python3 sim/snapshot.py        # Phase 0.1 live reads at one block
python3 sim/ingest.py          # FWA, rewards and oracle logs into sim/data/fwa.sqlite (resumable)
python3 sim/replay.py          # exact fee accumulator replay; must report 0 mismatches
python3 sim/analyze.py         # sim/out/phase0.2.md
python3 sim/model.py           # sim/out/phase0.3.md (gas from sim/out/gas.json)
python3 sim/find_selection.py  # real requests whose VRF word selects vault listings
python3 sim/reconcile.py       # after both ForkReconcile and ForkPartialReconcile: every bucket to the wei
python3 sim/forward.py 200     # sim/out/forward.md: expectation, backtest, forward simulation
python3 keeper/rehearsal_batch.py --plan  # prepare bounded local batch; execution requires its explicit approval
python3 keeper/test_policy.py      # gas classes, reserve need, status codes (no chain)
python3 keeper/test_index.py       # pure codec, durable projection and concurrent writer checks
# keeper/test_tx.py runs through the real vault inside the approved local rehearsal, not fake counterparties.
forge test --match-path test/scenario/VaultFlow.t.sol --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100   # 16 asset-flow regimes
python3 ~/.agents/guidance/asset-flow-kit/asset_gate.py .   # PASS needs the owner's signature on asset-flow.json
```

## Rules specific to this repo

- No mocks of FWA, its VRF, oracle, Shapes, ShapePacks or the token pool. Selections come only
  from replaying real request and fulfillment calls (`ForkSelection.t.sol`, fixtures from
  `sim/selection_fixture.py`). `vm.transact` re-forks and drops local state: do not use it.
- Test actors use `makeAddr("pack-vault-test-...")` and setUp asserts they hold no code or ETH:
  short labels map to real mainnet addresses, some with EIP-7702 sweepers. Deploy addresses can
  hold mainnet dust; read balances, do not assume them.
- Keeper pay is a fixed quote per operation (D56); never measured gas. The keeper pads the exact
  signed-call estimate 25% and enforces the transaction cap; later state can still invalidate an
  estimate. `cast send` exits 0 on a reverted transaction; check receipt status.
- The keeper payment policy is a separate contract (`src/KeeperPolicy.sol`, D57), set by the admin at once (D58); the vault caps
  its offer. Test policies live in `test/fork/ForkKeeperPolicy.t.sol`.
- Rehearsal actors are fresh addresses checked clean on the fork. Never anvil's dev accounts: they
  are real mainnet addresses and #2 carries an EIP-7702 delegation that diverts ETH it receives.
- Keeper decisions live in `keeper/policy.py` only; the simulation imports it. Vault accounting in
  `sim/vault.py` must stay a line-for-line mirror of PackVault; rerun the reconciler after any
  accounting change. Every vault call must fit EIP-7825's 16,777,216 gas per transaction.
- After changing the `Params` struct, `forge build --force`: a stale cached build deployed the
  old struct layout once and reverted with `OutOfBounds`.
