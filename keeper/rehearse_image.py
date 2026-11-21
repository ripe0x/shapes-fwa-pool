#!/usr/bin/env python3
"""Production keeper image against a fresh local mainnet fork, signing with encrypted keystores.

  python3 keeper/rehearse_image.py --image <tag> [--fork-block N]   # CI: the image Fly deploys
  python3 keeper/rehearse_image.py                                  # host processes, for debugging

Starts its own Anvil fork (Tenderly's public gateway), deploys through script/deploy.sh with
deploy/canary.json values (a fresh test owner), creates two disposable encrypted keystores (primary
and backup keepers; random passwords that never leave this process tree), and then checks:
startup through keeper/entrypoint.sh, pricing and listing by the primary for the pooled vault and
for a personal manager created through the real factory (both on one signer, both in /health), transaction state and
event index surviving container replacement on the same volume, the backup working beside it, and
recovery when the RPC response to a real accepted transaction is lost (a proxy drops it; only the
external service fails). Prints one JSON evidence object. Local simulated funds only.
"""
import argparse
import http.server
import json
import re
import os
import secrets
import shutil
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_utils import keccak, to_checksum_address

ROOT = Path(__file__).resolve().parent.parent
PORT, PROXY_PORT = 8581, 8582
RPC = f"http://127.0.0.1:{PORT}"
# Tenderly's public gateway by default. REHEARSAL_FORK_RPC (environment only) can name another
# upstream for the fork; its URL can carry an API key, so scrub() removes it from every record.
FORK_RPC = os.environ.get("REHEARSAL_FORK_RPC") or "https://mainnet.gateway.tenderly.co"


def scrub(text):
    text = text.replace(FORK_RPC, "<fork-rpc>") if "tenderly" not in FORK_RPC else text
    return re.sub(r"(https?://[^\s\"']*/v[0-9]+/)[A-Za-z0-9_-]{8,}", r"\1<key>", text)
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
MAX_GAS = 16_777_216
PARAMS_T = ("(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,uint64,uint64,"
            "uint64,uint64,uint64,uint128,uint128)")
# deploy/manager.json keys in VaultLib.Params struct order (6 u16, 9 u64, 2 u128).
PARAMS_ORDER = ["minEdgeBps", "bufferBps", "distributionBps", "payMarkupBps", "keeperShareBps",
                "allocatedBoundBps", "packUnitsMask", "gasCeilingWei", "essentialCeilingWei", "maxTipWei",
                "workFeeWei", "routineCapWei", "routineRatePerDayWei", "essentialCapWei",
                "essentialRatePerDayWei", "reserveWei", "tvlCapWei"]
ACTORS = {n: to_checksum_address(keccak(text=f"pack-vault-image-{n}")[-20:]) for n in ("deployer", "holder", "owner", "kicker", "manager")}
evidence = dict(steps=[])


def sh(*args, env=None, check=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT, env=env)
    if check and r.returncode:
        raise RuntimeError(f"{' '.join(map(str, args[:4]))}: {r.stdout[-2000:]}{r.stderr[-2000:]}")
    return r.stdout.strip()


def cast(*a):
    return sh("cast", *a, "--rpc-url", RPC)


