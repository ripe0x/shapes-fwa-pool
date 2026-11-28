import json, hashlib, statistics, re, sys
from pathlib import Path
from fractions import Fraction
from decimal import Decimal
from datetime import datetime, timezone
ROOT=Path(__file__).resolve().parents[3]
p=ROOT/'docs/receipts/formal-assessment.json'
r=json.loads(p.read_text());rows=r['rows'];assert len(rows)==89
assert all(hashlib.sha256((ROOT/k).read_bytes()).hexdigest()==v for k,v in r['source_sha256'].items())
key=lambda a:'|'.join(map(str,(a['label'],a['config'],a['principal_wei'],a['total_price_gwei'])))
for k,s in r['summary'].items():
    group=[a for a in rows if key(a)==k]
    values=[Fraction(a['holder_net_realized_wei']*10000,a['holder_paid_in_wei']) for a in group if a['exit_complete']]
    s['historical_upper_middle_return_bps']=s['median_return_bps']
    s['standard_median_return_bps']=float(statistics.median(values)) if values else None
    s['mean_holder_net_eth']=statistics.mean(a['holder_net_realized_wei']/10**18 for a in group)
r['statistics_clarification']={'standard_median':'statistics.median of each completed holder net return divided by its actual paid-in amount; mean of the middle pair for four draws.', 'historical_median_field':'median_return_bps retains the original upper-middle order statistic for comparability, and is also named historical_upper_middle_return_bps.', 'downside':'With four draws the historical empirical P10 is the worst draw. These finite samples are not confidence bounds.', 'creator_revenue':'Gross paid primary-mint fees accrued, not creator-wallet withdrawals.'}
gates=[s for s in r['summary'].values() if s['label']=='formal' and s['total_price_gwei']==.5]
r['formal']['historical_upper_middle_holder_return']=r['formal']['holder_return']
r['formal']['standard_median_holder_return']=all(s['completed_claims']==s['runs'] and s['standard_median_return_bps'] is not None and s['standard_median_return_bps']>=1000 for s in gates)
limit='The synthetic compressed-burst timestamps place 2,834 of 149,460 requests inside purchase blackout; these cells are abstract cash/permission stress, not a feasible onchain admission/VRF schedule. Actual-month formal gate cells are unaffected.'
if limit not in r['limits']:r['limits'].append(limit)
r['synthetic_burst_timing_limit']={'compressed_requests':149460,'inside_purchase_blackout':2834,'interpretation':'Abstract stress only; not feasible protocol timing or realized APR.'}
r['postprocessing']={'method':'Standard medians calculated from unchanged frozen-run rows; original upper-middle gate retained and explicitly labelled.', 'command':[sys.executable,*sys.argv], 'script':str(Path(__file__).relative_to(ROOT)), 'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
small_key=next(k for k,s in r['summary'].items() if s['label']=='formal' and s['principal_eth']==1.9601 and s['total_price_gwei']==.5)
r['formal']['holder_return_at_1_96_eth']=dict(r['summary'][small_key])
formal_log=ROOT/'docs/receipts/completion-checks/simulation-formal.log'
reconcile_log=ROOT/'docs/receipts/completion-checks/simulation-reconcile.log'
r['verification']={
 'formal':{'argv':['/tmp/shapes-completion-python/bin/python','sim/formal.py','--seeds','4','--workers','4'],'cwd':str(ROOT),'environment':{'CANDIDATE_RUN':'1'},'exit_status':0,'tool_session':15265,'stdout_stderr':str(formal_log.relative_to(ROOT)),'log_sha256':hashlib.sha256(formal_log.read_bytes()).hexdigest()},
 'archive':{'entrypoint':'assert replay.main() == 0 inside the same formal invocation, before any jobs','return_status':0,'earnings_checked':876437,'exact_matches':876437,'mismatches':0,'acquisition_sequences':'continuous','stdout':formal_log.read_text().splitlines()[0]},
 'contract_mirror':{'argv':['/tmp/shapes-completion-python/bin/python','sim/reconcile.py'],'cwd':str(ROOT),'environment_overrides':{},'exit_status':0,'stdout_stderr':str(reconcile_log.relative_to(ROOT)),'log_sha256':hashlib.sha256(reconcile_log.read_bytes()).hexdigest(),'trace_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted((ROOT/'sim/out').glob('reconcile*trace.jsonl'))},'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in ['sim/reconcile.py','sim/vault.py','keeper/policy.py','keeper/config.py']}}}
