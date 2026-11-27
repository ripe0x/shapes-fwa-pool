// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {IFWAV2} from "../../src/interfaces/External.sol";

interface ReviewFWAProcessor {
    function processAcquisitions(uint256 maxCount) external;
    function quoteAcquisitionPrice() external view returns (uint256, uint256, uint256);
    function acquire(address,uint256,uint256,uint256,uint256) external payable;
    function acquisitionMeta(uint256) external view returns (uint64,uint64,uint64,uint16,uint16,uint256);
    function withdrawAcquisitionRefund() external;
}

/// @dev Real historical journal and actual new expired requests, with priced cash-only holder rights.
contract ReviewJournalTest is ForkBase {
    function setUp() public override {
        super.setUp();
        VaultLib.Params memory p = defaultParams();
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei;
        p.reserve = 0.005 ether; p.routineCap = 0.1 ether; p.routineRate = 0.005 ether;

        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
    }

    function assertEnvironment() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function _advance() private returns (uint64 begin, uint64 end) {
        begin = vault.acquisitionCursor();
        vm.makePersistent(address(vault)); vm.makePersistent(address(VaultLib));
        vm.rollFork(BLOCK + 10_000);
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0); assertEq(actors[i].balance, 0);
            vm.deal(actors[i], 5 ether);
        }
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertEnvironment();
        end = FWA.nextSequenceToProcess();
        assertGe(end - begin, 16, "authentic completed history");
    }

    function _intrinsic(bytes memory input) private pure returns (uint256 gas_) {
        gas_ = 21_000;
        for (uint256 i; i < input.length; ++i) gas_ += input[i] == 0 ? 4 : 16;
    }

    function _measure(uint256 n) private returns (uint256 gross, uint256 pay, int64 refund) {
        bytes memory input = abi.encodeCall(PackAccount.sync, (new uint256[](0), 0, 0, vault.configurationHash()));
        uint256 intrinsic = _intrinsic(input);
        uint256 before = keeper.balance;
        vm.cool(address(vault)); vm.cool(address(FWA)); vm.cool(address(VaultLib));
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        gross = start - gasleft() + intrinsic;
        refund = vm.lastCallGas().gasRefunded;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        pay = abi.decode(result, (uint256));
        assertEq(keeper.balance - before, pay);
        assertLe((gross * 5 + 3) / 4, 16_777_216);
    }

    function _holderCall(bytes memory input, uint256 value) private returns (uint256 gross) {
        uint256 intrinsic = _intrinsic(input);
        vm.cool(address(vault)); vm.cool(address(FWA)); vm.cool(address(VaultLib));
        vm.prank(alice);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call{value:value}(input);
        gross = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        assertLe((gross * 5 + 3) / 4, 16_777_216);
    }

    function test_cashOnlyHistoryRebasesWithoutMaintenanceExpense() public {
        uint256 gross = vault.requestCharge() + 2 ether;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: gross}(_expected0);
        toBlackout(); checkpoint();
        (uint64 begin, uint64 end) = _advance();
        assertGt(end, begin);
        uint256 cash = address(vault).balance;
        (uint256 used, uint256 pay,) = _measure(1);
        assertEq(pay, 0); assertEq(address(vault).balance, cash);
        assertEq(vault.acquisitionCursor(), end, "provably unexposed rebase reaches real completed prefix");
        emit log_named_uint("cash-only real historical records skipped unpaid", end - begin);
        emit log_named_uint("unpaid rebase caller meter plus intrinsic proxy", used);
    }

    function test_realMixedHistoryCashOnlyExitWithZeroEssentialBudget() public {
        uint256 gross = vault.requestCharge() + 2 ether;
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: gross}(_expected1);
        toBlackout(); checkpoint();
        (uint64 begin,) = _advance();
        toOpen();
        ReviewFWAProcessor processor = ReviewFWAProcessor(address(FWA));
        uint64 first = FWA.lastIssuedSequence() + 1;
        uint64 deadline;
        for (uint256 i; i < 16; ++i) {
            (,, uint256 price) = processor.quoteAcquisitionPrice();
            vm.prank(bob); processor.acquire{value: price}(bob, 1, 0, 0, 10000);
            uint256 request = FWA.requestIdAtSequence(first + uint64(i));
            (,uint64 actualDeadline,,,,) = processor.acquisitionMeta(request);
            if (actualDeadline > deadline) deadline = actualDeadline;
        }
        vm.roll(uint256(deadline) + 1);
        vm.prank(bob); processor.processAcquisitions(16);
        vm.prank(bob); processor.withdrawAcquisitionRefund();
        uint64 end = FWA.nextSequenceToProcess();
        uint256 successful;
        uint256 refunded;
        for (uint64 i = begin; i < end; ++i) {
            IFWAV2.Acquisition memory a = FWA.acquisitions(FWA.requestIdAtSequence(i));
            if (a.status == 2) { ++successful; assertEq(vault.position(a.listingId).value, 0); }
            else { assertTrue(a.status == 3 || a.status == 4); ++refunded; }
        }
        assertGt(successful, 0); assertGe(refunded, 16);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        uint256 shares = vault.shareBalance(alice);
        uint256 charge = vault.requestCharge();
        uint256 expectedPrincipal = vault.lastNav() * shares / vault.totalShares();
        uint256 holderGross = _holderCall(abi.encodeCall(PackVault.requestRedeem, (shares, vault.configurationHash())), charge);
        assertGt(vault.lockedShares(), 0);
        uint256 routineBefore = vault.budget();
        assertGt(routineBefore, 0);
        uint256 cash = address(vault).balance;
        (uint256 used, uint256 pay,) = _measure(16);
        assertEq(pay, 0); assertEq(address(vault).balance, cash);
        assertEq(vault.acquisitionCursor(), end);
        toBlackout();
        holderGross += used;
        holderGross += _holderCall(abi.encodeCall(PackVault.checkpoint, (0, 0, vault.configurationHash())), 0);
        uint256 before = alice.balance;
        holderGross += _holderCall(abi.encodeCall(PackVault.claim, ()), 0);
        uint256 claimed = alice.balance - before;
        assertEq(vault.lockedShares(), 0); assertEq(vault.shareBalance(alice), 0);
        assertEq(vault.claimableEth(alice), 0);
        assertApproxEqAbs(claimed, expectedPrincipal, 2, "priced holder share of actual free capital");
        assertGt(claimed, 1.99 ether);
        uint256 routineAfter = vault.budget();
        assertGe(routineAfter, routineBefore);
        emit log_named_uint("actual successful foreign backlog", successful);
        emit log_named_uint("actual refunded backlog", refunded);
        emit log_named_uint("cash-only backlog rebase caller meter plus intrinsic proxy", used);
        emit log_named_uint("rebase caller meter cost proxy wei at 0.2gwei", used * 0.2 gwei);
        emit log_named_uint("request rebase checkpoint claim caller meter plus intrinsic proxy", holderGross);
        emit log_named_uint("full holder-call gas proxy wei at 0.2gwei", holderGross * 0.2 gwei);
        emit log_named_uint("actual claimed wei", claimed);
    }
}