def num(v):
    v = v.split()[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def call(sig, *a, to=None):
    return num(cast("call", to or VAULT, sig, *a))


def rpc(method, *params):
    return json.loads(cast("rpc", method, *[json.dumps(p) if not isinstance(p, str) else p for p in params]))


def send(frm, to, sig, *a, value=0):
    r = json.loads(cast("send", to, sig, *map(str, a), "--from", frm, "--unlocked", "--value", str(value), "--json"))
    r = r.get("data", r)
    assert int(r["status"], 16) == 1, f"{sig} reverted"
    return r


def holder_unwind(holder, log):
    """Runbook section 7: at canary values exit work is unpaid (essential budget 0, D64), so when the
    redemption exceeds free ETH the holder unlists and liquidates at their own gas, rerunning until
    nothing is owed. Each call the vault refuses (nothing to do yet or any more) is logged, not sent."""
    n = min(8, call("openListingCount()(uint256)"))
    ids = "[" + ",".join(str(call("openListingAt(uint256)(uint256)", i)) for i in range(n)) + "]"
    for sig, args in (("unlist(uint256[],uint256)", (ids, 0)), ("liquidate(uint256,uint256)", (8, 0))):
        try:
            send(holder, VAULT, sig, *args)
            log.append(dict(call=sig.split("(")[0], block=num(cast("block-number"))))
        except (RuntimeError, AssertionError) as e:
            reason = str(e)[-160:]
            if not log or log[-1].get("refused") != (sig.split("(")[0], reason):
                log.append(dict(refused=(sig.split("(")[0], reason)))


def warp_to(offset):
    now = num(cast("block", "latest", "--field", "timestamp"))
    nxt = now - now % 43_200 + offset
    nxt += 43_200 if nxt <= now else 0
    cast("rpc", "evm_setNextBlockTimestamp", str(nxt))
    cast("rpc", "evm_mine")


def expire_queue():
    """Process only real pending requests after their real deadlines (no VRF answer exists locally)."""
    for _ in range(64):
        if not call("unsettledAcquisitionCount()(uint256)", to=FWA):
            return
        cursor = call("nextSequenceToProcess()(uint64)", to=FWA)
        cast("rpc", "anvil_mine", hex(7_300))
        send(ACTORS["kicker"], FWA, "processAcquisitions(uint256)", 16)
        assert call("nextSequenceToProcess()(uint64)", to=FWA) > cursor, "FWA queue made no progress"
    raise RuntimeError("queue did not drain")


def wait_for(what, check, seconds=240):
    end = time.time() + seconds
    while time.time() < end:
        if check():
            evidence["steps"].append(dict(step=what, at_block=num(cast("block-number"))))
            return
        cast("rpc", "evm_mine")
        time.sleep(3)
    raise RuntimeError(f"timed out waiting for: {what}")


class DropFirstSend(http.server.BaseHTTPRequestHandler):
    """JSON-RPC proxy that forwards everything, then loses the response to the first transaction."""
    dropped = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        reply = urllib.request.urlopen(urllib.request.Request(RPC, body, {"Content-Type": "application/json"})).read()
        if not DropFirstSend.dropped and b"eth_sendRawTransaction" in body:
            DropFirstSend.dropped.append(json.loads(reply).get("result"))
            self.close_connection = True  # forwarded and accepted by the node; the answer is lost
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def log_message(self, *_):
        pass


class Keeper:
    """One keeper worker: the production container, or the same command as a host process."""

    def __init__(self, name, keystore, password, data, image, rpc=RPC, poll=5, health=8788):
        self.name, self.keystore, self.password, self.data, self.image, self.rpc, self.poll, self.health_port = \
            name, keystore, password, data, image, rpc, poll, health
        self.proc = None

    def start(self):
        env = dict(os.environ, VAULT=VAULT, FACTORY=FACTORY, RPC_URL=self.rpc, POLL_SECONDS=str(self.poll), KEEPER_ARGS="",
                   HEALTH_PORT=str(self.health_port),
                   KEEPER_KEYSTORE_JSON=Path(self.keystore).read_text(), KEEPER_KEYSTORE_PASSWORD=self.password)
        if self.image:  # values travel as inherited environment, never in argv
            sh("docker", "run", "-d", "--name", self.name, "--network", "host", "--mount",
               f"type=volume,source={self.data},target=/data", *[x for k in ("VAULT", "FACTORY", "RPC_URL", "POLL_SECONDS", "KEEPER_ARGS", "HEALTH_PORT",
                                                                     "KEEPER_KEYSTORE_JSON", "KEEPER_KEYSTORE_PASSWORD") for x in ("-e", k)],
               self.image, env=env)
        else:
            Path(self.data).mkdir(parents=True, exist_ok=True)
            self.log = open(Path(self.data) / f"{self.name}.log", "a")
            self.proc = subprocess.Popen(["python3", "keeper/keeper.py", VAULT, "--factory", FACTORY, "--send", "--keystore", self.keystore,
                                          "--password-file", self.password_file(), "--rpc", self.rpc,
                                          "--state", f"{self.data}/keeper-state.json", "--index", self.data,
                                          "--loop", str(self.poll), "--confirmations", "2", "--health-port", str(self.health_port)],
                                         cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT)

    def password_file(self):
        path = Path(self.data) / "pw"
        path.write_text(self.password)
        path.chmod(0o600)
        return path

    def health(self):
        """The worker's own /health answer (served on 127.0.0.1; 503 still carries the body)."""
        try:
            return json.loads(urllib.request.urlopen(f"http://127.0.0.1:{self.health_port}/health", timeout=5).read())
        except urllib.error.HTTPError as e:
            return json.loads(e.read())
        except OSError:
            return None

    def logs(self):
        if self.image:
            r = subprocess.run(["docker", "logs", "--tail", "40", self.name], capture_output=True, text=True)
            return (r.stdout + r.stderr)[-3000:]
        return (Path(self.data) / f"{self.name}.log").read_text()[-3000:]

    def stop(self):
        if self.image:
            sh("docker", "rm", "-f", self.name)
        elif self.proc:
            self.proc.terminate()
            self.proc.wait(30)

    def stored(self):
        """Saved transaction state and index head, read from the volume as a separate process."""
        code = ("import json,os,sqlite3\nif not os.path.exists('/data/keeper-state.json'): print('null'); raise SystemExit\n"
                "s=json.load(open('/data/keeper-state.json'));"
                "import glob\n"  # one index file per account; the head is the lowest across them
                "h=min((sqlite3.connect(p).execute('select max(end) from ranges').fetchone()[0] or 0 for p in glob.glob('/data/index-*.sqlite')), default=None);"
                "c=[dict(label=e['label'],block=e['block'],status=e['status'],gas_used=e['gas_used'],pay=e['pay']) for e in s['counted']];"
                "print(json.dumps(dict(stats=s['stats'],pending=s['pending'],counted=c,head=h)))")
        if self.image:
            out = sh("docker", "run", "--rm", "--mount", f"type=volume,source={self.data},target=/data",
                     "--entrypoint", "python3", self.image, "-c", code)
        else:
            out = sh("python3", "-c", code.replace("/data", self.data))
        return json.loads(out)


def main():
    global VAULT, FACTORY, MANAGER
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--image")
    ap.add_argument("--fork-block", type=int, default=26_450_200)
    a = ap.parse_args()
    work = Path(tempfile.mkdtemp(prefix="pack-vault-image-"))
    node = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", str(PORT), "--accounts", "0", "--silent",
                             "--fork-url", FORK_RPC, "--fork-block-number", str(a.fork_block), "--retries", "30",
                             "--fork-retry-backoff", "5000", "--base-fee", "150000000", "--gas-limit", str(MAX_GAS),
                             "--enable-tx-gas-limit"], stdout=open(work / "anvil.log", "w"), stderr=subprocess.STDOUT)
    keepers, cleanup = [], []
    try:
        for _ in range(300):
            try:
                fork_hash = rpc("eth_getBlockByNumber", hex(a.fork_block), False)["hash"]
                break
            except (RuntimeError, json.JSONDecodeError):
                time.sleep(1)
        evidence.update(fork_block=a.fork_block, fork_hash=fork_hash, image=a.image,
                        foundry=sh("cast", "--version").splitlines()[0])
        # Disposable keystores with random passwords: the real signing path, no raw key anywhere.
        keys = {}
        for name in ("primary", "backup"):
            password = secrets.token_hex(24)
            out = json.loads(sh("cast", "wallet", "new", str(work), "--unsafe-password", password, "--json"))
            made = (out.get("data", out) if isinstance(out, dict) else out)[0]
            keys[name] = (made["path"], password, to_checksum_address(made["address"]))
        for address in [*ACTORS.values(), *(k[2] for k in keys.values())]:
            assert cast("code", address) == "0x" and num(cast("nonce", address)) == 0 and num(cast("balance", address)) == 0, \
                f"actor not clean on the fork: {address}"
            rpc("anvil_setBalance", address, hex(10 * 10**18))
        for address in ACTORS.values():
            rpc("anvil_impersonateAccount", address)
        values = json.loads((ROOT / "deploy/canary.json").read_text())
        values["owner"] = ACTORS["owner"]
        path = ROOT / "deploy/rehearse-image.json"  # Forge reads values only under deploy/
        path.write_text(json.dumps(values))
        cleanup.append(path)
        env = dict(os.environ, RPC_URL=RPC, FORGE_WALLET_ARGS=f"--unlocked --sender {ACTORS['deployer']}")
        sh("script/deploy.sh", path, "--broadcast", env=env)
        run = json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
        VAULT = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault")
        evidence["vault"] = VAULT
        FACTORY = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackManagerFactory")
        evidence["factory"] = FACTORY
        evidence["postflight"] = sh("python3", "script/release.py", "postflight", VAULT, path, ACTORS["owner"], FACTORY,
                                    env=dict(os.environ, RPC_URL=RPC))
        # A personal manager from the real permissionless factory, with the published defaults.
        mv = json.loads((ROOT / "deploy/manager.json").read_text())
        send(ACTORS["manager"], FACTORY, f"create(address,{PARAMS_T})", ACTORS["manager"],
             "(" + ",".join(str(mv[k]) for k in PARAMS_ORDER) + ")", value=5 * 10**17)
        MANAGER = cast("call", FACTORY, "managerAt(uint256)(address)", "0").split()[0]
        assert call("managerCount()(uint256)", to=FACTORY) == 1 and \
            cast("call", MANAGER, "owner()(address)").lower() == ACTORS["manager"].lower(), "manager postflight"
        evidence["manager"] = MANAGER

        holder = ACTORS["holder"]
        deposit = call("requestCharge()(uint256)") + values["tvlCapWei"] - values["seedWei"]
        send(holder, VAULT, "deposit()", value=deposit)
        expire_queue()
        volume = lambda n: n if a.image else str(work / n)  # noqa: E731
        if a.image:
            for n in ("primary-data", "backup-data"):
                sh("docker", "volume", "create", n)
        primary = Keeper("primary", *keys["primary"][:2], volume("primary-data"), a.image)
        # Fly runs each worker on its own machine; sharing this host needs separate health ports.
        backup = Keeper("backup", *keys["backup"][:2], volume("backup-data"), a.image, poll=30, health=8789)
        keepers = [primary, backup]
        primary.start()
        backup.start()
        warp_to(42_360)
        wait_for("primary prices the deposit at the blackout", lambda: call("lastNav()(uint256)") > 0)
        warp_to(60)
        expire_queue()
        wait_for("keepers build and list", lambda: call("openListingCount()(uint256)") > 0)
        wait_for("primary builds and lists for the manager", lambda: call("openListingCount()(uint256)", to=MANAGER) > 0)
        both = lambda h: h is not None and h.get("policy_count") == 2 and \
            {VAULT.lower(), MANAGER.lower()} == {k.lower() for k in h.get("accounts", {})}  # noqa: E731
        wait_for("primary /health serves the vault and the manager", lambda: both(primary.health()))
        evidence["manager_open"] = call("openListingCount()(uint256)", to=MANAGER)
        before = primary.stored()
        evidence["before_replacement"] = before

        # Replacement: a new container on the same volume continues from the saved state and head.
        # The backup pauses meanwhile so the replacement, behind the dropping proxy, is the one that
        # must send (else the backup can price the redemption first and no response is lost).
        backup.stop()
        primary.stop()
        DropFirstSend.dropped.clear()
        server = socketserver.ThreadingTCPServer(("127.0.0.1", PROXY_PORT), DropFirstSend)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        replacement = Keeper("primary-replacement", *keys["primary"][:2], volume("primary-data"), a.image,
                             rpc=f"http://127.0.0.1:{PROXY_PORT}")
        keepers[0] = replacement
        replacement.start()
        # The charge is quoted at the basefee when the call runs; a build in between can raise it.
        # Pay double, as a holder should: the excess comes straight back.
        send(holder, VAULT, "requestRedeem(uint256)", call("shareBalance(address)(uint256)", holder) // 4,
             value=2 * call("requestCharge()(uint256)"))
        warp_to(42_360)
        expire_queue()
        unwind = evidence["holder_unwind"] = []
        wait_for("replacement prices the redemption through a lost RPC response",
                 lambda: holder_unwind(holder, unwind) or (DropFirstSend.dropped and call("lockedShares()(uint256)") == 0),
                 seconds=420)
        after = replacement.stored()
        evidence["after_replacement"] = after
        wait_for("replacement /health serves the vault and the manager", lambda: both(replacement.health()))
        evidence["replacement_health_accounts"] = sorted(replacement.health()["accounts"])
        evidence["dropped_transaction"] = DropFirstSend.dropped[0]
        dropped = rpc("eth_getTransactionReceipt", DropFirstSend.dropped[0])
        evidence["dropped_transaction_status"] = dropped and int(dropped["status"], 16)
        assert after["stats"]["mined"] >= before["stats"]["mined"] and after["head"] >= before["head"], "state or index lost"
        backup = Keeper("backup-restarted", *keys["backup"][:2], volume("backup-data"), a.image, poll=30, health=8789)
        keepers[1] = backup
        backup.start()  # same volume: the backup resumes its own saved state beside the replacement
        # The backup polls slowly and may find nothing to send; it must still complete clean passes.
        wait_for("backup completes a clean pass", lambda: (h := backup.health()) is not None
                 and h["block"] > 0 and h["pass_errors"] == 0, seconds=600)
        evidence["backup"] = dict(stored=backup.stored(), health=backup.health())
        # Two live keepers can race for the same work; the loser reverts and pays its gas. Any
        # revert that is not a lost race (same operation mined by the other worker within 2 blocks)
        # fails the rehearsal.
        mine = (after or {}).get("counted", [])
        other = ((evidence["backup"]["stored"] or {}).get("counted", []))
        races = []
        for a_, b_ in ((mine, other), (other, mine)):
            for e in a_:
                if not e["status"]:
                    won = [x for x in b_ if x["status"] and x["label"] == e["label"] and abs(x["block"] - e["block"]) <= 2]
                    assert won, f"a keeper transaction reverted without a race: {e}"
                    races.append(dict(lost=e, won=won[0]))
        evidence["lost_races"] = races
        keeper_nonce = num(cast("nonce", keys["primary"][2]))
        evidence["primary_nonce"] = keeper_nonce
        evidence["primary_sends_counted"] = after["stats"]["sent"]
        evidence["result"] = "PASS"
    finally:
        for k in keepers:
            try:
                evidence.setdefault("worker_log_tails", {})[k.name] = k.logs()
                k.stop()
            except Exception as e:  # keep the evidence; report the cleanup failure
                evidence.setdefault("cleanup_errors", []).append(str(e))
        node.terminate()
        for f in cleanup:
            f.unlink(missing_ok=True)
        print(scrub(json.dumps(evidence, indent=1, default=str)))
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
