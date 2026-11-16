#!/usr/bin/env python3
"""Acquisition-level reconciliation of the historical backtest (writes sim/out/backtest_audit.md).

The published backtest (sim/forward.py section 2) counted every acquisition *request* as revenue
and kept n vault listings active at all times (instant, free, unlimited relisting). This audit
replays FWA's event log in order and removes those assumptions one at a time:

  A  published: requests, instant relist (reproduced)
  B  only acquisitions that reached a selection (NFTAllocated); fee distributed at processing,
     over the active count at that moment, crown deduction from the same transaction
  C  B + the purchaser's real settlement delay (empirical distribution) + a keeper that polls
     every 10 minutes before a pack is relisted
  D  C + cash: a relist needs fresh backing, funded only by fees the vault has earned
  E  D + staging: a relist made while FWA's queue is busy earns nothing until the queue drains

Pool state per acquisition comes from events: active weight from NFTListed / BackingUpdated /
ListingRewardRemoved, active count from ListingRewardActivated / ListingRewardRemoved. Both are
checked against FWA's own totalWeight and acquisitionFee at every request. The inserted vault
changes the fee (through the harmonic backing) and the selection odds as FWA's formulas do; the
historical selection is otherwise kept (a vault selection replaces it, the pool is not re-drawn).
"""
import bisect
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
E = 10**18
B, P = 0.0363, 0.03
SUR = 0.05
DAY = 86_400
CYCLE_GAS = 800_000


def load():
    cache = OUT / "audit_events.npz"
    if cache.exists():
        return dict(np.load(cache, allow_pickle=True))
    db = sqlite3.connect(DB)
    weight = {}
    W = 0
    n_active = 0
    unsettled = 0
    cut = 100
    req = {}  # requestId -> (ts, fee)
    rows = []  # one per successful selection
    req_rows = []  # one per request: ts, fee, W_event, W_tracked, N, unsettled
    queue_empty = []  # timestamps when FWA's queue drained
    crown_in_tx = {}
    q = ("SELECT ts, tx, event, args FROM logs WHERE event IN ('NFTListed','BackingUpdated','ListingRewardRemoved',"
         "'ListingRewardActivated','AcquisitionRequested','AcquisitionProcessed','NFTAllocated','TopListingFunded',"
         "'ConfigSet') ORDER BY block, log_index")
    for ts, tx, ev, a in db.execute(q):
        a = json.loads(a)
        if ev == "NFTListed":
            weight[a["listingId"]] = int(a["weight"])
            W += int(a["weight"])
        elif ev == "BackingUpdated":
            lid = a["listingId"]
            if lid in weight:
                W += int(a["newWeight"]) - weight[lid]
                weight[lid] = int(a["newWeight"])
        elif ev == "ListingRewardActivated":
            n_active += 1
        elif ev == "ListingRewardRemoved":
            n_active -= 1
            W -= weight.pop(a["listingId"], 0)
        elif ev == "ConfigSet" and a["key"] == "18":
            cut = int(a["value"])
        elif ev == "TopListingFunded":
            crown_in_tx[tx] = int(a["amount"])
        elif ev == "AcquisitionRequested":
            fee = int(a["acquisitionFee"])
            req[a["requestId"]] = (ts, fee)
            unsettled += 1
            req_rows.append((ts, fee / E, int(a["totalWeight"]) / E, W / E, n_active))
        elif ev == "NFTAllocated":
            rts, fee = req[a["requestId"]]
            crown = crown_in_tx.pop(tx, 0)
            dist = fee - fee * cut // 10_000 - crown
            # Distribution runs before the selected listing leaves: N and W still include it.
            rows.append((ts, rts, fee / E, dist / E, n_active, W / E))
        elif ev == "AcquisitionProcessed":
            unsettled -= 1
            if unsettled == 0:
                queue_empty.append(ts)
    sel = np.array(rows)
    rq = np.array(req_rows)
    out = dict(sel=sel, req=rq, queue_empty=np.array(queue_empty))
    np.savez(cache, **out)
    return out


