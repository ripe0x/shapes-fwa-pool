#!/usr/bin/env python3
"""Bill successful foreign journal work on an isolated local Anvil.

The input allocation is exported by CompleteForeignJournal.t.sol after authentic
historical request and coordinator calls. Importing that exact execution state is
necessary because Anvil cannot set the authenticated historical request hash.
No external protocol storage is invented. Every measured call is a fresh, signed
transaction with an actual status, gasUsed and effectiveGasPrice receipt.

Use the already exported fixtures in sim/out, e.g.:
  EXPORT_COMPLETE_FOREIGN=true COMPLETE_FOREIGN_COUNT=2 forge test ...
  python3 keeper/complete_foreign_receipts.py --counts 1 2

This script creates and terminates only its own child node. It never connects a
signer to a public RPC, and never accesses the earlier bounded rehearsal node.
"""
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import urllib.request

from eth_utils import keccak

import keeper as keeper_client
import tx as txm

ROOT = Path(__file__).resolve().parents[1]
FWA = "0x958c41181182e76f221331b2755b77d9e1426a98"
RPC = "http://127.0.0.1:8562"
UPSTREAM = "https://mainnet.gateway.tenderly.co"
FORK = 26417085
TIP = 50_000_000
MAX_GAS = 16_777_216
SOURCES = ("src/PackVault.sol", "src/VaultLib.sol", "src/KeeperPolicy.sol",
           "keeper/keeper.py", "keeper/policy.py", "keeper/tx.py",
           "test/fork/CompleteForeignJournal.t.sol", "keeper/complete_foreign_receipts.py",
           "sim/complete_foreign_fixture.py", "test/fixtures/complete-foreign.json",
           "test/fixtures/complete-foreign-history.json")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rpc(method, *params):
    request = urllib.request.Request(RPC, json.dumps({"jsonrpc": "2.0", "id": 1,
        "method": method, "params": list(params)}).encode(), {"Content-Type": "application/json"})
    response = json.load(urllib.request.urlopen(request, timeout=55))
    if "error" in response:
        raise RuntimeError((method, response["error"]))
    return response["result"]


def cast(*args):
    try:
        return subprocess.check_output(["cast", *map(str, args), "--rpc-url", RPC],
            text=True, stderr=subprocess.STDOUT).strip()
    except subprocess.CalledProcessError as error:
        raise RuntimeError(error.output) from None


def num(value):
    text = str(value).split()[0]
    return int(text, 0) if text.startswith("0x") else int(text)


def read(vault, signature, *args):
    return num(cast("call", vault, signature, *args))


def match_runtime(artifact, actual, library=False):
    expected = artifact["object"].removeprefix("0x")
    actual = actual.removeprefix("0x")
    assert len(actual) // 2 <= 24_576
    regions = [r for rs in artifact.get("immutableReferences", {}).values() for r in rs]
    regions += [r for files in artifact.get("linkReferences", {}).values() for rs in files.values() for r in rs]
    if library:
        regions += [dict(start=1, length=20)]
    for region in regions:
        left, right = 2 * region["start"], 2 * (region["start"] + region["length"])
        expected = expected[:left] + "0" * (right-left) + expected[right:]
        actual = actual[:left] + "0" * (right-left) + actual[right:]
    assert expected.lower() == actual.lower(), "fixture runtime differs from compiled production artifact"


