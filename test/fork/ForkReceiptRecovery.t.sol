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
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {LISTING_ALLOCATED, LISTING_SETTLED, LISTING_WITHDRAWN} from "../../src/interfaces/External.sol";

interface IFwaFinalize {
    function finalizeUnsettled(uint256 listingId) external;
    function finalizeWindow() external view returns (uint256);
}

/// @dev Stands in for an account's receive() that cannot finish inside FWA's 100,000 gas stipend
///      (for example after a gas repricing): it spends all the gas it is given.
contract StipendExhauster {
    receive() external payable {
        while (true) {}
    }
}

/// @dev FWA pays an account with Solady's forceSafeTransferETH: a 100,000 gas call, and when that
///      call fails, a SELFDESTRUCT that delivers the ETH with no code run. These tests make the
///      account's receive() fail by swapping its runtime code for StipendExhauster around the one
///      FWA call, then restoring the exact code (storage is untouched). Everything else is real:
///      FWA, its VRF replay, ShapePacks and FWA's own forced-send fallback.
/// @notice Pooled vault: a keep payment that arrives with no receipt resolves from FWA's record,
///         exactly once, and the vault's NAV is unavailable until it does.
contract ForkReceiptRecoveryVaultTest is SelectionBase {
    receive() external payable {} // keeper pay

    function _breakReceive(address account) internal returns (bytes memory code) {
        code = account.code;
        vm.etch(account, type(StipendExhauster).runtimeCode);
    }

    function _status(uint256 id) internal view returns (uint8 status) {
        (,,,,,,,,,, status) = FWA.listings(id);
    }

    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    /// @dev Normal path (receipt recorded) and forced path (no receipt) from the same state end in
    ///      the same book, balances and NAV. A stranger's ETH of exactly the payment amount never
    ///      makes or replaces a receipt.
    function test_forcedKeepPayment_resolvesLikeRecordedOne() public {
        Candidate memory c = primary();
        _select(c);
        uint256 packId = vault.position(selected).packId;
        uint256 paid = B * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000;
        vault.sync(new uint256[](0), 0, 0); // apply the selection: the journal is current, so only the
        assertEq(vault.position(selected).state, 2); // Allocated gate can stop pricing below
        uint256 snap = vm.snapshotState();

        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        assertEq(vault.pendingReceipts(), 1, "recorded inside the stipend");
        vm.expectRevert(VaultLib.PendingReceipts.selector);
        vault.accountedNav(0);
        TestVaultOps.sync(vault, _one(selected), 0);
        uint256 navRecorded = vault.accountedNav(0);
        uint256 balRecorded = address(vault).balance;
        uint256 keeperRecorded = address(this).balance;

        assertTrue(vm.revertToState(snap));
        uint256 before = address(vault).balance;
        bytes memory code = _breakReceive(address(vault));
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        vm.etch(address(vault), code);
        assertEq(address(vault).balance - before, paid, "FWA force-sent B (1 - s)");
        assertEq(PACKS.ownerOf(packId), c.purchaser, "the purchaser kept the pack");
        assertEq(_status(selected), LISTING_SETTLED);
        assertEq(vault.pendingReceipts(), 0, "no receipt was recorded");
        assertEq(vault.receipts(selected).kind, 0);

        // A fabricated payment of the exact amount: not from FWA, so no receipt, and no effect on
        // the outcome. It simply accrues to holders, like any forced ETH.
        address stranger = makeAddr("pack-vault-test-receipt-stranger");
        vm.deal(stranger, paid);
        vm.prank(stranger);
        (bool sent,) = address(vault).call{value: paid}("");
        assertTrue(sent);
        assertEq(vault.pendingReceipts(), 0, "a stranger cannot create a receipt");

        // Until the settled allocation is synced, the vault cannot be priced (it would count the
        // pack and its payment twice).
        vm.expectRevert(VaultLib.PendingReceipts.selector);
        vault.accountedNav(0);

        TestVaultOps.sync(vault, _one(selected), 0);
        assertEq(TestVaultOps.open(vault).length, 0);
        assertEq(TestVaultOps.idle(vault).length, 0, "kept: no pack came back");
        assertEq(vault.position(selected).state, 0, "retired");
        (uint256 tracked,,,,, uint256 allocated) = vault.totals();
        assertEq(tracked, 0);
        assertEq(allocated, 0);
        assertEq(address(this).balance, keeperRecorded, "same keeper pay as the recorded path");
        assertEq(address(vault).balance, balRecorded + paid, "same cash plus the stranger's gift");
        assertEq(vault.accountedNav(0), navRecorded + paid, "same NAV plus the gift, counted once");

        // Exactly once: the listing cannot be resolved again.
        vm.expectRevert(VaultLib.Nothing.selector);
        TestVaultOps.sync(vault, _one(selected), 0);
    }

    /// @dev FWA's default after its finalize window (anyone may call it) is a second push to the
    ///      depositor outside the account's own calls. Forced, it resolves the same way.
    function test_forcedDefaultFinalization_resolves() public {
        Candidate memory c = primary();
        _select(c);
        uint256 paid = B * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000;
        vault.sync(new uint256[](0), 0, 0); // apply the selection: the journal is current
        vm.warp(block.timestamp + IFwaFinalize(address(FWA)).finalizeWindow());
        uint256 before = address(vault).balance;
        bytes memory code = _breakReceive(address(vault));
        IFwaFinalize(address(FWA)).finalizeUnsettled(selected);
        vm.etch(address(vault), code);
        assertEq(address(vault).balance - before, paid);
        assertEq(vault.pendingReceipts(), 0);
        vm.expectRevert(VaultLib.PendingReceipts.selector);
        vault.accountedNav(0);
        TestVaultOps.sync(vault, _one(selected), 0);
        assertEq(vault.position(selected).state, 0);
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

/// @notice Personal manager: a kick refund that arrives with no receipt resolves from FWA's record
///         and the owner exits with everything, while another manager is untouched.
contract ForkReceiptRecoveryManagerTest is ForkBase {
    PackManagerFactory factory;
    address carol = makeAddr("pack-vault-test-carol");

    receive() external payable {}

    function _breakReceive(address account) internal returns (bytes memory code) {
        code = account.code;
        vm.etch(account, type(StipendExhauster).runtimeCode);
    }

    function _status(uint256 id) internal view returns (uint8 status) {
        (,,,,,,,,,, status) = FWA.listings(id);
    }

    function setUp() public override {
        super.setUp();
        assertEq(carol.code.length, 0);
        assertEq(carol.balance, 0);
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS, KeeperPolicyV1(address(vault.keeperPolicy())));
        vm.deal(carol, 50 ether);
    }

    function _create(address who, uint256 funding) internal returns (PackManager m) {
        vm.prank(who);
        m = factory.create{value: funding}(who, managerParams());
    }

    function test_forcedKickRefund_resolvesAndOwnerExits() public {
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
        bytes memory code = _breakReceive(address(a));
        IFwaAdmin(address(FWA)).kickListing(id);
        vm.etch(address(a), code);
        assertEq(address(a).balance - before, backing, "FWA force-sent the full backing");
        assertEq(_status(id), LISTING_WITHDRAWN);
        assertEq(PACKS.ownerOf(packId), address(a), "pack delivered back");
        assertEq(a.pendingReceipts(), 0, "no receipt was recorded");

        uint256[] memory one = new uint256[](1);
        one[0] = id;
        vm.prank(keeper);
        a.sync(one, 0, 0);
        assertEq(a.openListingCount(), 0);
        assertEq(a.idlePackCount(), 1, "kicked pack back in inventory");
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Nothing.selector);
        a.sync(one, 0, 0);

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
