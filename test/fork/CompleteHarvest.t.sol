// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {JournalRequests} from "./EfficientJournal.t.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

/// @notice Real fees from the recorded Chainlink fulfillment. Cash is reduced only to exercise
///         the explicit liquidity gate; FWA state, pending fees and fee debts are never fabricated.
contract CompleteHarvestTest is ForkBase {
    uint256 first;
    uint256 second;

    receive() external payable {}

    function setUp() public override {
        vm.createSelectFork("mainnet", bytes32(0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f));
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0);
            assertEq(actors[i].balance, 0);
            vm.deal(actors[i], 50 ether);
        }
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        vm.deal(address(this), 10 ether);
        VaultLib.Params memory p = defaultParams();
        p.payMarkupBps = 0; p.workFee = 0; p.reserve = 0; p.gasCeiling = 0.5 gwei;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 3 ether);
        TestVaultOps.restock(vault, 2, UNITS, 0);
        TestVaultOps.list(vault, 2, 0);
        first = vault.openListingAt(0); second = vault.openListingAt(1);
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES))
        );
        for (uint256 i; i < 28; ++i) filler.createAndList(B());
        string memory fx = vm.readFile("test/fixtures/selection.json");
        _replay(fx, "req");
        vm.roll(26_417_091); vm.warp(1_794_705_887);
        vm.setBlockhash(26_417_086, vm.parseJsonBytes32(fx, ".26417086.reqBlockHash"));
        vm.fee(vm.parseJsonUint(fx, ".26417086.fulBaseFee"));
        _replay(fx, "ful");
        (,,,,,,,,,, uint8 a) = FWA.listings(first);
        (,,,,,,,,,, uint8 b) = FWA.listings(second);
        assertEq(a, 1); assertEq(b, 1);
        assertGt(FWA.pendingFees(first), 0);
        assertGt(FWA.pendingFees(second), 0);
        assertEq(FWA.feeCredit(address(vault)), 0);
        p = vault.getParams(); p.maxTip = 0;
        vm.prank(owner); vault.setParams(p);
        // Tiny genuine accruals suffice at one wei. Receipt calibration uses production prices.
        vm.fee(1); vm.txGasPrice(1);
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

    function _fullJob() private {
        JournalRequests f = JournalRequests(address(FWA));
        uint64 deadline;
        uint256 count = 128 - (FWA.nextSequenceToProcess() - vault.acquisitionCursor());
        for (uint256 i; i < count; ++i) {
            (,, uint256 price) = f.quoteAcquisitionPrice();
            vm.prank(bob); f.acquire{value: price}(bob, 1, 0, 0, 10_000);
            (, uint64 until,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
            if (until > deadline) deadline = until;
        }
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(count);
        assertEq(FWA.nextSequenceToProcess() - vault.acquisitionCursor(), 128);
    }

    function _ids() private view returns (uint256[] memory ids) {
        ids = new uint256[](2); ids[0] = first; ids[1] = second;
    }

    function _base() private pure returns (uint256) { return VaultLib.Q_SYNC + 128 * VaultLib.Q_JOURNAL; }

    function _measure(uint256[] memory ids) private returns (uint256 billed) {
        assertTrue(vm.isIsolateMode(), "gas profile needs --isolate");
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(policy); vm.cool(keeper);
        vm.prank(keeper); vault.sync(ids, 0, 0);
        billed = vm.lastCallGas().gasTotalUsed;
    }

    function test_scanIgnoresCashAndClaimsNoActiveFee() public {
        vm.skip(!vm.isIsolateMode());
        _fullJob();
        // Two own listings scan their positions instead of walking the 128-record journal, so a
        // foreign-only sync does no paid work and never reaches the active-fee funding path this
        // test once profiled (Q_FUND + Q_HARVESTED is reachable only with paid own-selection or
        // >= 94-position journal work; see ScanGas.t.sol and the own-selection fee funding). Cash
        // level is therefore irrelevant: with or without cash the scan pays nothing and claims no
        // active fee, so the funding "increment" this test measured is not reachable here.
        uint256[] memory ids = new uint256[](1); ids[0] = first;
        uint256 firstFees = FWA.pendingFees(first);
        uint256 snapshot = vm.snapshotState();
        uint256 withCash = _measure(ids);
        assertEq(FWA.pendingFees(first), firstFees, "scan with cash claims no active fee");
        assertTrue(vm.revertToState(snapshot));
        vm.deal(address(vault), 0);
        uint256 drained = _measure(ids);
        assertEq(FWA.pendingFees(first), firstFees, "scan with no cash still claims no active fee");
        emit log_named_uint("foreign-only scan billed gas with cash", withCash);
        emit log_named_uint("foreign-only scan billed gas drained", drained);
        uint256 delta = withCash > drained ? withCash - drained : drained - withCash;
        assertLe(delta, VaultLib.Q_FUND, "cash level does not engage a funding path");
    }

    function test_profileRefundedRequiredSingletonAfterFundingGate() public {
        vm.skip(!vm.isIsolateMode());
        vault.sync(new uint256[](0), 0, 0);
        JournalRequests f = JournalRequests(address(FWA));
        (, uint64 deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(1);
        assertEq(FWA.nextSequenceToProcess() - vault.acquisitionCursor(), 1);
        uint256 charge = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}();
        toBlackout();
        VaultLib.Params memory p = vault.getParams(); p.maxTip = 0.05 gwei;
        vm.prank(owner); vault.setParams(p);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        uint256 billed = _measure(new uint256[](0));
        emit log_named_uint("required refunded singleton with funding checks isolated billed gas", billed);
        assertLe(billed, VaultLib.Q_REQUIRED_TAIL + VaultLib.Q_JOURNAL);
    }

    function test_distributionTailProvesTheFullCollectionCostBeforePayingIt() public {
        JournalRequests f = JournalRequests(address(FWA));
        (, uint64 deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1); f.processAcquisitions(1);
        vault.sync(new uint256[](0), 0, 0);
        uint256 charge = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}();
        toBlackout(); vault.checkpoint(first, 0);
        vm.prank(owner); vault.startWindDown();
        uint256[] memory one = new uint256[](1); one[0] = first;
        vault.unlist(one, 0);
        uint256 credit = FWA.feeCredit(address(vault));
        assertGt(credit * 2500, VaultLib.Q_CREDIT * 10_000, "real credit is independently economical");
        toOpen();
        (,, uint256 price) = f.quoteAcquisitionPrice();
        vm.prank(bob); f.acquire{value: price}(bob, 1, 0, 0, 10_000);
        (, deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1); f.processAcquisitions(1);
        toBlackout();
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5000;
        vm.prank(owner); vault.setParams(p);
        uint256 cost = VaultLib.Q_REQUIRED_TAIL + VaultLib.Q_DISTRIBUTION_PROOF + VaultLib.Q_JOURNAL;
        uint256 supply = vault.totalShares();
        uint256 target = (vault.highWaterMark() * supply + 1e18 - 1) / 1e18
            + 0.02 ether + cost + VaultLib.Q_CREDIT / 2;
        (uint256 tracked,, uint256 backing,,,) = vault.totals();
        vm.deal(address(vault), target - tracked - backing - FWA.pendingFees(second) - credit);
        assertEq(vault.sync(new uint256[](0), second, 1), cost);
        assertEq(FWA.feeCredit(address(vault)), credit, "extra fee collection would erase the qualifying distribution");
        vault.checkpoint(second, 0);
        assertGe(vault.distributionReserve(), 0.01 ether);
    }

    function test_standaloneHarvestCannotSpendBudgetAndPreservesNav() public {
        vault.sync(new uint256[](0), 0, 0);
        uint256 nav = vault.accountedNav(first);
        uint256 pending = FWA.pendingFees(first);
        (uint256 routine,) = vault.budget();
        uint256[] memory ids = new uint256[](1); ids[0] = first;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.harvest(ids, 1);
        assertEq(FWA.pendingFees(first), pending);
        uint256 cash = address(vault).balance;
        uint256 keeperCash = address(this).balance;
        assertEq(vault.harvest(ids, 0), 0);
        assertEq(address(vault).balance, cash + pending);
        assertEq(address(this).balance, keeperCash);
        (uint256 afterRoutine,) = vault.budget();
        assertEq(afterRoutine, routine);
        assertEq(vault.accountedNav(second), nav);
    }

    function test_ampleCashNeverClaimsActiveFeesForPay() public {
        _fullJob();
        // The 128-record journal that once paid this sync is displaced by a scan of the two own
        // positions. A foreign-only scan outside a checkpoint window applies no own selection and
        // earns nothing, so it cannot claim active fees for pay; the minPay offer is refused and a
        // zero-minPay sync just clears the backlog free. (The paid-journal active-fee funding this
        // test pinned is unreachable for a small vault; it is covered by own-selection work.)
        uint256 pending = FWA.pendingFees(first);
        uint256 debt = vault.position(first).feeDebt;
        uint256 cash = address(vault).balance;
        uint256 keeperCash = address(this).balance;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(_ids(), 0, 1);
        uint256 paid = vault.sync(_ids(), 0, 0);
        assertEq(paid, 0, "foreign-only scan is unpaid");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "one scan clears the backlog");
        assertEq(address(vault).balance, cash, "no vault cash moved");
        assertEq(address(this).balance, keeperCash, "keeper paid nothing");
        assertEq(FWA.pendingFees(first), pending);
        assertEq(vault.position(first).feeDebt, debt);
    }

    function test_cashShortfallScanClaimsNoFeesAndKeepsProtectedCash() public {
        _fullJob();
        uint256 charge = vault.requestCharge();
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}();
        uint256 protectedCash = vault.pendingDepositTotal() + vault.processingPool();
        vm.deal(address(vault), protectedCash);
        // Cash is at the liabilities floor. The 128-record journal that once forced the cash-short
        // funding path (claim only the first useful position's fees) is displaced by a scan of the
        // two own positions; a foreign-only scan does no paid work, so nothing is claimed and the
        // protected cash stands. (The cash-shortfall funding path is reached by paid own-selection
        // or >= 94-position journal work, not by a small foreign-only scan.)
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256 secondDebt = vault.position(second).feeDebt;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(_ids(), 0, 1);
        uint256 paid = vault.sync(_ids(), 0, 0);
        assertEq(paid, 0, "foreign-only scan is unpaid");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "one scan clears the backlog");
        assertEq(FWA.pendingFees(first), firstFees, "no active fee claimed");
        assertEq(FWA.pendingFees(second), secondFees);
        assertEq(vault.position(second).feeDebt, secondDebt);
        assertEq(address(vault).balance, protectedCash, "protected cash untouched");
        assertEq(vault.pendingDepositTotal() + vault.processingPool(), protectedCash);
    }

    function test_irrelevantAndDuplicateIdsDoNotManufacturePay() public {
        _fullJob(); vm.deal(address(vault), 0);
        // With no cash and a foreign-only scan (no own selection, no checkpoint window) there is no
        // paid work for ids to inflate: a lone real id and a 16-slot batch padded with irrelevant
        // and duplicate ids both earn nothing, and both just clear the backlog. The minPay offer is
        // refused either way. (The journal/own-selection funding this guarded is covered there.)
        uint256 snapshot = vm.snapshotState();
        uint256[] memory one = new uint256[](1); one[0] = first;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(one, 0, 1);
        uint256 paid = vault.sync(one, 0, 0);
        assertEq(paid, 0, "lone real id earns nothing from a foreign-only scan");
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory padded = new uint256[](16);
        for (uint256 i; i < padded.length; ++i) padded[i] = i % 2 == 0 ? 1e9 + i : first;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(padded, 0, 1);
        assertEq(vault.sync(padded, 0, 0), paid, "padded ids neither shrink nor inflate the scan pay");
        assertGt(FWA.pendingFees(second), 0, "no active fee claimed");
    }

    function test_optionalTailAndNoProgressCannotCreateFundingWork() public {
        vm.deal(address(vault), 0);
        uint256 pending = FWA.pendingFees(first);
        assertEq(vault.sync(_ids(), 0, 0), 0);
        assertEq(FWA.pendingFees(first), pending);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vault.sync(_ids(), 0, 0);
        assertEq(FWA.pendingFees(first), pending);
    }

    function test_duplicateCannotManufactureScanPayOrClaimFees() public {
        _fullJob(); vm.deal(address(vault), 0);
        // A foreign-only scan over the two own positions does no paid work, so a duplicated id can
        // supply no "second fee balance" to a payment that never happens: the scan pays nothing and
        // claims no fees. (The paid-journal duplicate-id fee gate this test pinned is unreachable
        // for a small vault; its coverage moves to paid own-selection / journal work.)
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256[] memory ids = new uint256[](3); ids[0] = first; ids[1] = first; ids[2] = second;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(ids, 0, 1);
        uint256 paid = vault.sync(ids, 0, 0);
        assertEq(paid, 0, "duplicate ids earn nothing from a foreign-only scan");
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }

    function test_firstCashCoveringPrefixCannotBePaddedToPassTheFeeShareGate() public {
        _fullJob(); vm.deal(address(vault), 0);
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256 price = firstFees / (_base() + VaultLib.Q_FUND + VaultLib.Q_HARVESTED);
        vm.fee(price); vm.txGasPrice(price);
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 350;
        vm.prank(owner); vault.setParams(p);
        assertLt(firstFees * p.keeperShareBps, (VaultLib.Q_FUND + VaultLib.Q_HARVESTED) * price * 10_000);
        assertGe((firstFees + secondFees) * p.keeperShareBps,
            (VaultLib.Q_FUND + 2 * VaultLib.Q_HARVESTED) * price * 10_000);
        assertEq(vault.sync(_ids(), 0, 0), 0);
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }

    function test_budgetPermissionCannotBeReplacedWithFeeIncome() public {
        _fullJob();
        VaultLib.Params memory p = vault.getParams(); p.routineCap = 0; p.routineRate = 0;
        vm.prank(owner); vault.setParams(p);
        vm.deal(address(vault), 0);
        uint256 pending = FWA.pendingFees(first);
        assertEq(vault.sync(_ids(), 0, 0), 0);
        assertEq(FWA.pendingFees(first), pending);
    }

    function test_nonEconomicFundingCannotConsumeFees() public {
        _fullJob();
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 0;
        vm.prank(owner); vault.setParams(p);
        vm.deal(address(vault), 0);
        uint256 pending = FWA.pendingFees(first);
        uint256 secondPending = FWA.pendingFees(second);
        assertEq(vault.sync(_ids(), 0, 0), 0);
        assertEq(FWA.pendingFees(first), pending);
        assertEq(FWA.pendingFees(second), secondPending);
    }

    function test_insufficientRealFeesDoNotCausePartialPaidHarvest() public {
        _fullJob(); vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        vm.deal(address(vault), 0);
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        assertLt(firstFees + secondFees, _base() * 0.5 gwei);
        assertEq(vault.sync(_ids(), 0, 0), 0);
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }
}

