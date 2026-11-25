# Manager economic closeout

**Bounded single-cycle sensitivity, not monthly return, APR or viability proof.**

Receipt fee .0005 ETH at block 26488707; confirmed again at block 26489769. Accepted maximum and historical comparison .001 ETH. Standard fresh-bid mint-fee break-even before all gas: **0.000384605000 ETH per Shape**.

.03 backing is hypothetical for the current manager. FWA admission and actual unselected round trips are separate evidence.

| Backing ETH | Mint fee ETH | Gas gwei | Bid net after quoted cycle costs ETH | Keep net after quoted cycle costs ETH |
|---:|---:|---:|---:|---:|
| 0.030000000000 | 0.000500000000 | 0.2 | -0.000983585000 | -0.001211585000 |
| 0.210000000000 | 0.000500000000 | 0.2 | 0.005939305000 | 0.183911305000 |
| 0.030000000000 | 0.000500000000 | 0.5 | -0.001819685000 | -0.001969685000 |
| 0.210000000000 | 0.000500000000 | 0.5 | 0.005103205000 | 0.183153205000 |
| 0.030000000000 | 0.001000000000 | 0.2 | -0.002483585000 | -0.002711585000 |
| 0.210000000000 | 0.001000000000 | 0.2 | 0.004439305000 | 0.182411305000 |
| 0.030000000000 | 0.001000000000 | 0.5 | -0.003319685000 | -0.003469685000 |
| 0.210000000000 | 0.001000000000 | 0.5 | 0.003603205000 | 0.181653205000 |

The screen attributes k times backing in gross listing-fee income per own selection, assuming fixed proportional selection and fee weights. Actual fees need not arrive with that selection. Keep gains at .21 backing assume a purchaser voluntarily keeps a .03 pack rather than taking the larger bid; that is not a buyer forecast. Costs include three primary mints and full construction/maintenance keeper quotes, plus retirement for bids. Clone creation and final owner exit are additional measured-gas sensitivities:

| Gas gwei | Operation | Wallet gas ETH |
|---:|---|---:|
| 0.2 | create | 0.000121238800 |
| 0.2 | setExiting | 0.000010647200 |
| 0.2 | withdraw | 0.000007785200 |
| 0.2 | unlist | 0.000107731400 |
| 0.2 | liquidate | 0.000051510800 |
| 0.2 | recover_sync | 0.000039810200 |
| 0.2 | processAcquisitions | 0.000023188200 |
| 0.5 | create | 0.000303097000 |
| 0.5 | setExiting | 0.000026618000 |
| 0.5 | withdraw | 0.000019463000 |
| 0.5 | unlist | 0.000269328500 |
| 0.5 | liquidate | 0.000128777000 |
| 0.5 | recover_sync | 0.000099525500 |
| 0.5 | processAcquisitions | 0.000057970500 |

Actual FWA standard unselected round trips:

| Gas gwei | Face + backing returned ETH | Primary fees ETH | Wallet gas ETH | Owner net ETH |
|---:|---:|---:|---:|---:|
| 0.2 | 0.060000000000 | 0.001500000000 | 0.000358795000 | -0.001858795000 |
| 0.5 | 0.060000000000 | 0.001500000000 | 0.000896981500 | -0.002396981500 |

Actual current-source manager unselected exits:

| Account | Funded ETH | Withdrawn ETH | Wallet gas ETH | Owner net ETH |
|---|---:|---:|---:|---:|
| single-owner | 0.500000000000 | 0.498232923820 | 0.000172995406 | -0.001940071586 |
| batch-owner | 1.000000000000 | 0.994971171002 | 0.000170118887 | -0.005198947886 |

Actual keeper compensation / gas / net: 0.000795905178 / 0.000604073134 / 0.000191832044 ETH. Creator gross fees: 0.006000000000 ETH. Separate deployer startup gas: 0.002638574996 ETH.

Unmeasured operating gas: renew, standalone-harvest, list, sync.

No monthly return, APR, Monte Carlo inference or viability proof. No partial campaign outcomes are inputs.

.03 backing is an isolated hypothetical for the current manager, whose admission rejects it; actual FWA admission is separately proven.

The cycle screen assumes gross listing-fee income k times backing per own selection under fixed proportional selection/fee weights. It is an analytical expected-fee attribution, not fees actually received on an individual acquisition or a measured return period. Cycle costs include fresh mints and full quoted keeper payments, not billed renewal/harvest/list/sync operating costs.

Owner wallet sensitivity reprices measured operation gas individually; do not sum mutually conditional recovery calls or interpret them as a measured complete path.

Actual round trips are unselected exits, use their own receipt gas prices, and are not added to cycle quotes. Creator accrual is gross; deployer startup is separate from owner cash.

Historical input receipt/runtime bindings are checked locally; no fresh mainnet observation or new transaction is performed.

The incomplete funded campaigns remain incomplete and earlier invalid campaigns remain excluded.

Things that don't make sense: Quoted keeper margins do not establish actual billed profitability. A balanced cash ledger does not establish positive owner returns.
