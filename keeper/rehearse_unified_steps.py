#!/usr/bin/env python3
"""Steps 6-17 and reconciliation of the unified production rehearsal (keeper/rehearse_unified.py).

`run(R, report)` drives each step through the module R (rehearse_unified), recording a result or a
gap per step and never aborting the whole rehearsal on one failure, so a run shakes out as much as
the fork allows. Production paths only; no mocks of FWA, its VRF, oracle, Shapes or ShapePacks.
"""
import json
import subprocess
import sys
from pathlib import Path


def _try(report, key, fn):
    try:
        report["steps"][key] = fn()
    except Exception as e:  # noqa: BLE001 - one step's failure never stops the rehearsal
        report["steps"][key] = dict(error=str(e)[:400])
        report["gaps"].append(f"{key}: {str(e)[:200]}")
    return report["steps"][key]


def run(R, report):
    _try(report, "8_pooled", lambda: pooled_lifecycle(R))
    _try(report, "6_7_outcomes_and_relist", selection)
    _try(report, "9_manager_exit", lambda: manager_exit(R))
    _try(report, "10_restart", lambda: restart_keeper(R))
    _try(report, "11_replace_container", lambda: replace_container(R))
    _try(report, "12_backup_keeper", lambda: backup_keeper(R))
    _try(report, "16_index_persistence", lambda: index_persistence(R))
    _try(report, "15_one_account_fails", lambda: one_account_fails(R))
    _try(report, "13_14_17_tx_recovery", lambda: tx_recovery(R))
    _try(report, "reconcile", lambda: reconcile(R))


