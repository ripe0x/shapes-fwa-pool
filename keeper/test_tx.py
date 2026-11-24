#!/usr/bin/env python3
"""Actual PackVault transaction recovery tests, invoked by the approved local rehearsal.

Only external-service failure is injected: the real accepted transaction response is lost.
No test node, funding or synthetic successful counterparty is created by this module.
"""
import subprocess
import sys
import hashlib
from pathlib import Path

SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

def identity_regression(R):
    import json
    import tx as T
    path=Path(R.KEEPER_STATE).with_name('identity-regression.json')
    manager=T.TxManager(R.RPC,str(path),R.KEEPER,['--unlocked','--from',R.KEEPER])
    original=json.loads(path.read_text())
    manager._lockf.close()
    for altered,signer in ((original,R.HOLDER2),(original | {'identity': original['identity'] | {'chain_id':original['identity']['chain_id']+1}},R.KEEPER)):
        path.write_text(json.dumps(altered))
        try:
            unexpected=T.TxManager(R.RPC,str(path),signer,['--unlocked','--from',signer])
        except T.IdentityMismatch:
            continue
        unexpected._lockf.close()
        raise RuntimeError('real node identity mismatch was accepted')
    # Local-file corruption is the input; actual chain identity comes from the owned node.
    path.write_text(json.dumps(original))
    return dict(wrongSignerRejected=True,wrongChainRejected=True,chain=original['identity']['chain_id'])


