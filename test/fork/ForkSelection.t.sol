// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {
    IShapes, IShapePacks, IFWAV2, LISTING_ACTIVE, LISTING_ALLOCATED
} from "../../src/interfaces/External.sol";
import {IOwnable, IOracleAdmin, IFwaAdmin} from "./ForkBase.sol";

interface IFwaSettle {
    function acceptDepositorBid(uint256 listingId) external;
    function keepNFT(uint256 listingId) external;
    function setCollectionsWhitelisted(address[] calldata collections, bool allowed) external;
    function topListingId() external view returns (uint256);
    function processAcquisitions(uint256 maxCount) external returns (uint256 processed);
    function quoteAcquisitionPrice() external view returns (uint256, uint256, uint256);
    function acquire(address requester, uint256 count, uint256, uint256, uint256 maxFeeBps) external payable;
}

/// @notice Outcome paths driven by FWA's real randomness. sim/find_selection.py found historical
///         requests whose real VRF word selects the vault listing among 30 real listings posted
///         just before the request. Each test forks right before that request, posts the real
///         listings, then replays the real request and fulfillment transactions. Only the
///         purchaser's choice is ours to drive, through the purchaser's own call.
/// @dev     Every listing posts exactly `B` = edge(6). Weight is 1e36 / B, so any other backing
///          changes the selecting word and breaks the replay; the backing is the value
///          `sim/find_selection.py 64896174863380000 30` searched against.
abstract contract SelectionBase is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint256 constant COUNT = 1;
    uint256 constant FIXTURE_COUNT = 30;
    uint256 constant UNITS = 6; // the 0.06 ETH recipe: one 0.05 and one 0.01 Shape, two paid mints
    // edge(6): floor(0.06 - (0.0003 + 160000 x 2 gwei)) x 10000 / 9150, to the 10,000 wei. The
    // purchaser's redeem gas is priced at the fixed PURCHASER_GAS_PRICE = 2 gwei bound, not the
    // keeper's gas ceiling. Every one of the 30 listings posts this exact backing.
    uint256 constant B = 64_800_000_000_000_000;

    struct Candidate {
        bytes32 requestTx;
        uint256 requestBlock;
        uint256 fulfillBlock;
        uint256 fulfillTimestamp;
        uint256 index; // which of our 30 listings the real word selects
        uint256 slot;
        address purchaser;
    }

    // Block 26,310,897: before ShapePacks' FWA admission; FWA's owner whitelists and oracle-exempts
    // packs (its real D62 calls) first. Our listing is index 22 of 30.
    function primary() internal pure returns (Candidate memory) {
        return Candidate(
            0x3c030ce52b8ef58a5c499b9c6e6d02e4233ae670bcb25c7667fe20404e493f36,
            26_310_897,
            26_310_902,
            1_793_427_491,
            7,
            277,
            0x88d0e89E7f502Aa49a564b683e19089c771776c3
        );
    }

    // Block 26,335,398: likewise before admission. Our listing is index 10 of 30.
    function second() internal pure returns (Candidate memory) {
        return Candidate(
            0x89b2434d78c82537ce63f1cde0fd259f473ba88386fc52b02c6656d800b1bbaf,
            26_233_490,
            26_233_496,
            1_792_495_679,
            21,
            4142,
            address(bytes20(hex"6ba9ad599e6271252817933831e3148936cf742a"))
        );
    }

    PackVault vault;
    uint256 selected;
    uint256 expectedShare; // the selecting acquisition's flat fee share per listing
    // FWA's inputs to that share, read just before the replayed request.
    uint256 acqFee;
    uint256 acqCutBps;
    uint256 acqCrownBps; // zero when no listing holds the crown
    uint256 acqActive;
    uint256 deployBalance; // vault balance right after deployment (seed plus any mainnet dust)
    uint256 activationDebt; // real FWA debt read while the selected listing was still Active
    uint256 selectPay; // keeper pay to this contract for the build in _select

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    function _select(Candidate memory c) internal {
        vm.createSelectFork("mainnet", c.requestTx);
        // Both candidates precede ShapePacks' FWA admission (26,415,582): the real admin calls that
        // made D62 live are replayed first, before anything lists.
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaSettle(address(FWA)).setCollectionsWhitelisted(cols, true);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue empty before the request");

        _beforeSelectionDeploy();
        VaultLib.Params memory p;
        p.gasSchedule = VaultLib.defaultGasSchedule();
        p.backingRatioBps = 10_800;
        p.acceptedMintFee = 0.001 ether;
        p.minDeposit = 0.01 ether;
        p.minDistribution = 0.01 ether;
        p.minEdgeBps = 100;
        p.payMarkupBps = 0;
        p.maxTip = 0.05 gwei;
        p.keeperShareBps = 2_500;
        p.upliftBoundBps = 200;
        p.packUnitsMask = uint64(1) << UNITS;
        p.gasCeiling = 0.15 gwei; // historical inventory bootstrap; not keeper viability evidence
        p.maxTip = 0;
        p.essentialCeiling = 0.5 gwei;

        p.tvlCap = 100 ether;
        p.routineCap = 0.3 ether; // bytecode maxima: these suites test mechanics, not budgets
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vm.deal(address(this), 10 ether);
        address vaultOwner = makeAddr("pack-vault-test-selection-owner");
        assertEq(vaultOwner.code.length, 0);
        assertEq(vaultOwner.balance, 0);
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, vaultOwner, p, 3 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        deployBalance = address(vault).balance;
        (, uint256 edgeBacking, bool edgeOk) = vault.edge(UNITS);
        assertTrue(edgeOk, "edge(6) lists at gasCeiling 0.5 gwei");
        assertEq(edgeBacking, B, "edge(6) backing is the VRF-replay value B");
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES))
        );
        uint256 b0 = address(this).balance;
        // One real vault listing (built and listed straight into ShapePacks at backing B) and 29
        // independent third-party listings, all at the exact backing B so every weight is 1e36 / B.
        for (uint256 i; i < FIXTURE_COUNT; ++i) {
            if (i == c.index) {
                TestVaultOps.restock(vault, COUNT, UNITS, 0); // build+list our one pack
                selected = vault.openListingAt(0);
                assertEq(vault.position(selected).backing, B, "our listing posts exactly B");
            } else {
                filler.createAndList(B);
            }
        }
        selectPay = address(this).balance - b0;
        p.gasCeiling = 0.5 gwei;
        p.maxTip = 0.05 gwei;
        p.backingRatioBps = 12_000;
        bytes32 nextConfig = vault.configurationHash();
        vm.prank(vaultOwner);
        vault.setParams(p, nextConfig);
        (,,,,,,, uint256 liveActivationDebt, uint256 slot,, uint8 status) = FWA.listings(selected);
        activationDebt = liveActivationDebt;
        assertEq(slot, c.slot, "slot prediction");
        assertEq(status, LISTING_ACTIVE);

        // The flat share this acquisition pays each active listing, from FWA's own formula.
        uint256 fee = FWA.acquisitionFee();
        acqFee = fee;
        acqCutBps = FWA.ownerAcquisitionFeeBps();
        acqCrownBps = IFwaSettle(address(FWA)).topListingId() != 0 ? FWA.topListingShareBps() : 0;
        acqActive = FWA.activeListingCount();
        uint256 distributable = fee - fee * acqCutBps / 10_000;
        distributable -= distributable * acqCrownBps / 10_000;
        expectedShare = distributable / acqActive;

        // vm.transact re-forks at the transaction and would drop our listings, so each real
        // transaction is replayed as its original call: same sender, origin, calldata, value
        // and gas price. The fulfillment is the Chainlink node's call into the real coordinator
        // with the real proof; the coordinator checks the request block's real hash.
        string memory key = string.concat(".", vm.toString(c.requestBlock));
        string memory fx = vm.readFile(c.requestBlock == 26_233_490
            ? "test/fixtures/completion-selection.json" : "test/fixtures/selection.json");
        _call(fx, key, "req");
        vm.roll(c.fulfillBlock);
        vm.warp(c.fulfillTimestamp);
        vm.setBlockhash(c.requestBlock, vm.parseJsonBytes32(fx, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fx, string.concat(key, ".fulBaseFee")));
        _call(fx, key, "ful");

        address purchaser;
        (,, purchaser,,,,,,,, status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED, "real word selected our listing");
        assertEq(purchaser, c.purchaser);
        assertApproxEqAbs(FWA.feeCredit(address(vault)), expectedShare, 2, "fee share credited on selection");
        assertEq(vault.openListingCount(), COUNT);
    }

    function _beforeSelectionDeploy() internal virtual {}

    function _call(string memory fx, string memory key, string memory leg) internal {
        address from = vm.parseJsonAddress(fx, string.concat(key, ".", leg, "From"));
        address to = vm.parseJsonAddress(fx, string.concat(key, ".", leg, "To"));
        bytes memory input = vm.parseJsonBytes(fx, string.concat(key, ".", leg, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req") ? vm.parseJsonUint(fx, string.concat(key, ".reqValue")) : 0;
        vm.txGasPrice(vm.parseJsonUint(fx, string.concat(key, ".", leg, "GasPrice")));
        // msg.value is funded from this contract; the sender's own balance is not under test.
        vm.deal(address(this), address(this).balance + value);
        vm.prank(from, from);
        (bool ok, bytes memory ret) = to.call{value: value}(input);
        if (!ok) {
            assembly ("memory-safe") {
                revert(add(ret, 32), mload(ret))
            }
        }
    }

    /// @dev Reconstructs the busy acquisition queue the historical count=5 candidates provided for
    ///      free: a funded buyer submits a real acquisition request through FWA's public entry point
    ///      against the 29 foreign listings. The candidates now select with a single-count request
    ///      (fully drained by the replayed fulfillment), so nothing is left pending. The request's
    ///      VRF is never fulfilled here, so it stays unsettled (the vault refuses to list while FWA's
    ///      queue is busy) until a later drain past its deadline refunds it. Returns the buyer.
    function _pendForeignAcquisition() internal returns (address buyer) {
        buyer = makeAddr("pack-vault-test-selection-foreign-buyer");
        assertEq(buyer.code.length, 0);
        assertEq(buyer.balance, 0);
        vm.deal(buyer, 2 ether);
        (,, uint256 price) = IFwaSettle(address(FWA)).quoteAcquisitionPrice();
        vm.prank(buyer);
        IFwaSettle(address(FWA)).acquire{value: price}(buyer, 1, 0, 0, 10_000);
        assertGt(FWA.unsettledAcquisitionCount(), 0, "foreign request makes FWA's queue busy");
    }
}

contract ForkSelectionTest is SelectionBase {
    receive() external payable {} // this contract calls paid work directly

    /// @dev Bid: the purchaser takes FWA's best bid (90% of B). The vault keeps no ETH on the bid;
    ///      `sync` then resolves the position and returns the pack to idle inventory. Resolving also
    ///      sweeps the selection's economical fee credit into the vault, so the vault's net ETH
    ///      change across the sync is the swept credit minus the keeper pay.
    ///      (The returned pack cannot be relisted at this fork: FWA has 4 real pending acquisitions
    ///      awaiting VRF we cannot fulfill, so it stages new listings. Relist-without-mint is
    ///      exercised in ForkVaultLifecycle, where the queue is empty.)
    function test_bidOutcome_packReturnsIdle() public {
        Candidate memory c = primary();
        _select(c);
        uint256 pBefore = c.purchaser.balance;
        uint256 vBefore = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        assertEq(c.purchaser.balance - pBefore, B * 9_000 / 10_000, "purchaser gets 90% of backing");
        assertEq(address(vault).balance, vBefore, "no ETH back to the vault on a bid outcome");

        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        uint256 creditSwept = FWA.feeCredit(address(vault)); // the selection's flat fee share
        assertApproxEqAbs(creditSwept, expectedShare, 2, "credit is the selecting acquisition's share");
        uint256 keeperBefore = address(this).balance;
        uint256 balBeforeSync = address(vault).balance;
        TestVaultOps.sync(vault, one, 0);
        uint256 syncPay = address(this).balance - keeperBefore;
        assertGt(syncPay, 0, "resolving a position is paid");
        // Sync pulls the whole fee credit into the vault and pays the keeper. Conservation, sign-safe
        // because here the swept fee share exceeds the keeper pay (the vault nets a small gain):
        // starting balance + swept credit == ending balance + keeper pay.
        assertEq(balBeforeSync + creditSwept, address(vault).balance + syncPay, "sync ETH conserved: +swept credit, -keeper pay");
        assertEq(TestVaultOps.idle(vault).length, 1, "pack back in inventory");
        assertEq(TestVaultOps.open(vault).length, COUNT - 1);
    }

    /// @dev Keep: the purchaser keeps the pack. The vault receives exactly B(1 - s) = B x 9,900 /
    ///      10,000 (FWA's live 1% owner settlement fee) and the pack leaves. `sync` then resolves
    ///      the settled position.
    ///      (A replacement build cannot run at this fork for the same busy-queue reason as above;
    ///      that a built pack mints 2 Shapes and pays exactly 0.002 ETH is covered in
    ///      ForkVaultLifecycle.test_builtPackCostsAndMints.)
    function test_keepOutcome_backingBackLessFee() public {
        Candidate memory c = primary();
        _select(c);
        uint256 packId = vault.position(selected).packId;
        uint256 vBefore = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        assertEq(address(vault).balance - vBefore, B * 9_900 / 10_000, "backing less the 1% settlement fee");
        assertEq(PACKS.ownerOf(packId), c.purchaser, "pack to the purchaser");
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        TestVaultOps.sync(vault, one, 0);
        assertEq(TestVaultOps.idle(vault).length, 0, "no idle pack: the purchaser kept it");
        assertEq(TestVaultOps.open(vault).length, COUNT - 1);
    }

    /// @dev Silent purchaser: after the settlement window the vault reclaims the backing through
    ///      `sync` (B(1 - s) > P, so it keeps the ETH, D9) and the pack goes to the purchaser.
    function test_silentPurchaser_vaultReclaimsBacking() public {
        Candidate memory c = primary();
        _select(c);
        uint256 packId = vault.position(selected).packId;
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vault.sync(new uint256[](0), 0, 0, _expected0); // Journal work is paid even while the purchaser may still act.
        bytes32 expectedRegression1 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.Nothing.selector);
        vault.sync(one, 0, 0, expectedRegression1); // purchaser's window still open
        vm.warp(block.timestamp + FWA.settlementWindow());
        uint256 vBefore = address(vault).balance;
        uint256 kBefore = address(this).balance;
        TestVaultOps.sync(vault, one, 0);
        // B(1 - s) = B x 9,900 / 10,000 > P = 0.06, so the vault takes the backing (D9), less gas pay.
        assertEq(address(vault).balance - vBefore + (address(this).balance - kBefore), B * 9_900 / 10_000);
        assertEq(PACKS.ownerOf(packId), c.purchaser, "pack to the silent purchaser");
        assertEq(TestVaultOps.open(vault).length, COUNT - 1);
    }

    /// @dev The second real candidate: a bid outcome at a different request block and listing index.
    function test_secondCandidate_bidOutcome() public {
        Candidate memory c = second();
        _select(c);
        uint256 pBefore = c.purchaser.balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        assertEq(c.purchaser.balance - pBefore, B * 9_000 / 10_000, "purchaser gets 90% of backing");
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        TestVaultOps.sync(vault, one, 0);
        assertEq(TestVaultOps.idle(vault).length, 1, "pack back in inventory");
        assertEq(TestVaultOps.open(vault).length, COUNT - 1);
    }
}
