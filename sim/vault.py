"""Exact integer model of PackVault's accounting, shared by the reconciler (sim/reconcile.py,
which checks it against a fork run to the wei) and the forward simulation (sim/forward.py).

Every formula mirrors src/PackVault.sol: same order of operations, same floor and ceiling
rounding. FWA, Shapes and ShapePacks are outside this class: callers pass in what they pay or
take (fees, backing, mint fees, keeper pay). The ledger splits every wei into investor NAV,
amounts owed to holders (escrow, redemption and distribution reserves) and expenses (keeper gas
pay, Shapes mint fees, backing lost to purchasers, FWA settlement fees).
"""
import copy
from dataclasses import dataclass, field

E = 10**18
UNIT = 10**16
BPS = 10_000
SCALE = 10**36
DEAD_SHARES = 10**15
MIN_DISTRIBUTION = 10**16
MAX_LIST_BATCH = 8
MAX_BUILD_BATCH = 4  # VaultLib.MAX_BUILD_BATCH: packs built-and-listed per call

ACTIVE, ALLOCATED, WITHDRAWN, SETTLED, STAGED = 1, 2, 3, 4, 5
OWED = 3  # cached book state; distinct from the live FWA status namespace


def shape_count(units):
    """VaultLib.makeup: fewest Shapes for a pack of `units` x 0.01 ETH (0.1, 0.05, 0.01 denominations).
    Six units are one 0.05 and one 0.01 Shape: two paid primary mints."""
    return units // 10 + units % 10 // 5 + units % 5


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
    expired: bool = False  # allocated and past FWA's settlement window (sync can resolve it)
    value: int = 0  # exact wei backing, independent of strategy units
    fee_debt: int = 0
    state: int = ACTIVE  # cached book membership, independent of live FWA status
    allocated_at: int = 0
    unresolved_uplift: int = 0
    shapes: int = 0


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
    uplift_bound_bps: int = 25
    # Kept as an explicit deprecated constructor alias for historical fixtures only.
    allocated_bound_bps: int = None
    construction_cost: int = 0
    reference_capital: int = 24 * 10**16
    accepted_mint_fee: int = 10**15
    live_mint_fee: int = 10**15
    pack_units_mask: int = 8
    min_distribution: int = MIN_DISTRIBUTION
    settlement_fee_bps: int = 100

    total_shares: int = DEAD_SHARES
    shares: dict = field(default_factory=dict)
    epoch: int = 0
    high_water_mark: int = 0
    last_nav: int = 0
    pending: dict = field(default_factory=dict)  # holder -> [amount, epoch, deployment charge]
    pending_total: int = 0
    processing_pool: int = 0
    charge_era: int = 0
    charge_eras: dict = field(default_factory=dict)  # era -> [total, refundable, closed]
    contributions: list = field(default_factory=list)  # [payer, era, interval start, amount, claimed]
    charge_refund_reserve: int = 0
    issuances: dict = field(default_factory=dict)  # epoch -> [gross, issued, remaining gross, remaining shares]
    unresolved_keep_uplift: int = 0
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
    idle_packs: list = field(default_factory=list)  # exact wei backing of each idle pack
    idle_shapes: list = field(default_factory=list)
    idle_quotes: list = field(default_factory=list)  # funding quote paired with the idle stack
    idle_funding: int = 0
    tracked_value: int = 0
    idle_value: int = 0
    active_backing: int = 0
    active_count: int = 0
    fee_debt_sum: int = 0
    count_by_debt: dict = field(default_factory=dict)
    allocated_value: int = 0
    allocation_queue: list = field(default_factory=list)
    allocation_head: int = 0
    fee_accumulator: int = 0
    fee_credit: int = 0
    acquisition_cursor: int = 0
    completed_prefix: int = 0
    receipts: dict = field(default_factory=dict)  # payment-time identity, kind, amount and fee
    recovery_packs: list = field(default_factory=list)  # exact remaining backing in oversized gifts
    routine_budget: int = 10**30
    routine_cap: int = 10**30
    routine_rate: int = 0
    budget_at: int = 0

    # Expense and income ledger (wei). NAV changes only through these and holder flows.
    keeper_paid: int = 0
    mint_fees: int = 0
    fees_received: int = 0
    backing_lost: int = 0
    settlement_fees: int = 0

    def __post_init__(self):
        self.high_water_mark = self.seed * E // DEAD_SHARES
        if self.allocated_bound_bps is not None:
            self.uplift_bound_bps = self.allocated_bound_bps

    # ------------------------------------------------------------ cash buckets
    def free(self):
        owed = (self.pending_total + self.redemption_reserve + self.distribution_reserve + self.claimable_total
                + self.processing_pool + self.charge_refund_reserve)
        return self.balance - owed if self.balance > owed else 0

    def owed_estimate(self):
        if self.locked_shares == 0:
            return 0
        return mul_div_up(self.locked_shares, self.last_nav, self.total_shares)

    def idle(self):
        keep = self.reserve + self.owed_estimate()
        f = self.free()
        return f - keep if f > keep else 0

    def keeper_cash_after(self, proceeds=0):
        return max(0, self.free() + proceeds)

    def sync_budget(self, now):
        elapsed = now - self.budget_at
        self.routine_budget = min(self.routine_cap, self.routine_budget + elapsed * self.routine_rate // 86400)
        self.budget_at = now

    def set_budget(self, now, routine_cap, routine_rate):
        self.sync_budget(now)  # Accrue at the old rate before changing capacity.
        self.routine_budget = min(self.routine_budget, routine_cap)
        self.routine_cap, self.routine_rate = routine_cap, routine_rate

    def pay_keeper(self, amount, essential=False, cap=None, source=None):
        if source == 'processing':
            amount = min(amount, self.processing_pool, self.balance)
            self.processing_pool -= amount
            self.balance -= amount
            self.keeper_paid += amount
            return amount
        if source is not None:
            raise ValueError('unsupported keeper cash source')
        # Exit work is unpaid (owner decision); only routine work draws on the budget.
        if essential:
            return 0
        amount = min(amount, self.keeper_cash_after(), self.routine_budget if cap is None else cap)
        if cap is None:
            self.routine_budget -= amount
        self.balance -= amount
        self.keeper_paid += amount
        return amount

    # ------------------------------------------------------------ inventory and listings
    def build(self, ids, units, mint_fee, proposals, fee_debt=None):
        """Mirror of VaultLib.buildAndList: mint each pack of `units` straight into ShapePacks (one
        paid primary mint per Shape, no split, no loose Shapes) and list it at its backing proposal at
        once. `ids` are the FWA listing ids assigned on admission; one proposal per pack; `available`
        ETH (idle()) must cover every pack's mint cost and every backing."""
        count = len(ids)
        if mint_fee > self.accepted_mint_fee:
            raise RuntimeError('MintFeeNotAccepted')
        if (count == 0 or count > MAX_BUILD_BATCH or units < 3 or units > 30
                or not (self.pack_units_mask >> units) & 1 or len(proposals) != count):
            raise RuntimeError("BadBatch")
        n = shape_count(units)
        if len(set(proposals)) != count or any(p.backing in proposals and p.state != OWED for p in self.positions.values()):
            raise RuntimeError('Duplicate')
        price = units * UNIT + n * mint_fee  # createPack cost: the pack's face value plus mint fees
        if self.idle() < count * price + sum(proposals):
            raise RuntimeError("InsufficientBacking")
        for listing_id, backing in zip(ids, proposals):
            self.balance -= price
            self.mint_fees += n * mint_fee
            self.tracked_value += units * UNIT
            self.idle_value += units * UNIT
            self.idle_packs.append(units * UNIT)
            self.idle_shapes.append(n)
            self.idle_quotes.append(0)
            # Admission lists the pack at once (each widens the identifier interval, as on chain).
            self.list(listing_id, backing, fee_debt=fee_debt)

    def _debt_count(self, debt, change):
        self.count_by_debt[debt] = self.count_by_debt.get(debt, 0) + change

    def adopt(self, value, shapes=None):
        """Explicitly register a gift at its actual current backing after old listing retirement."""
        self.tracked_value += value
        self.idle_value += value
        if value > 30 * UNIT:
            self.recovery_packs.append(value)
        else:
            self.idle_packs.append(value)
            self.idle_shapes.append(shape_count(value//UNIT) if shapes is None else shapes)
            self.idle_quotes.append(0)

    def _remove_active(self, p):
        self.active_backing -= p.backing
        self.active_count -= 1
        self.fee_debt_sum -= p.fee_debt
        self._debt_count(p.fee_debt, -1)

    def list(self, listing_id, backing, status=ACTIVE, fee_debt=None):
        if status != ACTIVE:
            raise RuntimeError("InvalidListing")
        if not self.idle_packs or self.balance<backing:
            raise RuntimeError('InsufficientBacking')
        value = self.idle_packs.pop()
        shapes = self.idle_shapes.pop()
        self.idle_funding -= self.idle_quotes.pop()
        self.advance_unexposed()
        units = value // UNIT
        self.balance -= backing
        debt = self.fee_accumulator if fee_debt is None else fee_debt
        self.positions[listing_id] = Position(units, backing, status, value=value, fee_debt=debt, shapes=shapes)
        self.idle_value -= value
        self.active_backing += backing
        self.active_count += 1
        self.fee_debt_sum += debt
        self._debt_count(debt, 1)

    def accrue(self, listing_id, amount):
        p = self.positions[listing_id]
        p.pending_fees += amount
        self.fee_accumulator = max(self.fee_accumulator, p.fee_debt + p.pending_fees)

    def select(self, listing_id, allocated_at=0):
        """Apply an authenticated journal entry, once, before consuming its terminal outcome."""
        p = self.positions[listing_id]
        if p.state != ACTIVE:
            raise RuntimeError("InvalidJournal")
        self._remove_active(p)
        p.state = ALLOCATED
        p.allocated_at = allocated_at
        if p.status == ACTIVE:
            p.status = ALLOCATED
        self.allocated_value += p.value
        p.unresolved_uplift = max(0, p.backing - p.value)
        self.unresolved_keep_uplift += p.unresolved_uplift
        self.allocation_queue.append(listing_id)

    def process_journal(self, entries):
        """One fixed journal job: at most128 reads and16 authenticated own transitions."""
        if len(entries) > 128 or self.acquisition_cursor + len(entries) > self.completed_prefix:
            raise RuntimeError("BadBatch")
        if entries and self.advance_unexposed():
            return 0
        processed = own = 0
        for listing_id in entries:
            if listing_id is not None:
                if own == 16:
                    break
                self.select(listing_id)
                own += 1
            self.acquisition_cursor += 1
            processed += 1
        return processed

    def scan_rebase(self, found, scan_gas=30_000, journal_gas=22_000):
        """ScanLib.rebase: read every open Active listing instead of FWA's journal when that costs no
        more than the next journal batch. `found` is the (allocation time, id) of each own listing FWA
        allocated that the book still holds Active. Returns the listings read, or None when the journal
        path runs instead (not eligible, more than 16 found, or an order the queue cannot take)."""
        backlog = self.completed_prefix - self.acquisition_cursor
        if not backlog or len(self.positions) > 96 or len(self.positions) * scan_gas > min(backlog, 128) * journal_gas:
            return None
        found = sorted(found)
        if len(found) > 16 or (found and found[0][0] < max((p.allocated_at for p in self.positions.values()
                                                           if p.state != ACTIVE), default=0)):
            return None
        scanned = sum(p.state == ACTIVE for p in self.positions.values())
        for at, listing_id in found:
            self.select(listing_id, at)
        self.acquisition_cursor = self.completed_prefix
        return scanned

    def advance_unexposed(self):
        """Owner-approved O(1) completeness proof; no journal payment is earned."""
        if (self.positions or self.receipts or self.active_count or self.active_backing
                or self.allocated_value or self.acquisition_cursor == self.completed_prefix):
            return False
        self.acquisition_cursor = self.completed_prefix
        return True

    def distribution_tail(self, cost, credit=0):
        """Conservative checkpoint proof after the largest routine sync payment."""
        if (self.receipts or self.total_shares <= DEAD_SHARES or not self.distribution_bps
                or self.pending_total or self.locked_shares):
            return False
        if self.allocation_head < len(self.allocation_queue):
            p = self.positions.get(self.allocation_queue[self.allocation_head])
            if p is None or p.state != ALLOCATED or p.expired:
                return False
        nav = self.free() + self.tracked_value + self.active_backing + self.pending_active_fees() + credit - cost
        if nav <= 0 or self.unresolved_keep_uplift * BPS > nav * self.uplift_bound_bps:
            return False
        per_share = nav * E // self.total_shares
        if per_share <= self.high_water_mark:
            return False
        gain = mul_div(per_share - self.high_water_mark, self.total_shares, E)
        return min(gain * self.distribution_bps // BPS, self.free() + credit - self.reserve - cost) >= MIN_DISTRIBUTION

    def harvest_listing(self, listing_id, new_debt=None):
        p = self.positions[listing_id]
        debt = self.fee_accumulator if new_debt is None else new_debt
        self._debt_count(p.fee_debt, -1)
        self._debt_count(debt, 1)
        self.fee_debt_sum += debt - p.fee_debt
        p.fee_debt = debt
        p.pending_fees = 0

    def sync_fee_plan(self, ids, credit, gas_q, units, quote, share_bps,
                      credit_gas=40_000, funding_gas=40_000, claim_gas=80_000,
                      cash_delta=0, distribution_tail=False):
        """Preview VaultLib._fundSync without applying a transaction that may be declined.

        `quote(gas, units)` is the full bytecode payment envelope. Terminal proceeds are
        supplied through `cash_delta`; protected balances remain excluded by free().
        The returned credit and active IDs are collected only with the eligible sync.
        """
        if gas_q == 0:
            return gas_q, 0, []
        cost = quote(gas_q, units)
        if self.routine_budget < cost:
            return gas_q, 0, []
        proceeds, taken_credit = cash_delta, 0
        original_credit = credit
        proof = lambda gas: not distribution_tail or self.distribution_tail(quote(gas, 0), original_credit)
        combined = quote(gas_q + credit_gas, units)
        if (credit and combined <= self.routine_budget
                and (combined - cost) * BPS <= credit * share_bps and proof(gas_q + credit_gas)):
            taken_credit, credit = credit, 0
            proceeds += taken_credit
            gas_q += credit_gas
            cost = combined
        if self.keeper_cash_after(proceeds) >= cost:
            return gas_q, taken_credit, []
        claims, fees = [], credit
        for listing_id in ids:
            p = self.positions.get(listing_id)
            if (not p or p.state != ACTIVE or p.status != ACTIVE
                    or listing_id in claims or not p.pending_fees):
                continue
            claims.append(listing_id)
            fees += p.pending_fees
            funded_gas = gas_q + funding_gas + len(claims) * claim_gas + (credit_gas if credit else 0)
            combined = quote(funded_gas, units)
            if self.keeper_cash_after(proceeds + fees) < combined:
                continue
            # The first cash-covering prefix is final. Padding cannot qualify a failing
            # fee share or permission check, or manufacture another claim's compensation.
            if (combined > self.routine_budget or (combined - cost) * BPS > fees * share_bps
                    or not proof(funded_gas)):
                return gas_q, taken_credit, []
            return funded_gas, taken_credit + credit, claims
        return gas_q, taken_credit, []

    def pending_active_fees(self, witness_id=None):
        if self.active_count == 0:
            return 0
        if witness_id is None:
            # Offchain convenience only. Production callers select this ID from their event index.
            witness_id = min((i for i, p in self.positions.items() if p.state == ACTIVE),
                             key=lambda i: self.positions[i].fee_debt)
        p = self.positions[witness_id]
        if p.state != ACTIVE or p.status != ACTIVE:
            raise RuntimeError("BadWitness")
        d, pending = p.fee_debt, p.pending_fees
        if pending == 0:
            if self.count_by_debt.get(d, 0) + self.count_by_debt.get(d + 1, 0) != self.active_count:
                raise RuntimeError("BadWitness")
            return 0
        a = d + pending
        return self.active_count * a + self.count_by_debt.get(a + 1, 0) - self.fee_debt_sum

    def prune(self, max_count):
        advanced = 0
        while advanced < max_count and self.allocation_head < len(self.allocation_queue):
            p = self.positions.get(self.allocation_queue[self.allocation_head])
            if p and p.state == ALLOCATED:
                break
            self.allocation_head += 1
            advanced += 1
        return advanced

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
        if listing_id in self.receipts:
            raise RuntimeError("Duplicate")
        self.receipts[listing_id] = (2, p.backing, 0)
        self.balance += p.backing

    def sync_owned(self, listing_id, owned=True):
        """sync of a settled or withdrawn position whose pack the vault holds: pack goes idle."""
        p = self.positions[listing_id]
        if p.state == ACTIVE:
            self._remove_active(p)
        elif p.state == ALLOCATED:
            self.allocated_value -= p.value
            self.unresolved_keep_uplift -= p.unresolved_uplift
            p.unresolved_uplift = 0
        elif p.state != OWED:
            raise RuntimeError("InvalidListing")
        if not owned:
            p.state = OWED
            return
        del self.positions[listing_id]
        self.receipts.pop(listing_id, None)
        self.idle_value += p.value
        self.idle_packs.append(p.value)
        self.idle_shapes.append(p.shapes or shape_count(p.units))
        self.idle_quotes.append(p.backing)
        self.idle_funding += p.backing

    def resolve_bid(self, listing_id):
        if self.positions[listing_id].state == ACTIVE:
            self.select(listing_id)
        self.bid_settled(listing_id)
        self.sync_owned(listing_id)

    def resolve_keep(self, listing_id):
        """Purchaser kept the pack (or the vault reclaimed backing): backing less the fee back."""
        self.record_keep(listing_id, self.settlement_fee_bps)
        self.consume_keep(listing_id)

    def record_keep(self, listing_id, fee_bps):
        p = self.positions[listing_id]
        if listing_id in self.receipts:
            raise RuntimeError("Duplicate")
        amount = p.backing * (BPS - fee_bps) // BPS
        self.receipts[listing_id] = (1, amount, fee_bps)
        self.balance += amount
        self.settlement_fees += p.backing - amount
        p.status = SETTLED
        p.pack_owned = False

    def consume_keep(self, listing_id):
        p = self.positions[listing_id]
        if p.state != ALLOCATED or self.receipts.get(listing_id, (0,))[0] != 1:
            raise RuntimeError("InvalidListing")
        del self.receipts[listing_id]
        del self.positions[listing_id]
        self.allocated_value -= p.value
        self.unresolved_keep_uplift -= p.unresolved_uplift
        self.tracked_value -= p.value
        self.backing_lost += p.value  # the pack left: its value is the loss

    def unlist(self, listing_id):
        p = self.positions.pop(listing_id)
        self._remove_active(p)
        self.idle_value += p.value
        self.balance += p.backing
        self.idle_packs.append(p.value)
        self.idle_shapes.append(p.shapes or shape_count(p.units))
        self.idle_quotes.append(p.backing)
        self.idle_funding += p.backing

    def liquidate_one(self):
        if not self.idle_packs:
            return
        value = self.idle_packs.pop()
        self.idle_shapes.pop()
        self.idle_funding -= self.idle_quotes.pop()
        self.balance += value
        self.tracked_value -= value
        self.idle_value -= value

    def recover_pack(self, amount, complete=False):
        """Actual ETH paid by ShapePacks.claimEth's bounded chunk, supplied by the real caller."""
        if not self.recovery_packs or amount > self.recovery_packs[-1] or (complete and amount != self.recovery_packs[-1]):
            raise RuntimeError("InvalidRecovery")
        self.recovery_packs[-1] -= amount
        self.tracked_value -= amount
        self.idle_value -= amount
        self.balance += amount
        if complete:
            self.recovery_packs.pop()

    # ------------------------------------------------------------ holders
    def contribute(self, payer, amount):
        if not amount:
            return
        era = self.charge_eras.setdefault(self.charge_era, [0, 0, False])
        self.contributions.append([payer, self.charge_era, era[0], amount, False])
        era[0] += amount
        self.processing_pool += amount

    def fund_checkpoint(self, payer, value, quote):
        if not self.pending_total and not self.locked_shares:
            raise RuntimeError('Nothing')
        amount = min(value, max(0, quote - self.processing_pool))
        self.balance += amount
        self.contribute(payer, amount)
        return value - amount

    def close_charge_era(self):
        era = self.charge_eras.setdefault(self.charge_era, [0, 0, False])
        if not era[0]:
            return
        era[1], era[2] = self.processing_pool, True
        self.charge_refund_reserve += self.processing_pool
        self.processing_pool = 0
        self.charge_era += 1

    def checkpoint_refund(self, contribution_id):
        payer, era_id, start, amount, claimed = self.contributions[contribution_id]
        total, refund, closed = self.charge_eras[era_id]
        return 0 if claimed or not closed else (start + amount) * refund // total - start * refund // total

    def claim_checkpoint_refund(self, h, ids):
        snapshot = copy.deepcopy(self.__dict__)
        try:
            return self._claim_checkpoint_refund(h, ids)
        except Exception:
            self.__dict__.update(snapshot)
            raise

    def _claim_checkpoint_refund(self, h, ids):
        if not ids or len(ids) > 16:
            raise RuntimeError('Amount')
        if any(self.contributions[i][0] != h for i in ids):
            raise RuntimeError('Amount')
        amount = 0
        for i in ids:
            refund = self.checkpoint_refund(i)
            if self.charge_eras[self.contributions[i][1]][2]:
                self.contributions[i][4] = True
                amount += refund
        if not amount:
            raise RuntimeError('Nothing')
        self.charge_refund_reserve -= amount
        self.balance -= amount
        return amount

    def deposit(self, h, amount, ck=0):
        """Gross cancellable escrow; construction is computed only at commitment."""
        self._settle_holder(h)
        d = self.pending.setdefault(h, [0, self.epoch])
        d[0] += amount
        d[1] = self.epoch
        self.pending_total += amount
        self.contribute(h, ck)
        self.balance += amount + ck

    def cancel(self, h, keep=0):
        self._settle_holder(h)
        d = self.pending.get(h)
        if not d or not d[0]:
            raise RuntimeError('Nothing')
        amount = self.pending.pop(h)[0]
        self.pending_total -= amount
        if not self.pending_total and not self.locked_shares:
            self.close_charge_era()
        self.balance -= amount
        return amount

    def request_redeem(self, h, amount, ck=0):
        self._settle_holder(h)
        if amount <= 0 or amount > self.shares.get(h, 0):
            raise RuntimeError('Amount')
        self.contribute(h, ck)
        # Exit work is unpaid: the only redemption charge is the checkpoint (ck).
        self.balance += ck
        self._settle_dist(h)
        self.shares[h] -= amount
        self.dist_debt[h] = self.shares[h] * self.dist_per_share // E
        r = self.redemptions.setdefault(h, Redemption())
        r.shares += amount
        self.locked_shares += amount

    def claim(self, h):
        self._settle_holder(h)
        self._settle_dist(h)
        amount = self.claimable.get(h, 0)
        if not amount:
            raise RuntimeError("Nothing")
        self.claimable[h] = 0
        self.claimable_total -= amount
        self.balance -= amount
        return amount

    def share_balance(self, h):
        s = self.shares.get(h, 0)
        d = self.pending.get(h)
        if d and d[0] and d[1] < self.epoch:
            issuance = self.issuances[d[1]]
            s += issuance[3] if d[0] == issuance[2] else d[0] * issuance[1] // issuance[0]
        return s

    def _settle_holder(self, h):
        d = self.pending.get(h)
        if d and d[0] and d[1] < self.epoch:
            self._settle_dist(h)
            issuance = self.issuances[d[1]]
            minted = issuance[3] if d[0] == issuance[2] else d[0] * issuance[1] // issuance[0]
            issuance[2] -= d[0]
            issuance[3] -= minted
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
    def checkpoint_proof_counts(self, oracle_exempt=True):
        """Actual completed proof work; request funding separately reserves a conservative ceiling."""
        entries=reads=0
        if self.active_count and len(self.positions)<=32 and not oracle_exempt:
            entries=len(self.positions)
            reads=sum(p.state==ACTIVE for p in self.positions.values())
        if self.allocated_value:
            queued=self.allocation_queue[self.allocation_head:]
            if len(queued)>32:
                raise RuntimeError('CatchUpFirst')
            entries+=len(queued)
            reads+=sum(i in self.positions and self.positions[i].state==ALLOCATED for i in queued)
        return entries,reads

    def nav_positions(self):
        if self.allocated_value and len(self.allocation_queue) - self.allocation_head > 32:
            raise RuntimeError('CatchUpFirst')
        expired = False
        if self.allocation_head < len(self.allocation_queue):
            p = self.positions.get(self.allocation_queue[self.allocation_head])
            if p is None or p.state != ALLOCATED:
                raise RuntimeError("NeedsPrune")
            expired = p.expired
        return (self.tracked_value - self.idle_value + self.active_backing + self.pending_active_fees(),
                self.allocated_value, expired)

    def checkpoint(self, credit=0, keeper_payment=0, recovery_only=False):
        snapshot = copy.deepcopy(self.__dict__)
        try:
            return self._checkpoint(credit, keeper_payment, recovery_only)
        except Exception:
            self.__dict__.update(snapshot)
            raise

    def recover_checkpoint(self, credit=0):
        return self.checkpoint(credit, recovery_only=True)

    def _checkpoint(self, credit, keeper_payment, recovery_only=False):
        """Mirror of PackVault.checkpoint. `credit` is FWA fee credit harvested inside it.
        Returns True when holder flows made it a paid call."""
        if recovery_only and not self.locked_shares:
            raise RuntimeError("Nothing")
        work = (not recovery_only and self.pending_total != 0) or self.locked_shares != 0
        if not work and not self.distribution_bps:
            raise RuntimeError("Nothing")
        self.advance_unexposed()
        if self.acquisition_cursor != self.completed_prefix:
            raise RuntimeError("CatchUpFirst")
        if self.receipts:
            raise RuntimeError("PendingReceipts")
        nav_pos, alloc, expired = self.nav_positions()
        if expired:
            raise RuntimeError("SyncFirst")
        if credit:
            self.receive_fees(credit)
            self.fee_credit = 0
        inventory = self.idle_value
        nav = self.free() + nav_pos + inventory
        if self.unresolved_keep_uplift * BPS > nav * self.uplift_bound_bps:
            raise RuntimeError("AllocatedExposure")
        supply = self.total_shares
        filled = 0
        if self.locked_shares:
            owed = mul_div_up(self.locked_shares, nav, supply)
            liquid = self.free() + (0 if recovery_only else self.pending_total)
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
        if (not recovery_only and self.locked_shares == 0 and supply > DEAD_SHARES and per_share > self.high_water_mark
                and self.distribution_bps):
            gain = mul_div(per_share - self.high_water_mark, supply, E)
            distributed = min(gain * self.distribution_bps // BPS, self.idle())
            if distributed and distributed >= self.min_distribution:
                self.dist_per_share += distributed * E // (supply - DEAD_SHARES)
                self.distribution_reserve += distributed
                nav -= distributed
            else:
                distributed = 0
        per_share = nav * E // supply
        if not recovery_only and per_share > self.high_water_mark:
            self.high_water_mark = per_share
        if not recovery_only:
            self.epoch_dist[self.epoch] = self.dist_per_share
        committed = not recovery_only and self.pending_total != 0
        if committed:
            if self.pack_units_mask and self.live_mint_fee > self.accepted_mint_fee:
                raise RuntimeError('MintFeeNotAccepted')
            gross = self.pending_total
            cost = self.construction_cost if self.pack_units_mask else 0
            charge = gross * cost // (self.reference_capital + cost)
            issued = (gross - charge) * supply // nav
            if not issued:
                raise RuntimeError('Amount')
            self.issuances[self.epoch] = [gross, issued, gross, issued]
            self.total_shares += issued
            nav += self.pending_total
            self.pending_total = 0
            per_share = nav * E // self.total_shares
            if per_share > self.high_water_mark:
                self.high_water_mark = per_share
        if not committed and not filled and not distributed:
            raise RuntimeError("Nothing")
        self.last_nav = nav
        if not recovery_only:
            self.epoch += 1
        if work:
            if not recovery_only:
                self.pay_keeper(keeper_payment, essential=True, source='processing')
            if not recovery_only or self.pending_total == 0:
                self.close_charge_era()
        elif distributed == 0:
            raise RuntimeError("Nothing")
        return work or distributed != 0

    # ------------------------------------------------------------ reporting
    def nav_now(self):
        """NAV as a checkpoint would compute it now (before flows)."""
        return self.free() + self.tracked_value + self.active_backing + self.pending_active_fees() + self.fee_credit
