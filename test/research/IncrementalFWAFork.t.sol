// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {
    ReceiptIdentityTest, ReceiptFixtureFiller, ReceiptFWA,
    R_ACTIVE, R_ALLOCATED
} from "./ReceiptIdentity.t.sol";
import {IncrementalFWA, IncrementalJournal} from "./IncrementalFWA.sol";
import {IncrementalLedger} from "./IncrementalLedger.sol";

/// @dev Reference enumerates actual FWA records and unique pack ownership,
///      independently of the incremental kernel's states.
abstract contract IncrementalForkFixture is ReceiptIdentityTest {
    IncrementalFWA internal ledger;
    uint256[] internal knownListings;
    uint256[] internal knownPacks;
    mapping(uint256 => uint256) private seenListing;
    mapping(uint256 => uint256) private seenPack;
    uint256 private registryVersion;

    function _deploy() internal override {
        vm.deal(address(this), 20 ether);
        ledger = new IncrementalFWA{value: 10 ether}(FWA, PACKS, SHAPES);
        probe = ledger;
        delete knownListings;
        delete knownPacks;
        ++registryVersion;
    }

    function _register(uint256 id) internal {
        ReceiptFWA.Listing memory l = FWA.listings(id);
        assertEq(l.depositor, address(ledger));
        if (seenListing[id] != registryVersion) {
            seenListing[id] = registryVersion;
            knownListings.push(id);
        }
        if (seenPack[l.tokenId] != registryVersion) {
            seenPack[l.tokenId] = registryVersion;
            knownPacks.push(l.tokenId);
        }
    }

    function _listed(uint256 backing) internal returns (uint256 id) {
        id = ledger.createAndList(backing);
        _register(id);
    }

    function _selected(uint256 fee) internal {
        _select(fee);
        _register(selected);
    }

    function _one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function _catchUp() internal { _catchUp(new uint256[](0)); }

    function _catchUp(uint256[] memory ids) internal {
        IncrementalJournal j = IncrementalJournal(address(FWA));
        while (ledger.acquisitionCursor() < j.nextSequenceToProcess()) {
            ledger.syncChanges(16, new uint256[](0), 16);
        }
        ledger.syncChanges(0, ids, 16);
    }

    function _owner(uint256 packId) internal view returns (address) {
        try PACKS.ownerOf(packId) returns (address owner) { return owner; }
        catch { return address(0); }
    }

    function _witness() internal view returns (uint256 id) {
        uint256 debt = type(uint256).max;
        for (uint256 i; i < knownListings.length; ++i) {
            ReceiptFWA.Listing memory l = FWA.listings(knownListings[i]);
            if (l.status == R_ACTIVE && l.feeDebt <= debt) {
                id = knownListings[i];
                debt = l.feeDebt;
            }
        }
    }

    function _fullReference() internal view returns (uint256 nav) {
        nav = address(ledger).balance + FWA.feeCredit(address(ledger));
        for (uint256 i; i < knownPacks.length; ++i) {
            if (_owner(knownPacks[i]) == address(ledger)) nav += PACKS.valueOf(knownPacks[i]);
        }
        uint256 fee = FWA.ownerSettlementFeeBps();
        for (uint256 i; i < knownListings.length; ++i) {
            uint256 id = knownListings[i];
            ReceiptFWA.Listing memory l = FWA.listings(id);
            if (l.status == R_ACTIVE) {
                nav += l.value + PACKS.valueOf(l.tokenId) + IncrementalJournal(address(FWA)).pendingFees(id);
            } else if (l.status == R_ALLOCATED) {
                uint256 packValue = PACKS.valueOf(l.tokenId);
                uint256 netBacking = l.value - l.value * fee / 10_000;
                nav += packValue < netBacking ? packValue : netBacking;
            } else if (FWA.stuckNFTRecipient(id) == address(ledger)) {
                nav += PACKS.valueOf(l.tokenId);
            }
        }
    }

    function _assertBook() internal view {
        assertEq(ledger.accountedNav(_witness()), _fullReference(), "incremental NAV equals independent real FWA scan");
    }

    function _blackout() internal {
        uint256 next = block.timestamp - block.timestamp % 12 hours + 11 hours + 46 minutes;
        if (next <= block.timestamp) next += 12 hours;
        vm.warp(next);
    }
}

