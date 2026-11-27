// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MeasuredPay} from "../utils/MeasuredPay.sol";

import {GasQuotes} from "../utils/GasQuotes.sol";

import {SelectionBase} from "./ForkSelection.t.sol";
import {IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {IFWAV2, LISTING_ACTIVE} from "../../src/interfaces/External.sol";

interface CompleteForeignRequests {
    function quoteAcquisitionPrice() external view returns (uint256, uint256, uint256);
    function acquire(address, uint256, uint256, uint256, uint256) external payable;
    function acquisitionMeta(uint256) external view returns (uint64, uint64, uint64, uint16, uint16, uint256);
    function processAcquisitions(uint256) external;
    function withdrawAcquisitionRefund() external;
}

/// @notice Exposed successful foreign journal work. Both results come from the
/// authentic Chainlink coordinator calls for the real two-request transaction.
/// Only the ownership of the 30 newly posted listings differs from SelectionBase:
/// the vault owns index 0, and the real first result selects the foreign index 28.
/// There is no persistent external fork state, fabricated result, or storage write.
contract CompleteForeignJournalTest is SelectionBase {
    address internal keeper;
    address internal holder;
    uint64 internal begin;
    uint256 internal forkBlock;
    string internal fixture;
    string internal constant KEY = ".26417086";

    receive() external payable {}

    function setUp() public {
        // This suite replays real foreign acquisitions captured in complete-foreign.json at block
        // 26,417,086 (its own fixture), independent of SelectionBase's VRF candidates.
        Candidate memory c = Candidate(
            0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f,
            26_417_086, 26_417_091, 1_794_705_887, 0, 0, address(0)
        );
        vm.createSelectFork("mainnet", c.requestTx);
        forkBlock = c.requestBlock - 1;
        _deployExposure();
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES))
        );
        for (uint256 i = 1; i < FIXTURE_COUNT; ++i) filler.createAndList(B);
        fixture = vm.readFile("test/fixtures/complete-foreign.json");
        _call(fixture, KEY, "req");
        vm.roll(c.fulfillBlock); vm.warp(c.fulfillTimestamp);
        vm.setBlockhash(c.requestBlock, vm.parseJsonBytes32(fixture, string.concat(KEY, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fixture, string.concat(KEY, ".fulBaseFee")));
        _call(fixture, KEY, "ful");
        _assertForeign(begin);
        assertEq(FWA.nextSequenceToProcess(), uint256(begin) + 1);
        assertEq(FWA.unsettledAcquisitionCount(), 1, "second authentic request awaits its own proof");
        _assertExposure();
    }

    function _deployExposure() internal {
        assertEq(FWA.unsettledAcquisitionCount(), 0, "authentic queue is drained before local admission");
        keeper = makeAddr("pack-vault-test-complete-foreign-keeper");
        holder = makeAddr("pack-vault-test-complete-foreign-holder");
        address owner = makeAddr("pack-vault-test-complete-foreign-owner");
        assertEq(keeper.code.length, 0); assertEq(keeper.balance, 0);
        assertEq(holder.code.length, 0); assertEq(holder.balance, 0);
        assertEq(owner.code.length, 0); assertEq(owner.balance, 0);
        vm.deal(keeper, 1 ether); vm.deal(holder, 10 ether); vm.deal(address(this), 10 ether);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        // D62: ShapePacks oracle-exempt so a 0.06 ETH pack lists uncapped.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        VaultLib.Params memory p;
        p.gasSchedule = VaultLib.defaultGasSchedule();
        p.backingRatioBps = 12_000;
        p.acceptedMintFee = 0.001 ether;
        p.minDeposit = 0.01 ether;
        p.minDistribution = 0.01 ether;
        p.minEdgeBps = 100; p.maxTip = 0.05 gwei; p.keeperShareBps = 2_500;
        p.upliftBoundBps = 200; p.packUnitsMask = uint64(1) << UNITS;
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei; // the 6-unit edge lists at this ceiling
        p.tvlCap = 100 ether; p.routineCap = 0.3 ether; p.routineRate = 0.01 ether;

        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 3 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        TestVaultOps.restock(vault, 1, UNITS, 0); // build lists it at once
        selected = vault.openListingAt(0);

        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected0);
        begin = vault.acquisitionCursor();
        assertEq(begin, FWA.nextSequenceToProcess());
    }

    function _second() internal {
        _call(fixture, KEY, "secondFul");
        _assertForeign(begin + 1);
        assertEq(FWA.nextSequenceToProcess(), uint256(begin) + 2);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        _assertExposure();
    }

    function _assertForeign(uint64 sequence) internal view {
        IFWAV2.Acquisition memory acquisition = FWA.acquisitions(FWA.requestIdAtSequence(sequence));
        assertEq(acquisition.status, 2, "real proof produced a successful acquisition");
        (address collection, address depositor,,,,,,,,,) = FWA.listings(acquisition.listingId);
        assertTrue(collection != address(0));
        assertTrue(depositor != address(vault), "successful acquisition belongs to a foreign depositor");
    }

    function _assertExposure() internal view {
        (, address depositor,,,,,,,,, uint8 status) = FWA.listings(selected);
        assertEq(depositor, address(vault)); assertEq(status, LISTING_ACTIVE);
        assertEq(vault.openListingCount(), 1, "real active vault exposure remains throughout replay");
    }

    function _requiredTail() internal {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        uint256 amount = 0.1 ether + vault.requestCharge();
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(holder); vault.deposit{value: amount}(_expected1);
        uint256 interval = block.timestamp / 12 hours;
        uint256 blackout = interval * 12 hours + 12 hours - 15 minutes + 60;
        if (blackout < block.timestamp) blackout += 12 hours;
        vm.warp(blackout);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        assertTrue(FWA.isPurchaseBlackout());
    }

    function _paidTail(uint256 records) internal {
        _requiredTail();
        uint256 escrow = vault.pendingDepositTotal();
        uint256 processing = vault.processingPool();
        uint256 before = keeper.balance;
        // One own listing reaches its completed prefix by scanning that position whenever the scan
        // costs no more than the next journal batch; only a backlog below open*Q_SCAN/Q_JOURNAL
        // (here backlog 1) still walks the journal. The required tail prices whichever path runs.
        uint256 backlog = FWA.nextSequenceToProcess() - vault.acquisitionCursor();
        assertEq(backlog, records, "backlog is the record count under test");
        uint256 open = vault.openListingCount();
        uint256 batch = backlog < 128 ? backlog : 128;
        uint256 gasQ = open * GasQuotes.Q_SCAN <= batch * GasQuotes.Q_JOURNAL
            ? GasQuotes.Q_REQUIRED_TAIL + open * GasQuotes.Q_SCAN
            : GasQuotes.Q_REQUIRED_TAIL + backlog * GasQuotes.Q_JOURNAL;
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.recordLogs();
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 1, _expected2);
        assertEq(pay, MeasuredPay.gross(vault, gasQ, 0, false, 0.2 gwei));
        assertEq(keeper.balance - before, pay);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertEq(vault.pendingDepositTotal(), escrow, "journal payment cannot consume deposit escrow");
        assertEq(vault.processingPool(), processing, "journal payment cannot consume checkpoint charges");
        _assertExposure();
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 0, _expected3);
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); vault.checkpoint(selected, 0, _expected4);
        assertGt(vault.shareBalance(holder), 0, "holder checkpoint succeeds after real successful catchup");
    }

    function test_successfulForeignSingletonRequiredTail() public {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0, _expected5), 0);
        assertEq(vault.acquisitionCursor(), uint256(begin) + 1, "first singleton is voluntary while queue is live");
        _second();
        _paidTail(1);
    }

    function test_successfulForeignTwoRecordRequiredTail() public {
        _second();
        _paidTail(2);
    }

    function test_successfulForeignEarlyTailCannotCollectPayment() public {
        _second();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 1, _expected6);
        assertEq(vault.acquisitionCursor(), begin, "refused payment rolls back journal progress");
        uint256 before = address(vault).balance;
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0, _expected7), 0);
        assertEq(address(vault).balance, before);
        assertEq(vault.acquisitionCursor(), uint256(begin) + 2);
        _assertExposure();
    }

    function _replayForeignHistory() internal {
        string memory history = vm.readFile("test/fixtures/complete-foreign-history.json");
        vm.createSelectFork("mainnet", vm.parseJsonBytes32(history, ".calls[0].tx"));
        forkBlock = vm.parseJsonUint(history, ".calls[0].block") - 1;
        _deployExposure();
        uint256 n = vm.parseJsonUint(history, ".callCount");
        for (uint256 i; i < n; ++i) {
            string memory key = string.concat(".calls[", vm.toString(i), "]");
            vm.roll(vm.parseJsonUint(history, string.concat(key, ".block")));
            vm.warp(vm.parseJsonUint(history, string.concat(key, ".timestamp")));
            vm.fee(vm.parseJsonUint(history, string.concat(key, ".baseFee")));
            if (vm.parseJsonBool(history, string.concat(key, ".isFulfillment"))) {
                vm.setBlockhash(vm.parseJsonUint(history, string.concat(key, ".requestBlock")),
                    vm.parseJsonBytes32(history, string.concat(key, ".requestBlockHash")));
            }
            address from = vm.parseJsonAddress(history, string.concat(key, ".from"));
            address to = vm.parseJsonAddress(history, string.concat(key, ".to"));
            bytes memory input = vm.parseJsonBytes(history, string.concat(key, ".input"));
            uint256 value = vm.parseJsonUint(history, string.concat(key, ".value"));
            vm.txGasPrice(vm.parseJsonUint(history, string.concat(key, ".gasPrice")));
            vm.deal(address(this), address(this).balance + value);
            if (value != 0) {
                uint256 historicalBalance = vm.parseJsonUint(history, string.concat(key, ".senderBalanceBeforeBlock"));
                assertGe(historicalBalance, value, "canonical pre-request funding covers the original value");
                vm.deal(from, historicalBalance);
            }
            uint256 issued = FWA.lastIssuedSequence();
            vm.prank(from, from);
            (bool ok, bytes memory ret) = to.call{value: value}(input);
            if (!ok) {
                emit log_named_uint("authentic call index", i);
                emit log_named_string("authentic transaction", vm.parseJsonString(history, string.concat(key, ".tx")));
                assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
            }
            if (vm.parseJsonBool(history, string.concat(key, ".isRequest"))) {
                assertEq(FWA.lastIssuedSequence() - issued, vm.parseJsonUint(history, string.concat(key, ".records")),
                    string.concat("original request count at ", key));
            }
        }
        // Out-of-order callbacks can leave authenticated cached words ready.
        // Drain only through FWA's real permissionless bounded processor.
        while (FWA.unsettledAcquisitionCount() != 0) {
            uint64 before = FWA.nextSequenceToProcess();
            CompleteForeignRequests(address(FWA)).processAcquisitions(16);
            assertGt(FWA.nextSequenceToProcess(), before, "actual cached-word processing must progress");
        }
        uint256 records = vm.parseJsonUint(history, ".requests");
        assertEq(FWA.nextSequenceToProcess(), uint256(begin) + records);
        for (uint64 i = begin; i < begin + records; ++i) _assertForeign(i);
        _assertExposure();
    }

    function _threeDeadlineRefunds() internal {
        CompleteForeignRequests f = CompleteForeignRequests(address(FWA));
        address buyer = makeAddr("pack-vault-test-complete-foreign-refund-buyer");
        assertEq(buyer.code.length, 0); assertEq(buyer.balance, 0);
        vm.deal(buyer, 1 ether);
        uint64 start = FWA.nextSequenceToProcess();
        uint64 deadline;
        for (uint256 i; i < 3; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(buyer); f.acquire{value: price}(buyer, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1); f.processAcquisitions(3);
        vm.prank(buyer); f.withdrawAcquisitionRefund();
        for (uint64 i = start; i < start + 3; ++i) {
            uint8 status = FWA.acquisitions(FWA.requestIdAtSequence(i)).status;
            assertTrue(status == 3 || status == 4, "genuine deadline refund, never supplied randomness");
        }
        assertEq(FWA.nextSequenceToProcess(), uint256(begin) + 128);
    }

    function test_125SuccessfulForeignRecordsAndThreeRefundsFill128Batch() public {
        _replayForeignHistory(); _threeDeadlineRefunds();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        // A one-listing vault scans its single own position rather than walking the 128-record
        // journal: one scan clears the whole 128-record foreign backlog. Applying no own selection
        // and outside a checkpoint window, that scan earns nothing, so the minPay=1 keeper offer is
        // refused (the paid 128-record journal this test once pinned is unreachable for a small
        // vault; that journal path is reachable at >= 94 open positions, covered in ScanGas.t.sol).
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 1, _expected8);
        assertEq(vault.acquisitionCursor(), begin, "refused payment rolls back the scan progress");
        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 0, _expected9);
        assertEq(pay, 0, "foreign-only scan is unpaid");
        assertEq(vault.acquisitionCursor(), uint256(begin) + 128, "one scan clears the whole 128-record backlog");
        _assertExposure();
    }

    /// @notice A one-listing vault's largest authentic single sync is now a scan, not the journal:
    ///         it clears the full 128-record foreign backlog with a single own-position read.
    ///         Measures receipt-equivalent gas (cold state) under the normal transaction limit and
    ///         asserts it fits EIP-7825. The 128-record JOURNAL path (reachable only at >= 94 open
    ///         positions) keeps its own EIP-7825 coverage in
    ///         ScanGas.t.sol::test_full128ForeignJournalReceiptGasFitsCap; the 16 own transitions a
    ///         maximal sync could add are bounded analytically in
    ///         docs/receipts/allocation-burst-coverage.md, never measured here.
    function test_full128ForeignScanReceiptGasFitsCap() public {
        _replayForeignHistory(); _threeDeadlineRefunds();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        bytes memory input = abi.encodeCall(PackAccount.sync, (new uint256[](0), 0, uint256(0), vault.configurationHash()));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        // Receipt-equivalent: cold every contract the sync touches, as a mined transaction would.
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(keeper);
        vm.prank(keeper);
        uint256 g = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        uint256 used = g - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        emit log_named_uint("full 128-record foreign backlog scan receipt-equivalent gas", used);
        emit log_named_uint("full 128-record foreign backlog scan pay wei", abi.decode(ret, (uint256)));
        assertEq(vault.acquisitionCursor(), uint256(begin) + 128, "one scan drains the full 128-record backlog");
        _assertExposure();
        assertLt((used * 125 + 99) / 100, 16_777_216, "128-record backlog scan plus 25% keeper gas margin fits EIP-7825");
    }

    function test_125SuccessfulForeignRequiredTail() public {
        _replayForeignHistory(); _paidTail(125);
    }

    function _accountDigest(address account) private view returns (bytes32) {
        return keccak256(abi.encode(account, account.balance, vm.getNonce(account), account.code));
    }

    /// @dev Optional export of the state produced by genuine calls above. The
    /// local receipt runner imports this exact fixture state on an isolated fork;
    /// it never invents a protocol slot, acquisition result or VRF authority.
    function test_exportSuccessfulForeignReceiptFixture() public {
        vm.skip(!vm.envOr("EXPORT_COMPLETE_FOREIGN", false));
        uint256 count = vm.envOr("COMPLETE_FOREIGN_COUNT", uint256(2));
        require(count == 1 || count == 2 || count == 125 || count == 128, "supported authentic journal fixture");
        // Build every exported fixture in this test's live cache. Replaying the
        // small setup on a fresh fork avoids exporting Forge's setup overlay.
        if (count < 125) setUp();
        if (count == 1) {
            vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
            bytes32 _expected10 = TestVaultOps.configurationHash(vault);
            vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0, _expected10), 0);
        }
        if (count >= 125) _replayForeignHistory(); else _second();
        if (count == 128) _threeDeadlineRefunds();
        _requiredTail(); _assertExposure();
        string memory name = string.concat("sim/out/complete-foreign-", vm.toString(count));
        this.exportFixture(name);
    }

    function exportFixture(string memory name) external {
        require(msg.sender == address(this), "test export only");
        // Both replay paths were executed in the test body. Export that exact
        // state directly, without rewriting or inventing any protocol slot.
        bytes32 accountDigest = keccak256(abi.encode(_accountDigest(keeper), _accountDigest(holder),
            _accountDigest(address(vault)), _accountDigest(address(VaultLib))));
        vm.serializeBytes32(name, "accountDigest", accountDigest);
        vm.dumpState(string.concat(name, "-state.json"));
        vm.serializeAddress(name, "vault", address(vault));
        vm.serializeAddress(name, "keeper", keeper);
        vm.serializeAddress(name, "holder", holder);
        vm.serializeUint(name, "block", block.number);
        vm.serializeUint(name, "forkBlock", forkBlock);
        vm.serializeUint(name, "timestamp", block.timestamp);
        vm.serializeUint(name, "listing", selected);
        vm.serializeUint(name, "cursor", vault.acquisitionCursor());
        vm.serializeUint(name, "end", FWA.nextSequenceToProcess());
        vm.serializeUint(name, "escrow", vault.pendingDepositTotal());
        vm.serializeUint(name, "workFeeWei", 0);
        vm.serializeUint(name, "maxTipWei", 0.05 gwei);
        vm.serializeUint(name, "gasCeilingWei", 0.5 gwei);
        vm.serializeUint(name, "essentialCeilingWei", 2 gwei);
        string memory metadata = vm.serializeUint(name, "processing", vault.processingPool());
        vm.writeJson(metadata, string.concat(name, "-metadata.json"));
    }
}
