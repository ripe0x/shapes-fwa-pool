#!/usr/bin/env python3
"""End-to-end local production rehearsal for the unified Shape-pack system (D77).

One command runs the whole thing on a fresh local mainnet fork (never a public write):

    python3 keeper/rehearse_unified.py --fork-block <recent> --port <free, not 8545>

It (re-)execs keeper/rehearsal_batch.py, which owns the Anvil node, the fresh label-derived actors
and the manifest; this file is its single phase. Everything uses the real production paths:
script/deploy.sh (DeployCore, the same code every fork test deploys), the real keeper
(keeper/keeper.py) signing through an encrypted keystore with a durable state volume exactly as
keeper/entrypoint.sh does in the Fly image, and the real FWA/Shapes/ShapePacks contracts. No mocks
of FWA, its VRF, oracle, Shapes, ShapePacks or the token pool.

Covered (see the per-step results in docs/receipts/unified-production-rehearsal.json):
 1 deploy pooled vault + factory          10 restart keeper on its durable state
 2 create several personal managers       11 replace the keeper container (same volume)
 3 fund independent accounts               12 backup keeper (second signer, contending)
 4 keeper discovers every account          13 lost transaction response
 5 build and list fresh packs              14 transaction races / nonce handling
 6 relist returned packs                   15 one account failing, others continue
 7 keep / bid / expiry (real FWA VRF)      16 per-account event index persistence
 8 pooled deposit/checkpoint/redeem/claim  17 reorg: keeper index and books reconcile
 9 manager withdrawals and owner exit      + every account reconciles to the wei

Docker is not required: when it is absent this runs the identical pinned environment and entrypoint
outside Docker and leaves the image steps to CI (.github/workflows/keeper-image.yml). Steps 13-17
reuse the real-vault harnesses keeper/test_tx.py and keeper/test_index.py.

Step 7 note: a faithful real-VRF selection needs the vault to list at the exact backing the fixture
search matched and to fork at the fixture's request block (test/fixtures/selection.json,
sim/find_selection.py). When the live edge(6) backing differs from the fixture era (a recipe or
purchaser-gas change moves it) the fixtures are stale and this step records a gap with the exact
regeneration command rather than fabricate a selection. The keep/bid/expiry outcomes themselves are
proven in the Forge fork suites (ForkSelection/ForkManager/VaultFlow); the keeper-side resolution of
a force-sent terminal payment with no CashReceipt is covered by keeper/test_index.py.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "keeper"))
import rehearsal_batch as B  # noqa: E402

RPC = B.RPC
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
PACKS = "0xf21514B090Da7dF4390803497d6ae673801E5cA7"
# The exact backing sim/find_selection.py searched the shipped selection.json against (the B
# constant in ForkSelection.t.sol). If the live edge(6) backing differs the fixtures are stale.
FIXTURE_BACKING = 65_158_469_945_350_000
FIXTURE_BLOCK = 26_402_342  # primary() in ForkSelection.t.sol (fork at FIXTURE_BLOCK-1)
PARAMS_T = ("(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,uint64,uint64,"
            "uint64,uint64,uint64,uint128,uint128)")
# deploy/manager.json keys in VaultLib.Params struct order (6 u16, 9 u64, 2 u128).
PARAMS_ORDER = ["minEdgeBps", "bufferBps", "distributionBps", "payMarkupBps", "keeperShareBps",
                "allocatedBoundBps", "packUnitsMask", "gasCeilingWei", "essentialCeilingWei", "maxTipWei",
                "workFeeWei", "routineCapWei", "routineRatePerDayWei", "essentialCapWei",
                "essentialRatePerDayWei", "reserveWei", "tvlCapWei"]
E = 10**18
MGR_OWNERS = ["mgra", "mgrb", "mgrc"]
# Named unlocked actors the real-vault harnesses (keeper/test_tx.py, keeper/test_index.py) drive.
HOLDER = B.ACTORS["holder"]
HOLDER2 = B.ACTORS["holder2"]
KEEPER = B.ACTORS["keeper"]      # unlocked signer the recovery/reorg harnesses use
KICKER = B.ACTORS["kicker"]
KEEPER_STATE = None              # harness state file (set in main)
TOKEN = None
VAULT = FACTORY = None
MANAGERS = []
# Keystore keeper (production entrypoint path): its own durable /data volume, separate from KEEPER.
KS_KEEPER = KS_KEYSTORE = KS_PWFILE = KS_STATE = None


# --- thin cast helpers on the batch-owned endpoint (same shapes as rehearse_canary) ---
def sh(*args, check=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT)
    if check and r.returncode:
        sys.exit(f"failed: {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def cast(*a):
    if a and a[0] == "rpc" and len(a) > 1 and a[1].startswith(("anvil_", "evm_")):
        B.load_manifest()
    return sh("cast", *a, "--rpc-url", RPC)


def num(v):
    v = v.split(" ")[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def pricing(to, sig, *a):
    _, fees = B.pending_fees()
    return cast("call", to, sig, *a, "--block", "pending", *fees).split(" ")[0]


def call(to, sig, *a):
    if sig.split("(")[0] in ("edge", "requestCharge", "deployCharge", "unwindCharge"):
        return pricing(to, sig, *a)
    return cast("call", to, sig, *a).split(" ")[0]


def edge3(account, units=6):
    """The pending edge quote (k, backing, ok); call() truncates multi-return reads to one value."""
    _, fees = B.pending_fees()
    out = cast("call", account, "edge(uint256)(uint256,uint256,bool)", units, "--block", "pending", *fees)
    k, backing, ok = out.split("\n")
    return num(k), num(backing), ok.strip() == "true"


def send(frm, to, sig, *a, value=None, expect=True):
    return B.send(frm, to, sig, a, value or 0, expect)


def impersonate(addr):
    B.prepare_actor(addr)


def ids(account=None, inventory="open"):
    account = account or VAULT
    cs, it = (("idlePackCount()(uint256)", "idlePackAt(uint256)(uint256)") if inventory == "idle"
              else ("openListingCount()(uint256)", "openListingAt(uint256)(uint256)"))
    return [num(call(account, it, i)) for i in range(num(call(account, cs)))]


def redeem_charge(shares):
    """PackVault's redemption charge for `shares` now: checkpoint + unwind per position value."""
    value = shares * num(call(VAULT, "lastNav()(uint256)")) // num(call(VAULT, "totalShares()(uint256)"))
    return num(call(VAULT, "requestCharge()(uint256)")) + \
        value * num(call(VAULT, "unwindCharge()(uint256)")) // (663 * 10**14)