/// @dev Also inherits the twelve receipt tests against this exact adapter.
contract IncrementalFWAForkTest is IncrementalForkFixture {
    function test_receiptBeforeJournalCannotPriceOrRetireEarly() public {
        _selected(100);
        uint256 pack = FWA.listings(selected).tokenId;
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        assertEq(ledger.pendingCount(), 1);
        vm.expectRevert(IncrementalFWA.CatchUpFirst.selector);
        ledger.accountedNav(0);
        vm.expectRevert(IncrementalLedger.MissingInventory.selector);
        ledger.redeemIdle(pack);
        vm.expectRevert(IncrementalLedger.MissingInventory.selector);
        ledger.listIdle(pack, selectedBacking);
        (uint256 processed, uint256 resolved) = ledger.syncChanges(0, _one(selected), 16);
        assertEq(processed, 0);
        assertEq(resolved, 0);
        assertEq(ledger.pendingCount(), 1);
        _catchUp(_one(selected));
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.idForBacking(selectedBacking), 0);
        _assertBook();
        uint256 before = ledger.accountedNav(0);
        (processed, resolved) = ledger.syncChanges(15, _one(selected), 16);
        assertEq(processed, 0);
        assertEq(resolved, 0);
        assertEq(ledger.accountedNav(0), before);
    }

    function test_journalBeforeReceiptAndOmittedReceiptBlocksPricing() public {
        _selected(100);
        _catchUp();
        assertEq(uint256(ledger.position(selected).state), uint256(IncrementalLedger.State.Allocated));
        _assertBook();
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        vm.expectRevert(IncrementalFWA.PendingReceipts.selector);
        ledger.accountedNav(0);
        ledger.syncChanges(0, new uint256[](0), 16);
        assertEq(ledger.pendingCount(), 1);
        _catchUp(_one(selected));
        _assertBook();
    }

    function test_bidReturnNeedsNoValueRefreshThenCanRedeemAndReuseBacking() public {
        _selected(100);
        _catchUp();
        uint256 pack = FWA.listings(selected).tokenId;
        vm.prank(PURCHASER);
        FWA.acceptDepositorBid(selected);
        assertEq(ledger.pendingCount(), 0);
        _assertBook();
        vm.expectRevert(IncrementalLedger.MissingInventory.selector);
        ledger.redeemIdle(pack);
        _catchUp(_one(selected));
        assertEq(ledger.idForBacking(selectedBacking), 0);
        assertEq(ledger.idleValueOf(pack), 0.03 ether);
        _assertBook();
        ledger.redeemIdle(pack);
        _assertBook();
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        FWA.processAcquisitions(100);
        _catchUp();
        uint256 fresh = _listed(selectedBacking);
        assertTrue(fresh != selected);
        assertEq(ledger.idForBacking(selectedBacking), fresh);
        _assertBook();
    }

    function test_controlledWithdrawalAndSamePackRelistKeepExactValue() public {
        _quiet();
        uint256 first = _listed(0.032 ether);
        uint256 pack = FWA.listings(first).tokenId;
        _assertBook();
        ledger.controlledWithdraw(first);
        assertEq(ledger.idForBacking(0.032 ether), 0);
        _assertBook();
        uint256 second = ledger.listIdle(pack, 0.032 ether);
        _register(second);
        assertTrue(second != first);
        assertEq(ledger.idForBacking(0.032 ether), second);
        _assertBook();
        ledger.controlledWithdraw(second);
        ledger.redeemIdle(pack);
        _assertBook();
    }

    function test_directKickUpdatesLedgerWithoutAnAcquisitionEntry() public {
        (uint256 kicked, uint256 backing) = _prepareKickWithSettledBidDecoy();
        _register(selected);
        _register(kicked);
        _catchUp();
        uint64 cursor = ledger.acquisitionCursor();
        FWA.kickListing(kicked);
        assertEq(ledger.acquisitionCursor(), cursor);
        vm.expectRevert(IncrementalFWA.PendingReceipts.selector);
        ledger.accountedNav(0);
        _catchUp(_one(kicked));
        assertEq(ledger.idForBacking(backing), 0);
        _assertBook();
        _catchUp(_one(selected));
        _assertBook();
    }

    function test_checkpointWindowAndExpiredAllocationRemainEnforced() public {
        _selected(100);
        _catchUp();
        vm.expectRevert(IncrementalFWA.NotCheckpointWindow.selector);
        ledger.checkpointNav(0);
        vm.warp(block.timestamp + FWA.settlementWindow() + 25 hours);
        vm.roll(block.number + 7_500);
        FWA.processAcquisitions(100);
        _catchUp();
        _blackout();
        vm.expectRevert(IncrementalFWA.ExpiredAllocation.selector);
        ledger.checkpointNav(0);
        ledger.reclaimBacking(selected);
        _catchUp(_one(selected));
        assertEq(ledger.checkpointNav(0), _fullReference());
    }

    function test_cursorProgressSurvivesNewFWAActivityBetweenBatches() public {
        _selected(100);
        uint64 start = ledger.acquisitionCursor();
        (uint256 processed,) = ledger.syncChanges(1, new uint256[](0), 0);
        assertEq(processed, 1);
        assertEq(ledger.acquisitionCursor(), start + 1);
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        assertEq(ledger.pendingCount(), 1);

        // The recorded request bought two acquisitions. Its remaining request
        // expires through FWA after this first accounting batch has completed.
        assertGt(FWA.unsettledAcquisitionCount(), 0);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        FWA.processAcquisitions(100);
        assertGt(IncrementalJournal(address(FWA)).nextSequenceToProcess(), start + 1);
        (processed,) = ledger.syncChanges(0, _one(selected), 1);
        assertEq(processed, 0);
        assertEq(ledger.pendingCount(), 0);
        assertEq(ledger.acquisitionCursor(), start + 1, "completed prefix is retained");
        vm.expectRevert(IncrementalFWA.CatchUpFirst.selector);
        ledger.accountedNav(0);
        (processed,) = ledger.syncChanges(1, new uint256[](0), 1);
        assertEq(processed, 1);
        assertEq(ledger.acquisitionCursor(), start + 2);
        _assertBook();
    }

    function test_checkpointReadsNoPortfolioArray() public {
        _quiet();
        _listed(0.032 ether);
        _blackout();
        uint256 witness = _witness();
        _cold();
        uint256 start = gasleft();
        uint256 value = ledger.checkpointNav(witness);
        uint256 used = start - gasleft();
        assertEq(value, _fullReference());
        emit log_named_uint("real FWA cold checkpoint valuation gas", used);
        assertLt(used, 300_000);
    }

    function test_realFeeIndexAndHarvestMatchFullReference() public {
        vm.createSelectFork("mainnet", REQUEST_TX);
        _deploy();
        uint256 first = _listed(0.0363 ether);
        uint256 second = _listed(0.0362 ether);
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(FWA, PACKS, SHAPES);
        for (uint256 i; i < 28; ++i) filler.createAndList(0.0363 ether);
        _assertBook();
        string memory fixture = vm.readFile("test/fixtures/selection.json");
        string memory key = ".26417086";
        _replay(fixture, key, "req");
        vm.roll(26_417_091);
        vm.warp(1_794_705_887);
        vm.setBlockhash(26_417_086, vm.parseJsonBytes32(fixture, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fixture, string.concat(key, ".fulBaseFee")));
        _replay(fixture, key, "ful");
        assertEq(FWA.listings(first).status, R_ACTIVE, "first fee witness active");
        assertEq(FWA.listings(second).status, R_ACTIVE, "second fee witness active");
        _catchUp();
        _assertBook();
        uint256 before = _fullReference();
        ledger.controlledHarvest(_one(first));
        _assertBook();
        assertEq(_fullReference(), before, "harvesting exchanges earned fees for cash exactly");
        vm.expectRevert(IncrementalLedger.BadWitness.selector);
        ledger.accountedNav(first);
        _assertBook();
        ledger.controlledHarvest(_one(second));
        _assertBook();
        assertEq(_fullReference(), before);
    }
}
