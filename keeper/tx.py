"""Transaction execution for the PackVault keeper: one in-flight transaction per keeper address,
tracked in a state file so a restart, a lost RPC response or an uncertain broadcast never sends
the same work twice at a new nonce. Economic choices stay in keeper/policy.py; this module only
decides whether this keeper is willing to pay for a planned call and gets it mined.

Rules (adapted from shapes-pool-balancer keeper/keeper.ts, docs/KEEPER.md):
- Preflight: every call is estimated from the keeper's address first. A revert whose error means
  "state moved on" (EXPECTED) is a quiet skip; any other revert is reported as an error.
- The pending entry (nonce, call, fees) is saved before broadcasting. If the broadcast's response
  is lost, the entry stays and the next poll waits for the nonce, then resends at the same nonce.
- Pending longer than `replace_after` blocks: same-nonce replacement at +25% fees, at most
  `max_replacements` times, never above `max_fee` and only while the call still preflights.
- A receipt counts after `confirmations` blocks. Counted receipts stay re-checked for
  `reorg_window` blocks; one that disappears or moves block is reported and uncounted.
- One process per state file (flock). Other keepers are visible only through chain state: their
  completed work makes our preflight revert with an EXPECTED error.
- Keeper pay is read from the vault's KeeperPaid event in the receipt; net = pay - gasUsed x price.
"""
import fcntl
import json
import os
import subprocess
import time
import hashlib
import marshal
from pathlib import Path

from eth_utils import keccak

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def client_identity(modules):
    """Bind evidence to imported source and actual loaded function/method code."""
    result = {}
    for module in modules:
        if module is None:
            continue
        codes = {}
        for name, value in vars(module).items():
            if getattr(value, "__module__", None) != module.__name__:
                continue
            if hasattr(value, "__code__"):
                codes[name] = marshal.dumps(value.__code__).hex()
            elif isinstance(value, type):
                for method, function in vars(value).items():
                    if hasattr(function, "__code__"):
                        codes[name + "." + method] = marshal.dumps(function.__code__).hex()
        result[module.__name__] = dict(source_sha256_at_import=getattr(module, "SOURCE_SHA256", None),
                                      loaded_code_sha256=hashlib.sha256(json.dumps(codes, sort_keys=True).encode()).hexdigest())
    return result


KEEPER_PAID = "0x496b3bf0725d338a836ecf0b614e039f3736dacfd57aa32af1bf55ea601ceaf5"  # KeeperPaid(address,uint256)
EXPECTED = {  # selector -> name: the vault refused because the work is done, early or not allowed now
    "0xf9820cc1": "Nothing", "0xdc024d48": "NotCheckpointWindow",
    "0xcdda955f": "AlreadyCheckpointed", "0x9e87fac8": "Paused",
    "0x233d9570": "WindingDown", "0x46e807b5": "AllocatedExposure",
}

# A competitor may advance the journal, consume a receipt, change the fee witness or reserve a
# proposed backing between our pinned read and preflight. Refresh the index and quote again.
REFRESH_ERRORS = {"BadWitness", "InvalidBacking", "CatchUpFirst", "PendingReceipts", "NeedsPrune", "SyncFirst"}
EXPECTED.update({"0x" + keccak(text=f"{name}()").hex()[:8]: name for name in REFRESH_ERRORS})

ADMISSION_WAIT = {"InvalidListing", "EdgeGate", "InvalidBacking"}
ADMISSION_EXPECTED = {"0x" + keccak(text=f"{name}()").hex()[:8]: name for name in ADMISSION_WAIT}


class StaleContext(Exception):
    pass


