# System map: where PackVault's assets sit and how they move

Current design: one production vault and one capital pool. Exact running values live in
`VaultLib.Book`; its inventory indexes describe custody, not additional assets. Historical
measurements for earlier candidates remain under `docs/receipts/flow/` until regenerated.
Owner requirements: `OWNER-REQUIREMENTS.md`; decisions: `docs/DECISIONS.md` (D65).

| Actor | Brings | Receives |
| --- | --- | --- |
| Holders | ETH deposits and existing request charges | nontransferable shares, redeemed ETH, distributions |
| Permissionless keeper | gas for verified bounded work | replaceable policy's offer, capped by vault quotes, free cash and budgets |
| FWA purchaser | acquisition and settlement calls | pack, ETH bid or token bid according to FWA's actual rules |
| FWA main pool | custody, fee distribution and ordered acquisition journal | bid backing cut or ordinary keep fee |
| Shapes / ShapePacks | redeemable NFT backing and pack construction | primary mint fees, unchanged: 0.001 ETH per 0.1 ETH mint in the pinned fixture |
| FWA rewards | token entitlements | tokens are claimed and burned; zero NAV value |
| Owner | configuration inside bytecode bounds | no privileged asset withdrawal; can earn only what any keeper can earn |

| Bucket | Location and meaning | Required accounting |
| --- | --- | --- |
| Pending deposits | actual vault ETH, refundable before pricing | excluded from free cash and NAV |
| Redemption / distribution reserves | actual vault ETH owed to holders | excluded from free cash and NAV |
| Settled claimables | actual vault ETH owed to individual holders | excluded from free cash and NAV |
| `processingPool` | actual vault ETH funding one shared fixed checkpoint charge | excluded until checkpoint; no journal funding |
| Free cash | actual balance less all five protected buckets | NAV asset; only cash above reserve and estimated exits is deployable |
| Tracked Shapes backing P | loose Shapes, idle packs, active/allocated packs and authenticated return claims | counted once across representation/custody changes |
| Usable idle backing | subset of P available through bounded inventory redemption/recovery | liquidity estimate only; never added a second time to NAV |
| Active FWA backing B | actual posted ETH for cached active memberships | removed once when journal selection, kick or withdrawal is accounted |
| Active fee entitlement | FWA accumulator, exact authenticated witness and debt histogram | counted once; no portfolio enumeration |
| FWA fee credit | live `feeCredit(vault)` | counted once, or harvested into actual cash before valuation |
| Allocated P | subset of tracked backing; running exposure and FIFO queue | no additional asset; oldest unresolved entry enforces expiry guard |
| Token pending / credit / balance | rewards module and token | zero ETH value; burn remains unpaid |

```
NAV = free actual ETH + tracked Shapes backing + active posted FWA backing
    + aggregate pending active fees + live FWA fee credit
```

Uncredited crown rewards are excluded. Receipt tag reservations and `idleFunding` are identifiers
and future capital commitments, not additional assets. They never increase NAV or create cash.

Minting adds actual redeemable backing once; mint fees leave cash permanently. Splitting and
packing change representation. Listing exchanges cash B for active backing B and preserves P.
Selection removes active B and fee membership, preserving P as the conservative allocation floor.
A bid returns the pack or an authenticated claim to it. A keep receipt adds no synthetic cash:
the ETH is already in the vault balance; consuming it removes old P. Kick/withdrawal remove active
B while returned cash is counted by balance exactly once. Redemption exchanges P for actual ETH.
An extended kept pack gifted back is adopted only after retirement, at its actual current backing.
Oversized gifted packs use bounded unseal/claim recovery; unrelated gifts cannot create transitions.

Pricing requires blackout, drained FWA requests, a complete acquisition cursor, no pending payment
receipts, a clean allocation head, no overdue allocation and acceptable allocation exposure. Then
redemptions use preflow NAV, eligible distributions follow, and deposits use resulting NAV.
Protected balances remain protected through maintenance, cancellation and wind-down.

Routine and essential maintenance draw from free vault ETH inside their existing budgets.
Foreign/refunded journal entries do not return backing: their completed-work gas cost is an
explicit NAV expense with no per-entry flat work fee. This cost grows with new global activity.
Checkpoint valuation work does not grow with unchanged positions. Processing charges remain for
checkpoint work only. Token burning remains an operator expense.

Monotone values: journal cursor, allocation head, epochs, redemption era and interval marker advance
so completed work is not replayed. The high-water mark only rises so gains are not distributed
again. Wind-down is one-way; pause flags can be resumed by the owner. Mint fees, FWA bid losses,
settlement fees and paid gas do not reverse. Removing their trigger does not refund those costs.
No lifetime backing-ID counter ratchets quotes upward: identifiers retire and may be reused.
