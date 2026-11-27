// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MeasuredPay} from "../utils/MeasuredPay.sol";

import {GasQuotes} from "../utils/GasQuotes.sol";

import {Vm} from "forge-std/Vm.sol";
import {IFWAToken, IFWAV2} from "../../src/interfaces/External.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {ForkBase, IFwaAdmin, IOwnable, IOracleAdmin} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
interface ProductionTokenBid {
    function acceptBidAsTokens(uint256 id, uint256 minOut) external returns (uint256);
    function tokenSettlementDiscountBps() external view returns (uint256);
}

interface ProductionOracleExempt { function setOracleExemptCollection(address collection, bool exempt) external; }

interface ProductionGiftPacks {
    function addToPack(uint256 packId, uint256[] calldata shapeIds, uint32[] calldata mintCounts) external payable;
}

/// @dev This suite uses deployed PackVault, never a subclass or receipt instrumented substitute.
contract ForkProductionReceiptsTest is SelectionBase {
    uint256 private fee = 100;
    receive() external payable {}

    function _beforeSelectionDeploy() internal override {
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(19, fee);
        assertEq(FWA.ownerSettlementFeeBps(), fee);
    }

    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function _environment() internal {
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
    }

    function _one(uint256 id) private pure returns (uint256[] memory ids) {
        ids = new uint256[](1); ids[0] = id;
    }

    function _cold() private {
        vm.cool(address(vault)); vm.cool(address(FWA)); vm.cool(address(PACKS));
    }

    function _assertReceipt(uint256 id, uint256 amount, uint256 atFee, uint256 kind) private view {
        VaultLib.Receipt memory r = vault.receipts(id);
        assertTrue(r.initialized, "live identifier has prepared storage");
        assertEq(r.amount, amount);
        assertEq(r.feeBps, atFee, "retain payment-time fee");
        assertEq(r.kind, kind);
    }

    function _catchUp(uint256[] memory ids) private {
        while (vault.acquisitionCursor() < FWA.nextSequenceToProcess()) {
            bytes32 _expected0 = TestVaultOps.configurationHash(vault);
            vault.sync(new uint256[](0), 0, 0, _expected0);
        }
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        if (ids.length != 0) vault.sync(ids, 0, 0, _expected1);
    }

    function _drain() private {
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        _environment();
    }

    function _keep(uint256 atFee) private {
        fee = atFee;
        _select(primary());
        _environment();
        uint256 before = address(vault).balance;
        uint256 expected = B * (10_000 - atFee) / 10_000;
        _cold();
        vm.prank(primary().purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        _assertReceipt(selected, expected, atFee, 1);
        assertEq(vault.pendingReceipts(), 1);
        assertEq(address(vault).balance - before, expected, "absolute ordinary keep payout");
        emit log_named_uint("production vault runtime bytes", address(vault).code.length);
    }

    function test_productionColdKeepFee0() public { _keep(0); }
    function test_productionColdKeepFee100() public { _keep(100); }
    function test_productionColdKeepFee500() public { _keep(500); }

    function test_receiptBeforeJournalBlocksPricingAndSyncOrdersReconciliation() public {
        _keep(100);
        uint64 cursor = vault.acquisitionCursor();
        vm.expectRevert(VaultLib.CatchUpFirst.selector);
        vault.accountedNav(0);
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(_one(selected), 0, type(uint256).max, _expected2);
        assertEq(vault.acquisitionCursor(), cursor);
        assertEq(vault.pendingReceipts(), 1);
        assertEq(vault.idForBacking(B), selected);
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vault.sync(_one(selected), 0, 0, _expected3);
        assertGt(vault.acquisitionCursor(), cursor, "journal precedes terminal reconciliation in the same job");
        assertEq(vault.pendingReceipts(), 0);
        assertEq(vault.idForBacking(B), 0);
        (uint256 tracked, uint256 idle,,, , uint256 allocated) = vault.totals();
        assertEq(tracked, 0, "the kept pack leaves no inventory (direct-mint has no loose remainder)");
        assertEq(idle, 0);
        assertEq(allocated, 0);
        uint256 nav = vault.accountedNav(0);
        assertEq(nav, address(vault).balance + FWA.feeCredit(address(vault)));
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.sync(_one(selected), 0, 0, _expected4);
        assertEq(vault.accountedNav(0), nav);
    }

    function test_mutatingCheckpointCannotSkipUnseenOwnSelectionAndReceipt() public {
        _keep(100);
        _drain();
        uint256 next = block.timestamp - block.timestamp % 12 hours + 11 hours + 46 minutes;
        if (next <= block.timestamp) next += 12 hours;
        vm.warp(next); _environment();
        assertTrue(FWA.isPurchaseBlackout());
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        address holder = makeAddr("pack-vault-test-unsynced-checkpoint-holder");
        assertEq(holder.code.length, 0); assertEq(holder.balance, 0);
        uint256 charge = vault.requestCharge();
        vm.deal(holder, 0.1 ether + charge);
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(holder); vault.deposit{value: 0.1 ether + charge}(_expected5);
        uint64 cursor = vault.acquisitionCursor();
        uint256 open = vault.openListingCount();
        uint256 reserved = vault.reservedCount();
        uint256 balance = address(vault).balance;
        uint256 interval = vault.lastCheckpointInterval();
        assertEq(vault.pendingReceipts(), 1);
        assertEq(vault.position(selected).state, VaultLib.ACTIVE, "own selection has not reached the book");
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.CatchUpFirst.selector);
        vault.checkpoint(0, 0, _expected6);
        assertEq(vault.acquisitionCursor(), cursor);
        assertEq(vault.pendingReceipts(), 1);
        assertEq(vault.openListingCount(), open);
        assertEq(vault.reservedCount(), reserved);
        assertEq(vault.idForBacking(B), selected);
        assertEq(address(vault).balance, balance);
        assertEq(vault.pendingDepositTotal(), 0.1 ether);
        assertEq(vault.processingPool(), charge);
        assertEq(vault.lastCheckpointInterval(), interval);
        _catchUp(_one(selected));
        assertEq(vault.pendingReceipts(), 0);
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(0, 0, _expected7);
        assertGt(vault.shareBalance(holder), 0, "authenticated reconciliation opens the same checkpoint window");
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.processingPool(), 0);
    }

    function test_bidReturnPreservesFloorBeforeInventorySyncAndReusesIdentifierAfterRetirement() public {
        _select(primary()); _environment();
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected8);
        address buyer = primary().purchaser;
        uint256 before = buyer.balance;
        vm.prank(buyer); IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        assertEq(buyer.balance - before, B * 9_000 / 10_000);
        assertEq(vault.pendingReceipts(), 0);
        assertEq(vault.idlePackCount(), 0, "custody alone does not retire the old position");
        assertEq(vault.idForBacking(B), selected);
        (uint256 tracked, uint256 idle,,,, uint256 allocated) = vault.totals();
        assertEq(tracked, 0.06 ether); assertEq(idle, 0); assertEq(allocated, 0.06 ether);
        assertEq(vault.accountedNav(0), address(vault).balance + 0.06 ether + FWA.feeCredit(address(vault)), "unsynced bid return cannot raise NAV");
        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vault.sync(_one(selected), 0, 0, _expected9);
        assertEq(vault.idForBacking(B), 0);
        assertEq(vault.idlePackCount(), 1);
        (tracked, idle,,,, allocated) = vault.totals();
        assertEq(tracked, 0.06 ether); assertEq(idle, 0.06 ether); assertEq(allocated, 0);
        _drain();
        VaultLib.Params memory relistParams = vault.getParams();
        relistParams.backingRatioBps = uint32(B * 10_000 / 0.06 ether);
        bytes32 relistConfig = vault.configurationHash();
        vm.prank(vault.owner()); vault.setParams(relistParams, relistConfig);
        uint256[] memory proposed = new uint256[](1); proposed[0] = B;
        bytes32 _expected10 = TestVaultOps.configurationHash(vault);
        vault.list(proposed, 0, _expected10);
        uint256 fresh = vault.openListingAt(0);
        assertTrue(fresh != selected);
        assertEq(vault.idForBacking(B), fresh);
        assertTrue(vault.receipts(fresh).initialized);
        assertEq(vault.receipts(fresh).kind, 0);
    }

    function test_realTokenBidReturnsPackPreservesPrincipalAndCreatesNoEthReceipt() public {
        _select(primary()); _environment();
        bytes32 _expected11 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected11);
        address buyer = primary().purchaser;
        IFWAToken rewardToken = IFWAToken(FWA.token());
        uint256 buyerBefore = rewardToken.balanceOf(buyer);
        uint256 vaultEth = address(vault).balance;
        uint256 fwaEth = address(FWA).balance;
        uint256 payout = B * ProductionTokenBid(address(FWA)).tokenSettlementDiscountBps() / 10_000;
        (,,, uint256 pack,,,,,,,) = FWA.listings(selected);
        vm.recordLogs();
        vm.prank(buyer);
        uint256 bought = ProductionTokenBid(address(FWA)).acceptBidAsTokens(selected, 0);
        assertGt(bought, 0, "real initialized pool supplies actual FWA tokens");
        emit log_named_uint("token bid actual ETH input wei", payout);
        emit log_named_uint("token bid actual FWA tokens out raw", bought);
        assertEq(rewardToken.balanceOf(buyer) - buyerBefore, bought);
        assertEq(fwaEth - address(FWA).balance, payout, "absolute native ETH spent through real rewards/pool route");
        assertEq(address(vault).balance, vaultEth);
        assertEq(vault.pendingReceipts(), 0, "token bid must not invent a vault ETH keep receipt");
        assertEq(PACKS.ownerOf(pack), address(vault));
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bool identified;
        bytes32 signature = keccak256("DepositorBidAcceptedAsTokens(uint256,address,address,uint256,uint256,uint256)");
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter != address(FWA) || logs[i].topics[0] != signature) continue;
            assertEq(uint256(logs[i].topics[1]), selected);
            (uint256 paid, uint256 retained, uint256 tokens) = abi.decode(logs[i].data, (uint256, uint256, uint256));
            assertEq(paid, payout); assertEq(retained, B - payout); assertEq(tokens, bought);
            identified = true;
        }
        assertTrue(identified, "authenticated actual token-bid outcome");
        assertEq(vault.accountedNav(0), vaultEth + 0.06 ether + FWA.feeCredit(address(vault)), "token route preserves the same conservative principal");
        bytes32 _expected12 = TestVaultOps.configurationHash(vault);
        vault.sync(_one(selected), 0, 0, _expected12);
        (uint256 tracked, uint256 idle,,,, uint256 allocated) = vault.totals();
        assertEq(tracked, 0.06 ether); assertEq(idle, tracked); assertEq(allocated, 0);
        assertEq(vault.idForBacking(B), 0);
        assertEq(vault.accountedNav(0), address(vault).balance + 0.06 ether + FWA.feeCredit(address(vault)));
    }

    function test_burnedKeptPackCanStillConsumeReceipt() public {
        _keep(100);
        (,,, uint256 pack,,,,,,,) = FWA.listings(selected);
        vm.prank(primary().purchaser);
        PACKS.redeem(pack);
        _catchUp(_one(selected));
        assertEq(vault.pendingReceipts(), 0);
        (uint256 tracked,,,,,) = vault.totals();
        assertEq(tracked, 0, "no loose remainder after a kept pack is redeemed by its purchaser");
    }

    function test_extendedKeptGiftAdoptsActualBackingOnce() public {
        _keep(100);
        address buyer = primary().purchaser;
        (,,, uint256 pack,,,,,,,) = FWA.listings(selected);
        uint32[] memory counts = new uint32[](9); counts[0] = 1;
        uint256 cost = 0.01 ether + SHAPES.mintFee();
        vm.deal(buyer, buyer.balance + cost);
        vm.startPrank(buyer);
        ProductionGiftPacks(address(PACKS)).addToPack{value: cost}(pack, new uint256[](0), counts);
        PACKS.transferFrom(buyer, address(vault), pack);
        vm.stopPrank();
        assertEq(PACKS.valueOf(pack), 0.07 ether);
        _catchUp(_one(selected));
        (uint256 tracked, uint256 idle,,,,) = vault.totals();
        assertEq(tracked, 0.07 ether, "the kept six-unit pack extended by one gift unit");
        assertEq(idle, tracked);
        assertEq(vault.idForBacking(B), 0);
        uint256 before = vault.accountedNav(0);
        bytes32 _expected13 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.sync(_one(selected), 0, 0, _expected13);
        assertEq(vault.accountedNav(0), before);
    }

    function test_oversizedKeptGiftRecoversInBoundedChunksWithoutBlockingNormalInventory() public {
        _keep(100);
        address buyer = primary().purchaser;
        (,,, uint256 pack,,,,,,,) = FWA.listings(selected);
        uint32[] memory counts = new uint32[](9); counts[0] = 28;
        uint256 cost = 28 * (0.01 ether + SHAPES.mintFee());
        vm.deal(buyer, buyer.balance + cost);
        vm.startPrank(buyer);
        ProductionGiftPacks(address(PACKS)).addToPack{value: cost}(pack, new uint256[](0), counts);
        PACKS.transferFrom(buyer, address(vault), pack);
        vm.stopPrank();
        _catchUp(_one(selected));
        assertEq(vault.recoveryPackCount(), 1);
        assertEq(vault.idlePackCount(), 0);
        (uint256 tracked, uint256 idle,,,,) = vault.totals();
        assertEq(tracked, 0.34 ether); assertEq(idle, tracked);
        assertEq(vault.unwindCharge(), 0, "exits are unpaid, so there is no unwind charge");
        _drain();
        TestVaultOps.restock(vault, 1, UNITS, 0); // build lists it at once
        assertEq(vault.openListingCount(), 1, "oversized gift does not occupy normal stack");
        uint256 ordinaryId = vault.openListingAt(0);
        address vaultOwner = vault.owner();
        vm.prank(vaultOwner); vault.startWindDown();
        // The 30-Shape gift pack (one 0.05 and twenty-nine 0.01) unseals and burns in one bounded
        // chunk (MAX_REDEEM_SHAPES = 30), recovering its whole 0.34 ETH without blocking the fresh
        // listed pack.
        pack; // the recovery pack id, no longer asserted per-chunk
        uint256 before = address(vault).balance;
        _cold();
        uint256 start = gasleft();
        bytes32 _expected14 = TestVaultOps.configurationHash(vault);
        vm.recordLogs();
        uint256 paid = vault.liquidate(16, 0, _expected14);
        uint256 used = start - gasleft() + 21_000;
        emit log_named_uint("recovery thirty Shapes complete gas", used);
        emit log_named_uint("recovery thirty Shapes pay wei", paid);
        assertLt(used * 125 / 100, 16_777_216);
        assertEq(address(vault).balance + paid - before, 0.34 ether, "the whole gift pack recovers in one chunk");
        assertEq(paid, 0, "recovery is exit work and pays the keeper nothing");
        assertEq(vault.recoveryPackCount(), 0);
        (tracked, idle,,,,) = vault.totals();
        assertEq(tracked, 0.06 ether, "only the new listed six-unit pack remains");
        assertEq(idle, 0);
        vm.warp(vm.getBlockTimestamp() + 13 hours);
        paid += vault.unlist(_one(ordinaryId), 0, vault.configurationHash());
        paid += vault.liquidate(16, 0, vault.configurationHash());
        assertEq(vault.openListingCount() + vault.idlePackCount() + vault.recoveryPackCount(), 0);
        assertEq(paid, 0, "every mixed ordinary and oversized-gift exit call is unpaid");
    }

    function test_feeChangeDoesNotReinterpretReceipt() public {
        _keep(100);
        _drain();
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(19, 500);
        _assertReceipt(selected, B * 9_900 / 10_000, 100, 1);
        _catchUp(_one(selected));
        assertEq(vault.pendingReceipts(), 0);
    }

    function test_realRefundedForeignTailDoesNotEarnImmediateCompensation() public {
        _select(primary());
        _pendForeignAcquisition(); // a real foreign request that the drain below refunds unfulfilled
        _environment();
        bytes32 _expected15 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected15);
        _drain();
        uint64 cursor = vault.acquisitionCursor();
        uint64 completed = FWA.nextSequenceToProcess();
        assertGt(completed, cursor, "real completed foreign prefix awaits journaling");
        uint256 request = FWA.requestIdAtSequence(cursor);
        IFWAV2.Acquisition memory a = FWA.acquisitions(request);
        assertTrue(a.status == 3 || a.status == 4, "real abandoned request was refunded through FWA");
        uint256 before = address(vault).balance;
        bytes32 _expected16 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(new uint256[](0), 0, 1, _expected16);
        assertEq(vault.acquisitionCursor(), cursor);
        _cold();
        vm.cool(address(VaultLib));
        uint256 start = gasleft();
        bytes32 _expected17 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), 0, 0, _expected17);
        uint256 used = start - gasleft() + 21_000;
        assertEq(before - address(vault).balance, paid);
        assertEq(paid, 0, "unrelated short tails wait for a qualified job");
        assertEq(vault.acquisitionCursor(), completed, "the unpaid journal clears the whole completed foreign prefix");
        emit log_named_uint("refunded foreign prefix complete gas", used);
        emit log_named_uint("refunded foreign prefix pay wei", paid);
    }

    function test_terminalReconciliationPrunesItsHeadWithoutAnotherPaidCall() public {
        _select(primary());
        _pendForeignAcquisition(); // a foreign refund the post-drain journal sync clears for free
        _environment();
        vm.prank(primary().purchaser); IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint64 cursor = vault.acquisitionCursor();
        uint256 creditBefore = FWA.feeCredit(address(vault));
        bytes32 _expected18 = TestVaultOps.configurationHash(vault);
        vm.recordLogs();
        uint256 paid = vault.sync(_one(selected), 0, 0, _expected18);
        uint256 processed = vault.acquisitionCursor() - cursor;
        // At this selection the fee credit is large enough that the sync economically sweeps it into
        // the vault (withdrawEarnings), adding Q_CREDIT to the quote (D56). Priced from the on-chain
        // fact, not assumed: the terminal reconciliation and its bounded head cleanup are the rest.
        uint256 swept = creditBefore != 0 && FWA.feeCredit(address(vault)) == 0 ? GasQuotes.Q_CREDIT : 0;
        assertEq(paid, MeasuredPay.gross(vault, GasQuotes.Q_SYNC + processed * GasQuotes.Q_JOURNAL + GasQuotes.Q_SELECTED
            + GasQuotes.Q_SYNCED + GasQuotes.Q_PRUNED + swept, 1, false, 0.2 gwei));
        (uint256 head, uint256 length,,,) = vault.allocationState();
        assertEq(head, length, "terminal work includes bounded head cleanup");
        _drain();
        bytes32 _expected19 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected19);
        address holder = makeAddr("pack-vault-test-prune-holder");
        assertEq(holder.code.length, 0); assertEq(holder.balance, 0);
        uint256 deposit = vault.requestCharge() + 0.1 ether;
        vm.deal(holder, deposit);
        bytes32 _expected20 = TestVaultOps.configurationHash(vault);
        vm.prank(holder); vault.deposit{value: deposit}(_expected20);
        uint256 next = block.timestamp - block.timestamp % 12 hours + 11 hours + 46 minutes;
        if (next <= block.timestamp) next += 12 hours;
        vm.warp(next);
        uint256 processing = vault.processingPool();
        uint256 before = address(vault).balance;
        bytes32 _expected21 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vault.sync(new uint256[](0), 0, 0, _expected21);
        assertEq(vault.processingPool(), processing, "cleanup cannot use protected checkpoint charges");
        assertEq(address(vault).balance, before);
        bytes32 _expected22 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(0, 0, _expected22);
        assertGt(vault.shareBalance(holder), 0, "same pricing window opens after bounded cleanup");
    }

    function _kickFixture() private returns (uint256 id, uint256 backing) {
        _select(primary());
        _environment();
        vm.prank(primary().purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _drain();
        _catchUp(new uint256[](0)); // old bid lookup remains live until its terminal transition
        // A kick needs FWA's floor cap to apply, so drop the D62 exemption _select set, then list a
        // fresh pack under a high floor (it takes the next free backing above the reserved B).
        address oracle = FWA.floorOracle();
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        vm.prank(IOwnable(oracle).owner());
        IOracleAdmin(oracle).setFloor(address(PACKS), 0.33 ether); // cap 0.363 lets a 6-unit pack list at edge
        TestVaultOps.restock(vault, 1, UNITS, 0); // build lists it at once
        id = vault.openListingAt(vault.openListingCount() - 1);
        backing = vault.position(id).backing; // actual edge backing; B itself is reserved by `selected`
        assertGt(backing, 0.06 ether);
        // Drop the floor so this listing sits above the cap and becomes kickable.
        vm.prank(IOwnable(oracle).owner());
        IOracleAdmin(oracle).setFloor(address(PACKS), 0.03 ether);
        uint256 next = block.timestamp - block.timestamp % 12 hours + 11 hours + 46 minutes;
        if (next <= block.timestamp) next += 12 hours;
        vm.warp(next);
        assertEq(vault.idForBacking(B), selected, "settled bid decoy remains reserved");
        _assertReceipt(selected, 0, 0, 0);
    }

    function test_productionColdKickAfterFalseSettledBidCandidate() public {
        (uint256 id, uint256 backing) = _kickFixture();
        uint256 before = address(vault).balance;
        _cold();
        IFwaAdmin(address(FWA)).kickListing(id);
        assertEq(address(vault).balance - before, backing);
        assertEq(vault.pendingReceipts(), 1);
        _assertReceipt(id, backing, 100, 2);
        _assertReceipt(selected, 0, 0, 0);
        _catchUp(_one(id));
        _catchUp(_one(selected));
        assertEq(vault.pendingReceipts(), 0);
    }

    function test_productionLowGasKeepRecordsOrFailsAtomically() public {
        _select(primary());
        _environment();
        uint256 snapshot = vm.snapshotState();
        uint256 before = address(vault).balance;
        uint256 successes;
        uint256 failures;
        for (uint256 limit = 20_000; limit <= 800_000; limit += 20_000) {
            assertTrue(vm.revertToState(snapshot));
            _cold();
            vm.prank(primary().purchaser);
            (bool ok,) = address(FWA).call{gas: limit}(abi.encodeCall(IFwaSettle.keepNFT, (selected)));
            if (ok) {
                ++successes;
                assertEq(vault.pendingReceipts(), 1, "every successful payment is recorded");
                _assertReceipt(selected, B * 9_900 / 10_000, 100, 1);
                assertEq(address(vault).balance - before, B * 9_900 / 10_000);
            } else {
                ++failures;
                assertEq(vault.pendingReceipts(), 0);
                assertEq(address(vault).balance, before);
                (,,,,,,,,,, uint8 status) = FWA.listings(selected);
                assertEq(status, 2, "failed keep leaves allocation intact");
            }
        }
        emit log_named_uint("keep atomic failures", failures);
        emit log_named_uint("keep recorded successes", successes);
        assertGt(successes, 0); assertGt(failures, 0);
    }

    function test_productionLowGasKickRecordsOrFailsAtomically() public {
        (uint256 id, uint256 backing) = _kickFixture();
        uint256 snapshot = vm.snapshotState();
        uint256 before = address(vault).balance;
        uint256 successes;
        uint256 failures;
        for (uint256 limit = 20_000; limit <= 600_000; limit += 10_000) {
            assertTrue(vm.revertToState(snapshot));
            _cold();
            (bool ok,) = address(FWA).call{gas: limit}(abi.encodeCall(IFwaAdmin.kickListing, (id)));
            if (ok) {
                ++successes;
                assertEq(vault.pendingReceipts(), 1, "every successful kick is recorded");
                _assertReceipt(id, backing, 100, 2);
                assertEq(address(vault).balance - before, backing);
            } else {
                ++failures;
                assertEq(vault.pendingReceipts(), 0);
                assertEq(address(vault).balance, before);
                (,,,,,,,,,, uint8 status) = FWA.listings(id);
                assertEq(status, 1);
            }
        }
        emit log_named_uint("kick atomic failures", failures);
        emit log_named_uint("kick recorded successes", successes);
        assertGt(successes, 0); assertGt(failures, 0);
    }
}

