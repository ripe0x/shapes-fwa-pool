#!/usr/bin/env python3
"""Phase 0.3 validation: replay FWA's fee accumulator from events with exact integer math.

Mirrors FWAV2: accFeePerEV (1e36 scale) grows by amount * SCALE / activeListingCount at each
selection, before the selected listing is removed; activation and updateBacking set
feeDebt = ceil(acc / SCALE); claimListingFees sets feeDebt = floor(acc / SCALE); pending is
floor(acc / SCALE) - feeDebt, floored at zero. Every EarningsAccrued amount is predicted and
compared with the chain. A full match validates the fee model the simulator uses.
"""
import json
import sqlite3
from pathlib import Path

DB = Path(__file__).parent / "data/fwa.sqlite"
FWA = "0x958c41181182e76f221331b2755b77d9e1426a98"
SCALE, BPS = 10**36, 10_000

# Events _settleReadyAcquisition emits between its _distribute call and NFTAllocated, plus
# TopListingFunded, which immediately precedes _distribute.
SELECTION_TAIL = {"EarningsAccrued", "ListingRewardRemoved", "DepositorTokensAccrued",
                  "TopListingSettled", "TopListingSet", "TopListingFunded"}


def main():
    db = sqlite3.connect(DB)
    logs = [(b, li, tx, c, e, json.loads(a)) for b, li, tx, c, e, a in db.execute(
        "SELECT block, log_index, tx, contract, event, args FROM logs ORDER BY block, log_index")]

    # Locate where each selection's _distribute runs: right after its TopListingFunded, or
    # before the first event of its tail when the top was vacant.
    distribute_at = {}  # log position -> request id; distribution applied before this position
    for p, (_, _, tx, _, ev, a) in enumerate(logs):
        if ev != "NFTAllocated":
            continue
        q = p
        while q > 0 and logs[q - 1][2] == tx and logs[q - 1][4] in SELECTION_TAIL:
            q -= 1
            if logs[q][4] == "TopListingFunded":
                q += 1
                break
        distribute_at[q] = int(a["requestId"])

    fee_of = {}
    cut = 100
    acc = 0
    debt, active = {}, set()
    pending_top = None
    checked = mismatched = 0
    examples = []

    for p, (block, _, tx, contract, ev, a) in enumerate(logs):
        if p in distribute_at:
            rid = distribute_at[p]
            fee = fee_of[rid]
            distributable = fee - fee * cut // BPS
            share = pending_top if pending_top is not None else 0
            acc += (distributable - share) * SCALE // len(active)
            pending_top = None
        if contract == FWA and ev == "ConfigSet" and int(a["key"]) == 18:
            cut = int(a["value"])
        elif ev == "AcquisitionRequested":
            fee_of[int(a["requestId"])] = int(a["acquisitionFee"])
        elif ev == "TopListingFunded":
            pending_top = int(a["amount"])
        elif ev == "NFTListed":
            lid = int(a["listingId"])
            debt[lid] = -(-acc // SCALE)
            active.add(lid)
        elif ev == "BackingUpdated":
            debt[int(a["listingId"])] = -(-acc // SCALE)
        elif ev == "EarningsAccrued":
            lid = int(a["listingId"])
            predicted = max(acc // SCALE - debt[lid], 0)
            checked += 1
            if predicted != int(a["amount"]):
                mismatched += 1
                if len(examples) < 5:
                    examples.append((block, lid, predicted, int(a["amount"])))
            debt[lid] = acc // SCALE  # claim checkpoint; removals discard the listing anyway
        elif ev in ("NFTAllocated", "ListingWithdrawn", "ListingKicked"):
            active.discard(int(a["listingId"]))

    print(f"EarningsAccrued checked {checked:,}; exact matches {checked - mismatched:,}; "
          f"mismatches {mismatched:,}")
    for e in examples:
        print("  block {} listing {} predicted {} chain {}".format(*e))
    return mismatched


if __name__ == "__main__":
    raise SystemExit(1 if main() else 0)
