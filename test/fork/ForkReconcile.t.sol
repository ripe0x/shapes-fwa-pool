// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {PackVault} from "../../src/PackVault.sol";
import {Charges} from "../utils/Charges.sol";
import {LISTING_ACTIVE} from "../../src/interfaces/External.sol";

/// @notice One full cycle on real contracts with a real VRF selection, written step by step to
///         sim/out/reconcile-trace.jsonl. sim/reconcile.py replays the same steps through the
///         Python vault model (sim/vault.py, the one the forward simulation uses) and must match
///         every vault number to the wei. Inputs the model takes as given: FWA's fee formula
///         inputs, observed fixed-quote keeper payouts, and each listing's live backing.
contract ForkReconcileTest is SelectionBase {
    string constant OUT = "sim/out/reconcile-trace.jsonl";
    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");
    uint256 lastBal; // this contract's balance before the step: keeper pay is the delta

    receive() external payable {}

    function assertGasContext() external {
        assertEq(block.basefee, 0.4 gwei);
        assertEq(tx.gasprice, 0.45 gwei);
    }

    function _snap(string memory step) internal {
        ReconcileTrace.snapshot(vault, alice, bob, address(this).balance - lastBal, step, OUT);
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
        if (vault.acquisitionCursor() < FWA.nextSequenceToProcess()) vault.sync(new uint256[](0), 0, 0);
    }

    function test_reconcileFullCycle() public {
        if (vm.exists(OUT)) vm.removeFile(OUT);
        Candidate memory c = primary();
        _select(c); // deploy (3 ETH seed), restock 30, list 30, real request + fulfillment
        vm.writeLine(
            OUT,
            string.concat(
                '{"step":"setup","deployBalance":', vm.toString(deployBalance),
                ',"selectPay":', vm.toString(selectPay),
                ',"count":', vm.toString(COUNT), ',"units":6,"backing":', vm.toString(B),
                ',"activationDebt":', vm.toString(activationDebt), ',"initCursor":', vm.toString(vault.acquisitionCursor()), ',"selectedListing":', vm.toString(selected), ',"backings":[', vm.toString(B), '],"acqFee":', vm.toString(acqFee), ',"acqCutBps":', vm.toString(acqCutBps),
                ',"acqCrownBps":', vm.toString(acqCrownBps), ',"acqActive":', vm.toString(acqActive),
                ',"balance":', vm.toString(address(vault).balance), "}"
            )
        );
        lastBal = address(this).balance;
        // Vault operations at a set fee environment from here on.
        vm.fee(0.4 gwei);
        vm.txGasPrice(0.45 gwei);
        this.assertGasContext();
        _snap("selected");

        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _snap("bid");

        // Holders fund their deposits and the request charges (D56) on top.
        uint256 ckA = vault.requestCharge();
        vm.deal(alice, 1 ether + ckA);
        vm.prank(alice);
        vault.deposit{value: 1 ether + ckA}();
        uint256 ckB = vault.requestCharge();
        vm.deal(bob, 0.5 ether + ckB);
        vm.prank(bob);
        vault.deposit{value: 0.5 ether + ckB}();
        (,, uint96 chA,) = vault.pendingDeposits(alice);
        (,, uint96 chB,) = vault.pendingDeposits(bob);
        vm.writeLine(
            OUT,
            string.concat(
                '{"step":"charges","ckA":', vm.toString(ckA), ',"chargeA":', vm.toString(uint256(chA)),
                ',"ckB":', vm.toString(ckB), ',"chargeB":', vm.toString(uint256(chB)), "}"
            )
        );
        _snap("deposits");

        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        uint256 g = gasleft();
        TestVaultOps.sync(vault, one, 0);
        uint256 gSync = g - gasleft();
        _snap("sync");

        g = gasleft();
        TestVaultOps.harvest(vault, TestVaultOps.open(vault), 0);
        uint256 gHarvest = g - gasleft();
        _snap("harvest");
        uint256[] memory planned9 = TestVaultOps.proposals(vault, 1, UNITS);

        // FWA's queue is busy (the forked block's other request): the vault refuses to list into it.
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(planned9, 0);
        _toBlackout(); // FWA's own processor drains the queue
        _snap("catchup");
        g = gasleft();
        TestVaultOps.list(vault, 1, 0);
        uint256 gList = g - gasleft();
        uint256[] memory open = TestVaultOps.open(vault);
        (,, uint128 relistBacking) = TestVaultOps.position(vault, open[open.length - 1]);
        vm.writeLine(OUT, string.concat('{"step":"relistBacking","backing":', vm.toString(relistBacking), "}"));
        _snap("list");

        g = gasleft();
        TestVaultOps.checkpoint(vault, 0);
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
        uint256 ckR = vault.requestCharge();
        uint256 rc = Charges.redeemCharge(vault, aShares);
        vm.deal(alice, rc);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(aShares);
        vm.writeLine(OUT, string.concat('{"step":"redeemCharge","ck":', vm.toString(ckR), ',"total":', vm.toString(rc), "}"));
        _snap("redeem");

        vm.warp(block.timestamp + 12 hours);
        vm.roll(block.number + 3600);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        TestVaultOps.checkpoint(vault, 0);
        _snap("checkpoint2");

        vm.prank(alice);
        vault.claim();
        _snap("claim");
        vm.writeLine(OUT, string.concat('{"step":"aliceReceived","amount":', vm.toString(alice.balance), "}"));

        // The relist went in with the queue drained, so FWA activated it at once.
        (,,,,,,,,,, uint8 st) = FWA.listings(open[open.length - 1]);
        assertEq(st, LISTING_ACTIVE, "relist active");
        // Every position is live; nothing strands.
        for (uint256 i; i < open.length; ++i) {
            (,,,,,,,,,, uint8 status) = FWA.listings(open[i]);
            assertEq(status, LISTING_ACTIVE);
        }
    }
}