def next_base_fee(header):
    """EIP1559 next basefee from the complete parent header, including integer/minimum rules."""
    number = lambda v: int(v, 0) if isinstance(v, str) and v.startswith("0x") else int(v)
    base, used, limit = (number(header[k]) for k in ("baseFeePerGas", "gasUsed", "gasLimit"))
    target = limit // 2
    if target <= 0:
        raise ValueError("invalid parent gas limit")
    if used == target:
        return base
    if used > target:
        return base + max(base * (used - target) // target // 8, 1)
    return base - base * (target - used) // target // 8


class Locked(Exception):
    pass


class TxManager:
    def __init__(self, rpc, state_file, sender, auth, confirmations=1, replace_after=3, max_replacements=5,
                 max_fee=None, reorg_window=64, log=print):
        self.rpc, self.path, self.sender, self.auth = rpc, state_file, sender, auth
        self.conf, self.replace_after, self.max_repl = confirmations, replace_after, max_replacements
        self.max_fee, self.reorg_window, self.log = max_fee, reorg_window, log
        self._lockf = open(state_file + ".lock", "w")
        try:
            fcntl.flock(self._lockf, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Locked(f"another keeper process holds {state_file}.lock")
        self.state = {"pending": None, "counted": [], "errors": [],
                      "stats": dict(sent=0, mined=0, reverted=0, replaced=0, dropped=0, reorged=0,
                                    skipped_expected=0, skipped_loss=0, spent_wei=0, paid_wei=0)}
        if os.path.exists(state_file):
            saved = json.load(open(state_file))
            self.state.update(saved)
            self.state["stats"] = {**self.state["stats"], **saved.get("stats", {})}

    # ------------------------------------------------------------------ plumbing

    def cast(self, *args):
        return subprocess.check_output(["cast", *map(str, args), "--rpc-url", self.rpc], text=True,
                                       stderr=subprocess.STDOUT).strip()

    def rpc_call(self, method, *params):
        out = self.cast("rpc", method, *[json.dumps(p) if not isinstance(p, str) else p for p in params])
        return json.loads(out) if out else None

    def save(self):
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(self.state, f, indent=1)
        os.replace(tmp, self.path)  # atomic

    def error(self, msg):
        self.state["errors"] = (self.state["errors"] + [{"t": int(time.time()), "msg": msg[:300]}])[-20:]
        self.log(f"error: {msg[:300]}")

    def head(self):
        return int(self.rpc_call("eth_blockNumber"), 16)

    def nonce(self, tag):
        return int(self.rpc_call("eth_getTransactionCount", self.sender, tag), 16)

    # ------------------------------------------------------------------ preflight and send

    def preflight(self, to, args, fees=()):
        """Gas estimate from the keeper's address, or (None, reason, expected?)."""
        try:
            if not fees:
                pending = self.rpc_call("eth_getBlockByNumber", "pending", False)
                base = int(pending["baseFeePerGas"], 16)
                fees = ["--gas-price", str(2 * base + 1), "--priority-gas-price", "1"]
            estimate = int(self.cast("estimate", to, *args, "--from", self.sender, "--block", "pending", *fees).split()[0])
            if (estimate * 5 + 3) // 4 > 16_777_216:
                return None, "25% gas margin exceeds EIP7825 transaction limit", False
            return estimate, "", True
        except subprocess.CalledProcessError as e:
            msg = (e.output or "").strip()
            expected = dict(EXPECTED)
            if args and args[0].split("(")[0] in ("list", "restock"):
                expected.update(ADMISSION_EXPECTED)
            for sel, name in expected.items():
                if sel in msg or f"{name}()" in msg:  # selector or decoded name, never the bare word
                    return None, name, True
            return None, msg.splitlines()[-1][:200] if msg else "estimate failed", False

    def _broadcast(self, p):
        out = self.cast("send", p["to"], *p["args"], *self.auth, "--nonce", p["nonce"], "--gas-limit", p["gas"],
                        "--priority-gas-price", p["prio"], "--gas-price", p["max_fee"], "--async")
        h = out.split()[-1]
        if not h.startswith("0x") or len(h) != 66:
            raise subprocess.CalledProcessError(1, "cast send", output=out)
        return h

    def submit(self, label, to, args, est, base_fee, tip, expected_pay, expected_parent=None):
        """Save, then broadcast. A failed broadcast keeps the entry: the nonce may be in flight."""
        if expected_parent is not None and self.rpc_call("eth_getBlockByNumber", "latest", False)["hash"] != expected_parent:
            raise StaleContext("head changed after prospective quote; refresh before broadcast")
        max_fee = 2 * base_fee + tip
        if self.max_fee is not None:
            max_fee = min(max_fee, self.max_fee)
        p = dict(label=label, to=to, args=[str(a) for a in args], nonce=self.nonce("pending"), gas=(est * 5 + 3) // 4,
                 est=est, prio=tip, max_fee=max_fee, sent_block=self.head(), replacements=0, hashes=[],
                 expected_pay=expected_pay, submitted=int(time.time()))
        self.state["pending"] = p
        self.save()
        try:
            p["hashes"].append(self._broadcast(p))
            self.state["stats"]["sent"] += 1
            self.log(f"sent {label} nonce {p['nonce']} hash {p['hashes'][-1]}")
        except subprocess.CalledProcessError as e:
            self.error(f"broadcast of {label} uncertain (nonce {p['nonce']} kept pending): {(e.output or '').strip()}")
        self.save()

    # ------------------------------------------------------------------ resolution

    def _receipt(self, h):
        return self.rpc_call("eth_getTransactionReceipt", h)

    def _count(self, p, h, r):
        # A re-included hash replaces its orphan record; otherwise reorg polling counts it twice.
        for old in self.state["counted"]:
            if old["hash"] == h and not old.get("reorged"):
                self._apply(old, -1)
        self.state["counted"] = [old for old in self.state["counted"] if old["hash"] != h]
        gas_used, price = int(r["gasUsed"], 16), int(r["effectiveGasPrice"], 16)
        pay = sum(int(l["data"], 16) for l in r["logs"]
                  if l["topics"] and l["topics"][0] == KEEPER_PAID and l["address"].lower() == p["to"].lower()
                  and l["topics"][1][-40:].lower() == self.sender[2:].lower())
        ok = int(r["status"], 16) == 1
        s = self.state["stats"]
        s["mined" if ok else "reverted"] += 1
        s["spent_wei"] += gas_used * price
        s["paid_wei"] += pay
        entry = dict(label=p["label"], to=p["to"], hash=h, block=int(r["blockNumber"], 16), block_hash=r["blockHash"],
                     status=int(ok), gas_used=gas_used, price=price, cost=gas_used * price, pay=pay,
                     net=pay - gas_used * price, est=p["est"], gas_limit=p["gas"], expected_pay=p["expected_pay"])
        self.state["counted"] = (self.state["counted"] + [entry])[-200:]
        self.log(f"{'mined' if ok else 'REVERTED'} {p['label']} gas {gas_used} (est {p['est']}) cost {gas_used * price} "
                 f"pay {pay} net {pay - gas_used * price} wei")
        if not ok:
            self.error(f"{p['label']} reverted on chain: {h}")
        return entry

    def _find_by_nonce(self, p, head):
        # From the send block on (bounded): a lost response followed by downtime still finds it.
        for b in range(max(p["sent_block"], head - 5_000), head + 1):
            blk = self.rpc_call("eth_getBlockByNumber", hex(b), True)
            for t in (blk or {}).get("transactions", []):
                if t["from"].lower() == self.sender.lower() and int(t["nonce"], 16) == p["nonce"]:
                    return t["hash"] if (t.get("to") or "").lower() == p["to"].lower() else None
        return None

    def _apply(self, e, sign):
        st = self.state["stats"]
        st["mined" if e["status"] else "reverted"] += sign
        st["spent_wei"] += sign * e["cost"]
        st["paid_wei"] += sign * e["pay"]

    def check_reorgs(self, head):
        """Keep counted receipts on the canonical chain for `reorg_window` blocks: one that
        disappears is uncounted; one re-included (same hash, any block) is counted again from its
        new receipt, whose gas, status and pay may differ."""
        for e in self.state["counted"]:
            if head - e["block"] > self.reorg_window:
                continue
            r = self._receipt(e["hash"])
            if r is None:
                if not e.get("reorged"):
                    e["reorged"] = True
                    self._apply(e, -1)
                    self.state["stats"]["reorged"] += 1
                    self.error(f"reorg: {e['label']} {e['hash']} no longer in block {e['block']}; chain state is re-read")
                continue
            if r["blockHash"] == e["block_hash"] and not e.get("reorged"):
                continue
            if not e.get("reorged"):
                self._apply(e, -1)
            gas_used, price = int(r["gasUsed"], 16), int(r["effectiveGasPrice"], 16)
            pay = sum(int(l["data"], 16) for l in r["logs"]
                      if l["topics"] and l["topics"][0] == KEEPER_PAID and l["address"].lower() == e["to"].lower()
                      and l["topics"][1][-40:].lower() == self.sender[2:].lower())
            e.update(block=int(r["blockNumber"], 16), block_hash=r["blockHash"], status=int(int(r["status"], 16) == 1),
                     gas_used=gas_used, price=price, cost=gas_used * price, pay=pay, net=pay - gas_used * price, reorged=False)
            self._apply(e, 1)
            self.log(f"reorg moved {e['label']} {e['hash']} to block {e['block']}; recounted")

    def resolve(self, still_wanted):
        """Advance the in-flight transaction. Returns True while one remains in flight.
        `still_wanted(p, prio, max_fee)` preflights the same call again and re-checks profit at the
        replacement's fees (None if the work is gone or no longer worth it)."""
        p = self.state["pending"]
        if not p:
            return False
        head = self.head()
        for h in p["hashes"]:
            r = self._receipt(h)
            if r and head - int(r["blockNumber"], 16) + 1 >= self.conf:
                self._count(p, h, r)
                self.state["pending"] = None
                self.save()
                return False
            if r:
                return True  # mined, waiting for confirmations
        if self.nonce("latest") > p["nonce"]:
            # The nonce was used by a transaction we hold no hash for: a broadcast whose response
            # was lost, or another process with this key. Find it to account for it; either way
            # nothing is resent and chain state is re-read next pass. Our own hashes are checked
            # again first: the block may have landed between the receipt and nonce reads.
            head = self.head()
            h = next((x for x in p["hashes"] if self._receipt(x)), None) or self._find_by_nonce(p, head)
            if h:
                self._count(p, h, self._receipt(h))
                self.state["pending"] = None
                self.save()
                return False
            self.state["stats"]["dropped"] += 1
            self.log(f"nonce {p['nonce']} used by an untracked transaction; {p['label']} dropped from tracking")
            self.state["pending"] = None
            self.save()
            return False
        if head - p["sent_block"] < self.replace_after:
            return True
        if p["replacements"] >= self.max_repl:
            self.error(f"{p['label']} nonce {p['nonce']} still pending after {p['replacements']} replacements")
            return True
        base = int(self.rpc_call("eth_getBlockByNumber", "latest", False)["baseFeePerGas"], 16)
        prio = p["prio"] * 125 // 100 + 1
        max_fee = max(p["max_fee"] * 125 // 100 + 1, 2 * base + prio)
        if self.max_fee is not None and max_fee > self.max_fee:
            self.log(f"waiting: replacing {p['label']} would bid above the {self.max_fee} wei cap")
            return True
        estimate = still_wanted(p, prio, max_fee)
        if estimate is None:
            # Never confirmed broadcast and no longer needed: forget it. If the lost broadcast did
            # land, it sits at this nonce doing work that is gone (it reverts); the next submit
            # takes the following nonce. No work runs twice.
            if not p["hashes"]:
                self.log(f"{p['label']} (unconfirmed broadcast) no longer needed; tracking cleared")
                self.state["pending"] = None
                self.save()
                return False
            # Someone else did the work: the old transaction will revert or be dropped. Keep waiting
            # on it rather than paying more for a call that now fails.
            self.log(f"{p['label']} no longer needed; waiting for nonce {p['nonce']} to clear")
            return True
        gas = (estimate * 5 + 3) // 4
        if gas > 16_777_216:
            self.error(f"replacement of {p['label']} needs gas above the EIP7825 bound")
            return True
        # The attempt and current estimate survive an accepted broadcast whose response is lost.
        p.update(prio=prio, max_fee=max_fee, sent_block=head, est=estimate, gas=gas,
                 replacements=p["replacements"] + 1)
        self.save()
        try:
            first = not p["hashes"]
            p["hashes"].append(self._broadcast(p))
            self.state["stats"]["sent" if first else "replaced"] += 1
            self.log(f"{'sent' if first else 'replaced'} {p['label']} nonce {p['nonce']} max fee {max_fee} prio {prio}")
        except subprocess.CalledProcessError as e:
            self.error(f"replacement of {p['label']} failed: {(e.output or '').strip()}")
        self.save()
        return True

    def wait(self, still_wanted, timeout, poll=2.0):
        """Resolve until nothing is in flight or `timeout` seconds pass."""
        end = time.time() + timeout
        while self.resolve(still_wanted):
            if time.time() >= end:
                return True
            time.sleep(poll)
        return False
