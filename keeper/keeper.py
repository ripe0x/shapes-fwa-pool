#!/usr/bin/env python3
"""Reference keeper for PackVault. Each pass reads live chain state, asks keeper/policy.py what
is worth doing and prints or sends those calls one at a time, re-reading state after each.
Decisions come from chain state alone; keeper/tx.py tracks the one in-flight transaction in a
state file so restarts, lost responses and stuck transactions resolve at the same nonce.

Usage:
  keeper/keeper.py <vault>                                    # print status and the plan
  keeper/keeper.py <vault> --status                           # status, in-flight tx, keeper P&L
  keeper/keeper.py <vault> --send --account <keystore-name>   # sign through a cast keystore
  keeper/keeper.py <vault> --send --from <addr> --rpc http://127.0.0.1:8545   # local rehearsal
  --loop 300 repeats every 300 s; --health-port 8788 serves GET /health; --max-loss-wei N lets
  liability work above the vault's gas ceiling cost this keeper up to N wei per call (default 0:
  wait); --burn-tokens claims and burns FWA token rewards at the operator's cost.
  Operations and recovery: docs/KEEPER.md.

This script never sees a key: cast signs (keystore password from cast's own prompt or env).
"""
import argparse
import json
import hashlib
import subprocess
import sys
import threading
from dataclasses import replace
import re
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import policy  # noqa: E402
from config import PARAMS_T, decode_params, gas_schedule
import tx as txm  # noqa: E402
import index as event_index  # noqa: E402

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
RPC = "https://mainnet.gateway.tenderly.co"
FWA = "0x958C41181182e76F221331b2755b77D9e1426A98"
SHAPES = "0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0"
LISTING_T = "(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)"


def cast(*args):
    try:
        return subprocess.check_output(["cast", *map(str, args), "--rpc-url", RPC], text=True, stderr=subprocess.PIPE).strip()
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise


def call(to, sig, *args, block=None, fees=()):
    extra = ["--block", str(block)] if block is not None else []
    return cast("call", to, sig, *args, *extra, *fees)


