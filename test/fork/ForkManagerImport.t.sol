// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {IShapes, IShapePacks, IERC721Min, IFWAV2} from "../../src/interfaces/External.sol";

interface IImportFees {
    function pendingFees() external view returns (uint256);
}

interface IImportTransfer {
    function safeTransferFrom(address from, address to, uint256 id) external;
}

/// @notice Existing canonical packs move intact between owner-controlled accounts. Mainnet
///         counterparties, their custody records and their paid mint path are never substituted.
contract ForkManagerImportTest is Test {
    uint256 constant BLOCK = 26_488_707;
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    address alice = makeAddr("pack-vault-test-import-owner");
    address bob = makeAddr("pack-vault-test-import-other-owner");
    address outsider = makeAddr("pack-vault-test-import-outsider");
    PackManagerFactory factory;

    function setUp() public {
        vm.createSelectFork("mainnet", BLOCK);
        address[3] memory actors = [alice, bob, outsider];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0, "actor has mainnet code");
            assertEq(actors[i].balance, 0, "actor has mainnet funds");
            vm.deal(actors[i], 50 ether);
        }
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        this.assertExecutionEnvironment();
        assertTrue(FWA.oracleExemptCollections(address(PACKS)), "real collection is not exempt at this block");
        assertEq(FWA.unsettledAcquisitionCount(), 0, "fixture requires actual drained queue");
        factory = DeployCore.deployFactory(FWA, SHAPES, PACKS);
    }

    function assertExecutionEnvironment() external {
        assertEq(msg.sender, address(this));
        assertEq(block.basefee, 0.15 gwei, "state-changing basefee");
        assertEq(tx.gasprice, 0.2 gwei, "state-changing gas price");
    }

    function _params() internal pure returns (VaultLib.Params memory p) {
        p.gasSchedule = VaultLib.defaultGasSchedule();
        p.backingRatioBps = 12_000;
        p.acceptedMintFee = 0.001 ether;
        p.packUnitsMask = uint64(1) << 6;
        p.minEdgeBps = 100;
        p.keeperShareBps = 2_500;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;
        p.maxTip = 0.05 gwei;
        p.workFee = 0.00002 ether;
        p.reserve = 0.005 ether;
        // The owner pays transaction gas; zero budgets make all optional relisting unpaid.
    }

    function _manager(uint256 funding) internal returns (PackManager m) {
        VaultLib.Params memory p = _params();
        bytes32 expected = factory.configHashFor(p);
        vm.prank(alice);
        m = factory.create{value: funding}(alice, p, expected);
    }

    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function _pack(address who, uint32 tiny, uint32 medium, uint32 large) internal returns (uint256 id) {
        this.assertExecutionEnvironment();
        uint32[] memory counts = new uint32[](9);
        counts[0] = tiny;
        counts[1] = medium;
        counts[3] = large; // canonical denominations .01, .05 and .5 ETH
        uint256 value = uint256(tiny) * 0.01 ether + uint256(medium) * 0.05 ether + uint256(large) * 0.5 ether;
        uint256 fee = (uint256(tiny) + medium + large) * SHAPES.mintFee();
        uint256 before = who.balance;
        vm.prank(who);
        id = PACKS.createPack{value: value + fee}(new uint256[](0), counts);
        assertEq(before - who.balance, value + fee, "fixture pays exact primary value and fees");
        assertEq(PACKS.valueOf(id), value);
    }

    function _approve(address who, PackManager m) internal {
        vm.prank(who);
        PACKS.setApprovalForAll(address(m), true);
    }

    function _import(PackManager m, uint256 id) internal {
        bytes32 expected = m.configurationHash();
        vm.prank(alice);
        m.importPacks(_one(id), expected);
    }

    function _assertEmpty(PackManager m) internal view {
        (uint256 tracked, uint256 idle, uint256 backing, uint256 active,, uint256 allocated) = m.totals();
        assertEq(tracked, 0);
        assertEq(idle, 0);
        assertEq(backing, 0);
        assertEq(active, 0);
        assertEq(allocated, 0);
        assertEq(m.idlePackCount() + m.recoveryPackCount() + m.openListingCount(), 0);
    }

    function test_ownerPullRecordsExactBackingAndShapeCountWithoutMintBurnFeeOrReward() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 1, 1, 0); // .06 ETH, two actual Shapes, not six
        _approve(alice, m);
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IImportFees(address(SHAPES)).pendingFees();
        uint256 cash = address(m).balance;
        uint256 wallet = alice.balance;
        vm.recordLogs();
        _import(m, id);
        Vm.Log[] memory logs = vm.getRecordedLogs();
        for (uint256 i; i < logs.length; ++i) {
            assertTrue(logs[i].topics[0] != keccak256("PrimaryMinted(uint256,uint256,uint256,uint256)"));
            if ((logs[i].emitter == address(SHAPES) || logs[i].emitter == address(PACKS))
                && logs[i].topics[0] == keccak256("Transfer(address,address,uint256)")) {
                assertTrue(logs[i].topics[1] != bytes32(0) && logs[i].topics[2] != bytes32(0), "mint or burn");
            }
        }
        assertEq(PACKS.ownerOf(id), address(m));
        assertEq(m.idleValueOf(id), 0.06 ether);
        assertEq(m.inventoryShapeCount(id), 2);
        (uint256 tracked, uint256 idle,,,,) = m.totals();
        assertEq(tracked, 0.06 ether);
        assertEq(idle, 0.06 ether);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IImportFees(address(SHAPES)).pendingFees(), fees);
        assertEq(address(m).balance, cash);
        assertEq(alice.balance, wallet, "import makes no ETH payment");
        vm.prank(alice);
        m.withdrawPacks(alice, 1);
        _assertEmpty(m);
        assertEq(m.inventoryShapeCount(id), 0);
        assertEq(PACKS.ownerOf(id), alice);
        _import(m, id);
        assertEq(m.inventoryShapeCount(id), 2, "round trip must not ratchet counts");
    }

    function test_preheldSafeTransferNeedsExplicitOwnerImport() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 3, 0, 0);
        vm.prank(alice);
        IImportTransfer(address(PACKS)).safeTransferFrom(alice, address(m), id);
        _assertEmpty(m);
        _import(m, id);
        assertEq(m.idlePackAt(0), id);
        assertEq(m.inventoryShapeCount(id), 3);
    }

    function test_ownerBoundaryAndThirdPartyApprovalCannotBePulled() public {
        PackManager m = _manager(0);
        uint256 id = _pack(bob, 1, 1, 0);
        _approve(bob, m);
        bytes32 expected = m.configurationHash();
        vm.expectRevert(Ownable.Unauthorized.selector);
        vm.prank(bob);
        m.importPacks(_one(id), expected);
        vm.expectRevert(PackManager.InvalidPack.selector);
        vm.prank(alice);
        m.importPacks(_one(id), expected);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vm.prank(outsider);
        m.unlistForWithdrawal(_one(1));
        assertEq(PACKS.ownerOf(id), bob);
        _assertEmpty(m);
    }

    function test_staleConfigurationRejectsBeforeUnapprovedTransfer() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 1, 1, 0);
        bytes32 stale = m.configurationHash();
        vm.prank(alice);
        m.setListingPaused(true);
        vm.expectRevert(PackAccount.ConfigurationChanged.selector);
        vm.prank(alice);
        m.importPacks(_one(id), stale);
        assertEq(PACKS.ownerOf(id), alice);
        _assertEmpty(m);
    }

    function test_duplicateBatchIsAtomicAndBoundsRejectBeforeTransfer() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 1, 1, 0);
        _approve(alice, m);
        uint256[] memory ids = new uint256[](2);
        ids[0] = id;
        ids[1] = id;
        bytes32 expected = m.configurationHash();
        vm.expectRevert(PackManager.Tracked.selector);
        vm.prank(alice);
        m.importPacks(ids, expected);
        assertEq(PACKS.ownerOf(id), alice);
        _assertEmpty(m);
        vm.expectRevert(VaultLib.BadBatch.selector);
        vm.prank(alice);
        m.importPacks(new uint256[](17), expected);
        vm.expectRevert(VaultLib.BadBatch.selector);
        vm.prank(alice);
        m.importPacks(new uint256[](0), expected);
    }

    function test_contentsBeyondThirtyAreRejectedAndPreheldPackRemainsRescuable() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 31, 0, 0);
        vm.prank(alice);
        PACKS.transferFrom(alice, address(m), id);
        bytes32 expected = m.configurationHash();
        vm.expectRevert(PackManager.InvalidPack.selector);
        vm.prank(alice);
        m.importPacks(_one(id), expected);
        _assertEmpty(m);
        assertEq(PACKS.ownerOf(id), address(m));
        vm.prank(alice);
        m.rescue(IERC721Min(address(PACKS)), id, alice);
        assertEq(PACKS.ownerOf(id), alice);
        assertEq(PACKS.valueOf(id), 0.31 ether);
    }

    function test_oversizedSealedRecoveryMigratesIntactWithExactCount() public {
        PackManager source = _manager(0);
        PackManager destination = _manager(0);
        uint256 id = _pack(alice, 0, 0, 1); // one .5 ETH Shape; oversized ordinary recipe
        _approve(alice, source);
        _import(source, id);
        assertEq(source.recoveryPackAt(0), id);
        assertEq(source.inventoryShapeCount(id), 1);
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IImportFees(address(SHAPES)).pendingFees();
        vm.prank(alice);
        source.withdrawPacks(address(destination), 1);
        _assertEmpty(source);
        assertEq(source.inventoryShapeCount(id), 0);
        _import(destination, id);
        assertEq(destination.recoveryPackCount(), 1);
        assertEq(destination.inventoryShapeCount(id), 1);
        assertEq(destination.idleValueOf(id), 0.5 ether);
        vm.prank(alice);
        destination.withdrawPacks(alice, 1);
        _assertEmpty(destination);
        assertEq(PACKS.ownerOf(id), alice);
        assertEq(PACKS.valueOf(id), 0.5 ether);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IImportFees(address(SHAPES)).pendingFees(), fees);
    }

    function test_unsealedPackCannotBeImportedButRealClaimRecoversItsPrincipal() public {
        PackManager m = _manager(0);
        uint256 id = _pack(alice, 1, 1, 0);
        vm.prank(alice);
        PACKS.unseal(id, alice);
        assertEq(PACKS.claimantOf(id), alice);
        bytes32 expected = m.configurationHash();
        vm.expectRevert();
        vm.prank(alice);
        m.importPacks(_one(id), expected);
        _assertEmpty(m);
        uint256 balance = alice.balance;
        vm.prank(alice);
        PACKS.claimEth(id, 2, payable(alice));
        assertEq(alice.balance - balance, 0.06 ether, "real claim returns exact principal");
    }

    function _list(PackManager m, uint256 packId) internal returns (uint256 listingId, uint256 backing) {
        bool allowed;
        (, backing, allowed) = m.relistEdgeFor(packId);
        assertTrue(allowed);
        assertEq(backing, 0.072 ether);
        bytes32 expected = m.configurationHash();
        vm.prank(alice);
        uint256 paid = m.list(_one(backing), 0, expected);
        assertEq(paid, 0, "owner listing uses zero keeper budgets");
        listingId = m.openListingAt(0);
        assertEq(m.position(listingId).packId, packId);
    }

    function _unlist(PackManager m, uint256 listingId) internal {
        if (FWA.topListingId() == listingId && vm.getBlockTimestamp() < FWA.topListingSince() + 12 hours) {
            vm.warp(FWA.topListingSince() + 12 hours);
            vm.fee(0.15 gwei);
            vm.txGasPrice(0.2 gwei);
        }
        vm.prank(alice);
        m.setListingPaused(true);
        uint256 cash = address(m).balance;
        uint256 backing = m.position(listingId).backing;
        vm.prank(alice);
        m.unlistForWithdrawal(_one(listingId));
        assertEq(address(m).balance - cash, backing, "unlist returns exact backing without reward");
        assertFalse(m.windingDown(), "asset migration never enables liquidation");
    }

    function test_pausedUnlistTransferImportRelistAndReturnPreservesEveryAsset() public {
        PackManager source = _manager(0.5 ether);
        PackManager destination = _manager(0);
        uint256 id = _pack(alice, 1, 1, 0);
        _approve(alice, source);
        _import(source, id);
        uint256[] memory contents = PACKS.contentsOf(id);
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IImportFees(address(SHAPES)).pendingFees();
        uint256 ownerCash = alice.balance;
        uint256 accountCash = address(source).balance + address(destination).balance;
        (uint256 listing,) = _list(source, id);
        _unlist(source, listing);
        bytes32 expected = source.configurationHash();
        vm.expectRevert(StrategyLib.Nothing.selector);
        vm.prank(outsider);
        source.liquidate(1, 0, expected);
        vm.prank(alice);
        source.withdrawPacks(address(destination), 1);
        _import(destination, id);
        uint256 cash = address(source).balance;
        vm.prank(alice);
        source.withdraw(alice, cash);
        vm.prank(alice);
        (bool sent,) = address(destination).call{value: cash}("");
        assertTrue(sent);
        (listing,) = _list(destination, id);
        _unlist(destination, listing);
        vm.prank(alice);
        destination.withdrawPacks(address(source), 1);
        _import(source, id);
        uint256 returnedCash = address(destination).balance;
        vm.prank(alice);
        destination.withdraw(alice, returnedCash);
        vm.prank(alice);
        (bool returned,) = address(source).call{value: returnedCash}("");
        assertTrue(returned, "round trip returns the actual backing cash too");
        vm.prank(alice);
        source.setListingPaused(false); // removing the migration trigger makes the same pack listable again
        (listing,) = _list(source, id);
        _unlist(source, listing);
        vm.prank(alice);
        source.withdrawPacks(alice, 1);
        vm.prank(alice);
        source.setListingPaused(false);
        uint256 sourceCash = address(source).balance;
        uint256 destinationCash = address(destination).balance;
        if (sourceCash != 0) { vm.prank(alice); source.withdraw(alice, sourceCash); }
        if (destinationCash != 0) { vm.prank(alice); destination.withdraw(alice, destinationCash); }
        _assertEmpty(source);
        _assertEmpty(destination);
        assertEq(address(source).balance + address(destination).balance, 0);
        assertEq(alice.balance, ownerCash + accountCash, "all account ETH returned, excluding unbilled Forge wallet gas");
        assertEq(PACKS.ownerOf(id), alice);
        assertEq(PACKS.valueOf(id), 0.06 ether);
        assertEq(keccak256(abi.encode(PACKS.contentsOf(id))), keccak256(abi.encode(contents)));
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IImportFees(address(SHAPES)).pendingFees(), fees);
        for (uint256 i; i < contents.length; ++i) assertEq(SHAPES.ownerOf(contents[i]), address(PACKS));
    }
}

