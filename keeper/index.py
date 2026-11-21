"""Reconstructible PackVault event index. Onchain cursor and receipt checks remain authoritative.

Each committed range ends at a saved canonical block hash. Reorg repair rolls back whole
ranges and replays the retained event journal; ordinary ingestion applies only new events.
Wei and IDs stay decimal text so SQLite's signed integer range cannot truncate them.
"""
import json
import sqlite3
import hashlib
from pathlib import Path

from eth_abi import decode
from eth_utils import keccak

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

EVENTS = {
    "PositionUpdated": [("listingId", "uint256", True), ("packId", "uint256", False),
                        ("value", "uint256", False), ("backing", "uint256", False),
                        ("feeDebt", "uint256", False), ("allocatedAt", "uint64", False),
                        ("state", "uint8", False)],
    "InventoryUpdated": [("packId", "uint256", True), ("value", "uint256", False)],
    "RecoveryUpdated": [("packId", "uint256", True), ("value", "uint256", False), ("unsealed", "bool", False)],
    "CashReceipt": [("listingId", "uint256", True), ("outcome", "uint8", False), ("amount", "uint256", False)],
    "ReceiptConsumed": [("listingId", "uint256", True)],
    "JournalProgress": [("cursor", "uint64", False), ("processed", "uint256", False), ("own", "uint256", False)],
}
ALLOCATION_TOPIC = "0x" + keccak(text="NFTAllocated(uint256,uint256,address,address,uint256,uint256)").hex()
FWA = "0x958c41181182e76f221331b2755b77d9e1426a98"
BID_EVENTS = {
    "DepositorBidAccepted": [("listingId", "uint256", True), ("purchaser", "address", True),
                             ("depositor", "address", True), ("payout", "uint256", False),
                             ("retained", "uint256", False)],
    "DepositorBidAcceptedAsTokens": [("listingId", "uint256", True), ("purchaser", "address", True),
                                     ("depositor", "address", True), ("ethPayout", "uint256", False),
                                     ("retained", "uint256", False), ("tokenOut", "uint256", False)],
}
TOPICS = {"0x" + keccak(text=f"{name}({','.join(t for _, t, _ in fields)})").hex(): (name, fields)
          for name, fields in EVENTS.items()}
BID_TOPICS = {"0x" + keccak(text=f"{name}({','.join(t for _, t, _ in fields)})").hex(): (name, fields)
              for name, fields in BID_EVENTS.items()}


def own_allocation(log, vault):
    if (log.get("address", "").lower() != FWA or not log.get("topics")
            or log["topics"][0] != ALLOCATION_TOPIC):
        return False
    depositor, _, _ = decode(["address", "uint256", "uint256"], bytes.fromhex(log["data"][2:]))
    return depositor.lower() == vault.lower()


def decode_log(log, vault):
    if log.get("removed", False):
        raise ValueError("removed log cannot enter the canonical index")
    address = log.get("address", "").lower()
    if log.get("topics") and log["topics"][0] == ALLOCATION_TOPIC:
        if address != FWA:
            return None
        args = {"timestamp": log["_timestamp"]}
        if own_allocation(log, vault):
            args["listingId"] = int(log["topics"][2], 16)
        return dict(event="NFTAllocated", args=args,
                    block=int(log["blockNumber"], 16), log_index=int(log["logIndex"], 16), block_hash=log["blockHash"])
    topic = log["topics"][0] if log.get("topics") else None
    bid = topic in BID_TOPICS
    if address != (FWA if bid else vault.lower()):
        return None
    spec = (BID_TOPICS if bid else TOPICS).get(topic)
    if spec is None:
        return None
    name, fields = spec
    topics = iter(log["topics"][1:])
    plain = iter(decode([t for _, t, indexed in fields if not indexed], bytes.fromhex(log["data"][2:])))
    values = {n: decode([t], bytes.fromhex(next(topics)[2:]))[0] if indexed else next(plain)
              for n, t, indexed in fields}
    if bid and values["depositor"].lower() != vault.lower():
        return None
    return dict(event=name, args=values, block=int(log["blockNumber"], 16),
                log_index=int(log["logIndex"], 16), block_hash=log["blockHash"])


