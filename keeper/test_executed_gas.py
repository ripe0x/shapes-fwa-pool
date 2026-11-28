#!/usr/bin/env python3
"""TxManager.executed_gas against a real anvil fork of mainnet: the simulated gas of the exact
call at its signed limit equals the gas its mined receipt bills. The only injected condition is
an unreachable node, which must fall back (None) instead of guessing.

python3 keeper/test_executed_gas.py   # starts and stops its own anvil fork on a free port
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))
import tx as T

FORK = "https://mainnet.gateway.tenderly.co"
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main():
    port = free_port()
    rpc = f"http://127.0.0.1:{port}"
    node = subprocess.Popen(["anvil", "--fork-url", FORK, "--port", str(port), "--silent",
                             "--fork-retry-backoff", "5000", "--retries", "30"])
    try:
        for _ in range(120):
            try:
                subprocess.check_output(["cast", "block-number", "--rpc-url", rpc], stderr=subprocess.DEVNULL)
                break
            except subprocess.CalledProcessError:
                time.sleep(1)
        sender = subprocess.check_output(["cast", "wallet", "address", "--private-key", "0x" + os.urandom(32).hex()], text=True).strip()
        cast = lambda *a: subprocess.check_output(["cast", *map(str, a), "--rpc-url", rpc], text=True).strip()
        assert cast("code", sender) == "0x" and int(cast("balance", sender)) == 0, "test actor must start clean"
        cast("rpc", "anvil_setBalance", sender, hex(10**18))  # funding an external actor is setup
        cast("rpc", "anvil_impersonateAccount", sender)
        base = int(json.loads(cast("rpc", "eth_getBlockByNumber", "pending", "false"))["baseFeePerGas"], 16)
        fees = ["--gas-price", str(2 * base + 10**8), "--priority-gas-price", str(10**8)]
        with tempfile.TemporaryDirectory() as d:
            tm = T.TxManager(rpc, os.path.join(d, "state.json"), sender, ["--unlocked", "--from", sender])
            # A real FWA state-reading call executed as a transaction, plus a value transfer.
            for to, args in ((FWA, ["activeListingCount()"]), (sender, ["0x", "--value", "1"])):
                limit = 200_000
                predicted = tm.executed_gas(to, args, limit, fees)
                assert predicted, (to, args, "simulation unavailable on anvil")
                h = cast("send", to, *(args if args[0] != "0x" else args[1:]), "--from", sender, "--unlocked",
                         "--gas-limit", limit, *fees, "--async")
                cast("rpc", "evm_mine")
                receipt = json.loads(cast("receipt", h, "--json"))
                assert int(receipt["status"], 16) == 1, receipt
                assert predicted == int(receipt["gasUsed"], 16), (predicted, receipt["gasUsed"])
                print(f"ok {args[0]}: simulated {predicted} == billed {int(receipt['gasUsed'], 16)}")
            tm._lockf.close()
        with tempfile.TemporaryDirectory() as d:
            dead = T.TxManager.__new__(T.TxManager)
            dead.rpc, dead.sender = f"http://127.0.0.1:{free_port()}", sender
            assert dead.executed_gas(FWA, ["activeListingCount()"], 200_000, fees) is None
            print("ok unreachable node falls back")
    finally:
        node.terminate()
        node.wait()


if __name__ == "__main__":
    main()
