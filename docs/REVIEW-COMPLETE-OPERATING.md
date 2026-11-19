> **Current release instructions: [docs/release/RUNBOOK.md](release/RUNBOOK.md)** (2026-11-19). This document is history for the candidate it names; where it gives current instructions, the runbook replaces them.

# Final operating and complete exit results

The implementation removes recurring paid standalone harvests and funds useful fee collection through verified bounded sync work. Actual keeper preflight selects the shortest useful funding prefix. Creator mint fees and the primary mint recipe remain intact. The canary now permits 0.01 eth of routine spending per day with a 0.03 eth bucket; mainnet permits 0.02 eth per day with a 0.1 eth bucket. These permissions provide no additional cash.

## Applied refill settings

The following cases use the applied settings, seed 8, a fixed authenticated current foreign pool, 439.7 successful acquisition requests per day as a scenario input, and continued market activity during exit. Holder net is actual modeled claimed cash after entry charges and holder gas proxies. All four cases finish with no open positions, no inventory, no journal backlog and no unpaid routine calls.

| Principal eth | Operating days | Total gas price gwei | Routine expense eth | Permission at operating end eth | Holder net eth | Creator mint fees eth | Exit days |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 6.8000 | 30 | 0.5 | 0.466152000 | 0.099274500 | +1.176211779 | 0.025 | 0.300556 |
| 6.8000 | 90 | 0.5 | 1.339093500 | 0.100000000 | +1.827994346 | 0.025 | 0.300972 |
| 1.9601 | 30 | 0.2 | 0.120817600 | 0.029187278 | +0.657555180 | 0.008 | 0.300694 |
| 1.9601 | 30 | 0.5 | 0.283337500 | 0.028831667 | +0.572791726 | 0.007 | 0.300694 |

The 90 day mainnet case spends about 0.014879 eth per operating day. Its available permission is approximately 0.09928 eth at day 30 and the full 0.1 eth at days 60 and 90. The initial bucket does not mask a declining refill balance. The canary at 0.5 gwei makes one active fee claim to fund useful work; its minimum free cash is 0.000450462 eth. Protected balances remain excluded.

For comparison, the previous mainnet refill of 0.005 eth per day delays the high volume exit by 10.300694 days. The previous canary refill of 0.0008 eth per day leaves the 0.5 gwei case blocked after 30 exit days with 31,569 journal entries and 13 positions. Both failures are spending permission shortages while actual cash remains available. The older 0.3 eth initial bucket with 0.01 eth daily refill passes the mainnet 30 day scenario by consuming its initial balance; the applied refill avoids that dependence.

## Harvest regression

The short matched comparison retains the earlier conditional recorded pool and exemption assumption, two operating days plus at most two exit days, 609 successful acquisitions per day and 0.2 gwei. Packs were not actually exempt at that recorded block. Current primary scenarios use the independently authenticated current exemption. The candidate also corrects the earlier unrestricted policy candidate projection.

| Version | Standalone harvest calls | Harvest expense eth | All routine expense eth | Holder net eth | Creator mint fees eth | Fully funded routine |
|---|---:|---:|---:|---:|---:|---|
| baseline | 990 | 0.266081233 | 0.319476433 | -0.155298663 | 0.027 | no |
| candidate | 0 | 0.000000000 | 0.048699000 | +0.073280518 | 0.026 | yes |

The candidate performs one fewer paid mint in this conditional path. An unchanged fee rate does not guarantee unchanged mint volume; fee release timing and calibrated operating costs affect available capital.

## Purchaser timing

Five current pool scenarios use the applied mainnet settings, 6.8 eth principal, two operating days plus at most two exit days, and 0.2 gwei. Every scenario completes, funds routine work and clears all positions and inventory. Late responses arrive after the expiry reclaim has already completed in this sample.

| Purchaser regime | Holder net eth | Creator mint fees eth | Exit days |
|---|---:|---:|---:|
| timely | +0.124227364 | 0.026 | 0.300972 |
| late | +0.656164352 | 0.036 | 0.801250 |
| silent | +0.656164352 | 0.036 | 0.801250 |
| zero | -0.071095893 | 0.026 | 0.300694 |
| keep | +0.616908743 | 0.034 | 0.301250 |

## Limits and validation

The 0.15 eth scenarios complete and fund maintenance but lose money: approximately 0.02760 to 0.02886 eth at 0.2 gwei, and 0.04516 to 0.04518 eth at 0.5 gwei. Even zero gas loses approximately 0.01811 to 0.02020 eth. An early selection leaves insufficient cash to relist. The losses persist at zero gas and are much larger than the single 0.001 eth creator mint fee. No minimum deposit size or recurring subsidy was introduced.

These are conditional accounting and operating results from one seed, not expected returns or annual acceptance. The foreign pool is held fixed; acquisitions and purchaser behavior are generated scenario inputs. Historical holder receipt gas and operation gas proxies remain explicit. The model assumes atomic inclusion at each fresh read and does not charge failed transactions or model market responses to the vault. Separate fork and signed preflight evidence establish contract behavior and payment coverage.

The 18 previous default scenarios are loaded explicitly from commit e9cee61 for reproducibility: 17 complete and 14 have uninterrupted routine funding. All seven permission comparisons complete with funded routine work. Every case has an exact zero gap in its modeled asset ledger. No forecast fee credit, additional sponsor cash, unpaid operator work or creator fee recycling funds the results.

Python validation passes 20 accounting, funding and candidate projection tests plus keeper/test_policy.py. The projection test compares the simulator directly with real EventIndex SQL queries across 700 positions, including terminal bounds and persistent owed rotation. Funding regressions cover two required active claims, rejection of shorter insufficient prefixes, protected balances and full terminal batches needing funding slots.

[Operating results](receipts/complete-operating-candidate.json), [timing results](receipts/complete-timing-regressions.json), and [authenticated context](receipts/complete-operating-context.json) contain exact amounts, commands, source hashes, parameters and limitations. Reproduce with `python3 sim/efficient_operating.py --complete-pass --label candidate --seeds 8` and `python3 sim/complete_timing.py`. The local case cache is optional and is not a deliverable.