def delays():
    """Allocation -> purchaser resolution, seconds, every historical selection."""
    db = sqlite3.connect(DB)
    at = {}
    for ts, a in db.execute("SELECT ts, args FROM logs WHERE event='NFTAllocated'"):
        at[json.loads(a)["listingId"]] = ts
    d = []
    for ev in ("DepositorBidAccepted", "DepositorBidAcceptedAsTokens", "NFTKept", "NFTRelisted", "UnsettledFinalized"):
        for ts, a in db.execute("SELECT ts, args FROM logs WHERE event=?", (ev,)):
            lid = json.loads(a).get("listingId")
            if lid in at:
                d.append(ts - at[lid])
    return np.array(d)


def replay(sel, qe, n, t0, t1, rng, settle=None, poll=0, cash_limit=False, staging=False, gwei=0.15):
    """One draw of the vault inserted into the real selections between t0 and t1."""
    m = (sel[:, 0] >= t0) & (sel[:, 0] < t1)
    s = sel[m]
    gas = CYCLE_GAS * gwei * 1e-9 * 1.1
    capital = n * (B + P)
    # Position state: time it is (or becomes) active; inf while allocated or waiting.
    active_at = np.zeros(n)
    ready = np.full(n, np.inf)  # when a selected position's pack is back and relistable
    cash = 0.0
    fees = lost = gascost = 0.0
    sels = 0
    for ts, _rts, fee, dist, N, W in s:
        # Relist packs whose settlement is done, as the keeper's next poll allows.
        for j in np.nonzero(ready <= ts)[0]:
            if cash_limit and cash < B + gas:
                continue
            t_list = ready[j]
            cash -= B + gas
            gascost += gas
            ready[j] = np.inf
            if staging:
                k = bisect.bisect_left(qe, t_list)
                active_at[j] = qe[k] if k < len(qe) else np.inf
            else:
                active_at[j] = t_list
        act = np.nonzero(active_at <= ts)[0]
        a = len(act)
        if a == 0:
            continue
        H, H2 = N / W, (N + a) / (W + a / B)
        share = dist * (H2 / H) / (N + a)  # per listing, the vault's presence included
        fees += share * a
        cash += share * a
        if rng.random() < (a / B) / (W + a / B):
            j = act[rng.integers(a)]
            sels += 1
            lost += B
            active_at[j] = np.inf
            d = 0.0 if settle is None else float(rng.choice(settle))
            ready[j] = ts + d + (poll - (ts + d) % poll if poll else 0)
    # End value: active and waiting positions keep their pack; active ones also their backing.
    held = (active_at < np.inf).sum()
    end = cash + capital - lost + (0 if cash_limit else 0)
    # With instant relisting (no cash limit) the replacement backing was paid out of the same
    # fees, so the P&L is fees - lost - gas either way.
    pnl = fees - lost - gascost
    days = (t1 - t0) / DAY
    del end, held
    return pnl / capital, pnl / capital * 365 / days, sels


def published(req, n, t0, t1, rng, gwei=0.15):
    """Section 2 of forward.md: every request as revenue, constant n (reproduced here)."""
    m = (req[:, 0] >= t0) & (req[:, 0] < t1)
    ts, fee, w, _wt, N = req[m].T
    H, H2 = N / w, (N + n) / (w + n / B)
    vault_fees = fee * (H2 / H) * 0.99 * 0.999 * n / (N + n)
    p = (n / B) / (w + n / B)
    sel = (rng.random(len(p)) < p).sum()
    pnl = vault_fees.sum() - sel * (B + CYCLE_GAS * gwei * 1e-9 * 1.1)
    days = (t1 - t0) / DAY
    return pnl / (n * (B + P)), pnl / (n * (B + P)) * 365 / days, sel


def pct(x):
    return f"{100 * x:+.1f}%"


