// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, ForceSender, IFwaAdmin} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {Charges} from "../utils/Charges.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Vm} from "forge-std/Vm.sol";

/// @notice Billed-gas re-measurement against the fixed keeper quotes (D56) and the EIP-7825
///         16,777,216-gas transaction cap, for the direct-mint recipe. `build` mints each pack
///         straight into ShapePacks and lists it at once, so there is no idle pack to `list` after
///         a build; `list` only relists packs FWA returned. Every operation runs the real deployed
///         code against the real FWA/Shapes/ShapePacks; nothing is mocked.
contract ForkMaxBatchGasTest is ForkBase {
    receive() external payable {}

    // The 6-unit recipe mints two Shapes (one 0.05, one 0.01); the 30-unit cap mints three 0.1.
    uint256 constant BUILD_GAS_6 = VaultLib.Q_BUILD_PACK + 2 * VaultLib.Q_BUILD_SHAPE;
    uint256 constant BUILD_GAS_30 = VaultLib.Q_BUILD_PACK + 3 * VaultLib.Q_BUILD_SHAPE;

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

    /// @dev Cold keeper call, reporting the call's internal (receipt-equivalent) gas against the
    ///      fixed quote. It does not fail on an underpay (reported instead, per the audit brief); it
    ///      always enforces the real invariant: the operation plus the keeper's 25% estimate margin
    ///      fits the per-transaction cap.
    function _billed(string memory label, bytes memory input, uint256 quotedGas) private returns (uint256 billed) {
        _cold();
        vm.prank(keeper);
        (bool ok, bytes memory result) = address(vault).call(input);
        Vm.Gas memory frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        billed = uint256(frame.gasTotalUsed);
        emit log_named_uint(string.concat(label, " billed gas"), billed);
        emit log_named_uint(string.concat(label, " quoted gas"), quotedGas);
        if (quotedGas >= billed) emit log_named_uint(string.concat(label, " quote margin gas"), quotedGas - billed);
        else emit log_named_uint(string.concat(label, " QUOTE UNDERPAYS billed by gas"), billed - quotedGas);
        if (result.length >= 32) emit log_named_uint(string.concat(label, " keeper pay wei"), abi.decode(result, (uint256)));
        assertLt((billed * 125 + 99) / 100, 16_777_216, "operation plus 25% keeper margin fits EIP-7825");
    }

    /// @notice Build of 1..8 packs of six units: billed gas against Q_BUILD + n (buildGas + Q_LISTED),
    ///         then unlist and liquidate of the resulting 6-unit packs. ShapePacks is oracle-exempt
    ///         (ForkBase setUp), so a 0.06 ETH pack lists uncapped.
    function test_sixUnitBuildUnlistLiquidateBilledGas() public {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, defaultParams(), 5 ether);
        assertTrue(vm.isIsolateMode(), "receipt-equivalent frame gas requires isolated calls");
        (,, bool ok) = vault.edge(UNITS);
        assertTrue(ok, "6-unit edge must be live");

        for (uint256 n = 1; n <= 8; ++n) {
            uint256 snap = vm.snapshotState();
            uint256[] memory props = TestVaultOps.proposals(vault, n, UNITS);
            uint256 quoted = VaultLib.Q_BUILD + n * (BUILD_GAS_6 + VaultLib.Q_LISTED);
            _billed(string.concat("build ", vm.toString(n), " x 6-unit"),
                abi.encodeCall(PackAccount.build, (UNITS, props, 0)), quoted);
            assertEq(vault.openListingCount(), n, "build lists every pack at once");
            assertEq(vault.idlePackCount(), 0, "build leaves no idle pack");
            assertTrue(vm.revertToState(snap));
        }

        // Working set of eight open listings, then exit: unlist returns them to idle, liquidate redeems.
        uint256[] memory props8 = TestVaultOps.proposals(vault, 8, UNITS);
        vault.build(UNITS, props8, 0);
        assertEq(vault.openListingCount(), 8);
        // Clear FWA's 12h crown-exit window so the whole batch can unlist in one call.
        vm.warp(block.timestamp + 13 hours); vm.roll(block.number + 3_900);
        vm.prank(owner); vault.startWindDown();
        uint256[] memory open = TestVaultOps.open(vault);
        _billed("unlist 8 x 6-unit", abi.encodeCall(PackAccount.unlist, (open, 0)),
            VaultLib.Q_UNLIST + 8 * VaultLib.Q_UNLISTED);
        assertEq(vault.openListingCount(), 0, "all eight unlisted");
        assertEq(vault.idlePackCount(), 8, "returned to idle");
        // Liquidate burns two Shapes per 6-unit pack (8 packs, 48 units <= 60-unit per-call cap).
        _billed("liquidate 8 x 6-unit", abi.encodeCall(PackAccount.liquidate, (16, 0)),
            VaultLib.Q_LIQUIDATE + 8 * VaultLib.Q_LIQ_PACK + 16 * VaultLib.Q_REDEEM_SHAPE);
        assertEq(vault.idlePackCount(), 0, "all redeemed");
    }

    /// @notice Relisting idle packs (`list`). Gas is independent of pack size (no mint, no Shapes),
    ///         so it is measured on 30-unit packs returned to idle by a real FWA kick. Non-exempt
    ///         here (fresh fork), with a floor the kicked backings exceed.
    function test_listRebatchBilledGas() public {
        vm.createSelectFork("mainnet", BLOCK);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        vm.deal(keeper, 1 ether);
        setPackAsk(0.33 ether); // ceiling 0.363 covers 30-unit backings near 0.36
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 30; p.reserve = 0;
        vm.deal(address(this), 30 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 20 ether);
        uint256[] memory props8 = TestVaultOps.proposals(vault, 8, 30);
        vault.build(30, props8, 0);
        uint256[] memory open = TestVaultOps.open(vault);
        assertEq(open.length, 8);
        // FWA only permits kicks during the purchase blackout; drop the floor below the live
        // backings so every listing is kickable, returning its pack.
        toBlackout();
        setPackAsk(0.25 ether);
        for (uint256 i; i < open.length; ++i) IFwaAdmin(address(FWA)).kickListing(open[i]);
        assertEq(vault.pendingReceipts(), 8);
        vm.prank(keeper); vault.sync(open, 0, 0);
        assertEq(vault.idlePackCount(), 8, "kicked packs returned to idle");
        assertEq(vault.openListingCount(), 0);
        // Relist out of the blackout at fresh backings the restored ceiling allows.
        toOpen();
        setPackAsk(0.33 ether);
        uint256[] memory relist = TestVaultOps.proposals(vault, 8, 30);
        _billed("list 8 relisted", abi.encodeCall(PackAccount.list, (relist, 0)),
            VaultLib.Q_LIST + 8 * VaultLib.Q_LISTED);
        assertEq(vault.openListingCount(), 8, "all eight relisted");
    }

    /// @notice EIP-7825 worst case: the largest allowed packs (30 units) at maximum batch for each
    ///         operation — build 8, unlist 16, liquidate, sync 16 kicks — all inside the cap.
    function test_thirtyUnitMaxBatchFitsTransactionCap() public {
        vm.createSelectFork("mainnet", BLOCK);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        vm.deal(keeper, 1 ether);
        setPackAsk(0.33 ether);
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 30; p.reserve = 0;
        vm.deal(address(this), 40 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 30 ether);

        // Max build batch: eight 30-unit packs in one call.
        uint256 snap = vm.snapshotState();
        uint256[] memory eight = TestVaultOps.proposals(vault, 8, 30);
        _billed("build 8 x 30-unit (max build batch)", abi.encodeCall(PackAccount.build, (30, eight, 0)),
            VaultLib.Q_BUILD + 8 * (BUILD_GAS_30 + VaultLib.Q_LISTED));
        assertTrue(vm.revertToState(snap));

        // Sixteen open listings for the 16-wide unlist/sync worst case (two build calls of eight).
        uint256[] memory p8a = TestVaultOps.proposals(vault, 8, 30);
        vault.build(30, p8a, 0);
        uint256[] memory p8b = TestVaultOps.proposals(vault, 8, 30);
        vault.build(30, p8b, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 16);

        // Max sync batch: 16 kicked receipts processed in one call (kicks need the blackout window).
        snap = vm.snapshotState();
        toBlackout();
        setPackAsk(0.25 ether);
        for (uint256 i; i < ids.length; ++i) IFwaAdmin(address(FWA)).kickListing(ids[i]);
        assertEq(vault.pendingReceipts(), 16);
        _billed("sync 16 kicked receipts", abi.encodeCall(PackAccount.sync, (ids, 0, 0)),
            VaultLib.Q_SYNC); // base quote; per-receipt journal/scan work is added live
        assertEq(vault.idlePackCount(), 16);
        assertTrue(vm.revertToState(snap));

        // Max unlist batch: 16 active 30-unit listings withdrawn in wind-down.
        vm.warp(block.timestamp + 13 hours); vm.roll(block.number + 3_900);
        vm.prank(owner); vault.startWindDown();
        snap = vm.snapshotState();
        _billed("unlist 16 x 30-unit (max unlist batch)", abi.encodeCall(PackAccount.unlist, (ids, 0)),
            VaultLib.Q_UNLIST + 16 * VaultLib.Q_UNLISTED);
        assertEq(vault.openListingCount(), 0);
        // Liquidate: two 30-unit packs is the 60-unit per-call ceiling (six Shapes burned).
        _billed("liquidate 2 x 30-unit (60-unit per-call cap)", abi.encodeCall(PackAccount.liquidate, (2, 0)),
            VaultLib.Q_LIQUIDATE + 2 * VaultLib.Q_LIQ_PACK + 6 * VaultLib.Q_REDEEM_SHAPE);
        assertTrue(vm.revertToState(snap));
        assertLe(address(vault).code.length, 24_576);
        assertLe(address(VaultLib).code.length, 24_576);
    }

    function test_checkpointFullHolderMixCompleteGas() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5_000;
        vm.prank(owner); vault.setParams(p);
        uint256 deposit = Charges.grossFor(vault, 5 ether);
        vm.prank(alice); vault.deposit{value: deposit}();
        toBlackout(); checkpoint(); toOpen();
        // Lock part of the deposit in 6-unit listings (three builds of eight) so the bounded per-
        // checkpoint unwind cannot fill a half-share redemption in one pass (first fill stays
        // partial), while leaving idle ETH for the gain distribution to reserve into.
        for (uint256 i; i < 3; ++i) {
            TestVaultOps.restock(vault, 8, UNITS, 0);
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
        assertTrue(vm.isIsolateMode(), "receipt-equivalent frame gas requires isolated calls");
        bytes memory input = abi.encodeCall(PackVault.checkpoint, (witness, 0));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        uint256 callMeter = start - gasleft() + intrinsic;
        Vm.Gas memory frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        assertGe(frame.gasRefunded, 0);
        uint256 refund = uint256(uint64(frame.gasRefunded));
        uint256 gross = uint256(frame.gasTotalUsed) + refund;
        assertLe(frame.gasTotalUsed, VaultLib.Q_CHECKPOINT, "fixed checkpoint gas component covers this isolated receipt-equivalent sample");
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas", gross);
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas pay wei", abi.decode(result, (uint256)));
        emit log_named_uint("checkpoint call meter plus intrinsic", callMeter);
        emit log_named_uint("checkpoint isolated receipt-equivalent gas", frame.gasTotalUsed);
        emit log_named_uint("checkpoint finalized frame refund", refund);
        emit log_named_uint("checkpoint sample receipt-equivalent cost wei at matched 0.5 gwei", uint256(frame.gasTotalUsed) * 0.5 gwei);
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
        input = abi.encodeCall(PackVault.checkpoint, (witness, 0));
        intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        _cold(); vm.prank(keeper);
        start = gasleft();
        (ok, result) = address(vault).call(input);
        callMeter = start - gasleft() + intrinsic;
        frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        assertGe(frame.gasRefunded, 0);
        refund = uint256(uint64(frame.gasRefunded));
        gross = uint256(frame.gasTotalUsed) + refund;
        assertLe(frame.gasTotalUsed, VaultLib.Q_CHECKPOINT, "essential gas component covers this isolated receipt-equivalent sample");
        emit log_named_uint("essential spike checkpoint isolated receipt-equivalent gas", frame.gasTotalUsed);
        emit log_named_uint("essential spike checkpoint finalized frame refund", refund);
        emit log_named_uint("essential spike checkpoint isolated gross before refund", gross);
        emit log_named_uint("essential spike checkpoint call meter plus intrinsic", callMeter);
        emit log_named_uint("essential spike checkpoint actual pay wei", abi.decode(result, (uint256)));
        assertLt((gross * 125 + 99) / 100, 16_777_216);
        assertEq(keeper.balance - keeperBefore, spikeCharge, "essential ceiling is funded by the actual request charge");
        (uint256 routineAfter, uint256 essentialAfter) = vault.budget();
        assertEq(routineAfter, routineBefore); assertEq(essentialAfter, essentialBefore);
        assertEq(vault.processingPool(), 0); assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.lockedShares(), 0); assertGt(vault.shareBalance(bob), 0);
        protected = vault.redemptionReserve() + vault.distributionReserve() + vault.claimableTotal();
        assertGe(address(vault).balance, protected);
    }
}