contract CompleteCreditTest is SelectionBase {
    receive() external payable {}

    function _selected(uint256 price) private {
        _select(late());
        VaultLib.Params memory p = vault.getParams();
        p.payMarkupBps = 0; p.workFee = 0; p.maxTip = 0;
        vm.prank(vault.owner()); vault.setParams(p);
        vm.fee(price); vm.txGasPrice(price);
    }

    function test_economicCreditIsSweptOnceWithVerifiedOwnWork() public {
        _selected(1);
        uint256 credit = FWA.feeCredit(address(vault));
        uint256 cash = address(vault).balance;
        uint256 paid = vault.sync(new uint256[](0), 0, 1);
        assertEq(paid, VaultLib.Q_SYNC + VaultLib.Q_JOURNAL + VaultLib.Q_SELECTED + VaultLib.Q_CREDIT);
        assertEq(FWA.feeCredit(address(vault)), 0);
        assertEq(address(vault).balance, cash + credit - paid);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vault.sync(new uint256[](0), 0, 0);
    }

    function _measure() private returns (uint256 billed) {
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(policy);
        vault.sync(new uint256[](0), 0, 0);
        billed = vm.lastCallGas().gasTotalUsed;
    }

    function test_profileCreditIncrementAtDiagnosticPrice() public {
        vm.skip(!vm.isIsolateMode());
        _selected(1);
        uint256 snapshot = vm.snapshotState();
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 0;
        vm.prank(vault.owner()); vault.setParams(p);
        uint256 withoutCredit = _measure();
        assertTrue(vm.revertToState(snapshot));
        uint256 withCredit = _measure();
        emit log_named_uint("same own journal job with credit retained billed gas", withoutCredit);
        emit log_named_uint("same own journal job with economical credit swept billed gas", withCredit);
        emit log_named_uint("attached fee credit sweep incremental billed gas", withCredit - withoutCredit);
        assertLe(withCredit - withoutCredit, VaultLib.Q_CREDIT);
    }

    function test_terminalCashPrecedesFeeCollectionAndDustWaitsForCheckpoint() public {
        _selected(0.5 gwei);
        uint256 credit = FWA.feeCredit(address(vault));
        assertLt(credit * 2500 / 10_000, VaultLib.Q_CREDIT * 0.5 gwei);
        vm.prank(late().purchaser); IFwaSettle(address(FWA)).keepNFT(selected);
        uint256 cash = address(vault).balance;
        uint256[] memory ids = new uint256[](1); ids[0] = selected;
        uint256 paid = vault.sync(ids, 0, 1);
        assertEq(paid, (VaultLib.Q_SYNC + VaultLib.Q_JOURNAL + VaultLib.Q_SELECTED
            + VaultLib.Q_SYNCED + VaultLib.Q_PRUNED) * 0.5 gwei);
        assertEq(FWA.feeCredit(address(vault)), credit);
        assertEq(address(vault).balance, cash - paid);
        assertEq(vault.openListingCount(), 0);
    }
}
