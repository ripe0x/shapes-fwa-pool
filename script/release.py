#!/usr/bin/env python3
"""Release identity for PackVault and PackManagerFactory: one manifest binds what was tested to what deploys.

  script/release.py manifest                    write deploy/release-manifest.json (after forge build)
  script/release.py check <values>              sources, build, values, keeper and evidence match it
  script/release.py check <values> --broadcast  also the owner's signature on the acceptance package
  script/release.py postflight <vault> <values> [owner] [factory]  read deployed contracts back against manifest and values
  script/release.py keeper-config <vault> <values> [owner]  postflight, then set VAULT in both Fly configs

The owner accepts a release by signing the sha256 of docs/release/acceptance.json (which names the
manifest hash) with the key in deploy/allowed_signers, namespace packvault-release:
  printf %s <sha256> | ssh-keygen -Y sign -f <key> -n packvault-release > deploy/release-acceptance.sig
RPC_URL overrides the Tenderly mainnet gateway for postflight.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "keeper"))
from config import PARAMS_T, PARAM_FIELDS, GAS_FIELDS, decode_params, configuration_hash
MANIFEST = ROOT / "deploy/release-manifest.json"
ACCEPTANCE = ROOT / "docs/release/acceptance.json"
SIGNATURE = ROOT / "deploy/release-acceptance.sig"
SIGNERS = ROOT / "deploy/allowed_signers"
RPC = os.environ.get("RPC_URL", "https://mainnet.gateway.tenderly.co")
CODE_LIMIT = 24_576
CREATE2_FACTORY = "0x4e59b44847b379578588920cA78FbF26c0B4956C"
CONTRACTS = {"PackVault": "src/PackVault.sol", "PackManager": "src/PackManager.sol",
             "PackManagerFactory": "src/PackManagerFactory.sol", "StrategyLib": "src/StrategyLib.sol",
             "VaultLib": "src/VaultLib.sol", "ScanLib": "src/ScanLib.sol"}
# Linked libraries in dependency order: VaultLib links ScanLib, StrategyLib links VaultLib; both
# accounts (PackVault, the PackManager implementation) link VaultLib and StrategyLib.
LIBRARIES = ["ScanLib", "VaultLib", "StrategyLib"]
KEEPER = ["keeper/Dockerfile", "keeper/entrypoint.sh", "keeper/requirements.txt", "keeper/keeper.py",
          "keeper/policy.py", "keeper/config.py", "keeper/tx.py", "keeper/index.py", "fly.keeper-primary.toml", "fly.keeper-backup.toml"]
VALUES = ["deploy/mainnet.json", "deploy/manager.json", "deploy/mint-fee-observation.json", "deploy/existing-main-readback.json"]
# The acceptance package names this manifest, so it is not listed here (no cycle).
EVIDENCE = ["docs/receipts/formal-assessment.json", "docs/receipts/completion-calibration.json",
            "docs/receipts/unified-production-rehearsal.json",
            "docs/receipts/completion-verification.md", "docs/receipts/completion-economics.md",
            "docs/receipts/completion-independent-review.md", "docs/receipts/completion-app.json",
            "docs/receipts/completion-checks/input-manifest.json", "deploy/unsigned-cutover.json",
            "deploy/keeper-unsigned.json", "docs/receipts/completion-signed-budget-reorg.json",
            "docs/receipts/completion-image.json",
            "asset-flow.json"]


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sources():
    files = set(git("ls-files", "src", "script", "foundry.toml", "remappings.txt").split())
    files.update(str(p.relative_to(ROOT)) for folder in ("src", "script") for p in (ROOT / folder).rglob("*") if p.is_file() and p.suffix in (".sol", ".py", ".sh"))
    return {f: sha(f) for f in files if f != "script/release.py" and (ROOT / f).exists()} | {"script/release.py": sha("script/release.py")}


def artifact(name):
    return json.loads((ROOT / f"out/{Path(CONTRACTS[name]).name}/{name}.json").read_text())



# Launch checks are independent of the values/manifest being reviewed. They constrain this
# deployment package, not an account owner's later recipe or economic settings.
LAUNCH_UNITS = 3
LAUNCH_PACK_MASK = 1 << LAUNCH_UNITS
MAIN_DEPENDENCIES = {
    "fwa": "0x958C41181182e76F221331b2755b77D9e1426A98",
    "shapes": "0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0",
    "packs": "0xf21514B090Da7dF4390803497d6ae673801E5cA7",
}
PARAM_ABI_ALIASES = {
    "gasCeilingWei": "gasCeiling", "essentialCeilingWei": "essentialCeiling",
    "maxTipWei": "maxTip", "workFeeWei": "workFee", "routineCapWei": "routineCap",
    "routineRatePerDayWei": "routineRate", "essentialCapWei": "essentialCap",
    "essentialRatePerDayWei": "essentialRate", "reserveWei": "reserve", "tvlCapWei": "tvlCap",
    "acceptedMintFeeWei": "acceptedMintFee", "minDepositWei": "minDeposit",
    "minDistributionWei": "minDistribution",
}


def _exact_keys(value, expected, label):
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    missing, extra = set(expected) - value.keys(), value.keys() - set(expected)
    if missing or extra:
        raise ValueError(f"{label} keys: missing {sorted(missing)}, unexpected {sorted(extra)}")


def _unsigned(value, bits, label):
    if type(value) is not int or not 0 <= value < 1 << bits:
        raise ValueError(f"{label} must be an unsigned {bits}-bit JSON integer")


def validate_launch_values(values, *, manager=False):
    """Validate complete launch inputs without any RPC, manifest trust or numerical defaults."""
    if not isinstance(values, dict):
        raise ValueError("launch values must be an object")
    required = {key for key, _ in PARAM_FIELDS} | {"gasSchedule", "expectedMintFeeWei"}
    if not manager:
        required |= set(MAIN_DEPENDENCIES) | {"owner", "seedWei"}
    optional = {"comment"} if "comment" in values else set()
    _exact_keys(values, required | optional, "manager launch values" if manager else "main launch values")
    for key, kind in PARAM_FIELDS:
        _unsigned(values[key], int(kind.removeprefix("uint")), key)
    _exact_keys(values["gasSchedule"], GAS_FIELDS, "gasSchedule")
    for key in GAS_FIELDS:
        _unsigned(values["gasSchedule"][key], 32, f"gasSchedule.{key}")
    _unsigned(values["expectedMintFeeWei"], 256, "expectedMintFeeWei")
    if values["packUnitsMask"] != LAUNCH_PACK_MASK:
        raise ValueError(f"launch requires mask {LAUNCH_PACK_MASK} (units {LAUNCH_UNITS}), not {values['packUnitsMask']}")
    if values["expectedMintFeeWei"] > values["acceptedMintFeeWei"]:
        raise ValueError("reviewed launch mint fee exceeds the explicitly accepted maximum")
    if not manager:
        for key, expected in MAIN_DEPENDENCIES.items():
            if not isinstance(values[key], str) or values[key].lower() != expected.lower():
                raise ValueError(f"launch {key} must be the selected main-pool dependency {expected}")
        if not isinstance(values["owner"], str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", values["owner"]) or int(values["owner"], 16) == 0:
            raise ValueError("launch owner must be a nonzero address supplied by the values file")
        _unsigned(values["seedWei"], 256, "seedWei")


def _abi_entry(abi, kind, name=None):
    matches = [entry for entry in abi if entry.get("type") == kind and (name is None or entry.get("name") == name)]
    if len(matches) != 1:
        raise ValueError(f"compiled ABI must contain exactly one {name or kind}")
    return matches[0]


def _abi_fields(fields):
    return [(field.get("name"), field.get("type")) for field in fields]


def _validate_params_abi(component, label):
    expected = [(PARAM_ABI_ALIASES.get(key, key), kind) for key, kind in PARAM_FIELDS] + [("gasSchedule", "tuple")]
    fields = component.get("components", [])
    if component.get("type") != "tuple" or _abi_fields(fields) != expected:
        raise ValueError(f"{label} Params names/types/order differ from keeper.config.PARAM_FIELDS aliases")
    gas = fields[-1].get("components", [])
    if len(GAS_FIELDS) != 28 or _abi_fields(gas) != [(key, "uint32") for key in GAS_FIELDS]:
        raise ValueError(f"{label} GasSchedule names/types/order differ from the complete 28 keeper.config.GAS_FIELDS")


def validate_compiled_launch_abi(vault_abi, factory_abi):
    """Compare the real compiler's named schema with offchain encoding and deployment entrypoints."""
    getter = _abi_entry(vault_abi, "function", "getParams")
    if getter.get("inputs") != [] or len(getter.get("outputs", [])) != 1:
        raise ValueError("compiled getParams must return one Params tuple without arguments")
    _validate_params_abi(getter["outputs"][0], "getParams")
    constructor = _abi_entry(vault_abi, "constructor")
    if _abi_fields(constructor.get("inputs", [])) != [("fwa_", "address"), ("shapes_", "address"),
            ("packs_", "address"), ("owner_", "address"), ("initial", "tuple"), ("expected", "bytes32")]:
        raise ValueError("compiled PackVault constructor must have six guarded inputs, without a policy")
    _validate_params_abi(constructor["inputs"][4], "PackVault constructor")
    create = _abi_entry(factory_abi, "function", "create")
    if _abi_fields(create.get("inputs", [])) != [("owner", "address"), ("p", "tuple"), ("expected", "bytes32")]:
        raise ValueError("compiled factory create must be only (owner, p, expected), without a policy")
    _validate_params_abi(create["inputs"][1], "factory create")
    if _abi_fields(_abi_entry(factory_abi, "constructor").get("inputs", [])) != [
            ("fwa", "address"), ("shapes", "address"), ("packs", "address")]:
        raise ValueError("compiled factory constructor must have only the three main dependencies")