def num(v):
    v = v.split(" ")[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def lines(out):
    return [x for x in out.splitlines() if x]


def ids_of(out):
    out = out.strip("[]")
    return [num(x.strip()) for x in out.split(",") if x.strip()]




INDEXES = {}
INDEX_PATH = None
MAX_LOG_RANGE = 2_000
MAX_LOG_RANGES = 8
MAX_DISCOVERY_RANGE = 50_000
MAX_CANDIDATES = 16


class IndexBehind(RuntimeError):
    pass


def rpc(method, *params):
    return json.loads(cast("rpc", method, *[json.dumps(p) if not isinstance(p, str) else p for p in params]))


def quantity(v):
    return int(v, 0) if isinstance(v, str) and v.startswith("0x") else int(v)


def block_hash(number):
    b = rpc("eth_getBlockByNumber", hex(number), False)
    return b["hash"] if b else None


def sync_index(index, head):
    index.repair(block_hash)
    for _ in range(MAX_LOG_RANGES):
        if index.head >= head:
            break
        start, end = index.head + 1, min(index.head + MAX_LOG_RANGE, head)
        before = block_hash(end)
        logs = rpc("eth_getLogs", {"address": [index.vault, FWA], "fromBlock": hex(start), "toBlock": hex(end),
                                   "topics": [list(event_index.TOPICS) + list(event_index.BID_TOPICS) + [event_index.ALLOCATION_TOPIC]]})
        timestamps = {}
        for log in logs:
            if log["topics"][0] == event_index.ALLOCATION_TOPIC:
                number = quantity(log["blockNumber"])
                if number not in timestamps:
                    b = rpc("eth_getBlockByNumber", hex(number), False)
                    if b["hash"] != log["blockHash"]:
                        raise RuntimeError("allocation log block changed; retry range")
                    timestamps[number] = quantity(b["timestamp"])
                log["_timestamp"] = timestamps[number]
        if not before or block_hash(end) != before:
            raise RuntimeError("chain changed while reading event range; retry the pinned snapshot")
        index.append(start, end, before, logs)
    if index.head < head:
        raise IndexBehind(f"event index at block {index.head}; target {head}; next pass resumes bounded replay")
    sync_discovery(index, head)


def sync_discovery(index, head):
    # Older indexes did not subscribe to bids or retain own allocation IDs. Replay only
    # those FWA channels; preserve their financial projection and transaction state.
    span = min(MAX_DISCOVERY_RANGE, max(1, int(index.meta("discovery_span", MAX_DISCOVERY_RANGE))))
    for _ in range(MAX_LOG_RANGES):
        if index.discovery_head >= head:
            return
        start, end = index.discovery_head + 1, min(index.discovery_head + span, head)
        before = block_hash(end)
        try:
            bids = rpc("eth_getLogs", {"address": FWA, "fromBlock": hex(start), "toBlock": hex(end),
                                       "topics": [list(event_index.BID_TOPICS), None, None,
                                                  "0x" + index.vault[2:].lower().zfill(64)]})
            allocations = rpc("eth_getLogs", {"address": FWA, "fromBlock": hex(start), "toBlock": hex(end),
                                              "topics": [event_index.ALLOCATION_TOPIC]})
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or "").lower()
            if span > 1 and any(s in detail for s in ("too many results", "query returned more than", "response size", "block range")):
                span = max(1, span // 2)
                with index.db:
                    index.set_meta("discovery_span", span)
                continue  # Each smaller attempt consumes the same fixed pass budget.
            raise
        timestamps = {}
        own = [log for log in allocations if event_index.own_allocation(log, index.vault)]
        for log in own:
            timestamp = index.allocation_timestamp(log)
            if timestamp is None:
                number = quantity(log["blockNumber"])
                if number not in timestamps:
                    b = rpc("eth_getBlockByNumber", hex(number), False)
                    if b["hash"] != log["blockHash"]:
                        raise RuntimeError("allocation replay block changed; retry range")
                    timestamps[number] = quantity(b["timestamp"])
                timestamp = timestamps[number]
            log["_timestamp"] = timestamp
        if not before or block_hash(end) != before:
            raise RuntimeError("chain changed while replaying discovery events")
        index.append_discovery(start, end, before, bids + own)
    if index.discovery_head < head:
        raise IndexBehind(f"return/selection replay at block {index.discovery_head}; target {head}; existing financial index preserved")


def first_block_at(timestamp, head):
    lo, hi = 1, head
    while lo < hi:
        mid = (lo + hi) // 2
        b = rpc("eth_getBlockByNumber", hex(mid), False)
        if quantity(b["timestamp"]) < timestamp:
            lo = mid + 1
        else:
            hi = mid
    return lo


def get_index(vault, block, now):
    chain = quantity(rpc("eth_chainId"))
    deployment = num(call(vault, "deploymentBlock()(uint256)", block=block))
    # One index per account, in --index (a directory) or beside this file.
    path = str(Path(INDEX_PATH or Path(__file__).parent) / f"index-{chain}-{vault.lower()}-{deployment}.sqlite")
    key = (path, chain, vault.lower(), deployment)
    if key not in INDEXES:
        INDEXES[key] = event_index.EventIndex(path, chain, vault, deployment,
                                             lambda: first_block_at(now - 7 * 86400, block))
    index = INDEXES[key]
    index.vault = vault
    sync_index(index, block)
    return index


def inclusion_context():
    """Authenticate prospective execution BASEFEE, not just a provider's pending header label."""
    parent = rpc("eth_getBlockByNumber", "latest", False)
    pending = rpc("eth_getBlockByNumber", "pending", False)
    expected = txm.next_base_fee(parent)
    if (quantity(pending["number"]) != quantity(parent["number"]) + 1
            or pending["parentHash"] != parent["hash"] or quantity(pending["baseFeePerGas"]) != expected):
        raise txm.StaleContext("pending header is not the deterministic next block; retry context")
    # Read-only contract-creation simulation: BASEFEE; mstore(0); return32bytes. This deploys
    # nothing and supplies no external service answer or protocol state override.
    executed = quantity(rpc("eth_call", {"data": "0x485f5260205ff3", "from": "0x" + "00" * 20, "gas": hex(100_000),
                                        "maxFeePerGas": hex(2 * expected + 50_000_000),
                                        "maxPriorityFeePerGas": hex(50_000_000)}, "pending"))
    if executed != expected:
        if rpc("eth_getBlockByNumber", "latest", False)["hash"] != parent["hash"]:
            raise txm.StaleContext("head changed during pending context authentication")
        raise RuntimeError("RPC pending eth_call executes at the wrong basefee; admission disabled")
    return parent, expected


def stable_read_state(vault, slowdown, burn=False, pooled=True):
    for attempt in range(3):
        try:
            return read_state(vault, slowdown, burn, pooled)
        except txm.StaleContext:
            if attempt == 2:
                raise


def build_units_for(mask, design=0, held=None):
    """The pack size this keeper builds and how many more of it the account's design allows.

    design 0: REF_UNITS when the mask admits it, else the smallest admitted size, without a count.
    Otherwise the admitted size furthest below its design count (`held[u]` packs held), the
    smaller size on a tie; (0, 0) once every size is at its count."""
    if not design:
        if (mask >> policy.REF_UNITS) & 1:
            return policy.REF_UNITS, None
        return next((u for u in range(policy.MIN_PACK_UNITS, policy.MAX_PACK_UNITS + 1) if (mask >> u) & 1), 0), None
    room = {u: (design >> 8 * u & 0xFF) - held.get(u, 0) for u in range(policy.MIN_PACK_UNITS, policy.MAX_PACK_UNITS + 1)
            if (mask >> u) & 1 and design >> 8 * u & 0xFF}
    best = max(room, key=lambda u: (room[u], -u), default=0)
    return (best, room[best]) if best and room[best] > 0 else (0, 0)


def read_tokens(vault, candidate_ids, block):
    """Optional bounded candidates only; token value never enters NAV."""
    rewards = call(FWA, "rewards()(address)", block=block)
    token = call(FWA, "token()(address)", block=block)
    pend = {i: num(call(rewards, "pendingDepositorTokens(uint256)(uint256)", i, block=block))
            for i in candidate_ids[:policy.MAX_BATCH["tokens"]]}
    return dict(token_pending=sum(pend.values()), token_ids=[i for i, v in pend.items() if v],
                token_credit=num(call(rewards, "tokenCredit(address)(uint256)", vault, block=block)),
                token_held=num(call(token, "balanceOf(address)(uint256)", vault, block=block)))


def proposal_limits(s, value, settlement_fee, discount, cap, build=False, units=policy.REF_UNITS, retirement_shapes=None):
    """VaultLib._profitable floors for a listing near the edge's desired backing; production preflight
    authenticates each one. A keep must return at least the face, B(k-s) >= value, and the NAV face
    coverage holds at FWA's maximum settlement fee. Gas and the build are not charged to a selection."""
    if s.k <= 10**18 or not 0 < discount <= 10_000 or not 0 <= settlement_fee < 10_000:
        return 1, 0
    up = lambda a, b: -(-a // b)
    minimum = max(up(value * 10_000, 9500), up(value * 10**18, s.k - settlement_fee * 10**14))
    return minimum, cap


def validate_configuration_context(pinned, prospective):
    if pinned.lower() != prospective.lower():
        raise txm.StaleContext('configuration or mint fee changed after pinned hydration; refresh before planning')


def read_state(vault, slowdown, burn=False, pooled=True):
    # Cash, book, candidate hydration and log prefix share this pinned block. Prospective
    # admission prices later use one authenticated next-block execution context. `pooled` is False
    # for a personal PackManager, which has no shares, deposits, redemptions, checkpoints or
    # distributions: those pool-only views do not exist on it and must not be read.
    header = rpc("eth_getBlockByNumber", "latest", False)
    head, now, base_fee = (quantity(header[k]) for k in ("number", "timestamp", "baseFeePerGas"))
    index = get_index(vault, head, now)
    at = lambda to, sig, *args: call(to, sig, *args, block=head)
    account_owner = at(vault, 'owner()(address)') if not pooled else None
    p = decode_params(at(vault, f"getParams()({PARAMS_T})"))
    min_edge, buf, dist_bps = (p[k] for k in ('minEdgeBps', 'bufferBps', 'distributionBps'))
    premium, share, mask = (p[k] for k in ('payMarkupBps', 'keeperShareBps', 'packUnitsMask'))
    ceiling, ess_ceiling, tip, wfee, res = (p[k] for k in ('gasCeilingWei', 'essentialCeilingWei', 'maxTipWei', 'workFeeWei', 'reserveWei'))
    _ec = p['essentialCapWei']
    design = num(at(vault, 'design()(uint256)'))
    held = {u: num(at(vault, 'recipeCount(uint256)(uint256)', u)) for u in range(policy.MIN_PACK_UNITS, policy.MAX_PACK_UNITS + 1)
            if design >> 8 * u & 0xFF}
    build_units, build_room = build_units_for(mask, design, held)
    idle_count = num(at(vault, 'idlePackCount()(uint256)'))
    idle_ids = [num(at(vault, 'idlePackAt(uint256)(uint256)', idle_count-1-i)) for i in range(min(idle_count, policy.MAX_BATCH['list']))]
    idle_candidates = [(i, num(at(vault, 'idleValueOf(uint256)(uint256)', i))) for i in idle_ids]
    quote_units = build_units or (idle_candidates[0][1] // policy.UNIT if idle_candidates else policy.REF_UNITS)
    rbud, ebud = lines(at(vault, "budget()(uint256,uint256)"))
    k, backing = "0", "0"  # prospective economics are read after pinned financial hydration
    window = num(at(FWA, "settlementWindow()(uint256)"))
    top, top_since = num(at(FWA, "topListingId()(uint256)")), num(at(FWA, "topListingSince()(uint64)"))
    active_ids, terminal_ids = index.candidates(MAX_CANDIDATES, MAX_CANDIDATES, now, window)
    listings, witness, own_journal_pending = [], 0, False
    for i in dict.fromkeys(terminal_ids + active_ids):
        f = at(FWA, f"listings(uint256)({LISTING_T})", i).strip("()").split(", ")
        status, allocated_at = num(f[10]), num(f[9])
        pend = num(at(FWA, "pendingFees(uint256)(uint256)", i)) if status == policy.ACTIVE else 0
        owed = status in (policy.SETTLED, policy.WITHDRAWN) and \
            at(FWA, "stuckNFTRecipient(uint256)(address)", i).lower() == vault.lower()
        if status == policy.ACTIVE and not witness:
            witness = i  # candidates are minimum cached debt first
        cached = index.position(i)
        unapplied = bool(cached and cached["state"] == 1 and status in (policy.ALLOCATED, policy.SETTLED))
        own_journal_pending |= unapplied
        listings.append(policy.Listing(i, status, allocated_at, pend, owed,
                                       crown_locked=(i == top and now < top_since + 12 * 3600),
                                       value=int(cached["value"]) if cached else 0, backing=num(f[5]),
                                       unapplied=unapplied))
    total = [num(x) for x in lines(at(vault, "totals()(uint256,uint256,uint256,uint256,uint256,uint256)"))]
    allocation = lines(at(vault, "allocationState()(uint256,uint256,uint256,uint64,bool)"))
    balance = quantity(rpc("eth_getBalance", vault, hex(head)))
    # Pool-only holder accounting; a personal manager owes nothing and exposes none of these views.
    pending = processing_pool = reserves = locked = supply = owed = 0
    checkpoint_done = False
    if pooled:
        pending = num(at(vault, "pendingDepositTotal()(uint256)"))
        processing_pool = num(at(vault, "processingPool()(uint256)"))
        reserves = pending + num(at(vault, "redemptionReserve()(uint256)")) + \
            num(at(vault, "distributionReserve()(uint256)")) + num(at(vault, "claimableTotal()(uint256)")) + processing_pool + num(at(vault, "chargeRefundReserve()(uint256)"))
        locked = num(at(vault, "lockedShares()(uint256)"))
        supply = num(at(vault, "totalShares()(uint256)"))
        if locked:
            owed = -(-locked * num(at(vault, "lastNav()(uint256)")) // supply)
        checkpoint_done = num(at(vault, "lastCheckpointInterval()(uint256)")) == now // (12 * 3600)
    tokens = read_tokens(vault, index.token_candidates(policy.MAX_BATCH["tokens"]) if burn else [], head)
    state = policy.State(
        now=now, gas_price=base_fee + tip, base_fee=base_fee, gas_ceiling=ceiling,
        max_tip=tip, markup_bps=premium, share_bps=share, k=num(k), backing=num(backing), min_edge_bps=min_edge,
        mint_fee=num(at(SHAPES, "mintFee()(uint256)")), settlement_window=window,
        blackout=at(FWA, "isPurchaseBlackout()(bool)") == "true",
        queue_drained=num(at(FWA, "unsettledAcquisitionCount()(uint256)")) == 0,
        checkpoint_done_this_interval=checkpoint_done,
        listings=listings, idle_packs=num(at(vault, "idlePackCount()(uint256)")), idle_value=total[1],
        idle_funding=num(at(vault, "idleFunding()(uint256)")),
        recovery_packs=num(at(vault, "recoveryPackCount()(uint256)")),
        free=max(0, balance - reserves), idle_eth=num(at(vault, "idleEth()(uint256)")), owed_estimate=owed,
        pending_deposits=pending, locked_shares=locked, total_shares=supply, pack_units_mask=mask,
        build_units=build_units, build_room=build_room, pooled=pooled, settlement_fee_bps=num(at(FWA, "ownerSettlementFeeBps()(uint256)")),
        essential_ceiling=ess_ceiling, essential_cap=_ec, processing_pool=processing_pool,
        gas_schedule=gas_schedule(p), backing_ratio_bps=p["backingRatioBps"],
        accepted_mint_fee=p["acceptedMintFeeWei"],
        fee_credit=num(at(FWA, "feeCredit(address)(uint256)", vault)),
        open_positions=num(at(vault, "openListingCount()(uint256)")), active_count=total[3], witness_id=witness,
        journal_cursor=num(at(vault, "acquisitionCursor()(uint64)")),
        completed_prefix=num(at(FWA, "nextSequenceToProcess()(uint64)")),
        pending_receipts=num(at(vault, "pendingReceipts()(uint256)")), allocation_stale=allocation[4] == "true",
        own_journal_pending=own_journal_pending,
        winding_down=at(vault, "windingDown()(bool)") == "true",
        listing_paused=at(vault, "listingPaused()(bool)") == "true", distribution_bps=dist_bps,
        recent_volume=index.recent_volume(now), slowdown_volume=slowdown, burn_tokens=burn,
        reserve=res, work_fee=wfee, routine_budget=num(rbud), essential_budget=num(ebud), **tokens,
    )
    state.keeper_cash = num(at(vault, "keeperCash()(uint256)"))
    state.operating_reserve = res
    state.configuration_hash = at(vault, "configurationHash()(bytes32)")
    state.account_owner = account_owner
    state.request_funding_needed = policy.request_charge(state) if pooled and (pending or locked) else 0
    prospective_parent, future_base_fee = inclusion_context()
    # Financial candidates may come from a canonical ancestor while pricing uses the current
    # pending block. The full pending call authenticates capital, eligibility and payment.
    state.base_fee = future_base_fee
    state.gas_price = future_base_fee + tip
    state.pending_parent = prospective_parent["hash"]
    prospective = lambda to, sig, *args: call(to, sig, *args, block="pending", fees=fee_args(future_base_fee, tip))
    try:
        future_k, future_backing, _ = lines(prospective(vault, "edge(uint256)(uint256,uint256,bool)", quote_units))
        state.k, state.backing = num(future_k), num(future_backing)
    except subprocess.CalledProcessError:
        state.k, state.backing = 0, 0
    pending_configuration = prospective(vault, "configurationHash()(bytes32)")
    validate_configuration_context(state.configuration_hash, pending_configuration)
    if pooled and (pending or locked):
        state.request_funding_needed = num(prospective(vault, 'requestCharge()(uint256)'))
    # A distribution-only checkpoint is due when this exact pinned simulation succeeds (pool only).
    if pooled and dist_bps and not pending and not locked:
        try:
            prospective(vault, "checkpoint(uint256,uint256,bytes32)(uint256)", witness, 0, state.configuration_hash)
            state.distribution_due = True
        except subprocess.CalledProcessError:
            pass
    if (state.backing or idle_candidates) and state.gas_price <= state.gas_ceiling and not state.winding_down \
            and not state.listing_paused and state.queue_drained:
        packs = prospective(vault, "packs()(address)")
        fee, discount = num(prospective(FWA, "ownerSettlementFeeBps()(uint256)")), num(prospective(FWA, "settlementDiscountBps()(uint256)"))
        cap = 2**256 - 1
        if prospective(FWA, "oracleExemptCollections(address)(bool)", packs) != "true":
            oracle = prospective(FWA, "floorOracle()(address)")
            _, ask, _, _ = lines(prospective(oracle, "getFloorRange(address)(uint256,uint256,uint48,uint48)", packs))
            cap = num(ask) * (10_000 + num(prospective(FWA, "oracleCeilingPremiumBps()(uint256)"))) // 10_000
            cap = cap * (10_000 - buf) // 10_000
        reserved = num(prospective(vault, "reservedCount()(uint256)"))
        lo, hi = proposal_limits(state, build_units * policy.UNIT, fee, discount, cap, build=True, units=build_units)
        # build lists every pack at once: each proposal must be a distinct identifier inside the
        # interval the contract widens by one quantum per admission (reservedCount + i + 1).
        state.build_proposals = policy.propose_backings(state.backing, reserved, policy.MAX_BATCH["build"],
                                                        index.reserved, lo, hi, head) if build_units else []
        chosen = []
        state.relistable_idle = 0
        for pack_id, value in idle_candidates:
            state.relistable_idle += 1
            units = value // policy.UNIT
            _, target, ok = lines(prospective(vault, "relistEdgeFor(uint256)(uint256,uint256,bool)", pack_id))
            if ok != "true":
                break
            lo, hi = proposal_limits(state, value, fee, discount, cap, units=units, retirement_shapes=num(at(vault,"inventoryShapeCount(uint256)(uint256)",pack_id)))
            proposal = policy.propose_backings(num(target), reserved + len(chosen), 1,
                                               lambda b: b in chosen or index.reserved(b), lo, hi, head)
            if not proposal:
                break
            # Authenticate only bounded proposed amounts; another keeper may have won since
            # indexing. The final preflight also refreshes economics, witness and uniqueness.
            if num(prospective(vault, "idForBacking(uint256)(uint256)", proposal[0])):
                break
            chosen += proposal
        state.backing_proposals = chosen
    if block_hash(head) != header["hash"]:
        raise txm.StaleContext("pinned state block was reorganized; retry snapshot")
    if rpc("eth_getBlockByNumber", "latest", False)["hash"] != prospective_parent["hash"]:
        raise txm.StaleContext("head changed during prospective pricing; refresh quote")
    return state

def to_cast(step, min_pay=0, expected=None, caller_funded=False):
    """Encode the reviewed configuration alongside every guarded operation."""
    fn, *args = step
    array = lambda xs: "[" + ",".join(map(str, xs)) + "]"
    expected = expected or "0x" + "00" * 32
    if fn == 'setExiting':
        return ['setExiting(bool)', 'true' if args[0] else 'false']
    if fn == 'withdraw':
        return ['withdraw(address,uint256)', args[0], args[1]]
    if fn == 'processAcquisitions':
        if not caller_funded or args != [16]:
            raise ValueError('protocol queue progress requires explicit caller funding and a batch of16')
        return ['processAcquisitions(uint256)', 16]
    if caller_funded:
        if fn == 'checkpoint':
            return ['recoverCheckpoint(uint256)', args[0]]
        if fn in ('sync', 'syncCheckpoint'):
            return ['recover(uint256[],uint256)', array(args[0]), args[1]]
        if fn == 'unlist':
            return ['recoverUnlist(uint256[])', array(args[0])]
        if fn == 'liquidate':
            return ['recoverLiquidate(uint256)', args[0]]
    if fn in ('claim', 'cancelDeposit'):
        return [fn + '()']
    if fn == 'requestRedeem':
        return ['requestRedeem(uint256,bytes32)', args[0], expected, '--value', args[1]]
    if fn == 'claimCheckpointRefund':
        return ['claimCheckpointRefund(uint256[])', array(args[0])]
    if fn == "burnTokens":
        return ["burnTokens(uint256[])", array(args[0])]
    if fn == "fundCheckpoint":
        return ["fundCheckpoint(bytes32)", expected, "--value", args[0]]
    if fn == "harvest":
        return ["harvest(uint256[],uint256)", array(args[0]), min_pay]
    if fn in ("unlist", "list"):
        return [f"{fn}(uint256[],uint256,bytes32)", array(args[0]), min_pay, expected]
    if fn in ("sync", "syncCheckpoint"):
        return [f"{fn}(uint256[],uint256,uint256,bytes32)", array(args[0]), args[1], min_pay, expected]
    if fn == "liquidate":
        return ["liquidate(uint256,uint256,bytes32)", args[0], min_pay, expected]
    if fn == "build":
        return ["build(uint256,uint256[],uint256,bytes32)", args[0], array(args[1]), min_pay, expected]
    if fn == "checkpoint":
        return ["checkpoint(uint256,uint256,bytes32)", args[0], min_pay, expected]
    raise ValueError(f"unknown keeper operation: {fn}")


HEALTH = dict(last_pass=0, block=0, status=[], accounts={}, exposure=[], policy_count=0,
              pending=None, stats={}, errors=[], pass_errors=0)


def fee_args(base_fee, tip):
    """The fee fields the keeper signs with (tx.submit: max fee 2 x basefee + tip), so a simulation
    sees the same fee context as inclusion."""
    return ["--gas-price", str(2 * base_fee + tip), "--priority-gas-price", str(tip)]


def compensation(vault, args, sender, fees=()):
    """What the vault promises for this exact call now: every paid function returns its payment,
    so simulating it from the keeper's address reads measured compensation under that pending call's fee context (0 for unpaid work)."""
    if args[0].startswith(("burnTokens", "fundCheckpoint", "recover", "requestRedeem", "claim", "cancelDeposit", "setExiting", "withdraw", "processAcquisitions")):
        return 0
    sig = args[0].replace(")", ")(uint256)", 1) if args[0].endswith(")") else args[0]
    return num(cast("call", vault, sig, *args[1:], "--from", sender, "--block", "pending", *fees))


# Billed gas / eth_estimateGas per call, from canary-rehearsal receipts (docs/GAS.md). The estimate
# sets the gas limit; billed gas sets the cost. Replaced by this keeper's own receipts once it has
# three of a kind.
BILLED_PER_ESTIMATE = dict(build=0.92, list=0.98, sync=0.93, unlist=0.80, liquidate=0.80, checkpoint=0.97,
                           harvest=0.95, burnTokens=0.95)


def billed_ratio(tm, label):
    rows = [e for e in (tm.state["counted"] if tm else []) if e["label"] == label and e.get("est")]
    if len(rows) >= 3:
        return min(1.0, sum(e["gas_used"] for e in rows[-20:]) / sum(e["est"] for e in rows[-20:]))
    return BILLED_PER_ESTIMATE.get(label, 1.0)


def billed_basis(tm, target, args, est, fees, label):
    """(gas, ratio) the cost check bills: the exact call's executed gas at its signed limit when
    the node simulates it, else the estimate calibrated by receipts."""
    executed = tm.executed_gas(target, args, (est * 5 + 3) // 4, fees) if tm else None
    return (executed, 1.0) if executed else (est, billed_ratio(tm, label))


def execution_cost(est, bid, fail_rate_bps, ratio=1.0):
    """What the keeper expects to spend: billed gas (the estimate calibrated by receipts) at its
    bid, grossed up for competing transactions it expects to lose."""
    return int(est * ratio) * bid * (10_000 + fail_rate_bps) // 10_000


def wallet_debit_bound(estimate, base_fee, tip, value=0):
    return value + ((estimate * 5 + 3) // 4) * (2 * base_fee + tip)


def profitability_gate(est, bid, pay, fail_rate_bps, min_return_bps, max_loss_wei, ratio=1.0):
    cost = execution_cost(est, bid, fail_rate_bps, ratio)
    need = cost * (10_000 + min_return_bps) // 10_000
    return cost, need, pay + max_loss_wei >= need


def refresh_after_race(operation, reason, benign, refreshed):
    if benign and reason in txm.REFRESH_ERRORS and refreshed.get(operation, 0) < 2:
        refreshed[operation] = refreshed.get(operation, 0) + 1
        return True
    return False


def plan_key(step):
    """Declining one funding prefix must not suppress every other bounded sync candidate."""
    return (step[0], tuple(step[1]), step[2]) if step[0] in ("sync", "syncCheckpoint") else (step[0],)


def manager_exit_steps(state, sender, maintenance):
    """Only the owner starts this flow; final cash stays withdrawable independently of economics."""
    owner = state.account_owner
    if not owner or sender.lower() != owner.lower():
        raise ValueError('caller-funded manager exit requires its current owner')
    if not state.winding_down:
        return [('setExiting', True)]
    if not (state.open_positions or state.idle_packs or state.recovery_packs or state.pending_receipts):
        if state.fee_credit:
            return [('harvest', [])]
        return [('withdraw', owner, state.free)] if state.free else []
    return [step for step in maintenance if step[0] in ('sync', 'unlist', 'liquidate')]


def operation_target(account, step):
    return FWA if step[0] == 'processAcquisitions' else account


def validate_manager_exit_pending(state, account, sender, pending):
    # A previous ordinary keeper pass may have left growth or another account's call pending.
    # Preserve that signature and reservation, but never sign its replacement as exit work.
    manager_exit_steps(state, sender, [])
    if not pending:
        return
    args = pending.get('args', [])
    uint = lambda value: isinstance(value, str) and value.isdecimal() and int(value) < 2**256
    def ids(value):
        if not isinstance(value, str) or not re.fullmatch(r'\[(?:[0-9]+(?:,[0-9]+)*)?\]', value):
            return False
        values = value[1:-1].split(',') if value != '[]' else []
        return len(values) <= 16 and all(uint(x) for x in values)
    valid = False
    if pending.get('to', '').lower() == FWA.lower():
        valid = args == ['processAcquisitions(uint256)', '16']
    elif pending.get('to', '').lower() == account.lower() and args:
        fn = args[0]
        valid = (args == ['setExiting(bool)', 'true']
            or fn == 'recover(uint256[],uint256)' and len(args) == 3 and ids(args[1]) and uint(args[2])
            or fn == 'recoverUnlist(uint256[])' and len(args) == 2 and ids(args[1])
            or fn == 'recoverLiquidate(uint256)' and len(args) == 2 and uint(args[1]) and 0 < int(args[1]) <= 16
            or args == ['harvest(uint256[],uint256)', '[]', '0']
            or fn == 'withdraw(address,uint256)' and len(args) == 3 and args[1].lower() == sender.lower()
                and uint(args[2]) and int(args[2]) > 0)
    if not valid:
        raise ValueError('pending transaction is outside this owner-paid manager exit; preserve its state and resolve it separately')


def local_actor_rpc(url):
    parsed = urlparse(url)
    return parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1')


def run_account(a, tm, account, pooled):
    """One pass over ONE account: settle any in-flight transaction (there is at most one across all
    accounts, on the signer's single nonce stream), then plan, preflight and send one call at a time,
    waiting for each receipt and re-reading that account before choosing the next. Each account has
    its own event index and plan; `pooled` is False for a personal PackManager (no checkpoints,
    deposits or redemptions). Returns (failed, status_codes, in_flight)."""
    failed, skip, sent, declined = 0, set(), 0, []
    refreshed = {}
    codes, in_flight = [], False
    for _ in range(a.max_steps):
        state = stable_read_state(account, a.slowdown_volume, a.burn_tokens, pooled)
        if a.caller_funded_exit and not pooled:
            validate_manager_exit_pending(state, account, tm.sender if tm else a.sender or state.account_owner,
                                          tm.state['pending'] if tm else None)

        def wanted(p, prio=None, max_fee=None, state=state):
            """Preflight again; on a replacement also re-check profit at the bumped tip."""
            if a.caller_funded_exit and not pooled:
                current = stable_read_state(account, a.slowdown_volume, a.burn_tokens, pooled)
                validate_manager_exit_pending(current, account, tm.sender, p)
            est, _why, _exp = tm.preflight(p["to"], p["args"],
                                         ["--gas-price", str(max_fee), "--priority-gas-price", str(prio)]
                                         if prio is not None else fee_args(state.base_fee, state.max_tip))
            if est is not None and a.caller_funded_exit:
                sent_value=int(p['args'][p['args'].index('--value')+1]) if '--value' in p['args'] else 0
                cap=max_fee if max_fee is not None else 2*state.base_fee+state.max_tip
                if not tm.can_reserve(p['nonce'],(est*5+3)//4,cap,sent_value):
                    return None
            if est is None or prio is None or p["label"] == "burnTokens":
                return est
            pay = compensation(p["to"], p["args"], tm.sender, fee_args(state.base_fee, prio))
            if not a.caller_funded_exit and pay + a.max_loss_wei < execution_cost(est, state.base_fee + prio, a.fail_rate_bps,
                                                     billed_ratio(tm, p["label"])):
                return None
            return est

        had_pending = bool(tm and tm.state["pending"])
        if tm and tm.wait(wanted, a.pending_timeout):
            print(f"in flight: {tm.state['pending']['label']} nonce {tm.state['pending']['nonce']}; next pass resumes it")
            in_flight = True
            break
        if had_pending:
            state = stable_read_state(account, a.slowdown_volume, a.burn_tokens, pooled)
        state.caller_funded_exit = a.caller_funded_exit
        steps = [st for st in policy.plan(state) if plan_key(st) not in skip]
        if a.caller_funded_exit:
            steps = [step for step in steps if step[0] not in ('build', 'list', 'burnTokens')]
            if not pooled:
                sender = tm.sender if tm else a.sender or state.account_owner
                steps = manager_exit_steps(state, sender, steps)
                # A ready foreign queue can prevent this account from unlisting. The owner
                # explicitly pays that protocol work; no service is assumed to do it for free.
                if state.winding_down and state.open_positions and not state.queue_drained:
                    processed = num(call(FWA, 'processAcquisitions(uint256)(uint256)', 16,
                                         '--from', sender, block='pending', fees=fee_args(state.base_fee, state.max_tip)))
                    if processed:
                        steps.append(('processAcquisitions', 16))
                    else:
                        state.notes.append('protocol queue waits for an authenticated fulfillment or its real expiry')
                steps = [step for step in steps if plan_key(step) not in skip]
            if pooled and tm:
                holder = lines(call(account,'holderState(address)(uint256,uint256,uint256)',tm.sender))
                shares, holder_locked, holder_claimable = map(num,holder)
                own_pending = lines(call(account,'pendingDeposits(address)(uint128,uint128)',tm.sender))
                if not (shares or holder_locked or holder_claimable or num(own_pending[0])):
                    steps=[]
                if shares and ('requestRedeem',) not in skip:
                    last_nav = num(call(account, 'lastNav()(uint256)'))
                    charge = num(call(account, 'requestCharge()(uint256)')) + shares * last_nav // state.total_shares * num(call(account, 'unwindCharge()(uint256)')) // num(call(account, 'positionValue()(uint256)'))
                    steps.insert(0, ('requestRedeem', shares, charge))
                if state.pending_deposits and ('cancelDeposit',) not in skip:
                    pending = call(account, 'pendingDeposits(address)(uint128,uint128)', tm.sender).splitlines()
                    if pending and num(pending[0]):
                        steps.insert(0, ('cancelDeposit',))
                if ('claim',) not in skip:
                    try:
                        call(account, 'claim()', '--from', tm.sender)
                        steps.insert(0, ('claim',))
                    except subprocess.CalledProcessError:
                        pass
                if a.refund_contributions and ('claimCheckpointRefund',) not in skip:
                    refundable = [i for i in a.refund_contributions if num(call(account, 'checkpointRefund(uint256)(uint256)', i))]
                    if refundable:
                        steps.insert(0, ('claimCheckpointRefund', refundable[:16]))
        codes = policy.status(state)  # from the full plan: skips in this pass are this keeper's choice
        if sent == 0:
            print(f"account {account} ({'pool' if pooled else 'manager'}) {policy_info(account)}")
            print(f"gas {state.gas_price / 1e9:.3f} gwei, {state.open_positions} open, {state.idle_packs} idle packs, "
                  f"idle {state.idle_eth / 1e18:.4f} ETH, cycle net {policy.cycle_net(state) / 1e15:.3f} mETH, "
                  f"7d volume {state.recent_volume:.0f}/day")
            for code, kind, detail in codes:
                print(f"status {code} [{kind}] {detail}")
            for n in state.notes:
                print("note:", n)
        if not steps:
            print("nothing to do" if sent == 0 else f"done: {sent} sent, {failed} failed")
            break
        if not a.send:
            for st in steps:
                print("cast send", operation_target(account, st), *map(str, to_cast(st, expected=state.configuration_hash, caller_funded=a.caller_funded_exit)))
            break
        step, args = steps[0], to_cast(steps[0], expected=state.configuration_hash, caller_funded=a.caller_funded_exit)
        target = operation_target(account, step)
        est, why, benign = tm.preflight(target, args, fee_args(state.base_fee, state.max_tip))
        pay = 0
        if est is None:
            if refresh_after_race(step[0], why, benign, refreshed):
                print(f"refresh {step[0]}: {why}; reindexing and quoting at a new pinned block")
                continue
            skip.add(plan_key(step))
            if benign:
                if step[0] in ("build", "list") and why in txm.ADMISSION_WAIT:
                    declined.append(("ADMISSION_WAIT", "wait", "live FWA listing admission changed; retry after its backlog/economics changes"))
                tm.state["stats"]["skipped_expected"] += 1
                print(f"skip {step[0]}: vault says {why} (state moved on)")
            else:
                failed += 1
                tm.error(f"preflight of {step[0]} on {account} reverted: {why}")
            continue
        st = tm.state["stats"]
        max_loss = a.max_loss_wei
        if max_loss and st.get("spent_wei", 0) - st.get("paid_wei", 0) > a.max_total_loss_wei:
            # Past the cumulative limit the keeper accepts no further loss; paid work goes on.
            max_loss = 0
            declined.append(("KEEPER_LOSS_LIMIT", "action", "cumulative loss limit reached: only paid work; operator review"))
        # State already authenticates the deterministic inclusion-block fee. Parent changes
        # refresh the quote before send; delayed/racing inclusion remains in fail-rate/loss controls.
        bid = state.base_fee + state.max_tip
        fees = fee_args(state.base_fee, state.max_tip)
        pay = compensation(target, args, tm.sender, fees)
        gas, ratio = billed_basis(tm, target, args, est, fees, step[0])
        cost_, need, accepted = profitability_gate(gas, bid, pay, a.fail_rate_bps, a.min_return_bps, max_loss, ratio)
        if a.caller_funded_exit and step[0] not in ('build', 'list', 'burnTokens'):
            contribution = int(step[1]) if step[0] == 'fundCheckpoint' else int(step[2]) if step[0] == 'requestRedeem' else 0
            accepted=tm.can_reserve(tm.nonce('pending'),(est*5+3)//4,2*state.base_fee+state.max_tip,contribution)
            max_loss=max(0,a.exit_spend_limit_wei-(tm.state['signed_upper_wei']-tm.signed_start)) if accepted else 0
        if a.caller_funded_exit and not accepted:
            skip.add(plan_key(step))
            declined.append(('EXIT_SPEND_LIMIT','action','signed maximum reservations exhaust the accepted wallet spending limit'))
            print(f'skip {step[0]}: signed maximum reservation exceeds the wallet spending limit')
            continue
        if not accepted and step[0] != "burnTokens":  # burns are the operator's opt-in cost
            skip.add(plan_key(step))
            tm.state["stats"]["skipped_loss"] += 1
            # Liability work this keeper declined: holders wait on it, so monitoring must see it.
            alternatives = step[0] in ("sync", "syncCheckpoint") and any(st[0] in ("sync", "syncCheckpoint") for st in steps[1:])
            if not alternatives:
                declined.append(("LIABILITY_WORK_SKIPPED", "action",
                                 f"{step[0]} needs --max-loss-wei >= {cost_ - pay} or lower gas"))
            print(f"skip {step[0]}: pay {pay} wei < cost ~{need} wei beyond --max-loss-wei {max_loss}")
            continue
        # minPay: pay and this keeper's gas both move with basefee, so the floor is relative: 80% of
        # the simulated quote (basefee falls at most 12.5% a block). A larger drop means less work
        # was left to do; the whole call reverts instead of paying less.
        args = to_cast(step, pay * 8 // 10 if step[0] != "burnTokens" and max_loss == 0 else 0, state.configuration_hash, a.caller_funded_exit)
        # Re-check the exact signed call, minPay included, at the signed fees: a call that would
        # revert is not sent. A state change between this check and inclusion can still revert it.
        est2, why2, _ = tm.preflight(target, args, fees)
        if est2 is None:
            skip.add(plan_key(step))
            tm.state["stats"]["skipped_expected"] += 1
            print(f"skip {step[0]}: the signed call would revert ({why2})")
            continue
        if step[0] != "burnTokens" and not a.caller_funded_exit:
            gas2, ratio2 = billed_basis(tm, target, args, est2, fees, step[0])
            signed_cost = execution_cost(gas2, bid, a.fail_rate_bps, ratio2)
            if pay + max_loss < signed_cost * (10_000 + a.min_return_bps) // 10_000:
                skip.add(plan_key(step))
                tm.state["stats"]["skipped_loss"] += 1
                print(f"skip {step[0]}: signed-call cost ~{signed_cost} exceeds accepted payment/loss")
                continue
        if a.caller_funded_exit:
            sent_value = int(args[args.index('--value') + 1]) if '--value' in args else 0
            if not tm.can_reserve(tm.nonce('pending'),(est2*5+3)//4,2*state.base_fee+state.max_tip,sent_value):
                skip.add(plan_key(step))
                declined.append(('EXIT_SPEND_LIMIT', 'action', 'signed call exceeds the accepted wallet spending limit'))
                continue
        try:
            tm.submit(step[0], target, args, est2, state.base_fee, state.max_tip, pay, state.pending_parent)
        except txm.SpendLimit as e:
            skip.add(plan_key(step))
            declined.append(('EXIT_SPEND_LIMIT','action',str(e)))
            continue
        except txm.StaleContext:
            print("head changed before send; refreshing prospective quote")
            continue
        sent += 1
        if tm.wait(wanted, a.pending_timeout):
            print(f"in flight: {step[0]}; next pass resumes it")
            in_flight = True
            break
        last = tm.state["counted"][-1] if tm.state["counted"] else None
        if last and last["label"] == step[0] and not last["status"]:
            failed += 1
            skip.add(plan_key(step))
        elif last and last["status"]:
            skip.clear()  # Successful work changes funding and candidate eligibility.
            declined[:] = [entry for entry in declined if not
                           (entry[0] == "LIABILITY_WORK_SKIPPED" and entry[2].startswith(step[0] + " "))]
    return failed, codes + declined, in_flight


def run_pass(a, tm, accounts):
    """One multi-account pass. One signer, one nonce stream, at most one in-flight transaction:
    accounts are serviced in turn and a revert, empty budget, paused listing or stuck position on one
    never stops the others (each is isolated). /health carries a per-account block plus the keeper's
    per-account operation status. Aggregate exposure is unavailable without a separate report."""
    head = num(cast("block-number"))
    errors0 = len(tm.state["errors"]) if tm else 0
    if tm:
        tm.check_reorgs(head)
    failed = 0
    account_health = {}
    for account, pooled in accounts:
        try:
            f, codes, _in_flight = run_account(a, tm, account, pooled)
            failed += f
            account_health[account] = dict(pooled=pooled, status=codes)
        except (txm.StaleContext, IndexBehind) as e:
            account_health[account] = dict(pooled=pooled, status=[("CONTEXT_MOVED", "wait", str(e))])
            print(f"account {account} waits: {e}")
        except Exception as e:  # noqa: BLE001 - one account's failure never stops the others
            failed += 1
            account_health[account] = dict(pooled=pooled, status=[("ACCOUNT_ERROR", "action", str(e)[:200])])
            print(f"account {account} failed this pass: {str(e)[:200]}")
    exposure = [("EXPOSURE_UNAVAILABLE", "info", "aggregate share is not calculated in bounded routine passes")]
    attention = [c for h in account_health.values() for c in h["status"] if c[1] == "action"] + \
                [c for c in exposure if c[1] == "action"]
    HEALTH.update(block=head, accounts=account_health, exposure=exposure, policy_count=len(accounts))
    if tm:
        tm.save()
        HEALTH.update(pending=tm.state["pending"], stats=tm.state["stats"], signed_upper_wei=tm.state["signed_upper_wei"], errors=tm.state["errors"][-5:],
                      pass_errors=len(tm.state["errors"]) - errors0 + failed)
    HEALTH.update(last_pass=int(time.time()), status=[c for h in account_health.values() for c in h["status"]] + exposure)
    for code, kind, detail in exposure:
        print(f"exposure {code} [{kind}] {detail}")
    return failed


def serve_health(port, stale_after):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            fresh = time.time() - HEALTH["last_pass"] < stale_after
            ok = fresh and HEALTH["pass_errors"] == 0
            body = json.dumps(dict(HEALTH, ok=ok, fresh=fresh,
                                   attention=[c for c in HEALTH["status"] if c[1] == "action"])).encode()
            self.send_response(200 if ok or self.path != "/health" else 503)
            self.send_header("content-type", "application/json")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass
    srv = HTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def policy_info(vault):
    return f"configuration {call(vault, 'configurationHash()(bytes32)')}"


def is_pooled(account, factory=None):
    """True for a PackVault, False for a personal PackManager. Prefer the factory's own registry;
    otherwise probe a pool-only view (a manager has no pendingDepositTotal())."""
    if factory:
        try:
            return call(factory, "isManager(address)(bool)", account).strip().lower() != "true"
        except subprocess.CalledProcessError:
            pass
    try:
        call(account, "pendingDepositTotal()(uint256)")
        return True
    except subprocess.CalledProcessError:
        return False


def discover_managers(a):
    """Bounded per-pass manager discovery from the factory: read managerCount and fetch only indices
    not yet persisted, so no pass rescans the whole set. Returns the ordered manager address list."""
    if not a.factory:
        return []
    path = Path(a.state).with_name(f"discovered-{a.factory.lower()}.json")
    seen = json.loads(path.read_text()) if path.exists() else []
    count = num(cast("call", a.factory, "managerCount()(uint256)"))
    for i in range(len(seen), min(count, len(seen) + 32)):
        seen.append(cast("call", a.factory, "managerAt(uint256)(address)", i).strip())
    if count > 0 and (not path.exists() or len(seen) != len(json.loads(path.read_text()))):
        path.write_text(json.dumps(seen))
    return seen


def resolve_accounts(a):
    """Explicit vault/manager address(es) plus every manager the factory has created, each tagged as
    pool or manager. The explicit addresses keep their given order; discovered managers follow."""
    accounts = [(v, is_pooled(v, a.factory)) for v in a.vaults]
    if a.caller_funded_exit:
        return accounts  # Recovery never silently extends to every manager a factory created.
    known = {v.lower() for v in a.vaults}
    for m in discover_managers(a):
        if m.lower() not in known:
            accounts.append((m, False))
            known.add(m.lower())
    return accounts


def print_status(a):
    for account, pooled in resolve_accounts(a):
        state = stable_read_state(account, a.slowdown_volume, a.burn_tokens, pooled)
        print(f"{account} ({'pool' if pooled else 'manager'}) {policy_info(account)}")
        for code, kind, detail in policy.status(state):
            print(f"  {code:28} {kind:7} {detail}")
    try:
        saved = json.load(open(a.state))
    except FileNotFoundError:
        print(f"no keeper state file at {a.state}")
        return
    p, st = saved.get("pending"), saved.get("stats", {})
    print("in flight:", f"{p['label']} nonce {p['nonce']} hashes {p['hashes']}" if p else "none")
    print(f"sent {st.get('sent', 0)} mined {st.get('mined', 0)} reverted {st.get('reverted', 0)} replaced "
          f"{st.get('replaced', 0)} dropped {st.get('dropped', 0)} reorged {st.get('reorged', 0)}; "
          f"spent {st.get('spent_wei', 0) / 1e18:.6f} ETH, paid {st.get('paid_wei', 0) / 1e18:.6f} ETH, "
          f"net {(st.get('paid_wei', 0) - st.get('spent_wei', 0)) / 1e18:+.6f} ETH")
    for e in saved.get("errors", [])[-5:]:
        print("recent error:", e["msg"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("vaults", nargs="*", default=[],
                    help="explicit PackVault/PackManager address(es); may be empty with --factory")
    ap.add_argument("--factory", help="PackManagerFactory address: its managers are discovered and serviced too")
    ap.add_argument("--send", action="store_true")
    ap.add_argument("--caller-funded-exit", action="store_true", help="run necessary bounded exit maintenance without a keeper-profit requirement")
    ap.add_argument("--refund-contributions", type=lambda s: [int(i) for i in s.split(',')], default=[], help="known contribution IDs to claim, bounded 16 per call")
    ap.add_argument("--exit-spend-limit-wei", type=int, default=0, help="explicit maximum gross wallet gas and checkpoint funding for this exit run")
    ap.add_argument("--status", action="store_true", help="print status and keeper accounting, send nothing")
    ap.add_argument("--account")
    ap.add_argument("--keystore", help="encrypted keystore file (with --password-file)")
    ap.add_argument("--password-file")
    ap.add_argument("--from", dest="sender", help="sender for an unlocked local node (rehearsal)")
    ap.add_argument("--rpc", default=RPC)
    ap.add_argument("--state", help="keeper state file (default keeper/state-<vault>.json)")
    ap.add_argument("--index", help="directory for the per-account SQLite event indexes (default: keeper/)")
    ap.add_argument("--loop", type=int, default=0, help="seconds between passes; 0 runs once")
    ap.add_argument("--slowdown-volume", type=float, default=0.0)
    ap.add_argument("--max-steps", type=int, default=40, help="calls per pass, each after a fresh read")
    ap.add_argument("--burn-tokens", action="store_true",
                    help="claim and burn FWA token rewards; unpaid, the operator pays the gas")
    ap.add_argument("--max-total-loss-wei", type=int, default=5 * 10**15,
                    help="stop sending once spent minus paid exceeds this (default 0.005 ETH)")
    ap.add_argument("--max-loss-wei", type=int, default=0,
                    help="loss this keeper accepts per call (liability work above the gas ceiling)")
    ap.add_argument("--max-fee-gwei", type=float, help="never bid a max fee above this")
    ap.add_argument("--fail-rate-bps", type=int, default=0,
                    help="share of sent calls expected to lose to a competing keeper (adds to cost)")
    ap.add_argument("--min-return-bps", type=int, default=0, help="required return over expected cost")
    ap.add_argument("--confirmations", type=int, default=1, help="blocks before a receipt counts (2+ on mainnet)")
    ap.add_argument("--replace-after", type=int, default=3, help="blocks pending before a same-nonce replacement")
    ap.add_argument("--max-replacements", type=int, default=5)
    ap.add_argument("--pending-timeout", type=float, default=120, help="seconds a pass waits for a receipt")
    ap.add_argument("--health-port", type=int, default=0)
    a = ap.parse_args()
    if a.caller_funded_exit and (a.exit_spend_limit_wei <= 0 or a.loop):
        ap.error("caller-funded exit requires a positive --exit-spend-limit-wei and a single pass")
    if a.caller_funded_exit and not a.vaults:
        ap.error('caller-funded exit requires explicit account addresses')
    print("client " + json.dumps(txm.client_identity([sys.modules[__name__], policy, txm, event_index]), sort_keys=True))
    globals()["RPC"] = a.rpc
    globals()["INDEX_PATH"] = a.index
    if not a.vaults and not a.factory:
        sys.exit("give at least one account address, and/or a --factory to discover managers")
    # One signer, one nonce stream, one shared state file across every account this keeper runs.
    a.state = a.state or str(Path(__file__).parent / f"state-{(a.factory or a.vaults[0]).lower()}.json")
    if a.status:
        print_status(a)
        return
    if a.send and not (a.account or a.keystore or a.sender):
        sys.exit("--send needs --account (a cast keystore name), --keystore with --password-file, "
                 "or --from on an unlocked local node")
    if a.send and a.sender:
        if not local_actor_rpc(a.rpc) or quantity(rpc('eth_chainId')) != 31337 or not rpc('web3_clientVersion').lower().startswith('anvil/'):
            sys.exit('--from is restricted to a loopback Anvil on chain31337; use an existing signer store for other networks')
    tm = None
    if a.send:
        for v in a.vaults:
            if cast("code", v) in ("", "0x"):
                sys.exit(f"--send refused: no contract at {v}")
    if a.send:
        if a.keystore:  # an encrypted keystore file and its password file (containers); never a raw key
            auth = ["--keystore", a.keystore, "--password-file", a.password_file]
        elif a.account:
            auth = ["--account", a.account]
        else:
            auth = ["--unlocked", "--from", a.sender]
        # `cast wallet address` takes no --rpc-url, so not through cast()
        sender = a.sender or subprocess.check_output(["cast", "wallet", "address", *auth], text=True).strip()
        try:
            tm = txm.TxManager(a.rpc, a.state, sender, auth, a.confirmations, a.replace_after, a.max_replacements,
                               int(a.max_fee_gwei * 1e9) if a.max_fee_gwei else None)
        except (txm.Locked,txm.IdentityMismatch) as e:
            sys.exit(str(e))
    if tm and a.caller_funded_exit:
        tm.begin_signed_limit(a.exit_spend_limit_wei)
    if a.health_port:
        serve_health(a.health_port, 3 * max(a.loop, 60))
    while True:
        try:
            # Rediscover managers each pass (bounded): a factory can mint new ones between passes.
            failed = run_pass(a, tm, resolve_accounts(a))
        except txm.StaleContext as e:
            failed = 0
            HEALTH.update(status=[("CONTEXT_MOVED", "wait", str(e))], last_pass=int(time.time()), pass_errors=0)
            print(str(e))
        except IndexBehind as e:
            failed = 0
            HEALTH.update(status=[("INDEX_CATCHUP", "wait", str(e))], last_pass=int(time.time()), pass_errors=0)
            print(str(e))
        except RuntimeError as e:
            failed = 1
            HEALTH["pass_errors"] = 1
            print(f"read failed: {e}")
        except subprocess.CalledProcessError as e:  # RPC hiccup: read again next pass
            failed = 1
            HEALTH["pass_errors"] = 1
            print(f"read failed: {(e.output or str(e)).strip()[:200]}")
        if not a.loop:
            sys.exit(1 if failed else 0)
        time.sleep(a.loop)


if __name__ == "__main__":
    main()
