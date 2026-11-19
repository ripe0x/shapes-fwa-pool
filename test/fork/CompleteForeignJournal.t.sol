// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SelectionBase} from "./ForkSelection.t.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
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
        Candidate memory c = late();
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
        VaultLib.Params memory p;
        p.minEdgeBps = 100; p.payMarkupBps = 1_000; p.maxTip = 0.05 gwei; p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200; p.packUnitsMask = uint64(1) << 3;
        p.gasCeiling = 50 gwei; p.essentialCeiling = 50 gwei;
        p.tvlCap = 100 ether; p.routineCap = 0.3 ether; p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether; p.essentialRate = 0.005 ether;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 3 ether);
        TestVaultOps.restock(vault, 1, 3, 0);
        TestVaultOps.list(vault, 1, 0);
        selected = vault.openListingAt(0);
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei; p.payMarkupBps = 0;
        vm.prank(owner); vault.setParams(p);
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
        vm.prank(holder); vault.deposit{value: amount}();
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
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 1);
        assertEq(pay, (VaultLib.Q_REQUIRED_TAIL + records * VaultLib.Q_JOURNAL) * 0.2 gwei);
        assertEq(keeper.balance - before, pay);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertEq(vault.pendingDepositTotal(), escrow, "journal payment cannot consume deposit escrow");
        assertEq(vault.processingPool(), processing, "journal payment cannot consume checkpoint charges");
        _assertExposure();
        vm.expectRevert(VaultLib.Nothing.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 0);
        vm.prank(keeper); vault.checkpoint(selected, 0);
        assertGt(vault.shareBalance(holder), 0, "holder checkpoint succeeds after real successful catchup");
    }

    function test_successfulForeignSingletonRequiredTail() public {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0), 0);
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
        vm.expectRevert(VaultLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 1);
        assertEq(vault.acquisitionCursor(), begin, "refused payment rolls back journal progress");
        uint256 before = address(vault).balance;
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0), 0);
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
        vm.prank(keeper); uint256 pay = vault.sync(new uint256[](0), 0, 1);
        assertEq(pay, (VaultLib.Q_SYNC + 128 * VaultLib.Q_JOURNAL) * 0.2 gwei);
        assertEq(vault.acquisitionCursor(), uint256(begin) + 128);
        _assertExposure();
    }

    /// @notice The largest authentically reachable single sync (goal 2 base / goal 3): a full
    ///         128-record foreign journal in one call. Measures receipt-equivalent gas (cold
    ///         state) under the normal transaction limit and asserts the keeper's padded estimate
    ///         fits EIP-7825. The 16 own transitions a maximal sync could add are not authentically
    ///         reachable (no real VRF burst selects 17 vault listings); their gas is bounded
    ///         analytically in docs/receipts/allocation-burst-coverage.md, never measured here.
    function test_full128ForeignJournalSyncReceiptGasFitsCap() public {
        _replayForeignHistory(); _threeDeadlineRefunds();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), 0, uint256(1)));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        // Receipt-equivalent: cold every contract the sync touches, as a mined transaction would.
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(vault.keeperPolicy()));
        vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(keeper);
        vm.prank(keeper);
        uint256 g = gasleft();
        (bool ok, bytes memory ret) = address(vault).call(input);
        uint256 used = g - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(ret, 32), mload(ret)) }
        emit log_named_uint("full 128-record foreign journal sync receipt-equivalent gas", used);
        emit log_named_uint("full 128-record foreign journal sync pay wei", abi.decode(ret, (uint256)));
        assertEq(vault.acquisitionCursor(), uint256(begin) + 128, "one call drains the full 128-record journal");
        _assertExposure();
        assertLt((used * 125 + 99) / 100, 16_777_216, "128-record journal plus 25% keeper gas margin fits EIP-7825");
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
            vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0), 0);
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
            _accountDigest(address(vault)), _accountDigest(address(vault.keeperPolicy())), _accountDigest(address(VaultLib))));
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
        vm.serializeUint(name, "payMarkupBps", 0);
        vm.serializeUint(name, "maxTipWei", 0.05 gwei);
        vm.serializeUint(name, "gasCeilingWei", 0.5 gwei);
        vm.serializeUint(name, "essentialCeilingWei", 2 gwei);
        string memory metadata = vm.serializeUint(name, "processing", vault.processingPool());
        vm.writeJson(metadata, string.concat(name, "-metadata.json"));
    }
}