def exercise(R):
    """Real token burn, lost RPC response, restart, canonical re-inclusion and index rollback."""
    RPC, KEEPER_STATE, VAULT, KEEPER, TOKEN = R.RPC, R.KEEPER_STATE, R.VAULT, R.KEEPER, R.TOKEN
    num, call, cast, B = R.num, R.call, R.cast, R.B
    import keeper as K
    import tx as T
    identity = T.client_identity([sys.modules[__name__], K, T, R])
    print("loaded recovery client " + __import__("json").dumps(identity), flush=True)
    K.RPC, K.INDEX_PATH = RPC, KEEPER_STATE + ".sqlite"
    from test_value_reorg import exercise_value_reorg
    identity_check = identity_regression(R)
    records=[__import__('json').loads(line) for line in Path(B.load_manifest()['actions']).read_text().splitlines()]
    previous=next((row for row in reversed(records) if row.get('operation')=='real reverted-to-successful contribution reorg'
        and row.get('vault_context',{}).get('source_sha256')==B.CURRENT_DEPLOYMENT['source_sha256']
        and row.get('loaded_client',{}).get('tx',{}).get('source_sha256_at_import')==T.SOURCE_SHA256),None)
    value_reorg = dict(reusedVerifiedReceipts=True,failed=previous['failed']['hash'],success=previous['success']['hash']) if previous and '--resume-step13' in sys.argv else exercise_value_reorg(R)
    from test_index import exercise_vault_reorg
    index_reorg = exercise_vault_reorg(R)
    for _ in range(16):
        try:
            observed = K.stable_read_state(VAULT, 0, True)
            break
        except K.IndexBehind:
            pass
    else:
        raise RuntimeError("actual recovery index failed to catch up in16 bounded passes")
    if not observed.token_ids:
        observed = K.stable_read_state(VAULT, 0, True)  # another bounded rotation, not a portfolio scan
    if not observed.token_ids:
        return dict(identity=identity_check,value_reorg=value_reorg, index_reorg=index_reorg, gap="no real token claim candidate for token-burn transaction recovery")
    args = K.to_cast(("burnTokens", observed.token_ids[:16]))
    fees = K.fee_args(observed.base_fee, observed.max_tip)
    tm = T.TxManager(RPC, KEEPER_STATE, KEEPER, ["--unlocked", "--from", KEEPER])
    stats0 = dict(tm.state["stats"])
    supply0 = num(call(TOKEN, "totalSupply()(uint256)"))
    snapshot = B.rpc("evm_snapshot")
    estimate, reason, _ = tm.preflight(VAULT, args, fees)
    if estimate is None:
        raise RuntimeError(f"real burn recovery preflight failed: {reason}")
    real_broadcast = tm._broadcast
    def lost_response(pending):
        real_broadcast(pending)
        raise subprocess.CalledProcessError(1, "RPC response", output="test lost response after real node acceptance")
    tm._broadcast = lost_response  # external-service failure only; successful answers are never supplied
    B.load_manifest()
    tm.submit("burnTokens", VAULT, args, estimate, observed.base_fee, observed.max_tip, 0, observed.pending_parent)
    if not tm.state["pending"] or tm.state["pending"]["hashes"]:
        raise RuntimeError("lost response did not retain its original nonce")
    tm._lockf.close()
    tm = T.TxManager(RPC, KEEPER_STATE, KEEPER, ["--unlocked", "--from", KEEPER])
    if tm.wait(lambda p, *rest: tm.preflight(p["to"], p["args"], fees)[0], 30):
        raise RuntimeError("restart did not find the actual lost-response receipt")
    recovered = dict(tm.state["counted"][-1])
    if not recovered["status"] or num(call(TOKEN, "totalSupply()(uint256)")) >= supply0:
        raise RuntimeError("recovery test did not execute a real successful token burn")
    K.stable_read_state(VAULT, 0, True)  # index the actual new receipt block
    if not B.rpc("evm_revert", snapshot):
        raise RuntimeError("recovery test reorg failed")
    tm.check_reorgs(num(cast("block-number")))
    K.stable_read_state(VAULT, 0, True)  # canonical index repair, not a fabricated RPC answer
    if tm.state["stats"]["spent_wei"] != stats0["spent_wei"] or num(call(TOKEN, "totalSupply()(uint256)")) != supply0:
        raise RuntimeError("real reorg did not restore token supply and keeper cash accounting")
    # Re-include exactly that same signed intent at its restored nonce. Canonical P&L must count
    # a hash once even when a formerly orphaned transaction becomes valid again.
    snapshot2 = B.rpc("evm_snapshot")
    B.load_manifest()
    tm.submit("burnTokens", VAULT, args, estimate, observed.base_fee, observed.max_tip, 0)
    if tm.wait(lambda p, *rest: tm.preflight(p["to"], p["args"], fees)[0], 30):
        raise RuntimeError("re-included transaction did not confirm")
    tm.check_reorgs(num(cast("block-number")))
    canonical = [entry for entry in tm.state["counted"] if not entry.get("reorged")]
    if len({entry["hash"] for entry in canonical}) != len(canonical):
        raise RuntimeError("keeper counted a re-included transaction hash twice")
    # The identical call now has no pending tokens. Its actual reverted receipt must debit
    # gas, earn no pay, and count once as reverted rather than as successful maintenance.
    spent = tm.state["stats"]["spent_wei"]
    tm.submit("burnTokens", VAULT, args, estimate, observed.base_fee, observed.max_tip, 0)
    if tm.wait(lambda p, *rest: None, 30):
        raise RuntimeError("real stale burn receipt did not resolve")
    reverted = dict(tm.state["counted"][-1])
    if reverted["status"] or reverted["pay"] or tm.state["stats"]["spent_wei"] <= spent:
        raise RuntimeError("real reverted burn receipt accounting failed")
    if not B.rpc("evm_revert", snapshot2):
        raise RuntimeError("recovery test final token baseline restore failed")
    tm.check_reorgs(num(cast("block-number")))
    K.stable_read_state(VAULT, 0, True)
    # Hold a real valid burn below the basefee, restart, and replace it at the same nonce.
    replacement_snapshot = B.rpc("evm_snapshot")
    try:
        B.rpc("evm_setAutomine", False)
        tm.submit("burnTokens", VAULT, args, estimate, observed.base_fee, observed.max_tip, 0)
        nonce = tm.state["pending"]["nonce"]
        tm._lockf.close()
        B.rpc("anvil_setNextBlockBaseFeePerGas", hex(1_000_000_000))
        B.rpc("anvil_mine", "0x3")
        tm = T.TxManager(RPC, KEEPER_STATE, KEEPER, ["--unlocked", "--from", KEEPER], max_replacements=1)
        if tm.state["pending"]["nonce"] != nonce:
            raise RuntimeError("restart changed the in-flight nonce")
        def reprice(p, priority, maximum):
            return tm.preflight(p["to"], p["args"], ["--gas-price", str(maximum),
                                                       "--priority-gas-price", str(priority)])[0]
        real_replace = tm._broadcast
        accepted = []
        def lost_replacement(pending):
            accepted.append(real_replace(pending))
            raise subprocess.CalledProcessError(1, "RPC response", output="test lost accepted replacement response")
        tm._broadcast = lost_replacement
        if not tm.resolve(reprice):
            raise RuntimeError("underpriced original burn unexpectedly mined")
        pending = dict(tm.state["pending"])
        if pending["nonce"] != nonce or pending["replacements"] != 1 or len(pending["hashes"]) != 1 or len(accepted) != 1:
            raise RuntimeError("real uncertain replacement did not persist its attempt")
        if pending["gas"] != (pending["est"] * 5 + 3) // 4 or pending["gas"] > B.MAX_GAS:
            raise RuntimeError("replacement did not pad its current actual estimate")
        # A zero replacement delay exercises the attempt cap before mining the accepted call.
        # Its lost response must not permit another attempt, including after restart.
        tm._lockf.close()
        tm = T.TxManager(RPC, KEEPER_STATE, KEEPER, ["--unlocked", "--from", KEEPER],
                         max_replacements=1, replace_after=0)
        if not tm.resolve(reprice) or tm.state["pending"]["replacements"] != 1:
            raise RuntimeError("restart exceeded the uncertain replacement attempt cap")
        pool = B.rpc("txpool_content")
        transactions = []
        def collect(value):
            if isinstance(value, dict):
                if "hash" in value and "nonce" in value:
                    transactions.append(value)
                else:
                    for child in value.values():
                        collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)
        collect(pool)
        if len(transactions) != 1 or transactions[0]["hash"] != accepted[0] or B.quantity(transactions[0]["nonce"]) != nonce:
            raise RuntimeError(f"unexpected replacement pool at attempt cap: {pool}")
        B.append_action(dict(operation="real uncertain replacement attempt cap", accepted_hash=accepted[0],
                             nonce=nonce, attempt_count=tm.state["pending"]["replacements"], pool=pool))
        B.rpc("anvil_mine", "0x1")
        if tm.resolve(reprice):
            raise RuntimeError("real replacement did not mine")
        replaced = dict(tm.state["counted"][-1])
        if replaced["hash"] != accepted[0] or not replaced["status"] or tm.nonce("latest") != nonce + 1:
            raise RuntimeError("real replacement receipt/nonce mismatch")
    finally:
        B.rpc("evm_setAutomine", True)
        if not B.rpc("evm_revert", replacement_snapshot):
            raise RuntimeError("real replacement branch restore failed")
    tm.check_reorgs(num(cast("block-number")))
    K.stable_read_state(VAULT, 0, True)
    if num(call(TOKEN, "totalSupply()(uint256)")) != supply0 or tm.state["stats"]["spent_wei"] != stats0["spent_wei"]:
        raise RuntimeError("transaction test branches did not restore real token/cash accounting")
    tm.save()
    tm._lockf.close()
    B.append_action(dict(operation="keeper restart/lost-response/reorg", recovered=recovered,
                         recovery_client=identity,
                         reverted=reverted, replaced=replaced, index_reorg=index_reorg,
                         final_stats=tm.state["stats"], token_supply_restored=supply0))
    return dict(lost_response=True, restart=True, actual_receipt=recovered["hash"], reorg=True,
                canonical_hash_unique=True, token_supply_restored=True, receipt_status=True,
                same_nonce_replacement=True, uncertain_replacement_attempt_cap=True, index_reorg=index_reorg, value_reorg=value_reorg, identity=identity_check)


if __name__ == "__main__":
    raise SystemExit("Run through keeper/rehearsal_batch.py after the bounded local batch is approved; no standalone broadcasts.")
