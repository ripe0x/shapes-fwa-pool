"""Read-only source/runtime identity check at PackVault's pinned fork block."""
import hashlib
import json
import subprocess
import urllib.request
from pathlib import Path

RPC = 'https://mainnet.gateway.tenderly.co'
BLOCK = '26424971'
CONTRACTS = {
    'FWA V2': ('0x958C41181182e76F221331b2755b77D9e1426A98', 'src/FWAV2/FWAV2.sol'),
    'Shapes': ('0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0', 'src/Shapes.sol'),
    'ShapePacks': ('0xf21514B090Da7dF4390803497d6ae673801E5cA7', 'src/ShapePacks.sol'),
    'FWA rewards': ('0xA54b44C7a894AA19C49734A753D01f9B8C5f6516', 'src/FWAV2/FWAV2Rewards.sol'),
    'FWA token': ('0xa0Df17B5aC76ABaBA36E1450E2cbCd18A620C845', 'src/FWAToken.sol'),
    'FWA floor oracle': ('0xaA4D9009a4664604b57644bF13e447E9036727DC', 'src/FWAV2/CollectionFloorOracle.sol'),
}
rows = []
for name, (address, preferred) in CONTRACTS.items():
    url = f'https://sourcify.dev/server/v2/contract/1/{address}?fields=sources,runtimeBytecode'
    with urllib.request.urlopen(url, timeout=20) as response:
        record = json.load(response)
    verified = record['runtimeBytecode']['onchainBytecode']
    deployed = subprocess.run(
        ['cast', 'code', address, '--block', BLOCK, '--rpc-url', RPC],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    sources = record['sources']
    source_path = preferred if preferred in sources else next(
        (p for p in sources if p.endswith(preferred.rsplit('/', 1)[-1])), None
    )
    assert source_path is not None, (name, list(sources))
    assert deployed == verified, name
    row = {
        'name': name, 'chain_id': 1, 'block': int(BLOCK), 'address': address,
        'sourcify_url': url, 'runtime_match': record['runtimeMatch'],
        'deployed_equals_sourcify_onchain_bytecode': True,
        'runtime_sha256': hashlib.sha256(bytes.fromhex(deployed.removeprefix('0x'))).hexdigest(),
        'runtime_bytes': len(deployed.removeprefix('0x')) // 2,
        'source_path': source_path,
        'source_sha256': hashlib.sha256(sources[source_path]['content'].encode()).hexdigest(),
    }
    assert row['runtime_match'] == 'match', name
    rows.append(row)
out = Path(__file__).with_name('external-source-match.json')
out.write_text(json.dumps({'rpc': RPC, 'contracts': rows}, indent=2) + '\n')
for row in rows:
    print(row['name'], row['address'], row['runtime_sha256'], 'MATCH')