def expire_queue():
    """Expire only real pending FWA requests using their snapshotted deadlines, in bounded chunks,
    then let anyone run FWA's real processor. No fabricated success (rehearse_canary pattern)."""
    for _ in range(128):
        if not num(call(FWA, "unsettledAcquisitionCount()(uint256)")):
            return
        cursor = num(call(FWA, "nextSequenceToProcess()(uint64)"))
        last = num(call(FWA, "lastIssuedSequence()(uint64)"))
        deadline = 0
        for seq in range(cursor, min(cursor + 16, last + 1)):
            req = num(call(FWA, "requestIdAtSequence(uint64)(uint256)", seq))
            status = num(cast("call", FWA, "acquisitions(uint256)(address,uint256,uint256,uint256,uint8)", req).splitlines()[-1])
            if status == 1:
                meta = cast("call", FWA, "acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)", req).splitlines()
                deadline = max(deadline, num(meta[1]))
        needed = max(0, deadline + 1 - num(cast("block-number"))) if deadline else 0
        if needed > 7201:
            raise RuntimeError("snapshotted deadline exceeds the deployed protocol bound")
        while needed:
            amount = min(needed, 32)
            cast("rpc", "anvil_mine", hex(amount))
            needed -= amount
        send(KICKER, FWA, "processAcquisitions(uint256)", 16)
        if num(call(FWA, "nextSequenceToProcess()(uint64)")) <= cursor:
            raise RuntimeError("real FWA queue made no completed progress")
    raise RuntimeError("queue exceeds 128 bounded expiry/processor calls")


