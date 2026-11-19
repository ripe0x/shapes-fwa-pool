// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {VaultLib as L} from "../../src/VaultLib.sol";

/// @notice Production accounting library adapter for unit and model checks. This does not
///         implement or mock FWA, VRF, shapes, or any external asset contract.
///         Real external authentication is exercised by the separate fork tests.
contract ProductionLedgerHarness {
    using L for L.Book;
    L.Book private book;

    function addInventory(uint256 pack, uint256 value) external { book.addInventory(pack, value); }
    function list(uint256 id, uint256 pack, uint256 backing, uint256 debt) external {
        book.list(id, pack, backing, debt);
    }
    function select(uint256 id, uint64 at) external { book.select(id, at); }
    function keep(uint256 id) external { book.keep(id); }
    function returnPack(uint256 id, bool owned) external { book.returnPack(id, owned); }
    function claimReturned(uint256 id) external { book.claimReturned(id); }
    function redeemInventory(uint256 pack) external returns (uint256) { return book.redeemInventory(pack); }
    function updateFeeDebt(uint256 id, uint256 debt) external { book.updateFeeDebt(id, debt); }
    function prune(uint256 maximum) external returns (uint256) { return book.prune(maximum); }
    function oldestAllocation() external view returns (uint256, uint64) { return book.oldestAllocation(); }
    function pendingFees(uint256 id, uint256 pending) external view returns (uint256) {
        return book.pendingFees(id, pending);
    }
    function nav(uint256 cash, uint256 credit, uint256 id, uint256 pending) external view returns (uint256) {
        return book.nav(cash, credit, id, pending);
    }
    function totals() external view returns (uint256, uint256, uint256, uint256, uint256, uint256) {
        return (book.trackedValue, book.idleValue, book.activeBacking,
            book.activeCount, book.feeDebtSum, book.allocatedValue);
    }
    function position(uint256 id) external view returns (L.Position memory) { return book.positions[id]; }
    function inventory(uint256 pack) external view returns (uint256) { return book.idleValueOf[pack]; }
    function topInventory() external view returns (uint256) { return book.idlePacks.length == 0 ? 0 : book.idlePacks[book.idlePacks.length - 1]; }
    function packListing(uint256 pack) external view returns (uint256) { return book.packToListing[pack]; }
    function debtCount(uint256 debt) external view returns (uint256) { return book.countByDebt[debt]; }
    function queueHead() external view returns (uint256) { return book.allocationHead; }
}

/// @dev A fresh call frame prevents the test's growing reference array from
///      changing measured memory expansion. Target account and slots are cooled
///      before each measurement, as they would be in a separate transaction.
contract ProductionLedgerGasMeter {
    function measureNav(ProductionLedgerHarness target, uint256 cash, uint256 credit, uint256 id, uint256 pending)
        external view returns (uint256 value, uint256 used)
    {
        uint256 start = gasleft();
        value = target.nav(cash, credit, id, pending);
        used = start - gasleft();
    }

    function measureCall(address target, bytes calldata input) external returns (uint256 used) {
        uint256 start = gasleft();
        (bool ok, bytes memory result) = target.call(input);
        used = start - gasleft();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
    }
}

