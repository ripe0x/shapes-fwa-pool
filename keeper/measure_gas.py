#!/usr/bin/env python3
"""Local-only production artifact gas calibration, run via owner-approved rehearsal_batch.py.

The12ETH calibration values preserve canary budgets and add allowed30-unit packs for stress
measurements. Every call uses real counterparties. Successful VRF selections, fee-bearing active
harvest and expiry settlements need recorded Forge replay; they are explicit local coverage gaps.
"""
import json
from types import SimpleNamespace
from pathlib import Path

import policy
import tx as T
import rehearse_canary as R

OUT = R.ROOT / "sim/out/gas-quotes-incremental.json"
rows = []


def tx(label, sig, *args, frm=None, value=None, require_paid=False, **meta):
    before = R.num(R.cast("block-number"))
    R.send(frm or R.KEEPER, R.VAULT, sig, *args, value=value)
    block = json.loads(R.cast("rpc", "eth_getBlockByNumber", "latest", "true"))
    if R.num(block["number"]) <= before or len(block["transactions"]) != 1:
        raise RuntimeError("measurement did not produce exactly one isolated transaction block")
    transaction = block["transactions"][0]
    receipt = json.loads(R.cast("rpc", "eth_getTransactionReceipt", transaction["hash"]))
    gas = R.num(receipt["gasUsed"])
    limit = R.num(transaction["gas"])
    if limit > R.B.MAX_GAS or (gas * 5 + 3) // 4 > R.B.MAX_GAS:
        raise RuntimeError("complete operation plus25% margin exceeds EIP7825")
    paid = sum(int(log["data"], 16) for log in receipt["logs"]
               if log.get("topics") and log["topics"][0].lower() == T.KEEPER_PAID
               and log["address"].lower() == R.VAULT.lower())
    if require_paid and paid <= 0:
        raise RuntimeError("funded routine calibration did not execute positive keeper payment")
    row = dict(label=label, sig=sig, gas=gas, keeper_paid_wei=paid, gas_limit=limit, gas_margin=(gas * 5 + 3) // 4,
               basefee_wei=R.num(block["baseFeePerGas"]), effective_price_wei=R.num(receipt["effectiveGasPrice"]),
               block=R.num(block["number"]), transaction=transaction["hash"], **meta)
    rows.append(row)
    print(json.dumps(row), flush=True)
    return gas


def array(xs):
    return "[" + ",".join(map(str, xs)) + "]"


