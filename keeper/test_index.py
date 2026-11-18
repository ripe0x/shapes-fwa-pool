#!/usr/bin/env python3
"""Pure event serialization and SQLite projection tests; actual Vault reorgs run in the approved rehearsal."""
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pathlib import Path

from eth_abi import encode
from eth_utils import keccak

import index as I

VAULT = "0x0000000000000000000000000000000000001234"


def event(name, values, block, idx):
    fields = I.EVENTS[name]
    return dict(topics=["0x" + keccak(text=f"{name}({','.join(t for _, t, _ in fields)})").hex()] +
                       ["0x" + encode([t], [values[n]]).hex() for n, t, indexed in fields if indexed],
                data="0x" + encode([t for _, t, indexed in fields if not indexed],
                                   [values[n] for n, _, indexed in fields if not indexed]).hex(),
                blockNumber=hex(block), logIndex=hex(idx), blockHash=f"hash-{block}")


def pos(id_, debt=0, state=1, backing=None, block=10, idx=0):
    return event("PositionUpdated", dict(listingId=id_, packId=id_ + 100, value=3 * 10**16,
                 backing=backing or 4 * 10**16 + id_ * 10000, feeDebt=debt, allocatedAt=500 if state == 2 else 0,
                 state=state), block, idx)


def snapshot(index):
    return {t: [tuple(r) for r in index.db.execute(f"SELECT * FROM {t} ORDER BY 1")]
            for t in ("positions", "inventory", "recovery", "receipts", "allocations")}


def projection_tests(directory):
    path = directory / "index.sqlite"
    book = I.EventIndex(path, 1, VAULT, 10)
    logs = [pos(1, debt=2**130, idx=0), pos(2, debt=9, idx=1),
            event("InventoryUpdated", dict(packId=103, value=7 * 10**16), 10, 2)]
    book.append(10, 10, "hash-10", logs)
    assert book.candidates(1, 1) == ([2], [])  # numeric debt ordering, not SQLite integer truncation
    assert book.idle(1) == [(103, 7 * 10**16)]
    before = snapshot(book)
    book.close()
    book = I.EventIndex(path, 1, VAULT.upper(), 10)
    assert snapshot(book) == before and book.head == 10  # durable restart
    try:
        I.EventIndex(path, 2, VAULT, 10)
    except ValueError:
        pass
    else:
        raise AssertionError("cross-chain index reuse accepted")
    logs2 = [pos(2, state=2, block=11, idx=0),
             event("CashReceipt", dict(listingId=2, outcome=1, amount=395 * 10**14), 11, 1),
             event("JournalProgress", dict(cursor=99, processed=4, own=1), 11, 2),
             event("InventoryUpdated", dict(packId=103, value=0), 11, 3),
             event("RecoveryUpdated", dict(packId=104, value=10**18, unsealed=False), 11, 4)]
    book.append(11, 11, "hash-11", logs2)
    assert book.candidates(1, 1) == ([1], [2]) and book.meta("cursor") == "99" and not book.idle(1)
    assert book.db.execute("SELECT value FROM recovery WHERE pack_id='104'").fetchone()[0] == str(10**18)
    # Rollback and alternate replay restore the retained prefix, including a pending receipt.
    book.rollback(10)
    assert snapshot(book) == before and book.meta("cursor") is None
    book.append(11, 11, "hash-11-other", logs2)
    book.append(12, 12, "hash-12", [pos(2, state=0, block=12, idx=0),
                event("ReceiptConsumed", dict(listingId=2), 12, 1), pos(3, backing=4 * 10**16 + 20000, block=12, idx=2)])
    assert book.candidates(2, 2) == ([3, 1], [])
    assert book.reserved(4 * 10**16 + 20000)
    # Owed custody retains principal but its identifier is released by production.
    tag = 4 * 10**16 + 20000
    assert book.reserved(tag)
    book.append(13, 13, "hash-13", [pos(3, state=3, backing=tag, block=13, idx=0)])
    assert not book.reserved(tag)
    assert book.position(3)["state"] == 3
    # Duplicate log keys roll the complete range back instead of partly projecting it.
    before = snapshot(book)
    try:
        book.append(14, 14, "hash-14", [pos(4, block=14, idx=0), pos(5, block=14, idx=0)])
    except Exception:
        pass
    else:
        raise AssertionError("duplicate journal key accepted")
    assert book.head == 13 and snapshot(book) == before
    book.close()

    # 10,000 indexed bookkeeping positions do not enlarge hydrated candidate sets. This is an
    # index scale fixture, not 10,000 real onchain listings. Reconstruction uses the same logs.
    logs = [pos(i, debt=i % 7, block=10, idx=i) for i in range(1, 10_001)]
    volume = dict(topics=[I.ALLOCATION_TOPIC], data="0x", blockNumber="0xa", logIndex=hex(10_001),
                  blockHash="hash-10", _timestamp=1_000_000)
    logs.append(volume)
    a = I.EventIndex(directory / "scale.sqlite", 1, VAULT, 10)
    a.append(10, 10, "hash-10", logs)
    assert len(a.candidates(16, 16)[0]) == 16
    queries = ["SELECT id FROM positions WHERE state=1 ORDER BY debt,id LIMIT 16",
               "SELECT id FROM positions WHERE state=2 ORDER BY allocated_at,id LIMIT 16",
               "SELECT id FROM positions WHERE state=1 AND id>'5' ORDER BY id LIMIT 16",
               "SELECT * FROM inventory ORDER BY block DESC,log_index DESC LIMIT 16"]
    for query in queries:
        details = " ".join(row[3] for row in a.db.execute("EXPLAIN QUERY PLAN " + query))
        assert "TEMP B-TREE" not in details, details
    assert len(a.token_candidates(16)) == 16
    first = a.token_candidates(16)
    assert first != a.token_candidates(16)
    assert a.recent_volume(1_000_000) == 1 / 7 and a.recent_volume(1_604_801) == 0
    original = snapshot(a)
    a.rollback(10)
    assert snapshot(a) == original
    a.close()
    concurrent = directory / "concurrent.sqlite"
    I.EventIndex(concurrent, 1, VAULT, 10).close()
    barrier = Barrier(4)
    def writer(_):
        book = I.EventIndex(concurrent, 1, VAULT, 10)
        barrier.wait()
        result = book.append(10, 10, "hash-10", [pos(1)])
        book.close()
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        committed = list(pool.map(writer, range(4)))
    assert sum(committed) == 1
    book = I.EventIndex(concurrent, 1, VAULT, 10)
    assert book.head == 10 and book.db.execute("SELECT count(*) FROM events").fetchone()[0] == 1
    book.close()
    print("index projection: restart, identity, exact wei/debt, rollback/replay, duplicate atomicity, identifier reuse, 10k bounded candidates: pass")


