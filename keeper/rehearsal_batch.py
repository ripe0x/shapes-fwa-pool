#!/usr/bin/env python3
"""Prepare, or run an explicitly owner-approved local-only integration rehearsal.

--plan only prints the complete proposed batch. --execute-approved-local-batch is an execution
entry point, not approval: the operator must hold the owner's authority for a local campaign.
No keys are created. Six fresh label-derived actors use Anvil impersonation on our own process.
The fork block is a fresh pin for each campaign (--fork-block, recorded with its hash); the
historical default 26,418,539 is the 2026-11-18 campaign.
"""
import argparse
import hashlib
import json
import re
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent
PORT = int(os.environ.get("PACK_VAULT_LOCAL_PORT", 8557))
RPC = f"http://127.0.0.1:{PORT}"
# Tenderly's public gateway by default. REHEARSAL_FORK_RPC (environment only) can name another
# upstream for the fork; its URL can carry an API key, so scrub() removes it from every record.
FORK_RPC = os.environ.get("REHEARSAL_FORK_RPC") or "https://mainnet.gateway.tenderly.co"


def scrub(text):
    text = text.replace(FORK_RPC, "<fork-rpc>") if "tenderly" not in FORK_RPC else text
    return re.sub(r"(https?://[^\s\"']*/v[0-9]+/)[A-Za-z0-9_-]{8,}", r"\1<key>", text)

FORK_BLOCK = int(os.environ.get("PACK_VAULT_FORK_BLOCK", 26_418_539))
MAX_GAS = 16_777_216
CODE_SIZE = 24_576
ACTOR_ETH = 10 * 10**18
# mgra/mgrb/mgrc own personal managers (the unified system's permissionless clones); purchaser is a
# fresh FWA purchaser for the manager outcome paths. All are fresh label-derived addresses, verified
# clean before funding, never Anvil dev accounts (rehearse_unified.py).
ACTORS = {name: to_checksum_address(keccak(text=f"pack-vault-rehearsal-{name}")[-20:])
          for name in ("deployer", "holder", "holder2", "keeper", "kicker", "owner",
                       "mgra", "mgrb", "mgrc", "purchaser")}
ORACLE = "0xaA4D9009a4664604b57644bF13e447E9036727DC"
ORACLE_OWNER = "0x9306342f408185180987bBe69B5AFDCaD5e971b4"  # pinned deployed owner(), read 2026-11-18
ENV_MANIFEST = "PACK_VAULT_LOCAL_BATCH"
CURRENT_DEPLOYMENT = None
PHASES = None
SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def source_freeze():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in ("src/PackVault.sol", "src/VaultLib.sol", "src/interfaces/External.sol", "src/KeeperPolicy.sol")}



