// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {MainRenewalBase, IFwaSettle} from "./ForkMainRenewal.t.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Vm} from "forge-std/Vm.sol";

/// @notice Real Shapes/FWA work with an independently computable one-gas verified cap.
///         The cap is deliberately below real work, so unused transaction gas cannot affect pay.
contract ForkMeasuredKeeperTest is ForkBase {
    receive() external payable {}

    function params() private pure returns (VaultLib.Params memory p) {
        p = defaultParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        p.reserve = 0.005 ether;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.1 gwei;
        p.payMarkupBps = 1_000;
        p.gasSchedule.build = 1;
        p.gasSchedule.buildPack = 0;
        p.gasSchedule.buildShape = 0;
        p.gasSchedule.listed = 0;
        p.gasSchedule.unlist = 1;
        p.gasSchedule.unlisted = 0;
    }

    function manager(VaultLib.Params memory p) private returns (PackManager m) {
        PackManagerFactory factory = new PackManagerFactory(FWA, SHAPES, PACKS);
        m = factory.create{value: 1 ether}(owner, p, factory.configHashFor(p));
    }

    function proposals() private pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = 0.21 ether;
    }

    function measurement(address target, uint256 allowance, uint256 price, uint256 units, bool essential)
        private view returns (uint256 measured)
    {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bytes32 topic = keccak256("KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)");
        for (uint256 i = logs.length; i != 0; --i) {
            Vm.Log memory entry = logs[i - 1];
            if (entry.emitter != target || entry.topics.length == 0 || entry.topics[0] != topic) continue;
            (uint256 gasUsed, uint256 cap, uint256 chargedPrice, uint256 work, bool exitWork) =
                abi.decode(entry.data, (uint256, uint256, uint256, uint256, bool));
            assertEq(cap, allowance);
            assertEq(chargedPrice, price);
            assertEq(work, units);
            assertEq(exitWork, essential);
            return gasUsed;
        }
        revert("actual measurement missing");
    }

    function meterCount(address target) private view returns (uint256 count) {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bytes32 topic = keccak256("KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)");
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter == target && logs[i].topics.length != 0 && logs[i].topics[0] == topic) ++count;
        }
    }

    function buildAt(PackManager m, uint256 price, uint256 minPay) external returns (uint256) {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.15 gwei, "inside executed payment path basefee");
        assertEq(tx.gasprice, price, "inside executed payment path gas price");
        return m.build(3, proposals(), minPay, m.configurationHash());
    }

    function test_verifiedCapPlusNamedOverheadAtActualCheaperBid() public {
        VaultLib.Params memory p = params();
        PackManager m = manager(p);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.16 gwei);
        uint256 before = address(m).balance;
        uint256 supply = SHAPES.totalSupply();
        uint256 paid = this.buildAt(m, 0.16 gwei, 0);
        // 100001 gas x .16 gwei x 1.1 + two actual work fees; not the .20 gwei envelope.
        assertEq(paid, 57_600_176_000_000, "absolute bounded actual-price payment");
        assertGt(measurement(address(m), 1, 0.16 gwei, 2, false), 1);
        assertEq(before - address(m).balance, 0.24 ether + 0.003 ether + paid);
        assertEq(SHAPES.totalSupply() - supply, 3, "real three paid primary mints");
        assertGt(m.quote(1, 2, false), paid, "quote remains a ceiling independent of caller bid");
    }

    function test_priceAndEssentialMarkupLimitsApplyToMeasuredPayment() public {
        PackManager m = manager(params());
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.7 gwei);
        // The account reimburses only .15 base + .05 tip, even when the caller bids more.
        uint256 paid = this.buildAt(m, 0.7 gwei, 0);
        assertEq(paid, 62_000_220_000_000);
        assertGt(measurement(address(m), 1, 0.2 gwei, 2, false), 1);
        uint256 id = m.openListingAt(0);
        uint256[] memory ids = new uint256[](1);
        ids[0] = id;
        vm.prank(owner); m.setExiting(true);
        if (FWA.topListingId() == id) vm.warp(vm.getBlockTimestamp() + 12 hours);
        vm.fee(0.15 gwei); vm.txGasPrice(0.7 gwei);
        paid = this.unlistAt(m, ids);
        // Essential ceiling .1 gwei; no routine 10% markup; one actual unlisting fee.
        assertEq(paid, 30_000_100_000_000);
        assertGt(measurement(address(m), 1, 0.1 gwei, 1, true), 1);
        assertEq(m.idlePackCount(), 1);
    }

    function unlistAt(PackManager m, uint256[] calldata ids) external returns (uint256) {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.7 gwei);
        return m.unlist(ids, 0, m.configurationHash());
    }

    function test_measuredWorkDoesNotSpendUnusedLargeAllowance() public {
        VaultLib.Params memory p = params();
        p.gasSchedule.build = 16_000_000;
        PackManager m = manager(p);
        uint256 envelope = m.quote(16_000_000, 2, false);
        uint256 paid = this.buildAt(m, 0.2 gwei, 0);
        assertGt(paid, 2 * p.workFee, "real gas is reimbursed");
        assertLt(paid, envelope / 2, "unused allowance is not paid");
        uint256 measured = measurement(address(m), 16_000_000, 0.2 gwei, 2, false);
        assertLt(measured, 16_000_000);
        assertEq(paid, (measured + 100_000) * 0.2 gwei * 11_000 / 10_000 + 2 * p.workFee);
        assertEq(m.openListingCount(), 1);
    }

    function test_minimumAboveBoundRevertsEveryAssetAndBudgetMutation() public {
        PackManager m = manager(params());
        uint256 supply = SHAPES.totalSupply();
        uint256 active = FWA.activeListingCount();
        uint256 cash = address(m).balance;
        (uint256 routine, uint256 essential) = m.budget();
        vm.expectRevert(VaultLib.Payment.selector);
        this.buildAt(m, 0.2 gwei, 62_000_220_000_001);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(FWA.activeListingCount(), active);
        assertEq(address(m).balance, cash);
        assertEq(m.openListingCount(), 0);
        (uint256 afterRoutine, uint256 afterEssential) = m.budget();
        assertEq(afterRoutine, routine);
        assertEq(afterEssential, essential);
    }

    function test_noVerifiedWorkEarnsNoOverheadAndRecoveryStaysUnpaid() public {
        PackManager m = manager(params());
        uint256 before = address(m).balance;
        vm.expectRevert(VaultLib.Nothing.selector);
        m.harvest(new uint256[](0), 0);
        assertEq(m.quote(0, 0, false), 0, "overhead cannot create payable work");
        assertEq(address(m).balance, before);
        assertEq(meterCount(address(m)), 0, "unpaid harvest emits no payment meter");
        this.buildAt(m, 0.2 gwei, 0);
        uint256[] memory ids = new uint256[](1);
        ids[0] = m.openListingAt(0);
        vm.prank(owner); m.setExiting(true);
        if (FWA.topListingId() == ids[0]) vm.warp(vm.getBlockTimestamp() + 12 hours);
        before = address(m).balance;
        m.recoverUnlist(ids);
        assertEq(address(m).balance - before, 0.21 ether);
        before = address(m).balance;
        m.recoverLiquidate(1);
        assertEq(address(m).balance - before, 0.03 ether);
        assertEq(meterCount(address(m)), 1, "only the initial paid build emitted a meter");
    }

    function test_holderFundedCheckpointUsesSameMeasuredBoundAndRefundSource() public {
        VaultLib.Params memory p = vault.getParams();
        p.gasSchedule.checkpoint = 1;
        p.gasSchedule.allocationEntry = 0;
        p.gasSchedule.allocationRead = 0;
        bytes32 expected = vault.configurationHash();
        vm.prank(owner); vault.setParams(p, expected);
        expected = vault.configurationHash();
        vm.prank(alice); vault.deposit{value: 0.5 ether}(expected);
        uint256 source = vault.processingPool();
        assertEq(source, 40_000_200_000_000, "one gas plus100000 overhead and one work fee");
        toBlackout();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        uint256 paid = this.checkpointAt(vault.configurationHash());
        assertEq(paid, 40_000_200_000_000);
        assertGt(measurement(address(vault), 1, 0.2 gwei, 1, true), 1);
        assertEq(vault.processingPool(), 0);
    }

    function checkpointAt(bytes32 expected) external returns (uint256) {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
        return vault.checkpoint(0, 1, expected);
    }

    function test_paidUnlistAndRelistRejectUnusedInputsWhileRecoveryToleratesThem() public {
        PackManager m = manager(params());
        this.buildAt(m, 0.2 gwei, 0);
        uint256 id = m.openListingAt(0);
        uint256[] memory ids = new uint256[](2);
        ids[0] = id; ids[1] = type(uint256).max;
        vm.prank(owner); m.setExiting(true);
        if (FWA.topListingId() == id) vm.warp(vm.getBlockTimestamp() + 12 hours);
        bytes32 expected = m.configurationHash();
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        m.unlist(ids, 0, expected);
        assertEq(m.openListingCount(), 1, "paid padding reverts all earlier valid work");
        m.recoverUnlist(ids);
        assertEq(m.idlePackCount(), 1, "unpaid recovery tolerates stale hints");
        vm.prank(owner); m.setExiting(false);
        vm.prank(owner); m.setListingPaused(false);
        uint256[] memory extra = new uint256[](2);
        extra[0] = 0.21 ether; extra[1] = 0.21 ether + 10_000;
        expected = m.configurationHash();
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        m.list(extra, 0, expected);
        assertEq(m.idlePackCount(), 1, "unused proposal cannot be paid");
        assertEq(m.openListingCount(), 0);
    }
}

