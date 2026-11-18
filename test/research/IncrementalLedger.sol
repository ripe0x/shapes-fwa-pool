// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Research accounting kernel. Its caller authenticates every transition
///         against FWA and the pack contract before changing this book.
/// @dev No external calls. Valuation does not enumerate positions or inventory.
library IncrementalLedger {
    enum State {
        None,
        Active,
        Allocated,
        Owed
    }

    struct Position {
        uint256 packId;
        uint256 value;
        uint256 backing;
        uint256 feeDebt;
        uint64 allocatedAt;
        State state;
    }

    struct Book {
        mapping(uint256 listingId => Position) positions;
        mapping(uint256 packId => uint256 value) idleValueOf;
        mapping(uint256 packId => uint256 listingId) packToListing;
        uint256 trackedValue;
        uint256 idleValue;
        uint256 activeBacking;
        uint256 activeCount;
        uint256 feeDebtSum;
        mapping(uint256 debt => uint256 count) countByDebt;
        uint256 allocatedValue;
        uint256[] allocationQueue;
        uint256 allocationHead;
        uint64 lastAllocatedAt;
    }

    error Duplicate();
    error MissingInventory();
    error WrongState();
    error InsufficientBacking();
    error BadWitness();
    error NeedsPrune();
    error OutOfOrder();

    /// @notice Register newly created or explicitly adopted pack backing once.
    function addInventory(Book storage b, uint256 packId, uint256 value) internal {
        if (value == 0 || b.idleValueOf[packId] != 0 || b.packToListing[packId] != 0) revert Duplicate();
        b.idleValueOf[packId] = value;
        b.trackedValue += value;
        b.idleValue += value;
    }

    /// @notice Move registered inventory into an authenticated Active listing.
    /// @dev Backing must cover P even at FWA's maximum ordinary keep fee of 5%.
    ///      ceil(P * 10000 / 9500) = P + floor(P / 19) + (P % 19 != 0).
    function list(Book storage b, uint256 id, uint256 packId, uint256 backing, uint256 debt) internal {
        // Retired entries retain their value, making each FWA listing ID single use.
        if (id == 0 || b.positions[id].value != 0 || b.packToListing[packId] != 0) revert Duplicate();
        uint256 value = b.idleValueOf[packId];
        if (value == 0) revert MissingInventory();
        uint256 minimum = value + value / 19 + (value % 19 == 0 ? 0 : 1);
        if (backing < minimum) revert InsufficientBacking();

        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.positions[id] = Position(packId, value, backing, debt, 0, State.Active);
        b.packToListing[packId] = id;
        b.activeBacking += backing;
        ++b.activeCount;
        b.feeDebtSum += debt;
        ++b.countByDebt[debt];
    }

    /// @notice Apply one authenticated acquisition entry in sequence order.
    function select(Book storage b, uint256 id, uint64 allocatedAt) internal {
        Position storage p = b.positions[id];
        if (p.state != State.Active) revert WrongState();
        if (allocatedAt < b.lastAllocatedAt) revert OutOfOrder();
        _removeActive(b, p);
        p.state = State.Allocated;
        p.allocatedAt = allocatedAt;
        b.lastAllocatedAt = allocatedAt;
        b.allocatedValue += p.value;
        b.allocationQueue.push(id);
    }

    /// @notice Consume an authenticated keep outcome after its selection.
    /// @dev The received eth is already in the caller's balance. A later gift of
    ///      this pack can be adopted separately after this old position retires.
    function keep(Book storage b, uint256 id) internal returns (Position memory p) {
        p = b.positions[id];
        if (p.state != State.Allocated) revert WrongState();
        b.allocatedValue -= p.value;
        b.trackedValue -= p.value;
        _retire(b, id, p.packId);
    }

    /// @notice Resolve a withdrawal, kick, or bid return. The pack keeps its P.
    /// @param owned True only after the caller has verified custody; false
    ///        requires an authenticated FWA claim owing this pack to the caller.
    function returnPack(Book storage b, uint256 id, bool owned) internal returns (Position memory p) {
        Position storage live = b.positions[id];
        p = live;
        if (p.state == State.Active) {
            _removeActive(b, live);
        } else if (p.state == State.Allocated) {
            b.allocatedValue -= p.value;
        } else {
            revert WrongState();
        }

        if (owned) {
            _retire(b, id, p.packId);
            _toIdle(b, p.packId, p.value);
        } else {
            live.state = State.Owed;
        }
    }

    /// @notice Move an authenticated recovered pack from an owed claim to idle.
    function claimReturned(Book storage b, uint256 id) internal returns (Position memory p) {
        p = b.positions[id];
        if (p.state != State.Owed) revert WrongState();
        _retire(b, id, p.packId);
        _toIdle(b, p.packId, p.value);
    }

    /// @notice Remove backing redeemed into the caller's actual eth balance.
    function redeemInventory(Book storage b, uint256 packId) internal returns (uint256 value) {
        value = b.idleValueOf[packId];
        if (value == 0) revert MissingInventory();
        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.trackedValue -= value;
    }

    /// @notice Reflect the authenticated live debt after harvesting one listing.
    function updateFeeDebt(Book storage b, uint256 id, uint256 newDebt) internal {
        Position storage p = b.positions[id];
        if (p.state != State.Active) revert WrongState();
        uint256 oldDebt = p.feeDebt;
        if (oldDebt == newDebt) return;
        if (newDebt < oldDebt) revert OutOfOrder();
        --b.countByDebt[oldDebt];
        ++b.countByDebt[newDebt];
        b.feeDebtSum = b.feeDebtSum - oldDebt + newDebt;
        p.feeDebt = newDebt;
    }

    /// @notice Exact active fees from one authenticated active listing witness.
    /// @dev Caller verifies its current FWA state and fee debt match this book,
    ///      and reads actualPending directly from FWA. All active debts are <= A+1:
    ///      activation uses ceil(accumulator), harvest uses floor(accumulator).
    function pendingFees(Book storage b, uint256 witnessId, uint256 actualPending) internal view returns (uint256) {
        uint256 n = b.activeCount;
        if (n == 0) return 0;
        Position storage p = b.positions[witnessId];
        if (p.state != State.Active) revert BadWitness();
        uint256 d = p.feeDebt;
        if (actualPending == 0) {
            if (b.countByDebt[d] + b.countByDebt[d + 1] != n) revert BadWitness();
            return 0;
        }
        uint256 a = d + actualPending;
        return n * a + b.countByDebt[a + 1] - b.feeDebtSum;
    }

    /// @notice Compute NAV only after the caller's external completeness checks.
    function nav(Book storage b, uint256 freeEth, uint256 feeCredit, uint256 witnessId, uint256 actualPending)
        internal
        view
        returns (uint256)
    {
        return freeEth + b.trackedValue + b.activeBacking + feeCredit + pendingFees(b, witnessId, actualPending);
    }

    /// @notice Advance at most maxCount resolved queue entries without a scan.
    function prune(Book storage b, uint256 maxCount) internal returns (uint256 advanced) {
        uint256 head = b.allocationHead;
        uint256 length = b.allocationQueue.length;
        while (advanced < maxCount && head < length) {
            uint256 id = b.allocationQueue[head];
            if (b.positions[id].state == State.Allocated) break;
            delete b.allocationQueue[head];
            ++head;
            ++advanced;
        }
        b.allocationHead = head;
    }

    /// @notice Read the earliest unresolved allocation after bounded cleanup.
    function oldestAllocation(Book storage b) internal view returns (uint256 id, uint64 allocatedAt) {
        if (b.allocationHead == b.allocationQueue.length) return (0, 0);
        id = b.allocationQueue[b.allocationHead];
        Position storage p = b.positions[id];
        if (p.state != State.Allocated) revert NeedsPrune();
        allocatedAt = p.allocatedAt;
    }

    function _removeActive(Book storage b, Position storage p) private {
        b.activeBacking -= p.backing;
        --b.activeCount;
        b.feeDebtSum -= p.feeDebt;
        --b.countByDebt[p.feeDebt];
    }

    function _retire(Book storage b, uint256 id, uint256 packId) private {
        b.positions[id].state = State.None;
        delete b.packToListing[packId];
    }

    function _toIdle(Book storage b, uint256 packId, uint256 value) private {
        if (b.idleValueOf[packId] != 0) revert Duplicate();
        b.idleValueOf[packId] = value;
        b.idleValue += value;
    }
}