def quote(units, count, build=False):
    output = R.pricing(R.VAULT, "edge(uint256)(uint256,uint256,bool)", units).splitlines()
    k, target = R.num(output[0]), R.num(output[1])
    if output[2] != "true" or not target:
        raise RuntimeError("calibration regime has no economically admissible backing quote")
    configured = R.B.values(calibration=True)
    base, _ = R.B.pending_fees()
    context = SimpleNamespace(k=k, base_fee=base, max_tip=configured["maxTipWei"],
                              gas_ceiling=configured["gasCeilingWei"], markup_bps=configured["payMarkupBps"],
                              work_fee=configured["workFeeWei"])
    value = units * policy.UNIT
    fee = R.num(R.call(R.FWA, "ownerSettlementFeeBps()(uint256)"))
    discount = R.num(R.call(R.FWA, "settlementDiscountBps()(uint256)"))
    up = lambda a, b: -(-a // b)
    minimum = max(up(value * 10000, 9500), up(value * 10000, 10000 - fee), up(value * 10000, discount),
                  up(value * 10**18, k - fee * 10**14))
    cycle = policy.quote(context, policy.CYCLE_GAS, 2)
    build_cost = (policy.quote(context, policy.Q["pack"] + max(units - 3, 0) * policy.Q["pack_unit"]
                  + policy.Q["mint"] * units // 10 + policy.Q["listed"], 2)
                  + R.num(R.call(R.VALUES["shapes"], "mintFee()(uint256)")) * units // 10)
    minimum = max(minimum, up((cycle + (build_cost if build else 1)) * 10**18, k - 10**18))
    maximum = 2**256 - 1
    if R.call(R.FWA, "oracleExemptCollections(address)(bool)", R.PACKS) != "true":
        oracle = R.call(R.FWA, "floorOracle()(address)")
        ask = R.num(R.cast("call", oracle, "getFloorRange(address)(uint256,uint256,uint48,uint48)", R.PACKS).splitlines()[1])
        maximum = ask * (10000 + R.num(R.call(R.FWA, "oracleCeilingPremiumBps()(uint256)"))) // 10000
        maximum = maximum * (10000 - configured["bufferBps"]) // 10000
    reserved = R.num(R.call(R.VAULT, "reservedCount()(uint256)"))
    occupied = lambda b: bool(R.num(R.call(R.VAULT, "idForBacking(uint256)(uint256)", b)))
    result = policy.propose_backings(target, reserved, 1 if build else count, occupied, minimum, maximum)
    if build and result:
        result *= count
    if len(result) != count:
        raise RuntimeError("bounded identifier proposal batch incomplete")
    return array(result)


def witness():
    # Fixture-only independent enumeration, never the production keeper path.
    ids = R.ids()
    if not ids:
        return 0
    return min(ids, key=lambda id_: R.num(R.cast("call", R.FWA,
               "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", id_).splitlines()[7]))


def journal():
    for _ in range(128):
        cursor = R.num(R.call(R.VAULT, "acquisitionCursor()(uint64)"))
        prefix = R.num(R.call(R.FWA, "nextSequenceToProcess()(uint64)"))
        if cursor == prefix:
            return
        n = min(128, prefix - cursor)
        tx(f"completed global prefix{n}", "sync(uint256[],uint256,uint256)", "[]", 0, 0,
           entries=n, require_paid=False, winding_down=False, locked_shares=0)
        if R.num(R.call(R.VAULT, "acquisitionCursor()(uint64)")) != cursor + n:
            raise RuntimeError("journal receipt did not advance exactly its verified entry count")
    raise RuntimeError("bounded journal calibration did not catch up")


def drain_queue():
    R.expire_queue()


def refunded_prefix(count, basefee):
    R.warp_to(60)
    R.cast("rpc", "anvil_setNextBlockBaseFeePerGas", hex(basefee))
    R.cast("rpc", "evm_mine")
    first = R.num(R.call(R.FWA, "lastIssuedSequence()(uint64)")) + 1
    remaining = count
    for _ in range(16):
        if not remaining:
            break
        allowed = 1  # deployed batch cap is internal; one genuine request is always within it
        price = R.num(R.pricing(R.FWA, "quoteAcquisitionPrice()(uint256,uint256,uint256)").splitlines()[2])
        if price * allowed > 2 * 10**18:
            raise RuntimeError("foreign request batch exceeds2ETH temporary acquisition escrow")
        R.send(R.KICKER, R.FWA, "acquire(address,uint256,uint256,uint256,uint256)",
               R.KICKER, allowed, 0, 0, 10000, value=price * allowed)
        remaining -= allowed
    if remaining:
        raise RuntimeError("request fixture exceeds16 external calls")
    R.expire_queue()
    # Authenticate actual terminal statuses. No fulfilled success is supplied or imitated.
    for sequence in range(first, first + count):
        request = R.num(R.call(R.FWA, "requestIdAtSequence(uint64)(uint256)", sequence))
        status = R.num(R.cast("call", R.FWA, "acquisitions(uint256)(address,uint256,uint256,uint256,uint8)", request).splitlines()[-1])
        if status not in (3, 4):
            raise RuntimeError(f"real request did not refund/expire: {request} status{status}")
    R.cast("rpc", "anvil_setNextBlockBaseFeePerGas", hex(basefee))
    R.cast("rpc", "evm_mine")
    journal()
    R.send(R.KICKER, R.FWA, "withdrawAcquisitionRefund()")


def report(values, gaps):
    data = dict(fork_block=R.B.FORK_BLOCK, values=values, rows=rows,
                limits=dict(transaction_gas=R.B.MAX_GAS, runtime_bytes=R.B.CODE_SIZE), gaps=gaps)
    OUT.write_text(json.dumps(data, indent=2) + "\n")
    print(f"wrote{OUT}; coverage gaps are explicit, not passing measurements", flush=True)


def main():
    R.B.load_manifest()
    for actor in R.B.ACTORS.values():
        R.impersonate(actor)
    values = R.B.values(calibration=True)
    R.VAULT = R.B.deploy(values, "calibration")
    R.TOKEN = R.call(R.FWA, "token()(address)")
    initial = json.loads(R.cast("rpc", "evm_snapshot"))
    refunded_prefix(1, 150_000_000)
    rows[-1]["regime"] = "startup before holder flows"
    if not json.loads(R.cast("rpc", "evm_revert", initial)):
        raise RuntimeError("could not restore fresh deployment after startup metric")
    drain_queue()
    journal()
    ck = R.num(R.call(R.VAULT, "requestCharge()(uint256)"))
    # 11.99ETH escrow +0.01ETH dead-share seed. Two actors each send less than6ETH.
    R.send(R.HOLDER, R.VAULT, "deposit()", value=5_995_000_000_000_000_000 + ck)
    R.send(R.HOLDER2, R.VAULT, "deposit()", value=5_995_000_000_000_000_000)
    R.warp_to(42360)
    tx("checkpoint two deposits, zero positions", "checkpoint(uint256,uint256)", 0, 0)

    # Successful foreign selections require recorded proof replay. Local honest expiration still
    # exercises both size1 and size16 new global records that return no backing to this vault.
    refunded_prefix(1, 150_000_000)
    refunded_prefix(16, 150_000_000)
    refunded_prefix(16, 1_000_000_000)
    R.calm()
    R.warp_to(60)
    snapshot = json.loads(R.cast("rpc", "evm_snapshot"))
    tx("restock10 x3units", "restock(uint256,uint256[],uint256)", 3, quote(3, 10, True), 0,
       requested_packs=10, total_units=30)
    if not json.loads(R.cast("rpc", "evm_revert", snapshot)):
        raise RuntimeError("could not restore calibration cash branch")

    # The real oracle authority admits the largest supported denomination for this stress regime.
    oracle = R.call(R.FWA, "floorOracle()(address)")
    owner = R.call(oracle, "owner()(address)")
    if oracle.lower() != R.B.ORACLE.lower() or owner.lower() != R.B.ORACLE_OWNER.lower():
        raise RuntimeError("oracle test authority changed")
    if R.cast("code", owner) != "0x":
        # The named oracle owner is a real contract. An EOA impersonation would bypass its real
        # authorization path, and introducing its controller is outside the approved signer set.
        for count in (10, 6):
            tx(f"restock{count} x3units for bounded ordinary fixture", "restock(uint256,uint256[],uint256)",
               3, quote(3, count, True), 0, total_units=count * 3)
        for number in range(2):
            tx(f"list8 x3units ({number + 1}/2)", "list(uint256[],uint256)", quote(3, 8), 0,
               items=8, pack_units=3)
        listed = R.ids()
        if len(listed) != 16:
            raise RuntimeError("ordinary fixture did not create16 actual active listings")
        R.send(R.OWNER, R.VAULT, "startWindDown()")
        R.warp_to(60)
        R.warp_to(42360)
        R.warp_to(60)
        R.warp_to(42360)
        tx("unlist16 x3units", "unlist(uint256[],uint256)", array(listed), 0, items=16, pack_units=3)
        tx("liquidate max16, ordinary units cap30", "liquidate(uint256,uint256)", 16, 0,
           requested_items=16, maximum_complete_units=30)
        report(values, ["Oracle owner0x930634... is a3451-byte contract. Its controller is outside approved signer set; no EOA impersonation or oracle write was used.",
                        "Largest30unit admission/kicks/terminal sync require the real oracle admin path; supported Forge owner-call regimes remain separate evidence.",
                        "Successful foreign/own selections, fee-bearing harvest, allocation pruning and kept-gift recovery require recorded Forge replay."])
        return
    R.impersonate(owner)
    R.send(owner, oracle, "setFloor(address,uint256)", R.PACKS, 330_000_000_000_000_000)
    for i in range(16):
        tx(f"restock1 x30units ({i + 1}/16)", "restock(uint256,uint256[],uint256)", 30, quote(30, 1, True), 0,
           requested_packs=1, total_units=30)
    for number in range(2):
        tx(f"list8 x30units ({number + 1}/2)", "list(uint256[],uint256)", quote(30, 8), 0,
           items=8, pack_units=30)
    listed = R.ids()
    if len(listed) != 16:
        raise RuntimeError("largest-size listing fixture did not create16 real active positions")
    R.send(R.OWNER, R.VAULT, "startWindDown()")
    R.warp_to(60)
    R.warp_to(42360)
    R.warp_to(60)
    R.warp_to(42360)  # every crown lock is older than12hours
    snap = json.loads(R.cast("rpc", "evm_snapshot"))
    tx("unlist16 x30units", "unlist(uint256[],uint256)", array(listed), 0, items=16, pack_units=30)
    tx("liquidate max16, units cap30", "liquidate(uint256,uint256)", 16, 0,
       requested_items=16, maximum_complete_units=30)
    if not json.loads(R.cast("rpc", "evm_revert", snap)):
        raise RuntimeError("could not restore kick measurement branch")
    R.send(owner, oracle, "setFloor(address,uint256)", R.PACKS, 30_000_000_000_000_000)
    for id_ in listed:
        R.send(R.KICKER, R.FWA, "kickListing(uint256)", id_)
    tx("terminal kick sync16", "sync(uint256[],uint256,uint256)", array(listed), 0, 0, items=16)
    report(values, ["Successful foreign and own selections/settlements need recorded Forge VRF replay.",
                    "Fee-bearing active harvest16, allocation prune16, and token claim16 need their real replay fixtures.",
                    "Oversized kept-gift recovery needs a real selected keep path; no local VRF proof is manufactured."])


if __name__ == "__main__":
    main()
