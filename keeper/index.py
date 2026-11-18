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
TOPICS = {"0x" + keccak(text=f"{name}({','.join(t for _, t, _ in fields)})").hex(): (name, fields)
          for name, fields in EVENTS.items()}


def decode_log(log):
    if log.get("topics") and log["topics"][0] == ALLOCATION_TOPIC:
        return dict(event="NFTAllocated", args={"timestamp": log["_timestamp"]},
                    block=int(log["blockNumber"], 16), log_index=int(log["logIndex"], 16), block_hash=log["blockHash"])
    spec = TOPICS.get(log["topics"][0]) if log.get("topics") else None
    if spec is None:
        return None
    name, fields = spec
    topics = iter(log["topics"][1:])
    plain = iter(decode([t for _, t, indexed in fields if not indexed], bytes.fromhex(log["data"][2:])))
    values = {n: int.from_bytes(bytes.fromhex(next(topics)[2:]), "big") if indexed else next(plain)
              for n, _, indexed in fields}
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

    def repair(self, block_hash):
        """Check newest range, then walk back only on a reorg. block_hash reads canonical RPC."""
        keep = self.head
        for row in self.db.execute("SELECT end,hash FROM ranges ORDER BY end DESC"):
            if block_hash(row["end"]) == row["hash"]:
                keep = row["end"]
                break
            keep = self.start_block - 1
        if keep == self.head:
            return False
        self.rollback(keep)
        return True

    def rollback(self, end):
        """Restore a committed prefix atomically. Complete replay is only a repair operation."""
        with self.db:
            self.db.execute("DELETE FROM ranges WHERE end>?", (end,))
            self.db.execute("DELETE FROM events WHERE block>?", (self.head,))
            self.db.execute("DELETE FROM positions")
            self.db.execute("DELETE FROM inventory")
            self.db.execute("DELETE FROM recovery")
            self.db.execute("DELETE FROM receipts")
            self.db.execute("DELETE FROM allocations")
            self.db.execute("DELETE FROM meta WHERE key IN ('cursor','token_after')")
            for row in self.db.execute("SELECT * FROM events ORDER BY block,log_index").fetchall():
                self._apply(row["event"], json.loads(row["args"]), row["block"], row["log_index"])

    def append(self, start, end, end_hash, logs):
        if end < start:
            raise ValueError("invalid index range")
        events = [e for log in logs if (e := decode_log(log)) is not None]
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
        return True

    def _apply(self, event, a, block, log_index):
        if event == "PositionUpdated":
            id_ = str(a["listingId"])
            if a["state"] == 0:
                self.db.execute("DELETE FROM positions WHERE id=?", (id_,))
            else:
                self.db.execute("INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?)",
                                (id_, str(a["packId"]), str(a["value"]), str(a["backing"]),
                                 str(a["feeDebt"]).zfill(78), a["allocatedAt"], a["state"]))
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
            self.db.execute("INSERT INTO allocations VALUES (?,?,?)", (block, log_index, a["timestamp"]))

    def candidates(self, active_limit, terminal_limit):
        # Receipt candidates take priority, then oldest allocations/owed claims. Unchanged active
        # inventory is indexed, not hydrated; minimum debt also supplies the exact fee witness.
        due = [int(r[0]) for r in self.db.execute("SELECT id FROM receipts LIMIT ?", (terminal_limit,))]
        terminal = []
        for state in (2, 3):
            terminal += self.db.execute(
                "SELECT id,allocated_at FROM positions WHERE state=? ORDER BY allocated_at,id LIMIT ?",
                (state, terminal_limit)).fetchall()
        for r in sorted(terminal, key=lambda r: (r["allocated_at"], r["id"])):
            if int(r[0]) not in due:
                due.append(int(r[0]))
        active = [int(r[0]) for r in self.db.execute(
            "SELECT id FROM positions WHERE state=1 ORDER BY debt,id LIMIT ?", (active_limit,))]
        return active, due[:terminal_limit]

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
