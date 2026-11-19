// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReentrancyGuard} from "solady/utils/ReentrancyGuard.sol";
import {
    ReceiptIdentityProbe, ReceiptFWA, ReceiptPacks, ReceiptShapes,
    R_ACTIVE, R_ALLOCATED, R_WITHDRAWN, R_SETTLED
} from "./ReceiptIdentity.t.sol";
import {IncrementalLedger} from "./IncrementalLedger.sol";

interface IncrementalJournal {
    struct Acquisition {
        address purchaser;
        uint256 requestBlock;
        uint256 priceEscrowed;
        uint256 listingId;
        uint8 status;
    }
    function nextSequenceToProcess() external view returns (uint64);
    function requestIdAtSequence(uint64 sequence) external view returns (uint256);
    function acquisitions(uint256 requestId) external view returns (Acquisition memory);
    function pendingFees(uint256 id) external view returns (uint256);
    function isPurchaseBlackout() external view returns (bool);
    function recoverStuckNFT(uint256 id) external;
}

interface RedeemableResearchPacks {
    function redeem(uint256 packId) external;
}

/// @notice Research adapter for the real deployed FWA and shape packs.
/// @dev This proves accounting transitions, not a production share vault.
///      Asset creation uses a fixed test fixture and has no strategy policy.
contract IncrementalFWA is ReceiptIdentityProbe, ReentrancyGuard {
    using IncrementalLedger for IncrementalLedger.Book;

    uint256 public constant MAX_BATCH = 16;
    uint256 public constant ALLOCATED_BOUND_BPS = 1_000;
    address public immutable operator;
    IncrementalJournal public immutable journal;
    uint64 public acquisitionCursor;
    IncrementalLedger.Book internal book;

    error Unauthorized();
    error InvalidListing();
    error InvalidJournal();
    error MissingReceipt();
    error CatchUpFirst();
    error PendingReceipts();
    error InvalidBacking();
    error BadBatch();
    error NotCheckpointWindow();
    error ExpiredAllocation();
    error AllocatedExposure();

    modifier onlyOperator() {
        if (msg.sender != operator) revert Unauthorized();
        _;
    }

    constructor(ReceiptFWA f, ReceiptPacks p, ReceiptShapes s)
        payable
        ReceiptIdentityProbe(f, p, s)
    {
        operator = msg.sender;
        journal = IncrementalJournal(address(f));
        acquisitionCursor = journal.nextSequenceToProcess();
    }

    function createAndList(uint256 backing)
        external override onlyOperator nonReentrant returns (uint256 id)
    {
        uint32[] memory counts = new uint32[](9);
        counts[0] = 3;
        uint256 packId =
            packs.createPack{value: 0.03 ether + 3 * shapes.mintFee()}(new uint256[](0), counts);
        book.addInventory(packId, packs.valueOf(packId));
        id = _list(packId, backing);
    }

    function listIdle(uint256 packId, uint256 backing)
        external onlyOperator nonReentrant returns (uint256 id)
    {
        // A returned position must retire before the pack may leave custody.
        if (book.idleValueOf[packId] == 0 || book.packToListing[packId] != 0) {
            revert IncrementalLedger.MissingInventory();
        }
        id = _list(packId, backing);
    }

    function _list(uint256 packId, uint256 backing) private returns (uint256 id) {
        if (backing == 0 || backing > type(uint128).max || backing % 10_000 != 0
            || idForBacking[backing] != 0) revert InvalidBacking();
        id = fwa.listNFT{value: backing}(address(packs), packId);
        ReceiptFWA.Listing memory l = fwa.listings(id);
        if (l.status != R_ACTIVE || fwa.fwairListing(id)) revert InvalidListing();
        _validate(l, packId, backing);
        idForBacking[backing] = id;
        receipts[id].initialized = true;
        book.list(id, packId, backing, l.feeDebt);
    }

    function adopt(uint256 packId) external onlyOperator nonReentrant {
        if (!_owns(packId)) revert InvalidListing();
        book.addInventory(packId, packs.valueOf(packId));
    }

    function redeemIdle(uint256 packId) external onlyOperator nonReentrant {
        book.redeemInventory(packId);
        RedeemableResearchPacks(address(packs)).redeem(packId);
    }

    function controlledWithdraw(uint256 id) external override onlyOperator nonReentrant {
        IncrementalLedger.Position memory p = book.positions[id];
        if (p.state != IncrementalLedger.State.Active) revert IncrementalLedger.WrongState();
        controlled = true;
        fwa.withdrawListing(id);
        controlled = false;
        // Actual cash reflects a possible early crown exit fee.
        if (!_owns(p.packId)) revert InvalidListing();
        book.returnPack(id, true);
        _release(id, p.backing);
    }

    function controlledHarvest(uint256[] calldata ids) external override onlyOperator nonReentrant {
        if (ids.length > MAX_BATCH) revert BadBatch();
        controlled = true;
        if (ids.length != 0) {
            fwa.claimListingFees(ids);
            for (uint256 i; i < ids.length; ++i) {
                ReceiptFWA.Listing memory l = fwa.listings(ids[i]);
                if (l.status != R_ACTIVE) revert InvalidListing();
                book.updateFeeDebt(ids[i], l.feeDebt);
            }
        }
        if (fwa.feeCredit(address(this)) != 0) fwa.withdrawEarnings();
        controlled = false;
    }

    function reclaimBacking(uint256 id) external override onlyOperator nonReentrant {
        // The authenticated receipt remains pending until its journal entry is applied.
        fwa.depositorReclaimBacking(id);
    }

    function recoverReturn(uint256 id) external nonReentrant {
        IncrementalLedger.Position memory p = book.positions[id];
        if (p.state != IncrementalLedger.State.Owed) revert IncrementalLedger.WrongState();
        journal.recoverStuckNFT(id);
        if (!_owns(p.packId)) revert InvalidListing();
        book.claimReturned(id);
    }

    /// @notice Apply only new acquisitions and supplied changed positions.
    function syncChanges(uint256 maxAcquisitions, uint256[] calldata changedIds, uint256 maxPrune)
        external nonReentrant returns (uint256 processed, uint256 resolved)
    {
        if (maxAcquisitions + changedIds.length > MAX_BATCH || maxPrune > MAX_BATCH) revert BadBatch();
        uint64 cursor = acquisitionCursor;
        uint64 end = journal.nextSequenceToProcess();
        while (cursor < end && processed < maxAcquisitions) {
            uint256 requestId = journal.requestIdAtSequence(cursor);
            if (requestId == 0) revert InvalidJournal();
            IncrementalJournal.Acquisition memory a = journal.acquisitions(requestId);
            if (a.status == 2) {
                if (a.listingId == 0) revert InvalidJournal();
                IncrementalLedger.Position memory p = book.positions[a.listingId];
                if (p.value != 0) {
                    if (p.state != IncrementalLedger.State.Active) revert InvalidJournal();
                    ReceiptFWA.Listing memory l = fwa.listings(a.listingId);
                    _validate(l, p.packId, p.backing);
                    if (l.status != R_ALLOCATED && l.status != R_SETTLED) revert InvalidJournal();
                    book.select(a.listingId, l.allocatedAt);
                }
            } else if (a.status != 3 && a.status != 4) {
                revert InvalidJournal();
            }
            ++cursor;
            ++processed;
        }
        acquisitionCursor = cursor;
        for (uint256 i; i < changedIds.length; ++i) {
            if (_syncTerminal(changedIds[i])) ++resolved;
        }
        book.prune(maxPrune);
    }

    function _syncTerminal(uint256 id) private returns (bool) {
        IncrementalLedger.Position memory p = book.positions[id];
        if (p.state == IncrementalLedger.State.None || p.state == IncrementalLedger.State.Owed) return false;
        ReceiptFWA.Listing memory l = fwa.listings(id);
        _validate(l, p.packId, p.backing);
        if (l.status == R_ACTIVE || l.status == R_ALLOCATED) return false;

        uint8 kind = receipts[id].kind;
        if (l.status == R_SETTLED) {
            // Preserve completed prefix work when this ID's selection lies ahead.
            if (p.state == IncrementalLedger.State.Active) return false;
            if (p.state != IncrementalLedger.State.Allocated) revert InvalidListing();
            if (kind == 1) {
                book.keep(id);
                _release(id, p.backing);
                // A kept pack can already be burned, extended, or gifted back.
                if (_owns(p.packId)) book.addInventory(p.packId, packs.valueOf(p.packId));
                return true;
            }
            if (kind != 0) revert MissingReceipt();
        } else if (l.status == R_WITHDRAWN) {
            if (p.state != IncrementalLedger.State.Active || kind != 2) revert MissingReceipt();
        } else {
            revert InvalidListing();
        }

        bool owned = _owns(p.packId);
        if (!owned && fwa.stuckNFTRecipient(id) != address(this)) revert MissingReceipt();
        book.returnPack(id, owned);
        _release(id, p.backing);
        return true;
    }

    function _release(uint256 id, uint256 backing) private {
        if (idForBacking[backing] != id) revert InvalidListing();
        // A live lookup must never point at cleared storage or a burned/relisted old pack.
        delete idForBacking[backing];
        if (receipts[id].kind != 0) --pendingPlusOne;
        delete receipts[id];
    }

    function _validate(ReceiptFWA.Listing memory l, uint256 packId, uint256 backing) private view {
        if (l.depositor != address(this) || l.collection != address(packs)
            || l.tokenId != packId || l.value != backing) revert InvalidListing();
    }

    function _owns(uint256 packId) private view returns (bool) {
        // Terminal optional adoption may inspect a legitimately burned kept pack.
        // The synchronous receipt handler deliberately has a strict ownership read.
        try packs.ownerOf(packId) returns (address owner) { return owner == address(this); }
        catch { return false; }
    }

    function accountedNav(uint256 witnessId) public view returns (uint256) {
        if (acquisitionCursor != journal.nextSequenceToProcess()) revert CatchUpFirst();
        if (pendingPlusOne != 1) revert PendingReceipts();
        uint256 pending;
        if (book.activeCount != 0) {
            IncrementalLedger.Position memory p = book.positions[witnessId];
            ReceiptFWA.Listing memory l = fwa.listings(witnessId);
            if (p.state != IncrementalLedger.State.Active || l.status != R_ACTIVE
                || p.feeDebt != l.feeDebt) revert IncrementalLedger.BadWitness();
            _validate(l, p.packId, p.backing);
            pending = journal.pendingFees(witnessId);
        }
        return book.nav(address(this).balance, fwa.feeCredit(address(this)), witnessId, pending);
    }

    function checkpointNav(uint256 witnessId) external view returns (uint256 nav) {
        if (!journal.isPurchaseBlackout() || fwa.unsettledAcquisitionCount() != 0) revert NotCheckpointWindow();
        nav = accountedNav(witnessId);
        (uint256 oldest, uint64 at) = book.oldestAllocation();
        if (oldest != 0 && block.timestamp >= uint256(at) + fwa.settlementWindow()) revert ExpiredAllocation();
        if (book.allocatedValue * 10_000 > nav * ALLOCATED_BOUND_BPS) revert AllocatedExposure();
    }

    function position(uint256 id) external view returns (IncrementalLedger.Position memory) { return book.positions[id]; }
    function idleValueOf(uint256 packId) external view returns (uint256) { return book.idleValueOf[packId]; }
    function packToListing(uint256 packId) external view returns (uint256) { return book.packToListing[packId]; }
    function oldestAllocation() external view returns (uint256, uint64) { return book.oldestAllocation(); }
    function totals() external view returns (
        uint256 tracked, uint256 idle, uint256 backing, uint256 active, uint256 debt, uint256 allocated
    ) {
        return (book.trackedValue, book.idleValue, book.activeBacking, book.activeCount, book.feeDebtSum, book.allocatedValue);
    }
}
