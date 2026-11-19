# Actual local refund journal calibration

Source: Q_CHECKPOINT 400,000 / Q_SYNC 85,000 / Q_JOURNAL 30,000.77 local broadcasts, no public transactions. Basefee 0.15 gwei, effective 0.2 gwei for each measured row. One real Active vault listing; 16 real expired/refunded FWA records.

| Entries | Prefix estimate | Prefix billed | Tail estimate | Tail billed | Fixed pay ETH |
|---:|---:|---:|---:|---:|---:|
| 1 | 117,495 | 112,515 | 117469 | 112489 | 0.000023000 |
| 2 | 134,101 | 129,121 | 131275 | 129095 | 0.000029000 |
| 3 | 150,708 | 145,728 | 150682 | 145702 | 0.000035000 |
| 4 | 167,315 | 162,335 | 167289 | 162309 | 0.000041000 |
| 5 | 183,923 | 178,943 | 183897 | 178917 | 0.000047000 |
| 6 | 200,531 | 195,551 | 200505 | 195525 | 0.000053000 |
| 7 | 217,139 | 212,159 | 217113 | 212133 | 0.000059000 |
| 8 | 233,748 | 228,768 | 233722 | 228742 | 0.000065000 |
| 9 | 250,358 | 245,378 | 247532 | 245352 | 0.000071000 |
| 10 | 266,968 | 261,988 | 264142 | 261962 | 0.000077000 |
| 11 | 283,579 | 278,599 | 280753 | 278573 | 0.000083000 |
| 12 | 300,190 | 295,210 | 300164 | 295184 | 0.000089000 |
| 13 | 316,801 | 311,821 | 316775 | 311795 | 0.000095000 |
| 14 | 333,413 | 328,433 | 333387 | 328407 | 0.000101000 |
| 15 | 350,025 | 345,045 | 347199 | 345019 | 0.000107000 |
| 16 | 366,612 | 361,632 | — | — | 0.000113000 |

Two-part splitting adds 95878–95902billed gas versus one 16-record call. Existing85,000base at 10% markup adds93,500gas-equivalent pay. Proposed105,000base would exceed the observed extra cost even with 0% markup; one final completion bonus cancels between split/batch. Do not adopt that base.

Exit six calls bill 1,919,103 gas, cost 0.0003838206 ETH; checkpoint pays 0.0001 ETH from request pool, leaving caller net gas 0.0002838206 ETH. Sync/unlist/liquidate pay zero under zero essential budget. Holder claims 0.798104438999250060 ETH; final vault cash 0.010073561000749940 ETH includes 1 wei protected rounding reserve.

See calibration-summary.json for exact complete ETH ledger, source/deployment hashes, all split comparisons and measured versus event-derived readback limits. Successful-foreign billed receipts remain a gap.