p.write_text(json.dumps(r,indent=1)+'\n')
E=10**18
fmt=lambda x:f'{x:.6f}'
pct=lambda b:'n/a' if b is None else f'{b/100:+.2f}%'
small=next(s for s in r['summary'].values() if s['label']=='formal' and s['principal_eth']==1.9601 and s['total_price_gwei']==.5)
cal=json.loads((ROOT/'docs/receipts/completion-calibration.json').read_text())
paid=[a for a in cal['transactions'] if a['status'] and a.get('keeperPayWei',0)>0]
margins=[a['keeperPayWei']-a['gasUsed']*a['effectiveGasPrice'] for a in paid]
assert len(paid)==19 and min(margins)>0
assert all(a['essential_keeper_paid_wei']==0 for a in rows)
completed=sum(a['exit_complete'] for a in rows)
latest=json.loads((ROOT/'deploy/existing-main-readback.json').read_text())
v=json.loads((ROOT/'deploy/mainnet.json').read_text());q=v['gasSchedule'];P=3*10**16;B=P*v['backingRatioBps']//10000
buildgas=q['build']+q['buildPack']+3*q['buildShape']+q['listed']
retiregas=q['liquidate']+q['liquidatePack']+3*q['redeemShape']
def quote(g,u,price):return g*price*(10000+v['payMarkupBps'])//10000+u*v['workFeeWei']
floatone=B+3*v['acceptedMintFeeWei']+quote(buildgas+retiregas,3,v['gasCeilingWei'])
lines=[
'# Main pool economic evaluation, 2026-11-24', '',
'**Keep the package unsigned and the main-pool production gate closed.** The implementation evidence is distinct from the economic launch decision. At the selected 0.03 ETH recipe, the 1.9601 ETH holder cell fails the unchanged 10% net return hurdle at 0.5 gwei. None of the tested small-capital backing/float alternatives establishes that hurdle using the standard median.', '',
'| Outcome | Bounded result |', '|---|---|',
f'| Three paid fresh mints | 0.03 ETH pack; gross primary fees accrued 0.003 ETH at the current fee, 0.0015 ETH in the isolated half-fee sensitivity. |',
f'| 10% holder hurdle | **FAIL**: standard median {pct(small["standard_median_return_bps"])}, historical upper-middle {pct(small["median_return_bps"])}, worst {pct(small["worst_return_bps"])}, losses {small["loss_runs"]}/{small["runs"]} in the 1.9601 ETH / 0.5 gwei cell. |',
f'| Completed exits | {completed}/89 model exits complete; all six actual contract/mirror trace groups reconcile to the wei. This does not guarantee future exit timing. |',
f'| Bid-cycle screen | Closed-form net at 0.5 gwei {r["bid_outcome"][1]["net_wei"]/E:+.9f} ETH after the full fresh lifecycle quote; this does not establish annual holder returns. |',
f'| Keeper receipt sample | All {len(paid)} positive-payment rows among {len(cal["transactions"])} campaign receipts have positive pay minus billed gas; smallest observed surplus {min(margins)} wei. This is not an all-operation profitability claim. |',
'| Checkpoint expense target | **FAIL** against retained O6 target 0.0002 ETH: 500,000 gas + 0.00002 work fee costs 0.00027 ETH at 0.5 gwei, or 0.00102 ETH at the 2 gwei funded-checkpoint ceiling. Allocation-proof work can add cost. |',
'| Unresolved pricing | Selected 25 bps tolerance permits measurable ordering transfers; a 0.18 ETH unresolved uplift requires at least 72 ETH preflow NAV. |',
'| Production boundary | No public transaction, mint-fee change, live cutover or merge. Existing contracts and balances are preserved. |', '',
'## Evidence and method', '',
'One frozen campaign ran `CANDIDATE_RUN=1 /tmp/shapes-completion-python/bin/python sim/formal.py --seeds 4 --workers 4`: 22 stochastic cells with four draws each, plus one deterministic zero-demand case. The actual trailing 30 days are repeated for 360 operating days, with up to 30 exit days. Tokens are zero. The fee archive checked 876,437 EarningsAccrued records with zero mismatches and continuous acquisition sequences.', '',
f'The window contains {r["window"]["successful"]} successful and {r["window"]["refunded"]} refunded acquisitions ({r["window"]["successful_per_day"]:.2f} successes/day), ending at block {r["pin"]["block"]:,}. Latest separate readback at block {latest["block"]:,} confirms the current Shapes mint fee remains 0.001 ETH. The half-fee cells keep the accepted maximum at 0.001 ETH, so their float stays conservative.', '',
'Every holder return below includes actual account mint fees and keeper compensation once, checkpoint/contribution net consumption, and holder wallet gas. Wallet gas is a labelled proxy from actual billed receipts; variable unpaid maintenance uses the larger of its verified-work allowance and calibrated receipt sample. Reverted races and inclusion latency are not priced. Keeper columns show compensation, not net profit. Creator columns show gross paid primary-mint fees accrued in Shapes; no creator wallet withdrawal was executed or claimed.', '',
'The deployment package separately requires a 0.01 ETH seed and estimates 0.022785059249598685 ETH one-off deployment gas. These are unsigned simulation values, not public expenditure. They are excluded from recurring holder returns; creator gross fees are not owner net profit after startup/withdrawal costs.', '',
'The standard median is the mean of the middle pair. The original script upper-middle statistic remains visible for comparison and floors to integer basis points; occasional 0.01 percentage-point display differences even for one draw come from that flooring. Both fail the overall gate. With four draws, the empirical P10 equals the worst draw; none is a statistical confidence bound. Large positive outliers must not be substituted for depositor downside.', '',
'The complete six-group contract/mirror command was `/tmp/shapes-completion-python/bin/python sim/reconcile.py` from the repository root, exit 0. Exact argv, environment, source/trace hashes and durable stdout are embedded in the frozen-run JSON. Archive replay also ran inside that exact formal invocation before any scenario jobs.', '',
'## All scenario cells', '',
'Amounts in ETH; flow columns are means within the same cell. Returns are completed-holder net returns on actual paid-in value.', '',
'| Cell | Capital | gwei | Standard median | Upper-middle | Worst | Losses; claims | Gross primary fees accrued | Keeper compensation | Wallet gas proxy |',
'|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
for s in r['summary'].values():
    lines.append(f'| {s["label"]} | {s["principal_eth"]:g} | {s["total_price_gwei"]:g} | {pct(s["standard_median_return_bps"])} | {pct(s["median_return_bps"])} | {pct(s["worst_return_bps"])} | {s["loss_runs"]}/{s["runs"]}; {s["completed_claims"]}/{s["runs"]} | {fmt(s["mean_creator_mint_fees_eth"])} | {fmt(s["mean_routine_keeper_eth"]+s["mean_request_funded_keeper_eth"])} | {fmt(s["mean_holder_gas_eth"])} |')
lines += ['', 'Recorded timing/choice cases are diagnostics, not the all-bid formal gate. Purchaser choices and vault selections are seeded counterfactuals; historical VRF selected foreign listings. Foreign pool weights/fees do not react to the candidate. Early-burst cases synthesize ten copies of the recorded month compressed into the first two days and then zero acquisitions, not observed activity or billed fork performance. In this abstract compression, 2,834 of 149,460 requests land inside purchase blackout; the compressed request/VRF schedule is not feasible onchain. These cells only stress cash and permission and cannot establish protocol timing or a passing return gate.', '',
'Fee and gas cells follow state-dependent selection and reinvestment paths even with the same seed. Four draws do not establish that a fee reduction causes worse returns. With other state held fixed, the fork tests verify that a lower live fee reduces the actual mint cost; none of these sensitivities approves a production fee change.', '',
'## First opening and burst funding', '',
f'Named schedule: full construction allowance {buildgas:,} gas; retirement allowance {retiregas:,} gas. One conservative renewal float is backing + three accepted fees + full retirement/build/list compensation at the routine ceiling: **{floatone/E:.7f} ETH**. The independent maintenance reserve is 0.005 ETH.', '',
'| Actual mint fee per Shape | Total gas price | Construction compensation | Gross primary fees | Account cash needed before first build |', '|---|---:|---:|---:|---:|']
for fee in (10**15,5*10**14):
 for price in (200000000,500000000):
  comp=quote(buildgas,2,price);opening=P+B+3*fee+comp+v['reserveWei']+floatone
  lines.append(f'| {fee/E:g} ETH | {price/10**9:g} gwei | {comp/E:.7f} | {3*fee/E:.4f} | {opening/E:.7f} ETH |')
lines += ['', 'These are account cash thresholds including seed cash, reserve and float; checkpoint sponsorship and wallet/deployment gas are additional. They are not a minimum deposit or a minimum TVL. Cash-only deposits and exits still work below the first productive opening.', '',
'One float covers one worst-gap returned acquisition renewal, not an arbitrary burst. The real conditional-credit funding trace started with 0.213466500807007324 ETH cash, 0.03 ETH returned principal and 0.000072998385985353 ETH actual fee credit. It paid 0.000503 ETH keeper compensation and 0.003 ETH mint fees, then ended with 0.000036499192992677 ETH cash, one eligible returned pack and 0.298675333333333333 ETH routine permission. The next renewal waits for cash despite ample permission. That isolated branch uses reserve zero to expose funding; it is not the default reserve scenario.', '',
'Conversely, the low-permission stress uses routine cap 0.004 ETH and refill zero. Raising a capacity does not refill spent permission; increasing a rate accrues prospectively. Available ETH cannot substitute for spending authority. Operating-end diagnostics below distinguish the two balances; cash includes protected amounts and is not all spendable.', '',
'| Synthetic cell | gwei | Standard median | Mean operating-end cash | Mean remaining routine permission | Mean routine compensation | Mean journal backlog at cutoff |', '|---|---:|---:|---:|---:|---:|---:|']
for k,s in r['summary'].items():
 if s['label'].startswith('early-burst'):
  group=[a for a in rows if key(a)==k]
  m=lambda name:statistics.mean(a[name] for a in group)
  lines.append(f'| {s["label"]} | {s["total_price_gwei"]:g} | {pct(s["standard_median_return_bps"])} | {m("operation_end_cash_wei")/E:.6f} | {m("operation_end_routine_budget_wei")/E:.6f} | {m("operation_end_routine_paid_wei")/E:.6f} | {m("operation_end_backlog"):.1f} |')
lines += ['', '## Backing, float and uncertainty tradeoffs', '',
'Keep the fixed three-mint recipe. None of these four-seed small-capital alternatives clears the standard-median hurdle at both tested prices. Do not change production economics to manufacture a passing upper-middle statistic.', '',
'| Candidate | First-opening cash at 0.5 gwei/current fee | Worst-gap float | Preflow NAV for one unresolved allocation at 25 bps | Tradeoff |', '|---|---:|---:|---:|---|']
for ratio,count,label in ((50000,1,'50,000 bps / float1'),(70000,1,'70,000 bps / float1'),(90000,1,'90,000 bps / float1'),(70000,2,'70,000 bps / float2')):
 backing=P*ratio//10000;one=backing+3*v['acceptedMintFeeWei']+quote(buildgas+retiregas,3,v['gasCeilingWei']);opening=P+backing+3*10**15+quote(buildgas,2,v['gasCeilingWei'])+v['reserveWei']+count*one;nav=(backing-P)*10000//25
 trade='Lower cash demand, lower bid-cycle margin' if ratio==50000 else 'More cash and greater pricing uncertainty' if ratio==90000 else 'One extra worst-gap replacement, less growth cash' if count==2 else 'Selected local evaluation candidate'
 lines.append(f'| {label} | {opening/E:.7f} ETH | {count*one/E:.7f} ETH | {nav/E:g} ETH | {trade} |')
lines += ['', 'For selected backing 0.21 ETH and face 0.03 ETH, unresolved uplift is 0.18 ETH. The bound is `uplift × 10,000 ≤ preflow NAV × 25`, giving exactly 72 ETH for one allocation and 144 ETH for two. Pending unpriced deposits do not fund this denominator. Smaller accounts wait for real settlement/recovery; this is a temporary pricing limitation, not a listing cap or a new minimum TVL.', '',
'## Actual pricing-order wealth effects', '',
'The current real-protocol fairness tests completed both holders’ full exits. Comparing keep-after-pricing with keep-before-pricing shows an economic transfer within the selected tolerance, not zero dilution:', '',
'| Authentic unresolved allocations | Incumbent wealth effect | Entrant wealth effect | Entrant full-roundtrip result, before wallet gas |', '|---|---:|---:|---:|']
log=(ROOT/'docs/receipts/completion-checks/final-fairness-callback.log').read_text()
a=re.findall(r'incumbent wealth effect.*: (-?\d+)',log);b=re.findall(r'entrant wealth effect.*: (-?\d+)',log);c=re.findall(r'entrant full exit result.*: (-?\d+)',log)
assert len(a)==len(b)==len(c)==2
for n,x,y,z in zip((1,2),a,b,c):lines.append(f'| {n} | {Decimal(int(x))/Decimal(E):+.18f} ETH | {Decimal(int(y))/Decimal(E):+.18f} ETH | {Decimal(int(z))/Decimal(E):+.18f} ETH |')
lines += ['', 'The holder sizes are 73 ETH incumbent / 1 ETH entrant for one allocation, and 146 ETH / 1 ETH for two. These are genuine previously priced incumbents; the entrant’s complete result remains negative before adding wallet gas. A passed accounting test is not a claim that the ordering transfer vanishes.', '',
'## Calibration limits and recommendation', '',
'Keep this candidate unsigned and the production app gate closed. Larger-capital sample medians do not justify imposing a new minimum TVL, and four draws do not establish reliable capacity at the hurdle. A second float needs another 0.2141275 ETH of funding and buys one finite replacement opportunity; it does not create permission or income.', '',
'The cold sixteen-kick Forge logger compares frame gas 2,520,956 with only the 125,000 sync base. Actual verified allowance is 125,000 + 16×120,000 = 2,045,000 gas, plus sixteen work fees; actual compensation 0.000729 ETH exceeds that frame’s gas cost 0.0005041912 ETH at 0.2 gwei. The printed base-only UNDERPAYS label is not the payment gap. This is a Forge frame diagnostic, not a billed sixteen-kick receipt. The productive UI shared-vault one-pack build used 1,903,900 billed gas; its allowance 1,875,000 gas was lower, but work fees made total pay exceed actual gas by 0.000038554917143700 ETH at 0.050002867 gwei. Calibration does not promise every operation stays profitable.', '',
'Billed authentic-VRF renewal remains unmeasured: inserting contracts changes the historical request blockhash required by the proof. Real authenticated-proof Forge renewal traces agree with the mirror, including conditional credit funding; coordinator impersonation/receiver replacement are retired. Production-image execution passed CI run 45427099371 on commit 49da810, including fresh-fork operation and actual separate containers sharing durable storage. Encrypted-keystore/hardware-wallet transport and live Fly operation remain untested; no disposable secrets were generated.', '',
'Evidence: [frozen run](formal-assessment.json), [103 billed campaign receipts](completion-calibration.json), [production-path rehearsal](unified-production-rehearsal.json), [genuine funding trace](../../sim/out/reconcile-renewal-funding-trace.jsonl), [current fairness log](completion-checks/final-fairness-callback.log), [fresh signed-budget reorg proof](completion-signed-budget-reorg.json), [productive UI setup](completion-productive-ui-setup.json), [production image CI](completion-image.json).', '',
'## Things that do not make sense', '',
'- Positive means and a high upper-middle statistic conceal three losses in four small-capital samples. They cannot support a passing depositor-return claim.',
'- A finite float does not fund unlimited renewal bursts, and a 25 bps tolerance does not imply small accounts can price through unresolved allocations.',
'- Synthetic compression places 2,834 requests inside blackout; those abstract stress returns cannot be presented as a feasible market schedule.',
'- Creator fees have accrued; creator wallet withdrawals and billed authentic-VRF renewal profit have not been demonstrated.', '']
(ROOT/'docs/receipts/completion-economics.md').write_text('\n'.join(lines))
print(json.dumps({'runs':len(rows),'cells':len(r['summary']),'completed':completed,'standard_small_median_bps':small['standard_median_return_bps'],'historical_small_upper_bps':small['median_return_bps'],'worst_small_bps':small['worst_return_bps'],'formal':r['formal']},indent=1))
