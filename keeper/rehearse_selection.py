#!/usr/bin/env python3
"""Real-FWA-VRF selection outcomes on a local historical fork (keep / bid / expiry / relist /
forced-keep recovery), for the unified Shape-pack rehearsal.

    python3 keeper/rehearse_selection.py --port <free, not 8545> [--block 26310896]

FWA's VRF proof cannot be replayed on anvil (the real request lands in an anvil block with a
different hash, so the coordinator's blockhash/proof check fails). Instead this forks at the primary
fixture's request block minus one, posts the 30 real listings at the backing sim/find_selection.py
searched against, replays the REAL request transaction (impersonating its real sender), then
impersonates the REAL VRF coordinator and calls FWA's real `rawFulfillRandomWords(requestId, [word])`
with the request id the replay produced and the historical random word from sim/data/fwa.sqlite.
FWA, the request and the word stay real; only the coordinator's cryptographic proof check is skipped.
This is disclosed in the receipt. No mock of FWA, Shapes, ShapePacks or the token pool.

Outcomes driven by the real purchaser (keep, bid) or by letting the window lapse (expiry), then the
keeper's own `sync` resolves and books them; the returned (bid) pack is relisted; the forced-keep
case swaps the vault's receiver for a gas-burning `receive` (anvil_setCode) around one real keepNFT
and restores it, so FWA force-sends the keep payment with no CashReceipt (pendingReceipts()==0) and
the keeper must still discover and sync it.
"""
import argparse
import json
import re
import os
import secrets
import socket
import subprocess
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Tenderly's public gateway by default. REHEARSAL_FORK_RPC (environment only) can name another
# upstream for the fork; its URL can carry an API key, so scrub() removes it from every record.
FORK_RPC = os.environ.get("REHEARSAL_FORK_RPC") or "https://mainnet.gateway.tenderly.co"


def scrub(text):
    text = text.replace(FORK_RPC, "<fork-rpc>") if "tenderly" not in FORK_RPC else text
    return re.sub(r"(https?://[^\s\"']*/v[0-9]+/)[A-Za-z0-9_-]{8,}", r"\1<key>", text)

FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
PACKS = "0xf21514B090Da7dF4390803497d6ae673801E5cA7"
SHAPES = "0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0"
COORDINATOR = "0xD7f86b4b8Cae7D942340FF628F82735b7a20893a"  # mainnet Chainlink VRF 2.5 coordinator
B = 64_896_174_863_380_000  # edge(6); the backing find_selection searched; weight = 1e36 / B
PRIMARY_BLOCK = 26_310_897
PRIMARY_INDEX = 22
PRIMARY_SLOT = 3724
PRIMARY_PURCHASER = "0x88d0e89E7f502Aa49a564b683e19089c771776c3"
ACQ_REQUESTED_T0 = "0xf23e34f4aa4a06ecddd309d9692e7b7ca45b76fd0d5f4ce4f7fbf29731d9abd6"
LISTING_ALLOCATED, LISTING_ACTIVE, LISTING_SETTLED, LISTING_WITHDRAWN = 2, 1, 4, 3
E = 10**18
MAX_GAS = 16_777_216
PARAMS_T = ("(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,uint64,uint64,"
            "uint64,uint64,uint64,uint128,uint128)")
PARAMS_ORDER = ["minEdgeBps", "bufferBps", "distributionBps", "payMarkupBps", "keeperShareBps",
                "allocatedBoundBps", "packUnitsMask", "gasCeilingWei", "essentialCeilingWei", "maxTipWei",
                "workFeeWei", "routineCapWei", "routineRatePerDayWei", "essentialCapWei",
                "essentialRatePerDayWei", "reserveWei", "tvlCapWei"]

RPC = None


