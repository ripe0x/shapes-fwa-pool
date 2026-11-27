"""Keeper decisions for PackVault, as a pure function of observed state. keeper/keeper.py feeds it
live chain reads; sim/forward.py feeds it simulated state, so the year-long simulation runs the
same rules the live keeper does.

A call is planned only when the vault pays for it (necessary work, or value well above its cost)
or when holders need it (redemption liquidity, wind-down). Everything is recomputed each pass, so
an interrupted keeper resumes from chain state alone.

Gas classes (D45). Bounded measured compensation can underpay a planned candidate; the executor checks the
actual offer and signed-call estimate before accepting it. Above the ceiling only
liability work is planned: redemption liquidity, the checkpoint that prices a redemption, and
wind-down. Everything else (new packs, relists, fee harvests, deposit pricing, token
burns) waits for gas to fall. Whether a keeper accepts the loss on liability work above the
ceiling is the executor's choice (keeper.py --max-loss-wei), not the vault's.
"""
import functools
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from config import GAS_DEFAULTS, GAS_KEYS

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

BPS = 10_000
UNIT = 10**16
ACTIVE, ALLOCATED, WITHDRAWN, SETTLED = 1, 2, 3, 4
# Monitoring only (never changes a plan): warn when this keeper's own Active listings, across every
# account it runs, reach this share of FWA's total selection weight. FWA selects a listing with
# probability (its weight)/(total weight), each listing's weight being 1e36/backing.
EXPOSURE_SHARE_HIGH_BPS = 1_000  # 10%

# Default calibration only. Every observed account carries its own schedule.
Q = {GAS_KEYS[k]: v for k, v in GAS_DEFAULTS.items()}
REF_UNITS = 3
MIN_PACK_UNITS, MAX_PACK_UNITS = 3, 30
MAX_SCAN = 96  # hard work bound, independent of mutable quote coefficients
MAX_BATCH = dict(sync=16, journal=128, selected=16, prune=16, harvest=16, list=8, build=4, unlist=16, liquidate=16, tokens=16)


def shape_count(units):
    """VaultLib.makeup: fewest Shapes for a pack of `units` x 0.01 ETH from the 0.1, 0.05 and 0.01
    denominations. Six units are one 0.05 and one 0.01 Shape (two paid primary mints)."""
    return units // 10 + units % 10 // 5 + units % 5


@dataclass
class Listing:
    id: int
    status: int
    allocated_at: int = 0
    pending_fees: int = 0
    pack_owed: bool = False  # FWA holds this vault's pack as a pull claim
    crown_locked: bool = False  # holds FWA's crown inside its early-exit window
    value: int = 3 * UNIT
    backing: int = 0
    unapplied: bool = False  # the vault's book still holds it Active although FWA allocated it


