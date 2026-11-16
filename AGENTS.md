# shapes-fwa-pool

PackVault: pooled depositor vault listing Shape packs on the FWA V2 main pool. Owner
requirements: `OWNER-REQUIREMENTS.md`. Decisions: `docs/DECISIONS.md`. Status: `docs/REPORT.md`.

## Commands

```sh
# Fork tests: mainnet fork on Tenderly's public gateway only. It throttles, so pass the retries.
forge test --match-path test/fork/<File>.t.sol --rpc-url https://mainnet.gateway.tenderly.co \
  --fork-retries 30 --fork-retry-backoff 5000 --compute-units-per-second 100
forge build --sizes            # PackVault runtime is within ~70 bytes of the 24,576 limit

python3 sim/snapshot.py        # Phase 0.1 live reads at one block
python3 sim/ingest.py          # FWA, rewards and oracle logs into sim/data/fwa.sqlite (resumable)
python3 sim/replay.py          # exact fee accumulator replay; must report 0 mismatches
python3 sim/analyze.py         # sim/out/phase0.2.md
python3 sim/model.py           # sim/out/phase0.3.md (gas from sim/out/gas.json)
python3 sim/find_selection.py  # real requests whose VRF word selects vault listings
```

## Rules specific to this repo

- No mocks of FWA, its VRF, oracle, Shapes, ShapePacks or the token pool. Selections come only
  from replaying real request and fulfillment calls (`ForkSelection.t.sol`, fixtures from
  `sim/selection_fixture.py`). `vm.transact` re-forks and drops local state: do not use it.
- Test actors use `makeAddr("pack-vault-test-...")` and setUp asserts they hold no code or ETH:
  short labels map to real mainnet addresses, some with EIP-7702 sweepers. Deploy addresses can
  hold mainnet dust; read balances, do not assume them.
- Keeper transactions pad gas 25%: keeper pay depends on `gasleft()`. `cast send` exits 0 on a
  reverted transaction; check receipt status.