def warp_to(offset):
    now = num(cast("block", "latest", "--field", "timestamp"))
    nxt = now - now % 43200 + offset
    if nxt <= now:
        nxt += 43200
    cast("rpc", "evm_setNextBlockTimestamp", str(nxt))
    cast("rpc", "evm_mine")


# --- FWA admission (real historical admin calls; needed only before ShapePacks' admission block) ---
def fwa_admit_packs():
    if cast("call", FWA, "oracleExemptCollections(address)(bool)", PACKS) == "true":
        return "already admitted at this fork block"
    owner = cast("call", FWA, "owner()(address)")
    rpc("anvil_impersonateAccount", owner)
    _, fees = B.pending_fees()
    for sig, args in (("setCollectionsWhitelisted(address[],bool)", [f"[{PACKS}]", "true"]),
                      ("setOracleExemptCollection(address,bool)", [PACKS, "true"])):
        rec = json.loads(sh("cast", "send", FWA, sig, *args, "--from", owner, "--unlocked",
                            "--json", "--rpc-url", RPC, *fees))
        if num(rec["status"]) != 1:
            raise RuntimeError(f"FWA admission {sig} reverted")
    return "replayed real setCollectionsWhitelisted + setOracleExemptCollection (FWA owner)"


def rpc(method, *params):
    return B.rpc(method, *params)


# --- manager creation via the real permissionless factory ---
def manager_params():
    v = json.loads((ROOT / "deploy/manager.json").read_text())
    return "(" + ",".join(str(v[k]) for k in PARAMS_ORDER) + ")"


def create_manager(owner_label, seed):
    owner = B.ACTORS[owner_label]
    before = num(call(FACTORY, "managerCount()(uint256)"))
    send(owner, FACTORY, f"create(address,{PARAMS_T})", owner, manager_params(), value=seed)
    after = num(call(FACTORY, "managerCount()(uint256)"))
    if after != before + 1:
        raise RuntimeError("factory.create did not add exactly one manager")
    m = cast("call", FACTORY, "managerAt(uint256)(address)", after - 1)
    if cast("call", FACTORY, "isManager(address)(bool)", m) != "true" or \
            cast("call", m, "owner()(address)").lower() != owner.lower():
        raise RuntimeError("new manager failed factory/owner postflight")
    return m


# --- the real keeper, signing through an encrypted keystore with a durable state volume ---
def new_keystore(label="keeper"):
    """Generate a throwaway encrypted keystore + password in scratch (never the repo, never logged),
    exactly the pair keeper/entrypoint.sh feeds cast as --keystore/--password-file. Returns
    (keystore_file, password_file, address), funded for gas."""
    scratch = Path(tempfile.mkdtemp(prefix=f"pack-vault-{label}-"))
    (scratch / "keystores").mkdir()
    os.chmod(scratch, 0o700)
    import secrets
    pw = secrets.token_hex(24)
    pwf = scratch / f"{label}.pw"
    pwf.write_text(pw)
    os.chmod(pwf, 0o600)
    sh("cast", "wallet", "new", str(scratch / "keystores"), label, "--unsafe-password", pw)
    ks = next((scratch / "keystores").iterdir())
    addr = sh("cast", "wallet", "address", "--keystore", str(ks), "--password-file", str(pwf))
    if cast("code", addr) != "0x":
        raise RuntimeError("fresh keystore signer is not clean")
    rpc("anvil_setBalance", addr, hex(50 * E))
    return str(ks), str(pwf), addr


