// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MeasuredPay} from "../utils/MeasuredPay.sol";

import {GasQuotes} from "../utils/GasQuotes.sol";

import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {JournalRequests} from "./EfficientJournal.t.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

/// @notice Real fees from a recorded Chainlink fulfillment. Exact opening funding is spent
///         through real paid mints and FWA listings, leaving no fabricated liquidity shortfall.
contract CompleteHarvestTest is ForkBase {
    uint256 first;
    uint256 second;

    receive() external payable {}

    function seedTwoListings() external returns (uint256) {
        // build mints and lists both 6-unit packs at once; no idle pack remains to relist.
        return TestVaultOps.restock(vault, 2, UNITS, 0);
    }

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
        // D62: ShapePacks oracle-exempt (the real admin call) so a 0.06 ETH pack lists uncapped.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        VaultLib.Params memory p = defaultParams();
 p.workFee = 0; p.reserve = 0; p.gasCeiling = 0.5 gwei;
        // E2 made measured keeper gas accurate, now below the default build quote, so a build would
        // pay less than the quote and leave surplus free eth. This fixture's tests require the cash
        // floor its comments name ("real construction spends exact opening cash", "cash shortage
        // reached through actual construction"), so tighten the seed build's keeper quote below the
        // measured two-pack work: the pay saturates the funding cap and construction spends all
        // provisioned cash, exactly as the original (pre-E2) saturated build did.
        p.gasSchedule.listed = 750_000; // baseGas 2,980,000 < measured 3,082,166, so the seed build saturates
        uint256 baseGas = uint256(p.gasSchedule.build) + 2 * (uint256(p.gasSchedule.buildPack)
            + 2 * p.gasSchedule.buildShape + p.gasSchedule.listed);
        uint256 exactOpening = 2 * (P + FEE_PER_PACK + P * p.backingRatioBps / 10_000)
            + (baseGas + p.gasSchedule.overhead) * 0.2 gwei + 10_000; // second live backing needs its own 10,000-wei tag
        address predicted = vm.computeCreateAddress(address(this), vm.getNonce(address(this)));
        uint256 dust = predicted.balance;
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, exactOpening - dust, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        // External self-call: keeps restock/list out of setUp's stack frame (via_ir stack depth).
        vm.recordLogs();
        uint256 seedPay = this.seedTwoListings();
        assertEq(seedPay, MeasuredPay.gross(vault, baseGas, 4, false, 0.2 gwei));
        assertEq(seedPay, (baseGas + p.gasSchedule.overhead) * 0.2 gwei, "real two-pack work saturates the funding fixture cap");
        assertEq(vault.freeEth(), 0, "real construction spends exact opening cash");
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
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected0);
        // Tiny genuine accruals suffice at one wei. Receipt calibration uses production prices.
        vm.fee(1); vm.txGasPrice(1);
        vm.recordLogs();
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

    function _base() private pure returns (uint256) { return GasQuotes.Q_SYNC + 128 * GasQuotes.Q_JOURNAL; }

    function _measure(uint256[] memory ids) private returns (uint256 billed) {
        assertTrue(vm.isIsolateMode(), "gas profile needs --isolate");

        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(keeper);
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper); vault.sync(ids, 0, 0, _expected1);
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
        uint256 drained = _measure(ids);
        assertEq(FWA.pendingFees(first), firstFees, "scan without cash claims no active fee");
        assertTrue(vm.revertToState(snapshot));
        TestVaultOps.fundTo(vault, 0.1 ether);
        uint256 withCash = _measure(ids);
        assertEq(FWA.pendingFees(first), firstFees, "scan with no cash still claims no active fee");
        emit log_named_uint("foreign-only scan billed gas with cash", withCash);
        emit log_named_uint("foreign-only scan billed gas drained", drained);
        uint256 delta = withCash > drained ? withCash - drained : drained - withCash;
        assertLe(delta, GasQuotes.Q_FUND, "cash level does not engage a funding path");
    }

    function test_profileRefundedRequiredSingletonAfterFundingGate() public {
        vm.skip(!vm.isIsolateMode());
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected2);
        JournalRequests f = JournalRequests(address(FWA));
        (, uint64 deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1);
        f.processAcquisitions(1);
        assertEq(FWA.nextSequenceToProcess() - vault.acquisitionCursor(), 1);
        uint256 charge = vault.requestCharge();
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}(_expected3);
        toBlackout();
        VaultLib.Params memory p = vault.getParams(); p.maxTip = 0.05 gwei;
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected4);
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(keeper);
        bytes32 expected = vault.configurationHash();
        vm.prank(keeper);
        uint256 paid = vault.syncCheckpoint(new uint256[](0), first, 1, expected);
        uint256 billed = vm.lastCallGas().gasTotalUsed;
        assertGt(paid, 0, "required holder work is paid from explicit contributions");
        emit log_named_uint("contribution-funded required refunded singleton isolated billed gas", billed);
        assertLe(billed, GasQuotes.Q_REQUIRED_TAIL + GasQuotes.Q_JOURNAL + p.gasSchedule.overhead,
            "candidate allowance plus named transaction tail covers this actual receipt");
    }

    function test_distributionTailProvesTheFullCollectionCostBeforePayingIt() public {
        JournalRequests f = JournalRequests(address(FWA));
        (, uint64 deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1); f.processAcquisitions(1);
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected5);
        uint256 charge = vault.requestCharge();
        bytes32 _expected7 = TestVaultOps.configurationHash(vault);
        bytes32 _expected6 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}(_expected6);
        toBlackout(); vault.checkpoint(first, 0, _expected7);
        vm.prank(owner); vault.startWindDown();
        uint256[] memory one = new uint256[](1); one[0] = first;
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vault.unlist(one, 0, _expected8);
        uint256 credit = FWA.feeCredit(address(vault));
        assertGt(credit * 2500, GasQuotes.Q_CREDIT * 10_000, "real credit is independently economical");
        toOpen();
        (,, uint256 price) = f.quoteAcquisitionPrice();
        vm.prank(bob); f.acquire{value: price}(bob, 1, 0, 0, 10_000);
        (, deadline,,,,) = f.acquisitionMeta(FWA.requestIdAtSequence(FWA.lastIssuedSequence()));
        vm.roll(uint256(deadline) + 1); f.processAcquisitions(1);
        toBlackout();
        VaultLib.Params memory p = vault.getParams(); p.distributionBps = 5000;


        bytes32 _expected9 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected9);
        uint256 allowance = GasQuotes.Q_REQUIRED_TAIL + GasQuotes.Q_DISTRIBUTION_PROOF + GasQuotes.Q_JOURNAL;
        uint256 cost = allowance + p.gasSchedule.overhead;
        uint256 supply = vault.totalShares();
        uint256 target = (vault.highWaterMark() * supply + 1e18 - 1) / 1e18
            + 0.02 ether + cost + GasQuotes.Q_CREDIT / 2;
        (uint256 tracked,, uint256 backing,,,) = vault.totals();
        // E2: the earlier committing checkpoint now pays its measured work (below the charge) and
        // leaves the unused charge in chargeRefundReserve, a liability excluded from NAV and free
        // eth. fundTo targets NAV, so add that reserve back or the vault funds short of the gain
        // and liquidity the distribution tail needs to qualify.
        TestVaultOps.fundTo(vault,
            target - tracked - backing - FWA.pendingFees(second) - credit + vault.chargeRefundReserve());
        bytes32 _expected10 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), second, 1, _expected10);
        assertEq(paid, MeasuredPay.gross(vault, allowance, 0, false, 1));
        assertLe(paid, cost);
        assertEq(FWA.feeCredit(address(vault)), credit, "extra fee collection would erase the qualifying distribution");
        bytes32 _expected11 = TestVaultOps.configurationHash(vault);
        assertGt(vault.checkpoint(second, 1, _expected11), 0,
            "wind-down distribution uses routine permission, not the empty essential budget");
        assertGe(vault.distributionReserve(), 0.01 ether);
    }

    function test_standaloneHarvestCannotSpendBudgetAndPreservesNav() public {
        bytes32 _expected12 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected12);
        uint256 nav = vault.accountedNav(first);
        uint256 pending = FWA.pendingFees(first);
        uint256 routine = vault.budget();
        uint256[] memory ids = new uint256[](1); ids[0] = first;
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.harvest(ids, 1);
        assertEq(FWA.pendingFees(first), pending);
        uint256 cash = address(vault).balance;
        uint256 keeperCash = address(this).balance;
        assertEq(vault.harvest(ids, 0), 0);
        assertEq(address(vault).balance, cash + pending);
        assertEq(address(this).balance, keeperCash);
        uint256 afterRoutine = vault.budget();
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
        bytes32 _expected13 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(_ids(), 0, 1, _expected13);
        bytes32 _expected14 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(_ids(), 0, 0, _expected14);
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
        bytes32 _expected15 = TestVaultOps.configurationHash(vault);
        vm.prank(alice); vault.deposit{value: 0.1 ether + charge}(_expected15);
        uint256 protectedCash = vault.pendingDepositTotal() + vault.processingPool();
        assertEq(address(vault).balance, protectedCash, "escrow and sponsorship are the entire real balance");
        // Cash is at the liabilities floor. The 128-record journal that once forced the cash-short
        // funding path (claim only the first useful position's fees) is displaced by a scan of the
        // two own positions; a foreign-only scan does no paid work, so nothing is claimed and the
        // protected cash stands. (The cash-shortfall funding path is reached by paid own-selection
        // or >= 94-position journal work, not by a small foreign-only scan.)
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256 secondDebt = vault.position(second).feeDebt;
        bytes32 _expected16 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(_ids(), 0, 1, _expected16);
        bytes32 _expected17 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(_ids(), 0, 0, _expected17);
        assertEq(paid, 0, "foreign-only scan is unpaid");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess(), "one scan clears the backlog");
        assertEq(FWA.pendingFees(first), firstFees, "no active fee claimed");
        assertEq(FWA.pendingFees(second), secondFees);
        assertEq(vault.position(second).feeDebt, secondDebt);
        assertEq(address(vault).balance, protectedCash, "protected cash untouched");
        assertEq(vault.pendingDepositTotal() + vault.processingPool(), protectedCash);
    }

    function test_irrelevantAndDuplicateIdsDoNotManufacturePay() public {
        _fullJob(); assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        // With no cash and a foreign-only scan (no own selection, no checkpoint window) there is no
        // paid work for ids to inflate: a lone real id and a 16-slot batch padded with irrelevant
        // and duplicate ids both earn nothing, and both just clear the backlog. The minPay offer is
        // refused either way. (The journal/own-selection funding this guarded is covered there.)
        uint256 snapshot = vm.snapshotState();
        uint256[] memory one = new uint256[](1); one[0] = first;
        bytes32 _expected18 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(one, 0, 1, _expected18);
        bytes32 _expected19 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(one, 0, 0, _expected19);
        assertEq(paid, 0, "lone real id earns nothing from a foreign-only scan");
        assertTrue(vm.revertToState(snapshot));
        uint256[] memory padded = new uint256[](16);
        for (uint256 i; i < padded.length; ++i) padded[i] = i % 2 == 0 ? 1e9 + i : first;
        bytes32 _expected20 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(padded, 0, 1, _expected20);
        bytes32 _expected21 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(padded, 0, 0, _expected21), paid, "padded ids neither shrink nor inflate the scan pay");
        assertGt(FWA.pendingFees(second), 0, "no active fee claimed");
    }

    function test_optionalTailAndNoProgressCannotCreateFundingWork() public {
        assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        uint256 pending = FWA.pendingFees(first);
        bytes32 _expected22 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(_ids(), 0, 0, _expected22), 0);
        assertEq(FWA.pendingFees(first), pending);
        bytes32 _expected23 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vault.sync(_ids(), 0, 0, _expected23);
        assertEq(FWA.pendingFees(first), pending);
    }

    function test_duplicateCannotManufactureScanPayOrClaimFees() public {
        _fullJob(); assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        // A foreign-only scan over the two own positions does no paid work, so a duplicated id can
        // supply no "second fee balance" to a payment that never happens: the scan pays nothing and
        // claims no fees. (The paid-journal duplicate-id fee gate this test pinned is unreachable
        // for a small vault; its coverage moves to paid own-selection / journal work.)
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256[] memory ids = new uint256[](3); ids[0] = first; ids[1] = first; ids[2] = second;
        bytes32 _expected24 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Payment.selector);
        vault.sync(ids, 0, 1, _expected24);
        bytes32 _expected25 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(ids, 0, 0, _expected25);
        assertEq(paid, 0, "duplicate ids earn nothing from a foreign-only scan");
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }

    function test_firstCashCoveringPrefixCannotBePaddedToPassTheFeeShareGate() public {
        _fullJob(); assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        uint256 price = firstFees / (_base() + GasQuotes.Q_FUND + GasQuotes.Q_HARVESTED);
        vm.fee(price); vm.txGasPrice(price);
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 350;
        bytes32 _expected26 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected26);
        assertLt(firstFees * p.keeperShareBps, (GasQuotes.Q_FUND + GasQuotes.Q_HARVESTED) * price * 10_000);
        assertGe((firstFees + secondFees) * p.keeperShareBps,
            (GasQuotes.Q_FUND + 2 * GasQuotes.Q_HARVESTED) * price * 10_000);
        bytes32 _expected27 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(_ids(), 0, 0, _expected27), 0);
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }

    function test_budgetPermissionCannotBeReplacedWithFeeIncome() public {
        _fullJob();
        VaultLib.Params memory p = vault.getParams(); p.routineCap = 0; p.routineRate = 0;
        bytes32 _expected28 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected28);
        assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        uint256 pending = FWA.pendingFees(first);
        bytes32 _expected29 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(_ids(), 0, 0, _expected29), 0);
        assertEq(FWA.pendingFees(first), pending);
    }

    function test_nonEconomicFundingCannotConsumeFees() public {
        _fullJob();
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 0;
        bytes32 _expected30 = TestVaultOps.configurationHash(vault);
        vm.prank(owner); vault.setParams(p, _expected30);
        assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        uint256 pending = FWA.pendingFees(first);
        uint256 secondPending = FWA.pendingFees(second);
        bytes32 _expected31 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(_ids(), 0, 0, _expected31), 0);
        assertEq(FWA.pendingFees(first), pending);
        assertEq(FWA.pendingFees(second), secondPending);
    }

    function test_insufficientRealFeesDoNotCausePartialPaidHarvest() public {
        _fullJob(); vm.fee(0.5 gwei); vm.txGasPrice(0.5 gwei);
        assertEq(vault.freeEth(), 0, "cash shortage reached through actual construction");
        uint256 firstFees = FWA.pendingFees(first);
        uint256 secondFees = FWA.pendingFees(second);
        assertLt(firstFees + secondFees, _base() * 0.5 gwei);
        bytes32 _expected32 = TestVaultOps.configurationHash(vault);
        assertEq(vault.sync(_ids(), 0, 0, _expected32), 0);
        assertEq(FWA.pendingFees(first), firstFees);
        assertEq(FWA.pendingFees(second), secondFees);
    }
}

