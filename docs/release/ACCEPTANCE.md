# Owner acceptance package (unsigned)

Every open owner decision for the first public deployment, in one place. The machine-readable
copy is [acceptance.json](acceptance.json); signing its sha256 accepts every item below as written
and is what `script/deploy.sh` checks before a public broadcast. Nothing is accepted yet.
Requirement IDs are given with their meaning because "O1" and "O2" mean different things in
`OWNER-REQUIREMENTS.md` and `asset-flow.json`.

## A1. Holder return requirement fails at the canary's 2 ETH size

Requirement: OWNER-REQUIREMENTS A.3/A.8, B2 O1 (holder return ≥10% a year at trailing-30-day
successful volume, tokens zero, every expense, 0.5 gwei). Measured at block 26,450,200, 360 days
plus exit, 16 seeds, complete claims only:

| Principal | Median | Mean | p10 | Losing seeds |
|---|---:|---:|---:|---:|
| 1.96 ETH (canary) | −5.3% | +5.3% | −67% | 9 of 16 |
| 6.8 ETH | +76% | +75% | +34% | 1 of 16 |
| 20 ETH | +49% | +50% | +18% | 0 of 16 |

Cause: routine keeper pay for the shared FWA journal is about 1.5 ETH a year at 0.5 gwei whatever
the vault's size; a 2 ETH vault's edge does not cover it. No small code correction changes that
without cutting supported keeper pay, which the requirements forbid.

| Option | Effect | Cost to holders |
|---|---|---|
| **Deploy the 2 ETH canary as an owner-funded functional test, reviewed after 14 days or 5 real selections** (recommended) | Proves live VRF timing, gas and keepers; economics are not expected to clear the hurdle at this size | about 0.06 ETH of routine pay over 14 days at 0.5 gwei; a full year's downside at p10 is −67% |
| Raise the canary cap to about 7 ETH | Clears the hurdle in the model | more capital exposed before any live evidence |
| Do not deploy | No exposure | none |

## A2. O2 construction expense exception (asset-flow O2, "what building costs holders")

Measured 1,919,655 quoted gas per position built and listed against the 1,750,000 target; the
target is kept, so the outcome fails. Difference 169,655 gas = **0.0000848 ETH per position at the
0.5 gwei ceiling**. Model builds per year (from paid mints): canary about 46 packs, 0.0039 ETH a
year; 6.8 ETH about 220 packs, 0.019 ETH; 20 ETH about 465 packs, 0.039 ETH. No supported saving
was found beyond the completed optimization pass. Accepting this item accepts 1,919,655.

## A3. Raised pay constants (independent review)

`MAX_ROUTINE_RATE` 0.01 → 0.02 ETH a day; `Q_PACK_UNIT` 35,000 → 100,000 (inactive at three-unit
packs); `Q_SELECTED` 160,000 → 180,000; `Q_REQUIRED_TAIL` 110,000 → 120,000. Each is funded from
holder NAV and set from measured receipts (`COMPLETE-OPERATING-PASS.md`).

## A4. Spending and owner-key bounds (replaces B3's figures)

Canary routine pay at most 0.04 ETH in the first 24 h, then 0.01 ETH a day. With every bytecode
maximum set at once, a compromised owner key reaches at most the current budget plus 0.025 ETH a
day: about 0.055 ETH in the first 24 h. Request-funded checkpoint pay is separate: at most
0.00074 ETH per 12 h interval at canary settings, only from request charges. The owner key is one
hot EIP-7702 account, not the multisig or hardware wallet B3 assumed.

## A5. Coverage limits

- More than 16 simultaneous own allocations cannot be produced by authentic VRF replay; the bound
  is enforced by the contract and keeper discovery is proven across 18 real returned packs.
- The maximal combined sync is a quoted-gas bound (10,576,250 padded), not a receipt.
- A pure 128-successful journal batch is bounded from the measured mixed batch, not measured.
- Two live keepers occasionally race; the loser reverts and pays its gas.

## A6. Updated asset-flow outcomes

`asset-flow.json` outcomes are restated for this candidate (current budgets, measured values) and
are unsigned. The 2026-11-17 signature is kept in `docs/release/history/` for the older candidate.

## A7. Authorization still required after signing

Signing authorizes no transaction. The broadcast itself, keeper funding, Fly deployment and any
later TVL-cap increase each need the owner's explicit go-ahead.