contract ForkProductionInventoryTest is ForkBase {
    uint256[] private knownShapes;
    uint256[] private knownPacks;
    uint256[] private knownListings;
    bytes32 private constant TRANSFER = keccak256("Transfer(address,address,uint256)");
    bytes32 private constant LISTED = keccak256("NFTListed(uint256,uint256,address,address,uint256,uint256,uint256)");
    receive() external payable {}

    function _record() private {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        for (uint256 i; i < logs.length; ++i) {
            Vm.Log memory l = logs[i];
            if (l.topics.length == 4 && l.topics[0] == TRANSFER
                && address(uint160(uint256(l.topics[2]))) == address(vault)) {
                if (l.emitter == address(SHAPES)) knownShapes.push(uint256(l.topics[3]));
                if (l.emitter == address(PACKS)) knownPacks.push(uint256(l.topics[3]));
            } else if (l.emitter == address(FWA) && l.topics.length == 4 && l.topics[0] == LISTED
                && address(uint160(uint256(l.topics[3]))) == address(vault)) {
                knownListings.push(uint256(l.topics[1]));
            }
        }
    }

    function _owner(address collection, uint256 id) private view returns (address) {
        (bool ok, bytes memory data) = collection.staticcall(abi.encodeWithSignature("ownerOf(uint256)", id));
        return ok && data.length >= 32 ? abi.decode(data, (address)) : address(0);
    }

    function _seen(uint256[] storage ids, uint256 at) private view returns (bool) {
        for (uint256 i; i < at; ++i) if (ids[i] == ids[at]) return true;
        return false;
    }

    /// @dev Financial existence comes from actual custody and external listing state, not book fields.
    function _fullReference() private view returns (uint256 nav, uint256 principal, uint256 idle, uint256 backing) {
        uint256 liabilities = vault.pendingDepositTotal() + vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal() + vault.processingPool();
        nav = address(vault).balance - liabilities + FWA.feeCredit(address(vault));
        for (uint256 i; i < knownShapes.length; ++i) {
            if (_seen(knownShapes, i) || _owner(address(SHAPES), knownShapes[i]) != address(vault)) continue;
            uint256 value = SHAPES.backingOf(knownShapes[i]);
            principal += value; idle += value;
        }
        for (uint256 i; i < knownPacks.length; ++i) {
            if (_seen(knownPacks, i) || _owner(address(PACKS), knownPacks[i]) != address(vault)) continue;
            uint256 value = PACKS.valueOf(knownPacks[i]);
            principal += value; idle += value;
        }
        for (uint256 i; i < knownListings.length; ++i) {
            (,,, uint256 pack,, uint256 value,,,,, uint8 status) = FWA.listings(knownListings[i]);
            if (status == 1) {
                principal += PACKS.valueOf(pack); backing += value;
                nav += FWA.pendingFees(knownListings[i]);
            } else if (status == 2 || FWA.stuckNFTRecipient(knownListings[i]) == address(vault)) {
                principal += PACKS.valueOf(pack);
            }
        }
        nav += principal + backing;
    }

    function _assertReference() private view {
        (uint256 expected, uint256 principal, uint256 idle, uint256 backing) = _fullReference();
        (uint256 tracked, uint256 cachedIdle, uint256 activeBacking,,,) = vault.totals();
        assertEq(tracked, principal, "live redeemable backing across custody states");
        assertEq(cachedIdle, idle, "immediately usable actual inventory");
        assertEq(activeBacking, backing, "live active posted ETH");
        assertEq(vault.accountedNav(TestVaultOps.witness(vault)), expected, "independent full NAV to the wei");
    }

    /// Direct-mint recipe (build mints each 6-unit pack into ShapePacks and lists it at once, leaving
    /// no idle/loose inventory): an independent custody-based NAV reference matches the vault's own
    /// books across the build, wind-down unlist and liquidation custody states.
    function test_directMintBuildListingWithdrawalAndRedemptionMatchFullReference() public {
        uint256 amount = vault.requestCharge() + 2 ether;
        bytes32 _expected23 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: amount}(_expected23);
        toBlackout(); checkpoint(); toOpen();
        vm.recordLogs();
        TestVaultOps.restock(vault, 2, UNITS, 0);
        _record();
        assertEq(vault.openListingCount(), 2, "build lists both packs at once");
        assertEq(vault.idlePackCount(), 0, "no idle inventory after build");
        _assertReference();
        vm.recordLogs();
        TestVaultOps.restock(vault, 1, UNITS, 0);
        _record();
        assertEq(vault.openListingCount(), 3);
        _assertReference();
        // Clear FWA's 12h crown-exit window so the whole batch unlists.
        vm.warp(block.timestamp + 13 hours); vm.roll(block.number + 3_900);
        vm.prank(owner); vault.startWindDown();
        TestVaultOps.unlist(vault, TestVaultOps.open(vault), 0);
        _assertReference();
        bytes32 _expected24 = TestVaultOps.configurationHash(vault);
        vault.liquidate(16, 0, _expected24);
        _assertReference();
        (uint256 tracked, uint256 idle,,,,) = vault.totals();
        assertEq(tracked, 0); assertEq(idle, 0);
    }

    /// D56: the backing proposal is calibrated by the owner's gasCeiling, not the live block
    /// basefee. A pending-block basefee change alone leaves the floor unmoved; raising the ceiling
    /// moves it past the 10,000-wei tag window, and the stale proposal is then rejected.
    function test_gasCeilingAndBasefeeDoNotMoveBackingProposal() public {
        uint256 gross = vault.requestCharge() + 2 ether;
        bytes32 _expected25 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: gross}(_expected25);
        toBlackout(); checkpoint(); toOpen();
        VaultLib.Params memory p = vault.getParams();
        p.gasCeiling = 0.5 gwei; p.maxTip = 0.05 gwei; p.workFee = 0.00002 ether;
        p.backingRatioBps = 15_000; // fresh construction is viable in both tested gas regimes
        bytes32 _expected26 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected26);
        vm.prank(IOwnable(address(FWA)).owner());
        ProductionOracleExempt(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        vm.fee(0.4 gwei); vm.txGasPrice(0.45 gwei);
        uint256[] memory low = TestVaultOps.proposals(vault, 1, UNITS);
        vm.fee(0.35 gwei); vm.txGasPrice(0.4 gwei);
        uint256[] memory high = TestVaultOps.proposals(vault, 1, UNITS);
        assertEq(low[0], high[0], "basefee alone does not move the backing proposal");
        // D85: the keep-incentive backing prices the purchaser's redeem gas at the fixed
        // PURCHASER_GAS_PRICE, so neither the basefee nor the keeper gas ceiling moves the proposal.
        // Raising the ceiling only widens the profitability margin; the amount stays identical and
        // inside FWA's tag window, so a proposal computed at the lower ceiling still builds here.
        uint256[] memory stale = TestVaultOps.proposals(vault, 1, UNITS);
        p.gasCeiling = 1 gwei;
        bytes32 _expected27 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected27);
        uint256[] memory fresh = TestVaultOps.proposals(vault, 1, UNITS);
        assertEq(stale[0], fresh[0], "a higher gas ceiling does not move the backing proposal (D85)");
        // The tag window still rejects a backing outside it: one window-plus past the proposal fails.
        uint256[] memory outside = new uint256[](1);
        outside[0] = fresh[0] + 2 * 10_000;
        bytes32 _expected28 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, outside, 0, _expected28);
        bytes32 _expected29 = TestVaultOps.configurationHash(vault);
        vault.build(UNITS, stale, 0, _expected29);
        assertEq(vault.openListingCount(), 1);
        assertEq(vault.position(vault.openListingAt(0)).backing, stale[0]);
    }

    function test_pendingEscrowProcessingClaimsAndCancellationExcludedFromNAV() public {
        uint256 amount = vault.requestCharge() + 2 ether;
        uint256 before = vault.accountedNav(0);
        bytes32 _expected30 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: amount}(_expected30);
        assertEq(vault.accountedNav(0), before, "escrow and fixed processing charge are liabilities");
        vm.prank(alice); vault.cancelDeposit();
        assertEq(vault.accountedNav(0), before);
        bytes32 _expected31 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: amount}(_expected31);
        toBlackout(); checkpoint();
        uint256 shares = vault.shareBalance(alice);
        uint256 charge = vault.requestCharge() + shares * vault.lastNav() / vault.totalShares() * vault.unwindCharge() / 0.1248 ether;
        bytes32 _expected32 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.requestRedeem{value: charge}(shares, _expected32);
        toOpen(); toBlackout(); checkpoint();
        uint256 reserved = vault.redemptionReserve();
        uint256 nav = vault.accountedNav(0);
        vm.prank(alice); vault.claim();
        assertGt(reserved, 1.9 ether, "absolute holder principal remains available");
        assertEq(vault.accountedNav(0), nav, "claim moves a protected liability, never strategy NAV");
    }
}

