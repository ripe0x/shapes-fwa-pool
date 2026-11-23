// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {VaultLib} from "./VaultLib.sol";
import {IFWAV2, IFWAView, IShapePacks, LISTING_ACTIVE, LISTING_ALLOCATED, LISTING_SETTLED} from "./interfaces/External.sol";

/// @notice The read half of VaultLib's scan proof, a separate library only for EIP-170 size.
library ScanLib {
    /// @dev Every position the book holds Allocated must still be Allocated at FWA. A settlement
    ///      pays the account in its own transaction; if receive() could not record the receipt
    ///      (forced ETH), the cash would otherwise count beside the position until it is synced.
    ///      Reads at most MAX_ALLOCATION_SCAN queue entries from the head (else CatchUpFirst: sync
    ///      and prune first), so pricing cost never grows with allocation history.
    ///      A kick refunds B the same way, so while FWA can kick (the ShapePacks oracle exemption
    ///      lifted) and the account holds at most MAX_ALLOCATION_SCAN open entries, every booked
    ///      Active listing must also still be Active at FWA. Above that the check is skipped, not
    ///      refused, so pricing never stalls on FWA's exemption: an unrecorded kick refund needs
    ///      receive() to exceed FWA's 100,000 gas stipend (it uses 35,148), and with the exemption in
    ///      place no listing can be kicked.
    function requireAllocatedCurrent(VaultLib.Book storage b, IFWAV2 f, IShapePacks packs)
        external view returns (uint256 entries, uint256 reads)
    {
        uint256 n = b.open.length;
        if (b.activeCount != 0 && n <= VaultLib.MAX_ALLOCATION_SCAN && !f.oracleExemptCollections(address(packs))) {
            entries = n;
            for (uint256 i; i < n; ++i) {
                uint256 id = b.open[i];
                if (b.positions[id].state != VaultLib.ACTIVE) continue;
                ++reads;
                if (IFWAView(address(f)).listings(id).status != LISTING_ACTIVE) revert VaultLib.PendingReceipts();
            }
        }
        if (b.allocatedValue == 0) return (entries, reads);
        uint256 head = b.allocationHead;
        uint256 queued = b.allocationQueue.length - head;
        if (queued > VaultLib.MAX_ALLOCATION_SCAN) revert VaultLib.CatchUpFirst();
        entries += queued;
        for (uint256 i = head; i < head + queued; ++i) {
            uint256 id = b.allocationQueue[i];
            if (b.positions[id].state != VaultLib.ALLOCATED) continue;
            ++reads;
            uint8 status = IFWAView(address(f)).listings(id).status;
            // A bid pays nothing and returns the pack: the booked position already counts it.
            if (status == LISTING_ALLOCATED || (status == LISTING_SETTLED
                && (VaultLib.owns(packs, b.positions[id].packId) || f.stuckNFTRecipient(id) == address(this)))) continue;
            revert VaultLib.PendingReceipts();
        }
    }

    function rebase(VaultLib.Book storage b, IFWAV2 f) external returns (bool, uint256 scanned, uint256 own) {
        uint64 end = f.nextSequenceToProcess();
        uint256 backlog = end - b.acquisitionCursor;
        // Taken only when it costs no more than the next journal batch: a small vault's upkeep then
        // scales with its own positions, not with FWA's global activity, and the scan stays within
        // the journal batch's gas envelope.
        uint256 batch = backlog < VaultLib.MAX_JOURNAL ? backlog : VaultLib.MAX_JOURNAL;
        if (backlog == 0 || b.open.length * VaultLib.Q_SCAN > batch * VaultLib.Q_JOURNAL) return (false, 0, 0);
        uint256[] memory found = new uint256[](VaultLib.MAX_SELECTIONS);
        for (uint256 i; i < b.open.length; ++i) {
            uint256 id = b.open[i];
            if (b.positions[id].state != VaultLib.ACTIVE) continue;
            ++scanned;
            IFWAView.Listing memory l = IFWAView(address(f)).listings(id);
            if (l.status != LISTING_ALLOCATED && l.status != LISTING_SETTLED) continue;
            if (own == found.length) return (false, 0, 0);
            uint256 x = uint256(l.allocatedAt) << 192 | id;
            uint256 j = own++;
            for (; j != 0 && found[j - 1] > x; --j) found[j] = found[j - 1];
            found[j] = x;
        }
        if (own != 0 && found[0] >> 192 < b.lastAllocatedAt) return (false, 0, 0);
        for (uint256 i; i < own; ++i) VaultLib.select(b, uint192(found[i]), uint64(found[i] >> 192));
        b.acquisitionCursor = end;
        emit VaultLib.JournalProgress(end, 0, own);
        return (true, scanned, own);
    }
}
