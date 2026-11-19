"""Review-only helpers for root's approved 8559 batch recovery.

No top-level RPC, process, snapshot, or transaction operations. Root must review and
explicitly install the wrapper on its reconciled LocalBatch instance. This module
does not resume a batch or allocate/restore any snapshot.
"""

PLAN_SHA256 = "1c7e115fe1f62751f0b0bc6c478817d214e1bd97c1f1f09259d9cb48ff1340fd"
OWNED_PID = 96649
OWNED_RPC = "http://127.0.0.1:8559"


def expected_original_snapshot_map(observed_resume2_probe=6):
    """Pure derivation, valid only with the documented exact prior snapshot order.

    This does not test whether a snapshot remains live. Root must verify the stop
    stage and current chain getters before any authorized restoration.
    """
    if observed_resume2_probe != 6:
        raise ValueError("This derivation binds the recorded resume2 probe 0x6")
    counts = (1, 2, 3, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128)
    # After probe6: stock fresh1 + three*(origin1 + price restores2)
    # + final fresh restoration1 = eleven new snapshot IDs7..17.
    base = observed_resume2_probe + 12
    prefixes = {count: hex(base + i + 1) for i, count in enumerate(counts)}
    # Six normal descending cases before32 each allocate twelve snapshots:
    # outer restore1, holder1, matrix(origin1 + two*(origin1+branch1+prices2)
    # + final restore1). No-gain32 then outer restore, distribution restore,
    # and first-price restore produce106,107,108.
    first_after_prefixes = base + len(counts) + 1
    stopped_origin = first_after_prefixes + 6 * 12 + 2
    return {
        "entry": "0x0",
        "base_before_foreign": hex(base),
        "natural_prefixes": prefixes,
        "predicted_first_no_gain32_origin": hex(stopped_origin),
        "consumed_prefix32_id_do_not_restore": prefixes[32],
        "still_expected_prefixes_after_that_stop": {
            count: snap for count, snap in prefixes.items() if count < 32
        },
        "expected_broadcasts_if_all_preceding_steps_succeeded": 229,
        "expected_actions_if_all_preceding_steps_succeeded": 226,
        "assumptions": [
            "No extra evm_snapshot calls after the recorded resume2 probe6.",
            "Stock cases completed all three paths and both restored price branches.",
            "All natural prefixes were captured before descending measurements.",
            "Six upper holder cases128,127,65,64,63,33 completed before32.",
            "Stop is the first no-gain32 probe, before any gain transfer or holder32 request.",
            "Snapshot counter remains monotone; restored IDs themselves are consumed.",
        ],
    }


def install_zero_offer_decline_observation(batch, module):
    """Repair only the runner's absent=True observation, with zero broadcasts.

    Normal dispatch checks are unchanged. For the no-gain branch the genuine dry
    CLI candidate is retained, then the real sender's pending preflight and offer
    feed the same default profitability gate used by the ordinary keeper.
    """
    if batch.pid != OWNED_PID or module.RPC != OWNED_RPC:
        raise RuntimeError("Wrong batch/node for this reviewed recovery")
    if module.digest(module.PLAN) != PLAN_SHA256:
        raise RuntimeError("Approved plan changed")
    original = batch.ordinary_dispatch

    def checked_dispatch(sig, args, absent=False):
        if not absent:
            return original(sig, args, absent=False)
        if sig != "sync(uint256[],uint256,uint256)" or len(args) != 3 or module.num(args[-1]) != 0:
            raise RuntimeError("Unexpected zero-offer observation request")
        batch.guard()
        counters_before = (batch.broadcasts, batch.external_value, len(batch.actions))
        head_before = batch.rpc("eth_getBlockByNumber", "latest", False)["hash"]
        nonces_before = {role: module.num(batch.cast("nonce", address))
                         for role, address in module.ACTORS.items()}
        # This records the real printed candidate and verifies exact calldata.
        # It neither asserts absence nor runs the CLI with --send.
        record = original(sig, args, absent=False)
        base, fees = batch.inclusion()
        sender = module.ACTORS["keeper"]
        state_path = batch.work / ("zero-offer-preflight-" + str(len(batch.state.get("ordinary_dispatches", []))) + ".json")
        manager = module.txm.TxManager(module.RPC, str(state_path), sender, [])
        try:
            estimate, reason, expected = manager.preflight(batch.vault, [sig, *args], fees)
        finally:
            manager._lockf.close()
        if estimate is None:
            raise RuntimeError("Zero-offer exact preflight failed: " + str(reason))
        offer = module.num(batch.cast("call", batch.vault, sig, *args,
                                      "--from", sender, "--block", "pending", *fees))
        ratio = module.keeper_client.billed_ratio(None, "sync")
        cost, need, accepted = module.keeper_client.profitability_gate(
            estimate, base + 50_000_000, offer, 0, 0, 0, ratio
        )
        if offer != 0 or cost <= 0 or need <= 0 or accepted:
            raise RuntimeError("No-gain tail was not a zero-offer default-gate decline")
        nonces_after = {role: module.num(batch.cast("nonce", address))
                        for role, address in module.ACTORS.items()}
        if (batch.broadcasts, batch.external_value, len(batch.actions)) != counters_before:
            raise RuntimeError("Observation changed cumulative action limits")
        if nonces_after != nonces_before or batch.rpc("eth_getBlockByNumber", "latest", False)["hash"] != head_before:
            raise RuntimeError("A transaction or block appeared during the observation")
        record.update(
            sync_absent=False,
            sync_planned=True,
            execution_declined=True,
            broadcast=False,
            zero_offer_proof=dict(
                estimate=estimate,
                exact_arguments=[sig, *args],
                sender=sender,
                pending_basefee_wei=base,
                bid_wei=base + 50_000_000,
                offer_wei=offer,
                billed_ratio=ratio,
                expected_cost_wei=cost,
                required_payment_wei=need,
                fail_rate_bps=0,
                min_return_bps=0,
                max_loss_wei=0,
                shared_gate_accepted=accepted,
                actor_nonces_unchanged=True,
                chain_head_unchanged=True,
                counters_unchanged=True,
            ),
        )
        batch.save()
        return record

    batch.ordinary_dispatch = checked_dispatch


def install_future_snapshot_id_log(batch):
    """Log future IDs without allocating any additional node snapshots."""
    original = batch.snapshot

    def logged_snapshot():
        snap = original()
        batch.state.setdefault("recovery_snapshot_ids", []).append(
            dict(id=snap, broadcasts=batch.broadcasts,
                 action_count=len(batch.actions), external_value_wei=batch.external_value)
        )
        batch.save()
        return snap

    batch.snapshot = logged_snapshot


if __name__ == "__main__":
    raise SystemExit("Review-only definitions: no batch, node or transaction action was executed")
