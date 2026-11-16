#!/usr/bin/env python3
"""Phase 0.2 analysis over sim/data/fwa.sqlite. Writes sim/out/phase0.2.md and CSVs.

Reconstructs every listing's life from FWA events, then reports:
volume, settlement mix (by collection, by backing / floor ask, by purchaser), a
censoring-safe check of the lifetime fee multiple k, exit-window availability, the
ConfigSet timeline and depositor token accrual per sqrt-wei per day.
"""
import bisect
import csv
import json
import sqlite3
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
FWA = "0x958c41181182e76f221331b2755b77d9e1426a98"
PACKS = "0xf21514b090da7df4390803497d6ae673801e5ca7"
BPS = 10_000
INTERVAL, BLACKOUT_START = 12 * 3600, 11 * 3600 + 45 * 60
KEY_NAMES = {
    13: "surchargeBps", 15: "topListingShareBps", 16: "topThresholdBps", 17: "settlementDiscountBps",
    18: "ownerAcquisitionFeeBps", 19: "ownerSettlementFeeBps", 20: "settlementWindow",
    21: "finalizeWindow", 22: "minBacking", 23: "protocolFeeToTokenBps", 25: "maxStagedListings",
    26: "maxOracleAge", 27: "minOracleChallengePeriod", 28: "oracleCeilingPremiumBps",
    29: "tokenSettlementDiscountBps", 40: "retainedToProtocol", 41: "acquisitionsEnabled",
    42: "withdrawOnly", 43: "whitelistEnabled", 44: "acceptBidAsTokensEnabled",
}
OUTCOMES = ["bid_eth", "bid_tokens", "keep", "relist", "finalize"]


def day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def i(v):
    return int(v)


class Listing:
    __slots__ = ("id", "collection", "depositor", "value", "weight", "start", "end", "status",
                 "outcome", "purchaser", "alloc_ts", "settle_ts", "fees", "tokens", "sqrt",
                 "floor_ask", "lam", "c_start")

    def __init__(self, lid):
        self.id, self.fees, self.tokens, self.sqrt = lid, 0, 0, 0
        self.status = self.outcome = self.purchaser = self.floor_ask = None
        self.alloc_ts = self.settle_ts = self.end = None
        self.lam = 0.0


def load():
    db = sqlite3.connect(DB)
    rows = db.execute("SELECT block, log_index, ts, contract, event, args FROM logs "
                      "ORDER BY block, log_index").fetchall()
    return [(b, li, ts, c, e, json.loads(a)) for b, li, ts, c, e, a in rows]


