// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {SelectionBase, IFwaSettle} from "../../fork/ForkSelection.t.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {LISTING_STAGED, LISTING_ACTIVE} from "../../../src/interfaces/External.sol";

contract AuditActivationGas is SelectionBase {
    receive() external payable {}
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    function test_stagedActivationHundredAtCap() public {
        _select(late());
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        assertGt(FWA.unsettledAcquisitionCount(), 0);
        vm.deal(address(this), 20 ether);
        (bool ok,) = address(vault).call{value: 10 ether}("");
        assertTrue(ok);
        uint256[] memory beforeIds = vault.openListings();
        for (uint256 j; j < 10; ++j) {
            vault.restock(10, 3, 0);
            vault.list(10, 0);
        }
        uint256[] memory afterIds = vault.openListings();
        assertEq(afterIds.length, beforeIds.length + 100);
        uint256[] memory staged = new uint256[](100);
        for (uint256 i; i < 100; ++i) {
            staged[i] = afterIds[beforeIds.length + i];
            (,,,,,,,,,, uint8 status) = FWA.listings(staged[i]);
            assertEq(status, LISTING_STAGED);
        }
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7500);
        if (FWA.unsettledAcquisitionCount() != 0) IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        uint256 beforeGas = gasleft();
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.activate, (staged, 200, 0)));
        uint256 used = beforeGas - gasleft();
        emit log_named_uint("activate 100 staged gas used", used);
        emit log_named_uint("activate 100 succeeded", succeeded ? 1 : 0);
        if (!succeeded) {
            uint256 snap = vm.snapshotState();
            uint256 highGasBefore = gasleft();
            vault.activate{gas: 60_000_000}(staged, 200, 0);
            emit log_named_uint("activate 100 simulated gas needed", highGasBefore - gasleft());
            vm.revertToState(snap);
            uint256[] memory small = new uint256[](10);
            for (uint256 i; i < 10; ++i) small[i] = staged[i];
            vault.activate{gas: 16_000_000}(small, 10, 0);
            (,,,,,,,,,, uint8 status) = FWA.listings(small[0]);
            assertEq(status, LISTING_ACTIVE, "split activation succeeds");
        } else {
            (,,,,,,,,,, uint8 status) = FWA.listings(staged[99]);
            assertEq(status, LISTING_ACTIVE);
        }
    }
}
