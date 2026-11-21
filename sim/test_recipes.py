#!/usr/bin/env python3
"""Self-check for sim/recipe_comparison.py: recipe injection, the build gate per recipe, the
purchaser sampler, and one short cash-path run per recipe. Runs in ~20s (quick, 30 operating days).

Asserts the load-bearing facts the comparison turns on:
  - all three recipes LIST under the current keep-incentive backing, but only 0.06 and the legacy
    0.03 bulk-split can REBUILD after a keep; 0.03 direct cannot (one keep can't repay 3 fresh mints).
  - creator fee per pack: 0.06 -> 0.002, 0.03 bulk-split -> 0.0003, 0.03 direct -> 0.003 ETH.
  - the sampler returns the intended keep/bid choice.
  - a short run: 0.06 builds and lists; 0.03 direct never lists (so it earns nothing).
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "keeper"))
import numpy as np
import forward as F
import formal as FM
import policy
import recipe_comparison as RC


def test_backing_and_build_gate():
    b = RC.backing_table(gps_gwei=2, price_gwei=0.5)
    # All three list under the current keep rule.
    assert b["r1_06"]["lists"] and b["r2_03b"]["lists"] and b["r3_03d"]["lists"], b
    # 0.06 and legacy 0.03 rebuild; 0.03 direct cannot (3 fresh mints sink the keep outcome).
    assert b["r1_06"]["can_rebuild"], b["r1_06"]
    assert b["r2_03b"]["can_rebuild"], b["r2_03b"]
    assert not b["r3_03d"]["can_rebuild"], b["r3_03d"]
    # Backing ratio B/P ~ 1.08 for 0.06, ~1.07 for 0.03 (keeps a pack above the best bid).
    assert 1.05 < b["r1_06"]["ratio"] < 1.12, b["r1_06"]["ratio"]
    # Creator fee per pack.
    assert abs(b["r1_06"]["creator_fee_per_pack_eth"] - 0.002) < 1e-9
    assert abs(b["r2_03b"]["creator_fee_per_pack_eth"] - 0.0003) < 1e-9
    assert abs(b["r3_03d"]["creator_fee_per_pack_eth"] - 0.003) < 1e-9


def test_set_recipe_isolation():
    RC.set_recipe(dict(RC.RECIPES["r2_03b"]))
    assert F.BUILD_UNITS == 3 and F.P == 3 * 10**16 and F.MINT_FEE == 10**14
    assert policy.Q["build_shape"] == 0 and policy.Q["build_pack"] == 545_000
    RC.set_recipe(dict(RC.RECIPES["r1_06"]))
    assert F.BUILD_UNITS == 6 and policy.Q["build_shape"] == 130_000
    assert policy.Q_PURCHASER_REDEEM == RC.REDEEM_2


def test_sampler_behaviour():
    w = dict(responses=[(100, True), (200, False), (None, None)], start=0, events=[])
    rng = np.random.default_rng(0)
    bid = RC.make_scenario(w, "allbid", 0.0, None, None)["response_sampler"]
    val = RC.make_scenario(w, "value", 1.0, None, None)["response_sampler"]
    for _ in range(20):
        d, k = bid(rng)
        if d is not None:
            assert k is False
        d, k = val(rng)
        if d is not None:
            assert k is True


def test_short_runs():
    db = F.ROOT / "data/fwa.sqlite"
    w = FM.window(db, FM.PIN["timestamp"])
    import efficient_operating as C
    w["user_gas"] = C.receipt_gas()
    RC._init(w)
    out = {}
    for rk in RC.RECIPES:
        task = (rk, None, "1.96ETH", RC.CANARY, 0.5, "value", 1.0, "base", 1, 30, 30)
        out[rk] = RC._one(task)
    # 0.06 builds and lists within 30 days.
    assert out["r1_06"]["build_calls"] > 0 and out["r1_06"]["pos_max"] > 0, out["r1_06"]
    # 0.03 direct fails the build gate: it never lists, so it earns nothing.
    assert out["r3_03d"]["build_calls"] == 0 and out["r3_03d"]["own_selections"] == 0, out["r3_03d"]
    # legacy 0.03 bulk-split does list.
    assert out["r2_03b"]["build_calls"] > 0, out["r2_03b"]
    # ledger closes for every recipe (asserted inside _one; reaching here means it held).
    return out


if __name__ == "__main__":
    test_backing_and_build_gate()
    test_set_recipe_isolation()
    test_sampler_behaviour()
    o = test_short_runs()
    for rk, r in o.items():
        print(f"{rk}: builds={r['build_calls']} sel={r['own_selections']} "
              f"net_bps={r['net_bps']} mint_eth={r['creator_mint_fees_wei']/1e18:.4f}")
    print("PASS: recipe comparison self-check")