class EventIndex:
    def __init__(self, path, chain, vault, deployment_block, start_block=None):
        self.path = str(path)
        self.vault = vault
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS ranges (end INTEGER PRIMARY KEY, hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events (
                block INTEGER NOT NULL, log_index INTEGER NOT NULL, block_hash TEXT NOT NULL,
                event TEXT NOT NULL, args TEXT NOT NULL, PRIMARY KEY(block,log_index));
            CREATE TABLE IF NOT EXISTS positions (
                id TEXT PRIMARY KEY, pack_id TEXT NOT NULL, value TEXT NOT NULL, backing TEXT NOT NULL,
                debt TEXT NOT NULL, allocated_at INTEGER NOT NULL, state INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS positions_state_debt ON positions(state,debt,id);
            CREATE INDEX IF NOT EXISTS positions_state_id ON positions(state,id);
            CREATE INDEX IF NOT EXISTS positions_allocation ON positions(state,allocated_at,id);
            CREATE INDEX IF NOT EXISTS positions_backing ON positions(backing);
            CREATE TABLE IF NOT EXISTS inventory (
                pack_id TEXT PRIMARY KEY, value TEXT NOT NULL, block INTEGER NOT NULL, log_index INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS inventory_order ON inventory(block DESC,log_index DESC);
            CREATE TABLE IF NOT EXISTS recovery (
                pack_id TEXT PRIMARY KEY, value TEXT NOT NULL, unsealed INTEGER NOT NULL,
                block INTEGER NOT NULL, log_index INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS receipts (id TEXT PRIMARY KEY, outcome INTEGER NOT NULL, amount TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS allocations (block INTEGER NOT NULL, log_index INTEGER NOT NULL,
                timestamp INTEGER NOT NULL, PRIMARY KEY(block,log_index));
            CREATE INDEX IF NOT EXISTS allocations_time ON allocations(timestamp);
            CREATE TABLE IF NOT EXISTS selected (id TEXT PRIMARY KEY, block INTEGER NOT NULL, log_index INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS selected_order ON selected(block,log_index);
            CREATE TABLE IF NOT EXISTS returned (id TEXT PRIMARY KEY, block INTEGER NOT NULL, log_index INTEGER NOT NULL, ready INTEGER NOT NULL);
            CREATE INDEX IF NOT EXISTS returned_order ON returned(ready,block,log_index);
            CREATE TABLE IF NOT EXISTS discovery_ranges (end INTEGER PRIMARY KEY, hash TEXT NOT NULL);
        """)
        identity = json.dumps([int(chain), vault.lower(), int(deployment_block)])
        old = self.meta("identity")
        if old is not None and old != identity:
            raise ValueError("index belongs to another chain, vault or deployment block")
        self.deployment_block = int(deployment_block)
        with self.db:
            self.set_meta("identity", identity)
            saved_start = self.meta("start_block")
            if saved_start is None:
                initial_start = start_block() if callable(start_block) else start_block
                saved_start = min(deployment_block, initial_start or deployment_block)
            self.start_block = int(saved_start)
            self.set_meta("start_block", self.start_block)

    def close(self):
        self.db.close()

    def meta(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row is not None else default

    def set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, str(value)))

    @property
    def head(self):
        return self.db.execute("SELECT coalesce(max(end),?) FROM ranges", (self.start_block - 1,)).fetchone()[0]

    @property
    def discovery_head(self):
        return self.db.execute("SELECT coalesce(max(end),?) FROM discovery_ranges", (self.deployment_block - 1,)).fetchone()[0]

    def allocation_timestamp(self, log):
        row = self.db.execute("SELECT args FROM events WHERE block=? AND log_index=? AND block_hash=? AND event='NFTAllocated'",
                              (int(log["blockNumber"], 16), int(log["logIndex"], 16), log["blockHash"])).fetchone()
        return json.loads(row[0])["timestamp"] if row else None

    def repair(self, block_hash):
        """Check newest range, then walk back only on a reorg. block_hash reads canonical RPC."""
        observed_head = self.head
        keep = observed_head
        for row in self.db.execute("SELECT end,hash FROM ranges ORDER BY end DESC"):
            if block_hash(row["end"]) == row["hash"]:
                keep = row["end"]
                break
            keep = self.start_block - 1
        changed = keep != observed_head
        if changed and not self.rollback(keep, observed_head):
            return False
        observed_discovery = self.discovery_head
        discovery_keep = observed_discovery
        for row in self.db.execute("SELECT end,hash FROM discovery_ranges ORDER BY end DESC"):
            if block_hash(row["end"]) == row["hash"]:
                discovery_keep = row["end"]
                break
            discovery_keep = self.deployment_block - 1
        if discovery_keep != observed_discovery:
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if self.discovery_head != observed_discovery:
                    return changed  # Another writer extended this prefix while hashes were read.
                self.db.execute("DELETE FROM discovery_ranges WHERE end>?", (discovery_keep,))
                self.db.execute("DELETE FROM events WHERE event IN ('DepositorBidAccepted','DepositorBidAcceptedAsTokens') AND block>?",
                                (discovery_keep,))
                for row in self.db.execute("SELECT block,log_index,args FROM events WHERE event='NFTAllocated' AND block>?", (discovery_keep,)).fetchall():
                    args = {"timestamp": json.loads(row["args"])["timestamp"]}
                    self.db.execute("UPDATE events SET args=? WHERE block=? AND log_index=?",
                                    (json.dumps(args), row["block"], row["log_index"]))
                self.db.execute("DELETE FROM selected")
                self.db.execute("DELETE FROM returned")
                for row in self.db.execute("SELECT * FROM events WHERE event IN ('NFTAllocated','DepositorBidAccepted','DepositorBidAcceptedAsTokens') ORDER BY block,log_index").fetchall():
                    self._apply(row["event"], json.loads(row["args"]), row["block"], row["log_index"])
            changed = True
        return changed

    def rollback(self, end, expected_head=None):
        """Restore a committed prefix atomically. Complete replay is only a repair operation."""
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if expected_head is not None and self.head != expected_head:
                return False
            self.db.execute("DELETE FROM ranges WHERE end>?", (end,))
            self.db.execute("DELETE FROM events WHERE block>?", (self.head,))
            self.db.execute("DELETE FROM discovery_ranges WHERE end>?", (self.head,))
            self.db.execute("DELETE FROM positions")
            self.db.execute("DELETE FROM inventory")
            self.db.execute("DELETE FROM recovery")
            self.db.execute("DELETE FROM receipts")
            self.db.execute("DELETE FROM allocations")
            self.db.execute("DELETE FROM selected")
            self.db.execute("DELETE FROM returned")
            self.db.execute("DELETE FROM meta WHERE key IN ('cursor','token_after','owed_after','alloc_after')")
            for row in self.db.execute("SELECT * FROM events ORDER BY block,log_index").fetchall():
                self._apply(row["event"], json.loads(row["args"]), row["block"], row["log_index"])
        return True

    def append(self, start, end, end_hash, logs):
        if end < start:
            raise ValueError("invalid index range")
        events = [e for log in logs if (e := decode_log(log, self.vault)) is not None]
        events.sort(key=lambda e: (e["block"], e["log_index"]))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if start != self.head + 1:
                return False  # another writer moved the prefix; the bounded caller retries it
            for e in events:
                if not start <= e["block"] <= end:
                    raise ValueError("log outside requested range")
                self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                                (e["block"], e["log_index"], e["block_hash"], e["event"], json.dumps(e["args"])))
                self._apply(e["event"], e["args"], e["block"], e["log_index"])
            self.db.execute("INSERT INTO ranges VALUES (?,?)", (end, end_hash))
            if start <= self.discovery_head + 1 <= end:
                self.db.execute("INSERT INTO discovery_ranges VALUES (?,?)", (end, end_hash))
        return True

    def append_discovery(self, start, end, end_hash, logs):
        """Backfill newly subscribed FWA events without rewinding the financial projection."""
        events = [e for log in logs if (e := decode_log(log, self.vault)) is not None]
        events.sort(key=lambda e: (e["block"], e["log_index"]))
        with self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if start != self.discovery_head + 1:
                return False
            if not start <= end <= self.head:
                raise ValueError("discovery replay outside indexed prefix")
            for e in events:
                if not start <= e["block"] <= end or e["event"] not in (*BID_EVENTS, "NFTAllocated"):
                    raise ValueError("event outside discovery range")
                old = self.db.execute("SELECT * FROM events WHERE block=? AND log_index=?", (e["block"], e["log_index"])).fetchone()
                if old is not None:
                    legacy = json.loads(old["args"])
                    if (old["event"] != e["event"] or old["block_hash"] != e["block_hash"]
                            or any(e["args"].get(k) != v for k, v in legacy.items())):
                        raise ValueError("discovery replay conflicts with retained event")
                    if legacy == e["args"]:
                        continue
                    self.db.execute("UPDATE events SET args=? WHERE block=? AND log_index=?",
                                    (json.dumps(e["args"]), e["block"], e["log_index"]))
                else:
                    self.db.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                                    (e["block"], e["log_index"], e["block_hash"], e["event"], json.dumps(e["args"])))
                self._apply(e["event"], e["args"], e["block"], e["log_index"])
            self.db.execute("INSERT INTO discovery_ranges VALUES (?,?)", (end, end_hash))
        return True

    def _apply(self, event, a, block, log_index):
        if event == "PositionUpdated":
            id_ = str(a["listingId"])
            if a["state"] == 0:
                self.db.execute("DELETE FROM positions WHERE id=?", (id_,))
                self.db.execute("DELETE FROM returned WHERE id=?", (id_,))
            else:
                self.db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?)",
                                (id_, str(a["packId"]), str(a["value"]), str(a["backing"]),
                                 str(a["feeDebt"]).zfill(78), a["allocatedAt"], a["state"]))
            if a["state"] != 1:
                self.db.execute("DELETE FROM selected WHERE id=?", (id_,))
            self.db.execute("UPDATE returned SET ready=? WHERE id=?", (int(a["state"] != 3), id_))
        elif event == "InventoryUpdated":
            if a["value"] == 0:
                self.db.execute("DELETE FROM inventory WHERE pack_id=?", (str(a["packId"]),))
            else:
                self.db.execute("INSERT OR REPLACE INTO inventory VALUES (?,?,?,?)",
                                (str(a["packId"]), str(a["value"]), block, log_index))
        elif event == "RecoveryUpdated":
            if a["value"] == 0:
                self.db.execute("DELETE FROM recovery WHERE pack_id=?", (str(a["packId"]),))
            else:
                self.db.execute("INSERT OR REPLACE INTO recovery VALUES (?,?,?,?,?)",
                                (str(a["packId"]), str(a["value"]), int(a["unsealed"]), block, log_index))
        elif event == "CashReceipt":
            self.db.execute("INSERT OR REPLACE INTO receipts VALUES (?,?,?)",
                            (str(a["listingId"]), a["outcome"], str(a["amount"])))
        elif event == "ReceiptConsumed":
            self.db.execute("DELETE FROM receipts WHERE id=?", (str(a["listingId"]),))
        elif event == "JournalProgress":
            self.set_meta("cursor", a["cursor"])
        elif event == "NFTAllocated":
            self.db.execute("INSERT OR IGNORE INTO allocations VALUES (?,?,?)", (block, log_index, a["timestamp"]))
            if "listingId" in a:
                self.db.execute("INSERT OR REPLACE INTO selected SELECT ?,?,? WHERE EXISTS (SELECT 1 FROM positions WHERE id=? AND state=1)",
                                (str(a["listingId"]), block, log_index, str(a["listingId"])))
        elif event in BID_EVENTS:
            self.db.execute("INSERT OR REPLACE INTO returned SELECT ?,?,?,state<>3 FROM positions WHERE id=?",
                            (str(a["listingId"]), block, log_index, str(a["listingId"])))

    def candidates(self, active_limit, terminal_limit, now=None, settlement_window=0):
        # Each changed/expiry class gets a fixed quota; an unresolved older allocation cannot
        # hide a new return. None of these candidates replaces the vault's journal proof.
        due = [int(r[0]) for r in self.db.execute(
            "SELECT id FROM returned WHERE ready=1 ORDER BY block,log_index LIMIT ?",
            (terminal_limit,))]
        for r in self.db.execute("SELECT id FROM receipts LIMIT ?", (terminal_limit,)):
            if len(due) >= terminal_limit:
                break
            if int(r[0]) not in due:
                due.append(int(r[0]))
        due += [int(r[0]) for r in self.db.execute("SELECT id FROM selected ORDER BY block,log_index LIMIT ?", (terminal_limit,))]
        due += [int(r[0]) for r in self.db.execute(
            "SELECT id FROM positions WHERE state=2 AND allocated_at<=? ORDER BY allocated_at,id LIMIT ?",
            (now - settlement_window if now is not None else 2**63 - 1, terminal_limit))]
        # Booked-Allocated positions still inside the settlement window are status-checked each pass,
        # rotating and bounded: keeper.py reads each one's live FWA status, so an early keep or kick
        # whose payment FWA force-sent by SELFDESTRUCT (the account's receive reverted, no CashReceipt
        # event, pendingReceipts()==0) is still synced promptly instead of waiting for expiry.
        # Discovery never depends on CashReceipt. The complement of the expiry query above, so an
        # unexpired allocation inside the window cannot hide a terminal outcome at FWA.
        if now is not None:
            inside, after = now - settlement_window, self.meta("alloc_after", "")
            rows = self.db.execute(
                "SELECT id FROM positions WHERE state=2 AND allocated_at>? AND id>? ORDER BY id LIMIT ?",
                (inside, after, terminal_limit)).fetchall()
            if len(rows) < terminal_limit:
                rows += self.db.execute(
                    "SELECT id FROM positions WHERE state=2 AND allocated_at>? AND id<=? ORDER BY id LIMIT ?",
                    (inside, after, terminal_limit - len(rows))).fetchall()
            if rows:
                with self.db:
                    self.set_meta("alloc_after", rows[-1][0])
                due += [int(r[0]) for r in rows]
        after = self.meta("owed_after", "")
        owed = self.db.execute("SELECT id FROM positions WHERE state=3 AND id>? ORDER BY id LIMIT ?", (after, terminal_limit)).fetchall()
        if len(owed) < terminal_limit:
            owed += self.db.execute("SELECT id FROM positions WHERE state=3 AND id<=? ORDER BY id LIMIT ?", (after, terminal_limit - len(owed))).fetchall()
        if owed:
            with self.db:
                self.set_meta("owed_after", owed[-1][0])
            due += [int(r[0]) for r in owed]
        active = [int(r[0]) for r in self.db.execute(
            "SELECT id FROM positions WHERE state=1 ORDER BY debt,id LIMIT ?", (active_limit,))]
        return active, list(dict.fromkeys(due))

    def token_candidates(self, limit):
        """Bounded rotating active candidates. A restart continues the rotation, never rescans."""
        after = self.meta("token_after", "")
        rows = self.db.execute("SELECT id FROM positions WHERE state=1 AND id>? ORDER BY id LIMIT ?",
                               (after, limit)).fetchall()
        if len(rows) < limit:
            rows += self.db.execute("SELECT id FROM positions WHERE state=1 AND id<=? ORDER BY id LIMIT ?",
                                    (after, limit - len(rows))).fetchall()
        if rows:
            with self.db:
                self.set_meta("token_after", rows[-1][0])
        return [int(r[0]) for r in rows]

    def recent_volume(self, now):
        return self.db.execute("SELECT count(*) FROM allocations WHERE timestamp>=? AND timestamp<=?",
                               (now - 7 * 86400, now)).fetchone()[0] / 7

    def position(self, id_):
        row = self.db.execute("SELECT * FROM positions WHERE id=?", (str(id_),)).fetchone()
        return dict(row) if row else None

    def reserved(self, backing):
        return self.db.execute("SELECT 1 FROM positions WHERE backing=? AND state IN (1,2) LIMIT 1", (str(backing),)).fetchone() is not None

    def idle(self, limit):
        return [(int(r["pack_id"]), int(r["value"])) for r in self.db.execute(
            "SELECT * FROM inventory ORDER BY block DESC,log_index DESC LIMIT ?", (limit,))]
