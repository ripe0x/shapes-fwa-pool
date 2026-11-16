#!/usr/bin/env python3
"""Phase 0.3 forward model: vault returns from injected pack positions, closed form plus
Monte Carlo, under live parameters and the plan's stress set. Writes sim/out/phase0.3.md.

Mechanics (FWAV2, validated exactly by sim/replay.py):
- An acquisition costs F = H (1 + surcharge), H = harmonic-mean backing of active listings.
- F (1 - protocolCut) (1 - crownShare) is split equally across active listings.
- Selection probability of a listing is (1 / B) / sum(1 / B_i).
- So every listing's expected fees until selection are k B, k = (1+sur)(1-cut)(1-crown).
- Bid outcome (purchaser takes ETH or tokens): depositor loses B, keeps the NFT: net B (k - 1).
- Keep outcome: depositor gets B (1 - s) back, loses the NFT worth P: net B (k - s) - P.
Gas inputs come from sim/out/gas.json (Phase 0.4 fork measurements) when present.
"""
import json
import sqlite3
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).parent
DB = ROOT / "data/fwa.sqlite"
OUT = ROOT / "out"
E = 10**18

LIVE = dict(sur=0.05, cut=0.01, crown=0.001, s=0.01, bid_payout=0.90, token_payout=0.915,
            ask=0.033, premium=0.10, min_backing=0.025, mint_fee=0.001)
# Gas per operation, in gas units. Placeholders until 0.4 replaces them with fork measurements.
GAS_ESTIMATE = dict(list=380_000, earnings_batch=45_000, harvest_per_id=12_000,
                    mint_split_per_pack=230_000, create_pack=320_000, vault_overhead=60_000,
                    checkpoint=150_000)


def gas_table():
    f = OUT / "gas.json"
    if f.exists():
        return json.loads(f.read_text()), "measured (sim/out/gas.json)"
    return GAS_ESTIMATE, "ESTIMATED placeholders"


def pool_snapshot():
    """Active listing backings (ETH) at the end of the ingested history, and the last block."""
    db = sqlite3.connect(DB)
    value = {}
    for ev, a in db.execute("SELECT event, args FROM logs WHERE event IN ('NFTListed','BackingUpdated',"
                            "'NFTAllocated','ListingWithdrawn','ListingKicked') ORDER BY block, log_index"):
        a = json.loads(a)
        lid = int(a["listingId"])
        if ev == "NFTListed":
            value[lid] = int(a["value"]) / E
        elif ev == "BackingUpdated" and lid in value:
            value[lid] = int(a["newBacking"]) / E
        else:
            value.pop(lid, None)
    block = db.execute("SELECT max(block) FROM logs").fetchone()[0]
    return np.array(list(value.values())), block


def trailing_volume(days):
    db = sqlite3.connect(DB)
    end = db.execute("SELECT max(ts) FROM logs").fetchone()[0]
    n = db.execute("SELECT count(*) FROM logs WHERE event='AcquisitionRequested' AND ts > ?",
                   (end - days * 86400,)).fetchone()[0]
    return n / days


def scenario(pool, lam, n, P=0.03, B=None, p=LIVE, gwei=1.2, keep_irrational=0.0,
             token_value=0.0, gas=None, eth_buffer=0.0):
    """Expected annual economics for n vault positions at backing B."""
    gas = gas or GAS_ESTIMATE
    cap = p["ask"] * (1 + p["premium"])
    B = min(cap, B or cap) - eth_buffer
    k = (1 + p["sur"]) * (1 - p["cut"]) * (1 - p["crown"])
    W = np.sum(1 / pool) + n / B
    sel_per_pos_year = 365 * lam * (1 / B) / W
    # Rational purchaser keeps iff the pack is worth more than the best bid it can take.
    best_bid = max(p["bid_payout"], p["token_payout"] * (1 if token_value > 0 else 0)) * B
    rational_keep = P > best_bid
    q_keep = 1.0 if rational_keep else keep_irrational
    gwei_eth = gwei * 1e-9
    gas_cycle = (gas["list"] + gas["vault_overhead"] + gas["harvest_per_id"]) * gwei_eth
    gas_restock = (gas["mint_split_per_pack"] + gas["create_pack"]) * gwei_eth
    restock_fee = p["mint_fee"] / 10 * 3  # one 0.1 shape split into ten 0.01s, three per pack
    bid_net = B * (k - 1) - gas_cycle
    keep_net = B * (k - p["s"]) - P - gas_cycle - gas_restock - restock_fee
    per_cycle = (1 - q_keep) * bid_net + q_keep * keep_net
    capital = P + B
    # Depositor FWA token accrual is valued at zero unless token_value (ETH per position-year) set.
    annual = sel_per_pos_year * per_cycle + token_value
    H_after = (len(pool) + n) / W
    return dict(B=B, k=k, r=B / P, rational_keep=rational_keep, q_keep=q_keep,
                cycle_days=365 / sel_per_pos_year, bid_net=bid_net, keep_net=keep_net,
                per_cycle=per_cycle, apr=annual / capital, capital_total=n * capital,
                pool_share=(n / B) / W, H=H_after, gas_cycle=gas_cycle,
                breakeven_gwei=B * (k - 1) / ((gas["list"] + gas["vault_overhead"] + gas["harvest_per_id"]) * 1e-9))