import {MainRenewalBase} from "./ForkMainRenewal.t.sol";
import {IFwaSettle} from "./ForkSelection.t.sol";
interface IImportGift {
    function addToPack(uint256 packId, uint256[] calldata shapeIds, uint32[] calldata mintCounts) external payable;
}

contract ForkManagerMixedRecoveryTest is MainRenewalBase {
    function test_unsealedGiftCannotBlockIntactSealedRecoveryWithdrawal() public {
        _select(false);
        PackManager m = PackManager(payable(address(account)));
        account.sync(new uint256[](0), 0, 0, account.configurationHash());
        uint32[] memory counts = new uint32[](9);
        counts[3] = 1;
        uint256 mintFee = SHAPES.mintFee();
        vm.deal(accountOwner, 1 ether);
        vm.prank(accountOwner);
        uint256 sealedId = PACKS.createPack{value: 0.5 ether + mintFee}(new uint256[](0), counts);
        vm.startPrank(accountOwner);
        PACKS.setApprovalForAll(address(m), true);
        m.importPacks(one(sealedId), m.configurationHash());
        vm.stopPrank();
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        counts[3] = 0; counts[0] = 31;
        vm.deal(selectedPurchaser, selectedPurchaser.balance + 1 ether);
        vm.startPrank(selectedPurchaser);
        IImportGift(address(PACKS)).addToPack{value: 0.31 ether + 31 * SHAPES.mintFee()}(packId, new uint256[](0), counts);
        PACKS.transferFrom(selectedPurchaser, address(m), packId);
        vm.stopPrank();
        account.sync(one(selected), 0, 0, account.configurationHash());
        assertEq(m.recoveryPackCount(), 2);
        assertEq(PACKS.contentsOf(packId).length, 34, "real gift exceeds import bound");
        vm.prank(accountOwner); m.setExiting(true);
        m.recoverLiquidate(1);
        assertTrue(m.recoveryUnsealed(packId));
        assertEq(m.idleValueOf(packId), 0.04 ether, "four actual Shapes remain owed");
        vm.prank(accountOwner); m.setExiting(false);
        uint256 supply = SHAPES.totalSupply();
        vm.expectRevert(PackManager.InvalidPack.selector);
        vm.prank(accountOwner); m.withdrawRecoveryPack(accountOwner, 0, packId);
        vm.prank(accountOwner); m.withdrawRecoveryPack(accountOwner, 0, sealedId);
        assertEq(PACKS.ownerOf(sealedId), accountOwner);
        assertEq(PACKS.valueOf(sealedId), 0.5 ether);
        assertEq(SHAPES.totalSupply(), supply, "intact withdrawal does not burn another Shape");
        assertFalse(m.windingDown());
        assertEq(m.recoveryPackAt(0), packId, "swap-pop preserves the remaining claim");
        assertEq(m.recoveryPackCount(), 1);
        assertEq(m.idleValueOf(packId), 0.04 ether);
        vm.prank(accountOwner); m.setExiting(true);
        uint256 cash = address(m).balance;
        m.recoverLiquidate(1);
        assertEq(address(m).balance - cash, 0.04 ether);
        assertEq(m.recoveryPackCount(), 0);
    }
}