def load_fixture(count, artifacts):
    prefix = ROOT / f"sim/out/complete-foreign-{count}"
    metadata = json.loads(Path(str(prefix) + "-metadata.json").read_text())
    exported = json.loads(Path(str(prefix) + "-state.json").read_text())
    accounts = exported.get("alloc", exported)
    vault_artifact = json.loads((artifacts / "PackVault.sol/PackVault.json").read_text())["deployedBytecode"]
    vault_code = accounts[metadata["vault"].lower()]["code"]
    match_runtime(vault_artifact, vault_code)
    link = vault_artifact["linkReferences"]["src/VaultLib.sol"]["VaultLib"][0]
    library = "0x" + vault_code[2 + 2 * link["start"]:2 + 2 * (link["start"] + link["length"])]
    library_artifact = json.loads((artifacts / "VaultLib.sol/VaultLib.json").read_text())["deployedBytecode"]
    match_runtime(library_artifact, accounts[library.lower()]["code"], library=True)
    metadata["state_sha256"] = digest(Path(str(prefix) + "-state.json"))
    metadata["metadata_sha256"] = digest(Path(str(prefix) + "-metadata.json"))
    metadata["vault_runtime_sha256"] = hashlib.sha256(bytes.fromhex(vault_code[2:])).hexdigest()
    metadata["library_runtime_sha256"] = hashlib.sha256(bytes.fromhex(accounts[library.lower()]["code"][2:])).hexdigest()
    metadata["artifact_sha256"] = {p:digest(artifacts / p) for p in (
        "PackVault.sol/PackVault.json", "VaultLib.sol/VaultLib.json", "KeeperPolicy.sol/KeeperPolicyV1.json")}
    packed = bytes.fromhex(rpc("anvil_dumpState")[2:])
    state = json.loads(gzip.decompress(packed))
    state["accounts"] = exported.get("alloc", exported)
    # Forge's genesis allocation writes nonce as a hex quantity; Anvil's state
    # dump expects the identical value as a JSON integer.
    for account in state["accounts"].values():
        account["nonce"] = num(account["nonce"])
    # These are the block environment values used by the genuine fork fixture.
    state["block"]["number"] = hex(metadata["block"])
    state["block"]["timestamp"] = hex(metadata["timestamp"])
    state["best_block_number"] = metadata["block"]
    assert rpc("anvil_loadState", "0x" + gzip.compress(json.dumps(state).encode()).hex())
    rpc("evm_setNextBlockTimestamp", hex(metadata["timestamp"] + 1))
    rpc("evm_mine")
    vault = metadata["vault"]
    assert read(vault, "acquisitionCursor()(uint64)") == metadata["cursor"]
    assert read(FWA, "nextSequenceToProcess()(uint64)") == metadata["end"]
    assert min(128, metadata["end"] - metadata["cursor"]) == count
    assert read(vault, "openListingCount()(uint256)") == 1
    assert read(vault, "pendingDepositTotal()(uint256)") == metadata["escrow"]
    assert read(vault, "processingPool()(uint256)") == metadata["processing"]
    assert read(FWA, "unsettledAcquisitionCount()(uint256)") == 0
    assert cast("code", metadata["keeper"]) == "0x"
    policy = cast("call", vault, "keeperPolicy()(address)")
    policy_artifact = json.loads((artifacts / "KeeperPolicy.sol/KeeperPolicyV1.json").read_text())["deployedBytecode"]
    match_runtime(policy_artifact, cast("code", policy))
    # Every journal entry is checked against the real exposed fixture before
    # sending. Importing a silent empty-vault rebase cannot pass these checks.
    successful, refunded = 0, 0
    for sequence in range(metadata["cursor"], metadata["end"]):
        rid = read(FWA, "requestIdAtSequence(uint64)(uint256)", sequence)
        fields = cast("call", FWA, "acquisitions(uint256)(address,uint256,uint256,uint256,uint8)", rid).splitlines()
        if num(fields[4]) in (3, 4):
            refunded += 1
            continue
        assert num(fields[4]) == 2
        successful += 1
        listing = num(fields[3])
        live = cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", listing).splitlines()
        assert live[1].lower() != vault.lower()
    assert (successful, refunded) == ((125, 3) if count == 128 else (count, 0))
    metadata["record_mix"] = dict(successful_foreign=successful, genuine_deadline_refunds=refunded)
    return metadata


def fees_at(price):
    desired = price - TIP
    parent = desired * 8 // 7
    assert parent - parent // 8 == desired
    rpc("anvil_setNextBlockBaseFeePerGas", hex(parent))
    header = rpc("eth_getBlockByNumber", "latest", False)
    rpc("evm_setNextBlockTimestamp", hex(num(header["timestamp"]) + 1))
    rpc("evm_mine")
    parent_header = rpc("eth_getBlockByNumber", "latest", False)
    pending = rpc("eth_getBlockByNumber", "pending", False)
    assert num(pending["baseFeePerGas"]) == desired == txm.next_base_fee(parent_header)
    return ["--gas-price", str(2 * desired + TIP), "--priority-gas-price", str(TIP)]