def _launch_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate launch JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def validate_launch_inputs(values=None):
    """Fail before manifest generation/check or any postflight read if launch identity/schema drift."""
    validate_launch_values(_launch_json(values or ROOT / "deploy/mainnet.json"))
    validate_launch_values(_launch_json(ROOT / "deploy/manager.json"), manager=True)
    validate_compiled_launch_abi(artifact("PackVault")["abi"], artifact("PackManagerFactory")["abi"])


def normalized(code, link_refs=(), immutables=()):
    """Bytes with library links and immutables zeroed: the identity that does not depend on where
    or with which constructor arguments a contract is deployed."""
    b = bytearray.fromhex(re.sub(r"__\$[0-9a-f]{34}\$__", "0" * 40, code.removeprefix("0x")))
    for refs in link_refs:
        for r in refs:
            b[r["start"]:r["start"] + r["length"]] = bytes(r["length"])
    for refs in immutables:
        for r in refs:
            b[r["start"]:r["start"] + r["length"]] = bytes(r["length"])
    return bytes(b)


def links(bytecode):
    return [r for lib in bytecode.get("linkReferences", {}).values() for r in lib.values()]


def build():
    out = {}
    for name in CONTRACTS:
        a = artifact(name)
        runtime = normalized(a["deployedBytecode"]["object"], links(a["deployedBytecode"]),
                             a["deployedBytecode"].get("immutableReferences", {}).values())
        init = normalized(a["bytecode"]["object"], links(a["bytecode"]))
        out[name] = dict(runtime_bytes=len(runtime), runtime_sha256=hashlib.sha256(runtime).hexdigest(),
                         initcode_sha256=hashlib.sha256(init).hexdigest())
    from eth_utils import keccak, to_checksum_address
    create2 = lambda init: keccak(b"\xff" + bytes.fromhex(CREATE2_FACTORY[2:]) + bytes(32) + keccak(init))[12:]  # noqa: E731
    # forge script deploys each library through the factory with salt 0, linking earlier ones.
    addresses = {}
    for name in LIBRARIES:
        code = artifact(name)["bytecode"]
        addresses[name] = create2(linked(code["object"], code.get("linkReferences", {}), addresses))
        out[name]["create2_address"] = to_checksum_address(addresses[name])
    return out


