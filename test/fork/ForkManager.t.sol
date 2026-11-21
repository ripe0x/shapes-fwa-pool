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
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
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
    p.essentialCap = 0.03 ether;
    p.essentialRate = 0.005 ether;
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
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS, KeeperPolicyV1(address(vault.keeperPolicy())));
        vm.deal(carol, 50 ether);
    }

    function _create(address who, uint256 funding) internal returns (PackManager m) {
        vm.prank(who);
        m = factory.create{value: funding}(who, managerParams());
    }

    function _build(PackAccount a, uint256 n) internal returns (uint256 pay) {
        vm.prank(keeper);
        pay = TestVaultOps.restock(a, n, UNITS, 0);
    }

    function _sumBacking(PackAccount a) internal view returns (uint256 sum) {
        for (uint256 i; i < a.openListingCount(); ++i) sum += a.position(a.openListingAt(i)).backing;
    }

    // ------------------------------------------------------------------ factory

    function test_createInitializesAtomically() public {
        address predicted = vm.computeCreateAddress(address(factory), vm.getNonce(address(factory)));
        uint256 dust = predicted.balance; // a fresh address can still hold mainnet dust
        uint256 g = gasleft();
        PackManager m = _create(alice, 1 ether);
        emit log_named_uint("gas factory.create (clone + initialize)", g - gasleft());
        assertEq(address(m), predicted);
        assertEq(address(m).code.length, 44, "ERC-1167 minimal proxy (PUSH0 form)");
        assertEq(m.owner(), alice);
        assertEq(address(m).balance, 1 ether + dust, "funding forwarded in the same call");
        assertEq(address(factory).balance, 0, "factory holds no ETH");
        assertEq(factory.managerCount(), 1);
        assertEq(factory.managerAt(0), address(m));
        assertTrue(factory.isManager(address(m)));
        assertEq(keccak256(abi.encode(m.getParams())), keccak256(abi.encode(managerParams())));
        assertEq(address(m.keeperPolicy()), factory.policy());
        (uint256 r, uint256 e) = m.budget();
        assertEq(r, managerParams().routineCap);
        assertEq(e, managerParams().essentialCap);
        assertEq(m.deploymentBlock(), block.number);
        assertEq(m.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertTrue(IApproval(address(PACKS)).isApprovedForAll(address(m), address(FWA)), "FWA may take listed packs");
        assertEq(address(m.fwa()), address(FWA));
        assertEq(m.factory(), address(factory));
        assertFalse(m.listingPaused());
        assertFalse(m.windingDown());
        // The implementation never gets an owner.
        assertEq(factory.implementation().owner(), address(0));
    }

    function test_initializeOnlyOnceOnlyByFactory() public {
        PackManager m = _create(alice, 0.1 ether);
        PackManager impl = factory.implementation();
        address policy = factory.policy();
        VaultLib.Params memory p = managerParams();
        vm.prank(address(factory));
        vm.expectRevert(Ownable.AlreadyInitialized.selector);
        impl.initialize(bob, p, policy);
        vm.prank(address(factory));
        vm.expectRevert(Ownable.AlreadyInitialized.selector);
        m.initialize(bob, p, policy);
        vm.prank(bob);
        vm.expectRevert(Ownable.Unauthorized.selector);
        m.initialize(bob, p, policy);
        assertEq(m.owner(), alice);
    }

    function test_createRejectsBadInputs() public {
        VaultLib.Params memory p = managerParams();
        p.workFee = uint64(VaultLib.MAX_WORK_FEE + 1);
        vm.prank(alice);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        factory.create(alice, p);
        vm.prank(alice);
        vm.expectRevert(Ownable.NewOwnerIsZeroAddress.selector);
        factory.create(address(0), managerParams());
        assertEq(factory.managerCount(), 0);
    }

    // ------------------------------------------------------------------ owner controls

    function test_onlyOwnerControls_andHandover() public {
        PackManager m = _create(alice, 1 ether);
        address[3] memory others = [bob, keeper, address(factory)];
        address policy = factory.policy();
        VaultLib.Params memory p = managerParams();
        for (uint256 i; i < others.length; ++i) {
            vm.startPrank(others[i]);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.withdraw(others[i], 1);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.withdrawPacks(others[i], 1);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.rescue(IERC721Min(address(PACKS)), 1, others[i]);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.setParams(p);
            vm.expectRevert(Ownable.Unauthorized.selector);
            m.setPolicy(policy);
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
        // 0.995 idle ETH: each position needs 0.06 + 0.002 mint fees + ~0.0652 backing.
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
            packIds[i] = packId;
        }
        // Keep incentive: the pack (0.06) beats FWA's best bid (91.5% of backing) by >= 0.0003 ETH
        // after the purchaser's redeem gas at the ceiling.
        (, uint256 b,) = m.edge(UNITS);
        assertGe(P, b * 9_150 / 10_000 + 0.0003 ether + 160_000 * 0.5 gwei);

        // The owner withdraws spare cash at any time.
        uint256 spare = address(m).balance;
        uint256 a0 = alice.balance;
        vm.prank(alice);
        m.withdraw(alice, spare);
        assertEq(alice.balance - a0, spare);
        assertEq(address(m).balance, 0);

        // Exit: anyone unlists (essential work, paid from the manager's own essential budget, which
        // needs free ETH: with none left, the keeper is paid nothing and the work still happens).
        vm.prank(alice);
        m.setExiting(true);
        assertTrue(m.listingPaused());
        uint256[] memory ids = TestVaultOps.open(m);
        uint256 b0 = bob.balance;
        vm.prank(bob);
        uint256 exitPay = TestVaultOps.unlist(m, ids, 0);
        assertGt(exitPay, 0, "exit work is paid from the returned backing, after the work");
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

    function test_pauseStopsBuildsNotMaintenance() public {
        PackManager m = _create(alice, 1 ether);
        _build(m, 2);
        vm.prank(alice);
        m.setListingPaused(true);
        uint256[] memory quotes = TestVaultOps.proposals(m, 1, UNITS);
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.Paused.selector);
        m.build(UNITS, quotes, 0);
        // Stopping paid automation: zero budgets. Strategy work then pays nothing.
        VaultLib.Params memory p = managerParams();
        (p.routineCap, p.routineRate, p.essentialCap, p.essentialRate) = (0, 0, 0, 0);
        vm.prank(alice);
        m.setParams(p);
        (uint256 r, uint256 e) = m.budget();
        assertEq(r + e, 0);
        vm.prank(alice);
        m.setListingPaused(false);
        uint256 k0 = keeper.balance;
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.Payment.selector);
        m.build(UNITS, quotes, 1); // a keeper demanding pay is refused before any work
        vm.prank(alice);
        m.build(UNITS, quotes, 0); // the owner can always run it unpaid
        assertEq(keeper.balance, k0);
        assertEq(m.openListingCount(), 3);
    }

    // ------------------------------------------------------------------ isolation

    function test_isolation_managersAndVault() public {
        // Pooled vault with a priced deposit, and two managers of different sizes.
        vm.prank(bob);
        vault.deposit{value: vault.requestCharge() + 2 ether}();
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
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.UnlistNotAllowed.selector);
        a.unlist(aIds, 0);
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
        vm.prank(keeper);
        a.sync(one, 0, 0);
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
///         right before a historical acquisition request whose real VRF word selects listing #20
///         of 30 posted at exactly 65,158,469,945,350,000 wei backing (sim/find_selection.py), then
///         replays the real request and fulfillment calls. Only the purchaser's choice is ours.
contract ForkManagerSelectionTest is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    bytes32 constant REQUEST_TX = 0xbe792fe6c591b28151d56eac601e8de8b9be5aadf87b2077ec37f315ee2b0b68;
    uint256 constant REQUEST_BLOCK = 26_402_342;
    uint256 constant INDEX = 20;
    uint256 constant SLOT = 3055;
    address constant PURCHASER = 0x82D16fF1C724ab72F218A3f7f6DD3E5385ee87E8;
    uint256 constant BACKING = 65_158_469_945_350_000;
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
        KeeperPolicyV1 policy = new KeeperPolicyV1();
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS, policy);
        vm.deal(owner, 5 ether);
        vm.deal(keeper, 1 ether);
        vm.prank(owner);
        m = factory.create{value: 2 ether}(owner, managerParams());
        (, uint256 target, bool ok) = m.edge(6);
        assertTrue(ok);
        assertEq(target, BACKING, "exact backing the replayed word was found for");
        Filler filler = new Filler{value: 3 ether}(FWA, PACKS, SHAPES);
        for (uint256 i; i < 30; ++i) {
            if (i == INDEX) {
                uint256[] memory one = new uint256[](1);
                one[0] = BACKING;
                vm.prank(keeper);
                m.build(6, one, 0);
                selected = m.openListingAt(0);
            } else {
                filler.createAndList(BACKING);
            }
        }
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
        vm.prank(keeper);
        uint256 syncPay = m.sync(_one(selected), 0, 0);
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
        vm.prank(keeper);
        uint256 pay = m.build(6, q, 0);
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
        vm.prank(keeper);
        m.sync(_one(selected), 0, 0);
        assertEq(m.idlePackCount(), 1, "pack back in inventory");
        _drain();
        uint256 supply = SHAPES.totalSupply();
        (, uint256 target,) = m.edge(6);
        uint256[] memory q = new uint256[](1);
        q[0] = target; // the selected listing's identifier was released, so the target is free again
        vm.prank(keeper);
        m.list(q, 0);
        assertEq(SHAPES.totalSupply(), supply, "reuse mints nothing");
        assertEq(m.openListingCount(), 1);
        assertEq(m.idlePackCount(), 0);
    }

    /// @dev A silent purchaser: after the settlement window the manager reclaims B (1 - s), which
    ///      beats keeping its 0.06 pack, and the purchaser receives the pack.
    function test_silentPurchaser_reclaimsBacking() public {
        _select();
        vm.prank(keeper);
        m.sync(new uint256[](0), 0, 0); // applies the selection (paid), resolves nothing yet
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Nothing.selector);
        m.sync(_one(selected), 0, 0); // the purchaser's window is still open
        vm.warp(block.timestamp + FWA.settlementWindow());
        uint256 before = address(m).balance;
        uint256 k0 = keeper.balance;
        vm.prank(keeper);
        m.sync(_one(selected), 0, 0);
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
        return m.build(u, q, 0);
    }

    receive() external payable {
        if (attempts != 0) return;
        attempts = 3;
        try m.build(units, quotes, 0) { ++reentered; } catch {}
        try m.sync(new uint256[](0), 0, 0) { ++reentered; } catch {}
        try m.withdraw(address(this), 1) { ++reentered; } catch {}
    }
}
