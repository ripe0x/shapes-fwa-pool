// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, ForceSender, IFwaAdmin} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {Charges} from "../utils/Charges.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Vm} from "forge-std/Vm.sol";

interface BatchFwaProcessor { function processAcquisitions(uint256 maxCount) external returns (uint256); }

contract ForkMaxBatchGasTest is ForkBase {
    receive() external payable {}
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function assertEssentialSpikeContext() external view {
        assertEq(block.basefee, 1.95 gwei); assertEq(tx.gasprice, 2 gwei);
    }

    function _cold() private {
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(policy);
        vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(address(SHAPES)); vm.cool(keeper);
    }

    function _measure(string memory label, bytes memory input) private returns (uint256 used) {
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        used = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        emit log_named_uint(label, used);
        if (result.length >= 32) emit log_named_uint(string.concat(label, " pay wei"), abi.decode(result, (uint256)));
        assertLt((used * 125 + 99) / 100, 16_777_216, "complete operation plus 25% keeper gas margin");
    }

    function _replay(string memory fixture, string memory leg) private {
        string memory prefix = string.concat(".26417086.", leg);
        address from = vm.parseJsonAddress(fixture, string.concat(prefix, "From"));
        address to = vm.parseJsonAddress(fixture, string.concat(prefix, "To"));
        bytes memory data = vm.parseJsonBytes(fixture, string.concat(prefix, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req") ? vm.parseJsonUint(fixture, ".26417086.reqValue") : 0;
        vm.txGasPrice(vm.parseJsonUint(fixture, string.concat(prefix, "GasPrice")));
        vm.deal(address(this), address(this).balance + value);
        vm.prank(from, from);
        (bool ok, bytes memory result) = to.call{value: value}(data);
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
    }

    function test_maximumLargePackOperationsFitTransactionCap() public {
        vm.createSelectFork("mainnet", bytes32(0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f));
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        VaultLib.Params memory p = defaultParams(); p.packUnitsMask = (uint64(1) << 30) | (uint64(1) << 3); p.reserve = 0;
        vm.deal(address(this), 50 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 20 ether);
        uint256 smallSnapshot = vm.snapshotState();
        uint256[] memory smallBuild = TestVaultOps.buildProposals(vault, 10, 3);
        _measure("restock ten small packs thirty total units complete gas", abi.encodeCall(PackVault.restock, (3, smallBuild, 0)));
        vm.prank(owner); vault.startWindDown();
        _measure("liquidate ten small packs thirty total units complete gas", abi.encodeCall(PackVault.liquidate, (16, 0)));
        assertTrue(vm.revertToState(smallSnapshot));
        setPackAsk(0.33 ether);
        uint256[] memory build = TestVaultOps.buildProposals(vault, 1, 30);
        _measure("restock one largest 30-unit pack complete gas", abi.encodeCall(PackVault.restock, (30, build, 0)));
        // Fixture construction is deliberately outside the measured operation.
        for (uint256 i = 1; i < 16; ++i) vault.restock(30, build, 0);
        uint256[] memory quotes = TestVaultOps.proposals(vault, 16, 30);
        uint256 snapshot = vm.snapshotState();
        uint256[] memory one = new uint256[](1); one[0] = quotes[0];
        _measure("list single largest pack complete gas", abi.encodeCall(PackVault.list, (one, 0)));
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory eight = new uint256[](8);
        for (uint256 i; i < 8; ++i) eight[i] = quotes[i];
        _measure("list maximum eight largest packs complete gas", abi.encodeCall(PackVault.list, (eight, 0)));
        for (uint256 i; i < 8; ++i) eight[i] = quotes[i + 8];
        vault.list(eight, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 16);

        string memory fixture = vm.readFile("test/fixtures/selection.json");
        _replay(fixture, "req");
        vm.roll(26_417_091); vm.warp(1_794_705_887);
        vm.setBlockhash(26_417_086, vm.parseJsonBytes32(fixture, ".26417086.reqBlockHash"));
        vm.fee(vm.parseJsonUint(fixture, ".26417086.fulBaseFee"));
        _replay(fixture, "ful");
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        for (uint256 i; i < ids.length; ++i) {
            (,,,,,,,,,, uint8 status) = FWA.listings(ids[i]);
            assertEq(status, 1, "real foreign selection leaves each fee-earning witness Active");
            assertGt(FWA.pendingFees(ids[i]), 0);
        }
        snapshot = vm.snapshotState();
        one[0] = ids[0];
        _measure("harvest single active debt complete gas", abi.encodeCall(PackVault.harvest, (one, 0)));
        assertTrue(vm.revertToState(snapshot));
        _measure("harvest maximum sixteen active debts complete gas", abi.encodeCall(PackVault.harvest, (ids, 0)));
        // Expire the real remaining request and enter FWA's permitted withdrawal window.
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        BatchFwaProcessor(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        toBlackout();
        vm.prank(owner); vault.startWindDown();
        snapshot = vm.snapshotState();
        _measure("unlist single largest pack complete gas", abi.encodeCall(PackVault.unlist, (one, 0)));
        assertTrue(vm.revertToState(snapshot));
        _measure("unlist maximum sixteen largest packs complete gas", abi.encodeCall(PackVault.unlist, (ids, 0)));
        assertEq(vault.openListingCount(), 0);
        _measure("liquidate maximum units from largest pack complete gas", abi.encodeCall(PackVault.liquidate, (16, 0)));
        assertEq(vault.idlePackCount(), 15);
        assertTrue(vm.revertToState(snapshot));
        setPackAsk(0.30 ether);
        for (uint256 i; i < ids.length; ++i) IFwaAdmin(address(FWA)).kickListing(ids[i]);
        assertEq(vault.pendingReceipts(), 16);
        _measure("sync maximum sixteen kicked receipts complete gas", abi.encodeCall(PackVault.sync, (0, ids, 16, 0)));
        assertEq(vault.pendingReceipts(), 0);
        assertEq(vault.reservedCount(), 0);
        assertEq(vault.idlePackCount(), 16);
        assertLe(address(vault).code.length, 24_576);
        assertLe(address(VaultLib).code.length, 24_576);
    }

    function test_maximumEightMixedPacksWithRealCrownTakeoversFitTransactionCap() public {
        this.assertGasContext();
        uint256 oldTop = FWA.topListingId();
        (, address oldDepositor,,,,,,,,,) = FWA.listings(oldTop);
        assertEq(oldDepositor.code.length, 0, "the real crown owner can directly withdraw its own listing");
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        vm.prank(oldDepositor); FWA.withdrawListing(oldTop);
        assertEq(FWA.topListingId(), 0);
        vm.prank(IOwnable(address(FWA)).owner()); IFwaAdmin(address(FWA)).setUint(16, 0);
        setPackAsk(1 ether);
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = (uint64(1) << 30) | (uint64(1) << 3); p.reserve = 0;
        vm.deal(address(this), 20 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 10 ether);
        // The stack lists 3,30,3,30,..., with each later large backing slightly higher.
        for (uint256 i; i < 4; ++i) {
            vault.restock(30, TestVaultOps.buildProposals(vault, 1, 30), 0);
            vault.restock(3, TestVaultOps.buildProposals(vault, 1, 3), 0);
        }
        uint256 small = TestVaultOps.proposals(vault, 1, 3)[0];
        uint256 large = TestVaultOps.proposals(vault, 1, 30)[0];
        assertGt(large, small);
        uint256[] memory quotes = new uint256[](8);
        for (uint256 i; i < 8; ++i) quotes[i] = (i % 2 == 0 ? small : large) + (i / 2) * 10_000;
        vm.recordLogs();
        _measure("list maximum eight mixed packs with crown takeovers complete gas", abi.encodeCall(PackVault.list, (quotes, 0)));
        Vm.Log[] memory logs = vm.getRecordedLogs();
        uint256 nonzeroCrowns;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter == address(FWA) && logs[i].topics[0] == keccak256("TopListingSet(uint256,address)")
                && uint256(logs[i].topics[1]) != 0) ++nonzeroCrowns;
        }
        assertEq(nonzeroCrowns, 5, "first admission and every larger large-pack tag take the real crown");
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 8); assertEq(FWA.topListingId(), ids[7]);
        for (uint256 i; i < ids.length; ++i) {
            (,,, uint256 pack,,,,,,, uint8 status) = FWA.listings(ids[i]);
            assertEq(status, 1);
            assertEq(PACKS.valueOf(pack), i % 2 == 0 ? 0.03 ether : 0.3 ether);
        }
    }
    function test_checkpointFullHolderMixCompleteGas() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5_000;
        vm.prank(owner); vault.setParams(p);
        uint256 deposit = Charges.grossFor(vault, 4 ether);
        vm.prank(alice); vault.deposit{value: deposit}();
        toBlackout(); checkpoint(); toOpen();
        for (uint256 i; i < 4; ++i) {
            TestVaultOps.restock(vault, 10, 3, 0);
            TestVaultOps.list(vault, 10, 0);
        }
        uint256 half = vault.shareBalance(alice) / 2;
        uint256 charge = Charges.redeemCharge(vault, half);
        vm.prank(alice); vault.requestRedeem{value: charge}(half);
        toBlackout(); checkpoint();
        assertGt(vault.lockedShares(), 0, "first fill is genuinely partial");
        uint256 firstReserve = vault.redemptionReserve();
        assertGt(firstReserve, 1 ether, "absolute first holder reserve");
        toOpen();
        vm.deal(address(this), 2 ether);
        new ForceSender{value: 1 ether}(payable(address(vault)));
        uint256 beforeSecondDeposit = vm.snapshotState();
        deposit = Charges.grossFor(vault, 1 ether);
        vm.prank(bob); vault.deposit{value: deposit}();
        toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        bytes memory input = abi.encodeCall(PackVault.checkpoint, (witness, 0));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        uint256 gross = start - gasleft() + intrinsic;
        Vm.Gas memory frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        assertGe(frame.gasRefunded, 0);
        uint256 refund = uint256(uint64(frame.gasRefunded));
        uint256 cappedRefund = refund < gross / 5 ? refund : gross / 5;
        uint256 netUpper = gross - cappedRefund;
        assertLe(netUpper, VaultLib.Q_CHECKPOINT, "fixed checkpoint gas component covers this refund-adjusted sample");
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas", gross);
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas pay wei", abi.decode(result, (uint256)));
        emit log_named_uint("checkpoint callee frame execution gas", frame.gasTotalUsed);
        emit log_named_uint("checkpoint callee frame refund counter", refund);
        emit log_named_uint("checkpoint gross minus capped frame refund, gas upper bound", netUpper);
        emit log_named_uint("checkpoint sample cost upper bound wei at matched 0.5 gwei", netUpper * 0.5 gwei);
        assertLt((gross * 125 + 99) / 100, 16_777_216);
        assertEq(vault.lockedShares(), 0, "remaining partial redemption is completed");
        assertGt(vault.redemptionReserve(), firstReserve);
        assertGt(vault.distributionReserve(), 0, "eligible gain distribution is actually reserved");
        assertGt(vault.shareBalance(bob), 0, "new deposit is priced after flows");
        assertEq(vault.pendingDepositTotal(), 0);
        uint256 protected = vault.redemptionReserve() + vault.distributionReserve() + vault.claimableTotal() + vault.processingPool();
        assertGe(address(vault).balance, protected);

        assertTrue(vm.revertToState(beforeSecondDeposit));
        p = vault.getParams(); p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei;
        vm.prank(owner); vault.setParams(p);
        vm.fee(1.95 gwei); vm.txGasPrice(2 gwei); this.assertEssentialSpikeContext();
        uint256 spikeCharge = vault.requestCharge();
        assertEq(spikeCharge, VaultLib.Q_CHECKPOINT * 2 gwei + p.workFee);
        deposit = Charges.grossFor(vault, 1 ether);
        vm.prank(bob); vault.deposit{value: deposit}();
        toBlackout(); this.assertEssentialSpikeContext();
        assertGt(vault.lockedShares(), 0, "pending redemption makes this checkpoint essential");
        assertEq(vault.processingPool(), spikeCharge);
        (uint256 routineBefore, uint256 essentialBefore) = vault.budget();
        uint256 keeperBefore = keeper.balance;
        witness = TestVaultOps.witness(vault);
        _measure("essential spike full-holder checkpoint complete gas", abi.encodeCall(PackVault.checkpoint, (witness, 0)));
        assertEq(keeper.balance - keeperBefore, spikeCharge, "essential ceiling is funded by the actual request charge");
        (uint256 routineAfter, uint256 essentialAfter) = vault.budget();
        assertEq(routineAfter, routineBefore); assertEq(essentialAfter, essentialBefore);
        assertEq(vault.processingPool(), 0); assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.lockedShares(), 0); assertGt(vault.shareBalance(bob), 0);
        protected = vault.redemptionReserve() + vault.distributionReserve() + vault.claimableTotal();
        assertGe(address(vault).balance, protected);
    }

}