def linked(obj, refs, addresses):
    """Creation or runtime bytes with every library reference set to its address."""
    code = bytearray.fromhex(re.sub(r"__\$[0-9a-f]{34}\$__", "0" * 40, obj.removeprefix("0x")))
    for libs in refs.values():
        for name, rs in libs.items():
            assert name in addresses, f"{name} must be deployed before what links it"
            for r in rs:
                code[r["start"]:r["start"] + r["length"]] = addresses[name]
    return bytes(code)


def toolchain():
    toml = (ROOT / "foundry.toml").read_text()
    pick = lambda k: re.search(rf"^{k}\s*=\s*(.+)$", toml, re.M).group(1).strip().strip('"')  # noqa: E731
    docker = (ROOT / "keeper/Dockerfile").read_text()
    return dict(solc=pick("solc_version"), evm=pick("evm_version"), optimizer_runs=int(pick("optimizer_runs")),
                via_ir=pick("via_ir") == "true", bytecode_hash=pick("bytecode_hash"),
                lib_tree=git("rev-parse", "HEAD:lib"),
                keeper_image_foundry=re.search(r"foundryup --install (\S+)", docker).group(1))


def manifest():
    validate_launch_inputs()
    m = dict(name="PackVault and PackManagerFactory mainnet", sources=sources(), toolchain=toolchain(), build=build(),
             deployment_values="deploy/mainnet.json", values={v: sha(v) for v in VALUES},
             keeper={k: sha(k) for k in KEEPER},
             evidence={e: sha(e) for e in EVIDENCE if (ROOT / e).exists()})
    for name, b in m["build"].items():
        assert b["runtime_bytes"] <= CODE_LIMIT, f"{name} runtime {b['runtime_bytes']} exceeds EIP-170"
    MANIFEST.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} sha256 {sha(MANIFEST.relative_to(ROOT))}")


