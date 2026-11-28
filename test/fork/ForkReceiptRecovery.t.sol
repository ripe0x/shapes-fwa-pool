// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {managerParams} from "./ForkManager.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {LISTING_ALLOCATED, LISTING_WITHDRAWN} from "../../src/interfaces/External.sol";

interface IFwaFinalize {
    function finalizeUnsettled(uint256 listingId) external;
    function finalizeWindow() external view returns (uint256);
}

/// @notice Receipt paths through the unchanged real receiver and real FWA payment routes.
/// @dev Missing-callback evidence from substituted runtime is historical, not compliant evidence.
///      Current real low-gas attempts either revert atomically or record the receipt. A missing
///      callback and an owed main ShapePack remain untested until reachable without faking state.
contract ForkReceiptRecoveryVaultTest is SelectionBase {
    receive() external payable {}

    function _status(uint256 id) internal view returns (uint8 status) { (,,,,,,,,,, status) = FWA.listings(id); }
    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function test_recordedKeepResolvesExactlyOnceAndStrangerCannotFabricateReceipt() public {
        Candidate memory c = primary();
        _select(c);
        uint256 packId = vault.position(selected).packId;
        vault.recover(new uint256[](0), 0);
        uint256 expected = B * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000;
        uint256 before = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        assertEq(address(vault).balance - before, expected);
        assertEq(vault.pendingReceipts(), 1, "real callback completed within FWA stipend");
        assertEq(PACKS.ownerOf(packId), c.purchaser);
        vm.expectRevert(VaultLib.PendingReceipts.selector);
        vault.accountedNav(0);
        address stranger = makeAddr("pack-vault-test-real-receipt-stranger");
        assertEq(stranger.code.length, 0);
        assertEq(stranger.balance, 0);
        vm.deal(stranger, expected);
        vm.prank(stranger);
        (bool sent,) = address(vault).call{value: expected}("");
        assertTrue(sent);
        assertEq(vault.pendingReceipts(), 1, "stranger adds no forged receipt");
        vault.recover(_one(selected), 0);
        assertEq(vault.pendingReceipts(), 0);
        assertEq(vault.position(selected).state, 0);
        assertEq(vault.idlePackCount(), 0);
        vault.accountedNav(0);
        vm.expectRevert(VaultLib.Nothing.selector);
        vault.recover(_one(selected), 0);
    }

    function test_defaultFinalizationUsesRealReceiverAndResolves() public {
        Candidate memory c = primary();
        _select(c);
        vault.recover(new uint256[](0), 0);
        vm.warp(vm.getBlockTimestamp() + IFwaFinalize(address(FWA)).finalizeWindow());
        uint256 before = address(vault).balance;
        IFwaFinalize(address(FWA)).finalizeUnsettled(selected);
        assertEq(address(vault).balance - before, B * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000);
        assertEq(vault.pendingReceipts(), 1, "actual default callback recorded");
        vault.recover(_one(selected), 0);
        assertEq(vault.position(selected).state, 0);
        assertEq(vault.pendingReceipts(), 0);
        vault.accountedNav(0);
    }

    /// @dev The real receiver, no code swapped: with too little transaction gas a keep either
    ///      reverts entirely or records its receipt. A forced send needs a 32,000 gas CREATE after
    ///      the failed call, but a receiver that ran out of gas leaves FWA at most 1/64 of it.
    function test_lowGasKeepNeverForcesAnUnrecordedPayment() public {
        Candidate memory c = primary();
        _select(c);
        uint256 snap = vm.snapshotState();
        uint256 before = address(vault).balance;
        uint256 failed;
        uint256 succeeded;
        for (uint256 g = 60_000; g <= 600_000; g += 6_000) {
            assertTrue(vm.revertToState(snap));
            vm.cool(address(vault));
            vm.cool(address(FWA));
            vm.cool(address(PACKS));
            vm.prank(c.purchaser);
            (bool ok,) = address(FWA).call{gas: g}(abi.encodeCall(IFwaSettle.keepNFT, (selected)));
            if (ok) {
                ++succeeded;
                assertEq(vault.pendingReceipts(), 1, "every completed keep is recorded");
            } else {
                ++failed;
                assertEq(address(vault).balance, before, "a failed keep moves nothing");
                assertEq(_status(selected), LISTING_ALLOCATED);
            }
        }
        emit log_named_uint("keep gas limits that reverted", failed);
        emit log_named_uint("keep gas limits that completed and recorded", succeeded);
        assertGt(failed, 0);
        assertGt(succeeded, 0);
    }
}

/// @notice Real kick callback, manager isolation and complete owner withdrawal.
contract ForkReceiptRecoveryManagerTest is ForkBase {
    PackManagerFactory factory;
    address carol = makeAddr("pack-vault-test-carol");

    receive() external payable {}

    function _status(uint256 id) internal view returns (uint8 status) {
        (,,,,,,,,,, status) = FWA.listings(id);
    }

    function setUp() public override {
        super.setUp();
        assertEq(carol.code.length, 0);
        assertEq(carol.balance, 0);
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS);
        vm.deal(carol, 50 ether);
    }

    function _create(address who, uint256 funding) internal returns (PackManager m) {
        bytes32 _expected5 = TestVaultOps.factoryHash(factory, managerParams());
        vm.prank(who);
        m = factory.create{value: funding}(who, managerParams(), _expected5);
    }

    function test_recordedKickRefund_resolvesAndOwnerExits() public {
        PackManager a = _create(alice, 1 ether);
        PackManager other = _create(carol, 1 ether);
        vm.prank(keeper);
        TestVaultOps.restock(a, 1, UNITS, 0);
        vm.prank(keeper);
        TestVaultOps.restock(other, 1, UNITS, 0);
        uint256 id = a.openListingAt(0);
        uint256 backing = a.position(id).backing;
        uint256 packId = a.position(id).packId;
        uint256 otherBalance = address(other).balance;

        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(0.03 ether);
        vm.warp(block.timestamp + 7 hours);
        vm.roll(block.number + 7 * 300);
        toBlackout();

        uint256 before = address(a).balance;
        IFwaAdmin(address(FWA)).kickListing(id);
        assertEq(address(a).balance - before, backing, "FWA returned full real backing");
        assertEq(_status(id), LISTING_WITHDRAWN);
        assertEq(PACKS.ownerOf(packId), address(a), "pack delivered back");
        assertEq(a.pendingReceipts(), 1, "real stipend receiver recorded the kick");

        uint256[] memory one = new uint256[](1);
        one[0] = id;
        bytes32 _expected3 = TestVaultOps.configurationHash(a);
        vm.prank(keeper);
        a.sync(one, 0, 0, _expected3);
        assertEq(a.openListingCount(), 0);
        assertEq(a.idlePackCount(), 1, "kicked pack back in inventory");
        bytes32 _expected4 = TestVaultOps.configurationHash(a);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Nothing.selector);
        a.sync(one, 0, 0, _expected4);

        // Complete exit: the pack and every wei.
        vm.startPrank(alice);
        a.withdrawPacks(alice, 1);
        a.withdraw(alice, address(a).balance);
        vm.stopPrank();
        assertEq(PACKS.ownerOf(packId), alice);
        assertEq(address(a).balance, 0);
        assertEq(address(other).balance, otherBalance, "the other manager is untouched");
        assertEq(other.openListingCount(), 1);
    }
}
