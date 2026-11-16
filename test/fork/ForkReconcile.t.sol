// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {PackVault} from "../../src/PackVault.sol";
import {LISTING_ACTIVE, LISTING_STAGED} from "../../src/interfaces/External.sol";

/// @notice One full cycle on real contracts with a real VRF selection, written step by step to
///         sim/out/reconcile-trace.jsonl. sim/reconcile.py replays the same steps through the
///         Python vault model (sim/vault.py, the one the forward simulation uses) and must match
///         every vault number to the wei. Inputs the model takes as given: FWA's fee formula
///         inputs, keeper gas pay (it depends on gasleft), and the live backing on each listing.
contract ForkReconcileTest is SelectionBase {
    string constant OUT = "sim/out/reconcile-trace.jsonl";
    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");
    uint256 lastBal; // this contract's balance before the step: keeper pay is the delta

    receive() external payable {}

    function _snap(string memory step) internal {
        uint256 pay = address(this).balance - lastBal;
        uint256[] memory open = vault.openListings();
        uint256 pendingSum;
        for (uint256 i; i < open.length; ++i) {
            pendingSum += FWA.pendingFees(open[i]);
        }
        (uint128 aLocked,,,) = vault.redemptions(alice);
        string memory line = string.concat(
            '{"step":"', step, '","pay":', vm.toString(pay),
            ',"balance":', vm.toString(address(vault).balance),
            ',"totalShares":', vm.toString(vault.totalShares()),
            ',"lastNav":', vm.toString(vault.lastNav()),
            ',"pendingDepositTotal":', vm.toString(vault.pendingDepositTotal()),
            ',"redemptionReserve":', vm.toString(vault.redemptionReserve()),
            ',"lockedShares":', vm.toString(vault.lockedShares())
        );
        line = string.concat(
            line,
            ',"open":', vm.toString(open.length),
            ',"idle":', vm.toString(vault.idlePacks().length),
            ',"loose":', vm.toString(vault.looseShapeCount()),
            ',"aliceShares":', vm.toString(vault.shareBalance(alice)),
            ',"bobShares":', vm.toString(vault.shareBalance(bob)),
            ',"aliceLocked":', vm.toString(uint256(aLocked)),
            ',"aliceClaimable":', vm.toString(vault.claimableEth(alice)),
            ',"pendingFeesSum":', vm.toString(pendingSum),
            ',"feeCredit":', vm.toString(FWA.feeCredit(address(vault))), "}"
        );
        vm.writeLine(OUT, line);
        lastBal = address(this).balance;
    }

    function _toBlackout() internal {
        // The forked request transaction also issued a request whose word is not replayed here;
        // FWA expires it after its deadline (up to 7,200 blocks), so step past that first.
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        uint256 t = block.timestamp;
        uint256 start = t - t % 12 hours + 11 hours + 45 minutes;
        if (t >= start) start += 12 hours;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
        // Other real requests from the forked block are never fulfilled here; FWA's own
        // permissionless processor expires them after their word deadline, draining the queue.
        if (FWA.unsettledAcquisitionCount() != 0) IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue drained");
    }

    function test_reconcileFullCycle() public {
        if (vm.exists(OUT)) vm.removeFile(OUT);
        Candidate memory c = late();
        _select(c); // deploy (3 ETH seed), restock 30, list 30, real request + fulfillment
        vm.writeLine(
            OUT,
            string.concat(
                '{"step":"setup","deployBalance":', vm.toString(deployBalance),
                ',"selectPay":', vm.toString(selectPay),
                ',"count":30,"units":3,"backing":', vm.toString(B),
                ',"acqFee":', vm.toString(acqFee), ',"acqCutBps":', vm.toString(acqCutBps),
                ',"acqCrownBps":', vm.toString(acqCrownBps), ',"acqActive":', vm.toString(acqActive),
                ',"balance":', vm.toString(address(vault).balance), "}"
            )
        );
        lastBal = address(this).balance;
        // Vault operations at a set fee environment from here on.
        vm.fee(0.4 gwei);
        vm.txGasPrice(0.45 gwei);
        _snap("selected");

        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _snap("bid");

        vm.deal(alice, 1 ether);
        vm.deal(bob, 0.5 ether);
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        vm.prank(bob);
        vault.deposit{value: 0.5 ether}();
        _snap("deposits");

        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        uint256 g = gasleft();
        vault.sync(one);
        uint256 gSync = g - gasleft();
        _snap("sync");

        g = gasleft();
        vault.harvest(vault.openListings());
        uint256 gHarvest = g - gasleft();
        _snap("harvest");

        g = gasleft();
        vault.list(1);
        uint256 gList = g - gasleft();
        uint256[] memory open = vault.openListings();
        (,, uint128 relistBacking) = vault.positions(open[open.length - 1]);
        vm.writeLine(OUT, string.concat('{"step":"relistBacking","backing":', vm.toString(relistBacking), "}"));
        _snap("list");

        _toBlackout();
        g = gasleft();
        vault.checkpoint();
        uint256 gCheckpoint = g - gasleft();
        _snap("checkpoint1");
        vm.writeLine(
            OUT,
            string.concat(
                '{"step":"gas","sync1":', vm.toString(gSync), ',"harvest29":', vm.toString(gHarvest),
                ',"list1":', vm.toString(gList), ',"checkpoint30":', vm.toString(gCheckpoint), "}"
            )
        );

        uint256 aShares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(aShares);
        _snap("redeem");

        vm.warp(block.timestamp + 12 hours);
        vm.roll(block.number + 3600);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        vault.checkpoint();
        _snap("checkpoint2");

        vm.prank(alice);
        vault.claim();
        _snap("claim");
        vm.writeLine(OUT, string.concat('{"step":"aliceReceived","amount":', vm.toString(alice.balance), "}"));

        // The relist went in while FWA's queue was busy, so FWA staged it: no fees, no rewards.
        // With the queue drained, the vault activates it through FWA's own activation, paid.
        uint256 relist = open[open.length - 1];
        (,,,,,,,,,, uint8 st) = FWA.listings(relist);
        assertEq(st, LISTING_STAGED, "staged while the queue was busy");
        uint256[] memory one2 = new uint256[](1);
        one2[0] = relist;
        vault.activate(one2, 50);
        (,,,,,,,,,, st) = FWA.listings(relist);
        assertEq(st, LISTING_ACTIVE, "activated");
        _snap("activate");
        vm.expectRevert(PackVault.Nothing.selector);
        vault.activate(one2, 50); // nothing left to activate: no pay for a repeat
        // Every position is live; nothing strands.
        for (uint256 i; i < open.length; ++i) {
            (,,,,,,,,,, uint8 status) = FWA.listings(open[i]);
            assertEq(status, LISTING_ACTIVE);
        }
    }
}
