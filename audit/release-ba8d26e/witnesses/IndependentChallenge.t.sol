// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";

contract IndependentCheckpointCaller {
    function run(PackVault vault) external returns (uint256) {
        require(block.basefee == 0.15 gwei, "basefee inside call");
        require(tx.gasprice == 0.2 gwei, "gas price inside call");
        return vault.checkpoint(0);
    }
}

/// @notice Independent launch-audit challenge: an unpaid empty checkpoint consumes the only
///         slot in a blackout interval before a holder can request redemption.
contract IndependentChallenge is ForkBase {
    function test_emptyDistributionCheckpointDelaysRedemption() public {
        VaultLib.Params memory p = vault.getParams();
        p.distributionBps = 1_000;
        vm.prank(owner);
        vault.setParams(p);

        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        uint256 aliceShares = vault.shareBalance(alice);
        assertGt(aliceShares, 0, "holder received shares");

        // A new interval, with no pending deposits/redemptions and no distribution due.
        toBlackout();
        assertTrue(FWA.isPurchaseBlackout(), "real FWA blackout");
        assertEq(FWA.unsettledAcquisitionCount(), 0, "real FWA queue drained");
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.lockedShares(), 0);
        uint256 priorReserve = vault.distributionReserve();
        IndependentCheckpointCaller attacker = new IndependentCheckpointCaller();
        vm.prank(bob);
        uint256 pay = attacker.run(vault);
        assertEq(pay, 0, "attacker is unpaid");
        assertEq(vault.distributionReserve(), priorReserve, "no distribution occurred");
        assertEq(vault.lastCheckpointInterval(), block.timestamp / INTERVAL);

        uint256 request = vault.requestCharge();
        uint256 unwind = M.mulDiv(M.mulDiv(aliceShares, vault.lastNav(), vault.totalShares()),
            vault.unwindCharge(), 0.0663 ether);
        uint256 exactCharge = request + unwind;
        emit log_named_uint("request charge wei", request);
        emit log_named_uint("unwind charge wei", unwind);
        emit log_named_uint("exact redemption charge wei", exactCharge);
        vm.prank(alice);
        vault.requestRedeem{value: exactCharge}(aliceShares);
        assertEq(vault.processingPool(), request, "exact checkpoint request charge held");
        assertEq(vault.lockedShares(), aliceShares);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vm.prank(keeper);
        vault.checkpoint(0);
    }
}
