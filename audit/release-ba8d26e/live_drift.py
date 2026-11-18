"""Read-only pinned-versus-current protocol state via Tenderly's public mainnet RPC."""
import json
import subprocess
from pathlib import Path
RPC = 'https://mainnet.gateway.tenderly.co'
FWA = '0x958C41181182e76F221331b2755b77D9e1426A98'
PACKS = '0xf21514B090Da7dF4390803497d6ae673801E5cA7'
def cast(*args):
    return subprocess.run(['cast', *args, '--rpc-url', RPC], check=True, capture_output=True, text=True).stdout.strip()
latest = cast('block-number')
functions = [
    ('floor_oracle', 'floorOracle()(address)', []),
    ('rewards', 'rewards()(address)', []),
    ('token', 'token()(address)', []),
    ('owner_acquisition_fee_bps', 'ownerAcquisitionFeeBps()(uint256)', []),
    ('owner_settlement_fee_bps', 'ownerSettlementFeeBps()(uint256)', []),
    ('top_listing_share_bps', 'topListingShareBps()(uint256)', []),
    ('unsettled_acquisitions', 'unsettledAcquisitionCount()(uint256)', []),
    ('weighted_backing_total', 'weightedBackingTotal()(uint256)', []),
    ('total_weight', 'totalWeight()(uint256)', []),
    ('acquisition_fee_wei', 'acquisitionFee()(uint256)', []),
    ('packs_can_deposit', 'canDeposit(address)(bool)', [PACKS]),
]
rows = {}
for block in ('26424971', latest):
    rows[block] = {}
    for name, sig, args in functions:
        rows[block][name] = cast('call', FWA, sig, *args, '--block', block)
out={'rpc':RPC, 'pinned_block':26424971, 'latest_block':int(latest), 'states':rows}
Path(__file__).with_name('live-drift.json').write_text(json.dumps(out, indent=2)+'\n')
for name, _, _ in functions:
    old,new=rows['26424971'][name],rows[latest][name]
    print(name,old,'=>',new, 'CHANGED' if old!=new else 'same')
