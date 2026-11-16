"""Keeper decisions for PackVault, as a pure function of observed state. keeper/keeper.py feeds it
live chain reads; sim/forward.py feeds it simulated state, so the year-long simulation runs the
same rules the live keeper does.

A call is planned only when the vault pays for it (necessary work, or value well above its cost)
or when holders need it (redemption liquidity, wind-down). Everything is recomputed each pass, so
an interrupted keeper resumes from chain state alone.
"""
from dataclasses import dataclass, field

BPS = 10_000
UNIT = 10**16
ACTIVE, ALLOCATED, WITHDRAWN, SETTLED, STAGED = 1, 2, 3, 4, 5

# Measured on the fork (test/fork/ForkReconcile.t.sol, ForkVaultAdversarial.t.sol), plus the
# vault's 30k reimbursement overhead per call.
GAS = dict(sync_base=60_000, sync_per=100_000, harvest_base=90_000, harvest_per=15_000,
           list_per=570_000, restock_per_pack=921_000, unlist_per=201_000, liquidate_per=160_000,
           checkpoint_base=220_000, checkpoint_per=32_100, harvest_tokens=250_000, convert=350_000,
           overhead=30_000)
CYCLE_GAS = 800_000
RESTOCK_GAS_PER_PACK = 1_050_000
MAX_BATCH = dict(sync=20, harvest=60, list=10, restock=10, unlist=20, liquidate=40)


@dataclass
class Listing:
    id: int
    status: int
    allocated_at: int = 0
    pending_fees: int = 0
    pack_owed: bool = False  # FWA holds this vault's pack as a pull claim
    crown_locked: bool = False  # holds FWA's crown inside its early-exit window


@dataclass
class State:
    now: int
    gas_price: int  # what the keeper will bid
    base_fee: int
    gas_ceiling: int
    max_tip: int
    premium_bps: int
    share_bps: int
    k: int  # 1e18 scale, live
    backing: int  # live gated backing for a 3-unit pack, 0 when the gate fails
    min_edge_bps: int
    mint_fee: int
    settlement_window: int
    blackout: bool
    queue_drained: bool
    checkpoint_done_this_interval: bool
    listings: list = field(default_factory=list)
    idle_packs: int = 0
    loose_shapes: int = 0
    free: int = 0  # balance less escrow and holder reserves
    idle_eth: int = 0  # vault's idleEth(): free less reserve and owed estimate
    owed_estimate: int = 0
    pending_deposits: int = 0
    locked_shares: int = 0
    fee_credit: int = 0
    open_positions: int = 0
    max_positions: int = 300
    winding_down: bool = False
    listing_paused: bool = False
    distribution_bps: int = 0
    # FWA tokens. Amounts in token wei: pending on active listings, credit from removed or
    # repriced listings, already held. `token_sale_amount` is what one convert would sell
    # (min of the total and clipMax); `token_sale_eth` and `token_sale_gas` come from simulating
    # that exact convert call against the live pool (0 when it would revert), never from the
    # reference price, which is only the sale's protection floor. `token_wait` says why not.
    token_pending: int = 0
    token_credit: int = 0
    token_held: int = 0
    token_sale_amount: int = 0
    token_sale_min_out: int = 0
    token_sale_eth: int = 0
    token_sale_gas: int = 0
    token_wait: str = ""
    subsidize_tokens: bool = False  # operator pays convert gas the vault will not reimburse
    notes: list = field(default_factory=list)
    # Deployment slowdown: trailing acquisitions per day as the keeper measured them, and the
    # floor below which it stops building new packs (relisting existing ones continues).
    recent_volume: float = 0.0
    slowdown_volume: float = 0.0


def price(s):
    return min(s.gas_price, s.base_fee + s.max_tip, s.gas_ceiling)


def cost(s, gas):
    return (gas + GAS["overhead"]) * price(s) * (BPS + s.premium_bps) // BPS


def cycle_net(s):
    if s.k <= 10**18 or s.backing == 0:
        return 0
    gross = s.backing * (s.k - 10**18) // 10**18
    c = CYCLE_GAS * price(s) * (BPS + s.premium_bps) // BPS
    return gross - c if gross > c else 0