def keeper_identity():
    global KS_KEYSTORE, KS_PWFILE, KS_KEEPER, KS_STATE
    KS_KEYSTORE, KS_PWFILE, KS_KEEPER = new_keystore("keeper")
    KS_STATE = str(Path(KS_KEYSTORE).parent.parent / "data")  # the durable /data volume
    Path(KS_STATE).mkdir()
    return dict(keeper=KS_KEEPER, keystore_env="encrypted keystore + password file (entrypoint.sh), scratch only",
                state_volume=KS_STATE)


def run_keeper(*extra, state_dir=None, keeper_addr=None, keystore=None, pwfile=None, loop_once=True, tag="keeper"):
    """One bounded keeper invocation exactly as the Fly entrypoint runs it: keystore signing, the
    durable /data volume for state and the per-account indexes, --factory discovery. Retries only a
    read that failed on the throttled public fork gateway; asserts clean receipts under the gas cap."""
    state_dir = state_dir or KS_STATE
    keystore = keystore or KS_KEYSTORE
    pwfile = pwfile or KS_PWFILE
    keeper_addr = keeper_addr or KS_KEEPER
    B.load_manifest()
    for _ in range(16):
        cmd = ["python3", "keeper/keeper.py", VAULT, "--factory", FACTORY, "--send",
               "--keystore", keystore, "--password-file", pwfile, "--rpc", RPC,
               "--state", str(Path(state_dir) / "keeper-state.json"), "--index", state_dir,
               "--confirmations", "1", "--pending-timeout", "90", *extra]
        for _ in range(6):
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
            out = r.stdout + r.stderr
            if not r.returncode or "read failed" not in out:
                break
        print(f"  [{tag}] " + out.replace("\n", "\n  "), flush=True)
        if r.returncode:
            raise RuntimeError(f"keeper exited {r.returncode}: {out[-2000:]}")
        statef = Path(state_dir) / "keeper-state.json"
        if "event index at block" not in out and statef.exists():
            saved = json.loads(statef.read_text())
            bad = [e for e in saved["counted"] if not e.get("reorged") and (not e["status"] or e["gas_limit"] > B.MAX_GAS)]
            if bad:
                raise RuntimeError(f"keeper receipt status/gas-limit mismatch: {bad[:2]}")
            B.append_action(dict(operation=f"keeper ({tag})", arguments=list(extra), output=out[-4000:],
                                 keeper=keeper_addr or KEEPER, tx_state=saved))
            return saved
        if loop_once and "event index at block" not in out:
            return json.loads(statef.read_text()) if statef.exists() else {}
    raise RuntimeError("keeper index reconstruction exceeded 16 bounded passes")


def catch_up_and_build():
    """Run the keeper until every discovered account's index is caught up and no more routine work
    is planned (bounded). Returns the final keeper state."""
    saved = {}
    for _ in range(40):
        saved = run_keeper(tag="routine")
        counts = {a: num(call(a, "openListingCount()(uint256)")) for a in [VAULT] + MANAGERS}
        if all(c for a, c in counts.items() if a in MANAGERS):
            # every capital-funded manager has listed; one more pass settles the vault if funded
            run_keeper(tag="routine")
            break
    return saved


# --- account reconciliation to the wei ---
def account_snapshot(account, pooled):
    s = dict(account=account, pooled=pooled, balance=num(cast("balance", account)),
             open=num(call(account, "openListingCount()(uint256)")),
             idle=num(call(account, "idlePackCount()(uint256)")),
             idle_eth=num(call(account, "idleEth()(uint256)")))
    if pooled:
        s.update(total_shares=num(call(account, "totalShares()(uint256)")),
                 dead_shares=num(call(account, "DEAD_SHARES()(uint256)")),
                 locked_shares=num(call(account, "lockedShares()(uint256)")),
                 last_nav=num(call(account, "lastNav()(uint256)")))
    else:
        s.update(winding_down=cast("call", account, "windingDown()(bool)") == "true"
                 if _has(account, "windingDown()(bool)") else None)
    return s


def _has(account, sig):
    try:
        cast("call", account, sig)
        return True
    except subprocess.CalledProcessError:
        return False


