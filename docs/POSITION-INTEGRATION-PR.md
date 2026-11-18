# Remove the position ceiling with incremental accounting and efficient journal jobs

PackVault maintains one authoritative incremental book instead of a 300-position ceiling and
portfolio scans. Paid Shapes mints, packing recipes, creator fees and protected holder liabilities
remain. Provably unexposed history advances unpaid, preserving the minimum seed and first deposit.

This revision makes journal processing an automatic bounded job: 128 global records, with separate
16-own-selection, 16-terminal-ID and 16-prune bounds. Callers cannot choose a smaller paid slice.
Small foreign tails require a genuine checkpoint opportunity, including authenticated post-cost
distribution eligibility. There is no completion bonus. Sync remains routine upkeep during
redemption; D64's caller-funded unlisting/liquidation stays intact.

The keeper discovers returned packs from authenticated ETH/token bid events, retains unseen own
selections, independently discovers expiry, and upgrades existing indexes through bounded replay.
It pauses new exposure when known upkeep exceeds free cash or routine permission. Restock avoids
storing immediately consumed minted IDs and caches shared economics before minting.

## Verification

- Five new real FWA journal/distribution cases, 17 lifecycle/real-selection callers, five
  bootstrap/cash-only callers, 14 accounting tests and keeper/index checks pass. Three obsolete
  selective-work assertions are repaired; their failures remain archived.
- Both fresh fork traces reconcile every financial bucket to the wei. Cold receiver samples are
  unchanged at 46,462 / 69,730 gas. Runtime: **24,451 bytes**, 125 below EIP-170; library 22,997.
- Seven inventory profiles preserve fees/principal and improve receipt-equivalent restock execution
  by 1.28–7.24%. Fixed quotes are unchanged, so holder savings are not yet established.
- Earlier production-image startup and shared-volume replacement checks remain valid for their
  unchanged packaging. [Isolated image verification](https://github.com/ripe0x/shapes-fwa-pool/actions/runs/44393965532).

The all-cost model includes 84 primary cases and 28 separate holder-rescue diagnostics: 56 primary
exits complete, 28 more need holder-paid sync, and only 40 primary cases avoid routine funding
stalls. All 112 ledgers balance. These stochastic scenarios use historical gas proxies and do not
establish expected returns or funded operation. The inherited daily clock uses a 10^12-second
settlement surrogate versus actual 3,600 seconds, so its exit counts and returns are hypothetical
accounting diagnostics, not achievable operating evidence or grounds for raising an allowance.

Current commands, hashes, preserved failures and scope: [revision results](docs/EFFICIENT-JOURNAL-RESULTS.md).
The prior 52 affected checks and real 301-listing rehearsal are archived evidence for their named
inputs, not a new broad release verification of this revision.

## Things that don't make sense

- **Economics remains blocked.** At current quotes, the archived 18,281-record window needs at
  least **0.2802925 ETH / 30 days at 0.5 gwei**, before own work. That is **0.0093430833 ETH/day**
  versus the configured 0.005 refill. Vault operating cash is the default funding source;
  creator mint revenue is not an assumed subsidy.
- **O2 remains unresolved:** fresh max-load 1,919,655 versus 1,750,000 quoted gas; components are
  unchanged. Execution savings alone do not lower holder compensation. No outcome or signature changed.
- **Receipt gaps remain.** The new bounded local matrix is prepared, awaiting explicit approval.
  Authentic exposed successful-foreign bills are still unavailable under this local setup;
  refund receipts cannot substitute for them. Maximum combined own-transition work is unmeasured.
- **The old 342,766 checkpoint bound was wrong.** It subtracted finalized Foundry refunds twice.
  Current direct finalized gas is 345,937 against Q360; standalone billed full-holder proof remains pending.
- **Permission does not supply liquid cash.** Partial redemption can encumber the cash needed
  to reconcile a later returned pack; the existing holder rescue is explicit, not a funded
  keeper pass. Available authentic fixtures cannot reproduce this timing, so the finding is
  model/source evidence only.
- **The daily model is not an economics gate.** Its settlement/blackout timing surrogate can
  change terminal work, cash and rescue need. Fixing that model and obtaining authentic receipts
  remain necessary before accepting holder returns.
- **Foreign staging can still block new admission.** Another actor must clear that staging; bounded
  journal/accounting recovery remains available.

**Keep this PR draft.** No allowance increase, sponsorship assumption, minimum TVL, public-chain
transaction, real-fund spending, owner signature or merge is included. Affected review is not a
full security audit or release approval.
