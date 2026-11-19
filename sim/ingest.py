#!/usr/bin/env python3
"""Phase 0.2: ingest every FWA V2 and FWAV2Rewards log into SQLite (sim/data/fwa.sqlite).

Resumable: continues from the highest fully ingested block. Logs are decoded with the event
ABIs vendored in sim/abi (Sourcify full matches; each file records its source and artifact hash);
args are stored as JSON (ints as decimal strings so wei values keep full precision).

Usage: sim/ingest.py [to_block]    (MAINNET_RPC_URL overrides the Tenderly default)
"""
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak

RPC = os.environ.get("MAINNET_RPC_URL", "https://mainnet.gateway.tenderly.co")
ABI = Path(__file__).parent / "abi"
CONTRACTS = {
    "0x958c41181182e76f221331b2755b77d9e1426a98": ABI / "fwa-v2-events.json",
    "0xa54b44c7a894aa19c49734a753d01f9b8c5f6516": ABI / "fwa-v2-rewards-events.json",
    # CollectionFloorOracle, ABI from Sourcify (full match).
    "0xaa4d9009a4664604b57644bf13e447e9036727dc": Path(__file__).parent / "abi/oracle.json",
}
START_BLOCK = 25_944_000
DB = Path(os.environ.get("FWA_DB", Path(__file__).parent / "data/fwa.sqlite"))


def abi_type(p):
    if p["type"].startswith("tuple"):
        return "(" + ",".join(abi_type(c) for c in p["components"]) + ")" + p["type"][5:]
    return p["type"]


def jsonable(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return str(v)
    if isinstance(v, bytes):
        return "0x" + v.hex()
    if isinstance(v, (list, tuple)):
        return [jsonable(x) for x in v]
    return v


def load_events():
    events = {}
    for address, path in CONTRACTS.items():
        for e in json.load(open(path))["abi"]:
            if e["type"] != "event":
                continue
            sig = f"{e['name']}({','.join(abi_type(i) for i in e['inputs'])})"
            events[(address, "0x" + keccak(text=sig).hex())] = e
    return events


def decode_log(e, log):
    topics, data = log["topics"][1:], bytes.fromhex(log["data"][2:])
    plain = [i for i in e["inputs"] if not i["indexed"]]
    values = iter(decode([abi_type(i) for i in plain], data))
    args = {}
    for i in e["inputs"]:
        if i["indexed"]:
            raw = bytes.fromhex(topics.pop(0)[2:])
            # Dynamic indexed values are hashed; keep the hash.
            dynamic = i["type"] in ("string", "bytes") or i["type"].endswith("]") or "tuple" in i["type"]
            args[i["name"]] = "0x" + raw.hex() if dynamic else decode([i["type"]], raw)[0]
        else:
            args[i["name"]] = next(values)
    return {k: jsonable(v) for k, v in args.items()}


def rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, body, {"Content-Type": "application/json",
                                             "User-Agent": "fwa-ingest"})
    deadline, attempt = time.time() + 8 * 3600, 0
    while True:
        try:
            time.sleep(0.5)  # stay under the public gateway's rate limit
            return json.load(urllib.request.urlopen(req, timeout=120))
        except (urllib.error.URLError, TimeoutError) as exc:
            # The public gateway throttles with 429 for minutes at a time: wait it out.
            if time.time() > deadline:
                raise RuntimeError(f"{method} failed: {exc}") from exc
            wait = min(2 ** attempt, 300)
            print(f"  {exc}; retry in {wait}s", flush=True)
            time.sleep(wait)
            attempt += 1


def get_logs(addresses, start, end):
    """Logs in [start, end], splitting the range when the node's 20k result cap is hit."""
    r = rpc("eth_getLogs", [{"address": addresses, "fromBlock": hex(start), "toBlock": hex(end)}])
    if "error" not in r:
        return r["result"], end
    if "more than" not in str(r["error"]) or end == start:
        raise RuntimeError(f"eth_getLogs {start}-{end}: {r['error']}")
    return get_logs(addresses, start, start + (end - start) // 2)


def done_through(db, address):
    row = db.execute("SELECT v FROM meta WHERE k = ?", (f"done:{address}",)).fetchone()
    if row:
        return row[0]
    legacy = db.execute("SELECT v FROM meta WHERE k = 'done_through'").fetchone()
    core = list(CONTRACTS)[:2]  # the first run ingested FWA and Rewards under one key
    return legacy[0] if legacy and address in core else START_BLOCK - 1


def main():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS logs (
            block INTEGER, log_index INTEGER, ts INTEGER, tx TEXT, contract TEXT,
            event TEXT, args TEXT, PRIMARY KEY (block, log_index));
        CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INTEGER);
        CREATE INDEX IF NOT EXISTS logs_event ON logs (event);
    """)
    events = load_events()
    to_block = int(sys.argv[1]) if len(sys.argv) > 1 else int(rpc("eth_blockNumber", [])["result"], 16)
    unknown = 0
    while True:
        marks = {a: done_through(db, a) for a in CONTRACTS}
        start = min(marks.values()) + 1
        if start > to_block:
            break
        addresses = [a for a, m in marks.items() if m + 1 == start]
        span = 20_000
        start = ingest_range(db, events, addresses, start, to_block, span)
    total = db.execute("SELECT count(*) FROM logs").fetchone()[0]
    print(f"done through {to_block}; {total} logs")


def ingest_range(db, events, addresses, start, to_block, span):
    unknown = 0
    while start <= to_block:
        logs, end = get_logs(addresses, start, min(start + span - 1, to_block))
        rows = []
        for log in logs:
            if log.get("removed"):
                continue
            e = events.get((log["address"].lower(), log["topics"][0]))
            if e is None:
                unknown += 1
                name, args = "UNKNOWN", {"topics": log["topics"], "data": log["data"]}
            else:
                name, args = e["name"], decode_log(e, log)
            rows.append((int(log["blockNumber"], 16), int(log["logIndex"], 16),
                         int(log["blockTimestamp"], 16), log["transactionHash"],
                         log["address"].lower(), name, json.dumps(args)))
        with db:
            db.executemany("INSERT OR REPLACE INTO logs VALUES (?,?,?,?,?,?,?)", rows)
            db.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)",
                           [(f"done:{a}", end) for a in addresses])
        # Grow the window while results are sparse, shrink after a split.
        span = min(span * 2, 200_000) if len(logs) < 5_000 and end - start + 1 == span else end - start + 1
        print(f"{start}-{end}: {len(logs)} logs", flush=True)
        start = end + 1
    if unknown:
        print(f"{unknown} undecoded logs")
    return start


if __name__ == "__main__":
    main()
