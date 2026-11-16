#!/usr/bin/env python3
"""Find real historical acquisitions whose real VRF word would select a pack listing the vault
posts just before the request. Fork tests replay those exact transactions, so selection comes
from FWA's real randomness, never a fake.

FWAV2 selection: target = word % totalWeight, descending a segment tree whose leaves are slots
in ascending order, so a listing in slot s with weight w is chosen iff
C(s) <= target < C(s) + w, C(s) = total weight of active slots below s. A new listing takes the
head of the LIFO free-slot list, else the next unused slot. Weight is 1e36 // backing.

A candidate is valid only when inserting our listing changes nothing else before the selection:
the queue is empty at the request (our listing activates at once), and between our insertion and
the selection no listing activates, reprices or leaves.
Writes sim/out/selection_candidates.json.
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
DB = ROOT / "data/fwa.sqlite"
NUM = 10**36
DISRUPT = {"NFTListed", "BackingUpdated", "ListingWithdrawn", "ListingKicked"}


def main(backing_wei=36_300_000_000_000_000, count=30, start_block=26_164_530):
    w_ours = NUM // backing_wei
    db = sqlite3.connect(DB)
    logs = [(b, li, ts, tx, e, json.loads(a)) for b, li, ts, tx, e, a in db.execute(
        "SELECT block, log_index, ts, tx, event, args FROM logs ORDER BY block, log_index")]

    slot_w = {}  # active slot -> weight
    slot_of = {}  # listing -> slot
    free = []  # LIFO stack of released slots
    next_unused = 1
    unsettled = 0
    words = {}
    tx_of_word = {}
    for b, li, ts, tx, e, a in logs:
        if e == "RandomnessCached":
            words[a["requestId"]] = int(a["randomWord"])
            tx_of_word[a["requestId"]] = (tx, b)

    candidates = []
    open_req = None  # (request id, our slot, C(s), W, position)
    for pos, (b, li, ts, tx, e, a) in enumerate(logs):
        if open_req and (e in DISRUPT or (e == "NFTAllocated" and a["requestId"] != open_req["rid"])):
            open_req = None  # history after our insertion would differ: discard
        if e == "AcquisitionRequested":
            if unsettled == 0 and open_req is None and b >= start_block:
                # Our `count` listings activate just before this request's transaction, taking the
                # free-slot head repeatedly, then fresh slots.
                stack, nu, ours = list(free), next_unused, []
                for _ in range(count):
                    if stack:
                        ours.append(stack.pop())
                    else:
                        ours.append(nu)
                        nu += 1
                W = sum(slot_w.values())
                if W != int(a["totalWeight"]):
                    raise SystemExit(f"weight reconstruction broke at block {b}")
                slots = np.array(sorted(list(slot_w) + ours), dtype=np.int64)
                mine = set(ours)
                weights = [w_ours if sl in mine else slot_w[sl] for sl in slots.tolist()]
                open_req = dict(rid=a["requestId"], ours=ours, slots=slots, weights=weights,
                                W=W + count * w_ours, req_tx=tx, req_block=b, req_ts=ts,
                                purchaser=a["purchaser"])
            unsettled += 1
        elif e == "AcquisitionProcessed":
            unsettled -= 1
        elif e == "NFTAllocated" and open_req and a["requestId"] == open_req["rid"]:
            word = words.get(a["requestId"])
            if word is not None:
                target = word % open_req["W"]
                # Exact integer prefix sums: weights reach 1e38, beyond float precision.
                acc = 0
                for sl, w in zip(open_req["slots"].tolist(), open_req["weights"]):
                    acc += w
                    if target < acc:
                        break
                if sl in open_req["ours"]:
                    ftx, fblock = tx_of_word[a["requestId"]]
                    c = {k: v for k, v in open_req.items() if k not in ("slots", "weights")}
                    candidates.append({**c, "word": str(word), "W": str(c["W"]), "selected_slot": sl,
                                       "selected_index": c["ours"].index(sl), "fulfill_tx": ftx,
                                       "fulfill_block": fblock, "alloc_tx": tx, "alloc_block": b,
                                       "historical_listing": a["listingId"]})
            open_req = None
        if e == "NFTListed":
            sl = int(a["slot"])
            slot_w[sl] = int(a["weight"])
            slot_of[int(a["listingId"])] = sl
            if free and free[-1] == sl:
                free.pop()
            elif sl >= next_unused:
                next_unused = sl + 1
            else:
                free.remove(sl)
        elif e == "BackingUpdated":
            lid = int(a["listingId"])
            if lid in slot_of:
                slot_w[slot_of[lid]] = int(a["newWeight"])
        elif e in ("NFTAllocated", "ListingWithdrawn", "ListingKicked"):
            sl = slot_of.pop(int(a["listingId"]), None)
            if sl is not None:
                del slot_w[sl]
                free.append(sl)

    out = ROOT / "out/selection_candidates.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(candidates, indent=1))
    print(f"{len(candidates)} candidates for {count} listings at {backing_wei / 1e18} ETH from block "
          f"{start_block:,}; latest:")
    for c in candidates[-5:]:
        print(f"  block {c['req_block']} tx {c['req_tx']} fulfill {c['fulfill_block']} "
              f"alloc {c['alloc_block']} our #{c['selected_index']} slot {c['selected_slot']}")


if __name__ == "__main__":
    main(*(int(x) for x in sys.argv[1:]))
