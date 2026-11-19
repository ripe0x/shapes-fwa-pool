#!/usr/bin/env python3
"""Reproducible local receipt measurements for construction and listing.

Starts and owns an Anvil process. It cannot broadcast to an external endpoint.
Uses the normal DeployCore path, real forked counterparties, fresh funded test
actors, fixed prices, exact minPay calldata, and ordinary keeper profitability.
The pinned current snapshot has the real oracle exemption for shape packs.
No oracle, protocol configuration, or counterparty balance is modified.
"""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

from eth_abi import encode, decode
from eth_utils import keccak, to_checksum_address

import keeper as K
import policy

ROOT = Path(__file__).resolve().parents[1]
RPC = "http://127.0.0.1:8561"
FORK = "https://mainnet.gateway.tenderly.co"
BLOCK = 26_446_755
LIMIT = 16_777_216
E = 10**18
OUT = ROOT / "docs/receipts/complete-cost-receipts.json"
REPORT = {"scope": "owned local Anvil; no public transactions", "fork": BLOCK,
          "rpc_source": FORK, "rows": [], "unreachable": [], "status": "running"}
PRICE = 200_000_000
PROFILE = os.environ.get("COMPLETE_COST_PROFILE", "all")


def rpc(method, *params):
    request = urllib.request.Request(RPC, json.dumps(dict(jsonrpc="2.0", id=1,
        method=method, params=params)).encode(), {"Content-Type": "application/json"})
    result = json.loads(urllib.request.urlopen(request, timeout=180).read())
    if "error" in result:
        raise RuntimeError(json.dumps(result["error"]))
    return result["result"]


def data(sig, types=(), args=()):
    return "0x" + (keccak(text=sig)[:4] + encode(types, args)).hex()


def read(to, sig, outputs=("uint256",), types=(), args=(), sender=None):
    tx = {"to": to, "data": data(sig, types, args), "gasPrice": hex(PRICE)}
    if sender:
        tx["from"] = sender
    return decode(outputs, bytes.fromhex(rpc("eth_call", tx, "pending")[2:]))


def save():
    OUT.write_text(json.dumps(REPORT, indent=2) + "\n")


def fee():
    rpc("anvil_setNextBlockBaseFeePerGas", hex(PRICE - 50_000_000))


