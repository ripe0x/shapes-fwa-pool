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
        uint256 kBefore = keeper.balance;
        uint256[] memory ids = _listN(10);
        assertEq(ids.length, 10);
        // Absolute flows: 3 mints of 0.1 ETH + 0.001 fee, 10 listings at 0.0363, keeper gas pay.
        uint256 pay = keeper.balance - kBefore;
        assertGt(pay, 0, "restock and list are paid");
        assertEq(balBefore - address(vault).balance, 3 * 0.101 ether + 10 * B + pay);
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

        // The shortfall unlocks unlisting and liquidation, then the next checkpoint fills the rest.
        vm.startPrank(keeper);
        vault.unlist(ids);
        vault.liquidate(40);
        vm.stopPrank();
        assertEq(vault.openListings().length, 0);
        toOpen();
        toBlackout();
        uint256 payBeforeLast = keeper.balance - kBefore;
        checkpoint();
        assertEq(vault.lockedShares(), 0);

        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        // Every wei: alice's claim + mint fees + all keeper pay + what is left = seed + deposit.
        uint256 got = alice.balance - before;
        uint256 allPay = keeper.balance - 1 ether;
        assertEq(got + 0.003 ether + allPay + address(vault).balance, seed + 2 ether);
        // Alice bears her share of the mint fees and of the keeper pay after her pricing (the
        // order of fills makes the exact split path-dependent, so bound it on both sides).
        assertLe(got, (seed + 2 ether - 0.003 ether) * shares / supply);
        assertGe(got, (seed + 2 ether - 0.003 ether - allPay) * shares / supply);
        payBeforeLast;
        // About 20.7M gas reimbursed at 0.2 gwei plus 10%: restock 10 (9.2M), list 10 (5.7M),
        // unlist, liquidate and three checkpoints.
        assertLt(allPay, 0.005 ether);
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

    /// Repair: sync and unlist skip ids they cannot act on, so a keeper padding a call with junk
    /// ids was paid the premium on the padding. Pay is now capped per position actually moved.
    function test_paddedSyncPaysOnlyForWorkDone() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        setPackAsk(0.03 ether);
        toBlackout();
        IFwaAdmin(address(FWA)).kickListing(ids[0]); // a real kick: one position to resolve
        uint256[] memory padded = new uint256[](400);
        padded[0] = ids[0];
        for (uint256 i = 1; i < padded.length; ++i) {
            padded[i] = 1e9 + i; // ids the vault never held
        }
        uint256 before = keeper.balance;
        uint256 g = gasleft();
        vm.prank(keeper);
        vault.sync(padded);
        uint256 used = g - gasleft();
        uint256 pay = keeper.balance - before;
        // Price here is min(0.2 gwei, 0.15 + 0.05 tip) = 0.2 gwei, plus the 10% premium.
        // (+2k gas: the cap is taken just before the reimbursement code itself runs.)
        uint256 cap = (vault.GAS_PER_MOVED() + vault.KEEPER_OVERHEAD_GAS() + 2_000) * 0.2 gwei * 11_000 / 10_000;
        assertGt(used, vault.GAS_PER_MOVED(), "the padding really cost gas");
        assertLe(pay, cap, "paid for one moved position, not the padding");
        assertEq(vault.idlePacks().length, 1);
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
        // No edge: no capital goes into new packs or listings.
        vm.expectRevert(PackVault.EdgeGate.selector);
        vault.restock(1, 3);
        uint256 before = address(vault).balance;
        uint256 kBefore = keeper.balance;
        vault.unlist(ids);
        vm.stopPrank();
        assertEq(address(vault).balance - before + (keeper.balance - kBefore), 2 * B, "backing back, less gas pay");
    }

    /// Repair: a gas spike or a stale quote stops new listings but must not let anyone unwind
    /// earning positions (old code allowed unlisting whenever the full gate failed).
    function test_staleQuoteDoesNotUnlockUnlisting() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        vm.warp(block.timestamp + 6 days); // quote past FWA's max age: listing gate fails
        (,, bool ok) = vault.edge(3);
        assertFalse(ok);
        vm.prank(keeper);
        vm.expectRevert(PackVault.UnlistNotAllowed.selector);
        vault.unlist(ids);
    }

    /// Repair: unlisting read the oracle through edge(), so an oracle FWA's owner repoints to a
    /// contract that reverts blocked wind-down and redemptions. Now a failed read means no cap.
    function test_windDownSurvivesBrokenOracle() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(3);
        // FWA's owner repoints the floor oracle (config key 64) to a contract with no such
        // function: ShapePacks rejects unknown calls.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(PACKS));
        (, uint256 backing, bool ok) = vault.edge(3);
        assertFalse(ok, "no cap: nothing new lists");
        assertEq(backing, 0);
        vm.prank(guardian);
        vault.startWindDown();
        uint256 before = address(vault).balance;
        vm.prank(keeper);
        vault.unlist(ids);
        assertGe(address(vault).balance + (keeper.balance - 1 ether), before + 3 * B, "backing back");
        vm.prank(keeper);
        vault.liquidate(40);
        uint256 shares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(shares);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "redemption completes without the oracle");
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
        // Review S1: the reimbursed tip can never exceed the gas ceiling itself.
        p.maxTip = p.gasCeiling + 1;
        vm.prank(admin);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.proposeParams(p);
        p.maxTip = 0.05 gwei;
        vm.prank(admin);
        vault.proposeParams(p);
        vm.expectRevert(PackVault.TooEarly.selector);
        vault.applyParams();
        vm.warp(block.timestamp + 2 days);
        vault.applyParams();
        assertEq(vault.getParams().distributionBps, 1_000);
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
        // Same fill fraction for both. Bob priced one checkpoint later, after that checkpoint's
        // keeper pay, so his share count differs slightly from alice's.
        assertApproxEqAbs(uint256(aLeft) * (bShares / 2), uint256(bLeft) * aShares, aShares * 2);
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
        vm.prank(keeper);
        vault.liquidate(40); // wind-down: every idle pack and loose Shape back to ETH
        assertEq(vault.idlePacks().length, 0);
        assertEq(vault.looseShapeCount(), 0);
        toBlackout();
        uint256 kBefore = keeper.balance;
        checkpoint();
        uint256 checkpointPay = keeper.balance - kBefore;
        assertEq(vault.lockedShares(), 0);
        vm.prank(alice);
        vault.claim();
        vm.prank(bob);
        vault.claim();
        // Every wei is accounted for: what is left is exactly the dead shares' NAV, and seed plus
        // deposits equal holders' claims + mint fees + all keeper pay + what is left.
        uint256 seed = 0.01 ether + preexisting;
        uint256 claimed = (alice.balance + bob.balance) - (100 ether - 1.5 ether);
        uint256 keeperPay = keeper.balance - 1 ether;
        // The checkpoint's own gas pay leaves after it prices, so it comes out of the remainder.
        assertApproxEqAbs(address(vault).balance + checkpointPay, vault.lastNav(), 3, "only the dead shares' NAV remains");
        assertEq(claimed + 0.003 ether + keeperPay + address(vault).balance, seed + 1.5 ether);
        assertLt(address(vault).balance, seed, "the dead shares bore their slice of fees and gas");
    }
}