def raw(*args, check=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}: {r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def cast(*args):
    return raw("cast", *args, "--rpc-url", RPC)


def rpc(method, *params):
    return json.loads(cast("rpc", method, *[json.dumps(p) if not isinstance(p, str) else p for p in params]))


def quantity(v):
    return int(v, 0) if isinstance(v, str) and v.startswith("0x") else int(v)


def values(calibration=False):
    v = json.loads((ROOT / "deploy/mainnet.json").read_text())
    v["owner"] = ACTORS["owner"]
    if calibration:
        v["tvlCapWei"] = 12 * 10**18
        v["packUnitsMask"] |= 1 << 30
    return v


def plan():
    return dict(
        name=f"position-integration-local-{FORK_BLOCK}", endpoint=RPC, chain_id=1,
        node_command=["anvil", "--host", "127.0.0.1", "--port", str(PORT), "--accounts", "0", "--silent",
                      "--fork-url", FORK_RPC, "--fork-block-number", str(FORK_BLOCK), "--fork-retry-backoff", "5000",
                      "--retries", "30", "--base-fee", "150000000",
                      "--code-size-limit", str(CODE_SIZE), "--gas-limit", str(MAX_GAS), "--enable-tx-gas-limit"],
        signers=ACTORS, funding_wei_per_actor=ACTOR_ETH, aggregate_funding_wei=6 * ACTOR_ETH,
        external_test_signer=dict(address=ORACLE_OWNER, target=ORACLE, action="setFloor(packs,ask)",
                                  added_funding_wei=0, preconditions="pinned owner/code/nonce/balance readback; existing balance funds gas"),
        per_transaction_gas_limit=MAX_GAS, runtime_code_limit=CODE_SIZE, production_broadcasts=0,
        launch_values=values(), calibration_values=values(True),
        phase_isolation="evm_snapshot/revert reuses the single funded baseline between phases; no second balance credit",
        phases=[
            "Fresh production script/deploy.sh deployment and postflight; mainnet-values lifecycle using normal keeper/index, restart, tokens/burn, oracle kick, policy swap, gas spike, redemption, wind-down",
            "Fresh production deployment for the holder workflow and a separate owner wind-down (rehearse_current.py), mainnet values and budgets; restart normal keeper; holder-run exits with loss limits",
            "Fresh12ETH test-only calibration vault, same budgets; <=6ETH deposits by each of two holders; masks3+30; max16 listing/unlisting/harvest/token/sync items, total30Shapes restock/liquidation, exact fee witness checkpoints",
            "Genuine external FWA acquire requests in bounded batches, expire through real processor, measure1/16 refunded global journal entries and higher gas; withdraw actual refund; no fabricated VRF success",
        ],
        limitations=["Successful foreign selections use recorded real request/fulfillment replay in Forge; local request block hashes cannot reproduce their VRF proofs.",
                     "No failed NFT delivery is manufactured; no mainnet deployment, live funds or owner signature.",
                     "Quotes and headroom remain provisional until this approved batch executes; every action stops on mismatch."],
    )


def load_manifest():
    path = os.environ.get(ENV_MANIFEST)
    if not path:
        raise RuntimeError("run only inside the explicitly owner-approved keeper/rehearsal_batch.py batch")
    m = json.loads(Path(path).read_text())
    if m["endpoint"] != RPC or m["fork_block"] != FORK_BLOCK or m["max_gas"] != MAX_GAS:
        raise RuntimeError("local batch boundaries changed")
    # PID ownership prevents treating an arbitrary loopback proxy or unrelated Anvil as our node.
    owners = raw("lsof", "-nP", f"-tiTCP:{PORT}", "-sTCP:LISTEN").splitlines()
    if set(owners) != {str(m["pid"])}:
        raise RuntimeError("endpoint is not exclusively owned by this task's Anvil process")
    os.kill(m["pid"], 0)
    if "anvil" not in rpc("web3_clientVersion").lower() or quantity(rpc("eth_chainId")) != 1:
        raise RuntimeError("endpoint is not the expected Anvil mainnet fork")
    info = rpc("anvil_nodeInfo")
    fork = info.get("forkConfig") or {}
    if (str(fork.get("forkUrl")).rstrip("/") != FORK_RPC.rstrip("/")
            or quantity(fork.get("forkBlockNumber", -1)) != FORK_BLOCK):
        raise RuntimeError(scrub(f"unexpected Anvil fork metadata: {fork}"))
    if rpc("eth_getBlockByNumber", hex(FORK_BLOCK), False)["hash"] != m["fork_hash"]:
        raise RuntimeError("fork base block hash changed")
    return m


def append_action(record):
    m = load_manifest()
    import tx
    record["loaded_client"] = tx.client_identity([sys.modules[__name__], sys.modules.get("rehearse_canary"),
                                                  sys.modules.get("keeper"), sys.modules.get("policy"),
                                                  sys.modules.get("index"), tx])
    record["client_source_sha256"] = {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
                                      for path in ("keeper/keeper.py", "keeper/policy.py", "keeper/rehearsal_batch.py")}
    if CURRENT_DEPLOYMENT is not None:
        record["vault_context"] = CURRENT_DEPLOYMENT
    with open(m["actions"], "a") as f:
        f.write(scrub(json.dumps(record)) + "\n")


def prepare_actor(address):
    m = load_manifest()
    address = address.lower()
    if address in {v.lower() for v in ACTORS.values()}:
        if address not in m["funding"]:
            raise RuntimeError("fresh actor was not verified clean before funding")
        return  # funded once by the batch owner, never topped up by a phase
    if address != ORACLE_OWNER.lower():
        raise RuntimeError("unnamed rehearsal signer")
    if cast("code", address) != "0x":
        raise RuntimeError("external test signer has code or a delegation")
    if quantity(cast("balance", address)) == 0:
        raise RuntimeError("oracle test signer has no gas; funding it is outside the batch")
    rpc("anvil_impersonateAccount", address)


def pending_fees():
    import keeper as K
    old = K.RPC
    K.RPC = RPC
    try:
        _, base = K.inclusion_context()
    finally:
        K.RPC = old
    return base, ["--gas-price", str(2 * base + 50_000_000), "--priority-gas-price", "50000000"]


def send(frm, to, sig, args, value=0, expect=True):
    m = load_manifest()
    prepare_actor(frm)
    target_code = cast("code", to)
    if target_code == "0x":
        raise RuntimeError("transaction target has no deployed code")
    nonce = quantity(cast("nonce", frm))
    base, fees = pending_fees()
    action = dict(sender=frm, nonce=nonce, to=to,
                  target_runtime_sha256=hashlib.sha256(bytes.fromhex(target_code[2:])).hexdigest(), function=sig, arguments=list(args), value_wei=value,
                  expected_success=expect)
    if value < 0 or value > ACTOR_ETH or quantity(cast("balance", frm)) < value:
        raise RuntimeError("native transfer exceeds named signer funding")
    calldata = raw("cast", "calldata", sig, *map(str, args))
    action["calldata"] = calldata
    estimate = subprocess.run(["cast", "estimate", to, sig, *map(str, args), "--from", frm,
                               "--value", str(value), "--block", "pending", "--rpc-url", RPC, *fees], capture_output=True, text=True)
    if estimate.returncode:
        if not expect:
            action["preflight_rejected"] = estimate.stderr[-1000:]
            append_action(action)
            return False  # expected denial is demonstrated without an unnecessary failed broadcast
        raise RuntimeError(f"preflight failed: {action}: {estimate.stderr}")
    gas = (quantity(estimate.stdout.strip().split()[0]) * 5 + 3) // 4
    if gas > MAX_GAS:
        raise RuntimeError(f"25% gas margin exceeds per-transaction bound: {gas}")
    if quantity(cast("balance", frm)) < value + gas * (2 * base + 50_000_000):
        raise RuntimeError("named signer cannot cover the exact value and bounded maximum gas")
    rec = json.loads(cast("send", to, sig, *map(str, args), "--from", frm, "--unlocked", "--json",
                          "--nonce", nonce, "--value", value, "--gas-limit", gas, *fees))
    ok = quantity(rec["status"]) == 1
    action.update(receipt=rec, gas_limit=gas, post_nonce=quantity(cast("nonce", frm)))
    append_action(action)
    if ok != expect or action["post_nonce"] != nonce + 1 or quantity(rec["gasUsed"]) > MAX_GAS:
        raise RuntimeError(f"receipt/post-state mismatch: {action}")
    return ok


def deploy(v, label):
    global CURRENT_DEPLOYMENT
    load_manifest()
    frozen = source_freeze()
    path = ROOT / "deploy" / f"rehearse-{label}.json"
    if path.exists():
        raise RuntimeError(f"refusing to overwrite existing values: {path}")
    path.write_text(json.dumps(v, indent=2) + "\n")
    try:
        # Price the broadcast above the node's current base fee. The fork runs at a fixed --base-fee
        # (plan()), but forge otherwise estimates from the forked block's lower history and underprices
        # ("max fee per gas less than block base fee"). Read the pending base fee directly (not through
        # inclusion_context, whose deterministic-next-block check rejects the forced --base-fee on a
        # fresh fork before any block is mined).
        deploy_base = quantity(rpc("eth_getBlockByNumber", "pending", False)["baseFeePerGas"])
        env = {**os.environ, "RPC_URL": RPC,
               "FORGE_WALLET_ARGS": f"--unlocked --sender {ACTORS['deployer']} --with-gas-price {2 * deploy_base + 50_000_000}",
               "FOUNDRY_GAS_LIMIT": str(MAX_GAS)}
        # Forge's offchain script harness embeds creation code and exceeds EIP170. Keep its
        # default harness behavior; the actual Anvil node enforces24576 on every deployment.
        env.pop("FOUNDRY_CODE_SIZE_LIMIT", None)
        result = subprocess.run(["script/deploy.sh", str(path.relative_to(ROOT)), "--broadcast"], cwd=ROOT,
                                env=env, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
    finally:
        path.unlink()
    run = json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
    deployments = []
    for t in run["transactions"]:
        h = t["hash"]
        receipt = rpc("eth_getTransactionReceipt", h)
        if not receipt or quantity(receipt["status"]) != 1 or quantity(receipt["gasUsed"]) > MAX_GAS:
            raise RuntimeError(f"deployment receipt mismatch: {h}")
        if t.get("contractAddress") and t.get("transactionType") in ("CREATE", "CREATE2"):
            code = cast("code", t["contractAddress"])
            size = (len(code) - 2) // 2
            if size > CODE_SIZE:
                raise RuntimeError(f"deployed runtime exceeds EIP170: {size}")
            deployments.append(dict(name=t.get("contractName"), address=t["contractAddress"], runtime_bytes=size,
                                    gas_used=quantity(receipt["gasUsed"]),
                                    runtime_sha256=hashlib.sha256(bytes.fromhex(code[2:])).hexdigest(), receipt=receipt))
    for reference in run.get("libraries", []):
        source, name, address = reference.rsplit(":", 2)
        code = bytes.fromhex(cast("code", address)[2:])
        artifact = json.loads((ROOT / "out" / Path(source).name / f"{name}.json").read_text())["deployedBytecode"]
        # The compiled object carries __$...$__ placeholders where linked library addresses are
        # injected at deploy time (a library that calls another library); zero those hex positions
        # before parsing, then zero link and immutable references in both and compare the rest.
        obj = list(artifact["object"].removeprefix("0x"))
        offsets = [o for libs in artifact.get("linkReferences", {}).values()
                   for refs in libs.values() for o in refs]
        for o in offsets:
            obj[o["start"] * 2:(o["start"] + o["length"]) * 2] = "0" * (o["length"] * 2)
        compiled = bytearray.fromhex("".join(obj))
        actual = bytearray(code)
        offsets += [o for refs in artifact.get("immutableReferences", {}).values() for o in refs]
        for o in offsets:
            start, length = o["start"], o["length"]
            actual[start:start + length] = compiled[start:start + length] = bytes(length)
        if actual != compiled or len(code) > CODE_SIZE:
            raise RuntimeError("linked library runtime differs from frozen compiled artifact or exceeds EIP170")
        if not any(d["address"].lower() == address.lower() for d in deployments):
            deployments.append(dict(name=name, address=address, runtime_bytes=len(code),
                                    runtime_sha256=hashlib.sha256(code).hexdigest(), reused=True,
                                    artifact_match=True, gas_used=None, receipt=None))
    vault = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault")
    if cast("call", vault, "owner()(address)").lower() != v["owner"].lower():
        raise RuntimeError("vault owner postflight mismatch")
    unchanged = source_freeze() == frozen
    CURRENT_DEPLOYMENT = dict(vault=vault, source_sha256=frozen, source_unchanged_during_deploy=unchanged,
                              runtimes=[{k: x[k] for k in ("name", "address", "runtime_bytes", "runtime_sha256")}
                                        for x in deployments])
    append_action(dict(operation="production deployment", values=v, deployments=deployments,
                       postflight_output=result.stdout, vault=vault, source_sha256=frozen))
    if not unchanged:
        raise RuntimeError("source changed during deployment; immutable runtime receipts preserved, stop for reconciliation")
    return vault


def run_approved(calibration_first=False):
    if os.environ.get(ENV_MANIFEST):
        raise RuntimeError("refusing nested or inherited rehearsal batch")
    with socket.socket() as s:
        s.bind(("127.0.0.1", PORT))  # fail before spawning if any service already owns the endpoint
    work = Path(tempfile.mkdtemp(prefix="pack-vault-integration-batch-"))
    node_log = open(work / "anvil.log", "w")
    proc = subprocess.Popen(plan()["node_command"], stdout=node_log, stderr=subprocess.STDOUT, cwd=ROOT)
    manifest = work / "manifest.json"
    try:
        for _ in range(150):
            if proc.poll() is not None:
                raise RuntimeError(f"Anvil stopped; see {work / 'anvil.log'}")
            try:
                header = rpc("eth_getBlockByNumber", hex(FORK_BLOCK), False)
                break
            except (RuntimeError, json.JSONDecodeError):
                time.sleep(0.2)
        else:
            raise RuntimeError("Anvil did not become readable")
        m = dict(endpoint=RPC, fork_block=FORK_BLOCK, max_gas=MAX_GAS, pid=proc.pid,
                 fork_hash=header["hash"], actions=str(work / "actions.jsonl"), funding={})
        manifest.write_text(json.dumps(m, indent=2))
        os.environ[ENV_MANIFEST] = str(manifest)
        load_manifest()
        if quantity(cast("block-number")) != FORK_BLOCK:
            raise RuntimeError("new node is not at the requested initial fork block")
        # Every check precedes every funding mutation. No external protocol balance/state is faked.
        for address in ACTORS.values():
            if cast("code", address) != "0x" or quantity(cast("nonce", address)) or quantity(cast("balance", address)):
                raise RuntimeError(f"fresh actor is not clean: {address}")
        for address in ACTORS.values():
            rpc("anvil_impersonateAccount", address)
            rpc("anvil_setBalance", address, hex(ACTOR_ETH))
            m["funding"][address.lower()] = dict(before_code="0x", before_nonce=0, before_balance=0, funded=ACTOR_ETH)
        manifest.write_text(json.dumps(m, indent=2))
        env = {**os.environ, "FOUNDRY_GAS_LIMIT": str(MAX_GAS)}
        env.pop("FOUNDRY_CODE_SIZE_LIMIT", None)
        baseline = rpc("evm_snapshot")
        # Unified system (D77): one build-and-list strategy on PackVault plus permissionless
        # PackManager clones. rehearse_unified.py is the whole end-to-end rehearsal. The pre-A3
        # restock/split phase and calibration scripts are retired; gas is recalibrated from the
        # rehearsal's own keeper receipts and the ForkMaxBatchGas Forge suite.
        scripts = PHASES or ["rehearse_unified.py"]
        for number, script in enumerate(scripts):
            if number:
                if not rpc("evm_revert", baseline):
                    raise RuntimeError("could not restore approved phase baseline")
                baseline = rpc("evm_snapshot")
            attempt = 0
            while True:
                attempt += 1
                path = work / f"{number}-{script}-attempt{attempt}.log"
                print(f"START phase={script} log={path} manifest={manifest}", flush=True)
                result = subprocess.run([sys.executable, str(ROOT / "keeper" / script)], cwd=ROOT, env=env,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                path.write_text(scrub(result.stdout))
                if not result.returncode:
                    break
                print(f"PAUSED phase={script} exit={result.returncode} log={path}; node and ledger preserved. "
                      "Type retry only after reconciling the failure; stopping preserves the node.", flush=True)
                if input().strip() != "retry":
                    raise RuntimeError("batch stopped at a preserved phase failure")
                # Explicit snapshot recovery retires the failed local branch after its receipts
                # have been recorded; it never blindly reuses a partial deployment's nonce.
                if not rpc("evm_revert", baseline):
                    raise RuntimeError("failed phase baseline recovery refused")
                baseline = rpc("evm_snapshot")
            if calibration_first and number == 0:
                print(f"PAUSED_FOR_SOURCEQUOTE manifest={manifest}; calibration complete. "
                      "Type continue only after final quote freeze.", flush=True)
                if input().strip() != "continue":
                    raise RuntimeError("batch stopped before final holder phases")
        print(f"local batch complete; receipts, funding and logs: {work}")
    finally:
        # Preserve the approved fork and receipts for readback or a separately authorized resume.
        print(f"Anvil preserved pid={proc.pid}; work directory={work}", flush=True)
        node_log.close()
        os.environ.pop(ENV_MANIFEST, None)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--plan", action="store_true")
    group.add_argument("--execute-approved-local-batch", action="store_true")
    parser.add_argument("--calibration-first", action="store_true", help="approved calibration first; keep node paused until source quote freeze")
    parser.add_argument("--fork-block", type=int, help="fresh pinned block for a new campaign")
    parser.add_argument("--port", type=int)
    parser.add_argument("--phases", nargs="+", help="phase scripts to run, in order (default: all three)")
    args = parser.parse_args()
    # Phase scripts are child processes: they read the same pins from the environment.
    if args.fork_block or args.port:
        if args.fork_block:
            os.environ["PACK_VAULT_FORK_BLOCK"] = str(args.fork_block)
        if args.port:
            os.environ["PACK_VAULT_LOCAL_PORT"] = str(args.port)
        os.execv(sys.executable, [sys.executable, __file__, *[a for a in sys.argv[1:] if a not in
                 ("--fork-block", str(args.fork_block), "--port", str(args.port))]])
    PHASES = args.phases
    if args.plan:
        print(scrub(json.dumps(plan(), indent=2)))
    else:
        run_approved(args.calibration_first)