def main():
    OUT.mkdir(exist_ok=True)
    logs = load()
    end_ts = logs[-1][2]
    listings = {}
    floors = defaultdict(list)  # collection -> [(ts, ask)]
    acq_ts, acq_fee, acq_w = [], [], []
    queue = []  # (ts, delta)
    config = []
    # C = sum over selections of 1 / live totalWeight just before the selection. A listing's
    # cumulative selection hazard is weight x (C at exit - C at entry).
    cum_inv_w = [0.0]
    live_w = 0  # reconstructed totalWeight
    w_checks = []  # (reconstructed, reported) at each request
    distributable_total = 0
    top_settled = 0
    crown = 500  # source default; overwritten by ConfigSet
    cut = 100

    def L(lid):
        lid = i(lid)
        if lid not in listings:
            listings[lid] = Listing(lid)
        return listings[lid]

    def close(l, ts, status):
        nonlocal live_w
        l.status, l.end = status, ts
        if l.weight is not None and l.c_start is not None:
            l.lam += l.weight * (cum_inv_w[-1] - l.c_start)
            l.c_start = None
            live_w -= l.weight

    for block, _, ts, contract, ev, a in logs:
        if ev == "ConfigSet" and contract == FWA:
            k, v = i(a["key"]), i(a["value"])
            config.append((block, ts, KEY_NAMES.get(k, f"key{k}"), v))
            if k == 15:
                crown = v
            elif k == 18:
                cut = v
        elif ev in ("FloorRecorded", "ManualFloorSet"):
            ask = i(a.get("askPrice", a.get("newAskPrice", 0)))
            floors[a["collection"].lower()].append((ts, ask))
        elif ev == "FloorCleared":
            floors[a["collection"].lower()].append((ts, 0))
        elif ev == "NFTListed":
            l = L(a["listingId"])
            l.collection, l.depositor = a["collection"].lower(), a["depositor"].lower()
            l.value, l.weight, l.start, l.status = i(a["value"]), i(a["weight"]), ts, "active"
            l.c_start = cum_inv_w[-1]
            live_w += l.weight
        elif ev == "BackingUpdated":
            l = L(a["listingId"])
            if l.c_start is not None:
                l.lam += l.weight * (cum_inv_w[-1] - l.c_start)
                l.c_start = cum_inv_w[-1]
                live_w += i(a["newWeight"]) - l.weight
            l.value, l.weight = i(a["newBacking"]), i(a["newWeight"])
        elif ev == "AcquisitionRequested":
            acq_ts.append(ts)
            acq_fee.append(i(a["acquisitionFee"]))
            acq_w.append(i(a["totalWeight"]))
            w_checks.append((live_w, acq_w[-1]))
            queue.append((ts, 1))
            distributable_total += acq_fee[-1] * (BPS - cut) // BPS
        elif ev == "AcquisitionProcessed":
            queue.append((ts, -1))
        elif ev == "NFTAllocated":
            l = L(a["listingId"])
            # Selection draws from the live tree at processing time: charge every active
            # listing hazard weight / live totalWeight, before removing the selected one.
            if live_w:
                cum_inv_w.append(cum_inv_w[-1] + 1 / live_w)
            l.alloc_ts, l.purchaser = ts, a["purchaser"].lower()
            l.value = i(a["value"])  # backing at allocation
            close(l, ts, "allocated")
            f = floors.get(l.collection)
            if f:
                idx = bisect.bisect_right([t for t, _ in f], ts) - 1
                l.floor_ask = f[idx][1] if idx >= 0 else None
        elif ev in ("DepositorBidAccepted", "DepositorBidAcceptedAsTokens", "NFTKept",
                    "NFTRelisted", "UnsettledFinalized"):
            l = L(a["listingId"])
            if l.outcome is None:  # NFTKept also follows UnsettledFinalized? No: one per path.
                l.outcome = {"DepositorBidAccepted": "bid_eth", "DepositorBidAcceptedAsTokens": "bid_tokens",
                             "NFTKept": "keep", "NFTRelisted": "relist",
                             "UnsettledFinalized": "finalize"}[ev]
                l.settle_ts = ts
            l.status = "settled"
        elif ev == "ListingWithdrawn":
            close(L(a["listingId"]), ts, "withdrawn")
        elif ev == "ListingKicked":
            close(L(a["listingId"]), ts, "kicked")
        elif ev == "EarningsAccrued":
            L(a["listingId"]).fees += i(a["amount"])
        elif ev == "TopListingSettled":
            L(a["listingId"]).fees += i(a["amount"])
            top_settled += i(a["amount"])
        elif ev == "DepositorTokensAccrued":
            L(a["listingId"]).tokens += i(a["amount"])
        elif ev == "ListingRewardActivated":
            L(a["listingId"]).sqrt = i(a["sqrtBacking"])

    for l in listings.values():
        if l.c_start is not None:  # still active at end: hazard to date, fees partly unclaimed
            l.lam += l.weight * (cum_inv_w[-1] - l.c_start)

    md = [f"# Phase 0.2 event analysis\n",
          f"Data: FWA, FWAV2Rewards and CollectionFloorOracle logs, blocks {logs[0][0]:,} to "
          f"{logs[-1][0]:,} ({day(logs[0][2])} to {day(end_ts)}), {len(logs):,} logs.\n"]

    # 1. Volume
    per_day = Counter(day(t) for t in acq_ts)
    days = sorted(per_day)
    with open(OUT / "daily_acquisitions.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["day", "acquisitions", "mean_fee_eth"])
        fees_by_day = defaultdict(list)
        for t, fee in zip(acq_ts, acq_fee):
            fees_by_day[day(t)].append(fee)
        for d in days:
            w.writerow([d, per_day[d], f"{statistics.mean(fees_by_day[d]) / 1e18:.5f}"])

    def trailing(n):
        window = [t for t in acq_ts if t > end_ts - n * 86400]
        return len(window) / n

    md.append("## 1. Volume\n")
    md.append(f"Total acquisitions {len(acq_ts):,}. First 28 days {sum(per_day[d] for d in days[:28]) / 28:,.0f}/day.")
    md.append(f"Trailing averages: 1 d {trailing(1):.0f}, 7 d {trailing(7):.1f}, 30 d {trailing(30):.1f}, "
              f"60 d {trailing(60):.1f} per day.\n")
    md.append("| week starting | acquisitions/day |\n|---|---|")
    for wk in range(0, len(days), 7):
        chunk = days[wk:wk + 7]
        md.append(f"| {chunk[0]} | {sum(per_day[d] for d in chunk) / len(chunk):,.1f} |")
    md.append("")

    # 2. Settlement mix
    settled = [l for l in listings.values() if l.alloc_ts is not None]

    def mix(group):
        c = Counter(l.outcome or "pending" for l in group)
        n = len(group)
        return n, " | ".join(f"{100 * c[o] / n:.0f}%" if n else "-" for o in OUTCOMES + ["pending"])

    head = "| group | n | " + " | ".join(OUTCOMES + ["pending"]) + " |\n|" + "---|" * (len(OUTCOMES) + 3)
    md.append("## 2. Settlement mix\n")
    md.append("`keep` includes `depositorReclaimBacking`; `bid_eth` includes `depositorReclaimNFT` "
              "(same events). Late = settled after the 1 h purchaser window.\n")
    md.append("### By collection (top 12 by allocations, plus shape packs)\n")
    md.append(head)
    by_col = defaultdict(list)
    for l in settled:
        by_col[l.collection].append(l)
    cols = sorted(by_col, key=lambda c: -len(by_col[c]))[:12]
    if PACKS in by_col and PACKS not in cols:
        cols.append(PACKS)
    for c in cols:
        n, m = mix(by_col[c])
        md.append(f"| {'SHAPE PACKS' if c == PACKS else c} | {n} | {m} |")
    md.append(f"| all | {mix(settled)[0]} | {mix(settled)[1]} |\n")

    md.append("### By backing / floor ask at allocation (collections with a floor quote)\n")
    md.append(head)
    buckets = [(0, 0.9), (0.9, 1.0), (1.0, 1.05), (1.05, 1.1), (1.1, 1.15), (1.15, 1.25), (1.25, 9)]
    rated = [l for l in settled if l.floor_ask]
    for lo, hi in buckets:
        g = [l for l in rated if lo <= l.value / l.floor_ask < hi]
        if g:
            n, m = mix(g)
            md.append(f"| r {lo:.2f}-{hi:.2f} | {n} | {m} |")
    md.append("")

    md.append("### By purchaser (top 10 by allocations)\n")
    md.append(head)
    by_p = defaultdict(list)
    for l in settled:
        by_p[l.purchaser].append(l)
    for p in sorted(by_p, key=lambda p: -len(by_p[p]))[:10]:
        n, m = mix(by_p[p])
        md.append(f"| {p} | {n} | {m} |")
    late = [l for l in settled if l.settle_ts and l.settle_ts - l.alloc_ts > 3600]
    md.append(f"\nSettled after 1 h: {len(late)} of {len([l for l in settled if l.outcome])}. "
              f"Median time to settle: "
              f"{statistics.median([l.settle_ts - l.alloc_ts for l in settled if l.settle_ts]) / 60:.1f} min.\n")

    # 3. k check
    terminal = [l for l in listings.values() if l.status in ("allocated", "settled", "withdrawn", "kicked")
                and l.weight]
    num = sum(l.fees for l in terminal)
    den = sum(l.value * l.lam for l in terminal)
    sel = sum(1 for l in terminal if l.alloc_ts)
    exp_sel = sum(l.lam for l in terminal)
    md.append("## 3. Lifetime fee multiple k\n")
    md.append("Estimator: fees credited to terminal listings / sum of backing x cumulative selection "
              "hazard (weight / totalWeight per acquisition while active). Unbiased under "
              "withdrawal censoring; equals k when selection is proportional to weight.\n")
    exact = sum(1 for r, t in w_checks if r == t)
    md.append(f"- Reconstructed totalWeight equals the reported value at {exact:,} of {len(w_checks):,} requests.")
    md.append(f"- Terminal listings {len(terminal):,} (active listings excluded from both sides of k).")
    md.append("\nSelection fairness: selections vs cumulative hazard, all listings, by backing at exit.\n")
    md.append("| backing ETH | listings | selections | hazard-expected | ratio |\n|---|---|---|---|---|")
    allw = [l for l in listings.values() if l.weight]
    for lo, hi in [(0, 0.02), (0.02, 0.03), (0.03, 0.04), (0.04, 0.06), (0.06, 0.1), (0.1, 0.3), (0.3, 1e9)]:
        g = [l for l in allw if lo <= l.value / 1e18 < hi]
        if g:
            s_, e_ = sum(1 for l in g if l.alloc_ts), sum(l.lam for l in g)
            md.append(f"| {lo}-{hi if hi < 1e9 else 'max'} | {len(g):,} | {s_:,} | {e_:,.0f} | {s_ / e_:.3f} |")
    md.append("")
    md.append(f"- k estimate {num / den:.4f} over the whole history (crown share was 5% for part of it).")
    for lo, hi, label in [(0, 26_078_548, "before crown cut to 0.1%"), (26_078_548, 10**9, "after")]:
        g = [l for l in terminal if l.start is not None and lo <= block_of(l, logs) < hi]
        d = sum(l.value * l.lam for l in g)
        if d:
            md.append(f"- {label}: k {sum(l.fees for l in g) / d:.4f} over {len(g):,} listings")
    md.append("\n| backing ETH | terminal listings | k estimate |\n|---|---|---|")
    for lo, hi in [(0, 0.03), (0.03, 0.04), (0.04, 0.06), (0.06, 0.1), (0.1, 1e9)]:
        g = [l for l in terminal if lo <= l.value / 1e18 < hi and l.start is not None
             and block_of(l, logs) >= 26_078_548]
        d = sum(l.value * l.lam for l in g)
        if d:
            md.append(f"| {lo}-{hi if hi < 1e9 else 'max'} | {len(g):,} | {sum(l.fees for l in g) / d:.4f} |")
    md.append("\n(listings that started after the crown cut to 0.1%, block 26,078,548)\n")
    alloc = [l for l in terminal if l.alloc_ts]
    md.append(f"- Naive mean fees/backing over allocated listings: "
              f"{statistics.mean(l.fees / l.value for l in alloc):.4f} (biased low by censoring).")
    md.append(f"- Conservation: fees credited to all listings {sum(l.fees for l in listings.values()) / 1e18:,.3f} ETH "
              f"vs distributable {distributable_total / 1e18:,.3f} ETH "
              f"(difference is unclaimed pending fees, crown pot and the retained bid share is excluded).\n")

    # 4. Exit windows
    queue.sort()
    md.append("## 4. Queue lock and exit windows\n")
    count, locked, last_t, idx = 0, 0, queue[0][0], 0
    windows_total = windows_ok = 0
    ok_by_day = Counter()
    t0 = (queue[0][0] // INTERVAL) * INTERVAL
    events_sorted = queue
    # Walk each 12 h interval; usable if count reaches 0 at some point in [blackout start, end).
    count = 0
    j = 0
    for start in range(t0, end_ts - INTERVAL, INTERVAL):
        b0, b1 = start + BLACKOUT_START, start + INTERVAL
        while j < len(events_sorted) and events_sorted[j][0] < b0:
            prev_t = events_sorted[j][0]
            if count > 0:
                locked += prev_t - last_t
            last_t = prev_t
            count += events_sorted[j][1]
            j += 1
        usable = count == 0
        while j < len(events_sorted) and events_sorted[j][0] < b1:
            prev_t = events_sorted[j][0]
            if count > 0:
                locked += prev_t - last_t
            last_t = prev_t
            count += events_sorted[j][1]
            j += 1
            usable = usable or count == 0
        windows_total += 1
        windows_ok += usable
        ok_by_day[day(start)] += usable
    span = end_ts - queue[0][0]
    md.append(f"- Queue non-empty {100 * locked / span:.1f}% of the time.")
    md.append(f"- Blackouts with a drained queue (usable exit window): {windows_ok} of {windows_total}.")
    recent = sorted(ok_by_day)[-30:]
    md.append(f"- Last 30 days: {sum(ok_by_day[d] for d in recent)} usable of {2 * len(recent)}; "
              f"days with zero usable windows: {sum(1 for d in recent if ok_by_day[d] == 0)}.\n")

    # 5. Config timeline
    md.append("## 5. ConfigSet timeline (economic keys, changes only)\n\n"
              "| block | date | key | value |\n|---|---|---|---|")
    seen = {}
    for b, ts, name, v in config:
        if name.startswith("key") or seen.get(name) == v:
            continue
        seen[name] = v
        md.append(f"| {b:,} | {day(ts)} | {name} | {v} |")
    md.append("")

    # 6. Tokens
    tok = [l for l in terminal if l.sqrt and l.tokens and l.start is not None]
    md.append("## 6. Depositor token accrual\n")
    if tok:
        rates = [l.tokens / (l.sqrt * max((l.end or end_ts) - l.start, 1) / 86400) for l in tok]
        by_end = defaultdict(list)
        for l, r in zip(tok, rates):
            by_end[day(l.end or end_ts)[:7]].append(r)
        md.append(f"Tokens (wei) per sqrt-wei of backing per day, terminal listings with accruals "
                  f"({len(tok):,}): median {statistics.median(rates):.4g}.\n")
        md.append("| month ended | listings | median rate | example: 0.0363 ETH listing, tokens/day |\n|---|---|---|---|")
        sq = int((36_300_000_000_000_000) ** 0.5)
        for m in sorted(by_end):
            r = statistics.median(by_end[m])
            md.append(f"| {m} | {len(by_end[m])} | {r:.4g} | {r * sq / 1e18:.4g} |")
    else:
        md.append("No depositor token accruals found.")
    md.append("")

    # 7. Shape packs
    packs = [l for l in listings.values() if l.collection == PACKS]
    md.append("## 7. Shape packs\n")
    md.append(f"Listings {len(packs)}: " + ", ".join(
        f"#{l.id} B {l.value / 1e18:.4f} {l.status}{'/' + l.outcome if l.outcome else ''}" for l in packs))
    md.append("")

    (OUT / "phase0.2.md").write_text("\n".join(md))
    print("\n".join(md))


_block_cache = {}


def block_of(l, logs):
    # Listing start block, from its NFTListed timestamp (blocks are monotone in time).
    if not _block_cache:
        for b, _, ts, _, ev, a in logs:
            if ev == "NFTListed":
                _block_cache[int(a["listingId"])] = b
    return _block_cache.get(l.id, 0)


if __name__ == "__main__":
    main()
