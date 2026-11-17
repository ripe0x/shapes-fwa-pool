// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {ForkBase} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {Charges} from "../../utils/Charges.sol";

contract AuditFreeMismatch is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    function test_cancelChargeMakesKeeperMissShortfall() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
        p.gasCeiling = 0.5 gwei;
        p.payMarkupBps = 0;
        p.reserve = 0.005 ether;
        vm.prank(owner);
        vault.setParams(p);
        uint256 ck = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + ck}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        vault.restock(1, 3, 0);
        vm.prank(keeper);
        vault.list(1, 0);
        assertEq(vault.openListings().length, 1);
        uint256 cancelCharge = vault.requestCharge();
        for (uint256 i; i < 20; ++i) {
            vm.prank(bob);
            vault.deposit{value: 0.01 ether + cancelCharge}();
            vm.prank(bob);
            vault.cancelDeposit();
        }
        assertEq(vault.processingPool(), 20 * cancelCharge);
        assertEq(vault.pendingDepositTotal(), 0);
        uint256 realFreeBefore = address(vault).balance - vault.processingPool();
        uint256 supply = vault.totalShares();
        uint256 lastNav = vault.lastNav();
        uint256 unwind = vault.unwindCharge();
        uint256 positionValue = 0.0663 ether;
        uint256 targetNet = realFreeBefore + vault.processingPool() / 2;
        uint256 shares = targetNet * supply / lastNav * positionValue / (positionValue - unwind);
        assertLe(shares, vault.shareBalance(alice));
        uint256 redeemCharge = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: redeemCharge}(shares);
        uint256 owed = (shares * vault.lastNav() + vault.totalShares() - 1) / vault.totalShares();
        uint256 balance = address(vault).balance;
        uint256 realFree = balance - vault.processingPool();
        uint256 keeperFree = balance; // no other reserves; keeper.py omits processingPool
        emit log_named_uint("processing pool wei", vault.processingPool());
        emit log_named_uint("real free wei", realFree);
        emit log_named_uint("keeper free wei", keeperFree);
        emit log_named_uint("owed wei", owed);
        emit log_named_uint("locked shares", vault.lockedShares());
        assertGt(owed, realFree, "vault has actual redemption shortfall");
        assertLe(owed, keeperFree, "keeper computes no redemption shortfall");
        assertGt(vault.lockedShares(), 0);
        uint256 snap = vm.snapshotState();
        toBlackout();
        checkpoint();
        emit log_named_uint("shares still locked after keeper plan", vault.lockedShares());
        emit log_named_uint("remaining value estimate wei", vault.lockedShares() * vault.lastNav() / vault.totalShares());
        assertGt(vault.lockedShares(), 0, "keeper-only checkpoint gives a partial fill");
        vm.revertToState(snap);
        vm.prank(keeper);
        vault.liquidate(1, 0);
        assertEq(vault.looseShapeCount(), 6, "vault itself authorizes liquidation for the real cash shortfall");
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "one real Shape liquidation would fully fill the redemption");
    }
}