contract ProductionLedgerModelTest is Test {
    uint256 private constant SCALE = 1e36;
    uint256 private constant QUANTUM = 10_000;
    // Arbitrary positive bookkeeping cost, not a proposed or live mint policy.
    uint256 private constant MODEL_MINT_FEE = 0.0001 ether;

    // This reference keeps economic custody per asset. It does not maintain the
    // kernel's aggregates, debt histogram, or allocation queue. Every comparison
    // recomputes those quantities independently from the complete asset array.
    enum Custody { Idle, Listed, Selected, ReturnClaim, Gone }
    struct Asset {
        uint256 pack;
        uint256 id;
        uint256 principal;
        uint256 backing;
        uint256 debt;
        uint64 selectedAt;
        Custody custody;
        bool burned;
    }
    struct Model {
        ProductionLedgerHarness ledger;
        Asset[] assets;
        uint256 cash;
        uint256 credit;
        uint256 accumulator;
        uint256 nextId;
        uint256 nextPack;
        uint64 clock;
    }
    struct FullValue {
        uint256 tracked;
        uint256 idle;
        uint256 backing;
        uint256 count;
        uint256 debt;
        uint256 allocated;
        uint256 fees;
        uint256 witness;
        uint256 witnessPending;
        uint256 ceilingDebtCount;
    }
    struct GasResult { uint256 zeroFees; uint256 positiveFees; uint256 selection; uint256 keep; uint256 prune; }

    function _newModel(uint256 count) private returns (Model memory m) {
        m.ledger = new ProductionLedgerHarness();
        m.assets = new Asset[](count);
        m.cash = 1_000_000 ether;
        m.accumulator = 5 * SCALE + SCALE / 2;
        m.nextId = 1;
        m.nextPack = 1;
        m.clock = 1_000;
        for (uint256 i; i < count; ++i) {
            uint256 value = 0.03 ether + (i % 18) * 0.01 ether;
            Asset memory a = Asset(m.nextPack++, 0, value, 0, 0, 0, Custody.Idle, false);
            m.assets[i] = a;
            m.ledger.addInventory(a.pack, value);
            m.cash -= value + MODEL_MINT_FEE;
            _list(m, i);
        }
    }

    function _list(Model memory m, uint256 i) private {
        Asset memory a = m.assets[i];
        assertEq(uint256(a.custody), uint256(Custody.Idle));
        uint256 id = m.nextId++;
        uint256 backing = a.principal * 12 / 10 + id * QUANTUM;
        uint256 debt = (m.accumulator + SCALE - 1) / SCALE;
        m.ledger.list(id, a.pack, backing, debt);
        m.cash -= backing;
        m.assets[i].id = id;
        m.assets[i].backing = backing;
        m.assets[i].debt = debt;
        m.assets[i].selectedAt = 0;
        m.assets[i].custody = Custody.Listed;
    }

    function _owedFees(Model memory m, Asset memory a) private pure returns (uint256) {
        uint256 nowFloor = m.accumulator / SCALE;
        return nowFloor > a.debt ? nowFloor - a.debt : 0;
    }

    function _scan(Model memory m) private pure returns (FullValue memory v) {
        uint256 floor = m.accumulator / SCALE;
        uint256 minimumDebt = type(uint256).max;
        for (uint256 i; i < m.assets.length; ++i) {
            Asset memory a = m.assets[i];
            if (a.custody == Custody.Gone) continue;
            v.tracked += a.principal;
            if (a.custody == Custody.Idle) {
                v.idle += a.principal;
            } else if (a.custody == Custody.Listed) {
                v.backing += a.backing;
                ++v.count;
                v.debt += a.debt;
                uint256 pending = floor > a.debt ? floor - a.debt : 0;
                v.fees += pending;
                if (a.debt == floor + 1) ++v.ceilingDebtCount;
                if (a.debt < minimumDebt) {
                    minimumDebt = a.debt;
                    v.witness = a.id;
                    v.witnessPending = pending;
                }
            } else if (a.custody == Custody.Selected) {
                v.allocated += a.principal;
            }
        }
    }

    function _compare(Model memory m) private view returns (FullValue memory v) {
        v = _scan(m);
        (uint256 tracked, uint256 idle, uint256 backing, uint256 count, uint256 debt, uint256 allocated) = m.ledger.totals();
        assertEq(tracked, v.tracked, "full inventory principal");
        assertEq(idle, v.idle, "full idle inventory");
        assertEq(backing, v.backing, "full active posted backing");
        assertEq(count, v.count, "full active count");
        assertEq(debt, v.debt, "full active fee debts");
        assertEq(allocated, v.allocated, "full unresolved allocation exposure");
        assertEq(m.ledger.debtCount(m.accumulator / SCALE + 1), v.ceilingDebtCount, "ceil debt correction");
        assertEq(m.ledger.pendingFees(v.witness, v.witnessPending), v.fees, "direct sum of per position fees");
        assertEq(m.ledger.nav(m.cash, m.credit, v.witness, v.witnessPending),
            m.cash + v.tracked + v.backing + m.credit + v.fees, "full reference NAV to the wei");
    }

    function _randomStep(Model memory m, uint256 entropy) private {
        // Revisit a small working set as well as random inventory. At 10,000
        // positions, uniform sampling alone would almost never exercise both
        // selection and terminal resolution of the same position in 64 steps.
        uint256 scope = entropy & (1 << 15) != 0 && m.assets.length > 16 ? 16 : m.assets.length;
        uint256 i = (entropy >> 16) % scope;
        Asset memory a = m.assets[i];
        uint256 op = entropy % 10;
        if (op == 0) {
            // Monotonic fractional counter. The new floor may be unchanged,
            // cross one rounding boundary, or advance by hundreds of wei.
            m.accumulator += ((entropy >> 32) % 501) * SCALE + (entropy >> 96) % SCALE;
        } else if (op == 1) {
            m.cash += m.credit;
            m.credit = 0;
        } else if (a.custody == Custody.Listed) {
            if (op <= 3) {
                uint256 pending = _owedFees(m, a);
                if (pending == 0) return; // Deployed FWA skips a zero fee claim.
                uint256 debt = m.accumulator / SCALE;
                m.ledger.updateFeeDebt(a.id, debt);
                m.assets[i].debt = debt;
                m.cash += pending;
            } else if (op <= 6) {
                m.credit += _owedFees(m, a);
                uint64 at = ++m.clock;
                m.ledger.select(a.id, at);
                m.assets[i].custody = Custody.Selected;
                m.assets[i].selectedAt = at;
            } else {
                bool owned = entropy & (1 << 8) != 0;
                m.credit += _owedFees(m, a);
                m.cash += a.backing;
                m.ledger.returnPack(a.id, owned);
                m.assets[i].custody = owned ? Custody.Idle : Custody.ReturnClaim;
            }
        } else if (a.custody == Custody.Selected) {
            if (op <= 5) {
                uint256 fee = (entropy >> 32) % 501;
                m.ledger.keep(a.id);
                m.cash += a.backing * (10_000 - fee) / 10_000;
                m.assets[i].custody = Custody.Gone;
                m.assets[i].burned = false;
            } else {
                bool owned = entropy & (1 << 8) != 0;
                m.ledger.returnPack(a.id, owned);
                m.assets[i].custody = owned ? Custody.Idle : Custody.ReturnClaim;
            }
        } else if (a.custody == Custody.ReturnClaim) {
            m.ledger.claimReturned(a.id);
            m.assets[i].custody = Custody.Idle;
        } else if (a.custody == Custody.Idle) {
            if (m.ledger.topInventory() != a.pack) return; // Production consumes its inventory stack from the top.
            if (op <= 5) {
                _list(m, i);
            } else {
                uint256 principal = m.ledger.redeemInventory(a.pack);
                assertEq(principal, a.principal);
                m.cash += a.principal;
                m.assets[i].custody = Custody.Gone;
                m.assets[i].burned = true;
            }
        } else {
            // A kept pack can later be donated back. A redeemed pack is burned,
            // so replacement requires a fresh identity and another paid mint.
            if (a.burned) {
                m.assets[i].pack = m.nextPack++;
                m.cash -= a.principal + MODEL_MINT_FEE;
            }
            m.ledger.addInventory(m.assets[i].pack, a.principal);
            m.assets[i].custody = Custody.Idle;
            m.assets[i].burned = false;
        }
    }

    function _history(Model memory m, uint256 seed, uint256 steps) private {
        for (uint256 step; step < steps; ++step) {
            seed = uint256(keccak256(abi.encode(seed, step)));
            _randomStep(m, seed);
            _compare(m);
            // Cleanup is allowed to stop after any bounded number of entries.
            m.ledger.prune(seed % 4);
        }
    }

    function _measureNav(Model memory m, ProductionLedgerGasMeter meter) private returns (uint256 used) {
        FullValue memory v = _scan(m);
        vm.cool(address(m.ledger));
        (uint256 value, uint256 gasUsed) = meter.measureNav(m.ledger, m.cash, m.credit, v.witness, v.witnessPending);
        assertEq(value, m.cash + v.tracked + v.backing + m.credit + v.fees);
        assertLt(gasUsed, 100_000, "bounded kernel NAV including cold external call");
        return gasUsed;
    }

    function _scale(uint256 count) private returns (GasResult memory g) {
        Model memory m = _newModel(count);
        ProductionLedgerGasMeter meter = new ProductionLedgerGasMeter();
        _compare(m);
        g.zeroFees = _measureNav(m, meter);
        m.accumulator += 20 * SCALE;
        _compare(m);
        g.positiveFees = _measureNav(m, meter);

        uint256 index = count / 2;
        Asset memory a = m.assets[index];
        m.credit += _owedFees(m, a);
        uint64 at = ++m.clock;
        vm.cool(address(m.ledger));
        g.selection = meter.measureCall(address(m.ledger), abi.encodeCall(ProductionLedgerHarness.select, (a.id, at)));
        m.assets[index].custody = Custody.Selected;
        m.assets[index].selectedAt = at;
        _compare(m);

        vm.cool(address(m.ledger));
        g.keep = meter.measureCall(address(m.ledger), abi.encodeCall(ProductionLedgerHarness.keep, (a.id)));
        m.cash += a.backing * 9900 / 10_000;
        m.assets[index].custody = Custody.Gone;
        _compare(m);

        vm.cool(address(m.ledger));
        g.prune = meter.measureCall(address(m.ledger), abi.encodeCall(ProductionLedgerHarness.prune, (1)));
        (uint256 first,) = m.ledger.oldestAllocation();
        assertEq(first, 0);
        _history(m, uint256(keccak256(abi.encode(count, "scale"))), 64);

        emit log_named_uint("bookkeeping positions", count);
        emit log_named_uint("cold NAV with zero fees", g.zeroFees);
        emit log_named_uint("cold NAV with positive fees", g.positiveFees);
        emit log_named_uint("cold selection transition", g.selection);
        emit log_named_uint("cold keep transition", g.keep);
        emit log_named_uint("cold one entry queue cleanup", g.prune);
        assertLt(g.selection, 16_777_216);
        assertLt(g.keep, 16_777_216);
        assertLt(g.prune, 16_777_216);
    }

    /// @dev Run with --gas-limit 10000000000. The test creates 11,301 model
    ///      positions in many separate calls. That total fixture cost exceeds
    ///      Foundry's default test budget; each measured ledger call is bounded.
    function test_scale301_1000_10000MatchesReferenceAndHasConstantValuationGas() public {
        GasResult memory a = _scale(301);
        GasResult memory b = _scale(1_000);
        GasResult memory c = _scale(10_000);
        assertEq(a.zeroFees, b.zeroFees, "301 and 1000 zero fee NAV gas");
        assertEq(a.zeroFees, c.zeroFees, "301 and 10000 zero fee NAV gas");
        assertEq(a.positiveFees, b.positiveFees, "301 and 1000 positive fee NAV gas");
        assertEq(a.positiveFees, c.positiveFees, "301 and 10000 positive fee NAV gas");
        assertEq(a.selection, c.selection, "selection does not scan the portfolio");
        assertEq(a.keep, c.keep, "keep does not scan the portfolio");
        assertEq(a.prune, c.prune, "bounded cleanup does not scan the portfolio");
    }

    function testFuzz_randomizedLifecycleMatchesFullReference(uint256 seed) public {
        Model memory m = _newModel(32);
        _compare(m);
        _history(m, seed, 160);
    }

    function test_feeRoundingAndWitnessCompleteness() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        h.addInventory(1, 0.1 ether);
        h.list(101, 1, 0.2 ether, 90);
        h.addInventory(2, 0.1 ether);
        h.list(102, 2, 0.2 ether, 101);
        // A=100. The newest position has ceil(A+fraction)=101 and earns zero.
        // The old position earns ten. A fresh zero witness cannot hide that.
        vm.expectRevert(L.BadWitness.selector);
        h.pendingFees(102, 0);
        assertEq(h.pendingFees(101, 10), 10, "ceil correction prevents a one wei undercount");
        h.updateFeeDebt(101, 100);
        assertEq(h.pendingFees(101, 0), 0, "mixed floor and ceiling debts can both earn zero");
        vm.expectRevert(L.BadWitness.selector);
        h.pendingFees(102, 0);
        // When A advances to101, only the harvested position earns one.
        assertEq(h.pendingFees(101, 1), 1);
        h.select(101, 1);
        vm.expectRevert(L.BadWitness.selector);
        h.pendingFees(101, 1);
        assertEq(h.pendingFees(102, 0), 0);
        h.returnPack(102, true);
        assertEq(h.pendingFees(0, 0), 0, "empty active set needs no witness");
    }

    function test_duplicateTransitionsCannotDoubleCountPrincipalOrFees() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        h.addInventory(1, 0.1 ether);
        vm.expectRevert(L.Duplicate.selector);
        h.addInventory(1, 0.1 ether);
        h.list(10, 1, 0.2 ether, 7);
        vm.expectRevert(L.Duplicate.selector);
        h.list(11, 1, 0.2 ether, 7);
        vm.expectRevert(L.MissingInventory.selector);
        h.redeemInventory(1);
        vm.expectRevert(L.WrongState.selector);
        h.keep(10);
        h.select(10, 100);
        vm.expectRevert(L.WrongState.selector);
        h.select(10, 100);
        h.keep(10);
        vm.expectRevert(L.WrongState.selector);
        h.keep(10);
        vm.expectRevert(L.WrongState.selector);
        h.returnPack(10, true);
        h.addInventory(1, 0.1 ether); // Authenticated later gift, separate from old keep.
        vm.expectRevert(L.Duplicate.selector);
        h.list(10, 1, 0.2 ether, 8); // Old listing IDs cannot be recycled.
        h.list(11, 1, 0.2 ether, 8);
        assertEq(h.packListing(1), 11);
        assertEq(h.nav(0, 0, 11, 0), 0.3 ether);
    }

    function test_owedReturnsKeepPrincipalAndCannotBeSpentEarly() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        h.addInventory(9, 0.1 ether);
        h.list(90, 9, 0.2 ether, 7);
        h.select(90, 100);
        h.returnPack(90, false);
        assertEq(h.nav(0, 0, 0, 0), 0.1 ether);
        assertEq(h.inventory(9), 0);
        vm.expectRevert(L.MissingInventory.selector);
        h.redeemInventory(9);
        vm.expectRevert(L.Duplicate.selector);
        h.addInventory(9, 0.1 ether);
        vm.expectRevert(L.WrongState.selector);
        h.keep(90);
        h.claimReturned(90);
        vm.expectRevert(L.WrongState.selector);
        h.claimReturned(90);
        assertEq(h.inventory(9), 0.1 ether);
        assertEq(h.redeemInventory(9), 0.1 ether);
        assertEq(h.nav(0, 0, 0, 0), 0);
    }

    function test_fifoOnlyNeedsBoundedTombstoneCleanup() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        for (uint256 id = 1; id <= 4; ++id) {
            h.addInventory(id, 0.1 ether);
            h.list(id, id, 0.2 ether, 0);
        }
        h.select(1, 100);
        h.select(2, 101);
        h.select(3, 102);
        vm.expectRevert(L.OutOfOrder.selector);
        h.select(4, 99);
        h.returnPack(2, true);
        assertEq(h.prune(100), 0, "unresolved oldest entry stops pruning");
        (uint256 first, uint64 at) = h.oldestAllocation();
        assertEq(first, 1);
        assertEq(at, 100);
        h.keep(1);
        vm.expectRevert(L.NeedsPrune.selector);
        h.oldestAllocation();
        assertEq(h.prune(1), 1);
        assertEq(h.queueHead(), 1);
        vm.expectRevert(L.NeedsPrune.selector);
        h.oldestAllocation();
        assertEq(h.prune(1), 1);
        (first, at) = h.oldestAllocation();
        assertEq(first, 3);
        assertEq(at, 102);
        h.returnPack(3, false);
        assertEq(h.prune(1), 1, "an owed return is no longer an unresolved allocation");
        (first, at) = h.oldestAllocation();
        assertEq(first, 0);
        assertEq(at, 0);
    }

    function test_backingFloorCoversMaximumFeeAtRoundingBoundary() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        for (uint256 value = 1; value < 60; ++value) {
            h.addInventory(value, value);
            uint256 minimum = (value * 10_000 + 9499) / 9500;
            vm.expectRevert(L.InsufficientBacking.selector);
            h.list(value, value, minimum - 1, 0);
            h.list(value, value, minimum, 0);
            assertGe(minimum - minimum * 500 / 10_000, value);
        }
    }
    function test_maximumPruneBatchHasBoundedProductionKernelGas() public {
        ProductionLedgerHarness h = new ProductionLedgerHarness();
        for (uint256 id = 1; id <= 16; ++id) {
            h.addInventory(id, 0.03 ether); h.list(id, id, 0.0363 ether, 1);
            h.select(id, uint64(id)); h.keep(id);
        }
        ProductionLedgerGasMeter meter = new ProductionLedgerGasMeter();
        vm.cool(address(h));
        uint256 used = meter.measureCall(address(h), abi.encodeCall(ProductionLedgerHarness.prune, (16)));
        emit log_named_uint("production kernel prune sixteen gas excluding financial payment", used);
        assertEq(h.queueHead(), 16);
        assertLt((used + 21_000) * 125 / 100, 16_777_216);
    }

}