/// @notice Input-payment regressions use the real archived request and authenticated VRF proof.
contract ForkMeasuredSyncInputTest is MainRenewalBase {
    function test_paidAllocationSyncRejectsForeignAndUnusedAllocatedHints() public {
        _select(false);
        uint256 cursor = account.acquisitionCursor();
        bytes32 expected = account.configurationHash();
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        account.sync(one(type(uint256).max), 0, 0, expected);
        assertEq(account.acquisitionCursor(), cursor);
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        account.sync(one(selected), 0, 0, expected);
        assertEq(account.acquisitionCursor(), cursor, "ample cash makes fee-hint work unnecessary");
        assertGt(account.sync(new uint256[](0), 0, 0, expected), 0);
    }

    function test_paidTerminalSyncRejectsDuplicateAndUnpaidRecoveryToleratesIt() public {
        _select(false);
        account.sync(new uint256[](0), 0, 0, account.configurationHash());
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint256[] memory duplicate = new uint256[](2);
        duplicate[0] = selected; duplicate[1] = selected;
        bytes32 expected = account.configurationHash();
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        account.sync(duplicate, 0, 0, expected);
        assertEq(account.position(selected).state, VaultLib.ALLOCATED);
        account.recover(duplicate, 0);
        assertEq(account.position(selected).state, 0);
        assertEq(account.idleValueOf(packId), 0.03 ether);
    }

    function test_holderFundedSyncRejectsUnusedPaidHints() public {
        _select(true);
        PackVault pooled = PackVault(payable(address(account)));
        vm.deal(alice, 1 ether);
        bytes32 expected = pooled.configurationHash();
        vm.prank(alice); pooled.deposit{value: 0.5 ether}(expected);
        uint256 source = pooled.processingPool();
        vm.expectRevert(VaultLib.UnusedPaidInput.selector);
        pooled.syncCheckpoint(one(type(uint256).max), 0, 0, expected);
        assertEq(pooled.processingPool(), source);
        uint256 paid = pooled.syncCheckpoint(new uint256[](0), 0, 0, expected);
        assertGt(paid, 0);
        assertEq(source - pooled.processingPool(), paid, "only necessary sync debits request sponsorship");
    }
}