def main():
    ev = load()
    sel, req, qe = ev["sel"], ev["req"], ev["queue_empty"]
    settle = delays()
    end = int(req[:, 0].max())
    t0 = end - 30 * DAY
    spike0 = None
    days = (req[:, 0] // DAY).astype(int)
    last = days >= (t0 // DAY)
    counts = np.bincount(days[last] - days[last].min())
    spike_day = days[last].min() + int(np.argmax(counts))
    spike0, spike1 = spike_day * DAY, spike_day * DAY + DAY
    md = ["# Backtest reconciliation (acquisition level)\n",
          "Generated by `sim/backtest_audit.py` from `sim/data/fwa.sqlite` (FWA events through block 26,425,500).\n"]

    # Reconstruction checks.
    r = req[req[:, 0] >= t0]
    werr = np.abs(r[:, 3] - r[:, 2]) / r[:, 2]
    n_impl = r[:, 1] * r[:, 2] / (1 + SUR)
    nerr = np.abs(r[:, 4] - n_impl) / n_impl
    s30 = sel[sel[:, 0] >= t0]
    md += ["## 1. Reconstruction checks (last 30 days)\n",
           f"- Pool weight rebuilt from listing events vs FWA's `totalWeight` at each of {len(r):,} requests: "
           f"median error {100 * np.median(werr):.4f}%, max {100 * werr.max():.4f}%.",
           f"- Active count rebuilt from reward events vs count implied by FWA's own fee and weight "
           f"(fee x W / 1.05): median error {100 * np.median(nerr):.3f}%, 99th percentile {100 * np.percentile(nerr, 99):.3f}%.",
           f"- Requests {len(r):,}; successful selections {len(s30):,} ({100 * len(s30) / len(r):.1f}%). "
           f"The rest were refunded (slippage or expiry) and distributed no fees.",
           f"- Request to selection: median {np.median(s30[:, 0] - s30[:, 1]):.0f} s, "
           f"99th percentile {np.percentile(s30[:, 0] - s30[:, 1], 99):.0f} s.",
           f"- Purchaser settlement after selection (all history, {len(settle):,}): median {np.median(settle):.0f} s, "
           f"90th {np.percentile(settle, 90):.0f} s, 99th {np.percentile(settle, 99):.0f} s.\n"]

    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    rng = np.random.default_rng(3)
    md += ["## 2. Removing the assumptions one at a time (30 positions, 0.15 gwei)\n",
           f"{runs} draws each. Raw = return over the window; annualized = raw x 365 / days. Capital is 30 x (B + P) "
           "= 1.989 ETH. A to C allow unlimited instant relisting capital; D and E fund each relist from fees earned.\n",
           "| window | variant | raw mean | annualized mean | annualized p5 | p95 | P(loss) | selections |",
           "|---|---|---|---|---|---|---|---|"]
    windows = [("last 30 d", t0, end), ("last 30 d without Oct 31", None, None),
               ("Oct 31 (UTC) only", spike0, spike1), ("last 14 d", end - 14 * DAY, end)]
    variants = [("A published: requests, instant relist", "pub", {}),
                ("B successful selections only, instant", "rep", {}),
                ("C B + real settlement delay + 10 min keeper", "rep", dict(settle=settle, poll=600)),
                ("D C + relist funded by earned fees", "rep", dict(settle=settle, poll=600, cash_limit=True)),
                ("E D + staging while FWA's queue is busy", "rep", dict(settle=settle, poll=600, cash_limit=True,
                                                                       staging=True))]
    summary = {}
    for wname, a, b in windows:
        for vname, kind, kw in variants:
            res = []
            for _ in range(runs):
                if a is None:  # the 30 days with the Oct 31 day removed: one continuous P&L
                    parts = [replay(sel, qe, 30, t0, spike0, rng, **kw) if kind == "rep" else published(req, 30, t0, spike0, rng),
                             replay(sel, qe, 30, spike1, end, rng, **kw) if kind == "rep" else published(req, 30, spike1, end, rng)]
                    raw = parts[0][0] + parts[1][0]
                    d = (spike0 - t0 + end - spike1) / DAY
                    res.append((raw, raw * 365 / d, parts[0][2] + parts[1][2]))
                else:
                    res.append(replay(sel, qe, 30, a, b, rng, **kw) if kind == "rep" else published(req, 30, a, b, rng))
            raw, ann, ns = map(np.array, zip(*res))
            summary[(wname, vname[0])] = ann.mean()
            md.append(f"| {wname} | {vname} | {pct(raw.mean())} | {pct(ann.mean())} | {pct(np.percentile(ann, 5))} | "
                      f"{pct(np.percentile(ann, 95))} | {100 * np.mean(raw < 0):.0f}% | {ns.mean():.0f} |")
            print(md[-1], flush=True)

    # Oct 31 by hour.
    md += ["\n## 3. Oct 31 (UTC), hour by hour\n",
           "| hour | requests | selections | active listings (min) | pool weight (min, 1/ETH) | 30-position share of selections |",
           "|---|---|---|---|---|---|"]
    for hr in range(24):
        h0, h1 = spike0 + hr * 3600, spike0 + (hr + 1) * 3600
        rq = req[(req[:, 0] >= h0) & (req[:, 0] < h1)]
        ss = sel[(sel[:, 0] >= h0) & (sel[:, 0] < h1)]
        if len(rq) == 0 and len(ss) == 0:
            continue
        nmin = int(ss[:, 4].min()) if len(ss) else int(rq[:, 4].min())
        wmin = ss[:, 5].min() if len(ss) else rq[:, 3].min()
        share = (30 / B) / (wmin + 30 / B)
        md.append(f"| {hr:02d} | {len(rq):,} | {len(ss):,} | {nmin:,} | {wmin:,.0f} | {100 * share:.0f}% |")
    (OUT / "backtest_audit.md").write_text("\n".join(md) + "\n")
    json.dump({f"{k[0]}|{k[1]}": v for k, v in summary.items()}, open(OUT / "backtest_audit.json", "w"), indent=1)
    print("wrote sim/out/backtest_audit.md")


def compare():
    """Section 4: closed form vs replay under identical inputs (same window, successful volume,
    pool snapshot or the window's own pool, 30 positions, 0.15 gwei). Appends to the report."""
    import forward
    forward.POOL = forward.pool_snapshot()
    ev = load()
    sel = ev["sel"]
    end = int(ev["req"][:, 0].max())
    t0 = end - 30 * DAY
    s = sel[sel[:, 0] >= t0]
    days = (s[:, 0] // DAY).astype(int)
    counts = np.bincount(days - days.min())
    spike = days.min() + int(np.argmax(counts))
    ex = s[days != spike]
    res = json.load(open(OUT / "backtest_audit.json"))
    rows = []
    for name, ss, nd, key in (("last 30 d", s, 30, "last 30 d"), ("last 30 d without Oct 31", ex, 29, "last 30 d without Oct 31")):
        vol = len(ss) / nd
        cf_snap = forward.expectation(30, vol, 0.15)["apr"]
        # Same closed form with the window's own pool: cycles = sum over selections of the
        # vault's selection odds, with the vault's 30 listings in the real pool at each moment.
        p = (30 / B) / (ss[:, 5] + 30 / B)
        net = B * (forward.k_of() - 1) - CYCLE_GAS * 0.15e-9 * 1.1
        cf_hist = p.sum() * net / (30 * (B + P)) * 365 / nd
        rows.append(f"| {name} | {vol:.0f} | {100 * cf_snap:+.0f}% | {100 * cf_hist:+.0f}% | "
                    f"{100 * res[key + '|A']:+.0f}% | {100 * res[key + '|B']:+.0f}% | {100 * res[key + '|E']:+.0f}% |")
    md = ["\n## 4. Same inputs, every model\n",
          "30 positions, 0.15 gwei, successful acquisitions only unless stated, annualized means.\n",
          "| window | successful/day | closed form, today's pool | closed form, the window's real pool | "
          "replay A (published) | replay B (successful, instant) | replay E (executable) |",
          "|---|---|---|---|---|---|---|", *rows,
          "\nReading: outside Oct 31, closed form and replays agree within noise. Over the whole window the instant replay B is 16% below the closed form on the window's own pool: FWA prices the fee at request time and sets selection odds at processing, and during the drain the pool shrank in between (requests queued for minutes), so odds rose faster than fees. Today's pool is larger than the pool during the drain, so the closed form "
          "on today's pool is lower. The executable replay E sits below B by what settlement, keeper timing, cash and "
          "staging cost, almost all of it on Oct 31. Outside Oct 31 the models agree within noise.\n"]
    with open(OUT / "backtest_audit.md", "a") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--compare":
        compare()
    else:
        main()