@dataclass
class State:
    now: int
    gas_price: int  # what the keeper will bid
    base_fee: int
    gas_ceiling: int
    max_tip: int
    markup_bps: int
    share_bps: int
    k: int  # 1e18 scale, live
    backing: int  # live gated backing for a build_units pack, 0 when the gate fails
    min_edge_bps: int
    mint_fee: int
    settlement_window: int
    blackout: bool
    queue_drained: bool
    checkpoint_done_this_interval: bool
    listings: list = field(default_factory=list)
    relistable_idle: int = None
    idle_packs: int = 0
    recovery_packs: int = 0
    free: int = 0  # balance less escrow and holder reserves
    idle_eth: int = 0  # vault's idleEth(): free less reserve and owed estimate
    owed_estimate: int = 0
    pending_deposits: int = 0
    locked_shares: int = 0
    total_shares: int = 0  # includes the permanent 1e15 dead shares; distinguishes a full holder exit
    fee_credit: int = 0
    open_positions: int = 0  # aggregate count, never len(the bounded hydrated candidate set)
    active_count: int = 0
    idle_value: int = 0  # maintained immediately usable inventory backing, including loose Shapes
    idle_funding: int = 0  # prior idle packs' maintained future backing commitments
    journal_cursor: int = 0
    completed_prefix: int = 0
    pending_receipts: int = 0
    allocation_stale: bool = False
    own_journal_pending: bool = False
    witness_id: int = 0
    pending_parent: str = ""
    backing_proposals: list = field(default_factory=list)
    build_proposals: list = field(default_factory=list)
    winding_down: bool = False  # pool wind-down or a personal manager's exit mode
    listing_paused: bool = False
    distribution_bps: int = 0
    # FWA tokens in token wei: pending on active listings, credit from removed or repriced
    # listings, already held. The vault burns them (D43); burning is unpaid, so the keeper does
    # it only when its operator opts in.
    token_pending: int = 0
    token_credit: int = 0
    token_held: int = 0
    token_ids: list = field(default_factory=list)  # active listings with pending tokens
    burn_tokens: bool = False  # operator pays burnTokens gas; the vault reimburses nothing
    notes: list = field(default_factory=list)
    # Deployment slowdown: trailing acquisitions per day as the keeper measured them, and the
    # floor below which it stops building new packs (relisting existing ones continues).
    recent_volume: float = 0.0
    slowdown_volume: float = 0.0
    reserve: int = 0  # the vault's `reserve` parameter
    work_fee: int = 0  # flat wei per unit of work (D55)
    routine_budget: int = 10**30  # keeper budgets available now (PackVault.budget())
    essential_budget: int = 10**30
    distribution_due: bool = False  # a no-flow checkpoint would distribute now (simulated)
    pack_units_mask: int = 1 << REF_UNITS  # account packUnitsMask: the pack sizes it admits
    build_units: int = REF_UNITS  # pack size the keeper builds; must be enabled in pack_units_mask
    build_room: int = None  # packs of build_units the account design still allows; None = no count
    essential_ceiling: int = None  # redemption and wind-down work; None = same as gas_ceiling
    book_pack_count: int = 0
    book_shape_count: int = 0
    book_capital: int = 0
    book_max_units: int = 0
    book_recovery_count: int = 0
    book_recovery_value: int = 0
    checkpoint_proof_entries: int = 0
    processing_pool: int = 0  # request charges already held for the next checkpoint (pool only)
    essential_cap: int = None  # essentialCap; 0 = exit work unpaid (withdrawers run it)
    pooled: bool = True  # a PackVault (shares, checkpoints); False for a personal PackManager
    settlement_fee_bps: int = 100
    gas_schedule: dict = field(default_factory=lambda: Q.copy())
    backing_ratio_bps: int = 70_000
    keeper_cash: int = None
    operating_reserve: int = 0
    accepted_mint_fee: int = 5*10**14
    configuration_hash: str = ""
    caller_funded_exit: bool = False
    request_funding_needed: int = 0



def price(s, essential=False):
    """The price the vault quotes at: basefee + maxTip, capped at the routine or the essential
    ceiling (never the bid)."""
    ceiling = s.essential_ceiling if essential and s.essential_ceiling is not None else s.gas_ceiling
    return min(s.base_fee + s.max_tip, ceiling)


def quote(s, gas, units=0, essential=False):
    """Conservative payment envelope; work allowances cap measured gas."""
    if gas == 0 and units == 0:
        return 0
    q = (gas + s.gas_schedule['overhead']) * price(s, essential)
    if not essential:
        q = q * (BPS + s.markup_bps) // BPS
    return q + units * s.work_fee


def payment(s, gas, units=0, essential=False, *, measured_gas, tx_gas_price=None):
    """Measured compensation, before cash/permission limits; never infer a bill from a cap."""
    if gas == 0 and units == 0:
        return 0
    if measured_gas < 0:
        raise ValueError('measured gas must be nonnegative')
    paid_price = min(s.gas_price if tx_gas_price is None else tx_gas_price, price(s, essential))
    amount = (min(measured_gas, gas) + s.gas_schedule['overhead']) * paid_price
    if not essential:
        amount = amount * (BPS + s.markup_bps) // BPS
    return amount + units * s.work_fee


def cycle_gas(s, retirement_shapes=None):
    q = s.gas_schedule
    return sum(q[k] for k in ('sync', 'journal', 'selected', 'synced', 'pruned', 'sync_funding', 'harvested', 'sync_credit', 'list', 'listed'))


def position_value(s, units=None):
    units = s.build_units if units is None else units
    # Zero-mask fallback is only a quote denominator; authorization remains the actual mask.
    value = (units or REF_UNITS) * UNIT
    return value + value * s.backing_ratio_bps // BPS


