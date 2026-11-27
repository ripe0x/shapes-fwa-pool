// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ANY_DESIGN} from "../utils/TestVaultOps.sol";
import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {IFwaSettle} from "./ForkSelection.t.sol";
import {Vm} from "forge-std/Vm.sol";
import {Ownable} from "solady/auth/Ownable.sol";

interface IShapesFeeAdmin {
    function admin() external view returns (address);
    function setMintFee(uint256 fee) external;
    function pendingFees() external view returns (uint256);
}

/// @notice Real Shapes/FWA paths; fee changes are confined to this isolated fork.
contract ForkMainConfigurationTest is ForkBase {
    receive() external payable {}

    function setUp() public override {
        vm.createSelectFork("mainnet", BLOCK);
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0, "fresh actor code");
            assertEq(actors[i].balance, 0, "fresh actor balance");
        }
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
    }

    function launchParams() internal pure returns (VaultLib.Params memory p) {
        p = defaultParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        p.upliftBoundBps = 25;
        p.reserve = 0.005 ether;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 2 gwei;

    }

    function manager() internal returns (PackManager m) {
        PackManagerFactory factory = new PackManagerFactory(FWA, SHAPES, PACKS);
        VaultLib.Params memory p = launchParams();
        m = factory.create{value: 2 ether}(owner, p, ANY_DESIGN, factory.configHashFor(p));
        assertEq(m.owner(), owner, "factory preserves individual ownership");
        assertEq(m.referenceUnits(), 3);
        assertEq(m.referencePositionValue(), 0.24 ether);
    }

    function proposal() internal pure returns (uint256[] memory values) {
        values = new uint256[](1);
        values[0] = 0.21 ether;
    }

    function set(PackManager m, VaultLib.Params memory p) internal {
        bytes32 expected = m.configurationHash();
        vm.prank(owner);
        m.setParams(p, expected);
    }

    function buildInRealFeeContext(PackManager m, uint256[] calldata values, bytes32 expected)
        external returns (uint256)
    {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.15 gwei, "executed basefee");
        assertEq(tx.gasprice, 0.2 gwei, "executed gas price");
        return m.build(3, values, 0, expected);
    }

    function test_launchManagerPaysThreePrimaryMintFeesAndConsistentMarkup() public {
        PackManager m = manager();
        assertEq(SHAPES.mintFee(), 0.001 ether, "pinned baseline primary fee");
        VaultLib.Params memory p = m.getParams();
        uint256 supply = SHAPES.totalSupply();
        uint256 creatorFees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 balance = address(m).balance;
        uint256 quoteGas = uint256(p.gasSchedule.build) + p.gasSchedule.buildPack
            + 3 * p.gasSchedule.buildShape + p.gasSchedule.listed;
        uint256 expectedPay = (quoteGas + p.gasSchedule.overhead) * 0.2 gwei + 2 * p.workFee;
        uint256 paid = this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        assertLe(paid, expectedPay, "measured routine pay stays inside the work cap");
        assertGt(paid, 2 * p.workFee, "real paid work reimburses positive measured gas");
        assertEq(SHAPES.totalSupply() - supply, 3, "three fresh primary mints");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - creatorFees, 0.003 ether,
            "creator receives exactly three paid mint fees");
        assertGt(0.21 ether * FWA.settlementDiscountBps() / 10_000, 0.03 ether,
            "admission succeeds when the purchaser bid exceeds pack principal");
        uint256 id = m.openListingAt(0);
        VaultLib.Position memory pos = m.position(id);
        uint256[] memory contents = PACKS.contentsOf(pos.packId);
        assertEq(contents.length, 3);
        for (uint256 i; i < contents.length; ++i) assertEq(SHAPES.backingOf(contents[i]), 0.01 ether);
        assertEq(balance - address(m).balance, 0.03 ether + 0.003 ether + 0.21 ether + paid);
        assertGe(m.freeEth(), m.operatingReserve(), "growth leaves float and maintenance cash");
    }

    function test_freshBuildLimitIsIndependentOfListingAndEconomicLimits() public {
        PackManager m = manager();
        assertEq(m.MAX_BUILD_BATCH(), 4);
        assertEq(m.MAX_LIST_BATCH(), 8);
        uint256[] memory backingValues = new uint256[](5);
        for (uint256 i; i < backingValues.length; ++i) backingValues[i] = 0.21 ether + i * 10_000;
        uint256 supply = SHAPES.totalSupply();
        bytes32 expected = m.configurationHash();
        vm.expectRevert(VaultLib.BadBatch.selector);
        m.build(3, backingValues, 0, expected);
        assertEq(SHAPES.totalSupply(), supply, "oversized mint batch fails before primary mints");
    }

    function test_exitWorkIsUnpaidAndNonzeroMinPayReverts() public {
        PackManager m = manager();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256[] memory ids = new uint256[](1);
        ids[0] = m.openListingAt(0);
        vm.warp(vm.getBlockTimestamp() + 13 hours);
        vm.prank(owner);
        m.setExiting(true);
        // Exit work is unpaid: a nonzero minPay reverts before the work.
        uint256 fee = m.getParams().workFee;
        bytes32 h = m.configurationHash();
        vm.expectRevert(VaultLib.Payment.selector);
        m.unlist(ids, fee, h);
        // The same unlist runs unpaid at minPay 0, then the freed pack liquidates unpaid too.
        assertEq(m.unlist(ids, 0, m.configurationHash()), 0, "exit unlist pays nothing");
        assertEq(m.liquidate(16, 0, m.configurationHash()), 0, "exit liquidation pays nothing");
        assertEq(m.openListingCount() + m.idlePackCount(), 0, "the exit still completes");
    }

    function test_staleConfigurationFailsBeforeAnyMintOrCapitalCommitment() public {
        PackManager m = manager();
        bytes32 stale = m.configurationHash();
        VaultLib.Params memory p = m.getParams();
        p.gasSchedule.buildShape += 1_000;
        set(m, p);
        uint256 supply = SHAPES.totalSupply();
        uint256 balance = address(m).balance;
        vm.expectRevert(PackAccount.ConfigurationChanged.selector);
        m.build(3, proposal(), 0, stale);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(address(m).balance, balance);
        assertEq(m.openListingCount(), 0);
    }

    function test_feeIncreaseNeedsExplicitAcceptanceAndDecreasePaysActualFee() public {
        PackManager m = manager();
        IShapesFeeAdmin fees = IShapesFeeAdmin(address(SHAPES));
        bytes32 stale = m.configurationHash();
        vm.prank(fees.admin());
        fees.setMintFee(0.0015 ether);
        vm.expectRevert(PackAccount.ConfigurationChanged.selector);
        m.build(3, proposal(), 0, stale);
        VaultLib.Params memory p = m.getParams();
        p.workFee += 1;
        set(m, p);
        assertEq(m.getParams().acceptedMintFee, 0.001 ether, "unrelated settings never accept increased fees");
        bytes32 current = m.configurationHash();
        vm.expectRevert(VaultLib.MintFeeNotAccepted.selector);
        m.build(3, proposal(), 0, current);
        bytes32 expected = m.configurationHash();
        vm.prank(owner);
        m.acceptMintFee(0.0015 ether, expected);
        uint256 creator = fees.pendingFees();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        assertEq(fees.pendingFees() - creator, 0.0045 ether);
        vm.prank(fees.admin());
        fees.setMintFee(0.0005 ether);
        creator = fees.pendingFees();
        uint256[] memory another = proposal();
        another[0] += 10_000; // each open backing identifier is unique
        this.buildInRealFeeContext(m, another, m.configurationHash());
        assertEq(fees.pendingFees() - creator, 0.0015 ether, "actual decreased fee paid, never accepted maximum");
        assertEq(m.getParams().acceptedMintFee, 0.0015 ether);
    }

    function test_unrelatedSettingsCannotChangeAcceptedMintFee() public {
        PackManager m = manager();
        VaultLib.Params memory p = m.getParams();
        p.acceptedMintFee += 1;
        bytes32 expected = m.configurationHash();
        vm.prank(owner);
        vm.expectRevert(PackAccount.ExplicitFeeAcceptanceRequired.selector);
        m.setParams(p, expected);
    }

    function test_gasScheduleBuildCoefficientsReachCostAndPayment() public {
        PackManager m = manager();
        VaultLib.Params memory p = m.getParams();
        uint256 before = m.buildCost(3);
        p.gasSchedule.build += 1_000;
        p.gasSchedule.buildPack += 2_000;
        p.gasSchedule.buildShape += 3_000;
        p.gasSchedule.listed += 4_000;
        set(m, p);
        uint256 extra = (1_000 + 2_000 + 3 * 3_000 + 4_000) * 0.2 gwei;
        assertEq(m.buildCost(3) - before, extra);
        uint256 paid = this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256 gasQ = uint256(p.gasSchedule.build) + p.gasSchedule.buildPack
            + 3 * p.gasSchedule.buildShape + p.gasSchedule.listed;
        assertLe(paid, (gasQ + p.gasSchedule.overhead) * 0.2 gwei + 2 * p.workFee);
        assertGt(paid, 2 * p.workFee);
    }

    function test_oldRateAccrualAndCapacityIncreaseNeverRefillSpentBudget() public {
        PackManager m = manager();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256 oldBalance = m.budget();
        VaultLib.Params memory p = m.getParams();
        uint256 oldRate = p.routineRate;
        vm.warp(vm.getBlockTimestamp() + 1 hours);
        uint256 accrued = oldBalance + oldRate * 1 hours / 1 days;
        if (accrued > p.routineCap) accrued = p.routineCap;
        p.routineCap = 0.3 ether;
        p.routineRate = 0.02 ether;
        set(m, p);
        uint256 afterUpdate = m.budget();
        assertEq(afterUpdate, accrued, "old rate first, capacity increase gives no refill");
        p.routineCap = 1;
        set(m, p);
        afterUpdate = m.budget();
        assertEq(afterUpdate, 1, "lower capacity clamps");
    }

    function test_disabledFreshMintsStillRelistsUnselectedOldInventory() public {
        PackManager m = manager();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256 id = m.openListingAt(0);
        vm.prank(owner);
        m.setExiting(true);
        uint256[] memory ids = new uint256[](1);
        ids[0] = id;
        m.recoverUnlist(ids);
        uint256 packId = m.idlePackAt(0);
        assertEq(m.idleValueOf(packId), 0.03 ether, "unselected inventory stays tracked");
        vm.prank(owner);
        m.setExiting(false);
        vm.prank(owner);
        m.setListingPaused(false);
        VaultLib.Params memory p = m.getParams();
        p.packUnitsMask = 0;
        set(m, p);
        uint256 supply = SHAPES.totalSupply();
        bytes32 expected = m.configurationHash();
        m.list(proposal(), 0, expected);
        assertEq(SHAPES.totalSupply(), supply, "relisting pays no new mint");
        assertEq(m.position(m.openListingAt(0)).packId, packId);
        expected = m.configurationHash();
        vm.expectRevert(VaultLib.BadBatch.selector);
        m.build(3, proposal(), 0, expected);

    }

    function test_managerEconomicSettingsRemainOnlyItsOwners() public {
        PackManager m = manager();
        VaultLib.Params memory p = m.getParams();
        p.backingRatioBps = 60_000;
        bytes32 expected = m.configurationHash();
        vm.prank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.setParams(p, expected);
        assertEq(m.getParams().backingRatioBps, 70_000);
    }

    function test_moreThan300RealPositionsUseJournalEvenWhenScanPriceIsZero() public {
        PackManagerFactory factory = new PackManagerFactory(FWA, SHAPES, PACKS);
        VaultLib.Params memory p = launchParams();
        p.routineCap = 0.3 ether;
        p.packUnitsMask |= uint64(1) << 6; // an exact mix holds at most 255 packs of one size
        PackManager m = factory.create{value: 100 ether}(owner, p, ANY_DESIGN, factory.configHashFor(p));
        for (uint256 start; start < 301;) {
            uint256 count = 301 - start > 4 ? 4 : 301 - start;
            uint256 units = start < 252 ? 3 : 6; // 252 three-unit packs, then 49 six-unit packs
            if (start < 252 && start + count > 252) count = 252 - start;
            uint256[] memory values = new uint256[](count);
            for (uint256 i; i < count; ++i) values[i] = units * 0.07 ether + (start + i) * 10_000;
            m.build(units, values, 0, m.configurationHash());
            start += count;
        }
        assertEq(m.openListingCount(), 301, "no total position cap");
        p = m.getParams();
        p.gasSchedule.scan = 0;
        p.gasSchedule.journal = 16_777_216;
        set(m, p);
        address buyer = makeAddr("pack-vault-test-main-scan-expiring-buyer");
        assertEq(buyer.code.length, 0);
        assertEq(buyer.balance, 0);
        (,, uint256 price) = IFwaSettle(address(FWA)).quoteAcquisitionPrice();
        vm.deal(buyer, price);
        vm.prank(buyer);
        IFwaSettle(address(FWA)).acquire{value: price}(buyer, 1, 0, 0, 10_000);
        assertGt(FWA.unsettledAcquisitionCount(), 0, "real request pending");
        vm.warp(vm.getBlockTimestamp() + 12 hours);
        vm.roll(block.number + 3600);
        IFwaSettle(address(FWA)).processAcquisitions(32);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "actual timeout, no fake VRF");
        assertGt(FWA.nextSequenceToProcess(), m.acquisitionCursor());
        vm.recordLogs();
        m.recover(new uint256[](0), 0);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bool journal;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter != address(m) || logs[i].topics.length == 0
                || logs[i].topics[0] != keccak256("JournalProgress(uint64,uint256,uint256)")) continue;
            (, uint256 processed,) = abi.decode(logs[i].data, (uint64,uint256,uint256));
            if (processed != 0) journal = true;
        }
        assertTrue(journal, "fixed scan bound forces bounded journal despite zero mutable scan price");
        assertEq(m.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertEq(m.openListingCount(), 301);
    }


    function test_reuseRelistsRealExistingInventoryAndBuildIsNotChargedItsOneTimeCost() public {
        PackManager m = manager();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256 listingId = m.openListingAt(0);
        uint256 packId = m.position(listingId).packId;
        vm.prank(owner);
        m.setExiting(true);
        if (FWA.topListingId() == listingId) vm.warp(vm.getBlockTimestamp() + 12 hours);
        uint256[] memory ids = new uint256[](1);
        ids[0] = listingId;
        m.recoverUnlist(ids);
        assertEq(m.idlePackCount(), 1, "real unselected pack returned");
        vm.prank(owner);
        m.setExiting(false);
        vm.prank(owner);
        m.setListingPaused(false);
        VaultLib.Params memory p = m.getParams();
        p.backingRatioBps = 20_000;

        set(m, p);
        // The build gate charges a selection neither gas nor the one-time build (owner, 2026-11-26).
        (, uint256 freshBacking, bool freshOk) = m.edge(3);
        assertTrue(freshOk, "a fresh build is not charged its one-time construction");
        assertEq(freshBacking, 0.06 ether);
        (, uint256 relistBacking, bool relistOk) = m.relistEdge(3);
        assertTrue(relistOk, "existing inventory has no new primary mint expense");
        assertEq(relistBacking, 0.06 ether);
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256[] memory values = new uint256[](1);
        values[0] = relistBacking;
        m.list(values, 0, m.configurationHash());
        assertEq(m.position(m.openListingAt(0)).packId, packId);
        assertEq(SHAPES.totalSupply(), supply, "relisting a returned pack mints nothing");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), fees);
    }


    function test_ownerBackingFloorPreservesUnresolvedFaceCoverage() public {
        PackManager m = manager();
        this.buildInRealFeeContext(m, proposal(), m.configurationHash());
        uint256 id = m.openListingAt(0);
        uint256 pack = m.position(id).packId;
        vm.prank(owner);
        m.setExiting(true);
        if (FWA.topListingId() == id) vm.warp(vm.getBlockTimestamp() + 12 hours);
        uint256[] memory ids = new uint256[](1);
        ids[0] = id;
        m.recoverUnlist(ids);
        vm.prank(owner);
        m.setExiting(false);
        vm.prank(owner);
        m.setListingPaused(false);
        VaultLib.Params memory p = m.getParams();
        p.backingRatioBps = 10_527;

        set(m, p);
        (, uint256 target, bool ok) = m.relistEdgeFor(pack);
        assertTrue(ok, "both account settlement outcomes cover their actual costs");
        assertEq(target, 0.031581 ether);
        assertGe(target * 9_500 / 10_000, 0.03 ether, "maximum settlement fee still covers the unresolved face mark");
        uint256 supply = SHAPES.totalSupply();
        uint256[] memory values = new uint256[](1);
        values[0] = target;
        m.list(values, 0, m.configurationHash());
        assertEq(m.position(m.openListingAt(0)).backing, target, "real FWA admits selected backing");
        assertEq(SHAPES.totalSupply(), supply, "reuse creates no paid or free replacement mints");
    }

    function buildLegacyInRealFeeContext(PackManager m, uint256[] calldata values, bytes32 expected)
        external returns (uint256)
    {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
        return m.build(10, values, 0, expected);
    }

    function listInHalfGweiContext(PackManager m, uint256[] calldata values, bytes32 expected)
        external returns (uint256)
    {
        require(msg.sender == address(this), "test driver only");
        assertEq(block.basefee, 0.45 gwei);
        assertEq(tx.gasprice, 0.5 gwei);
        return m.list(values, 0, expected);
    }

    function test_legacyOneMintPackRelistsWithoutReplacingItsComposition() public {
        PackManager m = manager();
        VaultLib.Params memory p = m.getParams();
        p.packUnitsMask = uint64(1) << 10;
        set(m, p);
        uint256[] memory values = new uint256[](1);
        values[0] = 0.7 ether;
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        this.buildLegacyInRealFeeContext(m, values, m.configurationHash());
        assertEq(SHAPES.totalSupply() - supply, 1, "legacy .10 pack contains one directly minted Shape");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - fees, 0.001 ether);
        uint256 id = m.openListingAt(0);
        uint256 packId = m.position(id).packId;
        assertEq(m.inventoryShapeCount(packId), 1);
        vm.prank(owner);
        m.setExiting(true);
        if (FWA.topListingId() == id) vm.warp(vm.getBlockTimestamp() + 12 hours);
        uint256[] memory ids = new uint256[](1);
        ids[0] = id;
        m.recoverUnlist(ids);
        vm.prank(owner);
        m.setExiting(false);
        vm.prank(owner);
        m.setListingPaused(false);
        p = m.getParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 11_000;

        set(m, p);
        vm.fee(0.45 gwei);
        vm.txGasPrice(0.5 gwei);
        (,, bool reuseRelist) = m.relistEdgeFor(packId);
        assertTrue(reuseRelist, "existing legacy inventory is priced without replacing its recipe");
        assertEq(m.inventoryShapeCount(packId), 1, "legacy composition remains one Shape");
        values[0] = 0.11 ether;
        supply = SHAPES.totalSupply();
        fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        this.listInHalfGweiContext(m, values, m.configurationHash());
        assertEq(m.position(m.openListingAt(0)).packId, packId);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), fees);

    }

}