def sh(*args, check=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def cast(*a):
    return sh("cast", *a, "--rpc-url", RPC)


def num(v):
    v = v.split(" ")[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def rpc(method, *params):
    return json.loads(cast("rpc", method, *[json.dumps(p) if not isinstance(p, str) else p for p in params]))


def pending_base():
    return num(rpc("eth_getBlockByNumber", "pending", False)["baseFeePerGas"])


def fees():
    return ["--gas-price", str(2 * pending_base() + 50_000_000), "--priority-gas-price", "50000000"]


def send(frm, to, sig, *a, value=0):
    rpc("anvil_impersonateAccount", frm)
    f = fees()
    # Pad the gas limit well above the bare estimate: a reentrancy-guarded function (createPack,
    # listNFT) trips ReentrancySentryOOG if the limit equals the estimate (no sentry headroom).
    est = subprocess.run(["cast", "estimate", to, sig, *map(str, a), "--from", frm, "--value", str(value),
                          "--rpc-url", RPC, *f], capture_output=True, text=True)
    gl = min(MAX_GAS, num(est.stdout.strip()) * 2) if not est.returncode and est.stdout.strip() else MAX_GAS
    rec = json.loads(sh("cast", "send", to, sig, *map(str, a), "--from", frm, "--unlocked", "--json",
                        "--value", str(value), "--gas-limit", str(gl), "--rpc-url", RPC, *f))
    if num(rec["status"]) != 1:
        reason = ""
        try:  # surface the real revert reason via a static call at the same state
            reason = subprocess.run(["cast", "call", to, sig, *map(str, a), "--from", frm, "--value", str(value),
                                     "--rpc-url", RPC], capture_output=True, text=True).stderr.strip()[-400:]
        except Exception:  # noqa: BLE001
            pass
        raise RuntimeError(f"tx reverted: {sig} from {frm}: {reason}")
    return rec


def listing_status(lid):
    f = cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", lid)
    return num(f.splitlines()[-1])


def fund(addr, wei=100 * E):
    rpc("anvil_setBalance", addr, hex(wei))


def actor(label):
    from eth_utils import keccak, to_checksum_address
    a = to_checksum_address(keccak(text=f"pack-vault-selection-{label}")[-20:])
    if cast("code", a) not in ("0x", ""):
        raise RuntimeError(f"actor {label} {a} not clean")
    fund(a)
    return a


def start_anvil(port, block, log):
    cmd = ["anvil", "--host", "127.0.0.1", "--port", str(port), "--accounts", "0", "--silent",
           "--fork-url", FORK_RPC, "--fork-block-number", str(block), "--fork-retry-backoff", "5000",
           "--retries", "30", "--compute-units-per-second", "100", "--base-fee", "150000000",
           "--code-size-limit", "24576", "--gas-limit", str(MAX_GAS), "--enable-tx-gas-limit"]
    proc = subprocess.Popen(cmd, stdout=open(log, "w"), stderr=subprocess.STDOUT, cwd=ROOT)
    for _ in range(150):
        try:
            if "anvil" in rpc("web3_clientVersion").lower():
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.3)
    else:
        raise RuntimeError("anvil did not start")
    rpc("anvil_autoImpersonateAccount", True)
    return proc


def admit_packs():
    owner = cast("call", FWA, "owner()(address)")
    send(owner, FWA, "setCollectionsWhitelisted(address[],bool)", f"[{PACKS}]", "true")
    send(owner, FWA, "setOracleExemptCollection(address,bool)", PACKS, "true")
    if num(cast("call", FWA, "unsettledAcquisitionCount()(uint256)")) != 0:
        raise RuntimeError("acquisition queue not empty at the selection fork")


def deploy_vault(deployer, seed_wei):
    values = json.loads((ROOT / "deploy/mainnet.json").read_text())
    values["owner"] = actor("owner")
    values["seedWei"] = seed_wei
    values["tvlCapWei"] = 100 * E
    path = ROOT / "deploy/rehearse-selection.json"
    path.write_text(json.dumps(values, indent=1))
    try:
        base = pending_base()
        env = {**os.environ, "RPC_URL": RPC, "FOUNDRY_GAS_LIMIT": str(MAX_GAS),
               "FORGE_WALLET_ARGS": f"--unlocked --sender {deployer} --with-gas-price {2 * base + 50_000_000}"}
        r = subprocess.run(["script/deploy.sh", "deploy/rehearse-selection.json", "--broadcast"],
                           cwd=ROOT, env=env, capture_output=True, text=True)
        if r.returncode:
            raise RuntimeError(r.stdout + r.stderr)
    finally:
        path.unlink(missing_ok=True)
    run = json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
    return (next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault"),
            values["owner"])


def create_pack_and_list(filler):
    """One filler listing at backing B (ReceiptFixtureFiller.createAndList reproduced by an EOA)."""
    mint_fee = num(cast("call", SHAPES, "mintFee()(uint256)"))
    counts = "[3,0,0,0,0,0,0,0,0]"
    rec = send(filler, PACKS, "createPack(uint256[],uint32[])", "[]", counts, value=3 * 10**16 + 3 * mint_fee)
    pack = _packid_from_logs(rec, filler)
    if cast("call", PACKS, "isApprovedForAll(address,address)(bool)", filler, FWA) != "true":
        send(filler, PACKS, "setApprovalForAll(address,bool)", FWA, "true")
    r = send(filler, FWA, "listNFT(address,uint256)", PACKS, pack, value=B)
    return _listing_from_logs(r)


def _has(addr, sigargs):
    try:
        cast("call", addr, *sigargs.split(" "))
        return True
    except Exception:  # noqa: BLE001
        return False


def _packid_from_logs(rec, owner):
    # ERC721 Transfer(from=0, to=owner, tokenId) from PACKS.
    topic = "0x" + "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
    for log in rec["logs"]:
        if log["address"].lower() == PACKS.lower() and log["topics"] and log["topics"][0] == topic \
                and num(log["topics"][1]) == 0 and num(log["topics"][2]) == num(owner):
            return num(log["topics"][3])
    raise RuntimeError("no ShapePack mint in createPack receipt")


def _listing_from_logs(rec):
    # NFTListed(listingId indexed, slot indexed, depositor indexed, ...).
    topic = "0x01c953cf171a8c32b553c5b7e0964bae6b2123db065615e54e8425fec3ec16cd"
    for log in rec["logs"]:
        if log["address"].lower() == FWA.lower() and log["topics"] and log["topics"][0] == topic:
            return num(log["topics"][1]), num(log["topics"][2])
    raise RuntimeError("no NFTListed in listNFT receipt")


def historical_word(request_id):
    """The real random word for this request id, from sim/data/fwa.sqlite (RandomnessCached)."""
    db = ROOT / "sim/data/fwa.sqlite"
    if not db.exists():
        raise RuntimeError("sim/data/fwa.sqlite is required for the historical VRF word")
    con = sqlite3.connect(str(db))
    for (args,) in con.execute("SELECT args FROM logs WHERE event='RandomnessCached'"):
        a = json.loads(args)
        if int(a["requestId"]) == request_id:
            return int(a["randomWord"])
    raise RuntimeError(f"no RandomnessCached word for request {request_id}")


def replay_request_and_fulfill(fixture, vault):
    """Post 30 listings at B with the vault's at the fixture index, replay the real request, then
    impersonate the coordinator and deliver the real word. Returns the allocated listing id."""
    fx = fixture[str(PRIMARY_BLOCK)]
    # 22 fillers, our vault listing, 7 fillers -> our listing lands at the fixture slot.
    fillers = [actor(f"filler{i}") for i in range(29)]
    selected = None
    fi = 0
    for pos in range(30):
        if pos == PRIMARY_INDEX:
            send(actor("builder"), vault, "build(uint256,uint256[],uint256)", 6, f"[{B}]", 0)
            selected = num(cast("call", vault, "openListingAt(uint256)(uint256)", 0))
        else:
            create_pack_and_list(fillers[fi]); fi += 1
    slot = num(cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", selected).splitlines()[8])
    if slot != PRIMARY_SLOT:
        raise RuntimeError(f"slot prediction failed: {slot} != {PRIMARY_SLOT}")
    # Replay the real request tx verbatim from its real sender.
    rpc("anvil_impersonateAccount", fx["reqFrom"])
    rec = json.loads(sh("cast", "send", fx["reqTo"], fx["reqInput"], "--from", fx["reqFrom"], "--unlocked",
                        "--json", "--value", str(fx["reqValue"]), "--gas-price", str(fx["reqGasPrice"]),
                        "--priority-gas-price", "0", "--rpc-url", RPC))
    if num(rec["status"]) != 1:
        raise RuntimeError("real request replay reverted")
    request_id = next(num(log["topics"][1]) for log in rec["logs"]
                      if log["address"].lower() == FWA.lower() and log["topics"][0] == ACQ_REQUESTED_T0)
    word = historical_word(request_id)
    fund(COORDINATOR)
    # The coordinator-only VRF callback caches the real word (RandomnessCached); FWA runs the actual
    # selection in its permissionless processor (AcquisitionProcessed -> NFTAllocated), so process the
    # queue after caching. This keeps the word and the selection FWA's own; only the proof is skipped.
    send(COORDINATOR, FWA, "rawFulfillRandomWords(uint256,uint256[])", request_id, f"[{word}]")
    if listing_status(selected) != LISTING_ALLOCATED:
        send(actor("processor"), FWA, "processAcquisitions(uint256)", 16)
    if listing_status(selected) != LISTING_ALLOCATED:
        unsettled = num(cast("call", FWA, "unsettledAcquisitionCount()(uint256)"))
        raise RuntimeError(f"listing not allocated after real-word fulfillment + processing: "
                           f"status {listing_status(selected)}, unsettled {unsettled}, request {request_id}")
    purchaser = cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", selected).splitlines()[2]
    if purchaser.lower() != PRIMARY_PURCHASER.lower():
        raise RuntimeError(f"purchaser mismatch: {purchaser}")
    return selected, request_id, word, purchaser


def keeper_sync(vault, keeper, listing_ids):
    """The keeper applies the selection and resolves it (build+list proved the keeper's send path on
    the recent fork; here we call sync directly as the keeper would, own gas)."""
    ids = "[" + ",".join(map(str, listing_ids)) + "]"
    send(keeper, vault, "sync(uint256[],uint256,uint256)", ids, 0, 0)


def outcome(vault, keeper, kind):
    """Drive one outcome from a fresh snapshot: keep | bid | expiry | forced_keep."""
    fixture = json.loads((ROOT / "test/fixtures/selection.json").read_text())
    snap = rpc("evm_snapshot")
    try:
        return _outcome_body(vault, keeper, kind, fixture)
    finally:
        rpc("evm_revert", snap)  # always restore, even on error, so outcomes never corrupt each other


def _outcome_body(vault, keeper, kind, fixture):
    selected, request_id, word, purchaser = replay_request_and_fulfill(fixture, vault)
    result = dict(kind=kind, listing=selected, request_id=str(request_id), word=str(word),
                  purchaser=purchaser, allocated=True)
    bal0 = num(cast("balance", vault))
    if kind == "keep":
        send(purchaser, FWA, "keepNFT(uint256)", selected)
        keeper_sync(vault, keeper, [selected])
        result.update(fwa_status=listing_status(selected), vault_received_wei=num(cast("balance", vault)) - bal0,
                      resolved=True)
    elif kind == "bid":
        send(purchaser, FWA, "acceptDepositorBid(uint256)", selected)
        keeper_sync(vault, keeper, [selected])
        idle = num(cast("call", vault, "idlePackCount()(uint256)"))
        # Relist the returned pack (step 6).
        send(keeper, vault, "list(uint256[],uint256)", f"[{B}]", 0) if idle else None
        result.update(fwa_status=listing_status(selected), idle_after_bid=idle,
                      relisted_open=num(cast("call", vault, "openListingCount()(uint256)")), resolved=True)
    elif kind == "expiry":
        window = num(cast("call", FWA, "settlementWindow()(uint256)"))
        now = num(cast("block", "latest", "--field", "timestamp"))
        rpc("evm_setNextBlockTimestamp", str(now + window + 1))
        rpc("evm_mine")
        keeper_sync(vault, keeper, [selected])
        result.update(fwa_status=listing_status(selected), vault_reclaimed_wei=num(cast("balance", vault)) - bal0,
                      resolved=True)
    elif kind == "forced_keep":
        # Swap the vault's runtime for a receive() that burns all gas, around exactly one keepNFT, so
        # FWA force-sends the keep payment by SELFDESTRUCT: no CashReceipt, pendingReceipts()==0. Then
        # restore the exact runtime and show the keeper discovers and syncs it (receipt-recovery path).
        real_code = cast("code", vault)
        # A minimal runtime whose receive consumes all gas: PUSH0 ; JUMPDEST ; JUMP (infinite loop).
        burner = "0x5b5f56"  # JUMPDEST; PUSH0; JUMP -> consumes all forwarded gas and reverts
        rpc("anvil_setCode", vault, burner)
        keep_rec = send(purchaser, FWA, "keepNFT(uint256)", selected)
        rpc("anvil_setCode", vault, real_code)  # restore the exact vault runtime
        pending_receipts = num(cast("call", vault, "pendingReceipts()(uint256)"))
        booked_before = _booked_state(vault, selected)
        keeper_sync(vault, keeper, [selected])
        result.update(fwa_status=listing_status(selected), pending_receipts_at_force=pending_receipts,
                      booked_state_before_sync=booked_before, booked_state_after_sync=_booked_state(vault, selected),
                      resolved=True, receive_failed_no_cashreceipt=(pending_receipts == 0))
    return result


def _booked_state(vault, lid):
    try:
        pos = cast("call", vault, "position(uint256)((uint256,uint256,uint256,uint256,uint64,uint8))", lid)
        return num(pos.strip("()").split(", ")[5])
    except Exception:  # noqa: BLE001
        return None


def main():
    global RPC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--block", type=int, default=PRIMARY_BLOCK - 1)
    a = ap.parse_args()
    if a.port == 8545:
        sys.exit("8545 is reserved")
    with socket.socket() as s:
        s.bind(("127.0.0.1", a.port))
    RPC = f"http://127.0.0.1:{a.port}"
    work = Path(tempfile.mkdtemp(prefix="pack-vault-selection-"))
    proc = start_anvil(a.port, a.block, work / "anvil.log")
    report = dict(fork_block=a.block, request_block=PRIMARY_BLOCK, backing=B, coordinator=COORDINATOR,
                  disclosure="real FWA + real request + real historical word; only the VRF coordinator's "
                             "cryptographic proof check is skipped by impersonating the real coordinator address",
                  outcomes={})
    try:
        admit_packs()
        deployer = actor("deployer")
        vault, owner = deploy_vault(deployer, 4 * E)
        keeper = actor("keeper")
        report["vault"] = vault
        for kind in ("keep", "bid", "expiry", "forced_keep"):
            try:
                report["outcomes"][kind] = outcome(vault, keeper, kind)
            except Exception as e:  # noqa: BLE001
                report["outcomes"][kind] = dict(kind=kind, error=str(e)[:400])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except Exception:  # noqa: BLE001
            proc.kill()
    failures = {k: v.get("error") for k, v in report["outcomes"].items() if v.get("error") or not v.get("resolved")}
    report["all_outcomes_passed"] = not failures
    out = ROOT / "docs/receipts/unified-selection-rehearsal.json"
    out.write_text(scrub(json.dumps(report, indent=1, default=str)))
    print(scrub(json.dumps(report, indent=1, default=str)))
    if failures:
        sys.exit(f"selection rehearsal: {len(failures)} outcome(s) failed: {failures}")


if __name__ == "__main__":
    main()
