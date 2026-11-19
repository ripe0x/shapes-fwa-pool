// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {JournalRequests} from "./EfficientJournal.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @notice Calibration for Q_SCAN. A vault with N own Active listings and a real foreign backlog
///         takes the scan path; the scan reads one FWA listing per Active own position. We measure
///         receipt-equivalent billed gas (cold state, intrinsic added, gas-price context asserted)
///         for N = 1, 8, 30 to derive the marginal gas per scanned Active listing and the fixed
///         overhead the scan adds over Q_SYNC, then compare the journal path for the same backlog.
///         Nothing is mocked: the backlog is built from real acquire requests that FWA's own
///         permissionless processor refunds at their deadline.
contract ScanGasTest is ForkBase {
    function setUp() public override {
        super.setUp();
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 2 gwei;
        vm.prank(owner);
        vault.setParams(p);
        vm.deal(address(vault), 5 ether); // fund inventory purchases (our own contract)
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function assertGasContext() external view {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function _listOwn(uint256 n) internal {
        vm.prank(keeper);
        TestVaultOps.restock(vault, n, 3, 0);
        vm.prank(keeper);
        TestVaultOps.list(vault, n, 0);
        assertEq(vault.openListingCount(), n, "own active listings in place");
    }

    /// @dev Real foreign acquisitions refunded at their own deadline advance FWA's completed prefix.
    function _backlog(uint256 count) internal {
        JournalRequests f = JournalRequests(address(FWA));
        uint64 cursor = vault.acquisitionCursor();
        uint64 deadline;
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(bob);
            f.acquire{value: price}(bob, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        vm.prank(bob);
        f.withdrawAcquisitionRefund();
        assertEq(FWA.nextSequenceToProcess(), uint256(cursor) + count, "real completed foreign prefix");
    }

    function _cold() internal {
        vm.cool(address(vault));
        vm.cool(address(FWA));
        vm.cool(address(vault.keeperPolicy()));
        vm.cool(address(VaultLib));
        vm.cool(keeper);
    }

    function _intrinsic(bytes memory input) internal pure returns (uint256 g) {
        g = 21_000;
        for (uint256 i; i < input.length; ++i) g += input[i] == 0 ? 4 : 16;
    }

    /// @dev Receipt-equivalent billed gas of the (unpaid, own==0) scan sync over N own listings.
    function _measureScan(uint256 n) internal returns (uint256 billed, uint256 pay) {
        vm.deal(address(vault), 5 ether);
        _listOwn(n);
        _backlog(50); // 50*22000 > 30*30000: scan path for every N here
        uint64 end = FWA.nextSequenceToProcess();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), uint256(0), uint256(0)));
        uint256 intrinsic = _intrinsic(input);
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        billed = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        pay = abi.decode(ret, (uint256));
        assertEq(vault.acquisitionCursor(), end, "scan cleared the whole backlog in one call");
        assertEq(pay, 0, "foreign-only scan applies no own selection and is unpaid");
    }

    function test_scanBilledGasN1() public {
        (uint256 billed, uint256 pay) = _measureScan(1);
        emit log_named_uint("scan billed gas N=1", billed);
        emit log_named_uint("scan pay N=1", pay);
    }

    function test_scanBilledGasN8() public {
        (uint256 billed, uint256 pay) = _measureScan(8);
        emit log_named_uint("scan billed gas N=8", billed);
        emit log_named_uint("scan pay N=8", pay);
    }

    function test_scanBilledGasN30() public {
        (uint256 billed, uint256 pay) = _measureScan(30);
        emit log_named_uint("scan billed gas N=30", billed);
        emit log_named_uint("scan pay N=30", pay);
    }

    /// @notice Preserves the full 128-record foreign-journal EIP-7825 coverage that a small vault
    ///         can no longer reach (it scans instead). With >= 94 open own positions the scan is no
    ///         longer cheaper than the next journal batch (94*Q_SCAN > 128*Q_JOURNAL), so the sync
    ///         walks the real 128-record journal. Measures receipt-equivalent gas and asserts the
    ///         keeper's 25%-padded estimate fits EIP-7825. The own positions are foreign-refunded,
    ///         never selected, so the journal processes 128 foreign records with no own transition.
    function test_full128ForeignJournalReceiptGasFitsCap() public {
        vm.deal(address(vault), 10 ether);
        _listOwn(94); // 94*30000 = 2,820,000 > 128*22000 = 2,816,000: scan declines, journal runs
        _backlog(128);
        uint64 end = FWA.nextSequenceToProcess();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), uint256(0), uint256(1)));
        uint256 intrinsic = _intrinsic(input);
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(vault.keeperPolicy()));
        vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(keeper);
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        uint256 used = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        uint256 pay = abi.decode(ret, (uint256));
        assertEq(pay, (VaultLib.Q_SYNC + 128 * VaultLib.Q_JOURNAL) * 0.2 gwei, "paid 128-record journal job");
        assertEq(vault.acquisitionCursor(), end, "one call drains the full 128-record journal");
        emit log_named_uint("full 128-record foreign journal receipt-equivalent gas (94 own)", used);
        assertLt((used * 125 + 99) / 100, 16_777_216, "128-record journal plus 25% keeper gas margin fits EIP-7825");
    }

    /// @dev Journal path over the same backlog with one own listing (backlog 1 forces the journal):
    ///      a reference for the per-journal-entry cost the scan displaces.
    function test_journalBilledGasBacklog1() public {
        vm.deal(address(vault), 5 ether);
        _listOwn(1);
        _backlog(1); // 1*22000 < 1*30000: journal path
        uint64 end = FWA.nextSequenceToProcess();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), uint256(0), uint256(0)));
        uint256 intrinsic = _intrinsic(input);
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        uint256 billed = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        assertEq(vault.acquisitionCursor(), end, "journal cleared the single entry");
        emit log_named_uint("journal billed gas backlog=1 (1 own)", billed);
    }
}