def problems(values, broadcast):
    try:
        validate_launch_inputs(values)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return [f"launch inputs invalid: {error}"]
    if not MANIFEST.exists():
        return ["no deploy/release-manifest.json"]
    m = json.loads(MANIFEST.read_text())
    out = []
    dirty = git("status", "--porcelain", "--", "src", "script", "deploy", "foundry.toml", "remappings.txt", "lib", "keeper")
    if dirty:
        out.append("uncommitted release inputs:\n" + dirty)
    for key, now in (("sources", sources()), ("toolchain", toolchain()), ("build", build()),
                     ("keeper", {k: sha(k) for k in KEEPER}), ("values", {v: sha(v) for v in VALUES}),
                     ("evidence", {e: sha(e) for e in m["evidence"] if (ROOT / e).exists()})):
        if now != m[key]:
            changed = sorted(k for k in set(now) | set(m[key]) if now.get(k) != m[key].get(k))
            out.append(f"{key} differs from the manifest: {changed}")
    if os.path.relpath(Path(values).resolve(), ROOT) != m["deployment_values"]:
        out.append(f"values {values} are not the release's {m['deployment_values']}")
    if broadcast:
        if not ACCEPTANCE.exists():
            out.append("no docs/release/acceptance.json")
        elif json.loads(ACCEPTANCE.read_text()).get("manifest_sha256") != sha(MANIFEST.relative_to(ROOT)):
            out.append("acceptance package names a different manifest")
        elif not SIGNATURE.exists():
            out.append("no owner signature: deploy/release-acceptance.sig")
        else:
            r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", SIGNERS, "-I", "owner", "-n", "packvault-release",
                                "-s", SIGNATURE], input=sha(ACCEPTANCE.relative_to(ROOT)).encode(), capture_output=True)
            if r.returncode:
                out.append("owner signature does not verify over the acceptance package")
    return out


def cast(*args):
    return subprocess.check_output(["cast", *map(str, args), "--rpc-url", RPC], text=True).strip()


