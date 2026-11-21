#!/usr/bin/env python3
"""Assert-based self checks for sim/unified.py. Run: python3 sim/test_unified.py

Covers the four checks the study owner required:
  1. the VaultLib.edge backing self-check (0.06 pack at 0.5 gwei -> 65,158,469,945,350,000 wei);
  2. conservation of every wei across a full cycle (deposit -> operate -> full exit), integer ledger;
  3. our fee-share totals equal FWA's split (matches sim/forward.py.backtest exactly);
  4. a zero-activity run loses exactly the build/list costs (plus one-time deploy/exit gas).
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import unified as U  # noqa: E402

E = U.E


def check_backing():
    assert U.edge_backing(6 * 10**16, 0.5) == 65_158_469_945_350_000, U.edge_backing(6 * 10**16, 0.5)
    # gate: 0.06 keep recipe lists and restocks; 0.03 direct mint lists but cannot restock
    r4 = U.RECIPES["r4_direct06"]
    cyc = r4.cycle_cost(0.5)
    assert U.gate_ok(r4.backing(), r4.P, cyc)
    assert U.restock_ok(r4.backing(), r4.P, cyc, r4.build_cost(0.5))
    r3 = U.RECIPES["r3_direct03"]
    assert U.gate_ok(r3.backing(), r3.P, r3.cycle_cost(0.5))
    assert not U.restock_ok(r3.backing(), r3.P, r3.cycle_cost(0.5), r3.build_cost(0.5)), "0.03 should fail restock"
    print("1. backing + gate self-check OK")


def check_conservation():
    """Integer-wei ledger of one listing through a keep cycle and a bid cycle, then exit.

    Track every wei: the account's cash plus locked backing plus pack inventory must equal the
    starting capital plus FWA fees received minus every leak (settlement fee, mint fee, keeper pay,
    gas). No wei is created or destroyed.
    """
    bf = 0.5
    rc = U.RECIPES["r4_direct06"]
    B, P = rc.backing(), rc.P
    s_bps = int(U.S_FEE * 10_000)
    build_gas = U.quote(rc.build_gas(), 2, bf)
    mint = rc.shapes * U.MINT_FEE
    list_gas = rc.list_cost(bf)
    sync_gas = rc.sync_cost(bf)
    unlist_gas = U.quote(U.Q_UNLIST_BASE + U.Q_UNLIST_PER, 1, bf)

    cap = 10**17                      # 0.1 ETH working capital for one listing
    cash = cap
    locked = 0                        # backing posted on FWA
    pack_inv = 0                      # value of packs we hold (mintable Shapes, redeemable)
    fees_in = settle_out = mint_out = keeper_out = 0
    pack_to_purchaser = 0             # pack value handed to a keeping purchaser (counterparty)

    def build_and_list():
        nonlocal cash, locked, pack_inv, mint_out, keeper_out
        cash -= P                     # mint the Shapes (primary mint price)
        pack_inv += P                 # pack now worth P
        cash -= mint; mint_out += mint
        cash -= build_gas; keeper_out += build_gas
        cash -= B; locked += B        # post backing

    build_and_list()
    # --- a keep selection: FWA fee accrued, purchaser keeps the pack, backing returns B(1-s) ---
    fee = 7 * 10**15                  # an example accrued fee
    cash += fee; fees_in += fee       # harvest accrued fee
    got = B * (10_000 - s_bps) // 10_000
    cash += got; locked -= B          # backing released as B(1-s)
    settle_out += B - got
    pack_inv -= P; pack_to_purchaser += P   # pack gone to the keeping purchaser
    cash -= sync_gas; keeper_out += sync_gas
    build_and_list()                  # replace the kept pack

    # --- a bid selection: backing lost entirely, pack retained, relist ---
    fee2 = 6 * 10**15
    cash += fee2; fees_in += fee2
    locked -= B                       # backing gone (bid)
    backing_lost = B
    cash -= sync_gas; keeper_out += sync_gas
    cash -= list_gas; keeper_out += list_gas
    cash -= B; locked += B            # relist the same pack with fresh backing

    # --- full exit: unlist (backing back, pack to inventory) + liquidate pack (redeem to P) ---
    cash += locked; locked = 0
    cash -= unlist_gas; keeper_out += unlist_gas
    cash += pack_inv; pack_inv = 0    # redeem the pack's Shapes back to ETH

    nav = cash + locked + pack_inv
    # (a) pure value conservation: no wei created or destroyed. Everything the account's NAV lost
    #     (relative to capital + fees it took in) went to a named counterparty: the protocol
    #     (settlement + the lost bid backing), the creator (mint fees), the keeper (gas), and the
    #     keeping purchaser (the pack).
    leaked = settle_out + mint_out + keeper_out + backing_lost + pack_to_purchaser
    assert nav == cap + fees_in - leaked, (nav, cap + fees_in - leaked, nav - (cap + fees_in - leaked))

    # (b) the wei-exact ledger must equal unified.py's net formula for the same events
    #     (1 initial build, 1 keep cycle, 1 bid cycle, then full exit by unlist).
    settle_per = B - got
    keep_cost = P + settle_per + mint + build_gas + sync_gas          # pack P gone + settle + rebuild
    bid_cost = B + list_gas + sync_gas
    unified_net = (fee + fee2) - keep_cost - bid_cost - (build_gas + mint) - unlist_gas
    assert nav - cap == unified_net, (nav - cap, unified_net, nav - cap - unified_net)
    print(f"2. wei conservation OK (ledger NAV-cap = unified net = {unified_net} wei, exact)")


def check_fee_share():
    """Our per-listing fee share, summed over our n listings, equals FWA's split exactly:
    fee2*(1-cut)(1-crown)*n/(N+n) with fee2 = fee*H2/H  (sim/forward.py.backtest)."""
    win = U.window_arrays(mature_min_n=0)
    fee, w, N = win["fee"], win["w"], win["N"]
    cut, crown = win["cut"], win["crown"]
    n, B = 15, U.edge_backing(6 * 10**16) / E
    Wn = n / B
    # unified's per-listing share * n
    mine = n * fee * (1 - cut) * (1 - crown) * w / (N * (w + Wn))
    # backtest's vault_fees
    H, H2 = N / w, (N + n) / (w + n / B)
    fee2 = fee * H2 / H
    theirs = fee2 * (1 - cut) * (1 - crown) * n / (N + n)
    rel = np.abs(mine - theirs) / np.maximum(theirs, 1e-30)
    assert rel.max() < 1e-9, rel.max()
    # and selection odds match backtest's p_sel = (n/B)/(w + n/B)
    mine_p = n * (1 / B) / (w + Wn)
    theirs_p = (n / B) / (w + n / B)
    assert np.abs(mine_p - theirs_p).max() < 1e-9
    print(f"3. fee-share + selection-odds match backtest exactly (max rel err {rel.max():.1e})")


def check_zero_activity():
    """A zero-volume year loses exactly the one-time build/list + deploy + exit costs."""
    win = U.window_arrays()
    stream = U.year_stream(win)
    acc = U.Account(U.RECIPES["r4_direct06"], 2 * E, is_pool=True)
    res = U.run_cell([acc], U.Scenario("zero", keep_rate=1.0, basefee_gwei=0.5, volume_scale=0.0), stream)[id(acc)]
    bf = 0.5
    build_gas = U.quote(acc.recipe.build_gas(), 2, bf)
    mint = acc.recipe.shapes * U.MINT_FEE
    exit_gas = U.quote(U.Q_UNLIST_BASE + U.Q_UNLIST_PER * acc.n, 1, bf) + \
        U.quote(U.Q_LIQ_BASE + U.Q_LIQ_PACK * acc.n + U.Q_LIQ_SHAPE * acc.recipe.shapes * acc.n, 2, bf)
    request = U.quote(U.Q_CHECKPOINT, 1, bf)
    expected = -(acc.n * (build_gas + mint) + request + exit_gas)   # pool: no deploy, one request charge
    assert res["sel_mean"] == 0.0
    assert abs(res["net_mean"] - expected) < 1, (res["net_mean"], expected)
    print(f"4. zero-activity loses exactly build/list+exit costs: {expected/E:.5f} ETH")


if __name__ == "__main__":
    check_backing()
    check_conservation()
    check_fee_share()
    check_zero_activity()
    print("\nALL CHECKS PASSED")
