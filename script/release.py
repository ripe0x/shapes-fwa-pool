#!/usr/bin/env python3
"""Release identity for PackVault and PackManagerFactory: one manifest binds what was tested to what deploys.

  script/release.py manifest                    write deploy/release-manifest.json (after forge build)
  script/release.py check <values>              sources, build, values, keeper and evidence match it
  script/release.py check <values> --broadcast  also the owner's signature on the acceptance package
  script/release.py postflight <vault> <values> [owner] [factory]  read deployed contracts back against manifest and values
  script/release.py keeper-config <vault> <values> [owner]  postflight, then set VAULT in both Fly configs
  script/release.py manifest|check <values> --target manager  separate manager-only identity/approval
  script/release.py postflight-manager <factory> <values> [manager owner fundingWei]
  script/release.py manager-package <Forge mainnet dry-run.json>  write unsigned manager deployment data
  script/release.py manager-create <factory> <owner> <fundingWei> [design]  print unsigned creation template;
      design is PackAccount.design (byte u = packs of u x 0.01 ETH) and sets packUnitsMask to its sizes

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
from config import PARAMS_T, PARAM_FIELDS, GAS_FIELDS, decode_params, configuration_hash, params_values, tuple_arg
MANIFEST = ROOT / "deploy/release-manifest.json"
ACCEPTANCE = ROOT / "docs/release/acceptance.json"
SIGNATURE = ROOT / "deploy/release-acceptance.sig"
SIGNERS = ROOT / "deploy/allowed_signers"
MANAGER_MANIFEST = ROOT / "deploy/manager-release-manifest.json"
MANAGER_ACCEPTANCE = ROOT / "docs/release/manager-acceptance.json"
MANAGER_SIGNATURE = ROOT / "deploy/manager-release-acceptance.sig"
RPC = os.environ.get("RPC_URL", "https://mainnet.gateway.tenderly.co")
READ_BLOCK = None
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
MANAGER_VALUES = ["deploy/manager-factory.json", "deploy/manager.json", "deploy/manager-mint-fee-observation.json",
                  "deploy/manager-existing-main-readback.json"]
# Historical UI/container compatibility only; these are not current-source financial proof.
MANAGER_COMPATIBILITY_EVIDENCE = ["docs/receipts/manager-ui.json", "docs/receipts/manager-image.json"]
MANAGER_EVIDENCE = ["docs/receipts/manager-r2-closeout.json", "docs/receipts/manager-r2-cost-calibration.json",
                    "docs/receipts/manager-r2-live-observation.json", "docs/receipts/manager-r2-min-backing-continuity.json",
                    "docs/receipts/manager-funded-reconciliation.json", "docs/receipts/manager-funded-verification.md",
                    "docs/receipts/manager-funded-checks/input-manifest.json",
                    "docs/receipts/manager-monte-carlo.md", "docs/receipts/manager-monte-carlo-independent-review.md",
                    "sim/out/manager-monte-carlo-funded/manifest.json", "sim/out/manager-monte-carlo-funded/summary.json",
                    "sim/out/manager-standard-funded/manifest.json", "sim/out/manager-standard-funded/summary.json",
                    "docs/receipts/manager-standard-backing-fork.json", "deploy/manager-create-unsigned.json",
                    "deploy/manager-unsigned-cutover.json", "deploy/manager-keeper-unsigned.json"]
MANAGER_EVIDENCE += ["sim/manager_closeout.py", "sim/test_manager_closeout.py", "sim/manager_standard_backing.py",
                     "docs/receipts/manager-closeout-economics.json", "docs/receipts/manager-closeout-economics.md",
                     "docs/receipts/manager-final-live-observation.json", "docs/receipts/manager-closeout-review.md",
                     "docs/receipts/manager-final-verification.md"]
MANAGER_EVIDENCE += MANAGER_COMPATIBILITY_EVIDENCE
MANAGER_EVIDENCE += ["docs/receipts/manager-keeper-readiness.json", "docs/receipts/manager-keeper-readiness.md",
                     "docs/receipts/manager-operating-live-observation.json",
                     "docs/receipts/manager-operating-min-backing-continuity.json",
                     "docs/receipts/manager-operating-reconciliation.json",
                     "docs/receipts/manager-operating-model-review.md",
                     "docs/receipts/manager-operating-osaka-receipts.json",
                     "docs/receipts/manager-operating-cost-calibration.json",
                     "docs/receipts/manager-operating-calibration.md",
                     "docs/receipts/manager-operating-history-checks.json",
                     "docs/receipts/manager-operating-unsigned-checks.json",
                     "docs/receipts/manager-operating-verification.md",
                     "docs/receipts/manager-operating-economics.md",
                     "docs/receipts/manager-operating-image.json",
                     "sim/out/manager-operating-assessment/manifest.json",
                     "sim/out/manager-operating-assessment/summary.json"]
MANAGER_EVIDENCE += ["docs/receipts/manager-baseline-settings.json",
                     "docs/receipts/manager-operating-baseline-economics.json",
                     "docs/receipts/manager-operating-baseline-economics.md",
                     "docs/receipts/manager-operating-baseline-review.md",
                     "docs/receipts/manager-calibrated-receipts.json",
                     "docs/receipts/manager-calibrated-cost-calibration.json",
                     "docs/receipts/manager-calibrated-verification.md",
                     "docs/receipts/manager-calibrated-review.md",
                     "docs/receipts/manager-calibrated-checks.json",
                     "docs/receipts/manager-calibrated-reconciliation.json",
                     "docs/receipts/manager-calibrated-economics-review.md",
                     "docs/receipts/manager-calibrated-unsigned-checks.json",
                     "docs/receipts/manager-operating-economics.json",
                     "sim/out/manager-calibrated-assessment/manifest.json",
                     "sim/out/manager-calibrated-assessment/summary.json"]
MANAGER_EVIDENCE += ["deploy/manager-measured-dry-run.json",
                     "docs/receipts/manager-measured-50k-receipts.json",
                     "docs/receipts/manager-measured-sync-contexts.json",
                     "docs/receipts/manager-measured-cost-calibration.json",
                     "docs/receipts/manager-measured-reconciliation.json",
                     "docs/receipts/manager-measured-splitting-50k.json",
                     "docs/receipts/manager-measured-owner-exit.json",
                     "docs/receipts/manager-measured-owner-batch-exit.json",
                     "docs/receipts/manager-measured-ordinary-keeper.json",
                     "docs/receipts/manager-measured-ordinary-relist.json",
                     "docs/receipts/manager-measured-ui-create.json",
                     "docs/receipts/manager-measured-ui-migration.json",
                     "docs/receipts/manager-measured-ui-canonical.json",
                     "docs/receipts/manager-measured-postflight-create.json",
                     "docs/receipts/manager-measured-postflight-readback.json",
                     "docs/receipts/manager-measured-economics.md",
                     "docs/receipts/manager-measured-verification.md",
                     "sim/out/manager-measured-a8-bounded/manifest.json",
                     "sim/out/manager-measured-a8-bounded/failure.json",
                     "keeper/rehearse_manager_measured.py",
                     "keeper/rehearse_manager_sync_contexts.py"]
MANAGER_EVIDENCE += ["docs/receipts/manager-a9-public-readback.json",
                     "docs/receipts/manager-a10-public-readback.json",
                     "docs/receipts/manager-measured-unsigned-dry-run-a10.log",
                     "deploy/manager-unsigned-history/measured-dry-run-nonce4180.json",
                     "deploy/manager-unsigned-history/measured-cutover-nonce4180.json",
                     "deploy/manager-unsigned-history/measured-create-nonce4180.json",
                     "docs/receipts/manager-a9-independent-review.md",
                     "docs/receipts/manager-measured-reconciliation-a9.json",
                     "docs/receipts/manager-measured-sync-scan-attempt1.json",
                     "docs/receipts/manager-measured-sync-scan-attempt2.json",
                     "docs/receipts/manager-measured-sync-scan-attempt3.json",
                     "docs/receipts/manager-measured-sync-scan-one.json",
                     "docs/receipts/manager-measured-sync-scan-one-no-credit-blockfork.json",
                     "docs/receipts/manager-measured-sync-scan-three-blockfork.json",
                     "docs/receipts/manager-measured-sync-multi-two-attempt1.json",
                     "docs/receipts/manager-measured-sync-multi-two-no-credit.json",
                     "docs/receipts/manager-measured-sync-multi-three-blockfork.json",
                     "docs/receipts/manager-measured-sync-multi-later-first.json",
                     "docs/receipts/manager-measured-sync-preselected-two-blockfork.json",
                     "sim/out/manager-measured-multi-checkpoint-v2-metadata.json",
                     "sim/out/manager-measured-multi-checkpoint-v2-alloc.json",
                     "sim/out/manager-measured-multi-checkpoint-v2-diff.json",
                     "sim/out/manager-measured-preselected-checkpoint-metadata.json",
                     "sim/out/manager-measured-preselected-checkpoint-alloc.json",
                     "sim/out/manager-measured-preselected-checkpoint-diff.json",
                     "sim/out/manager-measured-a9-final/manifest.json",
                     "sim/out/manager-measured-a9-final/paths.jsonl",
                     "sim/out/manager-measured-a9-final/summary.json",
                     "sim/out/manager-measured-a9-final/report.md",
                     "sim/out/manager-measured-a10-release/manifest.json",
                     "sim/out/manager-measured-a10-release/paths.jsonl",
                     "sim/out/manager-measured-a10-release/summary.json",
                     "sim/out/manager-measured-a10-release/report.md",
                     "sim/out/manager-measured-a9-multiseed/manifest.json",
                     "sim/out/manager-measured-a9-multiseed/failure.json",
                     "docs/receipts/manager-a10-economics.md",
                     "docs/receipts/manager-a10-independent-review.md",
                     "keeper/rehearse_manager_sync_scan.py"]


def target_files(target):
    if target == "combined":
        return MANIFEST, ACCEPTANCE, SIGNATURE, VALUES, EVIDENCE, "deploy/mainnet.json"
    if target == "manager":
        return MANAGER_MANIFEST, MANAGER_ACCEPTANCE, MANAGER_SIGNATURE, MANAGER_VALUES, MANAGER_EVIDENCE, "deploy/manager-factory.json"
    raise ValueError(f"unknown deployment target: {target}")


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
    "routineRatePerDayWei": "routineRate", "reserveWei": "reserve", "tvlCapWei": "tvlCap",
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


def validate_manager_factory_values(values):
    required = set(MAIN_DEPENDENCIES) | {"target"}
    _exact_keys(values, required | ({"comment"} if "comment" in values else set()), "manager factory values")
    if values["target"] != "manager":
        raise ValueError("manager factory values must explicitly name target manager")
    for key, expected in MAIN_DEPENDENCIES.items():
        if not isinstance(values[key], str) or values[key].lower() != expected.lower():
            raise ValueError(f"launch {key} must be the selected main-pool dependency {expected}")


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
    if len(GAS_FIELDS) != 22 or _abi_fields(gas) != [(key, "uint32") for key in GAS_FIELDS]:
        raise ValueError(f"{label} GasSchedule names/types/order differ from the complete 22 keeper.config.GAS_FIELDS")


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
    _validate_factory_abi(factory_abi)


def _validate_factory_abi(factory_abi):
    # Two creates: without and with the owner's pack counts (PackAccount.design); nothing else, no policy.
    creates = [e for e in factory_abi if e.get("type") == "function" and e.get("name") == "create"]
    shapes = sorted(_abi_fields(e.get("inputs", [])) for e in creates)
    if shapes != sorted([[("owner", "address"), ("p", "tuple"), ("expected", "bytes32")],
                         [("owner", "address"), ("p", "tuple"), ("design", "uint256"), ("expected", "bytes32")]]):
        raise ValueError("compiled factory create must be only (owner, p, expected) and (owner, p, design, expected)")
    for create in creates:
        _validate_params_abi(create["inputs"][1], "factory create")
    if _abi_fields(_abi_entry(factory_abi, "constructor").get("inputs", [])) != [
            ("fwa", "address"), ("shapes", "address"), ("packs", "address")]:
        raise ValueError("compiled factory constructor must have only the three main dependencies")


def validate_compiled_manager_abi(manager_abi, factory_abi):
    if _abi_fields(_abi_entry(manager_abi, "constructor").get("inputs", [])) != [
            ("fwa_", "address"), ("shapes_", "address"), ("packs_", "address")]:
        raise ValueError("compiled manager constructor must have only the three main dependencies")
    getter = _abi_entry(manager_abi, "function", "getParams")
    if getter.get("inputs") != [] or len(getter.get("outputs", [])) != 1:
        raise ValueError("compiled manager getParams must return one Params tuple")
    _validate_params_abi(getter["outputs"][0], "manager getParams")
    _validate_factory_abi(factory_abi)
    initial = _abi_entry(manager_abi, "function", "initialize")
    if _abi_fields(initial.get("inputs", [])) != [("owner_", "address"), ("p", "tuple"), ("design_", "uint256")]:
        raise ValueError("compiled manager initialize must be only (owner_, p, design_)")
    _validate_params_abi(initial["inputs"][1], "manager initialize")
    for name, fields in (("importPacks", [("ids", "uint256[]"), ("expected", "bytes32")]),
                         ("unlistForWithdrawal", [("listingIds", "uint256[]")]),
                         ("withdrawRecoveryPack", [("to", "address"), ("index", "uint256"),
                                                   ("expectedPackId", "uint256")])):
        entry = _abi_entry(manager_abi, "function", name)
        if _abi_fields(entry.get("inputs", [])) != fields or entry.get("outputs") != []:
            raise ValueError(f"compiled manager {name} does not match the owner-controlled migration ABI")
    for abi in (manager_abi, factory_abi):
        if any(e.get("name") in ("keeperPolicy", "policy", "setPolicy", "renew", "renewalEligible",
                "renewalState", "renewalFloat", "renewalQuote", "fundingDeficit") for e in abi):
            raise ValueError("compiled manager ABI contains retired policy or fresh-renewal machinery")


def _launch_json(path):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate launch JSON key: {key}")
            result[key] = value
        return result
    return json.loads(Path(path).read_text(), object_pairs_hook=unique_object)


def validate_launch_inputs(values=None, target="combined"):
    """Fail before manifest generation/check or any postflight read if launch identity/schema drift."""
    target_files(target)
    if target == "manager":
        validate_manager_factory_values(_launch_json(values or ROOT / "deploy/manager-factory.json"))
        validate_launch_values(_launch_json(ROOT / "deploy/manager.json"), manager=True)
        validate_compiled_manager_abi(artifact("PackManager")["abi"], artifact("PackManagerFactory")["abi"])
        return
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


def build(target="combined"):
    out = {}
    for name in CONTRACTS:
        if target == "manager" and name == "PackVault":
            continue
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


def manifest(target="combined"):
    path, _, _, values, evidence, deployment = target_files(target)
    validate_launch_inputs(target=target)
    m = dict(name="PackManagerFactory mainnet" if target == "manager" else "PackVault and PackManagerFactory mainnet",
             deployment_target=target, sources=sources(), toolchain=toolchain(), build=build(target),
             deployment_values=deployment, values={v: sha(v) for v in values},
             keeper={k: sha(k) for k in KEEPER},
             evidence={e: sha(e) for e in evidence if (ROOT / e).exists()})
    for name, b in m["build"].items():
        assert b["runtime_bytes"] <= CODE_LIMIT, f"{name} runtime {b['runtime_bytes']} exceeds EIP-170"
    path.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {path.relative_to(ROOT)} sha256 {sha(path.relative_to(ROOT))}")


def problems(values, broadcast, target="combined"):
    path, acceptance, signature, value_paths, _, _ = target_files(target)
    try:
        validate_launch_inputs(values, target)
    except (ValueError, KeyError, TypeError, OSError) as error:
        return [f"launch inputs invalid: {error}"]
    if not path.exists():
        return [f"no {path.relative_to(ROOT)}"]
    m = json.loads(path.read_text())
    out = []
    if m.get("deployment_target", "combined") != target:
        out.append("manifest deployment target differs")
    dirty = git("status", "--porcelain", "--", "src", "script", "deploy", "foundry.toml", "remappings.txt", "lib", "keeper")
    if dirty:
        out.append("uncommitted release inputs:\n" + dirty)
    for key, now in (("sources", sources()), ("toolchain", toolchain()), ("build", build(target)),
                     ("keeper", {k: sha(k) for k in KEEPER}), ("values", {v: sha(v) for v in value_paths}),
                     ("evidence", {e: sha(e) for e in m["evidence"] if (ROOT / e).exists()})):
        if now != m[key]:
            changed = sorted(k for k in set(now) | set(m[key]) if now.get(k) != m[key].get(k))
            out.append(f"{key} differs from the manifest: {changed}")
    if os.path.relpath(Path(values).resolve(), ROOT) != m["deployment_values"]:
        out.append(f"values {values} are not the release's {m['deployment_values']}")
    if broadcast:
        if not acceptance.exists():
            out.append(f"no {acceptance.relative_to(ROOT)}")
        elif target == "manager" and json.loads(acceptance.read_text()).get("deployment_target") != target:
            out.append("acceptance package names a different deployment target")
        elif json.loads(acceptance.read_text()).get("manifest_sha256") != sha(path.relative_to(ROOT)):
            out.append("acceptance package names a different manifest")
        elif not signature.exists():
            out.append(f"no owner signature: {signature.relative_to(ROOT)}")
        else:
            r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", SIGNERS, "-I", "owner", "-n", "packvault-release",
                                "-s", signature], input=sha(acceptance.relative_to(ROOT)).encode(), capture_output=True)
            if r.returncode:
                out.append("owner signature does not verify over the acceptance package")
    return out


def cast(*args):
    pinned = ["--block", str(READ_BLOCK)] if READ_BLOCK is not None and args[0] in ("call", "code", "balance", "nonce") else []
    return subprocess.check_output(["cast", *map(str, args), *pinned, "--rpc-url", RPC], text=True).strip()


def first(raw):
    return raw.split()[0]


def _postflight_code(m, deployed, fail, target="combined"):
    expected = build(target)
    if m["build"] != expected:
        fail.append("manifest build differs from the current compiled artifacts")
    libs = {name: expected[name]["create2_address"] for name in LIBRARIES}
    check = lambda ok, what: ok or fail.append(what)
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


def clone_runtime(implementation):
    # The 44-byte clone used by the pinned Solady LibClone.clone implementation.
    return "0x3d3d3d3d363d3d37363d73" + implementation.removeprefix("0x").lower() + "5af43d3d93803e602a57fd5bf3"


def _address(value, label):
    if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", value) or int(value, 16) <= 0xffff:
        raise ValueError(f"{label} must be a real nonzero account address")
    return value


def _pin_read_block():
    global READ_BLOCK
    chain = int(cast("chain-id"))
    if chain == 1:
        if RPC != "https://mainnet.gateway.tenderly.co":
            raise ValueError("Ethereum mainnet reads require https://mainnet.gateway.tenderly.co")
    elif chain != 31337 or not re.fullmatch(r"http://(?:127\.0\.0\.1|localhost)(?::[0-9]+)?/?", RPC):
        raise ValueError("manager tooling requires Ethereum mainnet reads or isolated local chain 31337")
    header = json.loads(cast("block", "latest", "--json"))
    header = header.get("data", header)
    READ_BLOCK = int(header["number"], 16)
    return dict(chainId=chain, block=READ_BLOCK, blockHash=header["hash"], rpc=RPC)


def postflight_manager(factory, values, manager=None, owner=None, funding=None, *, emit=True):
    """Verify the manager product independently, without a vault or holder-pricing assumptions."""
    validate_launch_inputs(values, "manager")
    context = _pin_read_block()
    _address(factory, "factory")
    m, deps = json.loads(MANAGER_MANIFEST.read_text()), _launch_json(values)
    if m.get("deployment_target") != "manager":
        raise ValueError("manager postflight requires a manager-target manifest")
    fail = []
    check = lambda ok, what: ok or fail.append(what)
    implementation = cast("call", factory, "implementation()(address)")
    libs = {name: m["build"][name]["create2_address"] for name in LIBRARIES}
    deployed = [("PackManagerFactory", factory), ("PackManager", implementation)] + list(libs.items())
    _postflight_code(m, deployed, fail, "manager")
    check(cast("call", implementation, "factory()(address)").lower() == factory.lower(), "implementation factory")
    check(int(cast("call", implementation, "owner()(address)"), 16) == 0, "implementation has an owner")
    accounts = [("implementation", implementation)]
    result = dict(context, deploymentTarget="manager", factory=factory, implementation=implementation,
                  libraries=libs, managerCount=int(first(cast("call", factory, "managerCount()(uint256)"))),
                  factoryBalanceWei=int(cast("balance", factory)), implementationBalanceWei=int(cast("balance", implementation)))
    if manager:
        _address(manager, "manager")
        _address(owner, "owner")
        accounts.append(("manager", manager))
        check(cast("code", manager).lower() == clone_runtime(implementation), "manager clone runtime/implementation")
        check(cast("call", factory, "isManager(address)(bool)", manager) == "true", "manager not registered by factory")
        check(cast("call", manager, "factory()(address)").lower() == factory.lower(), "manager factory")
        check(cast("call", manager, "owner()(address)").lower() == owner.lower(), "manager owner")
        v = _launch_json(ROOT / "deploy/manager.json")
        # A manager created with a pack mix admits exactly the mix's sizes (as manager_create sets them).
        design = int(first(cast("call", manager, "design()(uint256)")))
        if design:
            v = v | {"packUnitsMask": sum(1 << u for u in range(3, 31) if (design >> (8 * u)) & 0xFF)}
        got = decode_params(cast("call", manager, f"getParams()({PARAMS_T})"))
        expected = {key: v[key] for key, _ in PARAM_FIELDS} | {"gasSchedule": v["gasSchedule"]}
        check(got == expected, "manager complete Params/GasSchedule")
        mint_fee = int(first(cast("call", deps["shapes"], "mintFee()(uint256)")))
        check(mint_fee <= v["acceptedMintFeeWei"], "live mint fee exceeds manager acceptance")
        check(cast("call", manager, "configurationHash()(bytes32)").lower() == configuration_hash(v, mint_fee).lower(), "manager configuration hash")
        flags = {name: cast("call", manager, name + "()(bool)") for name in ("windingDown", "listingPaused")}
        check(all(value == "false" for value in flags.values()), "new manager pause/exit flags")
        budget = int(first(cast("call", manager, "budget()(uint256)")))
        check(budget == v["routineCapWei"], "new manager budget")
        cash = int(cast("balance", manager))
        if funding is not None:
            _unsigned(int(funding), 256, "manager funding")
            check(cash >= int(funding), "manager initial funding")
        counts = {name: int(first(cast("call", manager, name + "()(uint256)"))) for name in ("openListingCount", "idlePackCount", "recoveryPackCount")}
        check(not any(counts.values()), "new manager already has inventory")
        result["manager"] = dict(address=manager, owner=owner, params=got, budget=budget,
                                 cashWei=cash, flags=flags, inventory=counts, liveMintFeeWei=mint_fee)
    for label, address in accounts:
        for key, expected_address in MAIN_DEPENDENCIES.items():
            check(cast("call", address, key + "()(address)").lower() == expected_address.lower(), f"{label} {key}")
        for key in ("rewards", "token"):
            expected_address = cast("call", deps["fwa"], key + "()(address)")
            check(cast("code", expected_address) not in ("", "0x"), f"FWA {key} missing")
            check(cast("call", address, key + "()(address)").lower() == expected_address.lower(), f"{label} {key}")
    if fail:
        raise ValueError("manager postflight FAILED: " + "; ".join(fail))
    if emit:
        print(json.dumps(result, indent=2))
        print("manager postflight passed; shared vault not required")
    return result


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
    _postflight_code(m, deployed, fail)
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
    budget = int(first(cast("call", vault, "budget()(uint256)")))
    check(budget <= v["routineCapWei"], "budget above cap")
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



def create_address(sender, nonce):
    """CREATE address from its RLP(sender, nonce), with Ethereum's 64-bit nonce bound."""
    from eth_utils import keccak
    _unsigned(nonce, 64, "creation nonce")
    address = bytes.fromhex(sender.removeprefix("0x"))
    if len(address) != 20:
        raise ValueError("creation sender must have 20 bytes")
    raw = nonce.to_bytes((nonce.bit_length() + 7) // 8, "big")
    encoded = raw if len(raw) == 1 and raw[0] < 0x80 else bytes([0x80 + len(raw)]) + raw
    payload = b"\x94" + address + encoded
    return "0x" + keccak(bytes([0xc0 + len(payload)]) + payload)[-20:].hex()


def validate_manager_transactions(run, values, compiled):
    """Decode a real Forge dry-run as unsigned manager deployments, not a vault replacement."""
    validate_manager_factory_values(values)
    if type(run.get("chain")) is not int or run["chain"] != 1 or run.get("receipts"):
        raise ValueError("unsigned manager package requires a mainnet dry-run without mined receipts")
    records, seen, sender, nonce = [], set(), None, None
    from eth_abi import encode
    addresses = {name: bytes.fromhex(compiled[name]["create2_address"][2:]) for name in LIBRARIES}
    rows = run.get("transactions", [])
    order = [*LIBRARIES, "PackManagerFactory"]
    last = -1
    for row in rows:
        name, tx = row.get("contractName"), row.get("transaction", {})
        if name not in (*LIBRARIES, "PackManagerFactory") or name in seen or row.get("hash"):
            raise ValueError("manager package has a duplicate, signed, vault or unknown deployment")
        seen.add(name)
        if order.index(name) <= last:
            raise ValueError("manager deployments are out of linked-library order")
        last = order.index(name)
        _address(tx.get("from"), "deployment sender")
        if sender is not None and tx["from"].lower() != sender:
            raise ValueError("manager deployment uses more than one sender")
        sender = tx["from"].lower()
        current_nonce = int(tx["nonce"], 16)
        _unsigned(current_nonce, 64, "deployment nonce")
        if nonce is not None and current_nonce != nonce + 1:
            raise ValueError("manager deployment nonces are not contiguous")
        nonce = current_nonce
        if int(tx["chainId"], 16) != 1 or not 0 < int(tx["gas"], 16) <= 16_777_216:
            raise ValueError("manager deployment chain/gas limit is invalid")
        if int(tx.get("value", "0x0"), 16) != 0:
            raise ValueError("manager factory deployment has no vault seed or attached funding")
        bytecode = artifact(name)["bytecode"]
        init = linked(bytecode["object"], bytecode.get("linkReferences", {}), addresses)
        if name in LIBRARIES:
            expected = bytes(32) + init
            if row.get("transactionType") != "CREATE2" or tx.get("to", "").lower() != CREATE2_FACTORY.lower():
                raise ValueError("library must use the reviewed CREATE2 factory")
            if row.get("contractAddress", "").lower() != compiled[name]["create2_address"].lower():
                raise ValueError("library predicted address differs from compiled linkage")
        else:
            expected = init + encode(["address"] * 3, [values[k] for k in MAIN_DEPENDENCIES])
            if row.get("transactionType") != "CREATE" or tx.get("to") not in (None, "", "0x"):
                raise ValueError("manager factory must use ordinary creation")
            if row.get("contractAddress", "").lower() != create_address(sender, current_nonce):
                raise ValueError("manager factory predicted address differs from sender/nonce")
        if bytes.fromhex(tx["input"].removeprefix("0x")) != expected:
            raise ValueError(f"{name} calldata differs from compiled bytecode/dependencies")
        allowed = ("from", "to", "gas", "value", "input", "nonce", "chainId")
        if set(tx) - set(allowed):
            raise ValueError("manager package has signed or unreviewed transaction fields")
        records.append(dict(contract=name, operation=row["transactionType"], predictedAddress=row["contractAddress"],
                            unsignedTransaction={key: tx[key] for key in allowed if key in tx}))
    if "PackManagerFactory" not in seen:
        raise ValueError("manager package is missing its factory deployment")
    return records, [name for name in LIBRARIES if name not in seen]


def manager_package(run_path):
    validate_launch_inputs(target="manager")
    m = json.loads(MANAGER_MANIFEST.read_text())
    if m.get("deployment_target") != "manager" or m["build"] != build("manager"):
        raise ValueError("manager package requires the current target-bound compiled manifest")
    values = _launch_json(ROOT / "deploy/manager-factory.json")
    run = json.loads(Path(run_path).read_text())
    transactions, reused = validate_manager_transactions(run, values, m["build"])
    context = _pin_read_block()
    if context["chainId"] != 1:
        raise ValueError("unsigned mainnet package readback must use the public mainnet gateway")
    fail = []
    if reused:
        _postflight_code(m, [(name, m["build"][name]["create2_address"]) for name in reused], fail, "manager")
    if fail:
        raise ValueError("reused library verification failed: " + "; ".join(fail))
    first_tx = transactions[0]["unsignedTransaction"]
    current_nonce = int(cast("nonce", first_tx["from"]))
    if current_nonce != int(first_tx["nonce"], 16):
        raise ValueError("deployment nonce changed since the dry-run; repeat the unsigned simulation")
    factory = next(t["predictedAddress"] for t in transactions if t["contract"] == "PackManagerFactory")
    package = dict(status="UNSIGNED_NOT_APPROVED_FOR_BROADCAST", deploymentTarget="manager", **context,
        values="deploy/manager-factory.json", valuesSha256=sha("deploy/manager-factory.json"),
        managerValues="deploy/manager.json", managerValuesSha256=sha("deploy/manager.json"),
        sourceSha256=m["sources"], build=m["build"], transactions=transactions, reusedVerifiedLibraries=reused,
        deployerNonceAtReadback=current_nonce, nonceStillMatchesSimulation=current_nonce == int(first_tx["nonce"],16),
        predictedImplementationAddress=create_address(factory, 1),
        sharedVaultDeployed=False, vaultSeedWei=0, publicTransactions=0,
        refreshBeforeSigning=["Recheck chain, signer nonce/balance, live mint fee and dependency/library code.",
          "Re-simulate the same target-manager production path and independently postflight before manager creation.",
          "No signature, production cutover or launch approval is included. Never reuse a combined-product approval."])
    (ROOT / "deploy/manager-unsigned-cutover.json").write_text(json.dumps(package, indent=2) + "\n")
    keeper = dict(status="UNSIGNED_ADDRESS_DATA_NOT_LIVE_CONFIGURATION", deploymentTarget="manager",
                  chainId=1, rpc="https://mainnet.gateway.tenderly.co", factory=factory, vault=None,
                  environment=dict(FACTORY=factory, RPC_URL="https://mainnet.gateway.tenderly.co",
                      KEEPER_KEYSTORE_PATH="<existing read-only keystore mount path>",
                      KEEPER_PASSWORD_FILE="<existing read-only password mount path>"),
                  discoveryFromBlock="set to the separately authorized factory deployment receipt block",
                  command=["python3", "keeper/keeper.py", "--factory", factory],
                  signer="existing separately selected external keystore; no secret is included",
                  sharedVaultOpen=False)
    (ROOT / "deploy/manager-keeper-unsigned.json").write_text(json.dumps(keeper, indent=2) + "\n")
    print("wrote unsigned manager-only deployment and keeper address data; no vault or seed")


def manager_create(factory, owner, funding, design=0):
    validate_launch_inputs(target="manager")
    _address(factory, "factory")
    _address(owner, "owner")
    if owner.lower() == factory.lower():
        raise ValueError("factory cannot own an individual manager")
    funding = int(funding)
    _unsigned(funding, 256, "manager funding")
    context = _pin_read_block()
    deployed = cast("code", factory) not in ("", "0x")
    if deployed:
        context = {k: v for k, v in postflight_manager(factory, ROOT / "deploy/manager-factory.json", emit=False).items()
                   if k in ("chainId", "block", "blockHash", "rpc")}
    p = _launch_json(ROOT / "deploy/manager.json")
    design = int(design, 0) if isinstance(design, str) else int(design)
    # PackAccount._setDesign: sizes 3..30 units only, at most 255 packs each; the mask admits exactly those sizes.
    if design & 0xFFFFFF or design >> 248:
        raise ValueError("design may only count pack sizes of 3 to 30 units")
    if design:
        p = p | {"packUnitsMask": sum(1 << u for u in range(3, 31) if (design >> (8 * u)) & 0xFF)}
    fee = int(first(cast("call", MAIN_DEPENDENCIES["shapes"], "mintFee()(uint256)")))
    if fee > p["acceptedMintFeeWei"]:
        raise ValueError("live mint fee exceeds the owner's accepted maximum")
    expected = configuration_hash(p, fee)
    if deployed and cast("call", factory, f"configHashFor({PARAMS_T})(bytes32)", tuple_arg(p)).lower() != expected.lower():
        raise ValueError("factory configuration hash disagrees with the reviewed encoding")
    from eth_abi import encode
    from eth_utils import keccak
    if design:
        signature = f"create(address,{PARAMS_T},uint256,bytes32)"
        data = keccak(text=signature)[:4] + encode(["address", PARAMS_T, "uint256", "bytes32"],
                       [owner, params_values(p), design, bytes.fromhex(expected[2:])])
    else:
        signature = f"create(address,{PARAMS_T},bytes32)"
        data = keccak(text=signature)[:4] + encode(["address", PARAMS_T, "bytes32"],
                       [owner, params_values(p), bytes.fromhex(expected[2:])])
    result = dict(status="UNSIGNED_MANAGER_CREATION_TEMPLATE", **context, factoryAlreadyDeployed=deployed,
                  unsignedTransaction=dict(chainId=hex(context["chainId"]), **{"from": owner}, to=factory,
                                           value=hex(funding), input="0x" + data.hex()),
                  reviewedOwner=owner, reviewedFundingWei=funding, reviewedDesign=hex(design), reviewedLiveMintFeeWei=fee,
                  fixtureExpectedMintFeeWei=p["expectedMintFeeWei"],
                  mintFeeChangedSinceFixture=fee != p["expectedMintFeeWei"],
                  acceptedMintFeeWei=p["acceptedMintFeeWei"], expectedConfigurationHash=expected,
                  managerValuesSha256=sha("deploy/manager.json"), params=p,
                  conditions=["Refresh preview and estimate exact calldata before signing.",
                    "After factory deployment, independently verify its runtime, dependencies and links.",
                    "Creating an idle manager does not establish productive funding or positive returns.",
                    "No factory or administrator can change this manager's owner/settings after creation."])
    print(json.dumps(result, indent=2))
    return result


def existing_readback(target="combined"):
    """Refresh the existing MAIN deployment at one latest public-mainnet block; send nothing."""
    previous=json.loads((ROOT/'deploy/existing-main-readback.json').read_text())
    path=ROOT/('deploy/manager-existing-main-readback.json' if target == 'manager' else 'deploy/existing-main-readback.json')
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



def parse_target(arguments):
    args = list(arguments)
    if args.count("--target") > 1:
        raise ValueError("supply exactly one deployment target")
    target = "combined"
    if "--target" in args:
        at = args.index("--target")
        if at + 1 >= len(args):
            raise ValueError("--target needs combined or manager")
        target = args[at + 1]
        del args[at:at + 2]
    target_files(target)
    return target, args


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    target, args = parse_target(args)
    if cmd == "existing-readback":
        existing_readback(target)
    elif cmd == "calibrate" and args:
        calibrate(args[0])
    elif cmd == "manifest":
        manifest(target)
    elif cmd == "check" and args:
        found = problems(args[0], "--broadcast" in args, target)
        for p in found:
            print("release check:", p)
        if found:
            sys.exit(1)
        print("release check passed" + (" with owner signature" if "--broadcast" in args else " (no signature checked)"))
    elif cmd == "postflight-manager" and len(args) in (2, 4, 5):
        postflight_manager(*args)
    elif cmd == "manager-package" and len(args) == 1:
        manager_package(args[0])
    elif cmd == "manager-create" and len(args) in (3, 4):
        manager_create(*args)
    elif cmd == "postflight" and len(args) in (2, 3, 4, 5):
        if target == "manager":
            postflight_manager(*args)
        elif len(args) in (2, 3, 4):
            postflight(*args)
        else:
            sys.exit(__doc__)
    elif cmd == "keeper-config" and len(args) in (2, 3) and target == "combined":
        keeper_config(*args)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError) as error:
        sys.exit(str(error))
