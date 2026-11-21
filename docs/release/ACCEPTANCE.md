# Owner acceptance: unified candidate (unsigned)

[acceptance.json](acceptance.json) binds commit `3573ea6`, the release manifest (`e7dd6d38…`), the
canary values (`deploy/canary.json`) and the asset-flow outcomes O1–O11. Signing its sha256 accepts the
items below. It authorizes nothing else: no broadcast, funding, Fly deployment or public offer of
personal managers.

| Item | What you accept | Numbers |
|---|---|---|
| U1 Canary return | The 2 ETH canary is a technical deployment; its return tail is wide | Formal gate median +70.6%, p10 −55.3%, 5 of 16 years lose; quieter demand median +0.6% (all bid) to +9.8% (all keep), below the 10% hurdle |
| U2 Recipe | 0.06 ETH packs, direct mint (one 0.05 + one 0.01 Shape) | 2.6 to 5.4× the creator revenue of 0.03 bulk-split; at the canary 0.03 bulk-split's median is slightly higher under all-bid (+25.1% vs +22.8%) and observed (+37.5% vs +34.3%) behaviour |
| U3 Purchaser gas | Fixed 2 gwei bound in the keep incentive | Backing 0.06489617 ETH; keep beats the best bid by 0.0003 ETH after 160,000 gas |
| U4 Payment receipts | Settlement from FWA's record; kick refunds checked while kicks are possible | Above 32 open listings with the exemption lifted, pool pricing waits for wind-down (canary holds at most about 16) |
| U5 Spending | Canary keeper budgets and checkpoint pay | 0.04 ETH routine in 24 h, then 0.01 ETH a day; essential budget 0 |
| U6 Asset flow | Outcomes O1–O11 replace the 2026-11-17 signature for this candidate | outcomes sha256 `9908f120…` |
| U7 Coverage limits | What was not shown for real | Image fork rehearsal in CI only; VRF outcomes via coordinator impersonation; mirror lacks the in-sync credit sweep; 6.8 and 50 ETH matched cells as a pilot only; the passing image run had no redemption shortfall for the holder to unwind; local rehearsal fork upstream was Alchemy |
| U8 Authority | Signing is acceptance only | Broadcast, funding, Fly and the manager product are separate decisions |

Evidence: [RUNBOOK.md](RUNBOOK.md) section 2. Earlier packages: `docs/release/history/`.
