# Read-only recovery review

No helper was imported or executed, no node RPC was issued by this review, and no process or production source was changed. The approved root runner remains the sole executor. The companion Python file contains definitions only and exits without actions if run directly.

## Minimum no-gain observation repair

`ordinary_dispatch(absent=True)` currently rejects a printed sync candidate. That is the wrong stage: the no-send CLI prints `policy.plan` candidates before execution profitability is checked. Configured distributions intentionally propose a short-tail candidate; the actual onchain offer can be zero and the default executor must decline it.

The companion `/private/tmp/efficient-journal-recovery-review.py` supplies an opt-in wrapper. On the no-gain branch only it:

1. Uses the existing normal dispatch check, preserving the real CLI output and exact calldata match.
2. Uses the real keeper sender, pending fee context and `TxManager.preflight`.
3. Reads the actual pending offer, requires zero, and calls the unchanged shared `profitability_gate` with zero failure allowance, zero minimum return and zero permitted loss.
4. Requires a positive estimated cost and a declined result, then records candidate/preflight/offer/gate facts with `broadcast=False`.
5. Checks all six actor nonces, latest head and cumulative counters stayed unchanged. No CLI `--send`, no substitute successful RPC answers and no production edit are involved.

This replaces a false absence assertion with the actual intended planned-but-declined behavior. It adds no broadcast. Existing positive-gain/holder measurements and all source/approval guards remain intact.

## Snapshot derivation

These are **derived expected IDs**, not a claim that this review queried their liveness. They bind resume2's recorded probe `0x6`, exact source order and no intervening extra snapshots before capture.

- Resume2 probe:6. Its restarted stock section consumes eleven snapshot allocations,7 through17: one fresh, three groups of one origin plus two price restores, and one final fresh restore.
- Portfolio base before foreign requests:18, `0x12`.
- Natural prefix snapshots:

| Records | ID | Records | ID | Records | ID |
| ---: | --- | ---: | --- | ---: | --- |
| 1 | `0x13` | 16 | `0x18` | 63 | `0x1d` |
| 2 | `0x14` | 17 | `0x19` | 64 | `0x1e` |
| 3 | `0x15` | 31 | `0x1a` | 65 | `0x1f` |
| 7 | `0x16` | 32 | `0x1b` | 127 | `0x20` |
| 15 | `0x17` | 33 | `0x1c` | 128 | `0x21` |

Each ordinary descending holder case allocates twelve snapshots. Six complete upper cases,128/127/65/64/63/33, allocate34 through105. Count32 then restores its prefix into106 (`0x6a`), enters distribution preparation107 (`0x6b`), and restores the first no-gain price origin108 (`0x6c`). The anticipated failure is after fee/time preparation but before any no-gain transaction, gain transfer or holder32 request. Thus `0x6c` is the expected remaining reusable no-flow prefix32 origin; the original `0x1b` has already been consumed.

If that exact stop occurs, lower prefix snapshots1/2/3/7/15/16/17/31, portfolio base `0x12` and entry `0x0` remain the intended ancestors. A root-controlled resume can start distribution32 from its fresh origin, then perform holder32 and the untouched lower prefix cases, followed by the original full-holder tail. Do not restart stock/portfolio/request generation or rerun already billed upper matrix branches. Restore operations allocate fresh IDs, so later newly created IDs must be carried from their actual return values rather than predicted from this original sequence.

The optional snapshot logger in the companion helper records each future returned ID and cumulative counters without making an additional snapshot RPC. It can prevent the next recovery from needing this derivation again; it was not installed by this review.

Before any restoration root must check the exact failure, original probe6, completed upper-case labels, genuine no-flow/current32-prefix getters, and the untouched frozen source/artifact/endpoint guards. Any additional snapshot before the recorded sequence invalidates these numeric deductions.

## Counters and recovery boundary

At the anticipated first no-gain32 stop, the source predicts229 broadcasts and226 action rows:21 initial/stock/portfolio broadcasts,128 real acquisition requests,38 process/refund calls, and42 upper matrix broadcasts. This is a consistency expectation, not authority to reset observed counters to it.

After snapshot restores, archived billed branches no longer belong to the current canonical chain. **Do not copy resume2's early `canonical tx count == cumulative broadcasts` or `sum(actor nonces) == cumulative broadcasts` checks into this recovery.** Those checks were valid before branch rollback. Preserve every archived action/reservation and the existing global ledger, including reverted branches; use current nonces only for the resumed branch. Never reset counters, fund again, deduplicate repeated nonce/hash histories, or repeat billed branches to reconstruct missing in-memory locals.

The entry snapshot remains `0x0`, as confirmed by root. Final restoration still requires the original six balances/nonces/code, exact entry head, automine and empty-pool readbacks. The540-transaction/32-ETH aggregate bounds and8.3-ETH initial funding remain unchanged, with no public-chain authority.

## Things that don't make sense

- A printed candidate is not an accepted transaction; zero-offer decline is the desired no-gain result.
- Canonical-chain nonces cannot reconstruct cumulative spending after deliberate branch rollback.
- Snapshot IDs should have been persisted at creation. These source-order deductions are a narrowly checked recovery aid, not a replacement for actual branch-state verification.
