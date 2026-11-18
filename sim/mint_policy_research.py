"""Explore pack sizes with the FWA economics recorded on 2026-11-16.

Research only. Deliberately not used for onchain keeper decisions until tested
against current FWA state and reconciled with the existing fork simulation.
Amounts are ETH floats, not safe for settlement/accounting.
"""
from dataclasses import dataclass

SIZES = (0.03, 0.05, 0.10, 0.20)
OUTSIDE_COUNT = 2584
OUTSIDE_HARMONIC_BACKING = 0.0514
OUTSIDE_WEIGHT = OUTSIDE_COUNT / OUTSIDE_HARMONIC_BACKING
K = 1.05 * (1 - 0.01) * (1 - 0.001)
BID_FACTOR = 0.9
SETTLEMENT_FEE = 0.01
MINT_FEE_PER_01 = 0.001
CYCLE_QUOTED_GAS = 75_000 + 530_000 + 15_000
WORK_FEE = 0.00002
BUILD_GAS_PER_01 = 2_200_000
PACK_GAS = 200_000


@dataclass(frozen=True)
class Choice:
    pack_value: float
    backing: float
    count: int
    selection_share: float
    initial_mint_fees: float


def mint_fees(value):
    """Amortized primary mint fee: one 0.1 ETH mint per 0.1 ETH backing."""
    return value / 0.1 * MINT_FEE_PER_01


def cycle_cost(gas_gwei):
    return CYCLE_QUOTED_GAS * gas_gwei * 1e-9 + 2 * WORK_FEE


def replacement_cost(value, gas_gwei):
    """Conservatively charge full replacement construction for each keep."""
    return mint_fees(value) + (
        PACK_GAS + BUILD_GAS_PER_01 * value / 0.1
    ) * gas_gwei * 1e-9 + WORK_FEE


def outcome_margins(value, backing, gas_gwei=0.5):
    """Expected incremental margin on one selection, ignoring future volume."""
    bid = backing * (K - 1) - cycle_cost(gas_gwei)
    keep = (backing * (K - SETTLEMENT_FEE) - value
            - cycle_cost(gas_gwei) - replacement_cost(value, gas_gwei))
    return bid, keep


def candidate(capital, pack_value, *, cash_bid_ratio=1.0, max_share=0.25):
    """Selection-weight admission for the *entire* intended allocation.

    This approximates capital and mints, excluding first-mint rounding and
    initial one-time costs. 25% is a provisional research threshold.
    """
    backing = pack_value * cash_bid_ratio / BID_FACTOR
    if backing < 0.025:
        return None
    price = pack_value + backing + mint_fees(pack_value)
    n = int(capital // price)
    if n == 0:
        return None
    weight = n / backing
    share = weight / (OUTSIDE_WEIGHT + weight)
    if share > max_share:
        return None
    return Choice(pack_value, backing, n, share, n * mint_fees(pack_value))


def choose(capital, *, cash_bid_ratio=1.0, max_share=0.25, sizes=SIZES):
    """Choose smallest admissible size. A mismatch returns None, not a bypass."""
    for size in sizes:
        c = candidate(capital, size, cash_bid_ratio=cash_bid_ratio,
                      max_share=max_share)
        if c is not None:
            return c
    return None


def expected_year(choice, *, acquisitions_per_day=97, keep_rate=0.0,
                  gas_gwei=0.5):
    """Sensitivity, not a prediction of purchaser keeps.

    Every FWA acquisition distributes fees equally among listings; selection
    uses inverse backing weights. Returning packs trigger zero new mint fees.
    """
    assert 0 <= keep_rate <= 1
    weight = OUTSIDE_WEIGHT + choice.count / choice.backing
    selection_count = 365 * acquisitions_per_day * choice.selection_share
    fee_income = 365 * acquisitions_per_day * K * choice.count / weight
    bid, keep = outcome_margins(choice.pack_value, choice.backing, gas_gwei)
    # fee_income contains K*backing per expected selection. The following
    # outcome margins already include that share; subtract that duplicate.
    margin = ((1 - keep_rate) * bid + keep_rate * keep)
    pnl = selection_count * margin
    capital = choice.count * (
        choice.pack_value + choice.backing + mint_fees(choice.pack_value))
    return {
        "net_annual_eth": pnl,
        "apr": pnl / capital,
        "selections": selection_count,
        "primary_mints_initial_eth": choice.initial_mint_fees,
        "primary_mints_replacement_eth": (
            selection_count * keep_rate * mint_fees(choice.pack_value)
        ),
        "cross_check_fee_income_eth": fee_income,
    }


if __name__ == "__main__":
    for capital in (0.66, 2, 6.6, 20, 66):
        c = choose(capital)
        if c is None:
            print(f"{capital}: WAIT")
        else:
            e = expected_year(c)
            print(f"{capital}: {c.pack_value:.2f} ETH x {c.count}, "
                  f"draw share {c.selection_share:.1%}, "
                  f"APR {e['apr']:.1%}, initial mint fees {c.initial_mint_fees:.5f}")