def first(raw):
    return raw.split()[0]


def postflight(vault, values, owner=None, factory=None):
    """Read the deployed vault, factory, implementation and libraries back; stop on any difference."""
    validate_launch_inputs(values)
    m, v = json.loads(MANIFEST.read_text()), json.loads(Path(values).read_text())
    fail = []
    check = lambda ok, what: ok or fail.append(what)  # noqa: E731
    libs = {name: m["build"][name]["create2_address"] for name in LIBRARIES}
    deployed = [("PackVault", vault)] + [(n, a) for n, a in libs.items()]
    if factory:
        implementation = cast("call", factory, "implementation()(address)")
        deployed += [("PackManagerFactory", factory), ("PackManager", implementation)]
        check(cast("call", implementation, "factory()(address)").lower() == factory.lower(), "implementation factory")
        check(int(cast("call", implementation, "owner()(address)"), 16) == 0, "implementation has an owner")
        for k, sig in (("fwa", "fwa()(address)"), ("shapes", "shapes()(address)"), ("packs", "packs()(address)")):
            check(cast("call", implementation, sig).lower() == v[k].lower(), f"implementation {k}")
    for name, address in deployed:
        a = artifact(name)
        code = cast("code", address)
        runtime = normalized(code, links(a["deployedBytecode"]), a["deployedBytecode"].get("immutableReferences", {}).values())
        check(hashlib.sha256(runtime).hexdigest() == m["build"][name]["runtime_sha256"], f"{name} runtime at {address}")
        # Every linked call must reach the manifest's library, not another one.
        onchain = bytes.fromhex(code[2:])
        for libs_ in a["deployedBytecode"].get("linkReferences", {}).values():
            for lib, rs in libs_.items():
                for r in rs:
                    check(onchain[r["start"]:r["start"] + 20].hex() == libs[lib][2:].lower(), f"{name} links another {lib}")
    owner = owner or v["owner"]  # after a D76 handover, pass the current owner
    check(cast("call", vault, "owner()(address)").lower() == owner.lower(), "owner")
    for k, sig in (("fwa", "fwa()(address)"), ("shapes", "shapes()(address)"), ("packs", "packs()(address)")):
        check(cast("call", vault, sig).lower() == v[k].lower(), k)
    got = decode_params(cast("call", vault, f"getParams()({PARAMS_T})"))
    expected = {k: int(v[k]) for k, _ in PARAM_FIELDS} | {"gasSchedule": {k: int(v['gasSchedule'][k]) for k in GAS_FIELDS}}
    check(got == expected, f"params {got}")
    mint_fee = int(first(cast("call", v['shapes'], "mintFee()(uint256)")))
    check(cast('call', vault, 'configurationHash()(bytes32)').lower() == configuration_hash(v, mint_fee).lower(), 'configuration hash')
    check(mint_fee <= v['acceptedMintFeeWei'], 'live mint fee exceeds accepted maximum')
    for key, expected_address in (("rewards", cast('call', v['fwa'], 'rewards()(address)')),
                                  ("token", cast('call', v['fwa'], 'token()(address)'))):
        check(cast('code', expected_address) not in ('', '0x'), f'FWA {key} dependency missing')
        check(cast('call', vault, key + '()(address)').lower() == expected_address.lower(), f'vault {key} immutable')
        if factory:
            check(cast('call', implementation, key + '()(address)').lower() == expected_address.lower(), f'implementation {key} immutable')
    budget = [int(first(x)) for x in cast("call", vault, "budget()(uint256,uint256)").splitlines()]
    check(budget[0] <= v["routineCapWei"] and budget[1] <= v["essentialCapWei"], "budgets above caps")
    dead = first(cast("call", vault, "DEAD_SHARES()(uint256)"))
    check(first(cast("call", vault, "sharesOf(address)(uint256)", "0x000000000000000000000000000000000000dEaD")) == dead,
          "seed shares")
    for flag in ("windingDown", "depositsPaused", "listingPaused"):
        check(cast("call", vault, f"{flag}()(bool)") == "false", flag)
    check(int(first(cast("balance", vault))) >= v["seedWei"], "seed balance")
    balances = {name: int(first(cast('call', vault, f'{name}()(uint256)'))) for name in
                ('pendingDepositTotal', 'redemptionReserve', 'distributionReserve', 'claimableTotal', 'processingPool', 'chargeRefundReserve')}
    balances['cash'] = int(first(cast('balance', vault)))
    check(balances['cash'] >= sum(value for key, value in balances.items() if key != 'cash'), 'protected balances not covered')
    print('account balances and claims: ' + json.dumps(balances, sort_keys=True))
    if fail:
        sys.exit("postflight FAILED: " + "; ".join(fail))
    print(f"postflight passed: {vault} libraries {libs} owner {owner}"
          + (f" factory {factory}" if factory else " (factory not checked)"))
    print("verification commands (Etherscan; ETHERSCAN_API_KEY from your environment):")
    scan, lib, strategy = libs["ScanLib"], libs["VaultLib"], libs["StrategyLib"]
    accounts = f"--libraries src/ScanLib.sol:ScanLib:{scan} --libraries src/VaultLib.sol:VaultLib:{lib} --libraries src/StrategyLib.sol:StrategyLib:{strategy}"
    print(f"  forge verify-contract {scan} src/ScanLib.sol:ScanLib --chain mainnet --watch")
    print(f"  forge verify-contract {lib} src/VaultLib.sol:VaultLib --chain mainnet "
          f"--libraries src/ScanLib.sol:ScanLib:{scan} --watch")
    print(f"  forge verify-contract {strategy} src/StrategyLib.sol:StrategyLib --chain mainnet "
          f"--libraries src/VaultLib.sol:VaultLib:{lib} --watch")
    print(f"  forge verify-contract {vault} src/PackVault.sol:PackVault --chain mainnet --guess-constructor-args "
          f"{accounts} --watch")
    if factory:
        print(f"  forge verify-contract {factory} src/PackManagerFactory.sol:PackManagerFactory --chain mainnet "
              f"--guess-constructor-args {accounts} --watch")
        print(f"  forge verify-contract {implementation} src/PackManager.sol:PackManager --chain mainnet "
              f"--guess-constructor-args {accounts} --watch")


