#!/usr/bin/env python3
"""Fetch canonical acquisition and coordinator calls for exposed journal replay.

All RPC calls are reads. No randomness, request identity or proof is constructed.
The selected prefix begins before the funded autobuyer's real request at block
26427899 and includes its first 125 acquisitions. Later original router work is
budget sensitive in the counterfactual pool and is deliberately excluded.
"""
import concurrent.futures
import argparse
import json
import time
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RPC = "https://mainnet.gateway.tenderly.co"
FWA = "0x958c41181182e76f221331b2755b77d9e1426a98"
BUYER = "0x61a2cad6b545983dbddb1de52d338cc319a4903e"
REQUEST = "0xf23e34f4aa4a06ecddd309d9692e7b7ca45b76fd0d5f4ce4f7fbf29731d9abd6"
WORD = "0x98f19be7797a0d9a9520c633b7e2ac1fc1517fcb3a5185d16a8081572f15a992"
PROCESSED = "0x63edc6f178d7041b96c564ba33fde66b3f2f3b215be8b2d5a785fee5231fbd57"
CACHE = Path(tempfile.gettempdir()) / "shapes-complete-foreign-rpc"


def rpc(method, params):
    key = method + "_" + str(params[0])
    if method == "eth_getBalance":
        key += "_" + params[1]
    path = CACHE / (key + ".json")
    if path.exists():
        return json.loads(path.read_text())
    request = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1,
        "method": method, "params": params}).encode(), {"Content-Type": "application/json"})
    for attempt in range(8):
        try:
            result = json.load(urllib.request.urlopen(request, timeout=55))
            if "error" in result:
                raise RuntimeError(result["error"])
            path.write_text(json.dumps(result["result"]))
            return result["result"]
        except Exception:
            if attempt == 7:
                raise
            time.sleep(min(2 ** attempt, 20))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--records", type=int, default=125)
    parser.add_argument("--output", type=Path, default=ROOT / "test/fixtures/complete-foreign-history.json")
    options = parser.parse_args()
    CACHE.mkdir(parents=True, exist_ok=True)
    # The logs file is reproducible through the read-only RPC, cached separately
    # because its structured query is not a suitable filename.
    logpath = CACHE / "logs.json"
    if not logpath.exists():
        query = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{
            "address": FWA, "fromBlock": hex(26417086), "toBlock": hex(26437086),
            "topics": [[REQUEST, WORD]]}]}
        request = urllib.request.Request(RPC, json.dumps(query).encode(), {"Content-Type": "application/json"})
        result = json.load(urllib.request.urlopen(request, timeout=55))
        if "error" in result:
            raise RuntimeError(result["error"])
        logpath.write_text(json.dumps(result["result"]))
    logs = json.loads(logpath.read_text())
    requested = [x for x in logs if x["topics"][0] == REQUEST and int(x["blockNumber"], 16) >= 26427899]
    chosen = requested[:options.records]
    chosen += [x for x in requested[options.records:] if x["transactionHash"] == chosen[-1]["transactionHash"]]
    ids = {x["topics"][1] for x in chosen}
    selected = [x for x in logs if x["topics"][1] in ids]
    processor_path = CACHE / "processor-context.json"
    if not processor_path.exists():
        query = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{
            "address": FWA, "fromBlock": hex(26427899), "toBlock": hex(26428100), "topics": [PROCESSED]}]}
        request = urllib.request.Request(RPC, json.dumps(query).encode(), {"Content-Type": "application/json"})
        result = json.load(urllib.request.urlopen(request, timeout=55))
        if "error" in result:
            raise RuntimeError(result["error"])
        processor_path.write_text(json.dumps(result["result"]))
    included = {x["transactionHash"] for x in selected}
    selected += [x for x in json.loads(processor_path.read_text())
        if x["topics"][1] in ids and x["transactionHash"] not in included]
    # Preserve the buyer's actual funding and order updates between requests.
    # Omitting these can make ripMany legitimately skip a request, so a later
    # genuine Chainlink proof has no corresponding locally issued request.
    context_path = CACHE / "buyer-context.json"
    if not context_path.exists():
        query = {"jsonrpc": "2.0", "id": 1, "method": "eth_getLogs", "params": [{
            "address": BUYER, "fromBlock": hex(26427899), "toBlock": hex(26428100)}]}
        request = urllib.request.Request(RPC, json.dumps(query).encode(), {"Content-Type": "application/json"})
        result = json.load(urllib.request.urlopen(request, timeout=55))
        if "error" in result:
            raise RuntimeError(result["error"])
        context_path.write_text(json.dumps(result["result"]))
    included = {x["transactionHash"] for x in selected}
    selected += [x for x in json.loads(context_path.read_text())
        if x["transactionHash"] not in included and int(x["blockNumber"], 16) <= int(chosen[-1]["blockNumber"], 16)]
    txids = sorted({x["transactionHash"] for x in selected})
    blocks = sorted({x["blockNumber"] for x in selected})
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        txs = list(pool.map(lambda x: rpc("eth_getTransactionByHash", [x]), txids))
        headers = list(pool.map(lambda x: rpc("eth_getBlockByNumber", [x, False]), blocks))
    headers = {x["number"]: x for x in headers}
    request_for_id = {x["topics"][1]: x for x in chosen}
    bytx = {}
    for log in selected:
        bytx.setdefault(log["transactionHash"], []).append(log)
    calls = []
    for tx in sorted(txs, key=lambda x: (int(x["blockNumber"], 16), int(x["transactionIndex"], 16))):
        block = headers[tx["blockNumber"]]
        events = bytx[tx["hash"]]
        request = events[0]["topics"][0] == REQUEST
        fulfillment = events[0]["topics"][0] == WORD
        source = request_for_id[events[0]["topics"][1]] if fulfillment else events[0]
        sender_balance = int(rpc("eth_getBalance", [tx["from"], hex(int(block["number"], 16) - 1)]), 16) if int(tx["value"], 16) else 0
        calls.append({"tx": tx["hash"], "from": tx["from"], "to": tx["to"], "input": tx["input"],
            "value": int(tx["value"], 16), "gasPrice": int(tx["gasPrice"], 16),
            "block": int(block["number"], 16), "timestamp": int(block["timestamp"], 16),
            "baseFee": int(block["baseFeePerGas"], 16), "isRequest": request, "isFulfillment": fulfillment,
            "requestBlock": int(source["blockNumber"], 16), "requestBlockHash": source["blockHash"],
            "records": len(events) if request or fulfillment else 0, "senderBalanceBeforeBlock": sender_balance})
    output = options.output
    output.write_text(json.dumps({"requests": len(chosen), "callCount": len(calls), "calls": calls}, indent=2) + "\n")
    print(f"Saved {len(calls)} authentic calls for {len(chosen)} requests to {output}", flush=True)


if __name__ == "__main__":
    main()
