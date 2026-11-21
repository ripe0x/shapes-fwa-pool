#!/usr/bin/env python3
"""Fetch the real transactions behind chosen selection candidates into test/fixtures/selection.json:
sender, target, value, calldata and gas price of the request and the VRF fulfillment, plus the
request block's real hash. Fork tests replay these calls verbatim."""
import json
import subprocess
import sys
from pathlib import Path

RPC = "https://mainnet.gateway.tenderly.co"
ROOT = Path(__file__).parent


def _cast(*args):
    out = json.loads(subprocess.check_output(["cast", *args, "--json", "--rpc-url", RPC]))
    return out.get("data", out) if isinstance(out, dict) and "schema_version" in out else out


def tx(h):
    return _cast("tx", h)


def block(n):
    return _cast("block", str(n))


def main(blocks):
    cands = {c["req_block"]: c for c in json.load(open(ROOT / "out/selection_candidates.json"))}
    p = ROOT.parent / "test/fixtures/selection.json"
    out = json.loads(p.read_text()) if p.exists() else {}  # keep fixtures other suites replay
    for b in blocks:
        c = cands[b]
        r, f = tx(c["req_tx"]), tx(c["fulfill_tx"])
        fb = block(c["fulfill_block"])
        out[str(b)] = {
            "reqFrom": r["from"], "reqTo": r["to"], "reqValue": int(r["value"], 16), "reqInput": r["input"],
            "reqGasPrice": int(r["gasPrice"], 16), "reqBlock": b, "reqBlockHash": block(b)["hash"],
            "fulBlock": c["fulfill_block"], "fulTimestamp": int(fb["timestamp"], 16),
            "fulFrom": f["from"], "fulTo": f["to"], "fulInput": f["input"], "fulGasPrice": int(f["gasPrice"], 16),
            "fulBaseFee": int(fb["baseFeePerGas"], 16),
        }
    p.write_text(json.dumps(out, indent=1))
    print(p, list(out))


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1:]])
