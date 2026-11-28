"""Pure ABI, quote and bounded-work regressions; real execution is covered by fork receipts."""
import json
from pathlib import Path
from config import PARAMS_T, GAS_FIELDS, params_values, tuple_arg, decode_params, configuration_hash, gas_schedule
from policy import State, Q, quote, payment, build_cost, scan_proof, scan_vault, MAX_SCAN, plan
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
    assert build_units_for(0) == (0, None) and build_units_for(8) == (3, None)
    mix = 1 << 3 | 1 << 5 | 1 << 10
    design = 4 << 24 | 2 << 40 | 1 << 80  # four 0.03, two 0.05, one 0.10 ETH packs
    assert build_units_for(mix, design, {}) == (3, 4)
    assert build_units_for(mix, design, {3: 3}) == (5, 2), "furthest below its count first"
    assert build_units_for(mix, design, {3: 3, 5: 1}) == (3, 1), "a tie builds the smaller size"
    assert build_units_for(mix, design, {3: 4, 5: 2}) == (10, 1)
    assert build_units_for(mix, design, {3: 5, 5: 2, 10: 1}) == (0, 0), "an over-count size never builds"
    assert build_units_for(1 << 3, design, {}) == (3, 4), "a size the mask refuses is skipped"
    assert to_cast(('build', 3, [21 * 10**16]), expected=h)[-1] == h
    assert to_cast(('checkpoint',7),caller_funded=True)==['recoverCheckpoint(uint256)',7]
    assert to_cast(('sync', [1], 1), expected=h, caller_funded=True) == ['recover(uint256[],uint256)', '[1]', 1]
    args = dict(now=0, gas_price=200_000_000, base_fee=150_000_000, gas_ceiling=500_000_000,
                max_tip=50_000_000, share_bps=2500, k=10**18, backing=0,
                min_edge_bps=100, mint_fee=10**15, settlement_window=3600, blackout=False,
                queue_drained=True, checkpoint_done_this_interval=False)
    s = State(**args, gas_schedule=gas_schedule(values))
    # One basis for quote and pay: measured gas x price plus flat service fees (no markup, V1).
    assert quote(s, 100_000, 2) == 40_000_000_000_000
    s.work_fee = 20_000_000_000_000
    assert quote(s, 100_000, 2) == 80_000_000_000_000
    assert quote(s, 100_000, 2, True) == 80_000_000_000_000
    # 140k compensated gas at0.1gwei plus two20e12workfees.
    assert payment(s,100_000,2,measured_gas=40_000,tx_gas_price=100_000_000)==54_000_000_000_000
    assert payment(s,100_000,2,measured_gas=200_000,tx_gas_price=10**9)==80_000_000_000_000
    assert payment(s,0,measured_gas=10**9)==0 and quote(s,0)==0
    oldpay=payment(s,100_000,2,measured_gas=40_000)
    oldquote=quote(s,100_000,2)
    s.gas_schedule=s.gas_schedule|{'overhead':110_000}
    assert payment(s,100_000,2,measured_gas=40_000)-oldpay==2_000_000_000_000
    assert quote(s,100_000,2)-oldquote==2_000_000_000_000
    s.backing = 21 * 10**16
    s.k = 1_038_500_000_000_000_000
    s.free = s.idle_eth = 10**18
    s.pack_units_mask = 0
    s.build_units = 0
    s.idle_packs, s.relistable_idle = 2, 1
    s.backing_proposals = [21 * 10**16]
    assert ('list', [21 * 10**16]) in plan(s), 'ordinary top pack is reusable with fresh mints disabled'
    s.relistable_idle = 0
    assert not any(step[0] in ('list', 'build', 'renew') for step in plan(s))
    s.pack_units_mask, s.build_units = 8, 3
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
    assert build_cost(s) - old == 2_000_000_000_000
    s.open_positions, s.completed_prefix = MAX_SCAN + 1, 10**9
    s.gas_schedule = Q | {'scan': 0, 'journal': 2**32 - 1}
    assert not scan_proof(s) and not scan_vault(s)
    try:
        to_cast(('renew',[1],[21*10**16],[]),expected=h)
        raise AssertionError('retired fresh-remint operation still exposed')
    except ValueError:
        pass
    assert 'renewalMode' not in values and 'renewalFloatCount' not in values
    print('keeper/test_config.py: pass (full nested ABI, configuration guards, account quotes, hard scan bound)')


if __name__ == '__main__':
    main()