def send(sender, to, sig="", types=(), args=(), value=0, label="setup", measure=False):
    fee()
    tx = dict(**{"from": sender, "to": to}, data=data(sig, types, args) if sig else "0x",
              value=hex(value), gasPrice=hex(PRICE))
    offer = None
    if measure:
        offer = decode(["uint256"], bytes.fromhex(rpc("eth_call", tx, "pending")[2:]))[0]
        args = tuple(args[:-1]) + (offer * 8 // 10,)
        tx["data"] = data(sig, types, args)
    estimate = int(rpc("eth_estimateGas", tx, "pending"), 16)
    padded = (estimate * 5 + 3) // 4
    assert padded <= LIMIT, (label, estimate, padded)
    tx["gas"] = hex(padded)
    balance = int(rpc("eth_getBalance", sender, "latest"), 16)
    h = rpc("eth_sendTransaction", tx)
    REPORT["inflight"] = dict(label=label, hash=h, transaction=tx)
    save()
    receipt = None
    for _ in range(600):
        receipt = rpc("eth_getTransactionReceipt", h)
        if receipt:
            break
        time.sleep(.1)
    assert receipt and int(receipt["status"], 16) == 1, (label, receipt)
    gas = int(receipt["gasUsed"], 16)
    actual_price = int(receipt["effectiveGasPrice"], 16)
    assert actual_price == PRICE
    block = rpc("eth_getBlockByNumber", receipt["blockNumber"], False)
    assert int(block["baseFeePerGas"], 16) == PRICE - 50_000_000
    paid = sum(int(x["data"], 16) for x in receipt["logs"]
               if x.get("topics") and x["topics"][0] == K.txm.KEEPER_PAID
               and x["address"].lower() == to.lower())
    row = dict(label=label, function=sig, arguments=args, value_wei=value,
               price_wei=PRICE, estimate=estimate, gas_limit=padded, billed_gas=gas,
               paid_wei=paid, cost_wei=gas*PRICE, receipt=receipt)
    if measure:
        op = sig.split("(")[0]
        cost, need, accepted = K.profitability_gate(estimate, PRICE, offer, 0, 0, 0,
                                                  K.BILLED_PER_ESTIMATE[op])
        row.update(ordinary_offer_wei=offer, exact_minPay=args[-1],
                   ordinary_expected_cost_wei=cost, ordinary_preflight=accepted,
                   keeper_net_wei=paid-gas*PRICE,
                   keeper_balance_delta_wei=int(rpc("eth_getBalance", sender, "latest"), 16)-balance)
        assert paid == offer
        assert row["keeper_balance_delta_wei"] == paid-gas*PRICE
    REPORT["rows"].append(row)
    REPORT.pop("inflight", None)
    save()
    print(json.dumps({k: row[k] for k in ("label", "billed_gas", "paid_wei", "price_wei")}), flush=True)
    return row


def proposals(vault, units, count, build):
    fee()
    _, target, ok = read(vault, "edge(uint256)", ("uint256", "uint256", "bool"), ["uint256"], [units])
    if not ok:
        raise RuntimeError("live edge gate is closed")
    base = (target + 9_999) // 10_000 * 10_000
    values = []
    for i in range(count):
        for offset in range(100):
            value = base - offset * 10_000
            if value in values or read(vault, "idForBacking(uint256)", types=["uint256"], args=[value])[0]:
                continue
            values.append(value)
            break
    if build:
        values = [values[0]] * count
    assert len(values) == count
    return values


def stock(vault, keeper, label, units, count):
    before_count = read(vault, "idlePackCount()")[0]
    before_loose = read(vault, "looseShapeCount()")[0]
    shapes = read(vault, "shapes()", ["address"])[0]
    sf = read(shapes, "feeRecipient()", ["address"])[0]
    owed = read(shapes, "feesOwedTo(address)", types=["address"], args=[sf])[0]
    backing = read(shapes, "redeemableBacking()")[0]
    mints = max(0, units*count-before_loose+9)//10
    row = send(keeper, vault, "restock(uint256,uint256[],uint256)",
               ["uint256", "uint256[]", "uint256"], [units, proposals(vault, units, count, True), 0],
               label=label, measure=True)
    assert read(vault, "idlePackCount()")[0] == before_count+count
    assert read(shapes, "feesOwedTo(address)", types=["address"], args=[sf])[0]-owed == mints*10**15
    assert read(shapes, "redeemableBacking()")[0]-backing == mints*10**17
    row.update(primary_mints=mints, creator_mint_fees_wei=mints*10**15,
               loose_shapes_before=before_loose, units=units, packs=count)
    save()


def main():
    global PRICE
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 8561))
    source = {p: hashlib.sha256((ROOT/p).read_bytes()).hexdigest()
              for p in ["src/PackVault.sol", "src/VaultLib.sol", "src/KeeperPolicy.sol", "keeper/policy.py", "keeper/keeper.py"]}
    REPORT["source_sha256"] = source
    REPORT["profile"] = PROFILE
    work = Path(tempfile.mkdtemp(prefix="complete-cost-"))
    REPORT["work_directory"] = str(work)
    node = subprocess.Popen(["anvil", "--host", "127.0.0.1", "--port", "8561", "--accounts", "0",
        "--silent", "--fork-url", FORK, "--fork-block-number", str(BLOCK), "--retries", "30",
        "--fork-retry-backoff", "5000", "--base-fee", "150000000", "--gas-limit", str(LIMIT),
        "--code-size-limit", "24576", "--enable-tx-gas-limit"], stdout=open(work/"anvil.log", "w"), stderr=subprocess.STDOUT)
    try:
        for _ in range(120):
            try:
                assert "anvil" in rpc("web3_clientVersion").lower()
                break
            except Exception:
                assert node.poll() is None
                time.sleep(.5)
        assert int(rpc("eth_blockNumber"), 16) == BLOCK
        REPORT["fork_block_hash"] = rpc("eth_getBlockByNumber", hex(BLOCK), False)["hash"]
        actors = {role: to_checksum_address(keccak(text="pack-vault-test-complete-cost-"+role)[-20:])
                  for role in ["deployer", "keeper", "owner"]}
        for role, actor in actors.items():
            assert rpc("eth_getCode", actor, "latest") == "0x"
            assert int(rpc("eth_getTransactionCount", actor, "latest"), 16) == 0
            assert int(rpc("eth_getBalance", actor, "latest"), 16) == 0
            rpc("anvil_setBalance", actor, hex((40 if role == "deployer" else 1)*E))
            rpc("anvil_impersonateAccount", actor)
        REPORT["actors"] = actors
        values = json.loads((ROOT/"deploy/mainnet.json").read_text())
        values.update(owner=actors["owner"], seedWei=20*E, routineCapWei=3*E//10,
                      routineRatePerDayWei=E//100, packUnitsMask=(1<<3)|(1<<4)|(1<<30))
        path = ROOT/"deploy/complete-cost.local.json"
        path.write_text(json.dumps(values, indent=2)+"\n")
        env = dict(os.environ, RPC_URL=RPC, I_AM_THE_OWNER="yes", FOUNDRY_GAS_LIMIT=str(LIMIT),
                   FORGE_WALLET_ARGS="--unlocked --sender "+actors["deployer"])
        with open(work/"deploy.log", "w") as log:
            subprocess.run(["script/deploy.sh", str(path.relative_to(ROOT)), "--broadcast"],
                           cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
        run = json.loads((ROOT/"broadcast/Deploy.s.sol/1/run-latest.json").read_text())
        deployments = [x for x in run["transactions"] if x.get("contractName") == "PackVault"]
        assert len(deployments) == 1
        vault = deployments[0]["contractAddress"]
        REPORT["vault"] = vault
        REPORT["deployment"] = []
        for tx in run["transactions"]:
            rec = rpc("eth_getTransactionReceipt", tx["hash"])
            assert int(rec["status"],16) == 1
            REPORT["deployment"].append(rec)
        fee()
        entry = rpc("evm_snapshot")
        for price in [200_000_000, 500_000_000]:
            PRICE = price
            assert rpc("evm_revert", entry)
            entry = rpc("evm_snapshot")
            try:
                stock(vault, actors["keeper"], "current admission fresh three", 3, 1)
            except RuntimeError as exc:
                REPORT["unreachable"].append(dict(price_wei=price, scope="current observed admission", error=str(exc)))
            assert rpc("evm_revert", entry)
            entry = rpc("evm_snapshot")
            assert read(values["fwa"], "oracleExemptCollections(address)", ["bool"],
                        ["address"], [values["packs"]])[0]
            branch = rpc("evm_snapshot")
            if PROFILE == "all":
                stock(vault, actors["keeper"], "three fresh one", 3, 1)
                stock(vault, actors["keeper"], "three leftover one", 3, 1)
                stock(vault, actors["keeper"], "three mixed three", 3, 3)
                assert rpc("evm_revert", branch)
                branch = rpc("evm_snapshot")
                stock(vault, actors["keeper"], "three bulk ten", 3, 10)
                for count in [8, 1, 1]:
                    send(actors["keeper"], vault, "list(uint256[],uint256)", ["uint256[]", "uint256"],
                         [proposals(vault, 3, count, False), 0], label="list "+str(count), measure=True)
                assert rpc("evm_revert", branch)
                branch = rpc("evm_snapshot")
            stock(vault, actors["keeper"], "four fresh one", 4, 1)
            stock(vault, actors["keeper"], "four mixed two", 4, 2)
            stock(vault, actors["keeper"], "four leftover two", 4, 2)
            assert rpc("evm_revert", branch)
            stock(vault, actors["keeper"], "thirty fresh one", 30, 1)
        for p, expected in source.items():
            assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == expected, "source changed: "+p
        REPORT["status"] = "completed"
    except BaseException as exc:
        REPORT["status"] = "failed"
        REPORT["error"] = repr(exc)
        raise
    finally:
        save()
        node.terminate()
        node.wait(timeout=20)
        (ROOT/"deploy/complete-cost.local.json").unlink(missing_ok=True)


if __name__ == "__main__":
    main()
