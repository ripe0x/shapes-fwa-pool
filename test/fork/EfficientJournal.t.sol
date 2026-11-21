// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

interface JournalRequests {
    function quoteAcquisitionPrice() external view returns (uint256, uint256, uint256);
    function acquire(address, uint256, uint256, uint256, uint256) external payable;
    function acquisitionMeta(uint256) external view returns (uint64, uint64, uint64, uint16, uint16, uint256);
    function processAcquisitions(uint256) external;
    function withdrawAcquisitionRefund() external;
}

contract EfficientJournalTest is ForkBase {
    function assertEnvironment() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function setUp() public override {
        super.setUp();
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0; p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei;
        p.essentialCap = 0; p.essentialRate = 0; p.reserve = 0.005 ether;
        vm.prank(owner); vault.setParams(p);
        uint256 deposit = 1 ether + vault.requestCharge();
        vm.prank(alice); vault.deposit{value: deposit}();
        toBlackout(); checkpoint(); toOpen();
        assertGt(vault.shareBalance(alice), 0, "the funded holder owns the priced deposit");
        vm.prank(keeper); TestVaultOps.restock(vault, 1, UNITS, 0);
        vm.prank(keeper); TestVaultOps.list(vault, 1, 0);
        assertEq(vault.openListingCount(), 1);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertEnvironment();
    }

    function _refund(uint256 count) private returns (uint64 cursor) {
        JournalRequests f = JournalRequests(address(FWA));
        cursor = vault.acquisitionCursor();
        assertEq(cursor, FWA.nextSequenceToProcess());
        uint64 deadline;
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(bob); f.acquire{value: price}(bob, 1, 0, 0, 10_000);
            uint256 request = FWA.requestIdAtSequence(FWA.lastIssuedSequence());
            (, uint64 until,,,,) = f.acquisitionMeta(request);
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        vm.prank(bob); f.withdrawAcquisitionRefund();
        assertEq(FWA.nextSequenceToProcess(), uint256(cursor) + count);
        for (uint64 seq = cursor; seq < cursor + count; ++seq) {
            uint8 status = FWA.acquisitions(FWA.requestIdAtSequence(seq)).status;
            assertTrue(status == 3 || status == 4, "real deadline processing, no supplied VRF result");
        }
        assertEq(vault.openListingCount(), 1, "real FWA exposure prevents unpaid rebase");
        this.assertEnvironment();
    }

    function test_fullJournalJobCannotBeShrunkByIrrelevantTerminalIds() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5000;
        vm.prank(owner); vault.setParams(p);
        uint64 cursor = _refund(128);
        // A one-listing vault scans its own position instead of walking the 128-record journal, so
        // the paid 128-record journal job this test once pinned is unreachable here: the scan
        // displaces it (the journal path is reachable only at >= 94 open positions, covered in
        // ScanGas.t.sol::test_full128ForeignJournalReceiptGasFitsCap). The anti-gaming intent
        // carries to the scan: a foreign-only scan in the same checkpoint interval earns nothing,
        // and irrelevant terminal ids neither inflate the pay nor change how much one call clears.
        uint256 snapshot = vm.snapshotState();
        vm.prank(keeper); uint256 normalPay = vault.sync(new uint256[](0), 0, 0);
        assertEq(vault.acquisitionCursor(), uint256(cursor) + 128, "one scan clears the whole backlog");
        assertEq(normalPay, 0, "foreign-only scan applies no own selection and is unpaid");
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory irrelevant = new uint256[](16);
        for (uint256 i; i < irrelevant.length; ++i) irrelevant[i] = 1e9 + i;
        vm.prank(keeper); uint256 paddedPay = vault.sync(irrelevant, 0, 0);
        assertEq(vault.acquisitionCursor(), uint256(cursor) + 128);
        assertEq(paddedPay, normalPay, "IDs do not shrink or increase the scan job");
        assertEq(vault.openListingCount(), 1);
    }

    function test_smallForeignTailIsUnpaidUntilRealCheckpointWindow() public {
        uint64 cursor = _refund(32);
        uint256 snapshot = vm.snapshotState();
        uint256 cash = address(vault).balance;
        vm.expectRevert(StrategyLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 1);
        assertEq(vault.acquisitionCursor(), cursor);
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0), 0);
        assertEq(address(vault).balance, cash);
        assertTrue(vm.revertToState(snapshot));
        uint256 charge = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}();
        uint256 escrow = vault.pendingDepositTotal();
        toBlackout();
        uint256 pool = vault.processingPool();
        // The checkpoint window reaches its completed prefix with one scan of the single own
        // listing, not by walking 32 journal entries: the required tail now prices that scan
        // (Q_REQUIRED_TAIL + scanned*Q_SCAN, scanned == openListingCount == 1).
        vm.prank(keeper); uint256 paid = vault.sync(new uint256[](0), 0, 1);
        assertEq(paid, (VaultLib.Q_REQUIRED_TAIL + VaultLib.Q_SCAN) * 0.2 gwei);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertEq(vault.processingPool(), pool);
        assertEq(vault.pendingDepositTotal(), escrow);
        checkpoint();
        assertEq(vault.pendingDepositTotal(), 0);
    }

    function test_lockedSharesKeepSyncRoutineWithZeroEssentialBudget() public {
        _refund(128);
        uint256 charge = vault.requestCharge();
        uint256 shares = vault.shareBalance(alice) / 10;
        vm.prank(alice); vault.requestRedeem{value: charge}(shares);
        assertGt(vault.lockedShares(), 0);
        // Locked shares make the checkpoint tail required. A one-listing vault reaches its completed
        // prefix with one scan rather than the 128-record journal, so the routine sync it earns is
        // the required tail over that scan (Q_REQUIRED_TAIL + 1*Q_SCAN). It is still drawn from the
        // routine budget while the essential budget stays zero, which is the point of the test.
        toBlackout();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        (uint256 routineBefore, uint256 essentialBefore) = vault.budget();
        assertEq(essentialBefore, 0);
        uint256 pool = vault.processingPool();
        vm.prank(keeper); uint256 paid = vault.sync(new uint256[](0), 0, 1);
        (uint256 routineAfter, uint256 essentialAfter) = vault.budget();
        assertEq(paid, (VaultLib.Q_REQUIRED_TAIL + VaultLib.Q_SCAN) * 0.2 gwei);
        assertEq(routineBefore - routineAfter, paid);
        assertEq(essentialAfter, 0);
        assertEq(vault.processingPool(), pool);
    }

    function test_distributionFlagCannotPayForTailWithoutDistributableGain() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5000;
        vm.prank(owner); vault.setParams(p);
        _refund(1); toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        uint256 cash = address(vault).balance;
        vm.prank(keeper); uint256 paid = vault.sync(new uint256[](0), witness, 0);
        assertEq(paid, 0, "a configured percentage is not a payable checkpoint");
        assertEq(address(vault).balance, cash);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        vm.expectRevert(bytes4(keccak256("Nothing()")));
        vault.checkpoint(witness, 0);
    }

    function test_distributionOnlyTailAllowsRealCheckpointAfterItsExpense() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5000;
        vm.prank(owner); vault.setParams(p);
        _refund(1);
        vm.prank(bob); (bool accepted,) = address(vault).call{value: 1 ether}("");
        assertTrue(accepted);
        toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        uint256 snapshot = vm.snapshotState();
        uint256 cursor = vault.acquisitionCursor();
        uint256 cash = address(vault).balance;
        vm.expectRevert(StrategyLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), witness + 1e9, 1);
        assertEq(vault.acquisitionCursor(), cursor, "refused proof payment rolls back the journal");
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), witness + 1e9, 0), 0);
        assertEq(address(vault).balance, cash, "invalid witness earns no proof premium");
        assertTrue(vm.revertToState(snapshot));
        vm.prank(keeper); uint256 paid = vault.sync(new uint256[](0), witness, 1);
        assertEq(paid, (VaultLib.Q_REQUIRED_TAIL + VaultLib.Q_DISTRIBUTION_PROOF + VaultLib.Q_JOURNAL) * 0.2 gwei);
        assertEq(vault.pendingDepositTotal(), 0); assertEq(vault.lockedShares(), 0);
        vm.prank(keeper); vault.checkpoint(witness, 0);
        assertGe(vault.distributionReserve(), 0.01 ether);
        assertGe(address(vault).balance, vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal() + vault.processingPool() + vault.pendingDepositTotal());
    }
}
