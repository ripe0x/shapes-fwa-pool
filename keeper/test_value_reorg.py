"""A real reverted value transfer re-included successfully on the owned rehearsal fork."""
from pathlib import Path
import json
import time


def exercise_value_reorg(R):
    import tx as T
    B, vault, signer = R.B, R.VAULT, R.KEEPER
    if R.num(R.call(vault, 'pendingDepositTotal()(uint256)')) or R.num(R.call(vault, 'lockedShares()(uint256)')):
        raise RuntimeError('value reorg regression needs no pending holder flows at entry')
    outer = B.rpc('evm_snapshot')
    path = str(Path(R.KEEPER_STATE).with_name('value-reorg-state.json'))
    manager = T.TxManager(R.RPC, path, signer, ['--unlocked', '--from', signer])
    try:
        base, _ = B.pending_fees()
        inner = B.rpc('evm_snapshot')
        expected = R.call(vault, 'configurationHash()(bytes32)')
        value = 100_000_000_000_000
        args = ['fundCheckpoint(bytes32)', expected, '--value', str(value)]
        cap=value+250_000*(2*base+50_000_000)
        manager.begin_signed_limit(cap)
        # This deliberately bypasses preflight to obtain the real failed receipt.
        manager.submit('fundCheckpoint', vault, args, 200_000, base, 50_000_000, 0)
        intent = dict(manager.state['pending'])
        if manager.wait(lambda *unused: 200_000, 30):
            raise RuntimeError('expected failed funding transaction did not confirm')
        failed = dict(manager.state['counted'][-1])
        if failed['status'] or failed['value_sent_wei'] or failed['transaction_value_wei'] != value:
            raise RuntimeError('failed value transfer did not preserve its original transaction value')
        if not B.rpc('evm_revert', inner):
            raise RuntimeError('value reorg branch could not be restored')
        manager.check_reorgs(R.num(R.cast('block-number')))
        reserved=manager.state['signed_upper_wei']
        if reserved!=cap:
            raise RuntimeError('orphaned transaction released its signed maximum reservation')
        try:
            manager._broadcast(intent | {'nonce':intent['nonce']+1})
        except T.SpendLimit:
            pass
        else:
            raise RuntimeError('orphaned reservation permitted another nonce to exceed the hard cap')
        shares = R.num(R.call(vault, 'shareBalance(address)(uint256)', R.HOLDER))
        if not shares:
            raise RuntimeError('value reorg regression requires the real holder position')
        charge = R.num(R.call(vault, 'requestCharge()(uint256)'))
        nav = R.num(R.call(vault, 'lastNav()(uint256)'))
        supply = R.num(R.call(vault, 'totalShares()(uint256)'))
        unwind = shares*nav//supply * R.num(R.call(vault,'unwindCharge()(uint256)')) // R.num(R.call(vault,'positionValue()(uint256)'))
        R.send(R.HOLDER, vault, 'requestRedeem(uint256)', shares, value=2*(charge+unwind))
        R.warp_to(42360)
        R.expire_queue()
        witness=R.num(R.call(vault,'openListingAt(uint256)(uint256)',0)) if R.num(R.call(vault,'openListingCount()(uint256)')) else 0
        R.send(R.HOLDER2, vault, 'checkpoint(uint256,uint256)', witness, 0)
        if not R.num(R.call(vault,'lockedShares()(uint256)')) or R.num(R.call(vault,'processingPool()(uint256)')):
            raise RuntimeError('real checkpoint must partially fill and close its funding era')
        # Identical nonce, calldata, value and fee fields produce the same transaction hash.
        moved_hash = manager._broadcast(intent)
        if moved_hash != failed['hash']:
            raise RuntimeError('identical re-included transaction has a different hash')
        for _ in range(100):
            if manager._receipt(moved_hash) is not None:
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('real re-included value transaction did not mine within10seconds')
        manager.check_reorgs(R.num(R.cast('block-number')))
        success = dict(manager.state['counted'][-1])
        if success['hash'] != failed['hash'] or not success['status'] or success['value_sent_wei'] != value:
            raise RuntimeError('same real transaction was not re-counted with its successful value debit')
        if success['checkpoint_contributed_wei'] <= 0 or success['overpayment_returned_wei'] != value-success['checkpoint_contributed_wei']:
            raise RuntimeError('new contribution and excess refund were not decoded from the canonical receipt')
        if manager.state['stats']['value_sent_wei'] != value or manager.state['stats']['checkpoint_contributed_wei'] != success['checkpoint_contributed_wei']:
            raise RuntimeError('reorg financial totals include stale reverted-receipt values')
        B.append_action(dict(operation='real reverted-to-successful contribution reorg', failed=failed, success=success,signedMaximumReservedWei=reserved,newNonceRefusedWhileOrphaned=True))
        return dict(same_hash=True, reverted_then_successful=True, contributed_wei=success['checkpoint_contributed_wei'], value_sent_wei=value,signedMaximumReservedWei=reserved,newNonceRefusedWhileOrphaned=True)
    finally:
        if not B.rpc('evm_revert', outer):
            raise RuntimeError('value reorg regression failed to restore its isolated branch')
        manager.check_reorgs(R.num(R.cast('block-number')))
        manager.save()
        manager._lockf.close()
