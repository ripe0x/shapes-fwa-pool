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
MANIFEST = ROOT / "deploy/release-manifest.json"
ACCEPTANCE = ROOT / "docs/release/acceptance.json"
SIGNATURE = ROOT / "deploy/release-acceptance.sig"
SIGNERS = ROOT / "deploy/allowed_signers"
RPC = os.environ.get("RPC_URL", "https://mainnet.gateway.tenderly.co")
CODE_LIMIT = 24_576
CREATE2_FACTORY = "0x4e59b44847b379578588920cA78FbF26c0B4956C"
CONTRACTS = {"PackVault": "src/PackVault.sol", "PackManager": "src/PackManager.sol",
             "PackManagerFactory": "src/PackManagerFactory.sol", "StrategyLib": "src/StrategyLib.sol",
             "VaultLib": "src/VaultLib.sol", "ScanLib": "src/ScanLib.sol", "KeeperPolicyV1": "src/KeeperPolicy.sol"}
# Linked libraries in dependency order: VaultLib links ScanLib, StrategyLib links VaultLib; both
# accounts (PackVault, the PackManager implementation) link VaultLib and StrategyLib.
LIBRARIES = ["ScanLib", "VaultLib", "StrategyLib"]
KEEPER = ["keeper/Dockerfile", "keeper/entrypoint.sh", "keeper/requirements.txt", "keeper/keeper.py",
          "keeper/policy.py", "keeper/tx.py", "keeper/index.py", "fly.keeper-primary.toml", "fly.keeper-backup.toml"]
VALUES = ["deploy/mainnet.json"]
# The acceptance package names this manifest, so it is not listed here (no cycle).
EVIDENCE = ["docs/receipts/formal-assessment.json", "docs/receipts/recipe-comparison.json",
            "docs/receipts/unified-production-rehearsal.json", "docs/receipts/unified-selection-rehearsal.json",
            "docs/receipts/image-rehearsal/ci-44948198556.json", "docs/receipts/unified-review.md",
            "docs/receipts/unified-verify/SUMMARY.md", "asset-flow.json"]


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def sources():
    files = git("ls-files", "src", "script", "foundry.toml", "remappings.txt").split()
    return {f: sha(f) for f in files if f != "script/release.py"} | {"script/release.py": sha("script/release.py")}


def artifact(name):
    return json.loads((ROOT / f"out/{Path(CONTRACTS[name]).name}/{name}.json").read_text())


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
    m = dict(name="PackVault and PackManagerFactory mainnet", sources=sources(), toolchain=toolchain(), build=build(),
             deployment_values="deploy/mainnet.json", values={v: sha(v) for v in VALUES},
             keeper={k: sha(k) for k in KEEPER},
             evidence={e: sha(e) for e in EVIDENCE if (ROOT / e).exists()})
    for name, b in m["build"].items():
        assert b["runtime_bytes"] <= CODE_LIMIT, f"{name} runtime {b['runtime_bytes']} exceeds EIP-170"
    MANIFEST.write_text(json.dumps(m, indent=1) + "\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)} sha256 {sha(MANIFEST.relative_to(ROOT))}")


def problems(values, broadcast):
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
    """Read the deployed vault, factory, implementation, libraries and policy back; stop on any difference."""
    m, v = json.loads(MANIFEST.read_text()), json.loads(Path(values).read_text())
    fail = []
    check = lambda ok, what: ok or fail.append(what)  # noqa: E731
    policy = cast("call", vault, "keeperPolicy()(address)")
    libs = {name: m["build"][name]["create2_address"] for name in LIBRARIES}
    deployed = [("PackVault", vault), ("KeeperPolicyV1", policy)] + [(n, a) for n, a in libs.items()]
    if factory:
        implementation = cast("call", factory, "implementation()(address)")
        deployed += [("PackManagerFactory", factory), ("PackManager", implementation)]
        check(cast("call", factory, "policy()(address)").lower() == policy.lower(), "factory default policy")
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
    check(first(cast("call", policy, "policyVersion()(uint256)")) == "1", "policy version")
    fields = ["minEdgeBps", "bufferBps", "distributionBps", "payMarkupBps", "keeperShareBps", "allocatedBoundBps",
              "packUnitsMask", "gasCeilingWei", "essentialCeilingWei", "maxTipWei", "workFeeWei", "reserveWei",
              "tvlCapWei", "routineCapWei", "routineRatePerDayWei", "essentialCapWei", "essentialRatePerDayWei"]
    raw = cast("call", vault, "getParams()((uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,"
                               "uint64,uint64,uint64,uint64,uint64,uint128,uint128))")
    got = [int(x.split()[0]) for x in raw.strip("()").split(", ")]
    order = ["minEdgeBps", "bufferBps", "distributionBps", "payMarkupBps", "keeperShareBps", "allocatedBoundBps",
             "packUnitsMask", "gasCeilingWei", "essentialCeilingWei", "maxTipWei", "workFeeWei", "routineCapWei",
             "routineRatePerDayWei", "essentialCapWei", "essentialRatePerDayWei", "reserveWei", "tvlCapWei"]
    check(dict(zip(order, got)) == {f: v[f] for f in fields}, f"params {dict(zip(order, got))}")
    budget = [int(first(x)) for x in cast("call", vault, "budget()(uint256,uint256)").splitlines()]
    check(budget[0] <= v["routineCapWei"] and budget[1] <= v["essentialCapWei"], "budgets above caps")
    dead = first(cast("call", vault, "DEAD_SHARES()(uint256)"))
    check(first(cast("call", vault, "sharesOf(address)(uint256)", "0x000000000000000000000000000000000000dEaD")) == dead,
          "seed shares")
    for flag in ("windingDown", "depositsPaused", "listingPaused"):
        check(cast("call", vault, f"{flag}()(bool)") == "false", flag)
    check(int(first(cast("balance", vault))) >= v["seedWei"], "seed balance")
    if fail:
        sys.exit("postflight FAILED: " + "; ".join(fail))
    print(f"postflight passed: {vault} policy {policy} libraries {libs} owner {owner}"
          + (f" factory {factory}" if factory else " (factory not checked)"))
    print("verification commands (Etherscan; ETHERSCAN_API_KEY from your environment):")
    scan, lib, strategy = libs["ScanLib"], libs["VaultLib"], libs["StrategyLib"]
    accounts = f"--libraries src/VaultLib.sol:VaultLib:{lib} --libraries src/StrategyLib.sol:StrategyLib:{strategy}"
    print(f"  forge verify-contract {scan} src/ScanLib.sol:ScanLib --chain mainnet --watch")
    print(f"  forge verify-contract {lib} src/VaultLib.sol:VaultLib --chain mainnet "
          f"--libraries src/ScanLib.sol:ScanLib:{scan} --watch")
    print(f"  forge verify-contract {strategy} src/StrategyLib.sol:StrategyLib --chain mainnet "
          f"--libraries src/VaultLib.sol:VaultLib:{lib} --watch")
    print(f"  forge verify-contract {policy} src/KeeperPolicy.sol:KeeperPolicyV1 --chain mainnet --watch")
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


def main():
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("", [])
    if cmd == "manifest":
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