def plan(s):
    """Ordered list of calls for this pass. Each is a tuple: (function, args...)."""
    out = []
    if s.gas_price > s.gas_ceiling:
        return out  # pay is capped at the ceiling: wait for gas to fall

    # 1. Resolve what FWA moved on: settled, withdrawn (kicked), or allocated past the window,
    #    and retry any pack FWA still owes.
    due = [l.id for l in s.listings
           if l.status in (SETTLED, WITHDRAWN)
           or (l.status == ALLOCATED and s.now >= l.allocated_at + s.settlement_window)]
    for i in range(0, len(due), MAX_BATCH["sync"]):
        out.append(("sync", due[i:i + MAX_BATCH["sync"]]))

    active = [l for l in s.listings if l.status == ACTIVE]
    shortfall = max(0, s.owed_estimate - s.free - s.pending_deposits)
    redeeming = shortfall > 0  # deploy nothing this pass while redeemers wait for ETH
    # FWA's live fees leave no edge: every further cycle loses, so unwind (the vault allows it).
    broken = s.k < 10**18 + s.min_edge_bps * 10**14

    # 2. Fees: claim when the vault would pay for it (pay <= share of the take), or when
    #    redeemers need ETH and fees are the cheapest source.
    earning = sorted((l for l in active if l.pending_fees), key=lambda l: -l.pending_fees)[:MAX_BATCH["harvest"]]
    amount = s.fee_credit + sum(l.pending_fees for l in earning)
    hcost = cost(s, GAS["harvest_base"] + GAS["harvest_per"] * len(earning))
    if amount and (hcost * BPS <= amount * s.share_bps or shortfall):
        out.append(("harvest", [l.id for l in earning]))
        shortfall = max(0, shortfall - amount)

    # 3. Redemption liquidity or wind-down: idle inventory first, then unlist (needs FWA's
    #    queue drained), then liquidate what unlisting returned.
    if s.winding_down or shortfall:
        if s.idle_packs or s.loose_shapes:
            out.append(("liquidate", MAX_BATCH["liquidate"]))
            shortfall = max(0, shortfall - (s.idle_packs * 3 + s.loose_shapes) * UNIT)
    unwind = s.winding_down or broken
    if (unwind or shortfall) and s.queue_drained:
        need_cash = s.winding_down or shortfall > 0
        pool = sorted((l for l in active if not l.crown_locked), key=lambda l: l.pending_fees)
        ids = []
        for l in pool:
            if not unwind and shortfall <= 0:
                break
            ids.append(l.id)
            shortfall = max(0, shortfall - 3 * UNIT - s.backing)  # close to each position's own
        for i in range(0, len(ids), MAX_BATCH["unlist"]):
            out.append(("unlist", ids[i:i + MAX_BATCH["unlist"]]))
        if ids and need_cash:
            out.append(("liquidate", MAX_BATCH["liquidate"]))

    # 3b. Listings FWA staged (its queue was busy when they were listed) earn nothing until
    #     activated; activation needs the queue drained.
    staged = sorted(l.id for l in s.listings if l.status == STAGED)
    if staged and s.queue_drained:
        out.append(("activate", staged, 200))

    # 4. Checkpoint in FWA's blackout with its queue drained, only when holders have flows.
    if (s.blackout and s.queue_drained and not s.checkpoint_done_this_interval
            and (s.pending_deposits or s.locked_shares)):
        out.append(("checkpoint",))

    # 5. Tokens (zero in NAV): one convert claims and sells. The vault pays the caller only if
    #    the pay is at most share_bps of the ETH realized; otherwise the call is a donation.
    total = s.token_pending + s.token_credit + s.token_held
    if total:
        if s.token_wait:
            s.notes.append(f"tokens {total / 1e18:.4f} waiting: {s.token_wait}")
        elif s.token_sale_eth:
            pay = cost(s, s.token_sale_gas)
            spend = s.token_sale_gas * s.gas_price  # what the keeper's transaction costs it
            paid = pay * BPS <= s.token_sale_eth * s.share_bps
            if paid and pay >= spend:
                out.append(("convert", [l.id for l in active], s.token_sale_amount, s.token_sale_min_out))
            elif s.subsidize_tokens:
                out.append(("convert", [l.id for l in active], s.token_sale_amount, s.token_sale_min_out))
                s.notes.append(f"token sale subsidized: keeper spends {spend / 1e18:.8f} ETH for "
                               f"{s.token_sale_eth / 1e18:.8f} ETH to holders")
            else:
                s.notes.append(f"tokens {total / 1e18:.4f} waiting: sale would realize {s.token_sale_eth / 1e18:.8f} ETH, "
                               f"under {BPS // s.share_bps}x its {pay / 1e18:.8f} ETH gas pay, so the vault would not pay for it")

    # 6. Deploy: relist idle packs, then build new ones only when one cycle repays the build.
    if s.winding_down or broken or s.listing_paused or redeeming or not s.backing:
        return out
    net = cycle_net(s)
    if not net:
        return out
    idle = s.idle_eth
    room = s.max_positions - s.open_positions
    if s.idle_packs:
        n = min(s.idle_packs, idle // s.backing, room, MAX_BATCH["list"])
        if n:
            out.append(("list", n))
            idle -= n * s.backing
            room -= n
    elif s.recent_volume >= s.slowdown_volume:
        build = cost(s, RESTOCK_GAS_PER_PACK - GAS["overhead"]) + s.mint_fee * 3 // 10
        n = 0  # largest batch the vault's capital check accepts: whole 0.1 mints plus backing
        for c in range(min(room, MAX_BATCH["restock"]), 0, -1):
            need = 3 * c
            mints = -(-(need - s.loose_shapes) // 10) if need > s.loose_shapes else 0
            if mints * (10 * UNIT + s.mint_fee) + c * s.backing <= idle:
                n = c
                break
        if build <= net and n:
            out.append(("restock", n, 3))
            out.append(("list", n))
    return out
