// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {GasQuotes} from "../utils/GasQuotes.sol";

import {ForkBase} from "./ForkBase.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {JournalRequests} from "./EfficientJournal.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Charges} from "../utils/Charges.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {LISTING_ALLOCATED} from "../../src/interfaces/External.sol";

/// @notice Scan-path regression guards. A small vault reads its own positions instead of FWA's
///         global journal; keeper pay is earned only for real own work, never manufactured from
///         foreign activity, backlog size, split calls, duplicate ids or a hostile policy, and
///         never funded from holder liabilities. Nothing is mocked: the backlog is real foreign
///         acquire requests FWA's own processor refunds at their deadline, and every own selection
///         is a real VRF replay from the authentic fixtures.
contract ScanSyncForeignTest is ForkBase {
    function setUp() public override {
        super.setUp();
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0; p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected0);
        TestVaultOps.fundTo(vault, 5 ether);
        vm.prank(keeper); TestVaultOps.restock(vault, 1, UNITS, 0); // build lists it at once
        assertEq(vault.openListingCount(), 1);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
    }

    function _backlog(uint256 count) internal {
        JournalRequests f = JournalRequests(address(FWA));
        uint64 cursor = vault.acquisitionCursor();
        uint64 deadline;
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(bob); f.acquire{value: price}(bob, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        vm.prank(bob); f.withdrawAcquisitionRefund();
        assertEq(FWA.nextSequenceToProcess(), uint256(cursor) + count, "real completed foreign prefix");
    }

    function _billedScan() internal returns (uint256 billed, uint256 pay) {
        bytes memory input = abi.encodeCall(PackAccount.sync, (new uint256[](0), uint256(0), uint256(0), vault.configurationHash()));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        vm.cool(address(vault)); vm.cool(address(FWA)); vm.cool(address(VaultLib)); vm.cool(keeper);
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        billed = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        pay = abi.decode(ret, (uint256));
    }

    // (b) Keeper work is paid only for eligible vault work: a foreign-only scan with no own
    //     selection and no checkpoint window pays nothing, and a repeat call has nothing to do.
    function test_b_foreignOnlyScanPaysNothingAndRepeatIsNothing() public {
        _backlog(32);
        uint256 cash = address(vault).balance;
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 0, _expected1);
        assertEq(pay, 0, "no own selection, no checkpoint: unpaid");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "one scan cleared it");
        assertEq(address(vault).balance, cash, "no vault cash moved");
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 0, _expected2);
    }

    // (c) Unrelated FWA acquisitions (real refunded foreign requests) cause no vault charge while
    //     the vault holds an Active listing.
    function test_c_unrelatedForeignAcquisitionsChargeNothing() public {
        uint256 cash = address(vault).balance;
        uint256 keeperCash = keeper.balance;
        _backlog(50);
        assertEq(address(vault).balance, cash, "foreign acquire/refund never touches vault cash");
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 0, _expected3);
        assertEq(pay, 0);
        assertEq(address(vault).balance, cash, "scanning the foreign backlog costs the vault nothing");
        assertEq(keeper.balance, keeperCash, "keeper earns nothing for foreign-only work");
        assertEq(vault.openListingCount(), 1, "the Active listing is untouched");
    }

    // (g) A small vault can pause routine work across a long backlog and resume with ONE scan whose
    //     cost does not grow with the backlog (it reads only the vault's own positions).
    function test_g_oneScanClearsAnyBacklogAtBacklogIndependentCost() public {
        uint256 snapshot = vm.snapshotState();
        _backlog(41);
        uint64 end41 = FWA.nextSequenceToProcess();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        (uint256 billed41,) = _billedScan();
        assertEq(vault.acquisitionCursor(), end41, "one scan cleared the 41-entry backlog");
        assertTrue(vm.revertToState(snapshot));
        _backlog(94);
        uint64 end94 = FWA.nextSequenceToProcess();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        (uint256 billed94,) = _billedScan();
        assertEq(vault.acquisitionCursor(), end94, "one scan cleared the 94-entry backlog");
        emit log_named_uint("scan billed gas backlog 41", billed41);
        emit log_named_uint("scan billed gas backlog 94", billed94);
        // A journal would add (94-41)*Q_JOURNAL. The scan's cost is independent of backlog size.
        uint256 diff = billed94 > billed41 ? billed94 - billed41 : billed41 - billed94;
        assertLt(diff, GasQuotes.Q_JOURNAL, "scan cost does not scale with the backlog");
    }

    // (h) A keeper cannot manufacture profitable repeat work: splitting a cleared backlog into a
    //     later call earns no second payment, and irrelevant or duplicate ids add nothing.
    function test_h_noManufacturedRepeatOrPaddedScan() public {
        _backlog(48);
        uint256 snapshot = vm.snapshotState();
        uint256[] memory padded = new uint256[](16);
        for (uint256 i; i < padded.length; ++i) padded[i] = 1e9 + i;
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); uint256 paddedPay = vault.sync(padded, 0, 0, _expected4);
        assertEq(paddedPay, 0, "irrelevant ids do not manufacture pay");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 0, _expected5);
        assertTrue(vm.revertToState(snapshot));
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); uint256 plainPay = vault.sync(new uint256[](0), 0, 0, _expected6);
        assertEq(plainPay, paddedPay, "padding changes nothing: a split later call earns no second scan");
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vm.prank(keeper); vault.sync(padded, 0, 0, _expected7);
    }
}

