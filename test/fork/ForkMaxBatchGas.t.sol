// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {GasQuotes} from "../utils/GasQuotes.sol";
import {MeasuredPay} from "../utils/MeasuredPay.sol";

import {ForkBase, IOwnable, ForceSender, IFwaAdmin} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {Charges} from "../utils/Charges.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Vm} from "forge-std/Vm.sol";

/// @notice Isolated gas diagnostics against the fixed keeper quotes (D56) and the EIP-7825
///         16,777,216-gas transaction cap, for the direct-mint recipe. `build` mints each pack
///         straight into ShapePacks and lists it at once, so there is no idle pack to `list` after
///         a build; `list` only relists packs FWA returned. Every operation runs the real deployed
///         code against the real FWA/Shapes/ShapePacks; nothing is mocked. These samples do not
///         substitute for actual transaction receipts when calibrating payment.
contract ForkMaxBatchGasTest is ForkBase {
    receive() external payable {}

    // The 6-unit recipe mints two Shapes (one 0.05, one 0.01); the 30-unit cap mints three 0.1.
    uint256 constant BUILD_GAS_6 = GasQuotes.Q_BUILD_PACK + 2 * GasQuotes.Q_BUILD_SHAPE;
    uint256 constant BUILD_GAS_30 = GasQuotes.Q_BUILD_PACK + 3 * GasQuotes.Q_BUILD_SHAPE;

    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function assertEssentialSpikeContext() external view {
        assertEq(block.basefee, 1.95 gwei); assertEq(tx.gasprice, 2 gwei);
    }

    function _cold() private {
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(address(SHAPES)); vm.cool(keeper);
    }

    /// @dev Cold keeper call, reporting the isolated execution-frame gas against the
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

    /// @notice Build of 1..4 packs of six units: billed gas against Q_BUILD + n (buildGas + Q_LISTED),
    ///         then unlist and liquidate of the resulting 6-unit packs. ShapePacks is oracle-exempt
    ///         (ForkBase setUp), so a 0.06 ETH pack lists uncapped.
    function test_sixUnitBuildUnlistLiquidateBilledGas() public {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, defaultParams(), 5 ether, keccak256(abi.encode(defaultParams(), SHAPES.mintFee(), false, false)));
        assertTrue(vm.isIsolateMode(), "execution-frame gas diagnostics require isolated calls");
        (,, bool ok) = vault.edge(UNITS);
        assertTrue(ok, "6-unit edge must be live");

        for (uint256 n = 1; n <= 4; ++n) {
            uint256 snap = vm.snapshotState();
            uint256[] memory props = TestVaultOps.proposals(vault, n, UNITS);
            uint256 quoted = GasQuotes.Q_BUILD + n * (BUILD_GAS_6 + GasQuotes.Q_LISTED);
            _billed(string.concat("build ", vm.toString(n), " x 6-unit"),
                abi.encodeCall(PackAccount.build, (UNITS, props, 0, vault.configurationHash())), quoted);
            assertEq(vault.openListingCount(), n, "build lists every pack at once");
            assertEq(vault.idlePackCount(), 0, "build leaves no idle pack");
            assertTrue(vm.revertToState(snap));
        }

        // Working set of eight open listings, then exit: unlist returns them to idle, liquidate redeems.
        TestVaultOps.restock(vault, 8, UNITS, 0);
        assertEq(vault.openListingCount(), 8);
        // Clear FWA's 12h crown-exit window so the whole batch can unlist in one call.
        vm.warp(block.timestamp + 13 hours); vm.roll(block.number + 3_900);
        vm.prank(owner); vault.startWindDown();
        uint256[] memory open = TestVaultOps.open(vault);
        _billed("unlist 8 x 6-unit", abi.encodeCall(PackAccount.unlist, (open, 0, vault.configurationHash())),
            GasQuotes.Q_UNLIST + 8 * GasQuotes.Q_UNLISTED);
        assertEq(vault.openListingCount(), 0, "all eight unlisted");
        assertEq(vault.idlePackCount(), 8, "returned to idle");
        // Liquidate burns two Shapes per 6-unit pack (8 packs, 48 units <= 60-unit per-call cap).
        _billed("liquidate 8 x 6-unit", abi.encodeCall(PackAccount.liquidate, (16, 0, vault.configurationHash())),
            GasQuotes.Q_LIQUIDATE + 8 * GasQuotes.Q_LIQ_PACK + 16 * GasQuotes.Q_REDEEM_SHAPE);
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
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 20 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        TestVaultOps.restock(vault, 8, 30, 0);
        uint256[] memory open = TestVaultOps.open(vault);
        assertEq(open.length, 8);
        // FWA only permits kicks during the purchase blackout; drop the floor below the live
        // backings so every listing is kickable, returning its pack.
        toBlackout();
        setPackAsk(0.25 ether);
        for (uint256 i; i < open.length; ++i) IFwaAdmin(address(FWA)).kickListing(open[i]);
        assertEq(vault.pendingReceipts(), 8);
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); vault.sync(open, 0, 0, _expected2);
        assertEq(vault.idlePackCount(), 8, "kicked packs returned to idle");
        assertEq(vault.openListingCount(), 0);
        // Relist out of the blackout at fresh backings the restored ceiling allows.
        toOpen();
        setPackAsk(0.33 ether);
        uint256[] memory relist = TestVaultOps.proposals(vault, 8, 30);
        _billed("list 8 relisted", abi.encodeCall(PackAccount.list, (relist, 0, vault.configurationHash())),
            GasQuotes.Q_LIST + 8 * GasQuotes.Q_LISTED);
        assertEq(vault.openListingCount(), 8, "all eight relisted");
    }

    /// @notice EIP-7825 worst case: the largest allowed packs (30 units) at maximum batch for each
    ///         operation — build 4, unlist 16, liquidate, sync 16 kicks — all inside the cap.
    function test_thirtyUnitMaxBatchFitsTransactionCap() public {
        vm.createSelectFork("mainnet", BLOCK);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        vm.deal(keeper, 1 ether);
        setPackAsk(0.33 ether);
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 30; p.reserve = 0;
        vm.deal(address(this), 40 ether);
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 30 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));

        // Max build batch: four 30-unit packs in one call.
        uint256 snap = vm.snapshotState();
        uint256[] memory four = TestVaultOps.proposals(vault, 4, 30);
        _billed("build 4 x 30-unit (max build batch)", abi.encodeCall(PackAccount.build, (30, four, 0, vault.configurationHash())),
            GasQuotes.Q_BUILD + 4 * (BUILD_GAS_30 + GasQuotes.Q_LISTED));
        assertTrue(vm.revertToState(snap));

        // Sixteen open listings for the 16-wide unlist/sync worst case (four build calls of four).
        TestVaultOps.restock(vault, 16, 30, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 16);

        // Max sync batch: 16 kicked receipts processed in one call (kicks need the blackout window).
        snap = vm.snapshotState();
        toBlackout();
        setPackAsk(0.25 ether);
        for (uint256 i; i < ids.length; ++i) IFwaAdmin(address(FWA)).kickListing(ids[i]);
        assertEq(vault.pendingReceipts(), 16);
        _billed("sync 16 kicked receipts", abi.encodeCall(PackAccount.sync, (ids, 0, 0, vault.configurationHash())),
            GasQuotes.Q_SYNC); // base quote; per-receipt journal/scan work is added live
        assertEq(vault.idlePackCount(), 16);
        assertTrue(vm.revertToState(snap));

        // Max unlist batch: 16 active 30-unit listings withdrawn in wind-down.
        vm.warp(block.timestamp + 13 hours); vm.roll(block.number + 3_900);
        vm.prank(owner); vault.startWindDown();
        snap = vm.snapshotState();
        _billed("unlist 16 x 30-unit (max unlist batch)", abi.encodeCall(PackAccount.unlist, (ids, 0, vault.configurationHash())),
            GasQuotes.Q_UNLIST + 16 * GasQuotes.Q_UNLISTED);
        assertEq(vault.openListingCount(), 0);
        // Liquidate: two 30-unit packs is the 60-unit per-call ceiling (six Shapes burned).
        _billed("liquidate 2 x 30-unit (60-unit per-call cap)", abi.encodeCall(PackAccount.liquidate, (2, 0, vault.configurationHash())),
            GasQuotes.Q_LIQUIDATE + 2 * GasQuotes.Q_LIQ_PACK + 6 * GasQuotes.Q_REDEEM_SHAPE);
        assertTrue(vm.revertToState(snap));
        assertLe(address(vault).code.length, 24_576);
        assertLe(address(VaultLib).code.length, 24_576);
    }

    /// @notice 29 units contain seven Shapes (two .10, one .05 and four .01), versus only
    ///         three Shapes at 30 units. Exercise the maximum fresh-mint work, not just face value.
    function test_twentyNineUnitSevenShapeMaximumBuildFitsActualTransactionCap() public {
        vm.createSelectFork("mainnet", BLOCK);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        vm.deal(keeper, 1 ether);
        setPackAsk(0.33 ether);
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 29;
        p.gasCeiling = 0.5 gwei;
        p.reserve = 0.005 ether;
        vm.deal(address(this), 40 ether);
        bytes32 deploymentHash = keccak256(abi.encode(p, SHAPES.mintFee(), false, false));
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 30 ether, deploymentHash);
        assertTrue(vm.isIsolateMode(), "isolated execution frame required for the gas diagnostic");
        (,, bool admissible) = vault.edge(29);
        assertTrue(admissible, "the real economic and oracle admission gates allow this batch");
        uint256[] memory proposals = TestVaultOps.proposals(vault, 4, 29);
        bytes memory input = abi.encodeCall(PackAccount.build, (29, proposals, 0, vault.configurationHash()));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        uint256 supply = SHAPES.totalSupply();
        _cold();
        vm.prank(keeper);
        (bool ok, bytes memory result) = address(vault).call{gas: 16_777_216 - intrinsic}(input);
        Vm.Gas memory frame = vm.lastCallGas();
        // These are isolated-frame diagnostics. Actual transaction receipts must calibrate pay.
        emit log_named_uint("4 x 29 units isolated execution gas", frame.gasTotalUsed);
        emit log_named_uint("4 x 29 units calldata intrinsic gas", intrinsic);
        emit log_named_uint("4 x 29 units isolated gas refund", uint256(uint64(frame.gasRefunded)));
        emit log_named_uint("4 x 29 units isolated gas plus intrinsic", uint256(frame.gasTotalUsed) + intrinsic);
        assertTrue(ok, "four seven-Shape packs must complete inside EIP-7825; otherwise bound per-call mint count");
        assertLe(uint256(frame.gasTotalUsed) + intrinsic, 16_777_216, "actual isolated call fits the transaction cap");
        assertEq(vault.openListingCount(), 4);
        assertEq(SHAPES.totalSupply() - supply, 28, "all 28 paid fresh Shapes actually minted");
        assertGt(abi.decode(result, (uint256)), 0, "verified fresh work is paid");
    }

    function test_checkpointFullHolderMixCompleteGas() public {
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5_000;
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected5);
        uint256 deposit = Charges.grossFor(vault, 5 ether);
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: deposit}(_expected6);
        toBlackout(); checkpoint(); toOpen();
        // Lock part of the deposit in 6-unit listings (three builds of eight) so the bounded per-
        // checkpoint unwind cannot fill a half-share redemption in one pass (first fill stays
        // partial), while leaving idle ETH for the gain distribution to reserve into.
        for (uint256 i; i < 3; ++i) {
            TestVaultOps.restock(vault, 8, UNITS, 0);
        }
        uint256 half = vault.shareBalance(alice) / 2;
        uint256 charge = Charges.redeemCharge(vault, half);
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.requestRedeem{value: charge}(half, _expected7);
        toBlackout(); checkpoint();
        assertGt(vault.lockedShares(), 0, "first fill is genuinely partial");
        uint256 firstReserve = vault.redemptionReserve();
        assertGt(firstReserve, 1 ether, "absolute first holder reserve");
        toOpen();
        vm.deal(address(this), 2 ether);
        new ForceSender{value: 1 ether}(payable(address(vault)));
        uint256 beforeSecondDeposit = vm.snapshotState();
        deposit = Charges.grossFor(vault, 1 ether);
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vm.prank(bob); vault.deposit{value: deposit}(_expected8);
        toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        assertTrue(vm.isIsolateMode(), "execution-frame gas diagnostics require isolated calls");
        bytes memory input = abi.encodeCall(PackVault.checkpoint, (witness, 0, vault.configurationHash()));
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
        assertLe(frame.gasTotalUsed, GasQuotes.Q_CHECKPOINT, "fixed checkpoint gas component covers this isolated execution sample");
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas", gross);
        emit log_named_uint("checkpoint redemption index distribution deposit payment complete gas pay wei", abi.decode(result, (uint256)));
        emit log_named_uint("checkpoint call meter plus intrinsic", callMeter);
        emit log_named_uint("checkpoint isolated execution gas", frame.gasTotalUsed);
        emit log_named_uint("checkpoint finalized frame refund", refund);
        emit log_named_uint("checkpoint isolated execution cost diagnostic wei at 0.5 gwei", uint256(frame.gasTotalUsed) * 0.5 gwei);
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
        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected9);
        vm.fee(1.95 gwei); vm.txGasPrice(2 gwei); this.assertEssentialSpikeContext();
        uint256 spikeCharge = vault.requestCharge();
        // A8: the request charge prices one checkpoint plus the account-owned overhead (100_000,
        // the deploy schedule's `overhead`) per call. Literal keeps this deep frame off stack-too-deep.
        assertEq(spikeCharge, (GasQuotes.Q_CHECKPOINT + 100_000) * 2 gwei + p.workFee);
        deposit = Charges.grossFor(vault, 1 ether);
        bytes32 _expected10 = TestVaultOps.configurationHash(vault);
        vm.prank(bob); vault.deposit{value: deposit}(_expected10);
        toBlackout(); this.assertEssentialSpikeContext();
        assertGt(vault.lockedShares(), 0, "pending redemption makes this checkpoint essential");
        assertEq(vault.processingPool(), spikeCharge);
        uint256 routineBefore = vault.budget();
        uint256 keeperBefore = keeper.balance;
        witness = TestVaultOps.witness(vault);
        input = abi.encodeCall(PackVault.checkpoint, (witness, 0, vault.configurationHash()));
        intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        vm.getRecordedLogs(); // flush prior events so the next KeeperWorkMeasured is this checkpoint's
        _cold(); vm.prank(keeper);
        start = gasleft();
        (ok, result) = address(vault).call(input);
        callMeter = start - gasleft() + intrinsic;
        frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        assertGe(frame.gasRefunded, 0);
        refund = uint256(uint64(frame.gasRefunded));
        gross = uint256(frame.gasTotalUsed) + refund;
        assertLe(frame.gasTotalUsed, GasQuotes.Q_CHECKPOINT, "essential gas component covers this isolated execution sample");
        emit log_named_uint("essential spike checkpoint isolated execution gas", frame.gasTotalUsed);
        emit log_named_uint("essential spike checkpoint finalized frame refund", refund);
        emit log_named_uint("essential spike checkpoint isolated gross before refund", gross);
        emit log_named_uint("essential spike checkpoint call meter plus intrinsic", callMeter);
        emit log_named_uint("essential spike checkpoint actual pay wei", abi.decode(result, (uint256)));
        assertLt((gross * 125 + 99) / 100, 16_777_216);
        // E2: the essential checkpoint pays its measured work (below the full quote), not the whole
        // charge. The request charge is the funding ceiling; the unused remainder stays refundable
        // to the depositor who paid it, so the keeper never pockets more than the real work.
        uint256 essentialPay = MeasuredPay.gross(vault, GasQuotes.Q_CHECKPOINT, 1, true, 2 gwei);
        assertEq(keeper.balance - keeperBefore, essentialPay, "essential checkpoint pays its measured work");
        assertLe(keeper.balance - keeperBefore, spikeCharge, "the request charge is the funding ceiling, never exceeded");
        uint256 routineAfter = vault.budget();
        assertEq(routineAfter, routineBefore);
        assertEq(vault.processingPool(), 0); assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.lockedShares(), 0); assertGt(vault.shareBalance(bob), 0);
        protected = vault.redemptionReserve() + vault.distributionReserve() + vault.claimableTotal();
        assertGe(address(vault).balance, protected);
    }
}
