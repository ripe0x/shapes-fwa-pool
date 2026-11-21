// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SelectionBase} from "./ForkSelection.t.sol";
import {VaultLib as L} from "../../src/VaultLib.sol";
import {ScanLib} from "../../src/ScanLib.sol";
import {IFWAV2, IShapePacks} from "../../src/interfaces/External.sol";

/// @dev The production book and allocation proof, with allocations applied directly. The proof's
///      FWA reads are real: the head is the listing FWA's real VRF word allocated.
contract AllocationProofHarness {
    using L for L.Book;
    L.Book private book;

    function allocate(uint256 id, uint64 at) external {
        uint256 pack = id + 1e12;
        book.addInventory(pack, 0.06 ether);
        book.list(id, pack, 0.065 ether, 0);
        book.select(id, at);
    }

    function keep(uint256 id) external { book.keep(id); }
    function prune(uint256 n) external returns (uint256) { return book.prune(n); }
    function queue() external view returns (uint256 head, uint256 length) {
        return (book.allocationHead, book.allocationQueue.length);
    }

    function proof(IFWAV2 f, IShapePacks packs) external view returns (uint256 entries, uint256 reads, uint256 used) {
        uint256 g = gasleft();
        (entries, reads) = ScanLib.requireAllocatedCurrent(book, f, packs);
        used = g - gasleft();
    }
}

/// @notice The checkpoint's allocation proof reads at most MAX_ALLOCATION_SCAN queue entries,
///         whatever the allocation history behind an unresolved allocation.
contract ForkAllocationProofTest is SelectionBase {
    receive() external payable {}

    AllocationProofHarness h;

    function _setUpQueue(uint256 resolvedBehind, uint256 unresolvedBehind) internal {
        _select(primary());
        h = new AllocationProofHarness();
        uint64 at = uint64(block.timestamp);
        h.allocate(selected, at); // the unresolved head, Allocated at FWA for real
        for (uint256 i = 1; i <= resolvedBehind; ++i) {
            h.allocate(1e15 + i, at);
            h.keep(1e15 + i); // resolved: a tombstone the head blocks pruning past
        }
        for (uint256 i = 1; i <= unresolvedBehind; ++i) h.allocate(2e15 + i, at);
        assertEq(h.prune(type(uint256).max), 0, "nothing prunes past an unresolved head");
    }

    function test_boundaryReadsTheQueue() public {
        _setUpQueue(L.MAX_ALLOCATION_SCAN - 1, 0);
        vm.cool(address(FWA));
        vm.cool(address(h)); // a checkpoint reads the queue in its own transaction
        (uint256 entries, uint256 reads, uint256 used) = h.proof(FWA, PACKS);
        assertEq(entries, L.MAX_ALLOCATION_SCAN);
        assertEq(reads, 1, "one FWA read: the only Allocated position");
        emit log_named_uint("proof gas, 32 entries, 1 FWA read", used);
        assertLe(used, entries * L.Q_ALLOCATION_ENTRY + reads * L.Q_ALLOCATION_READ, "within its quote");
    }

    /// @dev 2,000 resolved allocations behind one unresolved head: the proof refuses at a cost
    ///      that does not depend on the history; it prices again once the head resolves and prunes.
    function test_longHistoryRefusesAtConstantCost() public {
        _setUpQueue(L.MAX_ALLOCATION_SCAN, 0);
        (bool ok, uint256 small) = _measure();
        assertFalse(ok, "33 entries refuse");
        _setUpQueue(2_000, 0);
        (bool ok2, uint256 large) = _measure();
        assertFalse(ok2, "2,001 entries refuse");
        emit log_named_uint("refusal gas at 33 entries", small);
        emit log_named_uint("refusal gas at 2,001 entries", large);
        assertEq(large, small, "refusal cost is independent of the history");
        vm.expectRevert(L.CatchUpFirst.selector);
        h.proof(FWA, PACKS);
    }

    /// @dev Many unresolved allocations at once: the proof never reads more than the bound.
    function test_manyUnresolvedReadAtMostTheBound() public {
        _setUpQueue(0, L.MAX_ALLOCATION_SCAN);
        vm.expectRevert(L.CatchUpFirst.selector);
        h.proof(FWA, PACKS);
    }

    function _measure() internal returns (bool ok, uint256 used) {
        vm.cool(address(h));
        uint256 g = gasleft();
        (ok,) = address(h).call(abi.encodeCall(AllocationProofHarness.proof, (FWA, PACKS)));
        used = g - gasleft();
    }
}
