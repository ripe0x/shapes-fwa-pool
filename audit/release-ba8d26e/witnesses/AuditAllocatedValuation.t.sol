// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {SelectionBase, IFwaSettle} from "../fork/ForkSelection.t.sol";
import {Charges} from "../utils/Charges.sol";
import {LISTING_ALLOCATED} from "../../src/interfaces/External.sol";

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
    function path(bool syncFirst) internal returns (uint256 claimed, uint256 aliceValue, uint256 deadValue) {
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        if (syncFirst) {
            uint256 pay = vault.sync(one, 0);
            emit log_named_uint("early sync pay wei", pay);
        }
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        vault.checkpoint(0);
        if (!syncFirst) {
            uint256 pay = vault.sync(one, 0);
            emit log_named_uint("late sync pay wei", pay);
        }
        uint256 shares = vault.shareBalance(bob);
        uint256 charge = Charges.redeemCharge(vault, shares);
        vm.prank(bob);
        vault.requestRedeem{value: charge}(shares);
        toBlackout();
        vault.checkpoint(0);
        uint256 before = bob.balance;
        vm.prank(bob);
        vault.claim();
        claimed = bob.balance - before;
        emit log_named_uint(syncFirst ? "bob claim after early sync" : "bob claim after late sync", claimed);
        aliceValue = vault.shareBalance(alice) * vault.lastNav() / vault.totalShares();
        emit log_named_uint(syncFirst ? "alice value after early sync" : "alice value after late sync", aliceValue);
        deadValue = vault.shareBalance(address(0xdead)) * vault.lastNav() / vault.totalShares();
        emit log_named_uint(syncFirst ? "dead value after early sync" : "dead value after late sync", deadValue);
    }
    function test_earlyDepositorCapturesAllocatedUpliftFromExistingHolder() public {
        _select(late());
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        assertEq(bob.code.length, 0);
        assertEq(alice.code.length, 0);
        assertEq(bob.balance, 0);
        assertEq(alice.balance, 0);
        vm.deal(bob, 2 ether);
        vm.deal(alice, 2 ether);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7500);
        IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        (,,,,,,,,, uint64 allocatedAt, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED);
        assertGt(block.timestamp, uint256(allocatedAt) + FWA.settlementWindow());
        (, uint64 units, uint128 backing) = vault.positions(selected);
        assertEq(units, 3);
        assertEq(backing, B);
        assertEq(FWA.ownerSettlementFeeBps(), 100);
        emit log_named_uint("allocated pack floor wei", 0.03 ether);
        emit log_named_uint("reclaimable backing wei", uint256(backing) * 9900 / 10000);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(bob);
        vault.deposit{value: gross}();
        toBlackout();
        vault.checkpoint(0);
        assertGt(vault.shareBalance(bob), 0);
        toOpen();
        uint256 snap = vm.snapshotState();
        (uint256 lateClaim, uint256 lateAlice, uint256 lateDead) = path(false);
        vm.revertToState(snap);
        (uint256 earlyClaim, uint256 earlyAlice, uint256 earlyDead) = path(true);
        emit log_named_uint("bob loss due late sync", earlyClaim > lateClaim ? earlyClaim - lateClaim : 0);
        assertGt(earlyClaim, lateClaim, "pricing against a reclaimable allocated position dilutes earlier holder");
        assertGt(lateAlice, earlyAlice, "the new depositor receives the shifted value");
        emit log_named_uint("alice gain due late sync", lateAlice - earlyAlice);
        emit log_named_uint("dead seed slice lost due late sync", earlyDead - lateDead);
    }
}
