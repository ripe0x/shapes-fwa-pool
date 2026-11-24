// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {IFwaSettle} from "./ForkSelection.t.sol";
import {IShapesFeeAdmin} from "./ForkMainConfiguration.t.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {LISTING_ALLOCATED} from "../../src/interfaces/External.sol";

/// @notice The real request/proof at block 26385001 selects slot 339 after thirty .21 ETH listings.
abstract contract MainRenewalBase is ForkBase {
    uint256 internal constant REQUEST_BLOCK = 26_385_001;
    bytes32 internal constant REQUEST_TX = 0xf54ef3743c08e26cc43c125eef04188f114d47d38b9d801c0b56a051a19227ab;
    address internal constant BUYER = address(bytes20(hex"4de365ea3b8e94f30b4d5bfd9d89fae323bee55d"));
    struct ReplayCandidate { uint256 blockNumber; bytes32 requestTx; uint256 count; uint256 index; uint256 slot; address purchaser; }
    uint256 internal fixtureRequestBlock;
    address internal selectedPurchaser;
    uint256 internal selected;
    uint256 internal packId;
    PackAccount internal account;
    address internal accountOwner;

    receive() external payable {}

    function setUp() public virtual override {}

    function parameters() internal pure virtual returns (VaultLib.Params memory p) {
        p = defaultParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        p.renewalMode = VaultLib.RenewalMode.FreshAfterAcquisition;
        p.renewalFloatCount = 1;
        p.upliftBoundBps = 25;
        p.reserve = 0.005 ether;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 2 gwei;
    }

    function one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function backing() internal pure returns (uint256[] memory) { return one(0.21 ether); }

    function _select(bool pooled) internal {
        _selectCandidate(pooled, ReplayCandidate(REQUEST_BLOCK, REQUEST_TX, 30, 24, 339, BUYER));
    }

    function _selectCandidate(bool pooled, ReplayCandidate memory c) internal {
        vm.createSelectFork("mainnet", c.requestTx);
        fixtureRequestBlock = c.blockNumber;
        selectedPurchaser = c.purchaser;
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        accountOwner = makeAddr("pack-vault-test-main-renewal-owner");
        assertEq(accountOwner.code.length, 0);
        assertEq(accountOwner.balance, 0);
        vm.deal(address(this), 30 ether);
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaSettle(address(FWA)).setCollectionsWhitelisted(cols, true);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        if (pooled) {
            account = DeployCore.deploy(FWA, SHAPES, PACKS, accountOwner, parameters(), _initialFunding(), keccak256(abi.encode(parameters(), SHAPES.mintFee(), false, false)));
        } else {
            PackManagerFactory factory = new PackManagerFactory(FWA, SHAPES, PACKS);
            VaultLib.Params memory p = parameters();
            account = factory.create{value: _initialFunding()}(accountOwner, p, factory.configHashFor(p));
        }
        _beforeInitialBuild();
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: _fillerFunding()}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES)));
        for (uint256 i; i < c.count; ++i) {
            if (i == c.index || _additionalBuild(i)) {
                uint256 supply = SHAPES.totalSupply();
                uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
                uint256[] memory initialBacking = _initialBacking(i);
                uint256 initialPay = account.build(3, initialBacking, 0, account.configurationHash());
                _afterInitialBuild(initialPay);
                assertEq(SHAPES.totalSupply() - supply, 3, "account's initial three paid primary mints");
                assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - fees, 0.003 ether);
                if (i == c.index) {
                    selected = account.openListingAt(account.openListingCount() - 1);
                    packId = account.position(selected).packId;
                }
                assertEq(account.position(account.openListingAt(account.openListingCount() - 1)).backing, initialBacking[0]);
            } else filler.createAndList(0.21 ether);
        }
        (,,,,,,,, uint256 slot,,) = FWA.listings(selected);
        assertEq(slot, c.slot, "reconstructed real slot");
        string memory fx = vm.readFile("test/fixtures/completion-selection.json");
        _beforeRequest();
        _call(fx, "req");
        string memory key = string.concat(".", vm.toString(fixtureRequestBlock));
        vm.roll(vm.parseJsonUint(fx, string.concat(key, ".fulBlock")));
        vm.warp(vm.parseJsonUint(fx, string.concat(key, ".fulTimestamp")));
        vm.setBlockhash(fixtureRequestBlock, vm.parseJsonBytes32(fx, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fx, string.concat(key, ".fulBaseFee")));
        _call(fx, "ful");
        for (uint256 i = 2; i <= _fulfillmentCount(); ++i) _call(fx, string.concat("ful", vm.toString(i)));
        (,, address purchaser,,,,,,,, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED, "actual Chainlink proof selected our listing");
        assertEq(purchaser, selectedPurchaser);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function _call(string memory fx, string memory leg) internal {
        string memory key = string.concat(".", vm.toString(fixtureRequestBlock), ".", leg);
        address from = vm.parseJsonAddress(fx, string.concat(key, "From"));
        address to = vm.parseJsonAddress(fx, string.concat(key, "To"));
        bytes memory input = vm.parseJsonBytes(fx, string.concat(key, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req")
            ? vm.parseJsonUint(fx, string.concat(".", vm.toString(fixtureRequestBlock), ".reqValue")) : 0;
        vm.txGasPrice(vm.parseJsonUint(fx, string.concat(key, "GasPrice")));
        vm.prank(from, from);
        (bool ok, bytes memory result) = to.call{value: value}(input);
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
    }

    function _bidAndRecover() internal {
        uint256 paid = account.sync(new uint256[](0), 0, 0, account.configurationHash());
        _traceRenewalStep("allocated", paid);
        assertEq(account.unresolvedUplift(), 0.18 ether, "maximum positive keep uplift uses zero settlement fee");
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _traceRenewalStep("bid", 0);
        account.recover(one(selected), 0);
        _traceRenewalStep("returned", 0);
        assertEq(account.unresolvedUplift(), 0, "exact stored contribution removed at terminal transition");
        assertTrue(account.renewalEligible(packId));
        assertEq(PACKS.ownerOf(packId), address(account));
        _drainOtherRequest();
        _traceRenewalStep("drained", 0);
    }

    function _drainOtherRequest() internal {
        // This historical acquisition submitted two requests. Its other real request expires;
        // the public processor performs the same refund/queue progress production callers use.
        toOpen();
        IFwaSettle(address(FWA)).processAcquisitions(32);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "real queue drained before new exposure");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function _initialFunding() internal pure virtual returns (uint256) { return 3 ether; }
    function _beforeInitialBuild() internal virtual {}
    function _afterInitialBuild(uint256) internal virtual {}
    function _beforeRequest() internal virtual {}
    function _traceRenewalStep(string memory, uint256) internal virtual {}
    function _additionalBuild(uint256) internal view virtual returns (bool) { return false; }
    function _initialBacking(uint256) internal view virtual returns (uint256[] memory) { return backing(); }
    function _fillerFunding() internal view virtual returns (uint256) { return 10 ether; }
    function _fulfillmentCount() internal view virtual returns (uint256) { return 1; }
}

contract ForkMainRenewalTest is MainRenewalBase {
    string constant RENEWAL_TRACE = "sim/out/reconcile-renewal-trace.jsonl";
    string constant FUNDING_TRACE = "sim/out/reconcile-renewal-funding-trace.jsonl";
    bool private traceFresh;
    bool private doubleCredit;
    uint256 private deployBalance;
    uint256 private initialPay;
    uint256 private activationDebt;
    uint256 private initCursor;
    uint256 private acquisitionFee;
    uint256 private acquisitionActive;

    function _additionalBuild(uint256 index) internal view override returns (bool) { return doubleCredit && index == 3; }
    function _initialBacking(uint256 index) internal view override returns (uint256[] memory) {
        return one(0.21 ether + (doubleCredit && index == 6 ? 10_000 : 0));
    }
    function _fillerFunding() internal view override returns (uint256) { return doubleCredit ? 20 ether : 10 ether; }
    function _fulfillmentCount() internal view override returns (uint256) { return doubleCredit ? 5 : 1; }

    function _beforeInitialBuild() internal override {
        if (traceFresh) deployBalance = address(account).balance;
    }

    function _afterInitialBuild(uint256 paid) internal override {
        if (!traceFresh) return;
        initialPay = paid;
        initCursor = account.acquisitionCursor();
        activationDebt = account.position(account.openListingAt(0)).feeDebt;
    }

    function _beforeRequest() internal override {
        if (!traceFresh) return;
        acquisitionFee = FWA.acquisitionFee();
        acquisitionActive = FWA.activeListingCount();
    }

    function _traceRenewalStep(string memory step, uint256 paid) internal override {
        if (!traceFresh) return;
        PackVault v = PackVault(payable(address(account)));
        vm.writeLine(RENEWAL_TRACE, ReconcileTrace.render(v, alice, bob, paid, step));
    }

    function _startTrace() private {
        PackVault v = PackVault(payable(address(account)));
        vm.writeLine(RENEWAL_TRACE, string.concat('{"step":"setup","actors":',
            ReconcileTrace.actors(v, alice, bob, address(this)), ',"deployBalance":', vm.toString(deployBalance),
            ',"selectPay":', vm.toString(initialPay), ',"units":3,"count":1,"backings":[210000000000000000]',
            ',"selectedListing":', vm.toString(selected), ',"activationDebt":', vm.toString(activationDebt),
            ',"initCursor":', vm.toString(initCursor), ',"acqFee":', vm.toString(acquisitionFee),
            ',"acqActive":', vm.toString(acquisitionActive), ',"acqCutBps":', vm.toString(FWA.ownerAcquisitionFeeBps()),
            ',"acqCrownBps":', vm.toString(FWA.topListingShareBps()), ',"liveMintFee":', vm.toString(SHAPES.mintFee()),
            ',"renewalFloat":', vm.toString(v.renewalFloat()), ',"reserve":', vm.toString(v.getParams().reserve), '}'));
        _traceRenewalStep("selected", 0);
    }

    function test_launchVaultBidRetiresAndMintsThreePaidReplacementsExactlyOnce() public {
        traceFresh = true;
        if (vm.exists(RENEWAL_TRACE)) vm.removeFile(RENEWAL_TRACE);
        _select(true);
        _startTrace();
        _bidAndRecover();
        uint256 supply = SHAPES.totalSupply();
        uint256 creatorFees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 cash = address(account).balance;
        uint256 unneededCredit = FWA.feeCredit(address(account));
        uint256 quote = account.renewalQuote(packId, 0, false);
        assertGt(account.renewalQuote(packId, 1, true), quote, "conditional funding work is explicit");
        uint256 paid = account.renew(one(packId), backing(), new uint256[](0), 0, account.configurationHash());
        _traceRenewalStep("renewed", paid);
        assertEq(paid, quote, "actual returned-pack work shares the quote basis");
        assertEq(FWA.feeCredit(address(account)), unneededCredit, "funded renewal does not collect unnecessary fees");
        assertEq(SHAPES.totalSupply(), supply, "burn three old and mint three fresh");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - creatorFees, 0.003 ether);
        assertEq(cash - address(account).balance, 0.003 ether + 0.21 ether + paid,
            "returned .03 principal funds replacement .03 principal exactly");
        assertFalse(account.renewalEligible(packId));
        uint256 newPack = account.position(account.openListingAt(0)).packId;
        assertTrue(newPack != packId);
        uint256[] memory contents = PACKS.contentsOf(newPack);
        assertEq(contents.length, 3);
        bytes32 expected = account.configurationHash();
        vm.expectRevert(StrategyLib.Nothing.selector);
        account.renew(one(packId), backing(), new uint256[](0), 0, expected);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - creatorFees, 0.003 ether);
    }

    function test_managerRenewalCollectsRealCreditOnlyWhenCashNeedsItAndPermissionAllows() public {
        doubleCredit = true;
        _selectCandidate(false, ReplayCandidate(26_272_979,
            0x1adee9be0b88eb3ca2176e0b19ec408bd34907df93a34122c86212902942fe88,
            72, 6, 539, address(bytes20(hex"184b487d36aea8aa5990569c326c269de246179a"))));
        uint256 other = account.openListingAt(0);
        uint256 otherPack = account.position(other).packId;
        uint256 otherBacking = account.position(other).backing;
        uint256 selectedBacking = account.position(selected).backing;
        account.recover(new uint256[](0), 0);
        uint256[] memory acquired = new uint256[](2);
        acquired[0] = selected;
        acquired[1] = other;
        for (uint256 i; i < acquired.length; ++i) {
            vm.prank(selectedPurchaser);
            IFwaSettle(address(FWA)).acceptDepositorBid(acquired[i]);
        }
        account.recover(acquired, 0);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "five genuine proofs complete before renewal");
        assertTrue(account.renewalEligible(otherPack), "second real acquisition retains its own eligibility");
        PackManager manager = PackManager(payable(address(account)));
        // The real keeper chooses the last eligible idle pack; equal faces must retain their
        // own stored backing quotes rather than swapping same-value inventory in the model.
        uint256 renewalPack = manager.idlePackAt(manager.idlePackCount() - 1);
        uint256 waitingPack = renewalPack == packId ? otherPack : packId;
        VaultLib.Params memory reserveConfig = manager.getParams();
        reserveConfig.reserve = 0;
        bytes32 reserveExpected = manager.configurationHash();
        vm.prank(accountOwner);
        manager.setParams(reserveConfig, reserveExpected);
        uint256 credit = FWA.feeCredit(address(manager));
        uint256 bare = manager.renewalQuote(renewalPack, 0, false);
        uint256 funded = manager.renewalQuote(renewalPack, 0, true);
        assertGt(credit / 2, funded - bare, "actual protocol credit can cover the genuine collection cost");
        uint256 targetCash = manager.getParams().reserve + 0.213 ether + funded - credit / 2;
        vm.prank(accountOwner);
        manager.withdraw(accountOwner, address(manager).balance - targetCash);
        assertLt(manager.renewalCash() + 0.03 ether, 0.243 ether + bare,
            "owner's actual withdrawal leaves a visible renewal cash shortfall");
        uint256 snapshot = vm.snapshotState();
        VaultLib.Params memory p = manager.getParams();
        p.routineCap = 0;
        p.routineRate = 0;
        bytes32 expected = manager.configurationHash();
        vm.prank(accountOwner);
        manager.setParams(p, expected);
        expected = manager.configurationHash();
        uint256 supply = SHAPES.totalSupply();
        vm.expectRevert(StrategyLib.Payment.selector);
        manager.renew(one(renewalPack), backing(), new uint256[](0), 0, expected);
        assertEq(FWA.feeCredit(address(manager)), credit, "permission failure cannot consume credit");
        assertEq(SHAPES.totalSupply(), supply, "permission failure rolls back retirement and paid mints");
        assertTrue(vm.revertToState(snapshot));
        uint256 before = address(manager).balance;
        uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        if (vm.exists(FUNDING_TRACE)) vm.removeFile(FUNDING_TRACE);
        uint256[] memory values = new uint256[](2);
        uint256[] memory shapes = new uint256[](2);
        uint256[] memory oldQuotes = new uint256[](2);
        for (uint256 i; i < 2; ++i) {
            uint256 id = manager.idlePackAt(i);
            values[i] = manager.idleValueOf(id);
            shapes[i] = manager.inventoryShapeCount(id);
            oldQuotes[i] = id == packId ? selectedBacking : otherBacking;
        }
        vm.writeLine(FUNDING_TRACE, string.concat('{"step":"inputs","idleValues":', ReconcileTrace.uints(values),
            ',"idleShapes":', ReconcileTrace.uints(shapes), ',"idleQuotes":', ReconcileTrace.uints(oldQuotes),
            ',"mintFee":', vm.toString(SHAPES.mintFee()), ',"bareQuote":', vm.toString(bare),
            ',"fundedQuote":', vm.toString(funded), ',"feeShareBps":', vm.toString(manager.getParams().keeperShareBps),
            ',"params":"', vm.toString(abi.encode(manager.getParams())), '","baseFee":', vm.toString(block.basefee),
            ',"gasPrice":', vm.toString(tx.gasprice), '}'));
        vm.writeLine(FUNDING_TRACE, ReconcileTrace.renderStrategy(manager, 0, 0, "before"));
        assertEq(manager.keeperCash(), 0, "renewal compensation is deliberately inside the designated float");
        uint256 paid = manager.renew(one(renewalPack), backing(), new uint256[](0), funded, manager.configurationHash());
        vm.writeLine(FUNDING_TRACE, ReconcileTrace.renderStrategy(manager, paid,
            IShapesFeeAdmin(address(SHAPES)).pendingFees() - fees, "after"));
        assertEq(paid, funded, "conditional collection uses the same configured payment calculation");
        assertEq(FWA.feeCredit(address(manager)), 0, "real accrued credit is collected");
        assertEq(before + credit - address(manager).balance, 0.213 ether + paid,
            "actual returned principal funds replacement principal, with no synthetic cash");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - fees, 0.003 ether);
        assertFalse(manager.renewalEligible(renewalPack));
        assertTrue(manager.renewalEligible(waitingPack), "one float cannot consume another acquisition's permission");
        expected = manager.configurationHash();
        uint256[] memory secondBacking = one(0.21 ether + 10_000);
        vm.expectRevert(StrategyLib.Payment.selector);
        manager.renew(one(waitingPack), secondBacking, new uint256[](0), 0, expected);
        assertTrue(manager.renewalEligible(waitingPack), "cash wait preserves delayed replacement eligibility");
    }

    function test_managerReuseModeRelistsReturnedPackWithoutPaidFreshMints() public {
        _select(false);
        _bidAndRecover();
        VaultLib.Params memory p = account.getParams();
        p.renewalMode = VaultLib.RenewalMode.ReuseReturned;
        bytes32 expected = account.configurationHash();
        vm.prank(accountOwner);
        account.setParams(p, expected);
        uint256 supply = SHAPES.totalSupply();
        uint256 creatorFees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        account.list(backing(), 0, account.configurationHash());
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), creatorFees);
        assertEq(account.position(account.openListingAt(0)).packId, packId);
        assertFalse(account.renewalEligible(packId));
    }

    function test_managerKeepCreatesOnlyOnePaidReplacementPermission() public {
        _select(false);
        account.sync(new uint256[](0), 0, 0, account.configurationHash());
        uint256 cash = address(account).balance;
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        assertEq(address(account).balance - cash, 0.21 ether * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000);
        account.recover(one(selected), 0);
        assertEq(account.unresolvedUplift(), 0);
        (, uint256 kept,,) = account.renewalState();
        assertEq(kept, 1);
        _drainOtherRequest();
        uint256 supply = SHAPES.totalSupply();
        uint256 creatorFees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 quote = account.renewalQuote(0, 0, false);
        uint256 paid = account.renew(one(0), backing(), new uint256[](0), 0, account.configurationHash());
        assertEq(paid, quote, "kept replacement quote excludes retirement");
        assertEq(SHAPES.totalSupply() - supply, 3);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - creatorFees, 0.003 ether);
        (, kept,,) = account.renewalState();
        assertEq(kept, 0);
        bytes32 expected = account.configurationHash();
        vm.expectRevert(StrategyLib.Nothing.selector);
        account.renew(one(0), backing(), new uint256[](0), 0, expected);
        assertEq(PACKS.ownerOf(packId), selectedPurchaser);
    }

    function test_exitInventoryNeverCreatesFreshReplacement() public {
        _select(false);
        _bidAndRecover();
        PackManager m = PackManager(payable(address(account)));
        vm.prank(accountOwner);
        m.setExiting(true);
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 cash = address(account).balance;
        account.recoverLiquidate(1);
        assertEq(supply - SHAPES.totalSupply(), 3);
        assertEq(address(account).balance - cash, 0.03 ether);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), fees);
        assertFalse(account.renewalEligible(packId));
        (uint256 eligible, uint256 kept,,) = account.renewalState();
        assertEq(eligible, 0);
        assertEq(kept, 0);
        bytes32 expected = account.configurationHash();
        vm.expectRevert(StrategyLib.WindingDown.selector);
        account.renew(one(packId), backing(), new uint256[](0), 0, expected);
    }
}
