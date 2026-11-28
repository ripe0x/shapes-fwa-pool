// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

import {ForkBase} from "../../fork/ForkBase.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";

contract IndependentCheckpointCaller {
    function run(PackVault vault) external returns (uint256) {
        require(block.basefee == 0.15 gwei, "basefee inside call");
        require(tx.gasprice == 0.2 gwei, "gas price inside call");
        return TestVaultOps.checkpoint(vault, 0);
    }
}

/// @notice Independent launch-audit challenge (E3), as a regression: an empty checkpoint used to
///         consume the interval's only slot before a holder could request redemption.
contract IndependentChallenge is ForkBase {
    function test_emptyCheckpointRevertsAndLeavesSlotFree() public {
        VaultLib.Params memory p = vault.getParams();
        p.distributionBps = 1_000;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected0);
bytes32 _expected1 = TestVaultOps.configurationHash(vault);

        vm.prank(alice);
        vault.deposit{value: 1 ether}(_expected1);
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
        uint256 priorInterval = vault.lastCheckpointInterval();
        IndependentCheckpointCaller attacker = new IndependentCheckpointCaller();
        // Repaired (E3): a checkpoint that neither settles flows nor distributes reverts whole.
        vm.prank(bob);
        vm.expectRevert(PackVault.Nothing.selector);
        attacker.run(vault);
        assertEq(vault.distributionReserve(), priorReserve, "no distribution occurred");
        assertEq(vault.lastCheckpointInterval(), priorInterval, "the interval slot stays free");

        uint256 request = vault.requestCharge();
        uint256 exactCharge = request; // exits are unpaid; the redemption charge is just the checkpoint
        emit log_named_uint("request charge wei", request);
        emit log_named_uint("exact redemption charge wei", exactCharge);
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.requestRedeem{value: exactCharge}(aliceShares, _expected2);
        assertEq(vault.processingPool(), request, "exact checkpoint request charge held");
        assertEq(vault.lockedShares(), aliceShares);
        // The redemption prices in the same interval.
        vm.prank(keeper);
        TestVaultOps.checkpoint(vault, 0);
        assertEq(vault.lockedShares(), 0, "redemption priced without waiting an interval");
    }
}
