// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";
import {SelectionBase, IFwaSettle} from "../../fork/ForkSelection.t.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {Charges} from "../../utils/Charges.sol";
import {LISTING_ALLOCATED} from "../../../src/interfaces/External.sol";

contract AuditAllocatedValuation is SelectionBase {
    receive() external payable {}
    address bob = makeAddr("pack-vault-test-allocated-bob");
    address alice = makeAddr("pack-vault-test-allocated-alice");
    uint256 constant INTERVAL = 12 hours;
    uint256 constant BLACKOUT = 11 hours + 45 minutes;
    function toBlackout() internal {
        uint256 t = block.timestamp;
        uint256 start = t - t % INTERVAL + BLACKOUT;
        if (t >= start) start += INTERVAL;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
    }
    function toOpen() internal {
        uint256 t = block.timestamp;
        uint256 next = t - t % INTERVAL + INTERVAL + 60;
        vm.warp(next);
        vm.roll(block.number + (next - t) / 12);
    }
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    /// Repaired (E6): a checkpoint refuses to price while an allocation past its window is
    /// unsynced, so a new deposit never prices against its lower bound; sync (anyone, paid)
    /// resolves it and the checkpoint then runs in the same blackout.
    function test_expiredAllocationMustSyncBeforePricing() public {
        _select(primary());
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        assertEq(bob.code.length, 0);
        assertEq(bob.balance, 0);
        vm.deal(bob, 2 ether);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7500);
        IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        (,,,,,,,,, uint64 allocatedAt, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED);
        assertGt(block.timestamp, uint256(allocatedAt) + FWA.settlementWindow());

        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(bob);
        vault.deposit{value: gross}();
        toBlackout();
        vault.sync(new uint256[](0), 0, 0);
        uint256 interval = vault.lastCheckpointInterval();
        uint256 planned24 = TestVaultOps.witness(vault);
        vm.expectRevert(PackVault.SyncFirst.selector);
        vault.checkpoint(planned24, 0);
        assertEq(vault.lastCheckpointInterval(), interval, "slot not consumed");
        assertEq(vault.shareBalance(bob), 0, "not priced");

        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        uint256 bal = address(vault).balance;
        TestVaultOps.sync(vault, one, 0);
        // Net backing 0.035937 ETH > pack 0.03 ETH: sync reclaimed the backing.
        assertGt(address(vault).balance, bal, "backing reclaimed");
        TestVaultOps.checkpoint(vault, 0);
        assertGt(vault.shareBalance(bob), 0, "priced after the sync, same blackout");
    }
}