def keeper_config(vault, values, owner=None):
    postflight(vault, values, owner)
    for name in ("fly.keeper-primary.toml", "fly.keeper-backup.toml"):
        path = ROOT / name
        text, n = re.subn(r'^  VAULT = "0x[0-9a-fA-F]{40}"', f'  VAULT = "{vault}"', path.read_text(), flags=re.M)
        assert n == 1, f"{name}: VAULT line not found"
        path.write_text(text)
        print(f"{name}: VAULT = {vault}")


def calibrate(actions, output='docs/receipts/completion-calibration.json'):
    """Collect actual billed receipts from the production-path local batch, without simulations."""
    records={}
    prior_candidates=set()
    current_sources={str(p.relative_to(ROOT)):sha(p.relative_to(ROOT)) for p in sorted((ROOT/'src').rglob('*.sol'))}
    integer=lambda v:int(v,16) if isinstance(v,str) and v.startswith('0x') else int(v)
    for line in Path(actions).read_text().splitlines():
        action=json.loads(line);receipt=action.get('receipt')
        recorded=action.get('vault_context',{}).get('source_sha256')
        if recorded is not None and recorded != current_sources:
            prior_candidates.add(hashlib.sha256(json.dumps(recorded,sort_keys=True).encode()).hexdigest())
            continue  # Prior failed candidate receipts remain preserved in the immutable input ledger.
        if receipt and recorded is None:
            raise ValueError('unbound receipt cannot calibrate the current candidate')
        if receipt:
            h=receipt['transactionHash']
            records[h]=dict(operation=action['function'].split('(')[0],hash=h,gasUsed=integer(receipt['gasUsed']),
                effectiveGasPrice=integer(receipt['effectiveGasPrice']),status=integer(receipt['status']),valueWei=action.get('value_wei',0))
        for row in action.get('tx_state',{}).get('counted',[]):
            if not row.get('reorged'):
                records[row['hash']]=dict(operation=row.get('function',row['label']),hash=row['hash'],gasUsed=row['gas_used'],
                    effectiveGasPrice=row['price'],status=row['status'],keeperPayWei=row['pay'],
                    valueWei=row.get('transaction_value_wei',0),contributionWei=row.get('checkpoint_contributed_wei',0))
    if not records:
        raise ValueError('no actual transaction receipts in the batch actions')
    data=dict(method='Billed isolated-fork receipts; prospective costs remain estimates',
        source_sha256=current_sources,
        actions_sha256=hashlib.sha256(Path(actions).read_bytes()).hexdigest(),excluded_prior_candidate_source_hashes=sorted(prior_candidates),transactions=list(records.values()))
    (ROOT/output).write_text(json.dumps(data,indent=1)+'\n')
    print(f'wrote {output}: {len(records)} actual billed transactions')