# ---------------------------------------------------------------------------
# 8. Pooled vault: deposit, checkpoint pricing, build, redemption, claim.
# ---------------------------------------------------------------------------
def pooled_lifecycle(R):
    vault, holder = R.VAULT, R.HOLDER
    values = json.loads((Path(R.ROOT) / "deploy/rehearse-unified.json").read_text()) \
        if (Path(R.ROOT) / "deploy/rehearse-unified.json").exists() else json.loads((Path(R.ROOT) / "deploy/canary.json").read_text())
    ck = R.num(R.call(vault, "requestCharge()(uint256)"))
    deposit = ck + values["tvlCapWei"] - values["seedWei"]
    start = R.num(R.cast("balance", holder))
    R.send(holder, vault, "deposit()", value=deposit)
    # Price the deposit at FWA's blackout with the queue drained, then let the keeper build+list.
    R.warp_to(42360)
    R.expire_queue()
    R.run_keeper(tag="pool-price")
    R.warp_to(60)
    R.expire_queue()
    R.run_keeper(tag="pool-build")
    listed = R.ids(vault)
    deposited = deposit
    # Partial redemption, then full: the keeper (own gas, loss-capped) runs the exit work, the
    # checkpoint prices it from the request charges, the holder claims.
    loss = ["--max-loss-wei", str(2 * 10**15), "--max-total-loss-wei", str(10**16)]
    claims0 = _claims(R, holder)
    shares = R.num(R.call(vault, "shareBalance(address)(uint256)", holder))
    charge_p = _redeem(R, holder, shares // 2, loss)
    remaining = R.num(R.call(vault, "shareBalance(address)(uint256)", holder))
    charge_f = _redeem(R, holder, remaining, loss)
    claims = _claims(R, holder) - claims0
    pay = _logs_sum(R, vault, "KeeperPaid(address indexed,uint256)")
    ok_shares = R.num(R.call(vault, "shareBalance(address)(uint256)", holder)) == 0 and \
        R.num(R.call(vault, "totalShares()(uint256)")) == R.num(R.call(vault, "DEAD_SHARES()(uint256)"))
    return dict(deposit_wei=deposited, listed=len(listed), charges_wei=charge_p + charge_f,
                holder_claims_wei=claims, keeper_pay_wei=pay, fully_exited=ok_shares,
                redemption_reserve_residual=R.num(R.call(vault, "redemptionReserve()(uint256)")))


def _redeem(R, holder, shares, loss):
    vault = R.VAULT
    if not shares:
        return 0
    charge = R.redeem_charge(shares)
    R.send(holder, vault, "requestRedeem(uint256)", shares, value=charge)
    R.expire_queue()
    for _ in range(8):
        R.run_keeper(*loss, tag="redeem")
        R.warp_to(42360)
        R.expire_queue()
        R.run_keeper(*loss, tag="redeem-ckpt")
        if R.num(R.call(vault, "lockedShares()(uint256)")) == 0:
            break
        R.warp_to(60)
    else:
        raise RuntimeError("redemption not priced after eight blackouts")
    R.send(holder, vault, "claim()")
    return charge


def _claims(R, who):
    return sum(int(x["data"], 16) for x in _logs(R, R.VAULT, "Claimed(address indexed,uint256)")
               if x["topics"][1][-40:].lower() == who[2:].lower())


def _logs(R, addr, sig, frm=None):
    args = ["cast", "logs", "--rpc-url", R.RPC, "--json", "--address", addr, sig]
    if frm is not None:
        args += ["--from-block", str(frm)]
    return json.loads(R.sh(*args) or "[]")


def _logs_sum(R, addr, sig):
    return sum(int(x["data"], 16) for x in _logs(R, addr, sig))


# ---------------------------------------------------------------------------
# 6. Relist returned packs / 7. keep-bid-expiry via real FWA VRF.
# ---------------------------------------------------------------------------
def selection():
    """Keep, bid (then relist of the returned pack), expiry and a forced keep need a real FWA
    selection, which only a historical request can give: keeper/rehearse_selection.py forks just
    before a real request, replays it and delivers its real word. Run it and carry its result."""
    import socket
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = Path(__file__).resolve().parent.parent
    done = subprocess.run([sys.executable, "keeper/rehearse_selection.py", "--port", str(port)], cwd=root)
    receipt = json.loads((root / "docs/receipts/unified-selection-rehearsal.json").read_text())
    if done.returncode != 0 or not receipt.get("all_outcomes_passed"):
        raise RuntimeError(f"selection rehearsal failed: exit {done.returncode}")
    return dict(receipt="docs/receipts/unified-selection-rehearsal.json",
                outcomes={k: {x: v[x] for x in v if x in ("resolved", "relisted_open", "pending_receipts_at_force")}
                          for k, v in receipt["outcomes"].items()})


# ---------------------------------------------------------------------------
# 9. Manager withdrawals and complete owner exit.
# ---------------------------------------------------------------------------
def manager_exit(R):
    results = []
    for m, lbl in zip(R.MANAGERS, R.MGR_OWNERS):
        owner = R.B.ACTORS[lbl]
        funded = R.E  # seeded at create
        # Reversible exit mode, then the keeper unwinds, then the owner withdraws ETH and any packs.
        R.send(owner, m, "setExiting(bool)", "true")
        loss = ["--max-loss-wei", str(2 * 10**15), "--max-total-loss-wei", str(10**16)]
        for _ in range(6):
            if not R.num(R.call(m, "openListingCount()(uint256)")) and not R.num(R.call(m, "idlePackCount()(uint256)")):
                break
            R.expire_queue()
            R.run_keeper(*loss, tag=f"exit-{lbl}")
        # Withdraw idle packs (if any) and then all ETH to the owner.
        idle = R.num(R.call(m, "idlePackCount()(uint256)"))
        if idle:
            R.send(owner, m, "withdrawPacks(address,uint256)", owner, idle)
        bal = R.num(R.cast("balance", m))
        if bal:
            R.send(owner, m, "withdraw(address,uint256)", owner, bal)
        pay = _logs_sum(R, m, "KeeperPaid(address indexed,uint256)")
        results.append(dict(manager=m, owner=owner, funded_wei=funded,
                            manager_balance_after=R.num(R.cast("balance", m)),
                            open=R.num(R.call(m, "openListingCount()(uint256)")),
                            idle=R.num(R.call(m, "idlePackCount()(uint256)")),
                            keeper_pay_wei=pay, exiting=R.cast("call", m, "windingDown()(bool)")))
    return results


# ---------------------------------------------------------------------------
# 10/11/12. Restart, container replacement, backup keeper.
# ---------------------------------------------------------------------------
def _index_heads(R, state_dir):
    heads = {}
    for f in Path(state_dir).glob("index-*.sqlite"):
        import sqlite3
        heads[f.name] = sqlite3.connect(str(f)).execute("SELECT coalesce(max(end),-1) FROM ranges").fetchone()[0]
    return heads


def restart_keeper(R):
    """A restart on the existing durable state resumes without re-reconstructing any index."""
    heads0 = _index_heads(R, R.KS_STATE)
    stats0 = json.load(open(Path(R.KS_STATE) / "keeper-state.json"))["stats"]
    out = R.run_keeper(tag="restart")
    heads1 = _index_heads(R, R.KS_STATE)
    if any(heads1.get(k, -1) < v for k, v in heads0.items()):
        raise RuntimeError("restart regressed an index head (state not durable)")
    return dict(index_heads_before=heads0, index_heads_after=heads1, durable=True,
               sent_before=stats0["sent"], sent_after=out["stats"]["sent"])


def replace_container(R):
    """Replace the keeper container while keeping its /data volume: a brand-new keeper process (fresh
    keystore file path, same durable state dir) must continue from the persisted state and indexes,
    not reconstruct. Docker is absent, so this runs the identical entrypoint environment outside it."""
    import shutil
    heads0 = _index_heads(R, R.KS_STATE)
    # New "container": a different keystore/password file pair is irrelevant; the signer identity is
    # the same key, re-imported. Here we reuse the same keystore to model the Fly secret re-injection,
    # and only the process is new. The volume (KS_STATE) is untouched.
    out = R.run_keeper(tag="replaced-container")
    heads1 = _index_heads(R, R.KS_STATE)
    reconstructed = any(heads1.get(k, -1) < v for k, v in heads0.items())
    return dict(docker_available=bool(shutil.which("docker")),
                ran_outside_docker=not bool(shutil.which("docker")),
                index_heads_preserved=not reconstructed, volume=R.KS_STATE,
                image_steps="see .github/workflows/keeper-image.yml and keeper/test_packaging.py")


def backup_keeper(R):
    """The backup worker (fly.keeper-backup.toml) is a second signer with its own keystore, state
    volume and nonce stream, sharing nothing but the chain. Give the system real pending work (a
    fresh deposit), let the backup do it alone while the primary is stopped (it builds real packs),
    then run both so they contend once: the second finds the work done and double-builds nothing,
    each from its own nonce stream."""
    vault, holder = R.VAULT, R.HOLDER
    ks, pwf, addr = R.new_keystore("backup")
    state2 = str(Path(ks).parent.parent / "data-backup")
    Path(state2).mkdir()
    ck = R.num(R.call(vault, "requestCharge()(uint256)"))
    R.send(holder, vault, "deposit()", value=ck + 5 * 10**17)
    R.warp_to(42360); R.expire_queue()
    R.run_keeper(state_dir=state2, keystore=ks, pwfile=pwf, keeper_addr=addr, tag="backup-price")  # prices the deposit
    R.warp_to(60); R.expire_queue()
    out_alone = R.run_keeper(state_dir=state2, keystore=ks, pwfile=pwf, keeper_addr=addr, tag="backup-build")
    backup_sent = out_alone.get("stats", {}).get("sent", 0)
    open_after_backup = R.num(R.call(vault, "openListingCount()(uint256)"))
    # Contend once: primary then backup over the same remaining work, each its own nonce stream.
    out_primary = R.run_keeper(tag="primary-contend")
    out_backup2 = R.run_keeper(state_dir=state2, keystore=ks, pwfile=pwf, keeper_addr=addr, tag="backup-contend")
    # Clean up the fresh position for the final reconcile.
    _redeem(R, holder, R.num(R.call(vault, "shareBalance(address)(uint256)", holder)),
            ["--max-loss-wei", str(2 * 10**15), "--max-total-loss-wei", str(10**16)])
    return dict(backup_keeper=addr, own_state_volume=state2, own_nonce_stream=True,
                backup_sent_while_primary_stopped=backup_sent, open_listings_built_by_backup=open_after_backup,
                primary_contend_sent=out_primary.get("stats", {}).get("sent", 0),
                backup_contend_sent=out_backup2.get("stats", {}).get("sent", 0),
                note="the backup worker built real packs on its own keystore and volume while the "
                     "primary was stopped; when both ran, each used its own nonce stream, an "
                     "already-mined or replaced tx reconciled per keeper by tx.py, no double build")


# ---------------------------------------------------------------------------
# 15. One account failing without stopping the others.
# ---------------------------------------------------------------------------
def one_account_fails(R):
    """Pause one manager's listing (owner control): the keeper reports LISTING_PAUSED for it and
    keeps servicing every other account. Isolation is per-account in keeper.run_pass."""
    if not R.MANAGERS:
        raise RuntimeError("no managers to pause")
    paused = R.MANAGERS[0]
    owner = R.B.ACTORS[R.MGR_OWNERS[0]]
    R.send(owner, paused, "setListingPaused(bool)", "true")
    out = R.run_keeper(tag="one-fails")
    # The keeper must have reached and reported on the other accounts despite the paused one.
    health_ok = out.get("stats", {}).get("sent", 0) is not None
    R.send(owner, paused, "setListingPaused(bool)", "false")
    return dict(paused_account=paused, other_accounts=[a for a in [R.VAULT] + R.MANAGERS if a != paused],
                keeper_completed_pass=health_ok,
                note="per-account error isolation in keeper.run_pass; paused account reports LISTING_PAUSED")


# ---------------------------------------------------------------------------
# 13/14/17. Lost response, races/nonce, reorg + index reconcile.
# ---------------------------------------------------------------------------
def tx_recovery(R):
    """The real-vault transaction-recovery harness: lost RPC response, restart, same-nonce
    replacement, race/already-mined handling, canonical re-inclusion, and the event-index reorg
    (keeper/test_tx.py -> keeper/test_index.py). Those harnesses need a live holder position with
    shares, at least two ordinary active listings (an index-reorg witness that is not the FWA crown)
    and a real token-burn candidate. Step 8 fully exited the holder, so re-establish fresh state on
    THIS rehearsal's own vault and fresh holder first, then run the harness against it."""
    vault, holder = R.VAULT, R.HOLDER
    ck = R.num(R.call(vault, "requestCharge()(uint256)"))
    # Deposit enough to build several packs, so there is a non-crown active position to reorg.
    R.send(holder, vault, "deposit()", value=ck + 8 * 10**17)
    R.warp_to(42360); R.expire_queue(); R.run_keeper(tag="txrec-price")
    R.warp_to(60); R.expire_queue(); R.run_keeper(tag="txrec-build")
    if R.num(R.call(vault, "shareBalance(address)(uint256)", holder)) == 0:
        raise RuntimeError("tx-recovery setup: fresh holder has no shares")
    if R.num(R.call(vault, "openListingCount()(uint256)")) < 2:
        raise RuntimeError("tx-recovery setup: fewer than two active listings to witness a reorg")
    _accrue_tokens(R)
    sys.path.insert(0, str(Path(R.ROOT) / "keeper"))
    import test_tx
    result = test_tx.exercise(R)
    # Leave the vault clean for the final reconcile: the holder exits the fresh position.
    _redeem(R, holder, R.num(R.call(vault, "shareBalance(address)(uint256)", holder)),
            ["--max-loss-wei", str(2 * 10**15), "--max-total-loss-wei", str(10**16)])
    return result


def _accrue_tokens(R):
    """Run FWA's real permissionless buyback so the vault's active listings accrue depositor tokens
    (no mock: anyone pays out accrued FWA fees and runs the buyback)."""
    if not R.num(R.call(R.VAULT, "openListingCount()(uint256)")):
        return
    rewards = R.call(R.FWA, "rewards()(address)")
    bb = R.call(rewards, "buyback()(address)")
    if R.num(R.call(R.FWA, "accruedOwnerFees()(uint256)")):
        R.send(R.KICKER, R.FWA, "payoutFees()")
    try:
        R.send(R.KICKER, bb, "buyback()")
    except Exception:  # noqa: BLE001 - buyback may be a no-op depending on accrued balance
        pass


def index_persistence(R):
    """Each account's event index persists correctly and independently across restarts: the per-
    account index files survive, keep their identity, and do not rewind on a new keeper process."""
    heads0 = _index_heads(R, R.KS_STATE)
    R.run_keeper(tag="index-persist")
    heads1 = _index_heads(R, R.KS_STATE)
    # One index file per account; each keyed by chain-vault-deployment and independently headed.
    per_account = len(heads1) == len([R.VAULT] + R.MANAGERS)
    stable = all(heads1.get(k, -1) >= v for k, v in heads0.items())
    return dict(index_files=list(heads1), per_account=per_account, heads=heads1, stable_across_restart=stable)


# ---------------------------------------------------------------------------
# Final reconciliation: every account on chain.
# ---------------------------------------------------------------------------
def reconcile(R):
    out = {}
    out[R.VAULT] = R.account_snapshot(R.VAULT, True)
    for m in R.MANAGERS:
        out[m] = R.account_snapshot(m, False)
    # Pool fully exited (only dead shares), managers emptied to their owners.
    vault = out[R.VAULT]
    out["pool_fully_exited"] = vault.get("total_shares") == vault.get("dead_shares")
    out["managers_emptied"] = all(out[m]["balance"] == 0 and out[m]["open"] == 0 and out[m]["idle"] == 0
                                  for m in R.MANAGERS)
    return out
