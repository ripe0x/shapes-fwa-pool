// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {VaultLib} from "./VaultLib.sol";
import {IFWAV2, IFWAView, LISTING_ALLOCATED, LISTING_SETTLED} from "./interfaces/External.sol";

/// @notice The read half of VaultLib's scan proof, a separate library only for EIP-170 size.
library ScanLib {
    /// @dev Reads the FWA listing of every open position the book holds Active and selects, in
    ///      allocation-time order (packed `allocatedAt << 192 | id`), each one FWA allocated; then
    ///      moves the cursor to FWA's completed prefix `end`. FWA allocates a listing only while advancing
    ///      `nextSequenceToProcess`, so no completed entry before `end` keeps an unapplied own
    ///      selection. Position IDs exist only for listings VaultLib.admit validated, and FWA never
    ///      changes a listing's identity (so the journal's `_validate` is not repeated here; `_syncTerminal`
    ///      re-validates before any backing moves). With more than MAX_SELECTIONS found, or an order the
    ///      allocation queue cannot take, it changes nothing and returns false: the caller walks the
    ///      journal instead. `scanned` counts the listings read by a completed scan.
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