def existing_readback():
    """Refresh the existing MAIN deployment at one latest public-mainnet block; send nothing."""
    path=ROOT/'deploy/existing-main-readback.json';previous=json.loads(path.read_text())
    rpc='https://mainnet.gateway.tenderly.co'
    def run(*args):
        return subprocess.run(['cast',*map(str,args),'--rpc-url',rpc],capture_output=True,text=True)
    header=json.loads(run('block','latest','--json').stdout);header=header.get('data',header)
    block=int(header['number'],16);vault=previous['address'];factory=previous['factory']['address']
    def read(to,sig,*args):
        result=run('call',to,sig,*args,'--block',block)
        return dict(supported=result.returncode==0,result=result.stdout.strip() if result.returncode==0 else None,
                    error=result.stderr.strip()[-250:] if result.returncode else None)
    views={'owner':'owner()(address)','fwa':'fwa()(address)','shapes':'shapes()(address)','packs':'packs()(address)',
           'policy':'keeperPolicy()(address)','windingDown':'windingDown()(bool)',
           'totals':'totals()(uint256,uint256,uint256,uint256,uint256,uint256)'}
    for name in ('pendingDepositTotal','lockedShares','redemptionReserve','distributionReserve','claimableTotal',
                 'processingPool','chargeRefundReserve','totalShares','openListingCount','idlePackCount','recoveryPackCount'):
        views[name]=name+'()(uint256)'
    code=run('code',vault,'--block',block).stdout.strip()
    result=dict(address=vault,block=block,blockHash=header['hash'],timestamp=int(header['timestamp'],16),rpc=rpc,
        reads={name:read(vault,sig) for name,sig in views.items()},balance=run('balance',vault,'--block',block).stdout.strip(),
        runtimeSha256=hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(),
        factory=dict(address=factory,source=previous['factory']['source'],reads={name:read(factory,sig) for name,sig in
                     [('managerCount','managerCount()(uint256)'),('implementation','implementation()(address)'),('policy','policy()(address)')]}))
    result['reads']['feeCredit']=read(result['reads']['fwa']['result'],'feeCredit(address)(uint256)',vault)
    result['liveMintFee']=read(result['reads']['shapes']['result'],'mintFee()(uint256)')
    path.write_text(json.dumps(result,indent=1)+'\n')
    print(f'existing MAIN deployment read only at block {block}; preserved vault/factory and all unsupported selectors')



def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "existing-readback":
        existing_readback()
    elif cmd == "calibrate" and args:
        calibrate(args[0])
    elif cmd == "manifest":
        manifest()
    elif cmd == "check" and args:
        found = problems(args[0], "--broadcast" in args)
        for p in found:
            print("release check:", p)
        if found:
            sys.exit(1)
        print("release check passed" + (" with owner signature" if "--broadcast" in args else " (no signature checked)"))
    elif cmd == "postflight" and len(args) in (2, 3, 4):
        postflight(*args)
    elif cmd == "keeper-config" and len(args) in (2, 3):
        keeper_config(*args)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
