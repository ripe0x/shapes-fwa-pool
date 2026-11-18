// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {IncrementalForkFixture} from "./IncrementalFWAFork.t.sol";
import {IncrementalFWA} from "./IncrementalFWA.sol";
import {IncrementalLedger} from "./IncrementalLedger.sol";

interface AdversarialResearchPacks {
    function redeem(uint256 packId) external;
    function addToPack(uint256 packId, uint256[] calldata shapeIds, uint32[] calldata mintCounts)
        external payable;
    function transferFrom(address from, address to, uint256 tokenId) external;
}

/// @notice Independent edge cases against the deployed FWA and shape packs.
/// @dev All selections replay the recorded request and fulfillment fixture.
///      No external contract, oracle, or VRF is replaced or mocked.
contract IncrementalAdversarialTest is IncrementalForkFixture {
    function test_adversarialBuyerBurnsKeptPackBeforeReconciliation() public {
        _selected(100);
        uint256 pack = FWA.listings(selected).tokenId;
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        vm.prank(PURCHASER);
        AdversarialResearchPacks(address(PACKS)).redeem(pack);
        assertEq(_owner(pack), address(0), "purchaser burned the kept pack");
        assertEq(ledger.pendingCount(), 1);

        // The receipt survives both custody loss and a subsequent burned token.
        _catchUp();
        vm.expectRevert(IncrementalFWA.PendingReceipts.selector);
        ledger.accountedNav(0);
        _catchUp(_one(selected));
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.idForBacking(selectedBacking), 0);
        assertEq(ledger.packToListing(pack), 0);
        (uint256 tracked,,,,, uint256 allocated) = ledger.totals();
        assertEq(tracked, 0);
        assertEq(allocated, 0);
        _assertBook();
    }

    function test_adversarialBuyerExtendsKeptPackAndGiftsItBack() public {
        _selected(100);
        uint256 pack = FWA.listings(selected).tokenId;
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);

        uint32[] memory counts = new uint32[](9);
        counts[0] = 1;
        uint256 cost = 0.01 ether + SHAPES.mintFee();
        vm.deal(PURCHASER, PURCHASER.balance + cost);
        vm.startPrank(PURCHASER);
        AdversarialResearchPacks(address(PACKS)).addToPack{value: cost}(pack, new uint256[](0), counts);
        AdversarialResearchPacks(address(PACKS)).transferFrom(PURCHASER, address(ledger), pack);
        vm.stopPrank();
        assertEq(PACKS.valueOf(pack), 0.04 ether, "gift has more backing than the old position");

        _catchUp(_one(selected));
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.idForBacking(selectedBacking), 0);
        assertEq(ledger.idleValueOf(pack), 0.04 ether);
        (uint256 tracked, uint256 idle,,,, uint256 allocated) = ledger.totals();
        assertEq(tracked, 0.04 ether);
        assertEq(idle, 0.04 ether);
        assertEq(allocated, 0);
        _assertBook();

        // The old identifier is already retired before the gifted pack burns.
        ledger.redeemIdle(pack);
        assertEq(_owner(pack), address(0));
        _assertBook();
    }

    function test_adversarialLaterFeeChangeDoesNotRedecodeRecordedReceipt() public {
        _selected(100);
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        (uint128 received, uint16 usedFee, uint8 kind, bool initialized) = ledger.receipts(selected);
        assertEq(received, selectedBacking * 9900 / 10_000);
        assertEq(usedFee, 100);
        assertEq(kind, 1);
        assertTrue(initialized);

        // The real historical request leaves other queued acquisitions. FWA
        // forbids fee edits until those resolve; expire them through its public
        // processor while keeping this receipt deliberately unreconciled.
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        FWA.processAcquisitions(100);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        assertEq(ledger.pendingCount(), 1);
        vm.prank(FWA.owner());
        FWA.setUint(FEE_KEY, 500);
        assertEq(FWA.ownerSettlementFeeBps(), 500);
        _catchUp(_one(selected));
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.idForBacking(selectedBacking), 0);
        _assertBook();
    }

    function test_adversarialRetiredBurnedBidTagCannotPoisonLaterKickAndCanBeReused() public {
        (uint256 kicked, uint256 backing) = _prepareKickWithSettledBidDecoy();
        _register(selected);
        _register(kicked);
        uint256 returnedPack = FWA.listings(selected).tokenId;
        uint256 kickedPack = FWA.listings(kicked).tokenId;
        assertEq(ledger.idForBacking(selectedBacking), selected);

        // Actual custody alone cannot authorize movement before journal sync.
        vm.expectRevert(IncrementalLedger.MissingInventory.selector);
        ledger.redeemIdle(returnedPack);
        vm.expectRevert(IncrementalLedger.MissingInventory.selector);
        ledger.listIdle(returnedPack, selectedBacking);

        _catchUp(_one(selected));
        assertEq(ledger.idForBacking(selectedBacking), 0);
        ledger.redeemIdle(returnedPack);
        assertEq(_owner(returnedPack), address(0));
        _assertBook();

        // This kick's amount decodes to the burned old bid's backing. It must
        // skip that retired lookup, avoiding an ownerOf revert inside receive.
        FWA.kickListing(kicked);
        assertEq(ledger.pendingCount(), 1);
        (uint128 received,, uint8 kind,) = ledger.receipts(kicked);
        assertEq(received, backing);
        assertEq(kind, 2);
        _catchUp(_one(kicked));
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.idForBacking(backing), 0);
        _assertBook();

        // Restore the fixture's ordinary oracle exemption before a new listing.
        vm.prank(FWA.owner());
        FWA.setOracleExemptCollection(address(PACKS), true);
        uint256 fresh = ledger.listIdle(kickedPack, selectedBacking);
        _register(fresh);
        assertTrue(fresh != selected && fresh != kicked);
        assertEq(ledger.idForBacking(selectedBacking), fresh);
        assertEq(ledger.packToListing(kickedPack), fresh);
        _assertBook();
    }
}
