// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";
import {SelectionBase, IFwaSettle} from "../../fork/ForkSelection.t.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {LISTING_STAGED, LISTING_ACTIVE} from "../../../src/interfaces/External.sol";

contract AuditActivationGas is SelectionBase {
    receive() external payable {}
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    function test_busyQueueRefusesListing() public {
        _select(late());
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        assertGt(FWA.unsettledAcquisitionCount(), 0);
        vm.deal(address(this), 20 ether);
        (bool ok,) = address(vault).call{value: 10 ether}("");
        assertTrue(ok);
        // Repaired (audit B): build mints and lists each pack at once and refuses a busy queue
        // (unsettledAcquisitionCount != 0), so the 100 staged listings whose activation exceeded
        // EIP-7825 can no longer arise. The refusal now happens on build itself.
        uint256[] memory planned25 = TestVaultOps.proposals(vault, vault.MAX_LIST_BATCH(), 3);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.build(3, planned25, 0);
    }
}