contract ForkProductionFeeWitnessTest is ForkBase {
    receive() external payable {}

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

    function _earnedFees() private returns (uint256 first, uint256 second) {
        vm.createSelectFork("mainnet", bytes32(0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f));
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        vm.deal(address(this), 10 ether);
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, defaultParams(), 3 ether, keccak256(abi.encode(defaultParams(), SHAPES.mintFee(), false, false)));
        vm.prank(IOwnable(address(FWA)).owner());
        ProductionOracleExempt(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        TestVaultOps.restock(vault, 2, UNITS, 0);
        first = vault.openListingAt(0); second = vault.openListingAt(1);
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES))
        );
        for (uint256 i; i < 28; ++i) filler.createAndList(B());
        string memory fixture = vm.readFile("test/fixtures/selection.json");
        _replay(fixture, "req");
        vm.roll(26_417_091); vm.warp(1_794_705_887);
        vm.setBlockhash(26_417_086, vm.parseJsonBytes32(fixture, ".26417086.reqBlockHash"));
        vm.fee(vm.parseJsonUint(fixture, ".26417086.fulBaseFee"));
        _replay(fixture, "ful");
        (,,,,,,,,,, uint8 firstStatus) = FWA.listings(first);
        (,,,,,,,,,, uint8 secondStatus) = FWA.listings(second);
        assertEq(firstStatus, 1, "first witness remains Active");
        assertEq(secondStatus, 1, "second witness remains Active");
        bytes32 _expected33 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected33);
    }

    function _independentNav(uint256 first, uint256 second) private view returns (uint256) {
        return address(vault).balance + 0.12 ether + vault.position(first).backing + vault.position(second).backing
            + FWA.pendingFees(first) + FWA.pendingFees(second) + FWA.feeCredit(address(vault));
    }

    function test_liveDebtWitnessAndHarvestMatchIndividualFeeSum() public {
        (uint256 first, uint256 second) = _earnedFees();
        uint256 pending = FWA.pendingFees(first) + FWA.pendingFees(second);
        assertGt(pending, 0, "real completed foreign acquisition accrued fees");
        uint256 expected = _independentNav(first, second);
        assertEq(vault.accountedNav(first), expected);
        uint256[] memory one = new uint256[](1); one[0] = first;
        vault.harvest(one, 0);
        assertEq(vault.accountedNav(second), _independentNav(first, second));
        assertEq(vault.accountedNav(second), expected, "unpaid dust harvest exchanges fees for actual cash once");
        vm.expectRevert(VaultLib.BadWitness.selector);
        vault.accountedNav(first);
        one[0] = second;
        vault.harvest(one, 0);
        assertEq(vault.accountedNav(first), _independentNav(first, second));
        assertEq(vault.accountedNav(first), expected);
    }

    function test_realFailedHarvestPreservesDebtAndPaysNothing() public {
        (uint256 first, uint256 second) = _earnedFees();
        uint256 oldDebt = vault.position(first).feeDebt;
        uint256 pending = FWA.pendingFees(first);
        uint256 nav = vault.accountedNav(second);
        uint256 before = address(this).balance;
        uint256[] memory stale = new uint256[](2); stale[0] = first; stale[1] = 1e9;
        assertEq(FWA.feeCredit(address(vault)), 0, "no independent credit withdrawal masks the failed claim");
        vm.expectRevert(PackVault.Nothing.selector);
        vault.harvest(stale, 0); // The real FWA rejects the nonexistent listing, rolling back its earlier item.
        assertEq(vault.position(first).feeDebt, oldDebt);
        assertEq(FWA.pendingFees(first), pending);
        assertEq(vault.accountedNav(second), nav);
        assertEq(address(this).balance, before, "failed work earns no compensation");
    }

    function test_duplicateHarvestRejectedWithoutDebtChangeOrPay() public {
        (uint256 first,) = _earnedFees();
        uint256 debt = vault.position(first).feeDebt;
        uint256 pending = FWA.pendingFees(first);
        uint256 before = address(this).balance;
        uint256[] memory twice = new uint256[](2); twice[0] = first; twice[1] = first;
        vm.expectRevert(VaultLib.BadBatch.selector);
        vault.harvest(twice, 0);
        assertEq(vault.position(first).feeDebt, debt);
        assertEq(FWA.pendingFees(first), pending);
        assertEq(address(this).balance, before);
    }
}

