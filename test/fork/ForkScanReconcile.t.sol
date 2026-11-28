// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {GasQuotes} from "../utils/GasQuotes.sol";

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {JournalRequests} from "./EfficientJournal.t.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {LISTING_ALLOCATED} from "../../src/interfaces/External.sol";

/// @notice The scan-path sibling of ForkReconcile. One real VRF own selection, then a real foreign
///         backlog of >= 41 completed entries built from a funded clean purchaser's acquire requests
///         that FWA's own permissionless processor refunds at their deadline. The vault then takes
///         the scan path: it reads its single own position, applies the selection and jumps its
///         cursor over the whole backlog in one call. sim/reconcile.py::reconcile_scan replays the
///         same steps through sim/vault.py (Vault.scan_rebase) and must match every vault number to
///         the wei. keeperShareBps is zeroed so the scan pays from the routine budget alone: the
///         fee credit is neither swept nor needed, keeping the scan step a clean state transition.
contract ForkScanReconcileTest is SelectionBase {
    string private output;
    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");
    uint256 lastBal;

    receive() external payable {}

    function assertGasContext() external view {
        assertEq(block.basefee, 0.4 gwei);
        assertEq(tx.gasprice, 0.45 gwei);
    }

    function _snap(string memory step) internal {
        ReconcileTrace.snapshot(vault, alice, bob, address(this).balance - lastBal, step, output);
        lastBal = address(this).balance;
    }

    /// @dev The snapshot owns the log window. Verify its persisted real meter without consuming
    ///      recorded logs a second time before the exact cash/log reconciliation.
    function _assertRecordedScan(uint256 pay) private view {
        string[] memory lines = vm.split(vm.readFile(output), "\n");
        uint256 n = lines.length;
        while (n != 0 && bytes(lines[n - 1]).length == 0) --n;
        require(n != 0, "missing scan trace");
        string memory row = lines[n - 1];
        assertEq(vm.parseJsonString(row, ".step"), "scan");
        assertEq(vm.parseJsonUint(row, ".pay"), pay);
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].paid"), pay);
        uint256 allowance = GasQuotes.Q_SYNC + GasQuotes.Q_SCAN + GasQuotes.Q_SELECTED;
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].gasAllowance"), allowance);
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].gasPrice"), 0.4 gwei);
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].txGasPrice"), 0.45 gwei);
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].baseFee"), 0.4 gwei);
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].workUnits"), 0);
        assertFalse(vm.parseJsonBool(row, ".measuredWork[0].essential"));
        uint256 measured = vm.parseJsonUint(row, ".measuredWork[0].measuredGas");
        assertGt(measured, 0);
        uint256 overhead = vault.getParams().gasSchedule.overhead;
        assertEq(vm.parseJsonUint(row, ".measuredWork[0].overhead"), overhead);
        assertEq(pay, ((measured < allowance ? measured : allowance) + overhead) * 0.4 gwei);
    }

    /// @dev Build a real completed foreign backlog: clear the forked block's own stray request, then
    ///      issue and expire enough acquire requests that FWA's processor refunds at their deadline.
    function _foreignBacklog(uint256 count) internal {
        JournalRequests f = JournalRequests(address(FWA));
        // The forked request transaction issued a second request whose word is not replayed here.
        if (FWA.unsettledAcquisitionCount() != 0) {
            vm.roll(block.number + 7_300);
            f.processAcquisitions(16);
        }
        address buyer = makeAddr("pack-vault-test-scan-reconcile-buyer");
        assertEq(buyer.code.length, 0);
        assertEq(buyer.balance, 0);
        vm.deal(buyer, 10 ether);
        uint64 deadline;
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(buyer);
            f.acquire{value: price}(buyer, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        vm.prank(buyer);
        f.withdrawAcquisitionRefund();
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue drained to a clean completed prefix");
    }

    function test_reconcileScanPath() public {
        output = vm.envOr("MEASURED_SCAN_TRACE", string("sim/out/reconcile-measured-scan-trace.jsonl"));
        require(!vm.exists(output), "preserve prior measured scan trace");
        Candidate memory c = primary();
        _select(c); // deploy (3 ETH seed), restock 1, list 1 own, real request + fulfillment -> ALLOCATED

        // Zero keeperShareBps: the scan pays from routine only, never sweeping the fee credit.
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0;
        p.workFee = 0;
        p.maxTip = 0;
        p.keeperShareBps = 0;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner());
        vault.setParams(p, _expected0);

        vm.writeLine(
            output,
            string.concat(
                '{"compensationMode":"bounded-measured-v1","step":"setup","actors":', ReconcileTrace.actors(vault, alice, bob, address(this)), ',"deployBalance":', vm.toString(deployBalance),
                ',"selectPay":', vm.toString(selectPay),
                ',"count":', vm.toString(COUNT), ',"units":6,"backing":', vm.toString(B),
                ',"activationDebt":', vm.toString(activationDebt), ',"initCursor":', vm.toString(vault.acquisitionCursor()),
                ',"selectedListing":', vm.toString(selected), ',"backings":[', vm.toString(B), '],"acqFee":', vm.toString(acqFee),
                ',"acqCutBps":', vm.toString(acqCutBps), ',"acqCrownBps":', vm.toString(acqCrownBps),
                ',"acqActive":', vm.toString(acqActive), ',"balance":', vm.toString(address(vault).balance), "}"
            )
        );
        lastBal = address(this).balance;
        vm.fee(0.4 gwei);
        vm.txGasPrice(0.45 gwei);
        this.assertGasContext();
        _snap("selected");

        _foreignBacklog(45);
        (,,,,,,,,,, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED, "own selection still ALLOCATED through the foreign backlog");
        uint256 backlog = FWA.nextSequenceToProcess() - vault.acquisitionCursor();
        assertGe(backlog, 41, "real foreign backlog triggers the scan path");
        vm.fee(0.4 gwei);
        vm.txGasPrice(0.45 gwei);
        this.assertGasContext();
        _snap("backlog");

        // One scan reads the single own position, applies the selection and clears the whole
        // backlog; it is a paid own-selection sync.
        uint256 before = address(this).balance;
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        uint256 pay = vault.sync(new uint256[](0), 0, 1, _expected1);
        assertEq(address(this).balance - before, pay);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "scan jumped the cursor over the backlog");
        _snap("scan");
        _assertRecordedScan(pay);
    }
}
