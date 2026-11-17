// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {
    IShapes, IShapePacks, IFWAV2, LISTING_ACTIVE, LISTING_ALLOCATED
} from "../../src/interfaces/External.sol";
import {IOwnable, IOracleAdmin} from "./ForkBase.sol";

interface IFwaSettle {
    function acceptDepositorBid(uint256 listingId) external;
    function keepNFT(uint256 listingId) external;
    function setCollectionsWhitelisted(address[] calldata collections, bool allowed) external;
    function topListingId() external view returns (uint256);
    function processAcquisitions(uint256 maxCount) external returns (uint256 processed);
}

/// @notice Outcome paths driven by FWA's real randomness. sim/find_selection.py found historical
///         requests whose real VRF word selects one of 30 vault listings posted just before the
///         request. Each test forks right before that request, posts the listings, then replays
///         the real request and fulfillment transactions. Only the purchaser's choice is ours to
///         drive, through the purchaser's own call.
abstract contract SelectionBase is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint256 constant COUNT = 30;
    uint256 constant B = 0.0363 ether;

    struct Candidate {
        bytes32 requestTx;
        uint256 requestBlock;
        uint256 fulfillBlock;
        uint256 fulfillTimestamp;
        uint256 index; // which of our 30 listings the real word selects
        uint256 slot;
        address purchaser;
        bool needsAdmission; // before FWA admitted packs and set their quote
    }

    // Block 26,417,086: after packs were admitted (26,415,582) and quoted (26,415,718).
    function late() internal pure returns (Candidate memory) {
        return Candidate(
            0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f,
            26_417_086,
            26_417_091,
            1_794_705_887,
            28,
            1631,
            0x6A51eEe3a2C2d33921844965738aE99b81dbFf95,
            false
        );
    }

    // Block 26,405,703: before admission; FWA's owner and the oracle owner make their real calls first.
    function early() internal pure returns (Candidate memory) {
        return Candidate(
            0x8e3293810d4e650e8ea6c2f0080ca85767ac6c783f5e93796947ee7aeab5e56f,
            26_405_703,
            26_405_708,
            1_794_568_871,
            19,
            7487,
            0x184b487D36Aea8AA5990569C326c269DE246179A,
            true
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
    uint256 selectPay; // keeper pay to this contract for the restock and list in _select

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    function _select(Candidate memory c) internal {
        vm.createSelectFork("mainnet", c.requestTx);
        if (c.needsAdmission) {
            address[] memory cols = new address[](1);
            cols[0] = address(PACKS);
            vm.prank(IOwnable(address(FWA)).owner());
            IFwaSettle(address(FWA)).setCollectionsWhitelisted(cols, true);
            address oracle = FWA.floorOracle();
            vm.prank(IOwnable(oracle).owner());
            IOracleAdmin(oracle).setFloor(address(PACKS), 0.033 ether);
        }
        assertEq(FWA.unsettledAcquisitionCount(), 0, "queue empty before the request");

        VaultLib.Params memory p;
        p.minEdgeBps = 100;
        p.payMarkupBps = 1_000;
        p.maxTip = 0.05 gwei;
        p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200;
        p.packUnitsMask = uint64(1) << 3;
        p.gasCeiling = 50 gwei;
        p.essentialCeiling = 50 gwei;
        p.maxPositions = 150;
        p.tvlCap = 100 ether;
        p.routineCap = 0.3 ether; // bytecode maxima: these suites test mechanics, not budgets
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;
        vm.deal(address(this), 10 ether);
        vault = new PackVault{value: 3 ether}(
            FWA, SHAPES, PACKS, makeAddr("sel-admin"), p, new KeeperPolicyV1()
        );
        deployBalance = address(vault).balance;
        uint256 b0 = address(this).balance;
        vault.restock(COUNT, 3, 0);
        vault.list(COUNT, 0);
        selectPay = address(this).balance - b0;
        uint256[] memory ids = vault.openListings();
        selected = ids[c.index];
        (,,,,,,,, uint256 slot,, uint8 status) = FWA.listings(selected);
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
        string memory fx = vm.readFile("test/fixtures/selection.json");
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
        // Every other vault listing accrued the same share, still pending.
        assertApproxEqAbs(FWA.pendingFees(ids[(c.index + 1) % COUNT]), expectedShare, 2);
    }

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

}

contract ForkSelectionTest is SelectionBase {
    receive() external payable {} // this contract calls paid work directly

    function test_bidOutcome_packReturnsBackingSpent() public {
        Candidate memory c = late();
        _select(c);
        uint256 pBefore = c.purchaser.balance;
        uint256 vBefore = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        assertEq(c.purchaser.balance - pBefore, B * 9_000 / 10_000, "purchaser gets 90% of backing");
        assertEq(address(vault).balance, vBefore, "no ETH back to the vault on a bid outcome");
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        uint256 keeperBefore = address(this).balance;
        vault.sync(one, 0);
        uint256 syncPay = address(this).balance - keeperBefore;
        assertGt(syncPay, 0, "resolving a position is paid");
        assertEq(vBefore - address(vault).balance, syncPay, "sync moves no ETH but its gas pay");
        assertEq(vault.idlePacks().length, 1, "pack back in inventory");
        assertEq(vault.openListings().length, COUNT - 1);
        keeperBefore = address(this).balance;
        vault.harvest(new uint256[](0), 0);
        // The whole credited share reaches the vault. Its gas would cost more than 25% of it, so
        // the harvest is unpaid: a keeper earns nothing for a dust harvest.
        assertEq(address(this).balance, keeperBefore, "dust harvest unpaid");
        assertApproxEqAbs(address(vault).balance + syncPay - vBefore, expectedShare, 2);
    }

    function test_keepOutcome_backingBackLessFee() public {
        Candidate memory c = late();
        _select(c);
        (,,, uint256 packId,,,,,,,) = FWA.listings(selected);
        uint256 vBefore = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        assertEq(address(vault).balance - vBefore, B * 9_900 / 10_000, "backing less the 1% settlement fee");
        assertEq(PACKS.ownerOf(packId), c.purchaser);
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        vault.sync(one, 0);
        assertEq(vault.idlePacks().length, 0);
        assertEq(vault.openListings().length, COUNT - 1);
    }

    function test_silentPurchaser_vaultReclaimsBacking() public {
        Candidate memory c = late();
        _select(c);
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        vm.expectRevert(PackVault.Nothing.selector);
        vault.sync(one, 0); // purchaser's window still open
        vm.warp(block.timestamp + FWA.settlementWindow());
        uint256 vBefore = address(vault).balance;
        uint256 kBefore = address(this).balance;
        vault.sync(one, 0);
        // B (1 - s) = 0.035937 > P = 0.03, so the vault takes the backing (D9), less gas pay.
        assertEq(address(vault).balance - vBefore + (address(this).balance - kBefore), B * 9_900 / 10_000);
        assertEq(vault.openListings().length, COUNT - 1);
    }

    function test_earlyCandidate_afterRealAdmissionCalls() public {
        Candidate memory c = early();
        _select(c);
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        vault.sync(one, 0);
        assertEq(vault.idlePacks().length, 1);
    }
}