def edge_backing(k, cap, s_bps, units, gas_ceiling, markup_bps, work_fee, buffer_bps=0, min_edge_bps=100,
                 discount_bps=9_150, price=None, mint_fee=5*10**14, backing_ratio_bps=11_053,
                 gas_schedule=None, newly_built=True, reference_units=None, retirement_shapes=None):
    """Adjustable ratio backing, with actual FWA admission and no buyer-choice preference.
    Gas and build arguments are accepted for callers but no longer priced (VaultLib._profitable)."""
    value = units * UNIT
    floor = -(-value * BPS // 9500)  # Conservative NAV coverage at the protocol maximum 5% keep settlement fee.
    desired = value * backing_ratio_bps // BPS // BPS * BPS
    if cap is not None:
        desired = min(desired, cap * (BPS - buffer_bps) // BPS // BPS * BPS)
    ok = (cap != 0 and k >= 10**18 + min_edge_bps * 10**14 and desired >= floor
          and desired * (k - s_bps * 10**14) // 10**18 >= value)  # VaultLib._profitable: no gas or build cost
    return desired if ok else 0


def propose_backings(target, reserved_count, count, is_reserved, minimum=0, maximum=2**256 - 1, nonce=0):
    """Bounded local probes for unique quantized receipt identifiers, never an onchain search.

    Nearby quotes come first. A deterministic scatter avoids repeatedly probing a crowded center;
    the next pinned block changes nonce. Missing a free interval waits safely for another pass.
    is_reserved queries the local index; signed-call preflight authenticates current chain state.
    """
    if target <= 0:
        return []
    quantum = 10_000
    base = target // quantum * quantum
    proposals, used = [], set()
    for i in range(count):
        width = reserved_count + i + 1
        for offset in _probe_offsets(nonce, target, i, width):
            proposed = base + offset * quantum
            if (proposed <= 0 or proposed < minimum or proposed > maximum
                    or abs(proposed - target) > width * quantum or proposed in used or is_reserved(proposed)):
                continue
            proposals.append(proposed)
            used.add(proposed)
            break
        else:
            break
    return proposals


@functools.lru_cache(maxsize=65_536)
def _probe_offsets(nonce, target, i, width):
    # Test the actual band edges too: a dense run around the target must not require luck.
    offsets = [0] + [sign * j for j in range(1, 9) for sign in (1, -1)]
    offsets += [width, -width, max(width - 1, 0), -max(width - 1, 0)]
    for attempt in range(43):
        word = int.from_bytes(hashlib.sha256(f"{nonce}:{target}:{i}:{attempt}".encode()).digest(), "big")
        offsets.append(word % (2 * width + 1) - width)
    return tuple(offsets)


def cycle_net(s):
    """PackVault._cycleNet: a bid cycle's edge after the keeper pay it causes."""
    if s.k <= 10**18 or s.backing == 0:
        return 0
    gross = s.backing * (s.k - 10**18) // 10**18
    q = s.gas_schedule
    sync_gas = cycle_gas(s) - q['list'] - q['listed']
    c = quote(s, sync_gas, 1) + quote(s, q['list'] + q['listed'], 1)
    return gross - c if gross > c else 0


def build_net(s):
    """Worst one-cycle purchaser outcome per pack: bid margin, or keep payout less Shapes principal.
    Gas and mint fees are excluded by owner decision; the build gate charges neither."""
    if s.k <= 10**18 or not s.backing:
        return 0
    bid=s.backing*(s.k-10**18)//10**18
    keep=s.backing*(s.k-s.settlement_fee_bps*10**14)//10**18-s.build_units*UNIT
    return max(0,min(bid,keep)) if keep >= 0 else 0


def build_cost(s, units=None):
    """VaultLib.buildCost: building one pack of `units` and listing it at the envelope now, plus its
    paid primary mint fees (one per Shape)."""
    q = s.gas_schedule
    units = s.build_units if units is None else units
    n = shape_count(units)
    return quote(s, q["build"] + q["build_pack"] + n * q["build_shape"] + q["listed"], 2) + n * s.mint_fee


def checkpoint_cost(s):
    """VaultLib.requestCharge: one checkpoint at cost plus one work unit."""
    q = s.gas_schedule
    return quote(s, q["checkpoint"] + s.checkpoint_proof_entries * (q["allocation_entry"] + q["allocation_read"]), 1, True)


def request_charge(s):
    """PackVault.requestCharge: what tops the processing pool up to its current bounded checkpoint quote, in wei."""
    top = max(0, checkpoint_cost(s) - s.processing_pool)
    return top


def deploy_charge(s):
    """Conservative allowed-recipe build cost per current reference capital."""
    q = s.gas_schedule
    if not s.pack_units_mask:
        return 0
    reference = position_value(s)
    return max((-(-build_cost(s, u) * reference // position_value(s, u))
                for u in range(MIN_PACK_UNITS, MAX_PACK_UNITS + 1) if (s.pack_units_mask >> u) & 1), default=0)


def unwind_charge(s):
    """Actual maintained book exposure, or bounded allowed-recipe comparison before first build."""
    if s.essential_cap == 0:
        return 0
    q, reference = s.gas_schedule, position_value(s)
    if (s.book_pack_count or s.book_recovery_count) and s.book_capital:
        count = s.book_pack_count
        gas = s.active_count*q['unlisted'] + count*q['liq_pack'] + s.book_shape_count*q['redeem_shape']
        per_call=min(MAX_BATCH['liquidate'],60//(s.book_max_units or MAX_PACK_UNITS)) if count else MAX_BATCH['liquidate']
        calls = -(-s.active_count//MAX_BATCH['unlist']) + -(-count//per_call)
        gas += -(-s.active_count//MAX_BATCH['unlist'])*q['unlist'] + -(-count//per_call)*q['liquidate']
        units=s.active_count+count
        if s.book_recovery_count:
            shapes=s.book_recovery_value//UNIT
            chunks=-(-shapes//30)+s.book_recovery_count-1
            gas+=shapes*q['recovery_shape']+s.book_recovery_count*q['recovery_unseal']+chunks*(q['liquidate']+q['recovery_base'])
            units+=chunks
            calls+=chunks
        if calls == 0:
            return 0
        return -(-quote(s, gas + (calls-1)*q['overhead'], units, True)*reference//s.book_capital)
    costs = []
    for u in range(MIN_PACK_UNITS, MAX_PACK_UNITS+1):
        if s.pack_units_mask >> u & 1:
            gas = q['unlist']+q['unlisted']+q['liquidate']+q['liq_pack']+shape_count(u)*q['redeem_shape']
            costs.append(-(-quote(s, gas + q['overhead'], 2, True)*reference//position_value(s,u)))
    return max(costs, default=0)


def sync_funding_candidates(s, terminal_ids, active, checkpoint_due):
    """Optional bounded candidates; exact eligibility belongs to ordinary contract preflight.

    A fully funded worst-case job needs no active IDs. Otherwise the planner offers prefixes
    in increasing length, so the executor can find the smallest useful call without guessing
    the number of own journal transitions, terminal inflows or pruned heads.
    """
    q = s.gas_schedule
    records = min(MAX_BATCH["journal"], s.completed_prefix - s.journal_cursor)
    base = q["journal_tail"] + q["distribution_proof"] if checkpoint_due else q["sync"]
    upper = quote(s, base + records * q["journal"] + MAX_BATCH["selected"] * q["selected"]
                  + len(terminal_ids) * q["synced"] + MAX_BATCH["prune"] * q["pruned"], len(terminal_ids))
    if (s.free if s.keeper_cash is None else s.keeper_cash) >= upper or s.routine_budget < quote(s, q["sync"]):
        return []
    candidates = sorted((l for l in active if l.pending_fees and l.id not in terminal_ids),
                        key=lambda l: (-l.pending_fees, l.id))
    return list(dict.fromkeys(l.id for l in candidates))[:MAX_BATCH["sync"]]


def scan_proof(s):
    """ScanLib.rebase's choice: the vault reads its open positions instead of FWA's journal when
    that costs no more than the next journal batch."""
    q = s.gas_schedule
    backlog = s.completed_prefix - s.journal_cursor
    return backlog > 0 and s.open_positions <= MAX_SCAN and s.open_positions * q["scan"] <= min(backlog, MAX_BATCH["journal"]) * q["journal"]


def scan_vault(s):
    """Small enough that any full journal batch is replaced by one scan (at most 93 open)."""
    q = s.gas_schedule
    return s.open_positions <= MAX_SCAN and s.open_positions * q["scan"] <= MAX_BATCH["journal"] * q["journal"]


def plan(s):
    """Ordered list of calls for this pass. Each is a tuple: (function, args...)."""
    q = s.gas_schedule
    out = []
    spike = s.gas_price > s.gas_ceiling
    if spike and not (s.winding_down or s.locked_shares or s.caller_funded_exit):
        return out  # nothing owed to anyone waits on this pass: wait for gas to fall

    # 1. Resolve what FWA moved on: settled, withdrawn (kicked), or allocated past the window,
    #    and retry any pack FWA still owes.
    due = list(dict.fromkeys(l.id for l in s.listings
               if l.status in (SETTLED, WITHDRAWN)
               or (l.status == ALLOCATED and s.now >= l.allocated_at + s.settlement_window)))
    active = [l for l in s.listings if l.status == ACTIVE]
    shortfall = max(0, s.owed_estimate - s.free)
    catchup = s.journal_cursor < s.completed_prefix
    unexposed = not s.open_positions and not s.active_count and not s.pending_receipts and not s.listings
    checkpoint_due = (s.blackout and s.queue_drained and (not s.checkpoint_done_this_interval or (s.caller_funded_exit and s.locked_shares))
                      and (s.pending_deposits or s.locked_shares or s.distribution_bps))
    scanning = scan_vault(s) and not unexposed
    selected_due = [i for i in due if any(l.id == i and l.unapplied for l in s.listings)]
    defer = False
    if scanning:
        # A scan pays only when it applies an own selection or proves a checkpoint. Wait until
        # each selection settles or expires, so one paid call selects and resolves it; other
        # terminal and cleanup work rides along unless holders need it now.
        journal_due = catchup and checkpoint_due
        defer = (scan_proof(s) and not selected_due and not checkpoint_due and not s.locked_shares
                 and not shortfall and not s.winding_down)
    else:
        journal_due = catchup and not unexposed and (
            s.completed_prefix - s.journal_cursor >= MAX_BATCH["journal"]
            or s.own_journal_pending or checkpoint_due or s.caller_funded_exit)
    # All sync work uses routine funding, including while holders are withdrawing.
    if (due or journal_due or s.allocation_stale) and (not spike or s.caller_funded_exit) and not defer:
        ids = due[:MAX_BATCH["sync"]]
        if scanning and checkpoint_due and scan_proof(s) and not selected_due:
            ids = []  # the paid checkpoint scan first; terminals follow without a scan
        # Ordinary preflight tries the no-claim job first, then the shortest funded prefix.
        # The executor replans after one successful call; these are alternatives, not a batch.
        out.append(("syncCheckpoint" if checkpoint_due and (s.pending_deposits or s.locked_shares) else "sync", ids, s.witness_id))
        fees = []
        for candidate in sync_funding_candidates(s, ids, active, checkpoint_due):
            fees.append(candidate)
            terminals = ids[:MAX_BATCH["sync"] - len(fees)]
            if not terminals and not journal_due and not s.allocation_stale:
                break  # Active candidates alone cannot create a paid job.
            out.append(("syncCheckpoint" if checkpoint_due and (s.pending_deposits or s.locked_shares) else "sync", terminals + fees, s.witness_id))

    redeeming = shortfall > 0  # deploy nothing this pass while redeemers wait for ETH
    # FWA's live fees leave no edge: every further cycle loses, so unwind (the vault allows it).
    broken = s.k < 10**18 + s.min_edge_bps * 10**14

    # 2. Standalone claims are unpaid holder work. Use them only when a partial redemption
    #    can be filled without destroying productive listings, and the bounded claim is
    #    cheaper than one unlist. Full exits collect the same fees through unlisting and
    #    checkpoint, so they never pay for a redundant claim first.
    full_exit = s.total_shares and s.locked_shares + 10**15 >= s.total_shares
    credit_checkpoint = checkpoint_due and not catchup and not due and not s.pending_receipts and not s.allocation_stale
    if credit_checkpoint:
        shortfall = max(0, shortfall - s.fee_credit)
    earning, amount = [], 0 if credit_checkpoint else s.fee_credit
    if shortfall and s.locked_shares and not full_exit and not s.winding_down:
        for listing in sorted((l for l in active if l.pending_fees), key=lambda l: (-l.pending_fees, l.id)):
            if amount >= shortfall or len(earning) == MAX_BATCH["harvest"]:
                break
            earning.append(listing)
            amount += listing.pending_fees
        hgas = q["harvest"] + q["harvested"] * len(earning)
        # A due checkpoint already sweeps fee credit without a separate transaction.
        if amount >= shortfall and hgas < q["unlist"] + q["unlisted"] and not (not earning and credit_checkpoint):
            out.append(("harvest", sorted(l.id for l in earning)))
            shortfall = 0

    # 3. Redemption liquidity or wind-down: idle inventory first, then unlist (needs FWA's
    #    queue drained), then liquidate what unlisting returned.
    if s.winding_down or shortfall:
        if s.idle_packs or s.recovery_packs:
            out.append(("liquidate", MAX_BATCH["liquidate"]))
            shortfall = max(0, shortfall - s.idle_value)
    unwind = s.winding_down or broken
    if (unwind or shortfall) and s.queue_drained:
        need_cash = s.winding_down or shortfall > 0
        pool = sorted((l for l in active if not l.crown_locked), key=lambda l: l.pending_fees)
        ids = []
        for l in pool:
            if not unwind and shortfall <= 0:
                break
            ids.append(l.id)
            shortfall = max(0, shortfall - l.value - (l.backing or s.backing))
        for i in range(0, len(ids), MAX_BATCH["unlist"]):
            out.append(("unlist", ids[i:i + MAX_BATCH["unlist"]]))
        if ids and need_cash:
            out.append(("liquidate", MAX_BATCH["liquidate"]))

    # 4. Checkpoint in FWA's blackout with its queue drained, only when holders have flows.
    #    Personal managers have no shares, deposits or checkpoints (s.pooled is False), so the pool
    #    flow fields stay zero and this never fires for them.
    if (s.pooled and s.blackout and s.queue_drained and (not catchup or unexposed) and not s.pending_receipts
            and not s.allocation_stale and not due and (not s.checkpoint_done_this_interval or (s.caller_funded_exit and s.locked_shares))
            and (s.locked_shares or (s.pending_deposits and not spike and not s.caller_funded_exit) or (s.distribution_due and not spike and not s.caller_funded_exit))):
        out.append(("checkpoint", s.witness_id))

    # 5. Tokens (zero in NAV, never sold): claim and burn when the operator opts in.
    total = s.token_pending + s.token_credit + s.token_held
    if total and s.burn_tokens and not spike:
        # Only ids with pending tokens, in harvest-sized batches: bounds gas well under EIP-7825.
        out.append(("burnTokens", s.token_ids[:MAX_BATCH["tokens"]]))
    elif total:
        s.notes.append(f"tokens {total / 1e18:.4f} unburned (run with --burn-tokens; operator pays the gas)")

    # 6. Deploy: relist idle packs, then build new ones only when one cycle repays the build.
    #    Wait for FWA's queue to drain; production admission also rejects staged results atomically.
    if spike or s.winding_down or broken or s.listing_paused or redeeming or not (s.backing or s.backing_proposals) \
            or not s.queue_drained:
        return out
    if journal_backlog_floor(s) > min(s.free if s.keeper_cash is None else s.keeper_cash, s.routine_budget):
        return out
    idle = s.idle_eth
    proposals = s.backing_proposals[:MAX_BATCH["list"]]
    relistable = s.idle_packs if s.relistable_idle is None else s.relistable_idle
    if relistable:
        n = min(relistable, len(proposals))
        while n and sum(proposals[:n]) + quote(s, q['list'] + n*q['listed'], n) > idle:
            n -= 1
        if n:
            out.append(("list", proposals[:n]))
            return out
        if proposals:
            return out  # viable inventory keeps priority when only cash is missing
    if s.mint_fee > s.accepted_mint_fee:
        return out
    if s.recent_volume >= s.slowdown_volume and (s.pack_units_mask >> s.build_units) & 1:
        units = s.build_units
        price = units * UNIT + shape_count(units) * s.mint_fee  # mint cost of one pack (direct mint)
        proposals = s.build_proposals[:MAX_BATCH["build"]]
        build = build_cost(s, units)
        n = 0  # largest batch the vault's capital check accepts: per-pack mint cost plus backing
        limit = MAX_BATCH["build"] if s.build_room is None else min(MAX_BATCH["build"], s.build_room)
        for c in range(min(len(proposals), limit), 0, -1):
            if c * price + sum(proposals[:c]) + quote(s,q['build']+c*(q['build_pack']+shape_count(units)*q['build_shape']+q['listed']),2*c) <= max(0, idle - s.idle_funding):
                n = c
                break
        # The build repays from the keep outcome (build_net), not the bid-only cycle_net.
        if s.backing and build_net(s) and n:
            out.append(("build", units, proposals[:n]))
    return out


def reserve_need(s):
    """Cash for one listing batch plus mandatory journal catchup that returns no backing.

    Checkpoint request charges remain separate. Foreign/refunded entries earn their gas quote
    only, with no per-entry work fee. Essential catchup is priced at its own ceiling.
    """
    q = s.gas_schedule
    listing = (q["list"] + q["listed"] * MAX_BATCH["list"] + q["overhead"]) * s.gas_ceiling * (BPS + s.markup_bps) // BPS
    catchup = (q["sync"] + MAX_BATCH["journal"] * q["journal"] + MAX_BATCH["prune"] * q["pruned"])
    routine = (catchup + q["overhead"]) * s.gas_ceiling * (BPS + s.markup_bps) // BPS
    return listing + MAX_BATCH["list"] * s.work_fee + routine


def journal_backlog_floor(s):
    """Packed journal floor; own transitions, terminal work and distribution proof can add cost."""
    q = s.gas_schedule
    if not s.open_positions and not s.active_count and not s.pending_receipts and not s.listings:
        return 0
    records = s.completed_prefix - s.journal_cursor
    if records and scan_vault(s):
        return quote(s, q["journal_tail"] + s.open_positions * q["scan"])
    full, tail = divmod(records, MAX_BATCH["journal"])
    return full * quote(s, q["sync"] + MAX_BATCH["journal"] * q["journal"]) + (quote(s, q["journal_tail"] + tail*q["journal"]) if tail else 0)


def exposure_share_bps(backings, total_weight):
    """This keeper's combined share of FWA's selection weight, in bps: the sum over its own Active
    listings (across every account it runs) of each listing's FWA weight 1e36/backing, over FWA's
    total weight. Pure and monitoring only: it never enters a plan, only /health."""
    if total_weight <= 0:
        return 0
    own = sum(10**36 // b for b in backings if b > 0)
    return own * BPS // total_weight


def exposure_status(share_bps):
    """Status rows for the combined selection-weight share: an info line always, and an action when
    the share reaches EXPOSURE_SHARE_HIGH_BPS (the keeper's listings win too large a fraction of
    selections; the operator should widen backings or add independent listers)."""
    out = [("EXPOSURE_SHARE", "info", f"keeper holds {share_bps / 100:.2f}% of FWA selection weight across its accounts")]
    if share_bps >= EXPOSURE_SHARE_HIGH_BPS:
        out.append(("EXPOSURE_SHARE_HIGH", "action",
                    f"combined selection-weight share {share_bps / 100:.2f}% >= {EXPOSURE_SHARE_HIGH_BPS / 100:.0f}%"))
    return out


def status(s, planned=None):
    """Operational states for monitoring: (code, kind, detail). kind is "ok", "wait" (normal,
    clears by itself), "info", or "action" (someone must intervene)."""
    planned = plan(s) if planned is None else planned
    out = []
    spike = s.gas_price > s.gas_ceiling
    shortfall = max(0, s.owed_estimate - s.free)
    if s.winding_down:
        out.append(("WINDING_DOWN", "info", f"{s.open_positions} positions, {s.idle_packs} idle packs left to unwind"))
    if spike:
        out.append(("GAS_ABOVE_CEILING", "wait", f"bid {s.gas_price / 1e9:.3f} gwei > ceiling {s.gas_ceiling / 1e9:.3f}; "
                    + ("liability work only" if planned else "nothing owed waits")))
    if any(l.status == ALLOCATED and s.now < l.allocated_at + s.settlement_window for l in s.listings):
        out.append(("WAITING_SETTLEMENT", "wait", "a purchaser is inside FWA's settlement window"))
    if (s.pending_deposits or s.locked_shares) and not s.checkpoint_done_this_interval \
            and not (s.blackout and s.queue_drained):
        out.append(("WAITING_CHECKPOINT_WINDOW", "wait", "flows wait for FWA's blackout with a drained queue"))
    if not s.backing and not s.winding_down:
        out.append(("QUOTE_UNAVAILABLE", "wait", "FWA admission or its floor quote refuses a listing: nothing new lists"))
    if s.k < 10**18 + s.min_edge_bps * 10**14 and not s.winding_down:
        out.append(("EDGE_GATE_FAILED", "action", f"k {s.k / 1e18:.4f} below 1 + minEdge: positions unwinding; "
                    "consider wind-down"))
    elif s.backing and not spike and not s.winding_down and not s.idle_packs and not cycle_net(s):
        out.append(("BID_CYCLE_UNPROFITABLE", "wait", "gas too high for a bid cycle to repay itself"))
    if s.journal_cursor < s.completed_prefix:
        out.append(("JOURNAL_CATCHUP", "wait", f"{s.completed_prefix - s.journal_cursor} completed global entries remain"))
        floor = journal_backlog_floor(s)
        out.append(("JOURNAL_FUNDING", "info", f"packed journal floor {floor} wei; free {s.free} wei; routine permission {s.routine_budget} wei"))
        short = [name for name, have in (("cash", s.free), ("permission", s.routine_budget)) if floor > have]
        if short:
            # Cash is ETH the vault holds; permission is the routine budget. Neither creates the other.
            out.append(("MAINTENANCE_UNFUNDED", "wait", f"new exposure waits: known backlog {floor} wei exceeds "
                        + " and ".join(f"routine {n}" for n in short)))
    if s.pending_receipts:
        out.append(("RECEIPTS_PENDING", "wait", f"{s.pending_receipts} identified payments require reconciliation"))
    if s.allocation_stale:
        out.append(("ALLOCATION_CLEANUP", "wait", "resolved allocation queue heads require bounded cleanup"))
    if shortfall:
        out.append(("REDEMPTION_LIQUIDITY_SHORT", "wait" if planned else "action",
                    f"{shortfall / 1e18:.4f} ETH owed to redeemers beyond free ETH"))
    if s.token_pending + s.token_credit + s.token_held and not s.burn_tokens:
        out.append(("TOKENS_UNBURNED", "info", f"{(s.token_pending + s.token_credit + s.token_held) / 1e18:.4f} FWA tokens; "
                    "anyone may call burnTokens"))
    owed = [l.id for l in s.listings if l.pack_owed]
    if owed:
        out.append(("RECOVERY_REQUIRED", "action", f"FWA holds packs owed to the vault for listings {owed[:5]}"))
    if s.listing_paused and not s.winding_down:
        out.append(("LISTING_PAUSED", "action", "owner paused listing"))
    if s.mint_fee > s.accepted_mint_fee:
        out.append(("MINT_FEE_NOT_ACCEPTED", "action", f"live mint fee {s.mint_fee} wei exceeds accepted {s.accepted_mint_fee} wei"))
    if s.routine_budget == 0:
        out.append(("ROUTINE_BUDGET_EMPTY", "wait", "strategy work is unpaid until the routine budget refills"))
    if s.essential_budget == 0 and (s.locked_shares or s.winding_down):
        out.append(("ESSENTIAL_BUDGET_EMPTY", "action", "unlisting and liquidation are unpaid; holders can run them; sync uses routine permission"))
    if s.reserve < reserve_need(s) and not s.winding_down:
        out.append(("RESERVE_BELOW_NEED", "info", f"reserve {s.reserve / 1e18:.4f} ETH; maximum listing and sync batches quote {reserve_need(s) / 1e18:.4f} ETH"))
    if not out:
        out.append(("OK", "ok", "operating normally"))
    return out
