// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {ForkBase, IFwaAdmin, IOwnable, IOracleAdmin} from "./ForkBase.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {
    IShapes, IShapePacks, IFWAV2, IERC721Min, LISTING_ACTIVE, LISTING_ALLOCATED, LISTING_WITHDRAWN
} from "../../src/interfaces/External.sol";

interface IApproval {
    function isApprovedForAll(address owner, address operator) external view returns (bool);
}

interface IFwaPurchaser {
    function acceptDepositorBid(uint256 listingId) external;
    function keepNFT(uint256 listingId) external;
    function setCollectionsWhitelisted(address[] calldata collections, bool allowed) external;
    function processAcquisitions(uint256 maxCount) external returns (uint256 processed);
}

/// @dev Parameters a personal manager runs with in these tests: the canary's gas ceilings and
///      work fee, both budgets enabled so exit work is paid from the manager's own ETH.
function managerParams() pure returns (VaultLib.Params memory p) {
        p.gasSchedule = VaultLib.defaultGasSchedule();
        p.backingRatioBps = 12_000;
        p.acceptedMintFee = 0.001 ether;
        p.minDeposit = 0.01 ether;
        p.minDistribution = 0.01 ether;
    p.minEdgeBps = 100;
    p.keeperShareBps = 2_500;
    p.packUnitsMask = uint64(1) << 6;
    p.gasCeiling = 0.5 gwei;
    p.essentialCeiling = 0.5 gwei;
    p.maxTip = 0.05 gwei;
    p.workFee = 0.00002 ether;
    p.reserve = 0.005 ether;
    p.routineCap = 0.03 ether;
    p.routineRate = 0.01 ether;


}

