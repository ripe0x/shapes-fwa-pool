# Owner acceptance package (unsigned)

> **Superseded for the unified candidate (2026-11-21).** Items A1–A7 below describe the pre-A3
> candidate. The unified candidate (`docs/UNIFIED-SYSTEM.md`) changes the recipe, the backing rule,
> holder returns, keeper quotes and adds the factory; its owner items are `UNIFIED-SYSTEM.md`
> sections 7 and 8. `acceptance.json` has not been restated, so nothing here can be signed for it.

Every open owner decision for the first public deployment, in one place. The machine-readable
copy is [acceptance.json](acceptance.json); signing its sha256 accepts every item below as written
and is what `script/deploy.sh` checks before a public broadcast. Nothing is accepted yet.
Requirement IDs are given with their meaning because "O1" and "O2" mean different things in
`OWNER-REQUIREMENTS.md` and `asset-flow.json`.

## A1. Holder return at the canary's 2 ETH size (updated after D75)

Requirement: OWNER-REQUIREMENTS A.3/A.8, B2 O1. After the scan proof (D75), 400 seeds at 0.5 gwei:
**median +40.5%, mean +62.7%, p10 −62%, 33% of years lose** (0.15 gwei: median +88%, 23.5% lose).
The gate as defined (median) passes. The loss tail is selection luck at small size, not keeper
cost. Decision for the owner: accept a third of canary years losing (up to about two thirds of
principal at p5) as the price of a live test, or start larger (20 ETH, 32 seeds: 3% lose).
Details: `docs/KEEPER-ECONOMICS.md`.

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
hot EIP-7702 account, not the multisig or hardware wallet B3 assumed. Since D76 the owner can be
moved to a hardware wallet or Safe without a new vault, by two-step handover only; one-step
transfer and renouncing are disabled. It cannot recover a key an attacker has already used.

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
