// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {IKeeperPolicy} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {LISTING_ACTIVE, LISTING_WITHDRAWN} from "../../src/interfaces/External.sol";

contract ForkVaultLifecycleTest is ForkBase {
    receive() external payable {} // this contract calls paid work directly

    function _depositAndPrice(address who, uint256 amount) internal {
        {
            uint256 gross_ = Charges.grossFor(vault, amount);
            vm.prank(who);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
    }

    function _listN(uint256 n) internal returns (uint256[] memory ids) {
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, n, 3, 0);
        TestVaultOps.list(vault, n, 0);
        vm.stopPrank();
        ids = TestVaultOps.open(vault);
    }

    function test_edgeMatchesLiveFwa() public view {
        (uint256 k, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        // k = 1.05 x 0.99 x 0.999 at the pinned block.
        assertApproxEqAbs(k, 1.0384605e18, 1e12);
        assertEq(backing, B);
    }

    function test_depositListRedeem_roundTrip() public {
        uint256 ck = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: ck + 2 ether}();
        (,, uint96 charge,) = vault.pendingDeposits(alice);
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.totalShares() - vault.DEAD_SHARES();
        uint256 seed = 0.01 ether + preexisting;
        uint256 supply = vault.totalShares();
        // First depositor at seed price: 2 ETH less its deployment charge buys (2 - charge) / seed
        // times the dead shares; the charge itself joins NAV.
        assertEq(shares, (2 ether - charge) * vault.DEAD_SHARES() / seed);

        uint256 balBefore = address(vault).balance;
        uint256 kBefore = keeper.balance;
        uint256[] memory ids = _listN(10);
        assertEq(ids.length, 10);
        // Absolute flows: 3 mints of 0.1 ETH + 0.001 fee, 10 listings at 0.0363, keeper gas pay.
        uint256 pay = keeper.balance - kBefore;
        assertGt(pay, 0, "restock and list are paid");
        assertEq(balBefore - address(vault).balance, 3 * 0.101 ether + 10 * B - 45 * 10_000 + pay);
        for (uint256 i; i < ids.length; ++i) {
            (,,,,, uint256 value,,,,, uint8 status) = FWA.listings(ids[i]);
            assertEq(value, B - i * 10_000, "actual unique quantized backing");
            assertEq(status, LISTING_ACTIVE);
        }

        // Alice exits everything. First checkpoint fills from free ETH, the rest waits.
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        toBlackout();
        checkpoint();
        assertGt(vault.lockedShares(), 0, "partial fill leaves shares locked");

        // The shortfall unlocks unlisting and liquidation, then the next checkpoint fills the rest.
        vm.startPrank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        vault.liquidate(40, 0);
        vm.stopPrank();
        assertEq(TestVaultOps.open(vault).length, 0);
        toOpen();
        toBlackout();
        uint256 payBeforeLast = keeper.balance - kBefore;
        checkpoint();
        assertEq(vault.lockedShares(), 0);

        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        // Every wei: alice's claim + mint fees + all keeper pay + what is left = seed + deposit +
        // the two request charges she paid.
        uint256 got = alice.balance - before;
        uint256 allPay = keeper.balance - 1 ether;
        uint256 inflow = seed + 2 ether + ck + rc;
        assertEq(got + 0.003 ether + allPay + address(vault).balance, inflow);
        // Alice bears her share of the mint fees and of the keeper pay (the order of fills makes
        // the exact split path-dependent, so bound it on both sides).
        assertLe(got, (inflow - 0.003 ether) * shares / supply);
        assertGe(got, (inflow - 0.003 ether - allPay) * (shares) / supply - charge);
        payBeforeLast;
        // Ten packs use three mints, two list batches, one unlist and one liquidation.
        // Only two checkpoints have requester funding; the final fill has a zero charge pool.
        uint256 quotedGas = VaultLib.Q_RESTOCK + 10 * VaultLib.Q_PACK + 3 * VaultLib.Q_MINT
            + 2 * VaultLib.Q_LIST + 10 * VaultLib.Q_LISTED
            + VaultLib.Q_UNLIST + 10 * VaultLib.Q_UNLISTED
            + VaultLib.Q_LIQUIDATE + 10 * VaultLib.Q_LIQ_PACK + 30 * VaultLib.Q_REDEEM_SHAPE
            + 2 * VaultLib.Q_CHECKPOINT;
        assertEq(allPay, quotedGas * 0.2 gwei + 42 * vault.getParams().workFee, "complete independent operation sum");
        emit log_named_uint("complete holder round-trip keeper pay wei", allPay);
    }

    function test_kickReturnsFullBackingAndPack() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        (,, uint128 posted) = TestVaultOps.position(vault, ids[0]);
        // FWA's oracle owner lowers the ask: 0.030 x 1.10 = 0.033 < the posted backing (D62 floor
        // 0.0333 or more).
        assertGt(posted, 0.033 ether);
        setPackAsk(0.03 ether);
        toBlackout();
        uint256 before = address(vault).balance;
        IFwaAdmin(address(FWA)).kickListing(ids[0]);
        assertEq(address(vault).balance - before, posted, "kick returns full backing");
        (,,,,,,,,,, uint8 status) = FWA.listings(ids[0]);
        assertEq(status, LISTING_WITHDRAWN);
        TestVaultOps.sync(vault, ids, 0);
        assertEq(TestVaultOps.open(vault).length, 1);
        assertEq(TestVaultOps.idle(vault).length, 1);
        // New cap 0.033 is below the floor at which a purchaser takes the bid (P / 0.9): no relist.
        (, uint256 backing, bool ok) = vault.edge(3);
        assertFalse(ok);
        assertEq(backing, 0);
    }

    /// D56: a bounded batch of stale identifiers costs gas but cannot increase completed work or pay.
    function test_paddedSyncPaysOnlyForWorkDone() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        setPackAsk(0.03 ether);
        toBlackout();
        IFwaAdmin(address(FWA)).kickListing(ids[0]); // a real kick: one position to resolve
        uint256[] memory padded = new uint256[](16);
        padded[0] = ids[0];
        for (uint256 i = 1; i < padded.length; ++i) {
            padded[i] = 1e9 + i; // ids the vault never held
        }
        uint256 snapshot = vm.snapshotState();
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS));
        uint256 before = keeper.balance;
        uint256 g = gasleft();
        vm.prank(keeper);
        uint256 pay = vault.sync(padded, 0, 0);
        uint256 used = g - gasleft();
        assertEq(keeper.balance - before, pay);
        assertEq(pay, (VaultLib.Q_SYNC + VaultLib.Q_SYNCED) * 0.2 gwei + vault.getParams().workFee, "quote for one resolved position");
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory single = new uint256[](1); single[0] = ids[0];
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS));
        g = gasleft();
        vm.prank(keeper);
        uint256 singlePay = vault.sync(single, 0, 0);
        uint256 singleUsed = g - gasleft();
        assertEq(pay, singlePay, "stale padding earns no extra payment");
        assertGt(used, singleUsed, "bounded stale reads actually cost more gas");
        assertEq(TestVaultOps.idle(vault).length, 1);
    }

    function test_edgeGateStopsListingWhenCrownShareRaised() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        vm.prank(keeper);
        vm.expectRevert(PackVault.UnlistNotAllowed.selector);
        TestVaultOps.unlist(vault, ids, 0);

        // FWA's owner puts the crown share back to 5%: k = 0.9875, the edge is gone.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(15, 500);
        (uint256 k,, bool ok) = vault.edge(3);
        assertFalse(ok);
        assertLt(k, 1e18);
        uint256[] memory planned8 = TestVaultOps.proposals(vault, 1, 3);
        vm.startPrank(keeper);
        // No edge: no capital goes into new packs or listings.
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.restock(3, planned8, 0);
        uint256 before = address(vault).balance;
        uint256 kBefore = keeper.balance;
        TestVaultOps.unlist(vault, ids, 0);
        vm.stopPrank();
        assertEq(address(vault).balance - before + (keeper.balance - kBefore), 2 * B - 10_000, "actual unique backings back, less gas pay");
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
        TestVaultOps.unlist(vault, ids, 0);
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
        vm.prank(owner);
        vault.startWindDown();
        uint256 before = address(vault).balance;
        vm.prank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        assertGe(address(vault).balance + (keeper.balance - 1 ether), before + 3 * B, "backing back");
        vm.prank(keeper);
        vault.liquidate(40, 0);
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "redemption completes without the oracle");
    }

    function test_staleQuoteStopsListing() public {
        vm.warp(block.timestamp + 6 days);
        (,, bool ok) = vault.edge(3);
        assertFalse(ok, "quote older than FWA's 7 day max age");
    }

    function test_ownerStopsCannotMoveAssets() public {
        _depositAndPrice(alice, 1 ether);
        _listN(2);
        uint256 bal = address(vault).balance;
        uint256 gBal = owner.balance;
        vm.prank(owner);
        vault.guard(true, true);
        lowerTo(1 ether, 1 gwei, 0);
        vm.prank(owner);
        vault.startWindDown();
        assertEq(address(vault).balance, bal);
        assertEq(owner.balance, gBal);
        vm.prank(keeper);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.setParams(defaultParams());
    }

    /// D76: the owner moves only by the two-step handover; one-step transfer and renouncing are
    /// disabled so the vault always keeps a controllable owner that can pause, stop pay and wind down.
    function test_ownerHandoverOnly() public {
        address next = makeAddr("nextOwner");
        vm.prank(owner);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.transferOwnership(next);
        vm.prank(owner);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.renounceOwnership();
        // Only the owner completes; a request alone changes nothing.
        vm.prank(next);
        vault.requestOwnershipHandover();
        vm.prank(keeper);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.completeOwnershipHandover(next);
        // Cancelled requests and expired ones (after 48 hours) cannot be completed.
        vm.prank(next);
        vault.cancelOwnershipHandover();
        vm.prank(owner);
        vm.expectRevert(Ownable.NoHandoverRequest.selector);
        vault.completeOwnershipHandover(next);
        vm.prank(next);
        vault.requestOwnershipHandover();
        vm.warp(block.timestamp + 48 hours + 1);
        vm.prank(owner);
        vm.expectRevert(Ownable.NoHandoverRequest.selector);
        vault.completeOwnershipHandover(next);

        vm.prank(next);
        vault.requestOwnershipHandover();
        vm.warp(block.timestamp + 48 hours);
        vm.prank(owner);
        vault.completeOwnershipHandover(next);
        assertEq(vault.owner(), next);
        vm.prank(owner);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.guard(true, true);
        vm.prank(next);
        vault.startWindDown();
        assertTrue(vault.windingDown());
    }

    function test_zeroOwnerRejectedAtDeploy() public {
        IKeeperPolicy policy = vault.keeperPolicy();
        VaultLib.Params memory p = defaultParams();
        vm.deal(owner, 1 ether);
        vm.prank(owner);
        vm.expectRevert(Ownable.NewOwnerIsZeroAddress.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, address(0), p, policy);
    }

    function test_paramsBoundsAppliedAtOnce() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 6_000;
        vm.prank(owner);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.setParams(p);
        p.distributionBps = 1_000;
        // Review S1: the reimbursed tip can never exceed the gas ceiling itself.
        p.maxTip = p.gasCeiling + 1;
        vm.prank(owner);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.setParams(p);
        p.maxTip = 0.05 gwei;
        vm.prank(owner);
        vault.setParams(p);
        assertEq(vault.getParams().distributionBps, 1_000);
    }

    function test_cancelDepositBeforePricing() public {
        uint256 gross_ = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross_}();
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.cancelDeposit();
        // Escrow and checkpoint charge both come back: no other flow needs the pool.
        assertEq(alice.balance - before, gross_);
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.processingPool(), 0);
    }

    function test_proRataRedemptionAcrossCheckpoints() public {
        _depositAndPrice(alice, 1 ether);
        _depositAndPrice(bob, 1 ether);
        _listN(20);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares);
        }
        {
            uint256 rc_ = Charges.redeemCharge(vault, bShares / 2);
            vm.prank(bob);
            vault.requestRedeem{value: rc_}(bShares / 2);
        }
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
        uint256 seed = 0.01 ether + preexisting;
        uint256 inflow = seed; // every wei that entered: seed, deposits with charges, redeem charges
        uint256 g = Charges.grossFor(vault, 1 ether);
        inflow += g;
        vm.prank(alice);
        vault.deposit{value: g}();
        toBlackout();
        checkpoint();
        toOpen();
        g = Charges.grossFor(vault, 0.5 ether);
        inflow += g;
        vm.prank(bob);
        vault.deposit{value: g}();
        toBlackout();
        checkpoint();
        toOpen();
        uint256[] memory ids = _listN(8);
        vm.prank(owner);
        vault.startWindDown();
        vm.prank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        uint256 rc = Charges.redeemCharge(vault, aShares);
        inflow += rc;
        vm.prank(alice);
        vault.requestRedeem{value: rc}(aShares);
        rc = Charges.redeemCharge(vault, bShares);
        inflow += rc;
        vm.prank(bob);
        vault.requestRedeem{value: rc}(bShares);
        vm.prank(keeper);
        vault.liquidate(40, 0); // wind-down: every idle pack and loose Shape back to ETH
        assertEq(TestVaultOps.idle(vault).length, 0);
        assertEq(vault.looseShapeCount(), 0);
        toBlackout();
        uint256 pool = vault.processingPool();
        uint256 kBefore = keeper.balance;
        checkpoint();
        uint256 checkpointPay = keeper.balance - kBefore;
        assertLe(checkpointPay, pool, "the checkpoint is paid out of the request charges");
        assertEq(vault.lockedShares(), 0);
        uint256 claimed = alice.balance + bob.balance;
        vm.prank(alice);
        vault.claim();
        vm.prank(bob);
        vault.claim();
        claimed = alice.balance + bob.balance - claimed;
        uint256 keeperPay = keeper.balance - 1 ether;
        // What is left is exactly the dead shares' NAV plus the pool remainder (it joins the
        // vault's ETH after pricing), and every wei that entered is accounted for.
        assertApproxEqAbs(address(vault).balance, vault.lastNav() + (pool - checkpointPay), 3, "only the dead shares' NAV remains");
        assertEq(claimed + 0.003 ether + keeperPay + address(vault).balance, inflow);
    }
}