/// @notice Own-selection scan-path guards on the real VRF replay fixture (primary()): a paid scan is
///         capped by the vault's own quote and budget, delaying it loses no fees and cannot misprice
///         shares, budget exhaustion is recoverable, and a full redemption settles to the holder's
///         exact NAV share without ever funding keeper pay from liabilities.
contract ScanSyncSelectionTest is SelectionBase {
    uint256 constant SCAN_Q = GasQuotes.Q_SYNC + GasQuotes.Q_SCAN + GasQuotes.Q_SELECTED; // 295_000

    receive() external payable {}

    function _clean() internal {
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0; p.workFee = 0; p.maxTip = 0; p.keeperShareBps = 0;
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected8);
    }

    /// @dev Real foreign backlog (>= 41) so the vault takes the scan path over its one own listing.
    function _backlog(uint256 count) internal {
        JournalRequests f = JournalRequests(address(FWA));
        if (FWA.unsettledAcquisitionCount() != 0) { vm.roll(block.number + 7_300); f.processAcquisitions(16); }
        address buyer = makeAddr("pack-vault-test-scan-sync-buyer");
        assertEq(buyer.code.length, 0); assertEq(buyer.balance, 0);
        vm.deal(buyer, 10 ether);
        uint64 deadline;
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(buyer); f.acquire{value: price}(buyer, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        vm.prank(buyer); f.withdrawAcquisitionRefund();
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue drained");
        assertGe(FWA.nextSequenceToProcess() - vault.acquisitionCursor(), 41, "scan path");
    }

    // (a) Routine pay never exceeds the routine budget: with the budget below the scan quote, the
    //     paid scan pays exactly the budget and leaves it at zero.
    function test_a_routinePayCappedByBudget() public {
        _select(primary()); _clean();
        _backlog(45);
        VaultLib.Params memory p = vault.getParams();
        p.routineRate = 0; p.routineCap = 0.00008 ether; // below SCAN_Q at 0.5 gwei (= 0.0001475 ETH)
        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected9);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        (uint256 routine,) = vault.budget();
        assertEq(routine, 0.00008 ether, "budget below the scan quote");
        assertLt(routine, SCAN_Q * 0.5 gwei, "quote exceeds the budget");
        bytes32 _expected10 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), 0, 1, _expected10);
        assertEq(paid, routine, "pay is capped at the routine budget");
        (uint256 after_,) = vault.budget();
        assertEq(after_, 0, "budget drained to zero");
    }

    // (i) A hostile keeper policy (owner-set, always offers the maximum) cannot raise scan pay above
    //     the vault's own fixed quote and budget.
    function test_i_scanPaysSingleConfiguredQuote() public {
        _select(primary()); _clean();
        _backlog(45);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        uint256 cash = address(vault).balance;
        bytes32 _expected11 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), 0, 1, _expected11);
        assertEq(paid, SCAN_Q * 0.5 gwei, "the vault caps the max offer at its own scan quote");
        assertEq(cash - address(vault).balance, paid, "only the capped quote leaves the vault");
    }

    // (f) Budget exhaustion is recoverable: with no routine budget the paid scan is refused and the
    //     selection stays pending; after the budget refills over time the paid scan succeeds.
    function test_f_budgetExhaustionRecoverable() public {
        _select(primary()); _clean();
        _backlog(45);
        uint64 cursor = vault.acquisitionCursor();
        VaultLib.Params memory p = vault.getParams();
        p.routineCap = 0; p.routineRate = 0;
        bytes32 _expected12 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected12);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        (uint256 routine,) = vault.budget();
        assertEq(routine, 0, "budget exhausted");
        bytes32 _expected13 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(new uint256[](0), 0, 1, _expected13);
        assertEq(vault.acquisitionCursor(), cursor, "refused pay rolls back the scan: selection still pending");
        // Owner restores a refill rate and cap; time then refills the routine budget.
        p.routineCap = 0.01 ether; p.routineRate = 0.01 ether;
        bytes32 _expected14 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected14);
        vm.warp(block.timestamp + 12 hours);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        (routine,) = vault.budget();
        assertGe(routine, SCAN_Q * 0.5 gwei, "budget refilled above the scan quote");
        bytes32 _expected15 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), 0, 1, _expected15);
        assertEq(paid, SCAN_Q * 0.5 gwei, "the refilled budget pays the full scan quote");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "the selection is finally applied");
    }

    // (e) A delayed sync cannot misprice shares: with an unapplied own selection, checkpoint pricing
    //     reverts CatchUpFirst until the scan; and the applied NAV is identical to the journal path.
    function test_e_delayedSyncCannotMispriceSharesCatchUpFirst() public {
        _select(primary()); _clean();
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        // Cursor is behind the real selection, so NAV pricing refuses to run (CatchUpFirst): a stale
        // sync cannot misprice a deposit or redemption against an unapplied own selection.
        assertGt(FWA.nextSequenceToProcess(), vault.acquisitionCursor(), "selection not yet applied");
        vm.expectRevert(VaultLib.CatchUpFirst.selector);
        vault.accountedNav(0);

        // Journal path (backlog 1) applies the selection; price it and record the gas cost.
        uint256 snapshot = vm.snapshotState();
        bytes32 _expected16 = TestVaultOps.configurationHash(vault);
        uint256 payJournal = vault.sync(new uint256[](0), 0, 0, _expected16);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        uint256 navJournal = vault.accountedNav(0);
        assertTrue(vm.revertToState(snapshot));

        // Scan path over a long real backlog applies the same selection; the priced NAV is identical
        // net of each path's own keeper gas quote (Q_JOURNAL vs Q_SCAN).
        _backlog(45);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        bytes32 _expected17 = TestVaultOps.configurationHash(vault);
        uint256 payScan = vault.sync(new uint256[](0), 0, 1, _expected17);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        uint256 navScan = vault.accountedNav(0);
        assertEq(navScan + payScan, navJournal + payJournal,
            "same selection prices identically, net of each path's gas cost");
    }

    // (d) Delayed maintenance loses no fees: the vault's fee entitlement and NAV are identical whether
    //     the selection is applied immediately (journal) or after a long backlog (one late scan). The
    //     only difference is the legitimate keeper gas quote of each path.
    function test_d_delayedMaintenanceLosesNoFees() public {
        _select(primary()); _clean();
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        uint256 credit = FWA.feeCredit(address(vault)); // the selection's fee share, uncollected

        credit; // silence: fees read after each sync below
        uint256 snapshot = vm.snapshotState();
        uint256 cashBefore = address(vault).balance;
        bytes32 _expected18 = TestVaultOps.configurationHash(vault);
        uint256 payNow = vault.sync(new uint256[](0), 0, 0, _expected18);
        assertEq(cashBefore - address(vault).balance, payNow, "immediate sync outflow is only its gas quote");
        uint256 navNow = vault.accountedNav(0);
        uint256 feesNow = FWA.feeCredit(address(vault)) + FWA.pendingFees(selected);
        assertTrue(vm.revertToState(snapshot));

        _backlog(45);
        vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        uint256 cashBefore2 = address(vault).balance;
        bytes32 _expected19 = TestVaultOps.configurationHash(vault);
        uint256 payLate = vault.sync(new uint256[](0), 0, 1, _expected19);
        assertEq(cashBefore2 - address(vault).balance, payLate, "late sync outflow is only its gas quote");
        uint256 navLate = vault.accountedNav(0);
        uint256 feesLate = FWA.feeCredit(address(vault)) + FWA.pendingFees(selected);

        assertEq(feesLate, feesNow, "delay loses no fee income");
        assertEq(navLate + payLate, navNow + payNow, "delay does not change NAV, net of each path's gas cost");
    }

    // (j) A full redemption settles to the holder's exact NAV share; the scan/checkpoint/claim never
    //     fund keeper pay from liabilities, and with gas above the ceiling pay is capped at it.
    function test_j_fullRedemptionSettlesWithoutFundingPayFromLiabilities() public {
        _select(primary());
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0; p.workFee = 0; p.maxTip = 0; p.keeperShareBps = 0;
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 0.5 gwei; // pay capped at this ceiling
        bytes32 _expected20 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected20);

        // A holder funds a deposit and its request charge (the deposit is escrowed even while the
        // selection is still unapplied).
        address holder = makeAddr("pack-vault-test-scan-sync-holder");
        assertEq(holder.code.length, 0); assertEq(holder.balance, 0);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.deal(holder, gross);
        bytes32 _expected21 = TestVaultOps.configurationHash(vault);
        vm.prank(holder); vault.deposit{value: gross}(_expected21);

        _backlog(45); // long real backlog: interrupted maintenance the vault clears with one scan
        vm.fee(5 gwei); vm.txGasPrice(5 gwei); // gas far above the 0.5 gwei ceiling
        bytes32 _expected22 = TestVaultOps.configurationHash(vault);
        uint256 paidScan = vault.sync(new uint256[](0), 0, 0, _expected22);
        assertEq(paidScan, SCAN_Q * 0.5 gwei, "pay is capped at the 0.5 gwei ceiling, not the 5 gwei basefee");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "one scan caught the cursor up");

        // The purchaser keeps the pack; the terminal resolves and the position closes, leaving the
        // vault holding the settlement proceeds against which the holder redeems.
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        vm.prank(primary().purchaser); IFwaSettle(address(FWA)).keepNFT(selected);
        bytes32 _expected23 = TestVaultOps.configurationHash(vault);
        vault.sync(_one(selected), 0, 0, _expected23);
        assertEq(vault.openListingCount(), 0, "selection resolved, no active exposure");

        // Price the deposit in (no active positions: witness 0), then the holder redeems every share.
        _toBlackout();
        bytes32 _expected24 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(0, 0, _expected24);
        uint256 shares = vault.shareBalance(holder);
        assertGt(shares, 0, "holder priced in");
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.deal(holder, rc);
        bytes32 _expected25 = TestVaultOps.configurationHash(vault);
        vm.prank(holder); vault.requestRedeem{value: rc}(shares, _expected25);
        vm.warp(block.timestamp + 12 hours); vm.roll(block.number + 3600);
        bytes32 _expected26 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(0, 0, _expected26);

        // Liabilities are fully backed by cash: keeper pay was drawn from free ETH, never from them.
        uint256 liabilities = vault.redemptionReserve() + vault.claimableTotal()
            + vault.processingPool() + vault.pendingDepositTotal();
        assertGe(address(vault).balance, liabilities, "liabilities never funded keeper pay");

        uint256 holderBefore = holder.balance;
        uint256 vaultBefore = address(vault).balance;
        vm.prank(holder); vault.claim(); // claim lazily settles the redemption fill and pays it out
        uint256 received = holder.balance - holderBefore;
        assertEq(vaultBefore - address(vault).balance, received, "every claimed wei comes from the vault, exact");
        assertGt(received, 0.95 ether, "holder receives their NAV share of the ~1 ETH deposit");
        assertLt(received, 1 ether, "net of the deposit and redemption charges");
        assertEq(vault.shareBalance(holder), 0, "redeemed in full");
        assertEq(vault.claimableTotal(), 0, "nothing left owed");
    }

    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1); ids[0] = id;
    }

    function _toBlackout() internal {
        uint256 t = block.timestamp;
        uint256 start = t - t % 12 hours + 11 hours + 45 minutes;
        if (t >= start) start += 12 hours;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
    }
}
