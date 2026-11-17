#!/usr/bin/env python3
"""Recovery tests for keeper/tx.py on a plain local anvil (no fork: no mainnet address can carry
code or delegations here). Targets are three tiny contracts deployed from raw bytecode: one emits
KeeperPaid(caller, 123) like the vault does, one reverts with the vault's Nothing() error, one
reverts with no data. Run: python3 keeper/test_tx.py
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tx as txm  # noqa: E402

PAY = 123
TOPIC = txm.KEEPER_PAID[2:]
PAYER = "607b600052" + "33" + "7f" + TOPIC + "6020" + "6000" + "a2" + "00"  # mstore 123; LOG2(data, topic, caller)
NOTHING = "63f9820cc1" + "60e01b" + "600052" + "6004" + "6000" + "fd"  # revert Nothing()
BARE = "5f5ffd"  # revert with no data


def initcode(runtime):
    n = len(runtime) // 2
    return "0x" + f"60{n:02x}600c600039" + f"60{n:02x}6000f3" + runtime


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class Chain:
    def __init__(self):
        self.port = free_port()
        self.rpc = f"http://127.0.0.1:{self.port}"
        self.proc = subprocess.Popen(["anvil", "--port", str(self.port), "--base-fee", "100000000", "--silent"])
        for _ in range(50):
            try:
                self.cast("block-number")
                break
            except subprocess.CalledProcessError:
                time.sleep(0.2)
        self.keeper = "0x00000000000000000000000000000000c0ffee01"
        self.rpcm("anvil_impersonateAccount", self.keeper)
        self.rpcm("anvil_setBalance", self.keeper, hex(10**19))
        self.payer, self.nothing, self.bare = (self.deploy(c) for c in (PAYER, NOTHING, BARE))

    def cast(self, *a):
        return subprocess.check_output(["cast", *map(str, a), "--rpc-url", self.rpc], text=True,
                                       stderr=subprocess.STDOUT).strip()

    def rpcm(self, m, *p):
        return self.cast("rpc", m, *[json.dumps(x) if not isinstance(x, str) else x for x in p])

    def deploy(self, runtime):
        r = json.loads(subprocess.check_output(["cast", "send", "--rpc-url", self.rpc, "--unlocked", "--from", self.keeper,
                                                "--json", "--create", initcode(runtime)], text=True))
        return r["contractAddress"]

    def automine(self, on):
        self.rpcm("evm_setAutomine", on)

    def mine(self, n=1):
        self.rpcm("anvil_mine", hex(n))

    def base(self):
        return int(json.loads(self.rpcm("eth_getBlockByNumber", "latest", False))["baseFeePerGas"], 16)

    def close(self):
        self.proc.terminate()
        self.proc.wait()


def manager(c, path, **kw):
    return txm.TxManager(c.rpc, path, c.keeper, ["--unlocked", "--from", c.keeper], log=lambda m: print("  tx:", m, flush=True), **kw)


def release(tm):
    tm._lockf.close()


def submit(tm, c, to):
    est, _, _ = tm.preflight(to, [])
    assert est, "preflight"
    tm.submit("work", to, [], est, c.base(), 50_000_000, PAY)
    return est


def main():
    c = Chain()
    d = tempfile.mkdtemp()
    try:
        # 1. Preflight: the vault's "state moved on" error is benign, anything else is an error.
        tm = manager(c, f"{d}/a.json")
        assert tm.preflight(c.nothing, []) [:3:2] == (None, True), "Nothing() is expected"
        est, why, benign = tm.preflight(c.bare, [])
        assert est is None and not benign, why
        # 2. Normal send: receipt reconciled against the KeeperPaid event.
        submit(tm, c, c.payer)
        assert not tm.wait(lambda p, *a: 1, 10)
        e = tm.state["counted"][-1]
        assert e["status"] == 1 and e["pay"] == PAY and e["net"] == PAY - e["cost"] and e["cost"] > 0, e
        assert tm.state["stats"]["mined"] == 1 and tm.state["stats"]["paid_wei"] == PAY
        # 3. Concurrency: a second process on the same state file is refused.
        try:
            manager(c, f"{d}/a.json")
            raise AssertionError("second manager acquired the lock")
        except txm.Locked:
            pass
        release(tm)

        # 4. Stuck, then restart, then same-nonce replacement. The bid sits below the basefee.
        c.automine(False)
        tm = manager(c, f"{d}/b.json", replace_after=2)
        submit(tm, c, c.payer)
        nonce = tm.state["pending"]["nonce"]
        release(tm)  # process dies with the transaction in flight
        c.rpcm("anvil_setNextBlockBaseFeePerGas", hex(c.base() * 20))
        c.mine(3)
        tm = manager(c, f"{d}/b.json", replace_after=2)  # restart from the state file
        assert tm.state["pending"]["nonce"] == nonce
        assert tm.resolve(lambda p, *a: 1), "still in flight"
        p = tm.state["pending"]
        assert p["replacements"] == 1 and len(p["hashes"]) == 2 and p["nonce"] == nonce, p
        c.mine(1)
        assert not tm.resolve(lambda p, *a: 1)
        e = tm.state["counted"][-1]
        assert e["hash"] == p["hashes"][-1] and e["pay"] == PAY and tm.state["stats"]["replaced"] == 1
        assert int(c.cast("nonce", c.keeper)) == nonce + 1, "exactly one transaction used the nonce"

        # 5. Lost response, never broadcast: the entry has a nonce but no hash. After the replace
        #    delay the same nonce is broadcast; nothing is sent at a new nonce.
        n0 = int(c.cast("nonce", c.keeper))
        tm.state["pending"] = dict(label="work", to=c.payer, args=[], nonce=n0, gas=100_000, est=80_000,
                                   prio=50_000_000, max_fee=c.base() * 3, sent_block=tm.head(), replacements=0,
                                   hashes=[], expected_pay=PAY, submitted=0)
        c.mine(2)
        assert tm.resolve(lambda p, *a: 1) and len(tm.state["pending"]["hashes"]) == 1
        c.mine(1)
        assert not tm.resolve(lambda p, *a: 1) and int(c.cast("nonce", c.keeper)) == n0 + 1

        # 6. Lost response, broadcast happened: the nonce is used by our call; it is found and counted.
        n1 = int(c.cast("nonce", c.keeper))
        h = c.cast("send", c.payer, "--unlocked", "--from", c.keeper, "--nonce", n1, "--async")
        tm.state["pending"] = dict(label="work", to=c.payer, args=[], nonce=n1, gas=100_000, est=80_000,
                                   prio=50_000_000, max_fee=c.base() * 3, sent_block=tm.head(), replacements=0,
                                   hashes=[], expected_pay=PAY, submitted=0)
        c.mine(1)
        before = tm.state["stats"]["mined"]
        assert not tm.resolve(lambda p, *a: 1)
        assert tm.state["counted"][-1]["hash"] == h.split()[-1] and tm.state["stats"]["mined"] == before + 1

        # 7. Nonce used by an unrelated transaction (another process with this key): dropped, not resent.
        n2 = int(c.cast("nonce", c.keeper))
        c.cast("send", c.keeper, "--value", 1, "--unlocked", "--from", c.keeper, "--nonce", n2, "--async")
        tm.state["pending"] = dict(label="work", to=c.payer, args=[], nonce=n2, gas=100_000, est=80_000,
                                   prio=50_000_000, max_fee=c.base() * 3, sent_block=tm.head(), replacements=0,
                                   hashes=[], expected_pay=PAY, submitted=0)
        c.mine(1)
        dropped = tm.state["stats"]["dropped"]
        assert not tm.resolve(lambda p, *a: 1) and tm.state["stats"]["dropped"] == dropped + 1
        assert int(c.cast("nonce", c.keeper)) == n2 + 1

        # 8. Work done by someone else while ours was stuck: not replaced, waits for the nonce.
        tm.replace_after = 1
        tm.state["pending"] = None
        submit(tm, c, c.payer)
        c.rpcm("anvil_setNextBlockBaseFeePerGas", hex(c.base() * 20))
        c.mine(2)
        assert tm.resolve(lambda p, *a: None) and tm.state["pending"]["replacements"] == 0
        c.rpcm("anvil_dropAllTransactions")
        c.automine(True)
        c.mine(1)

        # 8b. Every replacement is re-priced: the callback receives the bumped tip and max fee and can
        #     refuse; a refusal means no replacement is sent.
        seen = []
        c.automine(False)
        tm.state["pending"] = None
        submit(tm, c, c.payer)
        c.rpcm("anvil_setNextBlockBaseFeePerGas", hex(c.base() * 20))
        c.mine(2)
        prio0 = tm.state["pending"]["prio"]
        assert tm.resolve(lambda p, prio=None, mf=None: seen.append((prio, mf)) or None)
        assert seen and seen[0][0] > prio0 and seen[0][1] > 0, seen
        assert tm.state["pending"]["replacements"] == 0, "unprofitable replacement not sent"
        c.rpcm("anvil_dropAllTransactions")
        c.automine(True)
        c.mine(1)

        # 9. Reorg: a counted receipt that leaves the chain is uncounted and reported.
        tm.state["pending"] = None
        submit(tm, c, c.payer)
        assert not tm.wait(lambda p, *a: 1, 10)
        mined, paid = tm.state["stats"]["mined"], tm.state["stats"]["paid_wei"]
        c.rpcm("anvil_reorg", 1, [])
        tm.check_reorgs(tm.head())
        s = tm.state["stats"]
        assert s["reorged"] == 1 and s["mined"] == mined - 1 and s["paid_wei"] == paid - PAY, s
        assert any("reorg" in e["msg"] for e in tm.state["errors"])

        # 10. The state file survives every step and reloads identically.
        tm.save()
        release(tm)
        again = manager(c, f"{d}/b.json")
        assert again.state == json.load(open(f"{d}/b.json"))
        release(again)
        print("keeper/test_tx.py: 11 scenarios pass")
    finally:
        c.close()


if __name__ == "__main__":
    main()
