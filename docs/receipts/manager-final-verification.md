# Individual manager final closeout

Runtime: `1bbe54c94eed34818d5e2c7ccd95d5f83a892b90`, unchanged during this closeout. App interaction/ABI source: `1330b18ee3bb38b85e9439b3c7213ac37fc9f1d8`; its later closeout is documentation only. This pass changes an offline receipt scorecard, the manager release evidence inventory and documentation. It does not change contracts, ownership, recipe, economic settings, app interactions or launch gates.

The owner resumed the manager task on 2026-11-24. The agreed limit is 15 minutes cumulative active execution and at most four concurrent workers. The uninstalled guard was not replaced. No Monte Carlo campaign, fork lifecycle, broad Solidity suite or new deployment rehearsal was started. Valid runtime-specific evidence is reused. The stopped campaigns remain incomplete; no partial financial row is used.

## Focused final batch

Exact commands, elapsed times, statuses and logs: [final-closeout-checks.json](manager-funded-checks/final-closeout-checks.json).

- Initial `python3 sim/test_manager_closeout.py` failed before tests because that interpreter lacked NumPy. The failure log is preserved. No dependency was installed or cache removed.
- Existing receipt environment `/Users/dd/.pyenv/versions/3.11.8/bin/python` then ran the three initial closeout tests, generated the scorecard, and ran `script/test_release.py` and `keeper/test_manager_exit.py`. These checks passed (3 + 22 + 10 tests). Independent review then found a missing diagnostic/proposal source binding; it was repaired with explicit pins and a real-source mutation regression. All four affected closeout tests passed after that repair. This was one focused batch, continuing unrun checks after the interpreter correction.
- Previous valid evidence: 18 affected fork cases, three real-counterparty funding regressions, cold callback, 43 exact accounting steps and 23 billed local transactions. Their full scope and limits remain in [manager-funded-verification.md](manager-funded-verification.md).
- Runtime bytecode is unchanged: PackManager 17,853 bytes, VaultLib 22,486, StrategyLib 18,279, ScanLib 22,993, below EIP-170. Existing billed local transactions fit the 16,777,216 limit. No duplicate broad suite was needed. The existing manager-only production path completed a fresh public read-only simulation in 6.309 seconds; compilation was cached. No PackVault or vault seed was created. Fresh unsigned deployment/creation and keeper address data were then regenerated from that same production-path dry run; all remain explicitly unsigned. The simulation precheck reported the intentionally uncommitted/stale evidence inventory; its log is preserved, and the final committed manifest check is separate. Existing orphan-artifact warnings were retained; no cache was cleared.

## Actual economic scorecard

| Outcome | Evidence | Interpretation |
| --- | --- | --- |
| .5 ETH manager full exit | Owner net −.001940071586360229 ETH | Actual unselected lifecycle including wallet gas, not a monthly return |
| 1 ETH manager full exit | Owner net −.005198947885644295 ETH | Actual three-pack lifecycle, not a causal comparison with the first account |
| Terminal holdings | Both accounts: zero cash, credit, inventory and receipts | Zero keeper permission, no account topups |
| Keeper | .000795905178295 paid; .000604073134372415 gas; .000191832043922585 net | Same local receipt set |
| Creator | .006 ETH gross fees, twelve paid primary mints | Separate from owner/keeper profit |
| Standard .03 backing/.03 pack | FWA admits it; manual unselected round-trip losses .001858795/.0023969815 ETH at .2/.5 gwei | Current manager admission rejects that ratio; hypothetical manager sensitivity is labelled |
| Current mint fee | .0005 ETH at block 26489769 | Read only; .001 ETH remains the accepted maximum and historical comparison |
| Production outcome | No acceptable full-period return demonstrated | No production recommendation or owner acceptance |

The [bounded scorecard](manager-closeout-economics.md) independently partitions actual receipt cash and compares both bid/keep quoted costs at .03/.21 backing, .0005/.001 fees and .2/.5 gwei. Its per-selection fee attribution is an expectation screen, not actual income at an acquisition. High-backing keep gains do not assume buyers will choose that outcome. Actual paid mint fees, keeper payments and wallet gas are counted separately without double charging.

The smallest existing mechanism worth evaluating further is explicit `ReuseReturned` for bid returns: it removes repeat paid mints/retirement on those returns while preserving .03 packs. Tradeoff: creator primary fees occur on initial/new replacement builds, rather than every returned acquisition. A keep still needs a fresh paid replacement. No renewal mode or production setting was changed, and this proposal does not establish viability. Lowering the public mint fee is not required or authorized by this closeout. Standard backing would additionally require a separately reviewed admission/coverage change; bypassing that guard is not included.

## Deployment boundary and missing evidence

The [manager-only runbook](../release/MANAGER-RUNBOOK.md), unsigned deployment/creation/address data and target-bound manifest form the delivery package. Existing main deployment readback was refreshed at block 26489773: vault balance .01 ETH; supported pending deposit, locked shares, redemption/distribution/claim reserves and FWA fee credit are zero; existing factory manager count is zero. Unsupported selectors remain recorded, not inferred as zero. Dependencies match the existing verified receipt runtimes. No public state was changed.

Authenticated billed renewal, standalone harvest and variable paid sync/list gas remain unmeasured. No full-period return forecast, public keeper operation, hardware-signing proof, mainnet lifecycle, production approval, public mint-fee change, live cutover or merge is claimed. Public app gates and the shared vault remain closed. The package must be refreshed again before any separately authorized signing.

Things that don't make sense: positive creator/keeper revenue does not make the owner profitable; larger allowances provide no cash; FWA admission does not establish manager admission; a fixed-path study size cannot become an owner requirement through a handoff.

Final release identity is checked after committing with `/Users/dd/.pyenv/versions/3.11.8/bin/python script/release.py check deploy/manager-factory.json --target manager`. This only verifies local identity and does not authorize or send a transaction. Main/app draft PR heads identify the delivery revision; the runtime and prior receipt revisions above remain unchanged.
