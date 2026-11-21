#!/usr/bin/env python3
"""Prospective quote context: exact EIP1559 arithmetic and real read-only Anvil execution.

No wallet is funded, no transaction is sent, and no contract is deployed. eth_call's creation
simulation executes BASEFEE directly; it is not a replacement for a production contract test.
"""
import argparse
import json

import keeper as K
import policy as P
from tx import StaleContext, next_base_fee


def arithmetic():
    h = lambda base, used, limit=20: dict(baseFeePerGas=hex(base), gasUsed=hex(used), gasLimit=hex(limit))
    assert next_base_fee(h(1000, 10)) == 1000
    assert next_base_fee(h(1000, 0)) == 875
    assert next_base_fee(h(1000, 20)) == 1125
    assert next_base_fee(h(1, 11)) == 2  # positive drift has a minimum1wei increment
    assert next_base_fee(h(1, 9)) == 1   # negative drift rounds down without that minimum
    assert next_base_fee(h(1000, 9, 21)) == 988  # floor(gasLimit/2), then division at each step
    # Backing depends on the routine gas ceiling, never on the block's basefee (D80): a head
    # basefee change between quote and inclusion cannot move the target outside the tag band.
    kwargs = dict(k=1_038_500_000_000_000_000, cap=None, s_bps=100, units=6,
                  gas_ceiling=500_000_000, markup_bps=0, work_fee=20_000_000_000_000)
    old = P.edge_backing(price=500_000_000, **kwargs)
    future = P.edge_backing(price=443_750_000, **kwargs)
    assert old == future == 65_158_469_945_350_000, (old, future)
    proposals = P.propose_backings(future, 0, 1, lambda _: False)
    assert abs(proposals[0] - future) <= 10_000
    print("inclusion arithmetic: EIP1559 roundings pass; backing target is basefee-independent")


def live_read_only(endpoint):
    K.RPC = endpoint
    parent, future = K.inclusion_context()
    print(json.dumps(dict(test="actual explicit-fee pending BASEFEE", endpoint=endpoint,
                          parent=K.quantity(parent["number"]), parent_basefee=K.quantity(parent["baseFeePerGas"]),
                          verified_pending_basefee=future, broadcasts=0)))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rpc", help="read-only probe on an existing endpoint; creates no node")
    parser.add_argument("--tenderly", action="store_true", help="also verify exact explicit-fee keeper probe on real mainnet read-only")
    args = parser.parse_args()
    arithmetic()
    if args.rpc:
        live_read_only(args.rpc)
    if args.tenderly:
        K.RPC = "https://mainnet.gateway.tenderly.co"
        parent, future = K.inclusion_context()
        print(json.dumps(dict(test="Tenderly exact keeper explicit-fee probe", parent=K.quantity(parent["number"]),
                              head_basefee=K.quantity(parent["baseFeePerGas"]), verified_pending_basefee=future,
                              funded_wallets=0, broadcasts=0)))
