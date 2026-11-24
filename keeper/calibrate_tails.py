"""Actual required small-tail receipts on the already owned fork; restore the entire branch."""
import json
from pathlib import Path
import rehearse_unified as R


def main():
    B=R.B
    actions=[json.loads(line) for line in Path(B.load_manifest()['actions']).read_text().splitlines()]
    context=next(row['vault_context'] for row in reversed(actions) if row.get('vault_context'))
    B.CURRENT_DEPLOYMENT=context
    R.VAULT=context['vault']
    R.TOKEN=R.call(R.FWA,'token()(address)')
    snapshot=B.rpc('evm_snapshot')
    rows=[]
    try:
        # Pure calibration capital; both setup funding and the complete branch are recorded.
        R.warp_to(42360);R.expire_queue()
        if R.num(R.call(R.VAULT,'lockedShares()(uint256)')):
            R.send(R.KEEPER,R.VAULT,'checkpoint(uint256,uint256)',0,0)
        ck=R.num(R.call(R.VAULT,'requestCharge()(uint256)'))
        R.send(R.HOLDER2,R.VAULT,'deposit()',value=2*R.E+ck)
        R.warp_to(42360);R.expire_queue()
        R.send(R.KEEPER,R.VAULT,'checkpoint(uint256,uint256)',0,0)
        R.warp_to(60);R.expire_queue()
        _,backing,ok=R.edge3(R.VAULT)
        if not ok:
            raise RuntimeError('tail calibration requires actual admission')
        R.send(R.KEEPER,R.VAULT,'build(uint256,uint256[],uint256)',3,'['+','.join(str(backing+i*10_000) for i in range(4))+']',0)
        witness=R.num(R.call(R.VAULT,'openListingAt(uint256)(uint256)',0))
        ck=R.num(R.call(R.VAULT,'requestCharge()(uint256)'))
        R.send(R.HOLDER2,R.VAULT,'deposit()',value=R.E//10+ck)
        for count in (1,17):
            cell=B.rpc('evm_snapshot')
            try:
                buyer=B.ACTORS['purchaser']
                start=R.num(R.call(R.VAULT,'acquisitionCursor()(uint64)'))
                for _ in range(count):
                    _,fees=B.pending_fees()
                    price=R.num(R.cast('call',R.FWA,'quoteAcquisitionPrice()(uint256,uint256,uint256)','--block','pending',*fees).splitlines()[2])
                    R.send(buyer,R.FWA,'acquire(address,uint256,uint256,uint256,uint256)',buyer,1,0,0,10000,value=price)
                R.expire_queue()
                R.send(buyer,R.FWA,'withdrawAcquisitionRefund()')
                R.warp_to(42360)
                B.rpc('anvil_setNextBlockBaseFeePerGas',hex(150_000_000*8//7));B.rpc('evm_mine')
                quote=R.num(R.call(R.VAULT,'requestCharge()(uint256)'))
                if quote:
                    R.send(R.HOLDER2,R.VAULT,'fundCheckpoint()',value=quote)
                    # Funding mines a block; restore the exact prospective fee environment.
                    B.rpc('anvil_setNextBlockBaseFeePerGas',hex(150_000_000*8//7));B.rpc('evm_mine')
                before=R.num(R.call(R.VAULT,'processingPool()(uint256)'))
                progress_snapshot=B.rpc('evm_snapshot')
                R.send(R.KEEPER,R.VAULT,'syncCheckpoint(uint256[],uint256,uint256)','[]',witness,0)
                end=R.num(R.call(R.VAULT,'acquisitionCursor()(uint64)'))
                if end-start != count:
                    raise RuntimeError('required tail did not verify every genuine expired request')
                paid=before-R.num(R.call(R.VAULT,'processingPool()(uint256)'))
                if not B.rpc('evm_revert',progress_snapshot):
                    raise RuntimeError('paid/unpaid tail comparison restore failed')
                R.send(R.KEEPER,R.VAULT,'recover(uint256[],uint256)','[]',witness)
                if R.num(R.call(R.VAULT,'acquisitionCursor()(uint64)'))-start != count or R.num(R.call(R.VAULT,'processingPool()(uint256)')) != before:
                    raise RuntimeError('unpaid recovery progress/source conservation differs')
                rows.append(dict(foreignRecords=count,openPositions=4,progress=end-start,
                    totalGasPriceWei=200_000_000,keeperPaidWei=paid,unpaidRecoveryKeeperPayWei=0))
            finally:
                if not B.rpc('evm_revert',cell):
                    raise RuntimeError('tail cell restore failed')
        B.append_action(dict(operation='actual required-tail calibration',cells=rows,setupDepositWei=21*R.E//10))
        print(json.dumps(rows,indent=1))
        return rows
    finally:
        if not B.rpc('evm_revert',snapshot):
            raise RuntimeError('tail calibration branch restore failed')


if __name__=='__main__':
    main()
