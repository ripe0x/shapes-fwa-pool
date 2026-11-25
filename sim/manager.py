"""Personal-account adapter over the canonical strategy/book arithmetic in vault.py.

Only shared inventory and keeper primitives are reused. A manager owns its entire balance;
there is no pool issuance, checkpoint, refund reserve or pricing-uplift gate.
"""
from dataclasses import dataclass
from vault import Vault


@dataclass
class Manager(Vault):
    owner: str = 'owner'
    exiting: bool = False
    listing_paused: bool = False
    owner_funded: int = None
    external_gifts: int = 0
    owner_withdrawn: int = 0

    def __post_init__(self):
        if self.seed != 0:
            raise ValueError('personal managers have no dead-share seed')
        self.total_shares = 0
        self.high_water_mark = 0
        if self.owner_funded is None:
            self.owner_funded = self.balance
        if not 0 <= self.owner_funded <= self.balance:
            raise ValueError('initial owner funding cannot exceed observed balance')
        self.external_gifts += self.balance-self.owner_funded

    def sync_budget(self, now):
        # Contract budget views accrue from the last payment/settings update, not each read.
        if not hasattr(self,'_stored_routine'):
            self._stored_routine,self._stored_essential=self.routine_budget,self.essential_budget
        if now < self.budget_at:
            raise ValueError('manager time cannot precede its budget anchor')
        self._budget_now=now
        elapsed=now-self.budget_at
        self.routine_budget=min(self.routine_cap,self._stored_routine+elapsed*self.routine_rate//86400)
        self.essential_budget=min(self.essential_cap,self._stored_essential+elapsed*self.essential_rate//86400)

    def _commit_budget(self):
        self.budget_at=getattr(self,'_budget_now',self.budget_at)
        self._stored_routine,self._stored_essential=self.routine_budget,self.essential_budget

    def pay_keeper(self, amount, essential=False, cap=None, source=None):
        paid=super().pay_keeper(amount,essential,cap,source)
        self._commit_budget()
        return paid

    def set_budget(self, now, routine_cap, routine_rate, essential_cap, essential_rate):
        super().set_budget(now,routine_cap,routine_rate,essential_cap,essential_rate)
        self._commit_budget()

    def free(self):
        return self.balance

    def owed_estimate(self):
        return 0

    def idle(self):
        return max(0,self.balance-self.reserve)

    def fund(self, amount, caller='owner'):
        if amount <= 0:
            raise RuntimeError('Amount')
        self.balance += amount
        if caller == self.owner:
            self.owner_funded += amount
        else:
            self.external_gifts += amount

    def withdraw(self, amount, caller='owner'):
        if caller != self.owner:
            raise RuntimeError('Unauthorized')
        if amount < 0 or amount > self.balance:
            raise RuntimeError('InsufficientBalance')
        self.balance -= amount
        self.owner_withdrawn += amount
        return amount

    def set_exiting(self, enabled, caller='owner'):
        if caller != self.owner:
            raise RuntimeError('Unauthorized')
        self.exiting = enabled
        if enabled:
            self.listing_paused = True

    def _pool_only(self, *args, **kwargs):
        raise RuntimeError('PersonalManagerHasNoHolderAccounting')

    deposit = cancel = request_redeem = checkpoint = recover_checkpoint = _pool_only
    claim = fund_checkpoint = claim_checkpoint_refund = share_balance = _pool_only


def owner_processing_reserve(pending, single_request_gas, gas_price):
    """Conservative owner wallet reserve: batches <=16, charging each record a full measured call."""
    if pending < 0 or single_request_gas < 0 or gas_price < 0:
        raise ValueError('negative processing input')
    return (pending+15)//16, pending*single_request_gas*gas_price