/// @notice Personal managers on the real FWA, Shapes and ShapePacks at the pinned block, beside the
///         pooled vault ForkBase deploys. Nothing is mocked; other parties act through their real
///         entry points (FWA's owner, the oracle owner, a keeper, the managers' owners).
contract ForkManagerTest is ForkBase {
    PackManagerFactory factory;
    address carol = makeAddr("pack-vault-test-carol");

    receive() external payable {} // this contract also calls paid work directly

    function setUp() public override {
        super.setUp();
        assertEq(carol.code.length, 0, "test actor has code on mainnet");
        assertEq(carol.balance, 0, "test actor has mainnet balance");
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS);
        vm.deal(carol, 50 ether);
    }

    function _create(address who, uint256 funding) internal returns (PackManager m) {
        bytes32 _expected19 = TestVaultOps.factoryHash(factory, managerParams());
        vm.prank(who);
        m = factory.create{value: funding}(who, managerParams(), _expected19);
    }

    function _build(PackAccount a, uint256 n) internal returns (uint256 pay) {
        vm.prank(keeper);
        pay = TestVaultOps.restock(a, n, UNITS, 0);
    }

    function _sumBacking(PackAccount a) internal view returns (uint256 sum) {
        for (uint256 i; i < a.openListingCount(); ++i) sum += a.position(a.openListingAt(i)).backing;
    }

    // ------------------------------------------------------------------ factory

    /// @dev An owner that could never act (the factory, or the manager itself) would lock the funds.
    function test_createRejectsOwnersThatCannotAct() public {
        address predicted = vm.computeCreateAddress(address(factory), vm.getNonce(address(factory)));
        bytes32 _expected20 = TestVaultOps.factoryHash(factory, managerParams());
        vm.prank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        factory.create{value: 1 ether}(address(factory), managerParams(), _expected20);
        bytes32 _expected21 = TestVaultOps.factoryHash(factory, managerParams());
        vm.prank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        factory.create{value: 1 ether}(predicted, managerParams(), _expected21);
    }

    function test_createInitializesAtomically() public {
        address predicted = vm.computeCreateAddress(address(factory), vm.getNonce(address(factory)));
        uint256 dust = predicted.balance; // a fresh address can still hold mainnet dust
        uint256 factoryDust = address(factory).balance;
        uint256 g = gasleft();
        PackManager m = _create(alice, 1 ether);
        emit log_named_uint("gas factory.create (clone + initialize)", g - gasleft());
        assertEq(address(m), predicted);
        assertEq(address(m).code.length, 44, "ERC-1167 minimal proxy (PUSH0 form)");
        assertEq(m.owner(), alice);
        assertEq(address(m).balance, 1 ether + dust, "funding forwarded in the same call");
        assertEq(address(factory).balance, factoryDust, "creation retains none of the supplied funding");
        assertEq(factory.managerCount(), 1);
        assertEq(factory.managerAt(0), address(m));
        assertTrue(factory.isManager(address(m)));
        assertEq(keccak256(abi.encode(m.getParams())), keccak256(abi.encode(managerParams())));

        assertEq(m.budget(), managerParams().routineCap);
        assertEq(m.deploymentBlock(), block.number);
        assertEq(m.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertTrue(IApproval(address(PACKS)).isApprovedForAll(address(m), address(FWA)), "FWA may take listed packs");
        assertEq(address(m.fwa()), address(FWA));
        assertEq(m.factory(), address(factory));
        assertFalse(m.listingPaused());
        assertFalse(m.windingDown());
        // The implementation never gets an owner.
        assertEq(PackManager(payable(factory.implementation())).owner(), address(0));
    }

    /// @dev Deployment gas of the shared contracts (libraries are deployed by the test harness and
    ///      estimated from their size in docs/UNIFIED-SYSTEM.md).
    function test_deploymentGas() public {
        uint256 g = gasleft();


        g = gasleft();
        DeployCore.deploy(FWA, SHAPES, PACKS, owner, defaultParams(), 0.01 ether, keccak256(abi.encode(defaultParams(), SHAPES.mintFee(), false, false)));
        emit log_named_uint("gas PackVault + postflight", g - gasleft());
        g = gasleft();
        DeployCore.deployFactory(FWA, SHAPES, PACKS);
        emit log_named_uint("gas PackManagerFactory + implementation + postflight", g - gasleft());
    }

    function test_initializeOnlyOnceOnlyByFactory() public {
        PackManager m = _create(alice, 0.1 ether);
        PackManager impl = PackManager(payable(factory.implementation()));

        VaultLib.Params memory p = managerParams();
        vm.prank(address(factory));
        vm.expectRevert(Ownable.AlreadyInitialized.selector);
        impl.initialize(bob, p, 0);
        vm.prank(address(factory));
        vm.expectRevert(Ownable.AlreadyInitialized.selector);
        m.initialize(bob, p, 0);
        vm.prank(bob);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.initialize(bob, p, 0);
        assertEq(m.owner(), alice);
    }

    /// @dev The admin may point new creations at another implementation; managers already created
    ///      keep their code, a hash reviewed against the old implementation is refused, and only an
    ///      implementation bound to this factory is accepted.
    function test_adminChangesImplementationForNewManagersOnly() public {
        assertEq(factory.admin(), address(this));
        PackManager oldM = _create(alice, 0.1 ether);
        address oldImpl = factory.implementation();
        bytes32 staleHash = TestVaultOps.factoryHash(factory, managerParams());

        PackManager foreign = new PackManager(FWA, SHAPES, PACKS, address(this)); // bound to another factory
        vm.expectRevert(PackManagerFactory.InvalidImplementation.selector);
        factory.setImplementation(address(foreign));
        vm.expectRevert(PackManagerFactory.InvalidImplementation.selector);
        factory.setImplementation(carol);

        vm.prank(alice); // anyone may deploy a replacement; only the admin may select it
        PackManager next = new PackManager(FWA, SHAPES, PACKS, address(factory));
        vm.prank(alice);
        vm.expectRevert(PackManagerFactory.Unauthorized.selector);
        factory.setImplementation(address(next));
        factory.setImplementation(address(next));
        assertEq(factory.implementation(), address(next));

        vm.prank(bob);
        vm.expectRevert(PackManagerFactory.ConfigurationChanged.selector);
        factory.create{value: 0.1 ether}(bob, managerParams(), staleHash);

        PackManager newM = _create(bob, 0.1 ether);
        assertEq(keccak256(address(oldM).code), keccak256(_clone(oldImpl)), "old manager keeps its code");
        assertEq(keccak256(address(newM).code), keccak256(_clone(address(next))), "new manager clones next");
        assertEq(oldM.owner(), alice);
        assertEq(newM.owner(), bob);
        assertTrue(factory.isManager(address(oldM)) && factory.isManager(address(newM)));
    }

    function test_adminTransferIsTwoStep() public {
        vm.prank(alice);
        vm.expectRevert(PackManagerFactory.Unauthorized.selector);
        factory.transferAdmin(alice);
        factory.transferAdmin(alice);
        assertEq(factory.admin(), address(this), "pending until accepted");
        vm.prank(bob);
        vm.expectRevert(PackManagerFactory.Unauthorized.selector);
        factory.acceptAdmin();
        vm.prank(alice);
        factory.acceptAdmin();
        assertEq(factory.admin(), alice);
        assertEq(factory.pendingAdmin(), address(0));
        address impl = factory.implementation();
        vm.expectRevert(PackManagerFactory.Unauthorized.selector);
        factory.setImplementation(impl);
    }

    function _clone(address impl) internal pure returns (bytes memory) {
        return abi.encodePacked(hex"3d3d3d3d363d3d37363d73", impl, hex"5af43d3d93803e602a57fd5bf3");
    }

    function test_createRejectsBadInputs() public {
        VaultLib.Params memory p = managerParams();
        p.workFee = uint64(VaultLib.MAX_WORK_FEE + 1);
        bytes32 _expected22 = TestVaultOps.factoryHash(factory, p);
        vm.prank(alice);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        factory.create(alice, p, _expected22);
        bytes32 _expected23 = TestVaultOps.factoryHash(factory, managerParams());
        vm.prank(alice);
        vm.expectRevert(Ownable.NewOwnerIsZeroAddress.selector);
        factory.create(address(0), managerParams(), _expected23);
        assertEq(factory.managerCount(), 0);
    }

    /// The owner's pack mix caps each size's held packs; builds below it run on the real pool,
    /// builds past it revert, and only the owner can change it.
    function test_designCapsEachPackSize() public {
        VaultLib.Params memory p = managerParams();
        p.packUnitsMask = uint64(1 << 3 | 1 << 5);
        uint256 design = 2 << 24 | 1 << 40; // two 0.03 ETH packs, one 0.05 ETH pack
        bytes32 expected = TestVaultOps.factoryHash(factory, p);
        vm.prank(alice);
        PackManager m = factory.create{value: 1 ether}(alice, p, design, expected);
        assertEq(m.design(), design);

        vm.startPrank(keeper);
        TestVaultOps.restock(m, 2, 3, 0);
        TestVaultOps.restock(m, 1, 5, 0);
        assertEq(m.recipeCount(3), 2);
        assertEq(m.recipeCount(5), 1);
        assertEq(m.openListingCount(), 3, "every designed pack lists");
        uint256[] memory one = TestVaultOps.proposals(m, 1, 3);
        bytes32 h = TestVaultOps.configurationHash(m);
        vm.expectRevert(VaultLib.BadBatch.selector);
        m.build(3, one, 0, h);
        one = TestVaultOps.proposals(m, 1, 5);
        vm.expectRevert(VaultLib.BadBatch.selector);
        m.build(5, one, 0, h);
        vm.stopPrank();

        vm.prank(bob);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.setDesign(3 << 24);
        vm.startPrank(alice);
        vm.expectRevert(PackAccount.InvalidDesign.selector);
        m.setDesign(1 << 16); // 0.02 ETH packs do not exist
        vm.expectRevert(PackAccount.InvalidDesign.selector);
        m.setDesign(1 << 248);
        m.setDesign(3 << 24 | 1 << 40);
        vm.stopPrank();
        vm.prank(keeper);
        TestVaultOps.restock(m, 1, 3, 0);
        assertEq(m.recipeCount(3), 3, "a raised count builds again");

        bytes32 e2 = TestVaultOps.factoryHash(factory, p);
        vm.prank(alice);
        vm.expectRevert(PackAccount.InvalidDesign.selector);
        factory.create{value: 1 ether}(alice, p, uint256(1) << 8, e2);
    }

    /// @dev Audit B E1: a build may not spend the backing booked for a returned pack (reuse first).
    function test_buildCannotSpendReturnedPackBacking() public {
        VaultLib.Params memory p = managerParams();
        p.packUnitsMask = uint64(1 << 3 | 1 << 5);
        bytes32 expected = TestVaultOps.factoryHash(factory, p);
        vm.prank(alice);
        PackManager m = factory.create{value: 1 ether}(alice, p, uint256(1) << 24 | uint256(1) << 40, expected);
        vm.prank(keeper);
        TestVaultOps.restock(m, 1, 3, 0);
        uint256[] memory ids = TestVaultOps.open(m);
        vm.prank(alice);
        m.unlistForWithdrawal(ids);
        uint256 booked = m.idleFunding();
        assertGt(booked, 0, "returned pack books its backing");
        assertEq(m.idlePackCount(), 1);

        // Cash for exactly one 0.05 ETH build above the reserve, so not also the returned pack's backing.
        uint256[] memory five = TestVaultOps.proposals(m, 1, 5);
        uint256 need5 = 0.05 ether + m.buildCost(5) + five[0] + 0.001 ether;
        uint256 target = m.operatingReserve() + need5;
        assertLt(0.001 ether, booked);
        vm.prank(alice);
        m.withdraw(alice, address(m).balance - target);
        assertEq(address(m).balance, target);

        uint256 supply0 = SHAPES.totalSupply();
        bytes32 h = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.InsufficientBacking.selector);
        m.build(5, five, 0, h);
        assertEq(SHAPES.totalSupply(), supply0, "no fresh mint while the returned pack waits");

        vm.prank(keeper);
        TestVaultOps.list(m, 1, 0);
        assertEq(m.idlePackCount(), 0, "the returned pack relists intact");
        assertEq(m.idleFunding(), 0);
        assertEq(SHAPES.totalSupply(), supply0, "relisting mints nothing");
    }

    // ------------------------------------------------------------------ owner controls

    function test_onlyOwnerControls_andHandover() public {
        PackManager m = _create(alice, 1 ether);
        address[3] memory others = [bob, keeper, address(factory)];

        VaultLib.Params memory p = managerParams();
        for (uint256 i; i < others.length; ++i) {
            vm.startPrank(others[i]);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.withdraw(others[i], 1);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.withdrawPacks(others[i], 1);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.rescue(IERC721Min(address(PACKS)), 1, others[i]);
            bytes32 _expected0 = TestVaultOps.configurationHash(m);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.setParams(p, _expected0);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.setListingPaused(true);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.setExiting(true);
            vm.stopPrank();
        }
        vm.startPrank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.transferOwnership(bob);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.renounceOwnership();
        vm.stopPrank();
        // Two-step handover: the new key asks, the owner completes.
        vm.prank(bob);
        m.requestOwnershipHandover();
        vm.prank(alice);
        m.completeOwnershipHandover(bob);
        assertEq(m.owner(), bob);
        vm.prank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.withdraw(alice, 1);
        uint256 before = bob.balance;
        vm.prank(bob);
        m.withdraw(bob, 0.5 ether);
        assertEq(bob.balance - before, 0.5 ether);
    }

    // ------------------------------------------------------------------ lifecycle

    function test_lifecycle_buildExitWithdrawEverything() public {
        PackManager m = _create(alice, 1 ether);
        uint256 start = address(m).balance;
        uint256 supply0 = SHAPES.totalSupply();
        uint256 k0 = keeper.balance;
        // Historical six-unit reuse: each position needs 0.06 principal, two paid mint fees
        // and backing at the account owner's selected ratio.
        uint256 pay = _build(m, 7);
        assertEq(m.openListingCount(), 7);
        assertEq(m.idlePackCount(), 0, "build lists at once");
        assertEq(SHAPES.totalSupply() - supply0, 14, "two paid primary mints per pack");
        uint256 backing = _sumBacking(m);
        assertEq(keeper.balance - k0, pay, "keeper paid by quote");
        assertGt(pay, 0);
        assertEq(start - address(m).balance, 7 * (P + FEE_PER_PACK) + backing + pay, "every wei of the build");
        uint256[] memory packIds = new uint256[](7);
        for (uint256 i; i < 7; ++i) {
            uint256 id = m.openListingAt(i);
            (, address depositor,, uint256 packId,, uint256 value,,,,, uint8 status) = FWA.listings(id);
            assertEq(depositor, address(m), "the manager is the FWA depositor");
            assertEq(status, LISTING_ACTIVE);
            assertEq(value, m.position(id).backing);
            assertEq(PACKS.valueOf(packId), P);
            assertGe(value * 9_500, P * 10_000, "each actual backing covers the pack at FWA's maximum settlement fee");
            packIds[i] = packId;
        }
        VaultLib.Params memory active = m.getParams();
        (, uint256 b, bool admitted) = m.edge(UNITS);
        assertTrue(admitted, "owner-selected ratio meets the live new-build gate");
        assertEq(b, P * active.backingRatioBps / 10_000 / 10_000 * 10_000,
            "backing follows the account owner's ratio, without requiring a buyer keep preference");
        assertTrue(FWA.canDeposit(address(PACKS)), "real collection admission is open");
        assertTrue(FWA.oracleExemptCollections(address(PACKS)), "this ratio quote is uncapped on the real fork");

        // The owner withdraws spare cash at any time.
        uint256 spare = address(m).balance;
        uint256 a0 = alice.balance;
        vm.prank(alice);
        m.withdraw(alice, spare);
        assertEq(alice.balance - a0, spare);
        assertEq(address(m).balance, 0);

        // Exit: anyone unlists, unpaid (owner decision: keepers are not paid for exits).
        vm.prank(alice);
        m.setExiting(true);
        assertTrue(m.listingPaused());
        uint256[] memory ids = TestVaultOps.open(m);
        uint256 b0 = bob.balance;
        vm.prank(bob);
        uint256 exitPay = TestVaultOps.unlist(m, ids, 0);
        assertEq(exitPay, 0, "exit work is unpaid");
        assertEq(bob.balance - b0, exitPay);
        assertEq(m.openListingCount(), 0);
        assertEq(m.idlePackCount(), 7);
        assertEq(address(m).balance, backing - exitPay, "every backing returned exactly, less exit pay");

        // Packs leave as NFTs; ETH leaves by withdrawal. Nothing remains.
        vm.prank(alice);
        m.withdrawPacks(alice, 7);
        for (uint256 i; i < 7; ++i) assertEq(PACKS.ownerOf(packIds[i]), alice);
        vm.prank(alice);
        m.withdraw(alice, backing - exitPay);
        (uint256 tracked, uint256 idle,,,,) = m.totals();
        assertEq(tracked + idle + address(m).balance, 0, "empty book, empty balance");
        // Owner round trip: in 1 ETH; out spare + returned backing in ETH and 7 x 0.06 in packs.
        // Spent: 14 mint fees to the Shapes creator and the two keeper payments, nothing else.
        assertEq(spare + (backing - exitPay) + 7 * P + 7 * FEE_PER_PACK + pay + exitPay, start, "every wei");
    }

    /// @dev FWA's owner removes ShapePacks from the whitelist with packs listed. New exposure stops
    ///      (no cap means no build and no relist); every exit path still returns every wei and pack.
    function test_dewhitelistedPacksNeverBrickExit() public {
        PackManager m = _create(alice, 1 ether);
        _build(m, 3);
        uint256 backing = _sumBacking(m);
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaPurchaser(address(FWA)).setCollectionsWhitelisted(cols, false);
        assertFalse(FWA.canDeposit(address(PACKS)), "real FWA removal");
        (,, bool admitted) = m.edge(UNITS);
        assertFalse(admitted, "no new exposure once the collection is removed");
        uint256[] memory planned = new uint256[](1);
        planned[0] = 0.07 ether;
        bytes32 h = m.configurationHash();
        vm.prank(keeper);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        m.build(UNITS, planned, 0, h);

        // Owner pulls one pack: it returns, and relisting it is refused, not stuck.
        uint256[] memory ids = TestVaultOps.open(m);
        vm.prank(alice);
        m.unlistForWithdrawal(_first(ids));
        assertEq(m.idlePackCount(), 1);
        h = m.configurationHash();
        vm.prank(keeper);
        vm.expectRevert();
        m.list(planned, 0, h);

        // Exit the rest unpaid, then every pack and every wei leaves.
        vm.prank(alice);
        m.setExiting(true);
        ids = TestVaultOps.open(m);
        vm.prank(bob);
        assertEq(TestVaultOps.unlist(m, ids, 0), 0, "exit work is unpaid");
        assertEq(m.openListingCount(), 0);
        assertEq(m.idlePackCount(), 3);
        vm.prank(alice);
        m.withdrawPacks(alice, 3);
        uint256 cash = address(m).balance;
        assertGe(cash, backing, "every backing returned");
        vm.prank(alice);
        m.withdraw(alice, cash);
        (uint256 tracked, uint256 idle,,,,) = m.totals();
        assertEq(tracked + idle + address(m).balance, 0, "empty book, empty balance");
    }

    function _first(uint256[] memory ids) internal pure returns (uint256[] memory one) {
        one = new uint256[](1);
        one[0] = ids[0];
    }

    function test_pauseStopsBuildsNotMaintenance() public {
        PackManager m = _create(alice, 1 ether);
        _build(m, 2);
        vm.prank(alice);
        m.setListingPaused(true);
        uint256[] memory quotes = TestVaultOps.proposals(m, 1, UNITS);
        bytes32 _expected1 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.Paused.selector);
        m.build(UNITS, quotes, 0, _expected1);
        // Stopping paid automation: zero budgets. Strategy work then pays nothing.
        VaultLib.Params memory p = managerParams();
        (p.routineCap, p.routineRate) = (0, 0);
        bytes32 _expected2 = TestVaultOps.configurationHash(m);
        vm.prank(alice);
        m.setParams(p, _expected2);
        assertEq(m.budget(), 0);
        vm.prank(alice);
        m.setListingPaused(false);
        uint256 k0 = keeper.balance;
        bytes32 _expected3 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.Payment.selector);
        m.build(UNITS, quotes, 1, _expected3); // a keeper demanding pay is refused before any work
        bytes32 _expected4 = TestVaultOps.configurationHash(m);
        vm.prank(alice);
        m.build(UNITS, quotes, 0, _expected4); // the owner can always run it unpaid
        assertEq(keeper.balance, k0);
        assertEq(m.openListingCount(), 3);
    }

    // ------------------------------------------------------------------ isolation

    function test_isolation_managersAndVault() public {
        // Pooled vault with a priced deposit, and two managers of different sizes.
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(bob);
        vault.deposit{value: vault.requestCharge() + 2 ether}(_expected5);
        toBlackout();
        checkpoint();
        toOpen();
        PackManager a = _create(alice, 1 ether);
        PackManager c = _create(carol, 0.5 ether);
        _build(vault, 4);
        uint256 cBal = address(c).balance;
        uint256 vBal = address(vault).balance;
        uint256 aBal = address(a).balance;
        uint256 aPay = _build(a, 3);
        assertEq(address(c).balance, cBal, "A's build never touches C");
        assertEq(address(vault).balance, vBal, "A's build never touches the vault");
        assertEq(aBal - address(a).balance, 3 * (P + FEE_PER_PACK) + _sumBacking(a) + aPay, "A pays only its own work");
        _build(c, 2);
        assertEq(a.openListingCount(), 3);
        assertEq(c.openListingCount(), 2);
        assertEq(vault.openListingCount(), 4);
        // Identical backing targets in different books map to each account's own listing.
        uint256 shared = a.position(a.openListingAt(0)).backing;
        assertEq(shared, c.position(c.openListingAt(0)).backing, "same live target");
        assertEq(a.idForBacking(shared), a.openListingAt(0));
        assertEq(c.idForBacking(shared), c.openListingAt(0));
        // Owners cannot reach other accounts' assets: C's packs sit in FWA custody under C.
        (,,, uint256 cPack,,,,,,,) = FWA.listings(c.openListingAt(0));
        vm.prank(alice);
        vm.expectRevert();
        a.rescue(IERC721Min(address(PACKS)), cPack, alice);
        vm.prank(alice);
        vm.expectRevert();
        a.withdraw(alice, address(a).balance + 1);
        // C's exit leaves A and the vault untouched.
        vm.prank(carol);
        c.setExiting(true);
        uint256[] memory cIds = TestVaultOps.open(c);
        vm.prank(keeper);
        TestVaultOps.unlist(c, cIds, 0);
        assertEq(a.openListingCount(), 3);
        assertEq(vault.openListingCount(), 4);
        assertFalse(a.windingDown());
        uint256[] memory aIds = TestVaultOps.open(a);
        bytes32 _expected6 = TestVaultOps.configurationHash(a);
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.UnlistNotAllowed.selector);
        a.unlist(aIds, 0, _expected6);
    }

    // ------------------------------------------------------------------ FWA's pushed ETH

    /// @dev A kick refund reaches a clone through two DELEGATECALLs under FWA's 100,000 gas
    ///      stipend; it must still be identified (else FWA force-sends and no receipt exists).
    function test_coldKickRefundIdentifiedUnderStipend() public {
        PackManager a = _create(alice, 1 ether);
        PackManager c = _create(carol, 1 ether);
        _build(a, 1);
        _build(c, 1);
        uint256 id = a.openListingAt(0);
        uint256 backing = a.position(id).backing;
        // FWA's owner lifts the exemption and the oracle owner quotes a floor below the backing.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(0.03 ether);
        vm.warp(block.timestamp + 7 hours); // the quote outlives FWA's challenge period
        vm.roll(block.number + 7 * 300);
        toBlackout(); // kicks happen only in FWA's purchase blackout
        uint256 before = address(a).balance;
        vm.cool(address(a));
        vm.cool(address(factory.implementation()));
        vm.cool(address(FWA));
        vm.cool(address(PACKS));
        IFwaAdmin(address(FWA)).kickListing(id);
        assertEq(address(a).balance - before, backing, "full backing refunded");
        assertEq(a.pendingReceipts(), 1, "identified inside the stipend");
        VaultLib.Receipt memory r = a.receipts(id);
        assertEq(r.amount, backing);
        assertEq(r.kind, 2);
        assertEq(c.pendingReceipts(), 0, "another manager never sees it");
        uint256[] memory one = new uint256[](1);
        one[0] = id;
        bytes32 _expected7 = TestVaultOps.configurationHash(a);
        vm.prank(keeper);
        a.sync(one, 0, 0, _expected7);
        assertEq(a.pendingReceipts(), 0);
        assertEq(a.idlePackCount(), 1, "kicked pack back in inventory");
        assertEq(a.openListingCount(), 0);
    }

    /// @dev A keeper that re-enters from its payment cannot reach any guarded entry point; the
    ///      failed re-entry leaves the manager's book and cash exactly as the completed work left them.
    function test_reentrantKeeperGetsNothingExtra() public {
        PackManager m = _create(alice, 1 ether);
        ReentrantKeeper attacker = new ReentrantKeeper(m);
        uint256[] memory quotes = TestVaultOps.proposals(m, 1, UNITS);
        uint256 before = address(m).balance;
        uint256 pay = attacker.attack(UNITS, quotes);
        assertGt(pay, 0);
        assertEq(attacker.reentered(), 0, "every re-entry reverted");
        assertEq(attacker.attempts(), 3);
        assertEq(address(attacker).balance, pay, "paid exactly the quote once");
        assertEq(m.openListingCount(), 1);
        assertEq(before - address(m).balance, P + FEE_PER_PACK + m.position(m.openListingAt(0)).backing + pay);
    }

    /// @dev ETH from anyone else, or forced in, just becomes the owner's free ETH.
    function test_plainEthIsFreeEth() public {
        PackManager a = _create(alice, 0);
        vm.prank(bob);
        (bool ok,) = address(a).call{value: 0.3 ether}("");
        assertTrue(ok);
        assertEq(a.freeEth(), 0.3 ether);
        assertEq(a.idleEth(), 0.3 ether - managerParams().reserve);
        assertEq(a.pendingReceipts(), 0);
    }

    /// @dev Shapes, or any NFT other than packs, are refused by the safe-transfer hook.
    function test_onlyPackNftsAccepted() public {
        PackManager a = _create(alice, 0);
        vm.prank(address(SHAPES));
        vm.expectRevert(PackAccount.UnknownNft.selector);
        a.onERC721Received(alice, alice, 1, "");
        vm.prank(address(PACKS));
        assertEq(a.onERC721Received(alice, alice, 1, ""), PackAccount.onERC721Received.selector);
    }
}

