"""V1 canary envelope versus pinned Anvil billed gas; all amounts ETH, absent budget/free binding."""
import json
from pathlib import Path
root=Path(__file__).resolve().parents[2]
rows=json.loads((root/'sim/out/gas-quotes.json').read_text())['rows']
gas={r['label']:r['gas'] for r in rows}
ops=[
 ('checkpoint 0',180_000,1,gas['checkpoint, 0 positions, 1 deposit']),
 ('restock 1/1 mint',2_680_000,1,gas['restock 1 (1 mint, no loose)']),
 ('restock 1/0 mint',480_000,1,gas['restock 1 (0 mints, from loose)']),
 ('list 1',785_000,1,gas['list 1']),
 ('sync 1',150_000,1,gas['sync 1 (kicked)']),
 ('unlist 1',410_000,1,gas['unlist 1']),
 ('liquidate 1',225_000,1,gas['liquidate 1 pack']),
 ('harvest 1',95_000,0,None),
 ('activate 1',500_000,1,None),
]
print('operation,billed_gas,basefee_gwei,quote_wei,billed_cost_wei,net_wei')
for name,qgas,units,billed in ops:
 for base in (0.15,0.5,1.0,1.5,5.0):
  price=round((base+0.05)*1e9)
  pay=qgas*min(price,500_000_000)+units*20_000_000_000_000
  cost='' if billed is None else billed*price
  net='' if billed is None else pay-cost
  print(f'{name},{billed if billed is not None else "unmeasured"},{base},{pay},{cost},{net}')
