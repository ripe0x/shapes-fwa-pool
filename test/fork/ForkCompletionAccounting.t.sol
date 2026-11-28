// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {IShapesFeeAdmin} from "./ForkMainConfiguration.t.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";

/// @notice Canonical wei sponsorship and gross escrow against the real main pool dependencies.
contract ForkCompletionAccountingTest is ForkBase {
    address carol = makeAddr("pack-vault-test-completion-carol");
    string constant TRACE = "sim/out/reconcile-contributions-trace.jsonl";

    receive() external payable {}

    function setUp() public override {
        super.setUp();
        assertEq(carol.code.length, 0);
        assertEq(carol.balance, 0);
        vm.deal(carol, 50 ether);
        VaultLib.Params memory p = vault.getParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        p.reserve = 0.005 ether;
        p.upliftBoundBps = 25;
        p.essentialCap = 0;
        p.essentialRate = 0;
        _settings(p);
    }

    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function _settings(VaultLib.Params memory p) internal {
        bytes32 expected = vault.configurationHash();
        vm.prank(owner);
        vault.setParams(p, expected);
    }

    function _deposit(address payer, uint256 principal) internal returns (uint256 contribution) {
        contribution = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(payer);
        vault.deposit{value: principal + contribution}(expected);
    }

    function _refund(address payer, uint256 id) internal returns (uint256 amount) {
        uint256[] memory ids = new uint256[](1);
        ids[0] = id;
        uint256 before = payer.balance;
        vm.prank(payer);
        vault.claimCheckpointRefund(ids);
        return payer.balance - before;
    }

    function test_zeroQuoteRestoredQuoteCancellationsPreserveActualPayers() public {
        this.assertGasContext();
        uint256 freeBefore = vault.freeEth();
        uint256 aliceBefore = alice.balance;
        uint256 bobBefore = bob.balance;
        uint256 carolBefore = carol.balance;
        uint256 first = _deposit(alice, 1 ether);
        assertGt(first, 0);
        assertEq(_deposit(bob, 0.2 ether), 0);
        VaultLib.Params memory initial = vault.getParams();
        VaultLib.Params memory zero = vault.getParams();
        zero.gasSchedule.checkpoint = 0;
        zero.workFee = 0;
        _settings(zero);
        assertEq(vault.requestCharge(), 0);
        vm.prank(bob);
        vault.cancelDeposit();
        assertEq(vault.chargeEra(), 0, "zero quote cannot close Alice's live era");
        assertEq(vault.processingPool(), first);
        initial.gasSchedule.checkpoint *= 2;
        _settings(initial);
        uint256 additional = _deposit(carol, 0.3 ether);
        assertGt(additional, 0, "restored higher quote is genuinely funded");
        vm.prank(carol);
        vault.cancelDeposit();
        assertEq(vault.chargeEra(), 0);
        vm.prank(alice);
        vault.cancelDeposit();
        assertEq(vault.processingPool(), 0);
        assertEq(vault.chargeRefundReserve(), first + additional);
        assertEq(vault.freeEth(), freeBefore, "refund reserve is excluded from deployable cash");
        assertEq(vault.checkpointRefund(0), first);
        assertEq(vault.checkpointRefund(1), additional);
        assertEq(_refund(carol, 1), additional);
        assertEq(_refund(alice, 0), first);
        assertEq(vault.chargeRefundReserve(), 0);
        assertEq(alice.balance, aliceBefore);
        assertEq(bob.balance, bobBefore);
        assertEq(carol.balance, carolBefore);
    }

    function test_constructionIsPricedAtCommitAndIssuanceHasNoOrphanShares() public {
        _deposit(alice, 0.4 ether + 3);
        _deposit(bob, 0.3 ether + 7);
        (uint128 escrow,) = vault.pendingDeposits(alice);
        assertEq(escrow, 0.4 ether + 3, "gross principal is cancellable");
        uint256 initialEstimate = vault.constructionCharge(0.7 ether + 10);
        VaultLib.Params memory p = vault.getParams();
        p.gasSchedule.buildShape *= 2;
        _settings(p);
        uint256 committedCharge = vault.constructionCharge(0.7 ether + 10);
        assertGt(committedCharge, initialEstimate);
        uint256 seed = vault.freeEth();
        uint256 expected = (0.7 ether + 10 - committedCharge) * vault.DEAD_SHARES() / seed;
        toBlackout();
        checkpoint();
        (uint256 gross, uint256 issued,,) = vault.issuances(0);
        assertEq(gross, 0.7 ether + 10);
        assertEq(issued, expected, "absolute issuance at the committing price and recipe");
        bytes32 expectedConfig = vault.configurationHash();
        uint256 checkpointTopup = vault.requestCharge();
        vm.prank(alice);
        vault.requestRedeem{value: checkpointTopup}(1, expectedConfig);
        vm.prank(bob);
        vault.requestRedeem(1, expectedConfig);
        (,, uint256 remainingGross, uint256 remainingShares) = vault.issuances(0);
        assertEq(remainingGross, 0);
        assertEq(remainingShares, 0);
        assertEq(vault.sharesOf(alice) + vault.sharesOf(bob) + vault.lockedShares(), expected);
    }

    function test_explicitTopupReturnsExcessAndPartialFillFinalizesEra() public {
        _deposit(alice, 1 ether);
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 2, 3, 0);
        uint256 shares = vault.shareBalance(alice);
        uint256 charge = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(alice);
        vault.requestRedeem{value: charge}(shares, expected);
        uint256 era = vault.chargeEra();
        VaultLib.Params memory p = vault.getParams();
        p.gasSchedule.checkpoint += 100_001;
        _settings(p);
        uint256 topup = vault.requestCharge();
        uint256 before = bob.balance;
        expected = vault.configurationHash();
        vm.prank(bob);
        uint256 accepted = vault.fundCheckpoint{value: topup + 101}(expected);
        assertEq(accepted, topup);
        assertEq(before - bob.balance, topup, "excess wei returned immediately");
        toBlackout();
        checkpoint();
        assertGt(vault.lockedShares(), 0, "real illiquid positions leave a partial fill");
        assertEq(vault.chargeEra(), era + 1, "partial successful checkpoint closes its funding era");
        assertEq(vault.processingPool(), 0);
        assertEq(vault.freeEth() + vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal() + vault.chargeRefundReserve(), address(vault).balance);
    }

    function _investAndRequestExit() internal {
        _deposit(alice, 1 ether);
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 2, 3, 0);
        uint256 amount = vault.shareBalance(alice);
        uint256 topup = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(alice);
        vault.requestRedeem{value: topup}(amount, expected);
    }

    function test_cancellableEscrowCannotSuppressPreparatoryLiquidation() public {
        _investAndRequestExit();
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.prank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        assertEq(vault.idlePackCount(), 2);
        _deposit(bob, 0.2 ether);
        uint256 before = address(vault).balance;
        uint256 supply = SHAPES.totalSupply();
        bytes32 expected = vault.configurationHash();
        vm.prank(keeper);
        uint256 paid = vault.liquidate(1, 0, expected);
        assertEq(address(vault).balance - before + paid, 0.03 ether, "actual returned principal is liquidated");
        assertEq(supply - SHAPES.totalSupply(), 3, "three actual Shapes redeemed, none reminted");
        assertEq(vault.pendingDepositTotal(), 0.2 ether, "cancellable escrow remains protected");
        vm.prank(bob);
        vault.cancelDeposit();
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.idlePackCount(), 1);
        toBlackout();
        checkpoint();
        assertGt(vault.redemptionReserve(), 0.9 ether);
    }

    function test_onlyActuallyCommittingDepositsFundAtomicMatchedRedemptions() public {
        _investAndRequestExit();
        assertLt(vault.freeEth(), vault.lastNav(), "position backing remains illiquid");
        _deposit(bob, 1 ether);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "committing inflow atomically funds full incumbent exit");
        assertEq(vault.openListingCount(), 2, "matching does not require unnecessary liquidation");
        assertGt(vault.shareBalance(bob), 0);
        (uint256 liveShares, uint256 locked, uint256 entitlement) = vault.holderState(alice);
        assertEq(liveShares, 0);
        assertEq(locked, 0);
        assertGt(entitlement, 0.98 ether, "real absolute incumbent entitlement after construction and keeper costs");
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertEq(alice.balance - before, entitlement);
    }

    function test_unpaidRecoveryCannotConsumePendingDepositsCheckpointWindow() public {
        _deposit(alice, 1 ether);
        toBlackout();
        checkpoint();
        toOpen();
        _deposit(bob, 0.2 ether);
        uint256 topup = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(alice);
        vault.requestRedeem{value: topup}(1, expected);
        uint256 interval = vault.lastCheckpointInterval();
        uint256 era = vault.chargeEra();
        uint256 sponsorship = vault.processingPool();
        toBlackout();
        vault.recoverCheckpoint(0);
        assertEq(vault.lastCheckpointInterval(), interval, "unpaid partial flow cannot monopolize guarded pricing");
        assertEq(vault.pendingDepositTotal(), 0.2 ether);
        assertEq(vault.chargeEra(), era, "unpriced deposit retains its funding era");
        assertEq(vault.processingPool(), sponsorship, "tiny unpaid recovery cannot strip normal keeper compensation");
        uint256 beforeKeeper = keeper.balance;
        vm.prank(keeper);
        uint256 paid = vault.checkpoint(0, 1, expected);
        assertGt(paid, 0, "ordinary paid commitment remains funded");
        assertEq(keeper.balance - beforeKeeper, paid);
        assertEq(vault.pendingDepositTotal(), 0);
        assertGt(vault.shareBalance(bob), 0, "pending deposit still commits in the same quiet window");
    }

    function test_recoveryPreservesUndistributedGainsForRemainingHolders() public {
        _deposit(alice, 1 ether);
        _deposit(bob, 1 ether);
        toBlackout();
        checkpoint();
        toOpen();
        VaultLib.Params memory p = vault.getParams();
        p.distributionBps = 5_000;
        p.minDistribution = 0;
        _settings(p);
        uint256 shares = vault.shareBalance(alice);
        uint256 topup = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(alice);
        vault.requestRedeem{value: topup}(shares, expected);
        (bool ok,) = address(vault).call{value: 0.1 ether}("");
        assertTrue(ok, "real cash gain for distribution-rights regression");
        uint256 watermark = vault.highWaterMark();
        toBlackout();
        vault.recoverCheckpoint(0);
        assertEq(vault.lockedShares(), 0, "Alice receives a real complete fill");
        assertGt(vault.shareBalance(bob), 0, "Bob remains a live incumbent");
        assertEq(vault.highWaterMark(), watermark, "unpaid recovery cannot erase undistributed gains");
        assertEq(vault.distributionReserve(), 0);
        toOpen();
        toBlackout();
        checkpoint();
        assertGt(vault.distributionReserve(), 0, "normal checkpoint can still distribute Bob's gain");
    }

    function test_callerFundedCheckpointPreservesEscrowWhenLiveMintFeeExceedsAcceptedMaximum() public {
        _investAndRequestExit();
        _deposit(bob, 0.2 ether);
        uint256 gross = vault.pendingDepositTotal();
        uint256 pricingEpoch = vault.epoch();
        uint256 era = vault.chargeEra();
        uint256 locked = vault.lockedShares();
        address admin = IShapesFeeAdmin(address(SHAPES)).admin();
        vm.prank(admin);
        IShapesFeeAdmin(address(SHAPES)).setMintFee(0.0015 ether);
        toBlackout();
        bytes32 expected = vault.configurationHash();
        uint256 witnessId = TestVaultOps.witness(vault);
        vm.expectRevert(PackVault.MintFeeNotAccepted.selector);
        vault.checkpoint(witnessId, 0, expected);
        uint256 beforeKeeper = keeper.balance;
        vm.prank(keeper);
        vault.recoverCheckpoint(witnessId);
        assertEq(keeper.balance, beforeKeeper, "caller-funded path earns no keeper payment");
        assertLt(vault.lockedShares(), locked, "real available cash pays a redemption fill");
        assertGt(vault.lockedShares(), 0, "illiquid positions leave a genuine partial fill");
        assertEq(vault.pendingDepositTotal(), gross, "gross pending escrow never funds recovery");
        assertEq(vault.epoch(), pricingEpoch, "uncommitted escrow retains its pricing epoch");
        assertEq(vault.chargeEra(), era, "unpriced deposits retain their relevant checkpoint sponsorship");
        assertGt(vault.processingPool(), 0);
        assertEq(vault.chargeRefundReserve(), 0, "pending holder work keeps this funding protected");
        uint256 before = bob.balance;
        vm.prank(bob);
        vault.cancelDeposit();
        assertEq(bob.balance - before, gross, "recovery leaves deposit fully cancellable");
        vm.expectRevert(PackVault.Nothing.selector);
        vault.recoverCheckpoint(witnessId);
    }

    function test_stalePreviewCannotCommitEscrowOrCheckpoint() public {
        bytes32 stale = vault.configurationHash();
        VaultLib.Params memory p = vault.getParams();
        p.backingRatioBps += 1;
        _settings(p);
        uint256 amount = vault.requestCharge() + 0.1 ether;
        vm.prank(alice);
        vm.expectRevert(PackAccount.ConfigurationChanged.selector);
        vault.deposit{value: amount}(stale);
        assertEq(vault.pendingDepositTotal(), 0);
        _deposit(alice, 0.1 ether);
        toBlackout();
        vm.expectRevert(PackAccount.ConfigurationChanged.selector);
        vault.checkpoint(0, 0, stale);
        assertEq(vault.epoch(), 0);
        vm.prank(alice);
        vault.cancelDeposit();
        assertEq(vault.pendingDepositTotal(), 0, "recovery does not require a stale expectation");
    }

    function _trace(string memory action) internal {
        vm.writeLine(TRACE, string.concat('{', action, ',"expected":',
            ReconcileTrace.render(vault, alice, bob, 0, "contribution"), '}'));
    }

    function test_reconcileContributionErasEveryWei() public {
        this.assertGasContext();
        if (vm.exists(TRACE)) vm.removeFile(TRACE);
        _trace(string.concat('"action":"setup","actors":{"alice":"', vm.toString(alice),
            '","bob":"', vm.toString(bob), '","carol":"', vm.toString(carol), '"}'));
        uint256 first = _deposit(alice, 1 ether);
        _trace(string.concat('"action":"deposit","payer":"alice","amount":1000000000000000000,"pay":', vm.toString(first)));
        _deposit(bob, 0.2 ether);
        _trace('"action":"deposit","payer":"bob","amount":200000000000000000,"pay":0');
        VaultLib.Params memory p = vault.getParams();
        VaultLib.Params memory zero = vault.getParams();
        zero.gasSchedule.checkpoint = 0;
        zero.workFee = 0;
        _settings(zero);
        vm.prank(bob);
        vault.cancelDeposit();
        _trace('"action":"cancel","payer":"bob"');
        p.gasSchedule.checkpoint += 100_001;
        _settings(p);
        uint256 extra = _deposit(carol, 0.3 ether);
        _trace(string.concat('"action":"deposit","payer":"carol","amount":300000000000000000,"pay":', vm.toString(extra)));
        vm.prank(carol);
        vault.cancelDeposit();
        _trace('"action":"cancel","payer":"carol"');
        vm.prank(alice);
        vault.cancelDeposit();
        _trace('"action":"cancel","payer":"alice"');
        _refund(alice, 0);
        _trace('"action":"claimRefund","payer":"alice","ids":[0]');
        _refund(carol, 1);
        _trace('"action":"claimRefund","payer":"carol","ids":[1]');

        first = _deposit(alice, 1 ether);
        _trace(string.concat('"action":"deposit","payer":"alice","amount":1000000000000000000,"pay":', vm.toString(first)));
        p.gasSchedule.checkpoint += 111_113;
        _settings(p);
        uint256 quote = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(bob);
        vault.fundCheckpoint{value: quote + 17}(expected);
        _trace(string.concat('"action":"fund","payer":"bob","amount":', vm.toString(quote + 17),
            ',"quote":', vm.toString(quote)));
        p.gasSchedule.checkpoint = 300_007;
        _settings(p);
        uint256 construction = vault.deployCharge();
        uint256 capital = vault.positionValue();
        toBlackout();
        expected = vault.configurationHash();
        vm.prank(keeper);
        uint256 paid = vault.checkpoint(0, 0, expected);
        _trace(string.concat('"action":"closeCheckpoint","pay":', vm.toString(paid),
            ',"constructionCost":', vm.toString(construction), ',"referenceCapital":', vm.toString(capital)));
        uint256 refundAlice = vault.checkpointRefund(2);
        uint256 refundBob = vault.checkpointRefund(3);
        assertGt(refundAlice, 0);
        assertGt(refundBob, 0);
        assertEq(refundAlice + refundBob, first + quote - paid, "all residual wei belong to the two payer intervals");
        _refund(bob, 3);
        _trace('"action":"claimRefund","payer":"bob","ids":[3]');
        _refund(alice, 2);
        _trace('"action":"claimRefund","payer":"alice","ids":[2]');
        assertEq(vault.chargeRefundReserve(), 0);
    }
}
