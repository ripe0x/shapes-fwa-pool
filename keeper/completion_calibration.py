"""Bounded billed local-fork calibration through the deployed production account and real minters."""
import json
from pathlib import Path


def calibrate_receipts(R, reuse_launch=False, half_only=False):
    from config import PARAMS_T, tuple_arg
    B, account, owner = R.B, R.MANAGERS[0], R.B.ACTORS['mgra']
    snapshot = B.rpc('evm_snapshot')
    rows = []
    try:
        initial_capital=R.num(R.cast('balance',account))
        # Real transfers from already checked wallets, never protocol balance overrides.
        R.send(owner, account, '', value=88*10**17)
        R.send(B.ACTORS['purchaser'], account, '', value=95*10**17)
        R.send(B.ACTORS['backup'], account, '', value=57*10**17)
        defaults = json.loads((Path(R.ROOT)/'deploy/manager.json').read_text())
        shapes = defaults['shapes'] if 'shapes' in defaults else json.loads((Path(R.ROOT)/'deploy/mainnet.json').read_text())['shapes']
        fee_admin = R.call(shapes, 'admin()(address)')
        gaps=[]
        if reuse_launch:
            actions=[json.loads(line) for line in Path(B.load_manifest()['actions']).read_text().splitlines()]
            reused=[row['receipt']['transactionHash'] for row in actions if row.get('function','').startswith('build(') and row.get('arguments',[None])[0]==3 and row.get('receipt') and row.get('vault_context',{}).get('source_sha256')==B.CURRENT_DEPLOYMENT['source_sha256']]
            if len(reused)<2:
                raise RuntimeError('missing preserved current-source launch receipts to reuse')
            rows.append(dict(reusedLaunchReceiptHashes=reused,reason='unchanged launch cells already passed before external-service timeout'))
        for actual_fee in ((5*10**14,) if half_only else (10**15, 5*10**14)):
            admin_code=R.cast('code',fee_admin)
            if actual_fee != 10**15 and admin_code != '0x' and not (len(admin_code)==48 and admin_code.startswith('0xef0100')):
                gaps.append('Half-fee billed receipt unavailable: actual Shapes.admin() has code; no EOA signature is fabricated for that contract.')
                continue
            fee_snapshot = B.rpc('evm_snapshot')
            try:
                if R.num(R.call(shapes,'mintFee()(uint256)')) != actual_fee:
                    R.send(fee_admin, shapes, 'setMintFee(uint256)', actual_fee)
                for total_price in (() if reuse_launch and actual_fee==10**15 else (200_000_000,500_000_000)):
                    cell = B.rpc('evm_snapshot')
                    try:
                        # Set the next empty block's environment, then authenticate its normal
                        # deterministic successor with the same pending-context path as the keeper.
                        desired_base = total_price-50_000_000
                        B.rpc('anvil_setNextBlockBaseFeePerGas',hex(desired_base*8//7))
                        B.rpc('evm_mine')
                        base,_=B.pending_fees()
                        before=R.num(R.call(shapes,'pendingFees()(uint256)'))
                        k,backing,ok=R.edge3(account,3)
                        if not ok:
                            raise RuntimeError('launch calibration lacks real admission economics')
                        R.send(R.KEEPER,account,'build(uint256,uint256[],uint256)',3,f'[{backing}]',0)
                        paid_fee=R.num(R.call(shapes,'pendingFees()(uint256)'))-before
                        if paid_fee != 3*actual_fee:
                            raise RuntimeError('creator revenue differs from three paid primary mints')
                        rows.append(dict(units=3,count=1,shapes=3,actualMintFeeWei=actual_fee,
                            acceptedMintFeeWei=defaults['acceptedMintFeeWei'],configuration=defaults,baseFeeWei=base,totalGasPriceWei=base+50_000_000,
                            paidCreatorFeeWei=paid_fee,k=k,backingWei=backing))
                    finally:
                        if not B.rpc('evm_revert',cell):
                            raise RuntimeError('calibration cell snapshot restore failed')
            finally:
                if not B.rpc('evm_revert',fee_snapshot):
                    raise RuntimeError('fee sensitivity snapshot restore failed')
        extreme = defaults | {'packUnitsMask': (1<<3)|(1<<29)|(1<<30)}
        if not half_only:
            R.send(owner, account, f'setParams({PARAMS_T})', tuple_arg(extreme))
        for units in (() if half_only else (29,30)):
            cell=B.rpc('evm_snapshot')
            try:
                B.rpc('anvil_setNextBlockBaseFeePerGas',hex(150_000_000*8//7));B.rpc('evm_mine')
                base,_=B.pending_fees()
                k,backing,ok=R.edge3(account,units)
                if not ok:
                    raise RuntimeError('extreme recipe lacks real admission economics')
                proposals=[backing+i*10_000 for i in range(4)]
                R.send(R.KEEPER,account,'build(uint256,uint256[],uint256)',units,'['+','.join(map(str,proposals))+']',0)
                rows.append(dict(units=units,count=4,shapes=(7 if units==29 else 3)*4,actualMintFeeWei=10**15,
                    baseFeeWei=base,k=k,backingWei=backing,configuration=extreme,transactionGasLimit=B.MAX_GAS))
            finally:
                if not B.rpc('evm_revert',cell):
                    raise RuntimeError('extreme recipe snapshot restore failed')
        if not half_only:
            batch=B.rpc('evm_snapshot')
            try:
                for group in range(4):
                    _,backing,ok=R.edge3(account,3)
                    if not ok:
                        raise RuntimeError('sixteen-pack calibration lacks real admission')
                    proposals=[backing+(group*4+i)*10_000 for i in range(4)]
                    R.send(R.KEEPER,account,'build(uint256,uint256[],uint256)',3,'['+','.join(map(str,proposals))+']',0)
                ids=R.ids(account)
                if len(ids)!=16:
                    raise RuntimeError('sixteen real listed packs were not built')
                R.send(owner,account,'setExiting(bool)','true')
                now=R.num(R.cast('block','latest','--field','timestamp'))
                B.rpc('evm_setNextBlockTimestamp',now+43201);B.rpc('evm_mine')
                B.rpc('anvil_setNextBlockBaseFeePerGas',hex(150_000_000*8//7));B.rpc('evm_mine')
                R.send(R.KEEPER,account,'unlist(uint256[],uint256)','['+','.join(map(str,ids))+']',1)
                B.rpc('anvil_setNextBlockBaseFeePerGas',hex(150_000_000*8//7));B.rpc('evm_mine')
                R.send(R.KEEPER,account,'liquidate(uint256,uint256)',16,1)
                if R.num(R.call(account,'openListingCount()(uint256)')) or R.num(R.call(account,'idlePackCount()(uint256)')):
                    raise RuntimeError('sixteen-pack real exit left tracked inventory')
                rows.append(dict(units=3,count=16,shapes=48,operation='unlist and liquidate hard-bound calibration',
                    positiveMinPayWei=1,totalGasPriceWei=200_000_000))
            finally:
                if not B.rpc('evm_revert',batch):
                    raise RuntimeError('sixteen-pack branch restore failed')
        B.append_action(dict(operation='completion bounded receipt calibration',cells=rows,
            limitation='No billed authenticated VRF renewal; gas proxy extrapolation requires its own stated margin'))
        return dict(cells=rows,gaps=gaps,upfrontCalibrationCapitalWei=initial_capital+24*10**18,renewalFloatCount=defaults['renewalFloatCount'],reserveWei=defaults['reserveWei'],restored=True)
    finally:
        if not B.rpc('evm_revert',snapshot):
            raise RuntimeError('calibration branch restore failed')