def main():
    global VAULT, FACTORY, MANAGERS
    report = dict(fork_block=B.FORK_BLOCK, fork_hash=B.load_manifest()["fork_hash"], rpc=RPC,
                  docker=bool(shutil.which("docker")), steps={}, gaps=[])
    for actor in B.ACTORS.values():
        impersonate(actor)

    # 1. Deploy the pooled vault and the factory through the production path.
    values = json.loads((ROOT / "deploy/canary.json").read_text())
    values["owner"] = B.ACTORS["owner"]
    VAULT = B.deploy(values, "unified")
    FACTORY = next(t["contractAddress"] for t in
                   json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())["transactions"]
                   if t.get("contractName") == "PackManagerFactory")
    global TOKEN
    TOKEN = call(FWA, "token()(address)")
    report["vault"], report["factory"] = VAULT, FACTORY
    admit = fwa_admit_packs()
    k, backing, ok = edge3(VAULT, 6)
    report["steps"]["1_deploy"] = dict(vault=VAULT, factory=FACTORY, fwa_admission=admit,
                                       edge6_backing=backing, edge6_ok=ok, k=k)

    # 2-3. Create several personal managers for different owners, funded independently at create.
    MANAGERS = [create_manager(lbl, 1 * E) for lbl in MGR_OWNERS]
    report["steps"]["2_managers"] = [dict(manager=m, owner=B.ACTORS[lbl], seed_wei=E)
                                     for m, lbl in zip(MANAGERS, MGR_OWNERS)]
    report["steps"]["3_fund"] = dict(managers_seeded_wei=E, vault_seed_wei=values["seedWei"],
                                     keeper_funded=True)

    # 4-5. One keeper discovers every account and builds+lists fresh packs on each funded account.
    keeper_identity()
    report["steps"]["4_discovery"] = dict(keeper=KEEPER, discovers=[VAULT] + MANAGERS)
    catch_up_and_build()
    built = {a: num(call(a, "openListingCount()(uint256)")) for a in [VAULT] + MANAGERS}
    report["steps"]["5_build_list"] = dict(open_listings=built,
                                           keeper_stats=json.load(open(Path(KS_STATE) / "keeper-state.json"))["stats"])

    # Remaining steps are orchestrated by rehearse_unified_steps (kept here for readability).
    global KEEPER_STATE
    KEEPER_STATE = str(Path(tempfile.mkdtemp(prefix="pack-vault-harness-")) / "state.json")
    import rehearse_unified_steps as steps  # noqa: E402  (same directory)
    steps.run(sys.modules[__name__], report)

    errors = {k: v["error"] for k, v in report["steps"].items() if isinstance(v, dict) and v.get("error")}
    report["errors"] = errors
    (ROOT / "docs/receipts/unified-production-rehearsal.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report["steps"].items()}, indent=1, default=str))
    print(f"gaps: {report['gaps']}")
    if errors:
        sys.exit(f"rehearsal: {len(errors)} step(s) errored: {list(errors)}")


def launch():
    """`python3 keeper/rehearse_unified.py --fork-block N --port P`: hand off to the batch launcher
    that owns the Anvil node and funds the fresh actors, with this file as its single phase."""
    import argparse
    ap = argparse.ArgumentParser(description="Unified system end-to-end local production rehearsal")
    ap.add_argument("--fork-block", type=int, required=True)
    ap.add_argument("--port", type=int, required=True, help="free local port (not 8545)")
    a = ap.parse_args()
    if a.port == 8545:
        sys.exit("port 8545 is reserved for another tool; pick another")
    cmd = [sys.executable, str(ROOT / "keeper/rehearsal_batch.py"), "--execute-approved-local-batch",
           "--fork-block", str(a.fork_block), "--port", str(a.port), "--phases", "rehearse_unified.py"]
    os.execv(sys.executable, cmd)


if __name__ == "__main__":
    if os.environ.get(B.ENV_MANIFEST):
        main()  # running as the batch phase
    else:
        launch()
