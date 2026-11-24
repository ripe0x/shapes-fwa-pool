// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {RefundClaims} from "../utils/RefundClaims.sol";

import {GasQuotes} from "../utils/GasQuotes.sol";

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {LISTING_ACTIVE, LISTING_WITHDRAWN} from "../../src/interfaces/External.sol";

contract ForkVaultLifecycleTest is ForkBase {
    receive() external payable {} // this contract calls paid work directly

    function _depositAndPrice(address who, uint256 amount) internal {
        {
            uint256 gross_ = Charges.grossFor(vault, amount);
            bytes32 _expected0 = TestVaultOps.configurationHash(vault);
            vm.prank(who);
            vault.deposit{value: gross_}(_expected0);
        }
        toBlackout();
        checkpoint();
        toOpen();
    }

    /// @dev Build-and-list `n` six-unit packs (build mints and lists at once; no idle packs left).
    function _listN(uint256 n) internal returns (uint256[] memory ids) {
        vm.prank(keeper);
        TestVaultOps.restock(vault, n, UNITS, 0);
        ids = TestVaultOps.open(vault);
    }

    /// @dev Sum of the backings actually posted for `ids` (unique quantized proposals near B()).
    function _backingSum(uint256[] memory ids) internal view returns (uint256 sum) {
        for (uint256 i; i < ids.length; ++i) sum += vault.position(ids[i]).backing;
    }

    function test_edgeMatchesLiveFwa() public view {
        (uint256 k, uint256 backing, bool ok) = vault.edge(UNITS);
        assertTrue(ok);
        // k = 1.05 x 0.99 x 0.999 at the pinned block (independent of pack units).
        assertApproxEqAbs(k, 1.0384605e18, 1e12);
        assertEq(backing, B());
    }

    /// A built pack mints exactly the recipe's two Shapes (0.05 + 0.01) and costs P + 0.002 ETH
    /// mint fee + its backing; relisting a returned pack mints no Shapes (covers the ForkSelection
    /// build/relist properties that FWA's busy queue blocks at the selection block).
    function test_builtPackCostsAndMints() public {
        _depositAndPrice(alice, 1 ether);
        assertEq(SHAPES.mintFee(), 0.001 ether, "live mint fee");
        uint256 supplyBefore = SHAPES.totalSupply();
        uint256 balBefore = address(vault).balance;
        uint256 kBefore = keeper.balance;
        uint256[] memory ids = _listN(1);
        uint256 pay = keeper.balance - kBefore;
        uint256 backing = vault.position(ids[0]).backing;
        assertEq(SHAPES.totalSupply() - supplyBefore, 2, "two fresh Shapes minted per pack");
        assertEq(balBefore - address(vault).balance, P + FEE_PER_PACK + backing + pay,
            "built pack costs P + 0.002 mint fee + backing (plus keeper pay)");

        // Return the pack to idle through a kick, then relist it: no new mint.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(0.03 ether); // cap below the posted backing: kickable
        toBlackout();
        IFwaAdmin(address(FWA)).kickListing(ids[0]);
        TestVaultOps.sync(vault, ids, 0);
        assertEq(TestVaultOps.idle(vault).length, 1, "returned pack is idle");
        // Re-exempt so edge lists again, leave the blackout, then relist the idle pack with no mint.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        toOpen();
        uint256 supplyAtRelist = SHAPES.totalSupply();
        vm.prank(keeper);
        uint256 relistPay = TestVaultOps.list(vault, 1, 0);
        assertGt(relistPay, 0, "relisting is paid");
        assertEq(SHAPES.totalSupply(), supplyAtRelist, "relist mints no Shapes");
        assertEq(TestVaultOps.idle(vault).length, 0, "idle pack relisted");
        assertEq(TestVaultOps.open(vault).length, 1);
    }

    function test_depositListRedeem_roundTrip() public {
        uint256 ck = vault.requestCharge();
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: ck + 2 ether}(_expected1);
        uint256 charge = vault.constructionCharge(2 ether);
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
        // Absolute flow: 10 built packs (each P + 0.002 mint fee into createPack) + their backings
        // sent to FWA + keeper gas pay. Backings are unique quantized proposals near B().
        uint256 pay = keeper.balance - kBefore;
        uint256 backingSum = _backingSum(ids);
        assertGt(pay, 0, "build is paid");
        assertEq(balBefore - address(vault).balance, 10 * (P + FEE_PER_PACK) + backingSum + pay);
        for (uint256 i; i < ids.length; ++i) {
            (,,,,, uint256 value,,,,, uint8 status) = FWA.listings(ids[i]);
            assertEq(value, vault.position(ids[i]).backing, "FWA records the posted backing");
            assertGe(value, B() - 10 * 10_000, "backing within the quantization window of B()");
            assertLe(value, B() + 10 * 10_000);
            assertEq(status, LISTING_ACTIVE);
        }

        // Alice exits everything. First checkpoint fills from free ETH, the rest waits.
        uint256 rc = Charges.redeemCharge(vault, shares);
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares, _expected2);
        toBlackout();
        checkpoint();
        assertGt(vault.lockedShares(), 0, "partial fill leaves shares locked");

        // The shortfall unlocks unlisting and liquidation, then the next checkpoint fills the rest.
        vm.startPrank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vault.liquidate(40, 0, _expected3);
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
        // Mint fees (10 packs x 0.002) leave the system permanently to the Shapes protocol; the pack
        // values and backings round-trip back through redemption and withdrawal.
        uint256 mintFees = 10 * FEE_PER_PACK;
        assertEq(got + mintFees + allPay + address(vault).balance, inflow);
        // Alice bears her share of the mint fees and of the keeper pay (the order of fills makes
        // the exact split path-dependent, so bound it on both sides).
        assertLe(got, (inflow - mintFees) * shares / supply);
        assertGe(got, (inflow - mintFees - allPay) * (shares) / supply - charge);
        payBeforeLast;
        // Ten packs built in three batches (4 + 4 + 2), one unlist of ten, one liquidation of ten packs
        // (20 Shapes burned). Only two checkpoints have requester funding; the final fill's pool is 0.
        uint256 quotedGas = 3 * GasQuotes.Q_BUILD + 10 * (GasQuotes.buildGas(2) + GasQuotes.Q_LISTED)
            + GasQuotes.Q_UNLIST + 10 * GasQuotes.Q_UNLISTED
            + GasQuotes.Q_LIQUIDATE + 10 * GasQuotes.Q_LIQ_PACK + 20 * GasQuotes.Q_REDEEM_SHAPE
            + 2 * GasQuotes.Q_CHECKPOINT;
        // Work units: 20 (2 per built pack) + 10 unlisted + 10 liquidated + 2 checkpoints = 42.
        assertEq(allPay, quotedGas * 0.2 gwei + 42 * vault.getParams().workFee, "complete independent operation sum");
        emit log_named_uint("complete holder round-trip keeper pay wei", allPay);
    }

    /// @dev Un-exempt ShapePacks and set a fresh high oracle ask so the 6-unit backing lists; the
    ///      oracle cap only bites these tests (production exempts ShapePacks, D62).
    function _useOracle(uint256 ask) internal {
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(ask);
    }

    function test_kickReturnsFullBackingAndPack() public {
        _useOracle(0.1 ether); // cap 0.11 > the 6-unit backing: lists
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        (,, uint128 posted) = TestVaultOps.position(vault, ids[0]);
        assertGt(posted, 0.033 ether);
        // The oracle owner lowers the ask below the posted backing: 0.030 x 1.10 = 0.033.
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
        // New cap 0.033 is below the keep-never-loses floor ceil(P / 0.95) = 0.0632: no relist.
        (, uint256 backing, bool ok) = vault.edge(UNITS);
        assertFalse(ok);
        assertEq(backing, 0);
    }

    /// D56: a bounded batch of stale identifiers costs gas but cannot increase completed work or pay.
    function test_paddedSyncPaysOnlyForWorkDone() public {
        _useOracle(0.1 ether);
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
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        uint256 pay = vault.sync(padded, 0, 0, _expected4);
        uint256 used = g - gasleft();
        assertEq(keeper.balance - before, pay);
        assertEq(pay, (GasQuotes.Q_SYNC + GasQuotes.Q_SYNCED) * 0.2 gwei + vault.getParams().workFee, "quote for one resolved position");
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory single = new uint256[](1); single[0] = ids[0];
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS));
        g = gasleft();
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        uint256 singlePay = vault.sync(single, 0, 0, _expected5);
        uint256 singleUsed = g - gasleft();
        assertEq(pay, singlePay, "stale padding earns no extra payment");
        assertGt(used, singleUsed, "bounded stale reads actually cost more gas");
        assertEq(TestVaultOps.idle(vault).length, 1);
    }

    function test_edgeGateStopsListingWhenCrownShareRaised() public {
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        uint256 backingSum = _backingSum(ids);
        vm.prank(keeper);
        bytes32 expectedRegression1 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.UnlistNotAllowed.selector);
        vault.unlist(ids, 0, expectedRegression1);

        // FWA's owner puts the crown share back to 5%: k = 0.9875, the edge is gone.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(15, 500);
        (uint256 k,, bool ok) = vault.edge(UNITS);
        assertFalse(ok);
        assertLt(k, 1e18);
        uint256[] memory planned8 = TestVaultOps.proposals(vault, 1, UNITS); // all zeros: no edge
        vm.startPrank(keeper);
        // No edge: no capital goes into new packs or listings.
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, planned8, 0, _expected6);
        uint256 before = address(vault).balance;
        uint256 kBefore = keeper.balance;
        TestVaultOps.unlist(vault, ids, 0);
        vm.stopPrank();
        assertEq(address(vault).balance - before + (keeper.balance - kBefore), backingSum,
            "the posted backings return, less gas pay");
    }

    /// Repair: a gas spike or a stale quote stops new listings but must not let anyone unwind
    /// earning positions (old code allowed unlisting whenever the full gate failed).
    function test_staleQuoteDoesNotUnlockUnlisting() public {
        _useOracle(0.1 ether);
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(2);
        vm.warp(block.timestamp + 8 days); // quote past FWA's 7 day max age: listing gate fails
        (,, bool ok) = vault.edge(UNITS);
        assertFalse(ok);
        vm.prank(keeper);
        bytes32 expectedRegression2 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.UnlistNotAllowed.selector);
        vault.unlist(ids, 0, expectedRegression2);
    }

    /// Repair: unlisting read the oracle through edge(), so an oracle FWA's owner repoints to a
    /// contract that reverts blocked wind-down and redemptions. Now a failed read means no cap.
    function test_windDownSurvivesBrokenOracle() public {
        _useOracle(0.1 ether); // real oracle active, cap above the 6-unit backing
        _depositAndPrice(alice, 1 ether);
        uint256[] memory ids = _listN(3);
        uint256 backingSum = _backingSum(ids);
        // FWA's owner repoints the floor oracle (config key 64) to a contract with no such
        // function: ShapePacks rejects unknown calls.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(PACKS));
        (, uint256 backing, bool ok) = vault.edge(UNITS);
        assertFalse(ok, "no cap: nothing new lists");
        assertEq(backing, 0);
        vm.prank(owner);
        vault.startWindDown();
        uint256 before = address(vault).balance;
        vm.prank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        assertGe(address(vault).balance + (keeper.balance - 1 ether), before + backingSum, "backing back");
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vault.liquidate(40, 0, _expected7);
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            bytes32 _expected8 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares, _expected8);
        }
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "redemption completes without the oracle");
    }

    function test_staleQuoteStopsListing() public {
        _useOracle(0.1 ether);
        (,, bool okFresh) = vault.edge(UNITS);
        assertTrue(okFresh, "fresh high ask lists");
        vm.warp(block.timestamp + 8 days);
        (,, bool ok) = vault.edge(UNITS);
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
        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.setParams(defaultParams(), _expected9);
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

        VaultLib.Params memory p = defaultParams();
        vm.deal(owner, 1 ether);
        vm.prank(owner);
        vm.expectRevert(Ownable.NewOwnerIsZeroAddress.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, address(0), p, keccak256(abi.encode(p, uint256(0.001 ether), false, false)));
    }

    function test_paramsBoundsAppliedAtOnce() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 6_000;
        bytes32 _expected10 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(p, _expected10);
        p.distributionBps = 1_000;
        // Review S1: the reimbursed tip can never exceed the gas ceiling itself.
        p.maxTip = p.gasCeiling + 1;
        bytes32 _expected11 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(p, _expected11);
        p.maxTip = 0.05 gwei;
        bytes32 _expected12 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected12);
        assertEq(vault.getParams().distributionBps, 1_000);
    }

    function test_cancelDepositBeforePricing() public {
        uint256 gross_ = Charges.grossFor(vault, 1 ether);
        bytes32 _expected13 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: gross_}(_expected13);
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.cancelDeposit();
        RefundClaims.claim(vault, alice);
        // Escrow and checkpoint charge both come back: no other flow needs the pool.
        assertEq(alice.balance - before, gross_);
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.processingPool(), 0);
    }

    function test_proRataRedemptionAcrossCheckpoints() public {
        // Larger deposits than the old 3-unit recipe: 20 six-unit packs cost ~2.5 ETH to list.
        _depositAndPrice(alice, 1.5 ether);
        _depositAndPrice(bob, 1.5 ether);
        _listN(20);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            bytes32 _expected14 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares, _expected14);
        }
        {
            uint256 rc_ = Charges.redeemCharge(vault, bShares / 2);
            bytes32 _expected15 = TestVaultOps.configurationHash(vault);
            vm.prank(bob);
            vault.requestRedeem{value: rc_}(bShares / 2, _expected15);
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
        bytes32 _expected16 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: g}(_expected16);
        toBlackout();
        checkpoint();
        toOpen();
        g = Charges.grossFor(vault, 0.5 ether);
        inflow += g;
        bytes32 _expected17 = TestVaultOps.configurationHash(vault);
        vm.prank(bob);
        vault.deposit{value: g}(_expected17);
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
        bytes32 _expected18 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(aShares, _expected18);
        rc = Charges.redeemCharge(vault, bShares);
        inflow += rc;
        bytes32 _expected19 = TestVaultOps.configurationHash(vault);
        vm.prank(bob);
        vault.requestRedeem{value: rc}(bShares, _expected19);
        bytes32 _expected20 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vault.liquidate(40, 0, _expected20); // wind-down: every idle pack back to ETH
        assertEq(TestVaultOps.idle(vault).length, 0);
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
        // vault's ETH after pricing), and every wei that entered is accounted for. The only
        // permanent outflow is the 8 built packs' mint fees (8 x 0.002 ETH).
        assertApproxEqAbs(address(vault).balance, vault.lastNav() + (pool - checkpointPay), 3, "only the dead shares' NAV remains");
        assertEq(claimed + 8 * FEE_PER_PACK + keeperPay + address(vault).balance, inflow);
    }
}
