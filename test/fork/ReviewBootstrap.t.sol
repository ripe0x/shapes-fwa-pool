// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {IFWAV2} from "../../src/interfaces/External.sol";

interface ReviewFwaQueue {
    function processAcquisitions(uint256 count) external;
    function acquisitionMeta(uint256 request) external view returns (uint64, uint64, uint64, uint16, uint16, uint256);
}

contract ReviewBootstrapTest is ForkBase {
    function setUp() public override {
        vm.createSelectFork("mainnet", 26_400_000);
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0); assertEq(actors[i].balance, 0);
        }
        VaultLib.Params memory p = defaultParams();
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei; p.payMarkupBps = 0;
        p.reserve = 0.005 ether; p.tvlCap = 2 ether;
        p.routineCap = 0.03 ether; p.routineRate = 0.0008 ether;
        p.essentialCap = 0; p.essentialRate = 0;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
    }

    function assertGasContext() external {
        assertEq(block.basefee, 0.45 gwei); assertEq(tx.gasprice, 0.5 gwei);
    }

    function _drainActualRequests() private {
        for (uint256 pass; FWA.unsettledAcquisitionCount() != 0 && pass < 128; ++pass) {
            uint64 cursor = FWA.nextSequenceToProcess();
            uint64 last = FWA.lastIssuedSequence();
            uint256 deadline;
            for (uint64 seq = cursor; seq <= last && seq < cursor + 16; ++seq) {
                uint256 request = FWA.requestIdAtSequence(seq);
                if (FWA.acquisitions(request).status == 1) {
                    (, uint64 until,,,,) = ReviewFwaQueue(address(FWA)).acquisitionMeta(request);
                    if (until > deadline) deadline = until;
                }
            }
            if (deadline >= block.number) {
                uint256 advance = deadline + 1 - block.number;
                assertLe(advance, 7_201, "actual snapshotted protocol timeout");
                vm.roll(block.number + advance); vm.warp(block.timestamp + advance * 12);
            }
            ReviewFwaQueue(address(FWA)).processAcquisitions(16);
        }
        assertEq(FWA.unsettledAcquisitionCount(), 0);
    }

    function _historicalBacklog() private returns (uint64 begin) {
        begin = vault.acquisitionCursor();
        vm.makePersistent(address(vault)); vm.makePersistent(address(vault.keeperPolicy()));
        vm.makePersistent(address(VaultLib));
        vm.rollFork(BLOCK + 10_000);
        assertEq(keeper.code.length, 0); assertEq(keeper.balance, 0);
        assertEq(alice.code.length, 0); assertEq(alice.balance, 0);
        vm.deal(keeper, 1 ether); vm.deal(alice, 2 ether);
        vm.fee(0.45 gwei); vm.txGasPrice(0.5 gwei); this.assertGasContext();
        assertGe(FWA.nextSequenceToProcess(), uint256(begin) + 576, "at least36 real full batches");
        assertEq(FWA.feeCredit(address(vault)), 0, "no external credit recapitalizes the seed");
        return begin;
    }

    function test_realForeignBacklogPreservesMinimumSeedAndFirstDeposit() public {
        uint256 seed = address(vault).balance;
        uint64 begin = _historicalBacklog();
        for (uint64 seq = begin; seq < begin + 576; ++seq) {
            IFWAV2.Acquisition memory a = FWA.acquisitions(FWA.requestIdAtSequence(seq));
            assertTrue(a.status == 2 || a.status == 3 || a.status == 4);
            if (a.status == 2) {
                (, address depositor,,,,,,,,,) = FWA.listings(a.listingId);
                assertTrue(depositor != address(vault), "authentic foreign selection");
            }
        }
        uint256 totalPay;
        while (vault.acquisitionCursor() < FWA.nextSequenceToProcess()) {
            vm.prank(keeper); totalPay += vault.sync(new uint256[](0), 0, 0);
        }
        emit log_named_uint("authentic completed records", vault.acquisitionCursor() - begin);
        emit log_named_uint("remaining bootstrap cash before first deposit", address(vault).balance);
        emit log_named_uint("foreign catchup pay", totalPay);
        toBlackout(); _drainActualRequests();
        vm.fee(0.45 gwei); vm.txGasPrice(0.5 gwei); this.assertGasContext();
        while (vault.acquisitionCursor() < FWA.nextSequenceToProcess()) {
            vm.prank(keeper); totalPay += vault.sync(new uint256[](0), 0, 0);
        }
        uint256 escrow = 0.1 ether;
        uint256 ck = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: escrow + ck}();
        assertEq(vault.pendingDepositTotal(), escrow);
        assertEq(vault.processingPool(), ck);
        vm.prank(keeper); vault.checkpoint(0, 0);
        assertEq(totalPay, 0, "unexposed history cannot consume bootstrap capital");
        assertGe(vault.lastNav(), seed + escrow, "seed and deposit value remain priced");
        assertGt(vault.shareBalance(alice), 0);
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
    }

    function test_firstCheckpointAdvancesUnexposedHistoryWithoutStandaloneSync() public {
        uint256 seed = address(vault).balance;
        uint64 beforeCursor = _historicalBacklog();
        toBlackout(); _drainActualRequests();
        vm.fee(0.45 gwei); vm.txGasPrice(0.5 gwei); this.assertGasContext();
        vm.expectRevert(VaultLib.CatchUpFirst.selector);
        vault.accountedNav(0);
        uint256 ck = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: 0.1 ether + ck}();
        assertEq(vault.acquisitionCursor(), beforeCursor, "deposit does not pretend exposure history is current");
        uint256 beforeGas = gasleft();
        vm.prank(keeper); uint256 pay = vault.checkpoint(0, 0);
        uint256 used = beforeGas - gasleft();
        emit log_named_uint("bootstrap checkpoint call gas, excluding intrinsic", used);
        assertLe(used, VaultLib.Q_CHECKPOINT, "shared fixed checkpoint charge covers automatic empty-history advance");
        assertEq(pay, ck, "only the existing shared request charge funds checkpoint");
        assertEq(address(vault).balance, seed + 0.1 ether);
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertGt(vault.shareBalance(alice), 0);
        assertEq(vault.pendingDepositTotal(), 0);
    }


    function test_unexposedAdvanceIsUnpaidAtomicAndIndependentOfReserve() public {
        uint64 beforeCursor = _historicalBacklog();
        uint256 seed = address(vault).balance;
        assertEq(owner.code.length, 0); assertEq(owner.balance, 0);
        vm.deal(owner, 1 ether);
        VaultLib.Params memory p = vault.getParams(); p.reserve = 0;
        vm.prank(owner); vault.setParams(p);
        vm.expectRevert(VaultLib.Payment.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 1);
        assertEq(vault.acquisitionCursor(), beforeCursor, "minPay refusal reverts the cursor advance");
        uint256 beforeKeeper = keeper.balance;
        vm.prank(keeper); assertEq(vault.sync(new uint256[](0), 0, 0), 0);
        assertEq(keeper.balance, beforeKeeper);
        assertEq(address(vault).balance, seed, "zero reserve does not allow bootstrap depletion");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        vm.expectRevert(VaultLib.Nothing.selector);
        vm.prank(keeper); vault.sync(new uint256[](0), 0, 0);
    }

}
