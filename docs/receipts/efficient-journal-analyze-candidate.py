"""Offline arithmetic and artifact checks for the completed approved batch."""
import hashlib,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
RESULTS=ROOT/'docs/receipts/efficient-journal-candidate-results.json'
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def num(x):return int(x,0) if isinstance(x,str) else x
r=json.loads(RESULTS.read_text())
b=json.loads((ROOT/'docs/receipts/efficient-journal-baseline-results.json').read_text())
a=json.loads((ROOT/'docs/receipts/efficient-journal-candidate-amendment.json').read_text())
assert r['status']=='passed' and r['global_phase']=='candidate_complete' and r['entry_restored']
assert r['approved_amendment_sha256']==digest(ROOT/'docs/receipts/efficient-journal-candidate-amendment.json')=='23aaa40e8dd8d8cdaac03ba3662bb83dc39b3ef64d5b17c8d5a5a7687af99089'
for p,h in a['source_sha256'].items():assert digest(ROOT/p)==h,p
assert r['phase_source_sha256']==a['source_sha256']
assert r['phase_artifact_templates_sha256']==a['artifact_templates_sha256']
assert r['broadcasts']==b['broadcasts']+len(r['actions'])+len(r['deployment']['transactions'])
missing=[x for x in r['actions'] if 'value_wei' not in x]
assert len(missing)==1 and missing[0]['label']=='existing owner-replaceable PolicyGreedy test role CREATE'
# The frozen CREATE helper supplies no native value; its distinct action schema omits value_wei.
assert r['external_value_wei']==b['external_value_wei']+sum(x.get('value_wei',0) for x in r['actions'])+10**16
assert r['broadcasts']<=540 and r['external_value_wei']<=32*10**18
assert r['funded']==b['funded'] and sum(r['funded'].values())==83*10**17
assert r['entry_actors']==r['restored_actors']==b['entry_actors'] and r['entry_head']['hash']==b['entry_head']['hash']
assert r['deployed_vault_normalized_runtime_matches']
rows=[]
for x in r['actions']:
 assert num(x['receipt']['status'])==1
 assert num(x['receipt']['gasUsed'])<=x['gas_limit']<=16777216
 if 'billed_gas' not in x:continue
 price=num(x['receipt']['effectiveGasPrice'])
 assert x['billed_gas']==num(x['receipt']['gasUsed'])
 assert x['actual_cost_wei']==x['billed_gas']*price
 assert x['keeper_paid_wei']==x['ordinary_keeper_offer_wei']==x['native_received_during_call_wei']
 if x['function'].startswith('sync'):
  assert x['after']['acquisitionCursor']-x['before']['acquisitionCursor']==x['records']
  for k in ['pendingDepositTotal','redemptionReserve','distributionReserve','claimableTotal','processingPool','lockedShares']:
   assert x['before'][k]==x['after'][k],(x['label'],k)
  assert x['before']['balance']-x['after']['balance']==x['keeper_paid_wei']
  assert x['before']['freeEth']-x['after']['freeEth']==x['keeper_paid_wei']
  ordinary=x['records']==128
  quote=(85000 if ordinary else 110000+(80000 if x['tail_mode']=='distribution' else 0))+22000*x['records']
  assert x['keeper_paid_wei']==quote*price*(10000+x['markup'])//10000
  key=(x['tail_mode'],x['records'],x['markup'],price)
  old=[v for v in b['actions'] if v.get('tail_mode')==key[0] and v.get('records')==key[1] and v.get('markup')==key[2] and num(v['receipt']['effectiveGasPrice'])==key[3]]
  assert len(old)==1
  rows.append({k:x[k] for k in ['label','records','markup','tail_mode','estimate','billed_gas','gas_limit','keeper_paid_wei','actual_cost_wei','ordinary_keeper_shared_gate_accepted','ordinary_keeper_exact_signed_estimate','ordinary_keeper_signed_minPay','ordinary_keeper_conservative_estimate_net_wei']} | {'price_wei':price,'actual_keeper_net_wei':x['keeper_paid_wei']-x['actual_cost_wei'],'signed_estimate_net_wei':x['keeper_paid_wei']-x['ordinary_keeper_exact_signed_estimate']*price,'baseline_billed_gas':old[0]['billed_gas'],'baseline_paid_wei':old[0]['keeper_paid_wei'],'baseline_gate_accepted':old[0]['ordinary_keeper_shared_gate_accepted']})
assert len(rows)==24
assert {(x['records'],x['markup'],x['price_wei']) for x in rows if x['tail_mode']=='holder'}=={(n,m,p) for n in [1,16,32,64,128] for m in [0,1000] for p in [200000000,500000000]}
assert all(x['actual_keeper_net_wei']>0 and x['signed_estimate_net_wei']>0 and x['ordinary_keeper_shared_gate_accepted'] for x in rows)
assert len(r['distribution_no_gain'])==2
for x in r['distribution_no_gain']:
 assert x['offer_wei']==0 and x['broadcast'] is False
out={'base_revision':r['base_revision'],'status':'passed','owner_answer':'Approve the amended local candidate batch','approved_amendment_sha256':r['approved_amendment_sha256'],'results_sha256':digest(RESULTS),'baseline_results_sha256':digest(ROOT/'docs/receipts/efficient-journal-baseline-results.json'),'cumulative_transactions':r['broadcasts'],'candidate_transactions':r['broadcasts']-b['broadcasts'],'cumulative_external_value_wei':r['external_value_wei'],'candidate_external_value_wei':r['external_value_wei']-b['external_value_wei'],'entry_restored':True,'matrix':rows,'no_gain_cases':2,'limits':['Candidate has one Active position; baseline had40. This is not a matched-state estimate of source-only gas savings.','Expired/refunded foreign records only; successful foreign receipt gap remains.','Operator calibration sends use minPay0; actual ordinary preflight, signed80percent-minPay estimates and shared default gate are separately recorded.','Positive observed bills/net/gates do not establish universal keeper profitability, races, combined own maximum, holder returns or release acceptance.','Original Q360 full-holder standalone receipts remain on the named baseline source; candidate did not repeat that fixture.']}
(ROOT/'docs/receipts/efficient-journal-candidate-summary.json').write_text(json.dumps(out,indent=2)+'\n')
print(json.dumps({k:v for k,v in out.items() if k!='matrix'},indent=2))
for x in rows:
 if x['markup']==0:print(x['label'],x['estimate'],x['billed_gas'],x['keeper_paid_wei'],x['actual_keeper_net_wei'],x['ordinary_keeper_shared_gate_accepted'])
