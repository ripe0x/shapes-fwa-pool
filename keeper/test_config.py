"""Pure ABI, quote and bounded-work regressions; real execution is covered by fork receipts."""
import json
from pathlib import Path
from config import PARAMS_T, GAS_FIELDS, params_values, tuple_arg, decode_params, configuration_hash, gas_schedule
from policy import State, Q, quote, build_cost, scan_proof, scan_vault, MAX_SCAN, plan
from keeper import build_units_for, to_cast, validate_configuration_context, wallet_debit_bound
from tx import StaleContext


def main():
    values = json.loads((Path(__file__).resolve().parent.parent / 'deploy/mainnet.json').read_text())
    assert decode_params(tuple_arg(values)) == {k: values[k] for k in decode_params(tuple_arg(values))}
    assert len(params_values(values)[-1]) == len(GAS_FIELDS)
    h = configuration_hash(values, 10**15)
    validate_configuration_context(h, h)
    try:
        validate_configuration_context(h, configuration_hash(values, 10**15 + 1))
        raise AssertionError('mixed configuration context accepted')
    except StaleContext:
        pass
    assert h != configuration_hash(values, 10**15 + 1)
    assert h != configuration_hash(values, 10**15, True)
    for field in GAS_FIELDS:
        changed = values | {'gasSchedule': values['gasSchedule'] | {field: values['gasSchedule'][field] + 1}}
        assert h != configuration_hash(changed, 10**15), field
    assert wallet_debit_bound(100, 2, 1, 7) == 632
    assert wallet_debit_bound(101, 2, 1, 7) > 632  # signed minPay calldata changes its estimate
    assert build_units_for(0) == 0 and build_units_for(8) == 3
    assert to_cast(('build', 3, [21 * 10**16]), expected=h)[-1] == h
    assert to_cast(('checkpoint',7),caller_funded=True)==['recoverCheckpoint(uint256)',7]
    assert to_cast(('sync', [1], 1), expected=h, caller_funded=True) == ['recover(uint256[],uint256)', '[1]', 1]
    args = dict(now=0, gas_price=200_000_000, base_fee=150_000_000, gas_ceiling=500_000_000,
                max_tip=50_000_000, markup_bps=1000, share_bps=2500, k=10**18, backing=0,
                min_edge_bps=100, mint_fee=10**15, settlement_window=3600, blackout=False,
                queue_drained=True, checkpoint_done_this_interval=False)
    s = State(**args, gas_schedule=gas_schedule(values))
    # One basis for quote and pay: markup applies to routine gas, never to flat service fees.
    assert quote(s, 100_000, 2) == 22_000_000_000_000
    s.work_fee = 20_000_000_000_000
    assert quote(s, 100_000, 2) == 62_000_000_000_000
    assert quote(s, 100_000, 2, True) == 60_000_000_000_000
    s.backing = 21 * 10**16
    s.k = 1_038_500_000_000_000_000
    s.free = s.idle_eth = 10**18
    s.pack_units_mask = 0
    s.build_units = 0
    s.idle_packs, s.relistable_idle, s.renewal_eligible = 2, 1, 1
    s.backing_proposals = [21 * 10**16]
    assert ('list', [21 * 10**16]) in plan(s), 'ordinary top pack is reusable with fresh mints disabled'
    s.relistable_idle = 0
    assert not any(step[0] in ('list', 'build', 'renew') for step in plan(s))
    s.pack_units_mask, s.build_units = 8, 3
    s.renewal_pack_ids, s.renewal_proposals = [1], [21 * 10**16]
    s.mint_fee = s.accepted_mint_fee + 1
    assert not any(step[0] in ('renew', 'build') for step in plan(s))
    s.mint_fee = 10**15
    s.blackout=s.queue_drained=s.checkpoint_done_this_interval=s.caller_funded_exit=True
    s.locked_shares=1
    assert ('checkpoint',s.witness_id) in plan(s), 'unpaid redemption pricing remains available after a normal checkpoint in the same window'
    s.locked_shares=0
    s.caller_funded_exit=False
    old = build_cost(s)
    s.gas_schedule = s.gas_schedule | {'build': s.gas_schedule['build'] + 10_000}
    assert build_cost(s) - old == 2_200_000_000_000
    s.open_positions, s.completed_prefix = MAX_SCAN + 1, 10**9
    s.gas_schedule = Q | {'scan': 0, 'journal': 2**32 - 1}
    assert not scan_proof(s) and not scan_vault(s)
    from policy import Listing,ACTIVE,MAX_BATCH
    from dataclasses import replace
    renewal=State(**(args|{'k':1_038_500_000_000_000_000,'backing':21*10**16,'markup_bps':0}),gas_schedule=gas_schedule(values),
        free=205*10**15,operating_reserve=5*10**15,renewal_eligible=1,renewal_pack_ids=[7],
        renewal_proposals=[21*10**16],renewal_pack_values=[3*10**16],renewal_pack_shapes=[3],
        listings=[Listing(99,ACTIVE,pending_fees=10**16),Listing(1,ACTIVE,pending_fees=5*10**15)])
    step=next(step for step in plan(renewal) if step[0]=='renew')
    assert step[3]==[1,99] and to_cast(step,expected=h)[3]=='[1,99]'
    assert len(step[3])<=MAX_BATCH['harvest']
    one_claim=replace(renewal,free=21*10**16,routine_budget=520*10**12,
        listings=[Listing(1,ACTIVE,pending_fees=1),Listing(99,ACTIVE,pending_fees=10**16)])
    chosen=next(job for job in plan(one_claim) if job[0]=='renew')
    assert chosen[3]==[99], 'one sufficient claim must not drag a low-ID dust claim into a two-claim budget failure'
    fallback=replace(renewal,free=5*10**17,idle_eth=45*10**16,routine_budget=3*10**14,
        idle_packs=2,relistable_idle=1,backing_proposals=[42*10**16],listings=[])
    assert ('list',[42*10**16]) in plan(fallback), 'waiting fresh renewal must preserve the ordinary legacy target'
    assert not any(job[0]=='renew' for job in plan(fallback))
    import sys
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent/'sim'))
    from vault import Vault,Position
    mirror=Vault(seed=0,balance=renewal.free,reserve=renewal.operating_reserve,routine_budget=10**18)
    mirror.positions={l.id:Position(3,l.backing,pending_fees=l.pending_fees) for l in renewal.listings}
    q=renewal.gas_schedule
    gas=q['build']+q['build_pack']+3*q['build_shape']+q['listed']+q['liquidate']+q['liq_pack']+3*q['redeem_shape']
    funded=mirror.renewal_fee_plan(step[3],0,gas,3,243*10**15,lambda g,u:quote(renewal,g,u),2500,
        q['sync_funding'],q['harvested'],q['sync_credit'],cash_delta=3*10**16)
    assert funded[2]==[1,99], 'ascending bounded prefix still collects both needed real-fee input amounts'
    print('keeper/test_config.py: pass (full nested ABI, configuration guards, account quotes, hard scan bound)')


if __name__ == '__main__':
    main()