def monte_carlo(pool, lam, n, days=365, runs=20_000, seed=7, **kw):
    """Distribution of realized return over `days`: fees accrue per acquisition, selections are
    Poisson with the model's rate. Bid outcome only when the purchaser is rational."""
    sc = scenario(pool, lam, n, **kw)
    rng = np.random.default_rng(seed)
    rate = n * days / sc["cycle_days"]
    selections = rng.poisson(rate, runs)
    capital = sc["capital_total"]
    # Expected fees per selection are k B; fees per unit time are deterministic given volume.
    fees = rate * sc["k"] * sc["B"]
    loss_per_sel = sc["B"] if not sc["rational_keep"] else -(sc["B"] * (1 - LIVE["s"]) - 0.03)
    gas = selections * sc["gas_cycle"]
    pnl = fees - selections * loss_per_sel - gas
    ret = pnl / capital * 365 / days
    return np.percentile(ret, [5, 50, 95]), float(np.mean(ret < 0))


def main():
    OUT.mkdir(exist_ok=True)
    gas, gas_src = gas_table()
    pool, block = pool_snapshot()
    vol = {d: trailing_volume(d) for d in (1, 7, 30, 60)}
    H = len(pool) / np.sum(1 / pool)
    md = ["# Phase 0.3 model\n",
          f"Pool at block {block:,}: {len(pool):,} active listings, harmonic backing {H:.4f} ETH.",
          f"Volume (acquisitions/day): 1 d {vol[1]:.0f}, 7 d {vol[7]:.1f}, 30 d {vol[30]:.1f}, 60 d {vol[60]:.1f}.",
          f"Gas table: {gas_src}.\n",
          "Assumptions: pack P = 0.03 ETH; backing at the oracle cap 0.0363; FWA tokens valued at zero; "
          "pool composition and volume stationary; volume does not respond to vault size.\n"]

    def row(label, **kw):
        lam = kw.pop("lam", vol[30])
        n = kw.pop("n", 50)
        sc = scenario(pool, lam, n, gas=gas, **kw)
        return (f"| {label} | {lam:.0f} | {n} | {sc['B']:.4f} | {sc['k']:.4f} | "
                f"{'keep' if sc['rational_keep'] else 'bid'} | {sc['cycle_days']:.0f} | "
                f"{sc['per_cycle'] * 1000:+.3f} | {100 * sc['apr']:+.1f}% | {sc['capital_total']:.1f} | "
                f"{100 * sc['pool_share']:.1f}% |")

    head = ("| scenario | acq/day | positions | B | k | purchaser | cycle days | net/cycle mETH | "
            "APR | capital ETH | selection share |\n|---|---|---|---|---|---|---|---|---|---|---|")
    md += ["## Base case and capacity (30-day volume, 1.2 gwei)\n", head]
    for n in (1, 10, 50, 150, 500):
        md.append(row(f"{n} positions", n=n))
    md += ["", "## Volume\n", head]
    for lam in (vol[1], 15, vol[7], vol[30], 80, 250):
        md.append(row(f"{lam:.0f}/day", lam=lam))
    md += ["", "## Stress (50 positions, 30-day volume)\n", head]
    md.append(row("live"))
    md.append(row("gas 5 gwei", gwei=5))
    md.append(row("gas 20 gwei", gwei=20))
    md.append(row("crown share back to 5%", p={**LIVE, "crown": 0.05}))
    md.append(row("crown 0.5%", p={**LIVE, "crown": 0.005}))
    md.append(row("floor ask cut to 0.0300", p={**LIVE, "ask": 0.030}))
    md.append(row("floor ask cut to 0.0275", p={**LIVE, "ask": 0.0275}))
    md.append(row("floor ask cut to 0.0265", p={**LIVE, "ask": 0.0265}))
    md.append(row("20% irrational keeps", keep_irrational=0.2))
    md.append(row("15/day and 5 gwei", lam=15, gwei=5))
    sc = scenario(pool, vol[30], 50, gas=gas)
    md.append(f"\nBreak-even gas price for the bid outcome: {sc['breakeven_gwei']:.1f} gwei "
              f"(gas per cycle {(gas['list'] + gas['vault_overhead'] + gas['harvest_per_id']):,}).\n")

    md += ["## Realized-return spread (Monte Carlo, one year, 30-day volume)\n",
           "| positions | p5 | median | p95 | P(loss) |\n|---|---|---|---|---|"]
    for n in (1, 10, 50, 150):
        (p5, p50, p95), ploss = monte_carlo(pool, vol[30], n, gas=gas)
        md.append(f"| {n} | {100 * p5:+.1f}% | {100 * p50:+.1f}% | {100 * p95:+.1f}% | {100 * ploss:.0f}% |")
    md.append("")
    (OUT / "phase0.3.md").write_text("\n".join(md))
    print("\n".join(md))


if __name__ == "__main__":
    sys.exit(main())