/// @notice Keep and bid outcomes on a personal manager, driven by FWA's real randomness. Forks
///         right before a historical acquisition request whose real VRF word selects listing #22
///         of 30 posted at exactly 64,896,174,863,380,000 wei backing (sim/find_selection.py), then
///         replays the real request and fulfillment calls. Only the purchaser's choice is ours.
contract ForkManagerSelectionTest is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    bytes32 constant REQUEST_TX = 0x3c030ce52b8ef58a5c499b9c6e6d02e4233ae670bcb25c7667fe20404e493f36;
    uint256 constant REQUEST_BLOCK = 26_310_897;
    uint256 constant INDEX = 7;
    uint256 constant SLOT = 277;
    address constant PURCHASER = 0x88d0e89E7f502Aa49a564b683e19089c771776c3;
    uint256 constant BACKING = 64_800_000_000_000_000;
    uint256 constant P = 0.06 ether;

    PackManagerFactory factory;
    PackManager m;
    uint256 selected;
    address owner = makeAddr("pack-vault-test-manager-owner");
    address keeper = makeAddr("pack-vault-test-manager-keeper");

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    receive() external payable {}

    function _select() internal {
        vm.createSelectFork("mainnet", REQUEST_TX);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue empty before the request");
        assertEq(owner.code.length + owner.balance + keeper.code.length + keeper.balance, 0, "clean actors");
        // Before ShapePacks' admission: FWA's owner makes the real admission and exemption calls.
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.startPrank(IOwnable(address(FWA)).owner());
        IFwaPurchaser(address(FWA)).setCollectionsWhitelisted(cols, true);
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        vm.stopPrank();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);

        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS);
        vm.deal(owner, 5 ether);
        vm.deal(keeper, 1 ether);
        VaultLib.Params memory replayParams = managerParams();
        replayParams.backingRatioBps = 10_800;
        replayParams.gasCeiling = 0.15 gwei;
        replayParams.maxTip = 0;
        bytes32 _expected24 = TestVaultOps.factoryHash(factory, replayParams);
        vm.prank(owner);
        m = factory.create{value: 2 ether}(owner, replayParams, _expected24);
        (, uint256 target, bool ok) = m.edge(6);
        assertTrue(ok);
        assertEq(target, BACKING, "exact backing the replayed word was found for");
        Filler filler = new Filler{value: 3 ether}(FWA, PACKS, SHAPES);
        for (uint256 i; i < 30; ++i) {
            if (i == INDEX) {
                uint256[] memory one = new uint256[](1);
                one[0] = BACKING;
                bytes32 _expected8 = TestVaultOps.configurationHash(m);
                vm.prank(keeper);
                m.build(6, one, 0, _expected8);
                selected = m.openListingAt(0);
            } else {
                filler.createAndList(BACKING);
            }
        }
        bytes32 restored = m.configurationHash();
        vm.prank(owner);
        m.setParams(managerParams(), restored);
        (,,,,,,,, uint256 slot,,) = FWA.listings(selected);
        assertEq(slot, SLOT, "slot prediction");
        string memory key = string.concat(".", vm.toString(REQUEST_BLOCK));
        string memory fx = vm.readFile("test/fixtures/selection.json");
        _call(fx, key, "req");
        vm.roll(vm.parseJsonUint(fx, string.concat(key, ".fulBlock")));
        vm.warp(vm.parseJsonUint(fx, string.concat(key, ".fulTimestamp")));
        vm.setBlockhash(REQUEST_BLOCK, vm.parseJsonBytes32(fx, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fx, string.concat(key, ".fulBaseFee")));
        _call(fx, key, "ful");
        (,, address purchaser,,,,,,,, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED, "the real word selected the manager's listing");
        assertEq(purchaser, PURCHASER);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function _call(string memory fx, string memory key, string memory leg) internal {
        address from = vm.parseJsonAddress(fx, string.concat(key, ".", leg, "From"));
        address to = vm.parseJsonAddress(fx, string.concat(key, ".", leg, "To"));
        bytes memory input = vm.parseJsonBytes(fx, string.concat(key, ".", leg, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req") ? vm.parseJsonUint(fx, string.concat(key, ".reqValue")) : 0;
        vm.txGasPrice(vm.parseJsonUint(fx, string.concat(key, ".", leg, "GasPrice")));
        vm.deal(address(this), address(this).balance + value);
        vm.prank(from, from);
        (bool ok, bytes memory ret) = to.call{value: value}(input);
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    /// @dev Let FWA's other historical requests expire and process, so new listings may activate.
    function _drain() internal {
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        IFwaPurchaser(address(FWA)).processAcquisitions(50);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
    }

    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    /// @dev The purchaser keeps the pack: the manager receives B (1 - s) through its clone receive
    ///      under FWA's stipend, resolves the keep, and a replacement build pays two fresh mints.
    function test_keep_replacementMintsFreshShapes() public {
        _select();
        (,,, uint256 packId,,,,,,,) = FWA.listings(selected);
        uint256 before = address(m).balance;
        // Everything the receive path touches starts cold, as in a real transaction.
        vm.cool(address(m));
        vm.cool(address(factory.implementation()));
        vm.cool(address(StrategyLib));
        vm.cool(address(PACKS));
        vm.prank(PURCHASER);
        IFwaPurchaser(address(FWA)).keepNFT(selected);
        assertEq(address(m).balance - before, BACKING * 9_900 / 10_000, "backing less the 1% settlement fee");
        assertEq(PACKS.ownerOf(packId), PURCHASER, "the purchaser keeps the pack");
        assertEq(m.pendingReceipts(), 1, "keep payment identified by the clone");
        assertEq(m.receipts(selected).kind, 1);
        bytes32 _expected9 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        uint256 syncPay = m.sync(_one(selected), 0, 0, _expected9);
        assertGt(syncPay, 0, "resolving the selection is paid");
        assertEq(m.openListingCount(), 0);
        assertEq(m.pendingReceipts(), 0);
        (uint256 tracked,,,,,) = m.totals();
        assertEq(tracked, 0, "the kept pack left the book");
        // Replacement: fresh paid primary mints, not a remint of anything returned.
        _drain();
        uint256 supply = SHAPES.totalSupply();
        uint256 bal = address(m).balance;
        (, uint256 target,) = m.edge(6);
        uint256[] memory q = new uint256[](1);
        q[0] = target;
        bytes32 _expected10 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        uint256 pay = m.build(6, q, 0, _expected10);
        assertEq(SHAPES.totalSupply() - supply, 2, "two new Shapes");
        assertEq(bal - address(m).balance, P + 0.002 ether + target + pay, "exact replacement cost");
    }

    /// @dev The purchaser takes the bid: the pack returns, is relisted with no new mint.
    function test_bid_returnedPackRelistedWithoutMint() public {
        _select();
        uint256 p0 = PURCHASER.balance;
        uint256 before = address(m).balance;
        vm.prank(PURCHASER);
        IFwaPurchaser(address(FWA)).acceptDepositorBid(selected);
        assertEq(PURCHASER.balance - p0, BACKING * 9_000 / 10_000, "purchaser gets 90% of backing");
        assertEq(address(m).balance, before, "no ETH to the manager on a bid");
        bytes32 _expected11 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        m.sync(_one(selected), 0, 0, _expected11);
        assertEq(m.idlePackCount(), 1, "pack back in inventory");
        _drain();
        uint256 supply = SHAPES.totalSupply();
        (, uint256 target,) = m.edge(6);
        uint256[] memory q = new uint256[](1);
        q[0] = target; // the selected listing's identifier was released, so the target is free again
        bytes32 _expected12 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        m.list(q, 0, _expected12);
        assertEq(SHAPES.totalSupply(), supply, "reuse mints nothing");
        assertEq(m.openListingCount(), 1);
        assertEq(m.idlePackCount(), 0);
    }

    /// @dev Removal while a listing is allocated: the real settlement still completes and syncs,
    ///      the returned pack cannot relist, and the owner still takes it out.
    function test_dewhitelistedDuringSelectionStillSettles() public {
        _select();
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaPurchaser(address(FWA)).setCollectionsWhitelisted(cols, false);
        assertFalse(FWA.canDeposit(address(PACKS)));
        (,,, uint256 packId,,,,,,,) = FWA.listings(selected);
        vm.prank(PURCHASER);
        IFwaPurchaser(address(FWA)).acceptDepositorBid(selected);
        bytes32 h = m.configurationHash();
        vm.prank(keeper);
        m.sync(_one(selected), 0, 0, h);
        assertEq(m.openListingCount(), 0);
        assertEq(m.idlePackCount(), 1, "pack back in inventory");
        (,, bool admitted) = m.edge(6);
        assertFalse(admitted, "no relist after removal");
        vm.prank(owner);
        m.withdrawPacks(owner, 1);
        assertEq(PACKS.ownerOf(packId), owner, "owner recovers the pack");
        uint256 cash = address(m).balance;
        vm.prank(owner);
        m.withdraw(owner, cash);
        (uint256 tracked, uint256 idle,,,,) = m.totals();
        assertEq(tracked + idle + address(m).balance, 0, "empty book, empty balance");
    }

    /// @dev A silent purchaser: after the settlement window the manager reclaims B (1 - s), which
    ///      beats keeping its 0.06 pack, and the purchaser receives the pack.
    function test_silentPurchaser_reclaimsBacking() public {
        _select();
        bytes32 _expected13 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        m.sync(new uint256[](0), 0, 0, _expected13); // applies the selection (paid), resolves nothing yet
        bytes32 _expected14 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Nothing.selector);
        m.sync(_one(selected), 0, 0, _expected14); // the purchaser's window is still open
        vm.warp(block.timestamp + FWA.settlementWindow());
        uint256 before = address(m).balance;
        uint256 k0 = keeper.balance;
        bytes32 _expected15 = TestVaultOps.configurationHash(m);
        vm.prank(keeper);
        m.sync(_one(selected), 0, 0, _expected15);
        assertEq(address(m).balance - before + (keeper.balance - k0), BACKING * 9_900 / 10_000);
        assertEq(m.openListingCount(), 0);
    }
}

contract Filler {
    IFWAV2 private immutable fwa;
    IShapePacks private immutable packs;
    IShapes private immutable shapes;

    constructor(IFWAV2 f, IShapePacks p, IShapes s) payable {
        (fwa, packs, shapes) = (f, p, s);
        IERC721Min(address(p)).setApprovalForAll(address(f), true);
    }

    function createAndList(uint256 backing) external returns (uint256) {
        uint32[] memory counts = new uint32[](9);
        counts[0] = 3;
        uint256 pack = packs.createPack{value: 0.03 ether + 3 * shapes.mintFee()}(new uint256[](0), counts);
        return fwa.listNFT{value: backing}(address(packs), pack);
    }

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }
}

/// @dev Attacker keeper: on receiving pay, tries to re-enter build, sync and withdraw.
contract ReentrantKeeper {
    PackManager immutable m;
    uint256 public attempts;
    uint256 public reentered;
    uint256 units;
    uint256[] quotes;

    constructor(PackManager m_) {
        m = m_;
    }

    function attack(uint256 u, uint256[] calldata q) external returns (uint256) {
        (units, quotes) = (u, q);
        bytes32 _expected16 = TestVaultOps.configurationHash(m);
        return m.build(u, q, 0, _expected16);
    }

    receive() external payable {
        if (attempts != 0) return;
        attempts = 3;
        bytes32 _expected17 = TestVaultOps.configurationHash(m);
        try m.build(units, quotes, 0, _expected17) { ++reentered; } catch {}
        bytes32 _expected18 = TestVaultOps.configurationHash(m);
        try m.sync(new uint256[](0), 0, 0, _expected18) { ++reentered; } catch {}
        try m.withdraw(address(this), 1) { ++reentered; } catch {}
    }
}
