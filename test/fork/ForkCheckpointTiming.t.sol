// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Charges} from "../utils/Charges.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @notice Matched-ordering attack against a real FWA allocation and its authenticated VRF replay.
contract ForkCheckpointTimingTest is SelectionBase {
    address bob = makeAddr("pack-vault-test-timing-bob");
    address alice = makeAddr("pack-vault-test-timing-alice");
    address carol = makeAddr("pack-vault-test-timing-carol");

    receive() external payable {}

    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    struct Outcome {
        uint256 bobShares;
        uint256 bobValue;
        uint256 incumbentValue;
        uint256 vaultNav;
        uint256 purchaserEth;
        uint256 purchaserPack;
        uint256 bobPaid;
        uint256 bobCash;
        uint256 deployCharge;
        uint256 requestCharge;
        uint256 checkpointPay;
        uint256 syncPay;
    }

    function _blackout() internal {
        uint256 t = vm.getBlockTimestamp();
        uint256 start = t - t % 12 hours + 11 hours + 45 minutes;
        if (start <= t) start += 12 hours;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
        assertTrue(FWA.isPurchaseBlackout());
        assertEq(FWA.unsettledAcquisitionCount(), 0);
    }

    function _settle(bool keep, address purchaser) internal returns (uint256 pay) {
        vm.prank(purchaser);
        if (keep) IFwaSettle(address(FWA)).keepNFT(selected);
        else IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint256[] memory ids = new uint256[](1);
        ids[0] = selected;
        pay = TestVaultOps.sync(vault, ids, 0);
    }

    function _run(bool settleBefore, bool keep, address purchaser) internal returns (Outcome memory o) {
        uint256 packId = vault.position(selected).packId;
        uint256 purchaserStart = purchaser.balance;
        uint256 keeperStart = address(this).balance;
        if (settleBefore) o.syncPay = _settle(keep, purchaser);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        o.requestCharge = gross - 1 ether;
        vm.prank(bob);
        vault.deposit{value: gross}();
        (,, uint96 charge,) = vault.pendingDeposits(bob);
        o.deployCharge = charge;
        o.bobCash = bob.balance;
        _blackout();
        TestVaultOps.checkpoint(vault, 0);
        o.bobShares = vault.shareBalance(bob);
        if (!settleBefore) o.syncPay = _settle(keep, purchaser);
        // Both branches have the same real FWA outcome; one more checkpoint prices its gain.
        o.vaultNav = vault.accountedNav(0);
        o.bobValue = o.vaultNav * o.bobShares / vault.totalShares();
        o.incumbentValue = o.vaultNav * vault.DEAD_SHARES() / vault.totalShares();
        o.purchaserEth = purchaser.balance - purchaserStart;
        o.purchaserPack = PACKS.ownerOf(packId) == purchaser ? PACKS.valueOf(packId) : 0;
        o.bobPaid = gross;
        o.checkpointPay = address(this).balance - keeperStart;
    }

    function _secondDeposit(bool settleBefore, address purchaser)
        internal returns (uint256 gross, uint256 shares, uint256 aliceValue, uint256 bobValue, uint256 nav)
    {
        if (settleBefore) _settle(true, purchaser);
        gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        if (!settleBefore) _settle(true, purchaser);
        _blackout(); // the next interval prices Alice; her request never locks lastNav
        TestVaultOps.checkpoint(vault, 0);
        shares = vault.shareBalance(alice);
        nav = vault.accountedNav(0);
        aliceValue = nav * shares / vault.totalShares();
        bobValue = nav * vault.shareBalance(bob) / vault.totalShares();
    }

    function test_postCheckpointDepositDoesNotLockPreKeepNav() public {
        Candidate memory c = Candidate(
            0x2eebb87b882804d37898b4074ab7e27e5f41eb59ed0712bf3ed6cddc943283a6,
            26_229_795, 26_229_800, 1_792_451_207, 23, 3647,
            0xE86C40ab0F182Ce4A7F2EC299080bcb741154720
        );
        _select(c);
        VaultLib.Params memory params = vault.getParams();
        params.allocatedBoundBps = 1000;
        vm.prank(vault.owner());
        vault.setParams(params);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vault.sync(new uint256[](0), 0, 0);
        vm.deal(bob, 2 ether);
        vm.deal(alice, 2 ether);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(bob);
        vault.deposit{value: gross}();
        _blackout();
        TestVaultOps.checkpoint(vault, 0);
        assertGt(vault.shareBalance(bob), 0, "Bob is a live incumbent before Alice requests entry");
        assertEq(vault.shareBalance(alice), 0);
        assertLt(block.timestamp, uint256(FWA.settlementWindow()) + c.fulfillTimestamp);

        uint256 snap = vm.snapshotState();
        (uint256 g0, uint256 s0, uint256 a0, uint256 b0, uint256 n0) = _secondDeposit(true, c.purchaser);
        assertTrue(vm.revertToState(snap));
        (uint256 g1, uint256 s1, uint256 a1, uint256 b1, uint256 n1) = _secondDeposit(false, c.purchaser);
        assertEq(g0, g1, "entry payment is independent of keep ordering");
        assertEq(s0, s1, "Alice receives the same shares when the keep settles before pricing");
        assertEq(a0, a1, "new depositor receives no pre-pricing settlement gain");
        assertEq(b0, b1, "live incumbent retains the same claim");
        assertEq(n0, n1, "both orderings end with identical vault NAV");
        emit log_named_uint("post-checkpoint Alice gross deposit (wei)", g1);
        emit log_named_uint("post-checkpoint Alice final claim (wei)", a1);
        emit log_named_uint("post-checkpoint incumbent Bob final claim (wei)", b1);
    }

    function _redeemAroundKeep(bool settleBefore, address purchaser)
        internal returns (uint256 charge, uint256 received, uint256 aliceValue, uint256 nav)
    {
        if (settleBefore) _settle(true, purchaser);
        uint256 shares = vault.shareBalance(carol);
        charge = Charges.redeemCharge(vault, shares);
        vm.prank(carol);
        vault.requestRedeem{value: charge}(shares);
        if (!settleBefore) _settle(true, purchaser);
        _blackout();
        TestVaultOps.checkpoint(vault, 0);
        uint256 cashBefore = carol.balance;
        vm.prank(carol);
        vault.claim();
        received = carol.balance - cashBefore;
        nav = vault.accountedNav(0);
        aliceValue = nav * vault.shareBalance(alice) / vault.totalShares();
    }

    function test_postCheckpointRedemptionDoesNotLockPreKeepNav() public {
        Candidate memory c = Candidate(
            0x2eebb87b882804d37898b4074ab7e27e5f41eb59ed0712bf3ed6cddc943283a6,
            26_229_795, 26_229_800, 1_792_451_207, 23, 3647,
            0xE86C40ab0F182Ce4A7F2EC299080bcb741154720
        );
        _select(c);
        VaultLib.Params memory params = vault.getParams();
        params.allocatedBoundBps = 1000;
        vm.prank(vault.owner());
        vault.setParams(params);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vault.sync(new uint256[](0), 0, 0);
        vm.deal(alice, 2 ether);
        vm.deal(carol, 2 ether);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        vm.prank(carol);
        vault.deposit{value: 1 ether}(); // Alice funded the shared checkpoint charge
        _blackout();
        TestVaultOps.checkpoint(vault, 0);
        assertGt(vault.shareBalance(alice), 0);
        assertGt(vault.shareBalance(carol), 0);
        assertLt(block.timestamp, uint256(FWA.settlementWindow()) + c.fulfillTimestamp);

        uint256 snap = vm.snapshotState();
        (uint256 c0, uint256 r0, uint256 a0, uint256 n0) = _redeemAroundKeep(true, c.purchaser);
        assertTrue(vm.revertToState(snap));
        (uint256 c1, uint256 r1, uint256 a1, uint256 n1) = _redeemAroundKeep(false, c.purchaser);
        assertEq(c0, c1, "the stale lastNav gives the same request charge");
        assertEq(r0, r1, "Carol's actual claimed ETH is priced at the same settled NAV");
        assertEq(a0, a1, "the remaining live holder retains the same value");
        assertEq(n0, n1, "both orderings end with identical vault NAV");
        assertGt(r1, 0, "Carol receives a real ETH exit payment");
        emit log_named_uint("post-checkpoint Carol redeem charge (wei)", c1);
        emit log_named_uint("post-checkpoint Carol received ETH (wei)", r1);
        emit log_named_uint("post-checkpoint remaining Alice claim (wei)", a1);
    }

    function test_colludingDepositorCapturesDeferredKeepGain() public {
        // This single-count historical fulfillment landed 38 minutes before blackout,
        // inside FWA's real one-hour settlement window. Its word selects index 23.
        Candidate memory c = Candidate(
            0x2eebb87b882804d37898b4074ab7e27e5f41eb59ed0712bf3ed6cddc943283a6,
            26_229_795,
            26_229_800,
            1_792_451_207,
            23,
            3647,
            0xE86C40ab0F182Ce4A7F2EC299080bcb741154720
        );
        _select(c);
        assertEq(FWA.settlementWindow(), 1 hours, "allocation remains live through this blackout");
        VaultLib.Params memory params = vault.getParams();
        params.allocatedBoundBps = 1000; // the production deployment's 10% limit
        vm.prank(vault.owner());
        vault.setParams(params);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        // Apply the real selection to the vault's book before testing its allocated NAV.
        vault.sync(new uint256[](0), 0, 0);
        assertEq(vault.position(selected).state, 2);
        vm.deal(bob, 2 ether);
        uint256 snap = vm.snapshotState();
        Outcome memory beforePricing = _run(true, true, c.purchaser);
        assertTrue(vm.revertToState(snap));
        Outcome memory afterPricing = _run(false, true, c.purchaser);

        emit log_named_uint("Bob value, settle before pricing (wei)", beforePricing.bobValue);
        emit log_named_uint("Bob value, settle after pricing (wei)", afterPricing.bobValue);
        emit log_named_uint("Bob incremental claim (wei)", afterPricing.bobValue - beforePricing.bobValue);
        emit log_named_uint("Incumbent loss (wei)", beforePricing.incumbentValue - afterPricing.incumbentValue);
        emit log_named_uint("Bob gross deposit (wei)", afterPricing.bobPaid);
        emit log_named_uint("Bob deployment charge (wei)", afterPricing.deployCharge);
        emit log_named_uint("Bob checkpoint charge (wei)", afterPricing.requestCharge);
        emit log_named_uint("Bob cash after deposit (wei)", afterPricing.bobCash);
        emit log_named_uint("Bob shares before keep (wei)", afterPricing.bobShares);
        emit log_named_uint("Bob shares after keep (wei)", beforePricing.bobShares);
        emit log_named_uint("Keeper receipts, before keep (wei)", beforePricing.checkpointPay);
        emit log_named_uint("Keeper receipts, after keep (wei)", afterPricing.checkpointPay);
        assertEq(beforePricing.bobPaid, afterPricing.bobPaid, "same deposit and charges");
        assertEq(beforePricing.deployCharge, afterPricing.deployCharge);
        assertEq(beforePricing.requestCharge, afterPricing.requestCharge);
        assertEq(beforePricing.purchaserEth, afterPricing.purchaserEth, "same FWA payment to purchaser");
        assertEq(beforePricing.purchaserPack, afterPricing.purchaserPack, "same acquired pack value");
        assertGt(afterPricing.bobValue, beforePricing.bobValue, "delayed settlement shifts gain to new shares");
        assertLt(afterPricing.bobValue, afterPricing.bobPaid, "no positive deposit-only round trip at this scale");

        assertTrue(vm.revertToState(snap));
        Outcome memory bidBefore = _run(true, false, c.purchaser);
        assertTrue(vm.revertToState(snap));
        Outcome memory bidAfter = _run(false, false, c.purchaser);
        emit log_named_uint("Bob value, bid before pricing (wei)", bidBefore.bobValue);
        emit log_named_uint("Bob value, bid after pricing (wei)", bidAfter.bobValue);
        emit log_named_uint("Keeper receipts, bid before (wei)", bidBefore.checkpointPay);
        emit log_named_uint("Keeper receipts, bid after (wei)", bidAfter.checkpointPay);
        emit log_named_uint("Bid sync pay, before (wei)", bidBefore.syncPay);
        emit log_named_uint("Bid sync pay, after (wei)", bidAfter.syncPay);
        assertEq(bidBefore.purchaserEth, bidAfter.purchaserEth, "same real FWA bid proceeds");
        assertEq(bidBefore.purchaserPack, 0, "bid leaves pack with vault");
        assertEq(bidAfter.purchaserPack, 0);
    }
}