contract ForkProductionAdmissionTest is ForkBase {
    receive() external payable {}

    function test_quantizedIntervalBothSidesCollisionsAndHardBounds() public {
        uint256 gross = vault.requestCharge() + 2 ether;
        bytes32 _expected34 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: gross}(_expected34);
        toBlackout(); checkpoint(); toOpen();
        VaultLib.Params memory p = vault.getParams(); p.gasCeiling = 1 gwei;
        bytes32 _expected35 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected35);
        vm.prank(IOwnable(address(FWA)).owner());
        ProductionOracleExempt(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        (, uint256 target, bool ok) = vault.edge(UNITS); assertTrue(ok);
        uint256 lower = target / 10_000 * 10_000;
        uint256 upper = lower + 10_000;
        assertGt(lower, (uint256(0.06 ether) * 10_000 + 9_499) / 9_500, "economic floor leaves both tag directions usable");
        uint256 snapshot = vm.snapshotState();
        uint256[] memory proposed = new uint256[](1); proposed[0] = lower;
        bytes32 _expected36 = TestVaultOps.configurationHash(vault);
        vault.build(UNITS, proposed, 0, _expected36);
        assertEq(vault.position(vault.openListingAt(0)).backing, lower);
        uint256 balance = address(vault).balance;
        bytes32 _expected37 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, proposed, 0, _expected37);
        assertEq(address(vault).balance, balance, "colliding proposal fails before paid mint");
        assertTrue(vm.revertToState(snapshot));
        proposed[0] = upper;
        bytes32 _expected38 = TestVaultOps.configurationHash(vault);
        vault.build(UNITS, proposed, 0, _expected38);
        assertEq(vault.position(vault.openListingAt(0)).backing, upper);
        assertTrue(vm.revertToState(snapshot));
        proposed[0] = lower - 20_000;
        bytes32 _expected39 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, proposed, 0, _expected39);
        proposed[0] = lower + 1;
        bytes32 _expected40 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, proposed, 0, _expected40);
        assertEq(vault.reservedCount(), 0);
        assertEq(vault.idlePackCount(), 0);
    }
}