def measure(metadata, count, price, work, fund_from_fees=False):
    fees = fees_at(price)
    vault, sender = metadata["vault"], metadata["keeper"]
    args = ["sync(uint256[],uint256,uint256)(uint256)", "[]", "0", "0"]
    cash_fixture = None
    if fund_from_fees:
        ordinary_offer = num(cast("call", vault, *args, "--from", sender, "--block", "pending", *fees))
        original = num(rpc("eth_getBalance", vault, "latest"))
        free = read(vault, "freeEth()(uint256)")
        actual_fees = read(FWA, "pendingFees(uint256)(uint256)", metadata["listing"])
        protected = original - free
        reduced = protected + ordinary_offer // 2
        # Explicit gas/eligibility scenario only: vary this newly deployed local
        # vault's unprotected cash. Every FWA slot and actual earned fee remains
        # exactly as produced by authenticated acquisition replay.
        rpc("anvil_setBalance", vault, hex(reduced))
        args[1] = f"[{metadata['listing']}]"
        cash_fixture = dict(original_balance_wei=original, reduced_balance_wei=reduced,
            protected_balance_wei=protected, pending_fees_wei=actual_fees,
            scope="explicit local vault cash adjustment for gas and eligibility; not a naturally funded lifecycle")
    offer = num(cast("call", vault, *args, "--from", sender, "--block", "pending", *fees))
    tm = txm.TxManager(RPC, str(work / f"preflight-{count}-{price}.json"), sender, [], log=lambda x: None)
    try:
        estimate, reason, expected = tm.preflight(vault, args, fees)
        assert estimate is not None, (reason, expected)
        signed = args[:-1] + [str(offer * 8 // 10)]
        signed_estimate, signed_reason, signed_expected = tm.preflight(vault, signed, fees)
        assert signed_estimate is not None, (signed_reason, signed_expected)
    finally:
        tm._lockf.close()
    ratio = keeper_client.billed_ratio(None, "sync")
    cost, needed, accepted = keeper_client.profitability_gate(signed_estimate, price, offer, 0, 0, 0, ratio)
    limit = (signed_estimate * 5 + 3) // 4
    assert limit <= MAX_GAS
    key = "0x" + keccak(text="pack-vault-test-complete-foreign-keeper").hex()
    address = subprocess.check_output(["cast", "wallet", "address", "--private-key", key], text=True).strip()
    assert address.lower() == sender.lower()
    before = num(rpc("eth_getBalance", sender, "latest"))
    escrow = read(vault, "pendingDepositTotal()(uint256)")
    processing = read(vault, "processingPool()(uint256)")
    receipt = json.loads(cast("send", vault, *signed, "--private-key", key,
        "--gas-limit", str(limit), "--json", *fees))
    assert num(receipt["status"]) == 1
    billed = num(receipt["gasUsed"])
    paid_price = num(receipt["effectiveGasPrice"])
    paid = sum(num(log["data"]) for log in receipt["logs"]
        if log["address"].lower() == vault.lower() and log["topics"]
        and log["topics"][0].lower() == txm.KEEPER_PAID
        and log["topics"][1][-40:].lower() == sender[2:].lower())
    after = num(rpc("eth_getBalance", sender, "latest"))
    assert paid_price == price
    assert paid == offer
    assert after - before == paid - billed * price
    assert read(vault, "pendingDepositTotal()(uint256)") == escrow
    assert read(vault, "processingPool()(uint256)") == processing
    assert read(vault, "acquisitionCursor()(uint64)") == metadata["cursor"] + count
    assert read(vault, "openListingCount()(uint256)") == 1
    row = dict(operation="sync-with-fee-funding" if fund_from_fees else "sync",
        records=count, remaining_records=metadata["end"] - metadata["cursor"] - count,
        price_wei=price, estimate=estimate, signed_estimate=signed_estimate,
        gas_limit=limit, signed_min_pay=offer * 8 // 10, keeper_offer_wei=offer,
        ordinary_billed_ratio=ratio, ordinary_expected_cost_wei=cost,
        ordinary_required_pay_wei=needed, ordinary_accepts=accepted,
        billed_gas=billed, cost_wei=billed * price, keeper_paid_wei=paid,
        keeper_net_wei=paid - billed * price, sender_balance_before_wei=before,
        sender_balance_after_wei=after, escrow_preserved=True, processing_pool_preserved=True,
        record_mix=metadata["record_mix"], cash_fixture=cash_fixture, receipt=receipt)
    if fund_from_fees:
        assert read(FWA, "pendingFees(uint256)(uint256)", metadata["listing"]) == 0
    suffix = "-funded" if fund_from_fees else ""
    (work / f"receipt-{count}-{price}{suffix}.json").write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps({k:row[k] for k in ("operation", "records", "price_wei", "signed_estimate", "billed_gas", "keeper_net_wei", "ordinary_accepts")}), flush=True)
    return row


def full_holder_checkpoint(metadata, price, work):
    """Turn the fixture's real deposit into a complete holder redemption."""
    vault, sender, holder = metadata["vault"], metadata["keeper"], metadata["holder"]
    key = "0x" + keccak(text="pack-vault-test-complete-foreign-keeper").hex()
    holder_key = "0x" + keccak(text="pack-vault-test-complete-foreign-holder").hex()
    fees = fees_at(price)
    initial = ["checkpoint(uint256,uint256)(uint256)", str(metadata["listing"]), "0"]
    estimate = num(cast("estimate", vault, *initial, "--from", sender, "--block", "pending", *fees))
    receipt = json.loads(cast("send", vault, *initial, "--private-key", key,
        "--gas-limit", str((estimate * 5 + 3) // 4), "--json", *fees))
    assert num(receipt["status"]) == 1
    assert read(vault, "pendingDepositTotal()(uint256)") == 0
    shares = read(vault, "shareBalance(address)(uint256)", holder)
    assert shares > 0
    fees = fees_at(price)
    checkpoint_charge = num(cast("call", vault, "requestCharge()(uint256)", "--block", "pending", *fees))
    unwind_charge = num(cast("call", vault, "unwindCharge()(uint256)", "--block", "pending", *fees))
    share_value = shares * read(vault, "lastNav()(uint256)") // read(vault, "totalShares()(uint256)")
    charge = checkpoint_charge + share_value * unwind_charge // (663 * 10**14)
    request = ["requestRedeem(uint256)", str(shares), "--value", str(charge)]
    estimate = num(cast("estimate", vault, *request, "--from", holder, "--block", "pending", *fees))
    receipt = json.loads(cast("send", vault, *request, "--private-key", holder_key,
        "--gas-limit", str((estimate * 5 + 3) // 4), "--json", *fees))
    assert num(receipt["status"]) == 1
    assert read(vault, "lockedShares()(uint256)") + read(vault, "DEAD_SHARES()(uint256)") == read(vault, "totalShares()(uint256)")
    header = rpc("eth_getBlockByNumber", "latest", False)
    rpc("evm_setNextBlockTimestamp", hex(num(header["timestamp"]) + 12 * 3600))
    rpc("evm_mine")
    fees = fees_at(price)
    offer = num(cast("call", vault, *initial, "--from", sender, "--block", "pending", *fees))
    signed = initial[:-1] + [str(offer * 8 // 10)]
    tm = txm.TxManager(RPC, str(work / f"full-holder-{price}.json"), sender, [], log=lambda x: None)
    try:
        estimate, reason, expected = tm.preflight(vault, signed, fees)
        assert estimate is not None, (reason, expected)
    finally:
        tm._lockf.close()
    cost, needed, accepted = keeper_client.profitability_gate(estimate, price, offer, 0, 0, 0,
        keeper_client.billed_ratio(None, "checkpoint"))
    limit = (estimate * 5 + 3) // 4
    assert limit <= MAX_GAS
    before = num(rpc("eth_getBalance", sender, "latest"))
    receipt = json.loads(cast("send", vault, *signed, "--private-key", key,
        "--gas-limit", str(limit), "--json", *fees))
    assert num(receipt["status"]) == 1
    billed = num(receipt["gasUsed"])
    assert num(receipt["effectiveGasPrice"]) == price
    paid = sum(num(log["data"]) for log in receipt["logs"]
        if log["address"].lower() == vault.lower() and log["topics"]
        and log["topics"][0].lower() == txm.KEEPER_PAID)
    after = num(rpc("eth_getBalance", sender, "latest"))
    assert paid == offer and after - before == paid - billed * price
    assert read(vault, "lockedShares()(uint256)") == 0
    assert read(vault, "shareBalance(address)(uint256)", holder) == 0
    assert read(vault, "totalShares()(uint256)") == read(vault, "DEAD_SHARES()(uint256)")
    assert read(vault, "redemptionReserve()(uint256)") > 0
    row = dict(operation="full-holder-checkpoint", price_wei=price, signed_estimate=estimate,
        gas_limit=limit, signed_min_pay=offer * 8 // 10, keeper_offer_wei=offer,
        ordinary_expected_cost_wei=cost, ordinary_required_pay_wei=needed, ordinary_accepts=accepted,
        billed_gas=billed, cost_wei=billed * price, keeper_paid_wei=paid, keeper_net_wei=paid - billed * price,
        all_live_holder_shares_redeemed=True, redemption_reserve_funded=True, receipt=receipt)
    (work / f"full-holder-receipt-{price}.json").write_text(json.dumps(row, indent=2) + "\n")
    print(json.dumps({k:row[k] for k in ("operation", "price_wei", "signed_estimate", "billed_gas", "keeper_net_wei", "ordinary_accepts")}), flush=True)
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--counts", type=int, nargs="+", default=[1, 2])
    parser.add_argument("--artifacts", type=Path, default=ROOT / "out")
    args = parser.parse_args()
    assert set(args.counts) <= {1, 2, 125, 128}
    source_hashes = {p:digest(ROOT / p) for p in SOURCES}
    work = Path(tempfile.mkdtemp(prefix="complete-foreign-receipts-"))
    rows, fixtures = [], []
    for count in args.counts:
        initial_metadata = json.loads((ROOT / f"sim/out/complete-foreign-{count}-metadata.json").read_text())
        logfile = open(work / f"anvil-{count}.log", "w")
        node = subprocess.Popen(["anvil", "--port", "8562", "--host", "127.0.0.1", "--accounts", "0",
            "--chain-id", "1", "--fork-url", UPSTREAM, "--fork-block-number", str(initial_metadata.get("forkBlock", FORK)),
            "--compute-units-per-second", "100", "--timeout", "60000"], stdout=logfile, stderr=subprocess.STDOUT)
        try:
            for attempt in range(60):
                try:
                    assert "anvil" in rpc("web3_clientVersion").lower(); break
                except Exception:
                    if node.poll() is not None:
                        raise RuntimeError(("local node exited", (work / f"anvil-{count}.log").read_text()))
                    time.sleep(.5)
            else:
                raise RuntimeError("local node did not start")
            metadata = load_fixture(count, args.artifacts)
            fixtures.append(metadata)
            snapshot = rpc("evm_snapshot")
            for price in (200_000_000, 500_000_000):
                rows.append(measure(metadata, count, price, work))
                if count == 2:
                    rows.append(full_holder_checkpoint(metadata, price, work))
                if count == 128 and metadata["end"] > metadata["cursor"] + count:
                    tail = {**metadata, "cursor": metadata["cursor"] + count}
                    rows.append(measure(tail, tail["end"] - tail["cursor"], price, work))
                assert rpc("evm_revert", snapshot)
                snapshot = rpc("evm_snapshot")
                if count == 128:
                    rows.append(measure(metadata, count, price, work, fund_from_fees=True))
                    assert rpc("evm_revert", snapshot)
                    snapshot = rpc("evm_snapshot")
        finally:
            node.terminate(); node.wait(timeout=15); logfile.close()
    assert source_hashes == {p:digest(ROOT / p) for p in SOURCES}, "source changed during receipt measurement"
    report = dict(fixture="actual historical acquisition and VRF coordinator replay, exported without invented slots",
        source_sha256=source_hashes, imported_client_identity=txm.client_identity([keeper_client, txm, keeper_client.policy]),
        scope="actual signed local sync receipts; setup is a restored Forge execution snapshot, not mined setup receipts",
        limitation="When included, a full 128-record transaction has 125 successful foreign records and three genuine deadline refunds. This report does not claim a 128-of-128 successful receipt.",
        tool_versions={tool:subprocess.check_output([tool, "--version"], text=True).strip() for tool in ("forge", "cast", "anvil")},
        work_directory=str(work), fixture_provenance=fixtures, rows=rows,
        all_billed_costs_covered=all(r["keeper_net_wei"] >= 0 for r in rows),
        all_ordinary_preflights_accept=all(r["ordinary_accepts"] for r in rows))
    destination = ROOT / "docs/receipts/complete-foreign-journal.json"
    destination.write_text(json.dumps(report, indent=2) + "\n")
    print(destination, flush=True)


if __name__ == "__main__":
    main()