contract CompleteCreditTest is SelectionBase {
    receive() external payable {}

    function _selected(uint256 price) private {
        _select(primary());
        VaultLib.Params memory p = vault.getParams();
 p.workFee = 0; p.maxTip = 0;
        bytes32 _expected33 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected33);
        vm.fee(price); vm.txGasPrice(price);
        vm.recordLogs();
    }

    function test_economicCreditIsSweptOnceWithVerifiedOwnWork() public {
        _selected(1);
        uint256 credit = FWA.feeCredit(address(vault));
        uint256 cash = address(vault).balance;
        bytes32 _expected34 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(new uint256[](0), 0, 1, _expected34);
        assertEq(paid, MeasuredPay.gross(vault, GasQuotes.Q_SYNC + GasQuotes.Q_JOURNAL + GasQuotes.Q_SELECTED + GasQuotes.Q_CREDIT, 0, false, 1));
        assertEq(FWA.feeCredit(address(vault)), 0);
        assertEq(address(vault).balance, cash + credit - paid);
        bytes32 _expected35 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(StrategyLib.Nothing.selector);
        vault.sync(new uint256[](0), 0, 0, _expected35);
    }

    function _measure() private returns (uint256 billed) {
        bytes32 _expected36 = TestVaultOps.configurationHash(vault);

        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vault.sync(new uint256[](0), 0, 0, _expected36);
        billed = vm.lastCallGas().gasTotalUsed;
    }

    function test_profileCreditIncrementAtDiagnosticPrice() public {
        vm.skip(!vm.isIsolateMode());
        _selected(1);
        uint256 snapshot = vm.snapshotState();
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 0;
        bytes32 _expected37 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected37);
        uint256 withoutCredit = _measure();
        assertTrue(vm.revertToState(snapshot));
        uint256 withCredit = _measure();
        emit log_named_uint("same own journal job with credit retained billed gas", withoutCredit);
        emit log_named_uint("same own journal job with economical credit swept billed gas", withCredit);
        emit log_named_uint("attached fee credit sweep incremental billed gas", withCredit - withoutCredit);
        assertLe(withCredit - withoutCredit, GasQuotes.Q_CREDIT);
    }

    function test_terminalCashPrecedesFeeCollectionAndDustWaitsForCheckpoint() public {
        _selected(0.5 gwei);
        // This fixture's selection credits enough fee that at the default keeper share the sync would
        // economically sweep it; lower the share so the keeper is paid purely from the kept terminal
        // cash and the credit genuinely waits for the checkpoint (the invariant under test).
        VaultLib.Params memory p = vault.getParams(); p.keeperShareBps = 350;
        bytes32 _expected38 = TestVaultOps.configurationHash(vault);
        vm.prank(vault.owner()); vault.setParams(p, _expected38);
        uint256 credit = FWA.feeCredit(address(vault));
        assertLt(credit * p.keeperShareBps / 10_000, GasQuotes.Q_CREDIT * 0.5 gwei);
        vm.prank(primary().purchaser); IFwaSettle(address(FWA)).keepNFT(selected);
        uint256 cash = address(vault).balance;
        uint256[] memory ids = new uint256[](1); ids[0] = selected;
        bytes32 _expected39 = TestVaultOps.configurationHash(vault);
        uint256 paid = vault.sync(ids, 0, 1, _expected39);
        assertEq(paid, MeasuredPay.gross(vault, GasQuotes.Q_SYNC + GasQuotes.Q_JOURNAL + GasQuotes.Q_SELECTED
            + GasQuotes.Q_SYNCED + GasQuotes.Q_PRUNED, 1, false, 0.5 gwei));
        assertEq(FWA.feeCredit(address(vault)), credit);
        assertEq(address(vault).balance, cash - paid);
        assertEq(vault.openListingCount(), 0);
    }
}
