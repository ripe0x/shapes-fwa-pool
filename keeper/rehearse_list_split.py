#!/usr/bin/env python3
"""Real billed singleton/batch comparison inside the approved fork's existing vault snapshot."""
import json

import measure_gas as M
import rehearse_canary as R


def exercise():
    R.B.load_manifest()
    baseline = R.B.rpc("evm_snapshot")
    try:
        shares = R.num(R.call(R.VAULT, "shareBalance(address)(uint256)", R.HOLDER)) // 5
        if not shares:
            raise RuntimeError("split calibration requires the real canary holder")
        R.send(R.HOLDER, R.VAULT, "requestRedeem(uint256)", shares, value=R.redeem_charge(shares))
        R.send(R.KEEPER, R.VAULT, "unlist(uint256[],uint256)", M.array(R.ids()[:8]), 0)
        R.send(R.KEEPER, R.VAULT, "liquidate(uint256,uint256)", 8, 0)
        R.warp_to(42360)
        R.send(R.KEEPER, R.VAULT, "checkpoint(uint256,uint256)", M.witness(), 0)
        R.send(R.HOLDER2, R.VAULT, "deposit()", value=3 * 10**17 + R.num(R.call(R.VAULT, "requestCharge()(uint256)")))
        R.warp_to(42360)
        R.send(R.KEEPER, R.VAULT, "checkpoint(uint256,uint256)", M.witness(), 0)
        R.warp_to(60)
        R.send(R.KEEPER, R.VAULT, "restock(uint256,uint256[],uint256)", 3, M.quote(3, 3, True), 0)
        inventory_count = R.num(R.call(R.VAULT, "idlePackCount()(uint256)"))
        if inventory_count < 3:
            raise RuntimeError("split comparison requires three actual idle packs")
        comparison = R.B.rpc("evm_snapshot")
        before = len(M.rows)
        # The empty parent makes the authentic next header exactly .15gwei. Every included
        # call then has the same .2gwei effective price, quote price, and routine work fee.
        def list_count(count, label):
            R.B.rpc("anvil_setNextBlockBaseFeePerGas", hex(171_428_571))
            R.B.rpc("evm_mine")
            M.tx(label, "list(uint256[],uint256)", M.quote(3, count), 0, require_paid=True, items=count)
            row = M.rows[-1]
            if row["basefee_wei"] != 150_000_000 or row["effective_price_wei"] != 200_000_000:
                raise RuntimeError(f"split comparison price context moved: {row}")
        list_count(3, "split comparison batch3")
        if not R.B.rpc("evm_revert", comparison):
            raise RuntimeError("split comparison branch restore failed")
        for i in range(3):
            list_count(1, f"split comparison singleton{i + 1}")
        rows = M.rows[before:]
        extra_gas = sum(row["gas"] for row in rows[1:]) - rows[0]["gas"]
        extra_pay = sum(row["keeper_paid_wei"] for row in rows[1:]) - rows[0]["keeper_paid_wei"]
        result = dict(rows=rows, starting_idle_count=inventory_count, extra_billed_gas=extra_gas, extra_keeper_pay_wei=extra_pay,
                      extra_billed_cost_wei=extra_gas * 200_000_000,
                      max_base_quote_at_10percent_markup=extra_gas * 10_000 // (2 * 11_000),
                      q300k_extra_envelope_wei=2 * 300_000 * 200_000_000 * 11_000 // 10_000)
        print(json.dumps(result, indent=2), flush=True)
        R.B.append_action(dict(operation="actual list splitting calibration", result=result))
        return result
    finally:
        if not R.B.rpc("evm_revert", baseline):
            raise RuntimeError("split calibration failed to restore original canary branch")