/// @notice A paid scan: one real VRF own selection applied by the scan. Confirms the fixed quote
///         (Q_SYNC + scanned*Q_SCAN + Q_SELECTED) covers the keeper's billed gas at 0.5 gwei.
contract ScanPaidGasTest is SelectionBase {
    receive() external payable {}

    function test_paidScanProfitableN1() public {
        _select(late()); // 1 own listing, really ALLOCATED; vault book still holds it Active
        // Drain the forked block's other pending request and build backlog >= 2 so the scan triggers.
        JournalRequests f = JournalRequests(address(FWA));
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        if (FWA.unsettledAcquisitionCount() != 0) f.processAcquisitions(50);
        address buyer = makeAddr("pack-vault-test-scan-paid-buyer");
        assertEq(buyer.code.length, 0);
        vm.deal(buyer, 5 ether);
        uint64 deadline;
        for (uint256 i; i < 3; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(buyer);
            f.acquire{value: price}(buyer, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(10);
        vm.prank(buyer);
        f.withdrawAcquisitionRefund();
        uint256 backlog = FWA.nextSequenceToProcess() - vault.acquisitionCursor();
        assertGe(backlog, 2, "scan triggers for one own listing");

        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0;
        p.workFee = 0;
        p.maxTip = 0;
        vm.prank(vault.owner());
        vault.setParams(p);
        vm.fee(0.5 gwei);
        vm.txGasPrice(0.5 gwei);

        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), uint256(0), uint256(0)));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        vm.cool(address(vault));
        vm.cool(address(FWA));
        vm.cool(address(vault.keeperPolicy()));
        vm.cool(address(VaultLib));
        uint256 start = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        uint256 billed = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        uint256 pay = abi.decode(ret, (uint256));
        uint256 gasQ = VaultLib.Q_SYNC + 1 * VaultLib.Q_SCAN + VaultLib.Q_SELECTED;
        emit log_named_uint("paid scan billed gas", billed);
        emit log_named_uint("paid scan quoted gasQ", gasQ);
        emit log_named_uint("paid scan pay wei (0.5 gwei)", pay);
        assertEq(pay, gasQ * 0.5 gwei, "paid scan pays the fixed quote");
        assertGt(billed, 0);
        assertGe(gasQ, billed, "fixed quote covers the keeper's billed gas: scan stays profitable");
    }
}
