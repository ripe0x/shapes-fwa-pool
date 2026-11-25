# Manager backing comparison

**Corrected execution and final numerical review are pending.** The earlier two-draw −28.5% result
is withdrawn. The simulator could commit routine work without paying its full compensation after
depleting the renewal float. Its two partial campaigns, 20,020 and 14,288 rows, are invalid economic
evidence and remain archived with their original source identity and content hashes. No replacement
return estimate has been accepted.
The shared vault stays closed. No production settings, public transactions or live services change.

## Frozen study

- 8,192 independent path IDs, split equally between two adjacent recorded 30-day windows.
- Each ID compares 0.21, 0.15 and 0.03 ETH backing at 0.2 and 0.5 gwei: 49,152 scenario runs.
- Every case uses 0.5 ETH owner funding, 0.03 ETH packs containing three paid 0.01 ETH Shapes,
  FreshAfterAcquisition, one renewal float, and a 0.005 ETH operating reserve.
- Actual mint fee observation: 0.0005 ETH per Shape at block 26,488,707. Accepted maximum: 0.001 ETH.
- The original adverse response assumption is retained: every archived eventual responder bids
  by 3,480 seconds. Archive-unresolved cases remain explicit. Unequal follow-up, right censoring,
  fixed foreign weights and the repeated historical exit tail limit interpretation.
- Mean intervals describe conditional Monte Carlo uncertainty. They do not measure future-market
  uncertainty or establish APR. Missing or incomplete exits suppress final population inference.

The current manager refuses 0.03 ETH backing through its own face-coverage and profitability
checks. The separate 1:1 reference relaxes only admission in isolated analysis workers; actual
payments, cash constraints, budgets, reserves, fresh mints and owner-paid exit accounting remain
unchanged. It is not an executable configuration of the deployed candidate. At equal funding it
can start about seven packs, versus one at the larger backings. Forced bids are not the worst
purchaser outcome at 1:1: a keep also costs the owner its settlement fee.

The invalid parent [manifest](../../sim/out/manager-monte-carlo-adverse/manifest.json) has canonical hash
`13b63560ec6ddf116c68077e09be57212971265634747fbaafa1f9e2775e1f5a`.
The invalid standard-backing [manifest](../../sim/out/manager-standard-backing/manifest.json) has hash
`d8d3e7db087bdf381bd65f6cee88a2e9c88d34e11ec4411b9105d8f491d11d78`.
Their saved partial rows are preserved; neither campaign completed its planned sample. The corrected
study uses new `manager-monte-carlo-funded` and `manager-standard-funded` output directories.
It requires zero unpaid ordinary keeper calls and independently checks owner, keeper and creator
cash partitions. Explicit owner recovery pays wallet gas. Ordinary modeled work requires its full
quoted compensation, a conservative controller assumption: the real bot may accept a smaller
payment if it still covers its actual transaction gas and required margin.

## Actual protocol check

Ten signed transactions on the owned Tenderly mainnet fork verify MAIN ShapePacks, not the
community collection. Each case directly mints three Shapes, creates a 0.03 ETH pack, lists it
with 0.03 ETH backing, withdraws it unselected and redeems its face. Both recover the full
0.06 ETH principal. These transactions establish admission and an unselected round trip only.

| Total gas price | Billed wallet gas | Paid primary fees | Owner net |
| --- | ---: | ---: | ---: |
| 0.2 gwei | 0.000358795 ETH | 0.0015 ETH | −0.001858795 ETH |
| 0.5 gwei | 0.0008969815 ETH | 0.0015 ETH | −0.0023969815 ETH |

Each receipt asserts its executed base fee and effective gas price. Both ledgers close to zero
wei. [Receipts](manager-standard-backing-fork.json) bind exact verified dependency runtimes.
Creator values are gross fee accrual, not withdrawals or net profit. These manual gas bills do
not replace the manager gas proxies in the operating study.

## Verification and execution

The correction has three real-counterparty fork regressions and a new
[43-step reconciliation](manager-funded-reconciliation.json). It proves the actual 0.5 ETH
post-renewal float deficit, an insufficient single fee claim followed by the first sufficient
two-claim prefix, and an atomic refusal when real fees cannot cover an enlarged reserve.
The fee-prefix and reserve regressions needed valid historical selection fixtures; original failures are
preserved. Pure funding, forward/randomness and affected existing manager/renewal/sync checks pass.
The original 32 nominal Fresh/Reuse steps remain separate compatibility evidence. Neither they
nor cached/uncached equality established the missing cash-hold invariant.

Fresh receipt calibration is being completed against the changed contracts. Authenticated renewal,
standalone harvest and variable paid sync/list gas remain explicitly unmeasured. The funding-prefix
regression uses cheap owner calibration to isolate cash protection; it proves no keeper profit.

The study requires the frozen real archive at `sim/data/fwa.sqlite` and the existing Python
dependencies. The archive is not substituted with mock responses. Commands from the repository:

```sh
python3 sim/test_manager.py
python3 sim/test_forward_randomness.py
python3 sim/test_forward.py
python3 sim/test_manager_monte_carlo.py
python3 sim/test_manager_standard_backing.py
python3 sim/manager_reconcile.py --funded
CANDIDATE_RUN=1 python3 sim/manager_monte_carlo.py --execute --workers 8
CANDIDATE_RUN=1 python3 sim/manager_standard_backing.py --execute --workers 8
```

The invalid standard-reference execution was resized from four to eight lower-priority workers
without changing inputs or path IDs; all durable rows were retained. A different one-hour-response
design was rejected before inspecting returns, preserving its 676 partial rows and source packet.
The [independent review](manager-monte-carlo-independent-review.md) checks the correction and its
43-step reconciliation; financial execution remains open until the corrected study completes.

Things that don't make sense: treating two outcomes as an expected return; presenting 1:1 guard
refusal as its economics; combining creator accrual with manager return; or treating narrower
conditional intervals as proof of future profitability. Billed renewal/harvest/variable-operation
gas and live keeper availability remain separate limitations.
