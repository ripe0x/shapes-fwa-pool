// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {LISTING_ACTIVE, LISTING_WITHDRAWN} from "../../src/interfaces/External.sol";

contract ForkVaultLifecycleTest is ForkBase {
    function _depositAndPrice(address who, uint256 amount) internal {
        vm.prank(who);
        vault.deposit{value: amount}();
        toBlackout();
        checkpoint();
        toOpen();
    }

    function _listN(uint256 n) internal returns (uint256[] memory ids) {
        vm.startPrank(keeper);
        vault.restock(n, 3);
        vault.list(n);
        vm.stopPrank();
        ids = vault.openListings();
    }

    function test_edgeMatchesLiveFwa() public view {
        (uint256 k, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        // k = 1.05 x 0.99 x 0.999 at the pinned block.
        assertApproxEqAbs(k, 1.0384605e18, 1e12);
        assertEq(backing, B);
    }

    function test_depositListRedeem_roundTrip() public {
        _depositAndPrice(alice, 2 ether);
        uint256 shares = vault.totalShares() - vault.DEAD_SHARES();
        uint256 seed = 0.01 ether + preexisting;
        uint256 supply = vault.totalShares();
        // First depositor at seed price: 2 ETH buys 2 / seed times the dead shares.
        assertEq(shares, 2 ether * vault.DEAD_SHARES() / seed);

        uint256 balBefore = address(vault).balance;
        uint256[] memory ids = _listN(10);
        assertEq(ids.length, 10);
        // Absolute flows: 3 mints of 0.1 ETH + 0.001 fee, 10 listings at 0.0363.
        assertEq(balBefore - address(vault).balance, 3 * 0.101 ether + 10 * B);
        for (uint256 i; i < ids.length; ++i) {
            (,,,,, uint256 value,,,,, uint8 status) = FWA.listings(ids[i]);
            assertEq(value, B);
            assertEq(status, LISTING_ACTIVE);
        }

        // Alice exits everything. First checkpoint fills from free ETH, the rest waits.
        vm.prank(alice);
        vault.requestRedeem(shares);
        toBlackout();
        checkpoint();
        assertGt(vault.lockedShares(), 0, "partial fill leaves shares locked");

        // The shortfall unlocks unlisting, then the next checkpoint fills the rest.
        vm.prank(keeper);
        vault.unlist(ids);
        assertEq(vault.openListings().length, 0);
        toOpen();
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0);

        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        // NAV lost exactly the three 0.001 mint fees; alice owns her share of the rest.
        uint256 nav = seed + 2 ether - 0.003 ether;
        uint256 expected = nav * shares / supply;
        assertApproxEqAbs(alice.balance - before, expected, 1e6);
    }

    function test_kickReturnsFullBackingAndPack() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        // FWA's oracle owner lowers the ask: 0.030 x 1.10 = 0.033 < 0.0363 posted backing.
        setPackAsk(0.03 ether);
        toBlackout();
        uint256 before = address(vault).balance;
        IFwaAdmin(address(FWA)).kickListing(ids[0]);
        assertEq(address(vault).balance - before, B, "kick returns full backing");
        (,,,,,,,,,, uint8 status) = FWA.listings(ids[0]);
        assertEq(status, LISTING_WITHDRAWN);
        vault.sync(ids);
        assertEq(vault.openListings().length, 1);
        assertEq(vault.idlePacks().length, 1);
        // New cap 0.033 still clears the keep gate B (k - s) >= P: 0.033 x 1.0285 > 0.03.
        (, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        assertEq(backing, 0.033 ether);
    }

    function test_edgeGateStopsListingWhenCrownShareRaised() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        vm.prank(keeper);
        vm.expectRevert(PackVault.UnlistNotAllowed.selector);
        vault.unlist(ids);

        // FWA's owner puts the crown share back to 5%: k = 0.9875, the edge is gone.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(15, 500);
        (uint256 k,, bool ok) = vault.edge(3);
        assertFalse(ok);
        assertLt(k, 1e18);
        vm.startPrank(keeper);
        vault.restock(1, 3);
        vm.expectRevert(PackVault.EdgeGate.selector);
        vault.list(1);
        uint256 before = address(vault).balance;
        vault.unlist(ids);
        vm.stopPrank();
        assertEq(address(vault).balance - before, 2 * B);
    }

    function test_staleQuoteStopsListing() public {
        vm.warp(block.timestamp + 6 days);
        (,, bool ok) = vault.edge(3);
        assertFalse(ok, "quote older than FWA's 7 day max age");
    }

    function test_guardianCannotMoveAssets() public {
        _depositAndPrice(alice, 1 ether);
        _listN(2);
        uint256 bal = address(vault).balance;
        uint256 gBal = guardian.balance;
        vm.startPrank(guardian);
        vault.guard(true, true, true, true);
        vault.lowerCaps(1 ether, 10, 1 gwei);
        vault.startWindDown();
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.lowerCaps(2 ether, 10, 1 gwei);
        vm.stopPrank();
        assertEq(address(vault).balance, bal);
        assertEq(guardian.balance, gBal);
        vm.prank(guardian);
        vm.expectRevert(PackVault.NotAdmin.selector);
        vault.proposeParams(defaultParams());
    }

    function test_paramsDelayAndBounds() public {
        PackVault.Params memory p = defaultParams();
        p.distributionBps = 6_000;
        vm.prank(admin);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.proposeParams(p);
        p.distributionBps = 1_000;
        vm.prank(admin);
        vault.proposeParams(p);
        vm.expectRevert(PackVault.TooEarly.selector);
        vault.applyParams();
        vm.warp(block.timestamp + 2 days);
        vault.applyParams();
        (,, uint16 dist,,,,,,,,,,,,) = vault.params();
        assertEq(dist, 1_000);
    }

    function test_cancelDepositBeforePricing() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.cancelDeposit();
        assertEq(alice.balance - before, 1 ether);
        assertEq(vault.pendingDepositTotal(), 0);
    }

    function test_proRataRedemptionAcrossCheckpoints() public {
        _depositAndPrice(alice, 1 ether);
        _depositAndPrice(bob, 1 ether);
        _listN(20);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        assertEq(aShares, bShares);
        vm.prank(alice);
        vault.requestRedeem(aShares);
        vm.prank(bob);
        vault.requestRedeem(bShares / 2);
        toBlackout();
        checkpoint();
        vm.prank(alice);
        vault.claim();
        vm.prank(bob);
        vault.claim();
        (uint128 aLeft,,,) = vault.redemptions(alice);
        (uint128 bLeft,,,) = vault.redemptions(bob);
        // Same fill fraction for both: alice's remaining is twice bob's.
        assertApproxEqAbs(uint256(aLeft), 2 * uint256(bLeft), 2);
    }

    function test_windDownCompletesWithNoAcquisitions() public {
        _depositAndPrice(alice, 1 ether);
        _depositAndPrice(bob, 0.5 ether);
        uint256[] memory ids = _listN(8);
        vm.prank(guardian);
        vault.startWindDown();
        vm.prank(keeper);
        vault.unlist(ids);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        vm.prank(alice);
        vault.requestRedeem(aShares);
        vm.prank(bob);
        vault.requestRedeem(bShares);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0);
        vm.prank(alice);
        vault.claim();
        vm.prank(bob);
        vault.claim();
        // Only the dead shares' slice of NAV remains: the seed less its share of mint fees.
        assertEq(vault.idlePacks().length, 0);
        uint256 seed = 0.01 ether + preexisting;
        uint256 nav = seed + 1.5 ether - 0.003 ether; // 24 Shapes: three 0.1 ETH mints
        uint256 deadSlice = nav * seed / (seed + 1.5 ether);
        // Liquidation stops once redemptions are covered: leftover 0.01 Shapes stay as inventory.
        assertApproxEqAbs(address(vault).balance + vault.looseShapeCount() * 0.01 ether, deadSlice, 1e12);
        assertEq(vault.lastNav(), deadSlice + 1, "dead shares' NAV");
    }
}
