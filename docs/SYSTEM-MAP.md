# System map: assets, rights and funding

PackVault and each personal PackManager are separate FWA depositors and custodians. Shared linked
libraries own no assets. The factory cannot change an existing manager. Current requirements:
OWNER-REQUIREMENTS A5 and [MAIN-POOL-COMPLETION.md](MAIN-POOL-COMPLETION.md).

| Actor | Contributes | Receives or controls |
| --- | --- | --- |
| Vault holder | Gross escrow, checkpoint sponsorship and wallet gas | Priced shares, pro-rata redemption/distribution claims, attributed funding refunds |
| Manager owner | Their own cash and wallet gas | Their manager's cash, packs and immediate settings |
| Account owner | Economic configuration | No pooled-asset withdrawal; can perform verified keeper work like other callers |
| Keeper | Actual transaction gas | Account's verified quoted compensation within source/cash/permission limits |
| Purchaser | FWA acquisition and settlement | Actual pack or actual protocol bid, at their choice |
| Shapes creator | Primary mint service | Actual paid mint fees, never assumed recycled as sponsorship |
| FWA | Listing custody, acquisitions and fee accrual | Protocol cuts, bid backing and settlement fees under real deployed rules |

| Bucket | Valuation and spending rights |
| --- | --- |
| Pending gross deposits | Cancellable payer escrow; excluded from NAV/free cash until commitment |
| Redemption/distribution reserves and claimables | Owed holder cash; excluded from NAV and every keeper/growth source |
| processingPool | Attributed active-era sponsorship; only verified required pricing work/checkpoint may spend it |
| chargeRefundReserve | Closed-era payer refunds; never NAV, investment, compensation or liquidity |
| Free cash | Actual account balance less every liability; part of NAV |
| Renewal float | Target within free cash reserved against new growth and ordinary routine pay; eligible renewal may consume it |
| Maintenance reserve | Target within free cash preserved by growth/renewal; pays real maintenance |
| Tracked pack principal | Actual owned/allocated/owed redeemable principal, counted once across custody changes |
| Active FWA backing | Posted cash, removed once at acquisition or withdrawal |
| Pending fees / fee credit | Exact entitlement, counted once; not cash until actual collection |
| Renewal eligibility | Single-use verified work permission; zero additional NAV |
| Unresolved keep uplift | Conservative uncertainty bound; zero additional NAV |
| FWA token rewards | Zero ETH NAV; public claim-and-burn remains unpaid |

NAV = free actual cash + tracked principal + active backing + exact pending fees + live fee credit.

Fresh construction exchanges principal cash for redeemable Shapes and pays mint fees permanently.
Listing moves separate backing to FWA. Acquisition removes active backing; bid returns the pack,
keep returns backing less the live settlement fee and transfers the pack. Retirement exchanges
actual principal for cash; fresh renewal pays fresh creator fees again. Ordinary withdrawals and
kicks do not create renewal permission. Recovery/terminal processing stays bounded.

Cancellable deposits do not count as preparatory liquidation cash. At a successful checkpoint they
commit atomically and may fund matched redemption. Sponsorship pays its own source directly; unused
funding becomes attributed refunds. Refund claims do not consume general capital. Removing a request
or lowering a quote does not erase a prior payer's record.

Ratchets: acquisition cursor, allocation head, epochs, contribution IDs/eras and interval markers
advance to prevent duplicate work. Historical contribution intervals persist for lazy refunds.
The high-water mark rises to prevent repeat distributions. Wind-down is one-way for the vault;
manager exit is owner-reversible. Mint fees, settlement cuts, paid keeper compensation and wallet
gas are irreversible expenses. Removing their trigger does not recover them.

Things that don't make sense: accrued income cannot fund renewal until collected; an enlarged
allowance supplies no cash; exact accounting alone does not establish fair pricing or viable returns.