contract ForkProductionStagingTest is SelectionBase {
    receive() external payable {}

    function assertStagingGasContext() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function _backlog(uint256 count) private returns (ReceiptFixtureFiller foreign, uint256[] memory staged) {
        _select(primary());
        _pendForeignAcquisition(); // real pending request keeps FWA's queue busy so new listings stage
        assertGt(FWA.unsettledAcquisitionCount(), 0);
        foreign = new ReceiptFixtureFiller{value: 3 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES))
        );
        staged = new uint256[](count);
        for (uint256 i; i < count; ++i) {
            staged[i] = foreign.createAndList(B);
            (,,,,,,,,,, uint8 status) = FWA.listings(staged[i]);
            assertEq(status, 5, "real foreign listing is staged after the already-issued request");
        }
        vm.warp(block.timestamp + 25 hours); vm.roll(block.number + 7_500);
        IFwaSettle(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "the public request-queue precheck passes");
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertStagingGasContext();
    }

    function test_stagedAdmissionAfterDrainedPrecheckRevertsAtomically() public {
        (, uint256[] memory staged) = _backlog(17);
        vm.prank(IOwnable(address(FWA)).owner()); IFwaAdmin(address(FWA)).setUint(10, 1);
        uint256[] memory proposal = TestVaultOps.proposals(vault, 1, UNITS);
        uint256 before = address(vault).balance;
        uint256 reserved = vault.reservedCount();
        uint256 supply = SHAPES.totalSupply();
        uint256 openBefore = vault.openListingCount();
        // build mints and lists atomically; a rejected foreign autoactivation rolls back the paid
        // mint and the posted cash in the same transaction (no separate list step any more).
        bytes32 _expected41 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidListing.selector);
        vault.build(UNITS, proposal, 0, _expected41);
        assertEq(address(vault).balance, before, "failed admission returns posted cash atomically");
        assertEq(SHAPES.totalSupply(), supply, "failed admission mints nothing atomically");
        assertEq(vault.idlePackCount(), 0); assertEq(vault.openListingCount(), openBefore);
        assertEq(vault.reservedCount(), reserved);
        assertEq(vault.idForBacking(proposal[0]), 0);
        for (uint256 i; i < staged.length; ++i) {
            (,,,,,,,,,, uint8 status) = FWA.listings(staged[i]);
            assertEq(status, 5, "foreign activation also rolls back with rejected admission");
        }
    }

    function test_foreignAutoactivationRejectedWithBoundedGasEvenWhenOurListingWouldBeActive() public {
        (ReceiptFixtureFiller foreign, uint256[] memory staged) = _backlog(15);
        vm.prank(IOwnable(address(FWA)).owner()); IFwaAdmin(address(FWA)).setUint(10, 16);
        uint256 snapshot = vm.snapshotState();
        uint256 active = FWA.activeListingCount();
        uint256 start = gasleft();
        uint256 direct = foreign.createAndList(B);
        emit log_named_uint("real FWA one admission with fifteen foreign activations gross gas", start - gasleft());
        (,,,,,,,,,, uint8 status) = FWA.listings(direct);
        assertEq(status, 1, "FWA's final status alone permits the costly path");
        assertEq(FWA.activeListingCount() - active, 16, "real side effect activates fifteen foreign listings");
        assertTrue(vm.revertToState(snapshot));
        // build mints and lists four packs atomically; its incidental foreign autoactivation
        // exceeds FWA's per-admission bound, so FWA rejects it with bounded gas and the whole build
        // (every paid mint and every posted backing) rolls back.
        uint256[] memory proposed = TestVaultOps.proposals(vault, 4, UNITS);
        uint256 balance = address(vault).balance;
        uint256 reserved = vault.reservedCount();
        uint256 supply = SHAPES.totalSupply();
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS));
        bytes32 _expected42 = TestVaultOps.configurationHash(vault);
        vm.expectRevert();
        start = gasleft();
        vault.build(UNITS, proposed, 0, _expected42);
        uint256 used = start - gasleft() + 21_000;
        emit log_named_uint("bounded rejected maximum-four admission gross gas", used);
        assertLt(used * 125 / 100, 16_777_216);
        assertEq(address(vault).balance, balance);
        assertEq(SHAPES.totalSupply(), supply, "rejected build mints nothing");
        assertEq(vault.reservedCount(), reserved);
        assertEq(vault.idlePackCount(), 0);
        assertEq(FWA.activeListingCount(), active, "rejected incidental work is never committed");
        for (uint256 i; i < proposed.length; ++i) assertEq(vault.idForBacking(proposed[i]), 0);
        for (uint256 i; i < staged.length; ++i) {
            (,,,,,,,,,, uint8 st) = FWA.listings(staged[i]); assertEq(st, 5);
        }
    }
}
