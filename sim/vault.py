"""Exact integer model of PackVault's accounting, shared by the reconciler (sim/reconcile.py,
which checks it against a fork run to the wei) and the forward simulation (sim/forward.py).

Every formula mirrors src/PackVault.sol: same order of operations, same floor and ceiling
rounding. FWA, Shapes and ShapePacks are outside this class: callers pass in what they pay or
take (fees, backing, mint fees, keeper pay). The ledger splits every wei into investor NAV,
amounts owed to holders (escrow, redemption and distribution reserves) and expenses (keeper gas
pay, Shapes mint fees, backing lost to purchasers, FWA settlement fees).
"""
from dataclasses import dataclass, field

E = 10**18
UNIT = 10**16
BPS = 10_000
SCALE = 10**36
DEAD_SHARES = 10**15
MIN_DISTRIBUTION = 10**16
SHAPES_PER_MINT = 10

ACTIVE, ALLOCATED, WITHDRAWN, SETTLED, STAGED = 1, 2, 3, 4, 5


def mul_div(a, b, c):
    return a * b // c


def mul_div_up(a, b, c):
    return -(-a * b // c)


@dataclass
class Position:
    units: int
    backing: int
    status: int = ACTIVE
    pending_fees: int = 0  # FWA pendingFees for an active listing
    pack_owned: bool = False  # settled or withdrawn: pack held or owed to the vault


@dataclass
class Redemption:
    shares: int = 0
    era: int = 0
    g0: int = SCALE
    q0: int = 0


@dataclass
class Vault:
    seed: int
    balance: int  # deploy balance: seed plus any dust already at the address
    reserve: int = 5 * 10**16
    distribution_bps: int = 0
    allocated_bound_bps: int = 1_000
    settlement_fee_bps: int = 100

    total_shares: int = DEAD_SHARES
    shares: dict = field(default_factory=dict)
    epoch: int = 0
    high_water_mark: int = 0
    last_nav: int = 0
    pending: dict = field(default_factory=dict)  # holder -> [amount, epoch]
    pending_total: int = 0
    epoch_nav: dict = field(default_factory=dict)
    epoch_supply: dict = field(default_factory=dict)
    epoch_dist: dict = field(default_factory=dict)
    redemptions: dict = field(default_factory=dict)
    locked_shares: int = 0
    redeem_era: int = 0
    redeem_g: int = SCALE
    redeem_q: int = 0
    era_final_q: dict = field(default_factory=dict)
    redemption_reserve: int = 0
    claimable: dict = field(default_factory=dict)
    claimable_total: int = 0
    dist_per_share: int = 0
    dist_debt: dict = field(default_factory=dict)
    distribution_reserve: int = 0

    positions: dict = field(default_factory=dict)  # listing id -> Position
    idle_packs: list = field(default_factory=list)  # units of each idle pack
    loose_shapes: int = 0

    # Expense and income ledger (wei). NAV changes only through these and holder flows.
    keeper_paid: int = 0
    mint_fees: int = 0
    fees_received: int = 0
    backing_lost: int = 0
    settlement_fees: int = 0

    def __post_init__(self):
        self.high_water_mark = self.seed * E // DEAD_SHARES

    # ------------------------------------------------------------ cash buckets
    def free(self):
        owed = self.pending_total + self.redemption_reserve + self.distribution_reserve + self.claimable_total
        return self.balance - owed if self.balance > owed else 0

    def owed_estimate(self):
        if self.locked_shares == 0:
            return 0
        return mul_div_up(self.locked_shares, self.last_nav, self.total_shares)

    def idle(self):
        keep = self.reserve + self.owed_estimate()
        f = self.free()
        return f - keep if f > keep else 0

    def pay_keeper(self, amount):
        amount = min(amount, self.free())
        self.balance -= amount
        self.keeper_paid += amount
        return amount

    # ------------------------------------------------------------ inventory and listings
    def restock(self, count, units, mint_fee):
        need = count * units
        mints = -(-(need - self.loose_shapes) // SHAPES_PER_MINT) if need > self.loose_shapes else 0
        self.balance -= mints * (UNIT * SHAPES_PER_MINT + mint_fee)
        self.mint_fees += mints * mint_fee
        self.loose_shapes += mints * SHAPES_PER_MINT - need
        self.idle_packs += [units] * count
        return mints

    def list(self, listing_id, backing, status=ACTIVE):
        units = self.idle_packs.pop()
        self.balance -= backing
        self.positions[listing_id] = Position(units, backing, status)

    def accrue(self, listing_id, amount):
        self.positions[listing_id].pending_fees += amount

    def receive_fees(self, amount):
        """ETH FWA paid the vault from claimListingFees or withdrawEarnings."""
        self.balance += amount
        self.fees_received += amount

    def bid_settled(self, listing_id):
        """Purchaser took the bid: backing gone, pack back to the vault (still an open position
        until sync)."""
        p = self.positions[listing_id]
        p.status, p.pack_owned, p.pending_fees = SETTLED, True, 0
        self.backing_lost += p.backing

    def kicked(self, listing_id):
        """FWA kicked the listing (backing above a lowered cap): full backing and pack back."""
        p = self.positions[listing_id]
        p.status, p.pack_owned, p.pending_fees = WITHDRAWN, True, 0
        self.balance += p.backing

    def sync_owned(self, listing_id):
        """sync of a settled or withdrawn position whose pack the vault holds: pack goes idle."""
        p = self.positions.pop(listing_id)
        self.idle_packs.append(p.units)

    def resolve_bid(self, listing_id):
        self.bid_settled(listing_id)
        self.sync_owned(listing_id)

    def resolve_keep(self, listing_id):
        """Purchaser kept the pack (or the vault reclaimed backing): backing less the fee back."""
        p = self.positions.pop(listing_id)
        fee = p.backing * self.settlement_fee_bps // BPS
        self.balance += p.backing - fee
        self.settlement_fees += fee
        self.backing_lost += p.units * UNIT  # the pack left: its value is the loss

    def unlist(self, listing_id):
        p = self.positions.pop(listing_id)
        self.balance += p.backing
        self.idle_packs.append(p.units)

    def liquidate_one(self):
        if self.idle_packs:
            self.balance += self.idle_packs.pop() * UNIT
        elif self.loose_shapes:
            self.loose_shapes -= 1
            self.balance += UNIT

    # ------------------------------------------------------------ holders
    def deposit(self, h, amount):
        self._settle_holder(h)
        d = self.pending.setdefault(h, [0, 0])
        d[0] += amount
        d[1] = self.epoch
        self.pending_total += amount
        self.balance += amount

    def cancel(self, h):
        self._settle_holder(h)
        amount = self.pending.pop(h, [0, 0])[0]
        self.pending_total -= amount
        self.balance -= amount
        return amount

    def request_redeem(self, h, amount):
        self._settle_holder(h)
        self._settle_dist(h)
        self.shares[h] = self.shares.get(h, 0) - amount
        self.dist_debt[h] = self.shares[h] * self.dist_per_share // E
        r = self.redemptions.setdefault(h, Redemption())
        r.shares += amount
        self.locked_shares += amount

    def claim(self, h):
        self._settle_holder(h)
        self._settle_dist(h)
        amount = self.claimable.get(h, 0)
        self.claimable[h] = 0
        self.claimable_total -= amount
        self.balance -= amount
        return amount

    def share_balance(self, h):
        s = self.shares.get(h, 0)
        d = self.pending.get(h)
        if d and d[0] and d[1] < self.epoch:
            s += d[0] * self.epoch_supply[d[1]] // self.epoch_nav[d[1]]
        return s

    def _settle_holder(self, h):
        d = self.pending.get(h)
        if d and d[0] and d[1] < self.epoch:
            self._settle_dist(h)
            minted = d[0] * self.epoch_supply[d[1]] // self.epoch_nav[d[1]]
            self.shares[h] = self.shares.get(h, 0) + minted
            self.dist_debt[h] = self.dist_debt.get(h, 0) + minted * self.epoch_dist[d[1]] // E
            del self.pending[h]
        r = self.redemptions.setdefault(h, Redemption())
        if r.shares == 0:
            r.era, r.g0, r.q0 = self.redeem_era, self.redeem_g, self.redeem_q
            return
        remaining = 0
        if r.era < self.redeem_era:
            paid = mul_div(r.shares, self.era_final_q[r.era] - r.q0, r.g0)
        else:
            paid = mul_div(r.shares, self.redeem_q - r.q0, r.g0)
            remaining = mul_div(r.shares, self.redeem_g, r.g0)
        if paid:
            self.redemption_reserve -= paid
            self.claimable[h] = self.claimable.get(h, 0) + paid
            self.claimable_total += paid
        r.shares = remaining
        r.era, r.g0, r.q0 = self.redeem_era, self.redeem_g, self.redeem_q

    def _settle_dist(self, h):
        owed = self.shares.get(h, 0) * self.dist_per_share // E - self.dist_debt.get(h, 0)
        if owed:
            self.distribution_reserve -= owed
            self.claimable[h] = self.claimable.get(h, 0) + owed
            self.claimable_total += owed
            self.dist_debt[h] = self.dist_debt.get(h, 0) + owed

    # ------------------------------------------------------------ checkpoint
    def nav_positions(self):
        nav = alloc = 0
        for p in self.positions.values():
            value = p.units * UNIT
            if p.status == ACTIVE:
                nav += value + p.backing + p.pending_fees
            elif p.status == STAGED:
                nav += value + p.backing
            elif p.status == ALLOCATED:
                floor = min(value, p.backing * (BPS - self.settlement_fee_bps) // BPS)
                nav += floor
                alloc += floor
            elif p.pack_owned:
                nav += value
        return nav, alloc

    def checkpoint(self, credit=0):
        """Mirror of PackVault.checkpoint. `credit` is FWA fee credit harvested inside it.
        Returns True when holder flows made it a paid call."""
        work = self.pending_total != 0 or self.locked_shares != 0
        nav_pos, alloc = self.nav_positions()
        if credit:
            self.receive_fees(credit)
        inventory = self.loose_shapes * UNIT + sum(self.idle_packs) * UNIT
        nav = self.free() + nav_pos + inventory
        if alloc * BPS > nav * self.allocated_bound_bps:
            raise RuntimeError("AllocatedExposure")
        supply = self.total_shares
        if self.locked_shares:
            owed = mul_div_up(self.locked_shares, nav, supply)
            liquid = self.free() + self.pending_total
            frac = SCALE if owed <= liquid else mul_div(liquid - 2 if liquid > 2 else 0, SCALE, owed)
            filled = mul_div(self.locked_shares, frac, SCALE)
            unit = mul_div(frac, nav, supply)
            paid = mul_div_up(self.locked_shares, unit, SCALE)
            self.redeem_q += mul_div(self.redeem_g, unit, SCALE)
            if frac == SCALE:
                self.era_final_q[self.redeem_era] = self.redeem_q
                self.redeem_era += 1
                self.redeem_g, self.redeem_q, self.locked_shares = SCALE, 0, 0
            else:
                self.redeem_g = mul_div(self.redeem_g, SCALE - frac, SCALE)
                self.locked_shares -= filled
            self.redemption_reserve += paid
            self.total_shares = supply - filled
            nav -= paid
            supply -= filled
        distributed = 0
        per_share = nav * E // supply
        if (self.locked_shares == 0 and supply > DEAD_SHARES and per_share > self.high_water_mark
                and self.distribution_bps):
            gain = mul_div(per_share - self.high_water_mark, supply, E)
            distributed = min(gain * self.distribution_bps // BPS, self.idle())
            if distributed >= MIN_DISTRIBUTION:
                self.dist_per_share += distributed * E // (supply - DEAD_SHARES)
                self.distribution_reserve += distributed
                nav -= distributed
            else:
                distributed = 0
        per_share = nav * E // supply
        if per_share > self.high_water_mark:
            self.high_water_mark = per_share
        self.epoch_nav[self.epoch] = nav
        self.epoch_supply[self.epoch] = supply
        self.epoch_dist[self.epoch] = self.dist_per_share
        if self.pending_total:
            self.total_shares += self.pending_total * supply // nav
            nav += self.pending_total
            self.pending_total = 0
        self.last_nav = nav
        self.epoch += 1
        return work or distributed != 0

    # ------------------------------------------------------------ reporting
    def nav_now(self):
        """NAV as a checkpoint would compute it now (before flows)."""
        nav_pos, _ = self.nav_positions()
        return self.free() + nav_pos + self.loose_shapes * UNIT + sum(self.idle_packs) * UNIT