def exercise_vault_reorg(R):
    """Index actual PackVault withdrawals, then repair to the real restored chain."""
    import keeper as K
    R.B.load_manifest()
    K.RPC = R.RPC
    deployment = R.num(R.call(R.VAULT, "deploymentBlock()(uint256)"))
    path = Path(R.KEEPER_STATE).with_name("actual-vault-index-reorg.sqlite")
    book = I.EventIndex(path, 1, R.VAULT, deployment)
    K.sync_index(book, R.num(R.cast("block-number")))
    before = snapshot(book)
    chain_snapshot = R.B.rpc("evm_snapshot")
    try:
        shares = R.num(R.call(R.VAULT, "shareBalance(address)(uint256)", R.HOLDER)) // 5
        if not shares:
            raise RuntimeError("real index reorg witness needs the actual canary holder")
        R.send(R.HOLDER, R.VAULT, "requestRedeem(uint256)", shares, value=R.redeem_charge(shares))
        top = R.num(R.call(R.FWA, "topListingId()(uint256)"))
        ids = [id_ for id_ in R.ids() if id_ != top][:2]
        if not ids:
            raise RuntimeError("real index reorg witness needs an ordinary active position")
        R.send(R.KEEPER, R.VAULT, "unlist(uint256[],uint256)", "[" + ",".join(map(str, ids)) + "]", 0)
        K.sync_index(book, R.num(R.cast("block-number")))
        if snapshot(book) == before or not book.idle(1):
            raise RuntimeError("actual withdrawals did not change indexed positions/inventory")
        book.close()
        book = I.EventIndex(path, 1, R.VAULT, deployment)
        if snapshot(book) == before:
            raise RuntimeError("actual changed projections did not survive index restart")
    finally:
        if not R.B.rpc("evm_revert", chain_snapshot):
            raise RuntimeError("actual vault index reorg restore failed")
    K.sync_index(book, R.num(R.cast("block-number")))
    if snapshot(book) != before:
        raise RuntimeError("actual canonical rollback did not restore indexed positions/inventory")
    book.close()
    result = dict(vault=R.VAULT, deployment_block=deployment, real_withdrawal=True,
                  durable_restart=True, canonical_projection_restore=True)
    R.B.append_action(dict(operation="actual vault event index reorg", result=result))
    return result


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as d:
        projection_tests(Path(d))
