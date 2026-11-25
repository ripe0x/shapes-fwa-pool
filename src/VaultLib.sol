// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {LibBit} from "solady/utils/LibBit.sol";
import {ScanLib} from "./ScanLib.sol";
import {
    IFWAV2,
    IFWAView,
    IFloorOracle,
    IShapePacks,
    IShapes,
    LISTING_ACTIVE,
    LISTING_ALLOCATED,
    LISTING_SETTLED,
    LISTING_WITHDRAWN
} from "./interfaces/External.sol";

/// @notice What the shared strategy reads from the account it runs in (PackVault or PackManager):
///         ETH it may spend on keeper pay (`freeEth`) and on new exposure (`idleEth`). Each
///         account defines both from its own liabilities; the strategy never sees them otherwise.
interface IAccount {
    function freeEth() external view returns (uint256);
    function idleEth() external view returns (uint256);
    function renewalCash() external view returns (uint256);
    function keeperCash() external view returns (uint256);
    function fundingDeficit(bool renewal) external view returns (uint256);
}

/// @notice PackVault's share-price reads, used only for its distribution checkpoint tail.
interface ISyncVault is IAccount {
    function accountedNav(uint256 witnessId) external view returns (uint256);
    function totalShares() external view returns (uint256);
    function highWaterMark() external view returns (uint256);
}

/// @notice Shared strategy core, linked into PackVault and PackManager (with StrategyLib and
///         ScanLib). Runs by DELEGATECALL in the calling account's context, so that account is the
///         FWA depositor and owns every asset; the library holds no state and reads only the
///         storage pointers it is passed. Split into three libraries only for EIP-170 size.
library VaultLib {
    uint256 internal constant BPS = 10_000;
    uint256 internal constant DEAD_SHARES = 1e15;

    /// @notice PackVault's governed parameters (moved here so library code can read them by
    ///         storage pointer; EIP-170 size).
    struct GasSchedule {
        uint32 checkpoint;
        uint32 allocationEntry;
        uint32 allocationRead;
        uint32 build;
        uint32 buildPack;
        uint32 buildShape;
        uint32 list;
        uint32 listed;
        uint32 sync;
        uint32 requiredTail;
        uint32 distributionProof;
        uint32 journal;
        uint32 scan;
        uint32 selected;
        uint32 synced;
        uint32 pruned;
        uint32 unlist;
        uint32 unlisted;
        uint32 liquidate;
        uint32 liquidatePack;
        uint32 redeemShape;
        uint32 recoveryBase;
        uint32 recoveryShape;
        uint32 recoveryUnseal;
        uint32 harvest;
        uint32 harvested;
        uint32 credit;
        uint32 fund;
    }

    enum RenewalMode { FreshAfterAcquisition, ReuseReturned }

    struct Params {
        uint16 minEdgeBps; // require k >= 1 + minEdge
        uint16 bufferBps; // list at cap x (1 - buffer), so a small ask cut does not trigger kicks
        uint16 distributionBps; // share of new gains above the high-water mark paid out
        uint16 payMarkupBps; // markup on quoted routine gas compensation
        uint16 keeperShareBps; // optional calls are paid only if pay <= this share of value realized
        uint16 upliftBoundBps; // checkpoint skips when Allocated value exceeds this share of NAV
        uint64 packUnitsMask; // bit u set: packs of u x 0.01 ETH may be built and listed
        uint64 gasCeiling; // wei per gas, routine work
        uint64 essentialCeiling; // wei per gas, redemption and wind-down work (essential budget)
        uint64 maxTip; // reimbursed price is at most basefee + this
        uint64 workFee; // flat wei per unit of work done: position listed, resolved,
        //                 unlisted, item liquidated, or a checkpoint that priced flows
        uint64 routineCap; // keeper budget for strategy work: capacity (wei) and refill per day
        uint64 routineRate;
        uint64 essentialCap; // keeper budget for redemption and wind-down work
        uint64 essentialRate;
        uint128 reserve; // ETH kept idle
        uint128 tvlCap; // deposits refused above this NAV
        uint32 backingRatioBps; // backing as a ratio of pack face value
        RenewalMode renewalMode;
        uint16 renewalFloatCount;
        uint64 acceptedMintFee; // changed only by explicit owner acceptance
        uint64 minDeposit;
        uint64 minDistribution;
        GasSchedule gasSchedule;
    }


    uint256 internal constant UNIT = 0.01 ether;

    /// @notice Everything the shared strategy owns in an account: governed parameters, keeper
    ///         budgets, the position book and the two operating flags.
    struct Strategy {
        Params params;
        Budget budget;
        Book book;
        bool listingPaused;
        bool windingDown;
        bool callerFunded;
    }

    // ---------------------------------------------------------------- bounds and quotes

    uint256 internal constant MAX_WORK_FEE = 0.00005 ether; // per unit of work (D55, D56)
    uint256 internal constant MAX_MIN_EDGE_BPS = 1_000;
    uint256 internal constant MAX_BUFFER_BPS = 2_000;
    uint256 internal constant MAX_GAS_CEILING = 50 gwei;
    uint256 internal constant MAX_DISTRIBUTION_BPS = 5_000;
    uint256 internal constant MAX_PAY_MARKUP_BPS = 1_000; // routine work only (D56, D57)
    uint256 internal constant MAX_KEEPER_SHARE_BPS = 5_000;
    uint256 internal constant MAX_UPLIFT_BOUND_BPS = 1_000;
    uint256 internal constant MAX_ROUTINE_CAP = 0.3 ether;
    uint256 internal constant MAX_ROUTINE_RATE = 0.02 ether;
    uint256 internal constant MAX_ESSENTIAL_CAP = 0.1 ether;
    uint256 internal constant MAX_ESSENTIAL_RATE = 0.005 ether;
    uint256 internal constant MAX_PACK_UNITS = 30; // at most 30 x 0.01 ETH: bounded redemption work
    uint256 internal constant MIN_PACK_UNITS = 3; // ShapePacks' minimum pack value, 0.03 ETH
    uint256 internal constant REF_UNITS = 3; // charge fallback; launch recipe remains owner adjustable
    uint256 internal constant MAX_BACKING_RATIO_BPS = 1_000_000;
    uint256 internal constant MAX_GAS_QUOTE = 16_777_216;
    uint256 internal constant MAX_REBASE_SCAN = 96; // independent of every economic setting

    uint256 internal constant MAX_BATCH = 16;
    uint256 internal constant MAX_JOURNAL = 128;
    uint256 internal constant MAX_SELECTIONS = 16;
    /// Pricing reads at most this many allocation queue entries. The queue from its head holds only
    /// allocations newer than the oldest unresolved one, which a checkpoint already requires to be
    /// inside FWA's settlement window, so a longer queue waits at most one window for sync.
    uint256 internal constant MAX_ALLOCATION_SCAN = 32;
    uint256 internal constant MAX_TERMINALS = 16;
    uint256 internal constant MAX_PRUNES = 16;
    uint256 internal constant MAX_LIST_BATCH = 8;
    uint256 internal constant MAX_BUILD_BATCH = 4; // paid mint work fits the transaction cap with keeper padding
    uint256 internal constant LIST_CALL_GAS = 1_200_000;
    uint256 internal constant MAX_LIQUIDATE_UNITS = 60;
    uint256 internal constant MAX_REDEEM_SHAPES = 30; // Shapes burned per liquidation call
    uint8 internal constant NONE = 0;
    uint8 internal constant ACTIVE = 1;
    uint8 internal constant ALLOCATED = 2;
    uint8 internal constant OWED = 3;

    struct Position {
        uint256 packId;
        uint256 value;
        uint256 backing;
        uint256 feeDebt;
        uint64 allocatedAt;
        uint8 state;
        uint256 keepUplift;
    }

    struct Work { uint256 processed; uint256 own; uint256 resolved; uint256 pruned; uint256 scanned; }

    struct BackingTerms {
        uint256 k;
        uint256 desired;
        uint256 cap;
        uint256 settlementFee;
        uint256 value;
        uint256 floor;
        uint256 cycleCost;
        uint256 initialCost;
        bool ok;
    }

    struct Receipt { uint128 amount; uint16 feeBps; uint8 kind; bool initialized; }

    /// @dev Inventory indexes and all financial totals share this single authoritative book.
    struct Book {
        mapping(uint256 => Position) positions;
        mapping(uint256 => uint256) idleValueOf;
        mapping(uint256 => uint256) packToListing;
        uint256 trackedValue;
        uint256 idleValue;
        uint256 activeBacking;
        uint256 activeCount;
        uint256 feeDebtSum;
        mapping(uint256 => uint256) countByDebt;
        uint256 allocatedValue;
        uint256 unresolvedKeepUplift;
        mapping(uint256 => bool) renewalEligible;
        uint256 renewalEligibleCount;
        uint256 keptReplacements;
        uint256[31] recipeCounts;
        mapping(uint256 => uint256) packShapeCount;
        uint256 ordinaryShapeCount;
        bool renewalEnabled;
        mapping(uint256 => uint256) idleIndex;
        uint256[] allocationQueue;
        uint256 allocationHead;
        uint64 lastAllocatedAt;
        uint256[] open;
        mapping(uint256 => uint256) openIndex;
        uint256[] idlePacks;
        uint256[] recoveryPacks;
        mapping(uint256 => bool) recoveryUnsealed;
        mapping(uint256 => uint256) idleQuote;
        uint256 idleFunding;
        mapping(uint256 => uint256) idForBacking;
        mapping(uint256 => Receipt) receipts;
        uint256 pendingPlusOne;
        uint256 reservedCount;
        uint64 acquisitionCursor;
        bool controlled;
    }

    event PositionUpdated(uint256 indexed listingId, uint256 packId, uint256 value, uint256 backing, uint256 feeDebt, uint64 allocatedAt, uint8 state);
    event InventoryUpdated(uint256 indexed packId, uint256 value);
    event PrimaryMinted(uint256 packs, uint256 shapes, uint256 principal, uint256 mintFees);
    event RecoveryUpdated(uint256 indexed packId, uint256 value, bool unsealed);
    event CashReceipt(uint256 indexed listingId, uint8 outcome, uint256 amount);
    event ReceiptConsumed(uint256 indexed listingId);
    event JournalProgress(uint64 cursor, uint256 processed, uint256 own);

    error Duplicate();
    error MissingInventory();
    error WrongState();
    error InsufficientBacking();
    error BadWitness();
    error NeedsPrune();
    error OutOfOrder();
    error InvalidListing();
    error InvalidJournal();
    error CatchUpFirst();
    error PendingReceipts();
    error InvalidBacking();
    error BadBatch();
    error Nothing();

    /// @notice One checkpoint's redemption fill. Owed rounds up and a partial fill leaves 2 wei of
    ///         headroom, so the rounded-up reserve never exceeds the ETH actually freed. `unit` is
    ///         ETH per locked share x 1e36; holders claim floor(shares x unit) and the reserve
    ///         (`paid`) rounds the same unit up over the never-understated locked total.
    function fill(uint256 locked, uint256 nav, uint256 supply, uint256 liquid)
        external
        pure
        returns (uint256 frac, uint256 filled, uint256 unit, uint256 paid)
    {
        return ScanLib.fill(locked, nav, supply, liquid);
    }

    error OutOfBounds();

    uint256 internal constant ORACLE_GAS = 100_000;

    // ---------------------------------------------------------------- keeper pay (D56, D57)

    /// Keeper budgets: levels as of `at`; each refills at its daily rate up to its cap.
    struct Budget {
        uint128 routine;
        uint128 essential;
        uint256 at;
    }

    event KeeperPaid(address indexed keeper, uint256 amount);

    error Payment();
    error MintFeeNotAccepted();
    error ExplicitFeeAcceptanceRequired();

    /// @notice The vault's envelope for work: quoted gas at basefee + maxTip, capped at the
    ///         ceiling, markup on routine work, plus work fees. The most this work may ever pay.
    function quote(Params storage p, uint256 gasQ, uint256 units, bool essential) internal view returns (uint256) {
        return calculatePayment(gasQ, units, block.basefee, essential ? p.essentialCeiling : p.gasCeiling,
            p.maxTip, essential ? 0 : p.payMarkupBps, p.workFee);
    }

    function calculatePayment(uint256 gasQ, uint256 units, uint256 basefee, uint256 ceiling,
        uint256 tip, uint256 markupBps, uint256 workFee) internal pure returns (uint256)
    {
        return gasQ * M.min(basefee + tip, ceiling) * (BPS + markupBps) / BPS + units * workFee;
    }

    function budgetNow(Params storage p, Budget storage b) internal view returns (uint256 r, uint256 e) {
        uint256 dt = block.timestamp - b.at;
        r = M.min(p.routineCap, b.routine + dt * p.routineRate / 1 days);
        e = M.min(p.essentialCap, b.essential + dt * p.essentialRate / 1 days);
    }

    /// @notice Accrue both budgets to now; caps lowered since only clamp, never refill.
    function syncBudget(Params storage p, Budget storage b) external {
        (uint256 r, uint256 e) = budgetNow(p, b);
        (b.routine, b.essential, b.at) = (uint128(r), uint128(e), block.timestamp);
    }

    /// @notice Pay the caller for verified work: the least of the account's
    ///         envelope for that work, `cap` (a funding source), free ETH and the budget. Below
    ///         `minPay` the whole call reverts; with 0 the work is done for whatever is paid.
    function pay(
        Params storage p,
        Budget storage b,
        uint256 gasQ,
        uint256 units,
        bool essential,
        uint256 minPay,
        uint256 cap,
        uint256 free
    ) external returns (uint256 amount) {
        (uint256 r, uint256 e) = budgetNow(p, b);
        amount = M.min(M.min(quote(p, gasQ, units, essential), cap), M.min(free, essential ? e : r));
        if (amount < minPay) revert Payment();
        (b.routine, b.essential, b.at) =
            (uint128(essential ? r : r - amount), uint128(essential ? e - amount : e), block.timestamp);
        if (amount == 0) return 0;
        (bool ok,) = msg.sender.call{value: amount}("");
        if (!ok) revert Payment();
        emit KeeperPaid(msg.sender, amount);
    }

    function payFunded(Params storage p, uint256 gasQ, uint256 units, bool essential, uint256 minPay,
        uint256 fundingCap) external returns (uint256 amount)
    {
        amount = M.min(quote(p, gasQ, units, essential), fundingCap);
        if (amount < minPay) revert Payment();
        if (amount != 0) {
            (bool ok,) = msg.sender.call{value: amount}("");
            if (!ok) revert Payment();
            emit KeeperPaid(msg.sender, amount);
        }
    }

    function defaultGasSchedule() internal pure returns (GasSchedule memory g) {
        g = GasSchedule(500_000, 6_000, 30_000, 360_000, 300_000, 130_000, 280_000, 825_000,
            125_000, 120_000, 80_000, 22_000, 30_000, 180_000, 120_000, 45_000, 340_000, 285_000,
            75_000, 80_000, 35_000, 100_000, 35_000, 70_000, 125_000, 80_000, 40_000, 40_000);
    }

    function preview(Params memory p, uint256 mintFee) external view returns (uint256 units, uint256 principal,
        uint256 backing, uint256 mintCost, uint256 floatRequired, uint256 openingCash, bytes32 expectedConfigHash)
    {
        return ScanLib.preview(p, mintFee);
    }

    function cycleGas(GasSchedule storage g) internal view returns (uint256) {
        return uint256(g.journal) + g.selected + g.synced + g.pruned + g.listed + g.harvested;
    }

    // ---------------------------------------------------------------- parameters and charges

    /// @notice Bytecode bounds on every parameter.
    function checkBounds(Params storage p) external view {
        ScanLib.checkBounds(p);
    }

    /// @notice ShapePacks makeup for a pack of `units` x 0.01 ETH, minted straight into the pack:
    ///         fewest Shapes from the 0.1, 0.05 and 0.01 denominations (index 2, 1, 0 of the nine).
    ///         Six units are one 0.05 and one 0.01 Shape: two paid primary mints.
    function makeup(uint256 units) internal pure returns (uint32[] memory counts, uint256 shapeCount) {
        counts = new uint32[](9);
        counts[2] = uint32(units / 10);
        counts[1] = uint32(units % 10 / 5);
        counts[0] = uint32(units % 5);
        shapeCount = uint256(counts[0]) + counts[1] + counts[2];
    }

    function buildGas(Params storage p, uint256 shapeCount) internal view returns (uint256) {
        return p.gasSchedule.buildPack + shapeCount * p.gasSchedule.buildShape;
    }

    function renewalGas(Params storage p, uint256 count, uint256 retired, uint256 burned)
        internal view returns (uint256 gasQ)
    {
        (, uint256 n) = makeup(refUnits(p));
        gasQ = uint256(p.gasSchedule.build) + count * (buildGas(p, n) + p.gasSchedule.listed);
        if (retired != 0) gasQ += uint256(p.gasSchedule.liquidate)
            + retired * p.gasSchedule.liquidatePack + burned * p.gasSchedule.redeemShape;
    }

    function renewalFundingGas(Params storage p, uint256 feeClaims, bool withdrawCredit)
        internal view returns (uint256)
    {
        return uint256(p.gasSchedule.fund) + feeClaims * p.gasSchedule.harvested
            + (withdrawCredit ? p.gasSchedule.credit : 0);
    }

    /// @notice Building one pack of `units` and listing it, at the envelope now, plus its paid
    ///         primary mint fees (one per Shape).
    function buildCost(Params storage p, uint256 units, uint256 mintFee) public view returns (uint256) {
        return ScanLib.buildCost(p, units, mintFee);
    }

    /// @notice A request's checkpoint charge: one checkpoint at its envelope, at cost plus one unit.
    function requestCharge(Params storage p) external view returns (uint256) {
        return quote(p, p.gasSchedule.checkpoint, 1, true);
    }

    function refUnits(Params storage p) internal view returns (uint256) {
        return p.packUnitsMask == 0 ? REF_UNITS : LibBit.ffs(p.packUnitsMask);
    }

    function positionValue(Params storage p) external view returns (uint256) {
        return ScanLib.positionValue(p);
    }

    function renewalFloat(Params storage p) public view returns (uint256) {
        return ScanLib.renewalFloat(p);
    }

    function operatingReserve(Params storage p) external view returns (uint256) {
        return ScanLib.operatingReserve(p);
    }

    function deployCharge(Params storage p, uint256 mintFee) external view returns (uint256 cost) {
        return ScanLib.deployCharge(p, mintFee);
    }

    function unwindCharge(Params storage p, Book storage b) external view returns (uint256) {
        return ScanLib.unwindCharge(p, b);
    }

    /// @notice Owner-selected backing ratio, bounded by actual FWA admission and profitable
    ///         operating costs. Buyer choice is modeled, never enforced by the backing recipe.
    function edge(Params storage p, IFWAV2 f, address packs, uint256 units, uint256 mintFee, bool newlyBuilt, uint256 retiredShapes)
        public
        view
        returns (uint256 k1e18, uint256 backing, bool ok)
    {
        BackingTerms memory t = _backingTerms(p, f, packs, units, mintFee, retiredShapes);
        ok = t.ok && _profitable(t, t.desired, newlyBuilt);
        return (t.k, ok ? t.desired : 0, ok);
    }

    function _backingTerms(Params storage p, IFWAV2 f, address packs, uint256 units, uint256 mintFee, uint256 retiredShapes)
        private view returns (BackingTerms memory t)
    {
        return ScanLib.backingTerms(p, f, packs, units, mintFee, retiredShapes);
    }

    /// @dev Initial reuse pays construction once plus maintenance, without charging a second
    ///      relisting. A continuing reuse cycle pays no fresh mint. Fresh cycles fund replacement.
    function _profitable(BackingTerms memory t, uint256 backing, bool newlyBuilt) internal pure returns (bool) {
        uint256 cost = newlyBuilt ? t.initialCost : t.cycleCost;
        return backing * (t.k - 1e18) / 1e18 > cost
            && backing * (t.k - t.settlementFee * 1e14) / 1e18 >= t.value + cost;
    }


    /// @notice Revert before the work when `minPay` already exceeds what could be paid.
    function precheck(Params storage p, Budget storage b, uint256 minPay, bool essential, uint256 free)
        external
        view
    {
        (uint256 r, uint256 e) = budgetNow(p, b);
        if (minPay > M.min(free, essential ? e : r)) revert Payment();
    }

    function owns(IShapePacks packs, uint256 packId) internal view returns (bool) {
        try packs.ownerOf(packId) returns (address o) {
            return o == address(this);
        } catch {
            return false;
        }
    }

    /// @notice Live k (1e18 scale) and FWA's backing cap for `packs` (zero when FWA would refuse
    ///         a listing). k = (1 + surcharge)(1 - protocolCut)(1 - crownShare).
    function economics(IFWAV2 f, address packs) internal view returns (uint256 k1e18, uint256 cap, uint256 s) {
        return ScanLib.economics(f, packs);
    }

    function _emitPosition(Book storage b, uint256 id) internal {
        Position storage p = b.positions[id];
        emit PositionUpdated(id, p.packId, p.value, p.backing, p.feeDebt, p.allocatedAt, p.state);
    }

    function addInventory(Book storage b, uint256 packId, uint256 value) internal {
        if (value == 0 || b.idleValueOf[packId] != 0 || b.packToListing[packId] != 0) revert Duplicate();
        b.trackedValue += value;
        if (value <= MAX_PACK_UNITS * UNIT) {
            ++b.recipeCounts[value / UNIT];
            b.packShapeCount[packId] = value / UNIT;
            b.ordinaryShapeCount += value / UNIT;
        }
        b.idleValue += value;
        _toIdle(b, packId, value, 0);
    }

    function _toIdle(Book storage b, uint256 packId, uint256 value, uint256 backingQuote) private {
        if (b.idleValueOf[packId] != 0) revert Duplicate();
        b.idleValueOf[packId] = value;
        if (value > MAX_PACK_UNITS * UNIT) {
            b.recoveryPacks.push(packId);
            emit RecoveryUpdated(packId, value, false);
        } else {
            b.idlePacks.push(packId);
            b.idleIndex[packId] = b.idlePacks.length;
            emit InventoryUpdated(packId, value);
        }
        b.idleQuote[packId] = backingQuote;
        b.idleFunding += backingQuote;
    }

    function list(Book storage b, uint256 id, uint256 packId, uint256 backing, uint256 debt) internal {
        if (id == 0 || b.positions[id].value != 0 || b.packToListing[packId] != 0) revert Duplicate();
        uint256 value = b.idleValueOf[packId];
        if (value == 0) revert MissingInventory();
        // Preserve the face-value floor of an unresolved allocation at the 5% protocol fee cap.
        if (backing < value + value / 19 + (value % 19 == 0 ? 0 : 1)) revert InsufficientBacking();
        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.idleFunding -= b.idleQuote[packId];
        delete b.idleQuote[packId];
        _removeIdle(b, packId);
        emit InventoryUpdated(packId, 0);
        b.positions[id] = Position(packId, value, backing, debt, 0, ACTIVE, 0);
        clearRenewal(b, packId);
        b.packToListing[packId] = id;
        b.open.push(id);
        b.openIndex[id] = b.open.length;
        b.activeBacking += backing;
        ++b.activeCount;
        b.feeDebtSum += debt;
        ++b.countByDebt[debt];
        _emitPosition(b, id);
    }

    /// @dev Every caller (`_syncJournal`, `ScanLib.rebase`) must move the cursor past this selection's
    ///      sequence in the same call; completeness of both proofs relies on it.
    function select(Book storage b, uint256 id, uint64 at) internal {
        Position storage p = b.positions[id];
        if (p.state != ACTIVE) revert WrongState();
        if (at < b.lastAllocatedAt) revert OutOfOrder();
        _removeActive(b, p);
        p.state = ALLOCATED;
        p.allocatedAt = at;
        b.lastAllocatedAt = at;
        b.allocatedValue += p.value;
        p.keepUplift = p.backing > p.value ? p.backing - p.value : 0;
        b.unresolvedKeepUplift += p.keepUplift;
        b.allocationQueue.push(id);
        _emitPosition(b, id);
    }

    function keep(Book storage b, uint256 id) internal returns (Position memory p) {
        p = b.positions[id];
        if (p.state != ALLOCATED) revert WrongState();
        b.allocatedValue -= p.value;
        b.unresolvedKeepUplift -= p.keepUplift;
        b.trackedValue -= p.value;
        --b.recipeCounts[p.value / UNIT];
        b.ordinaryShapeCount -= b.packShapeCount[p.packId];
        delete b.packShapeCount[p.packId];
        _retire(b, id, p.packId);
    }

    function returnPack(Book storage b, uint256 id, bool owned) internal returns (Position memory p) {
        Position storage live = b.positions[id];
        p = live;
        if (p.state == ACTIVE) _removeActive(b, live);
        else if (p.state == ALLOCATED) {
            b.allocatedValue -= p.value;
            b.unresolvedKeepUplift -= p.keepUplift;
            live.keepUplift = 0;
        }
        else revert WrongState();
        if (owned) {
            _retire(b, id, p.packId);
            b.idleValue += p.value;
            _toIdle(b, p.packId, p.value, p.backing);
        } else {
            live.state = OWED;
            _emitPosition(b, id);
        }
    }

    function claimReturned(Book storage b, uint256 id) internal returns (Position memory p) {
        p = b.positions[id];
        if (p.state != OWED) revert WrongState();
        _retire(b, id, p.packId);
        b.idleValue += p.value;
        _toIdle(b, p.packId, p.value, p.backing);
    }

    function redeemInventory(Book storage b, uint256 packId) internal returns (uint256 value) {
        value = b.idleValueOf[packId];
        if (value == 0 || b.idleIndex[packId] == 0) revert MissingInventory();
        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.trackedValue -= value;
        --b.recipeCounts[value / UNIT];
        b.ordinaryShapeCount -= b.packShapeCount[packId];
        delete b.packShapeCount[packId];
        b.idleFunding -= b.idleQuote[packId];
        delete b.idleQuote[packId];
        _removeIdle(b, packId);
        clearRenewal(b, packId);
        emit InventoryUpdated(packId, 0);
    }

    function _removeIdle(Book storage b, uint256 packId) private {
        uint256 index = b.idleIndex[packId];
        if (index == 0) revert MissingInventory();
        uint256 last = b.idlePacks[b.idlePacks.length - 1];
        b.idlePacks[index - 1] = last;
        b.idleIndex[last] = index;
        b.idlePacks.pop();
        delete b.idleIndex[packId];
    }

    function clearRenewal(Book storage b, uint256 packId) internal {
        if (b.renewalEligible[packId]) {
            delete b.renewalEligible[packId];
            --b.renewalEligibleCount;
        }
    }

    function updateFeeDebt(Book storage b, uint256 id, uint256 debt) internal {
        Position storage p = b.positions[id];
        if (p.state != ACTIVE) revert WrongState();
        uint256 old = p.feeDebt;
        if (old == debt) return;
        if (debt < old) revert OutOfOrder();
        --b.countByDebt[old];
        ++b.countByDebt[debt];
        b.feeDebtSum = b.feeDebtSum - old + debt;
        p.feeDebt = debt;
        _emitPosition(b, id);
    }

    function pendingFees(Book storage b, uint256 witnessId, uint256 actualPending) internal view returns (uint256) {
        uint256 n = b.activeCount;
        if (n == 0) return 0;
        Position storage p = b.positions[witnessId];
        if (p.state != ACTIVE) revert BadWitness();
        uint256 d = p.feeDebt;
        if (actualPending == 0) {
            if (b.countByDebt[d] + b.countByDebt[d + 1] != n) revert BadWitness();
            return 0;
        }
        uint256 a = d + actualPending;
        return n * a + b.countByDebt[a + 1] - b.feeDebtSum;
    }

    function nav(Book storage b, uint256 freeEth, uint256 credit, uint256 witnessId, uint256 actualPending)
        internal view returns (uint256)
    {
        return freeEth + b.trackedValue + b.activeBacking + credit + pendingFees(b, witnessId, actualPending);
    }

    function prune(Book storage b, uint256 maxCount) internal returns (uint256 advanced) {
        uint256 head = b.allocationHead;
        while (advanced < maxCount && head < b.allocationQueue.length) {
            if (b.positions[b.allocationQueue[head]].state == ALLOCATED) break;
            delete b.allocationQueue[head];
            ++head;
            ++advanced;
        }
        b.allocationHead = head;
    }

    function oldestAllocation(Book storage b) internal view returns (uint256 id, uint64 at) {
        if (b.allocationHead == b.allocationQueue.length) return (0, 0);
        id = b.allocationQueue[b.allocationHead];
        Position storage p = b.positions[id];
        if (p.state != ALLOCATED) revert NeedsPrune();
        at = p.allocatedAt;
    }

    function _removeActive(Book storage b, Position storage p) internal {
        b.activeBacking -= p.backing;
        --b.activeCount;
        b.feeDebtSum -= p.feeDebt;
        --b.countByDebt[p.feeDebt];
    }

    function _retire(Book storage b, uint256 id, uint256 packId) private {
        b.positions[id].state = NONE;
        delete b.packToListing[packId];
        uint256 idx = b.openIndex[id] - 1;
        uint256 last = b.open[b.open.length - 1];
        b.open[idx] = last;
        b.openIndex[last] = idx + 1;
        b.open.pop();
        delete b.openIndex[id];
        _emitPosition(b, id);
    }

    function listing(IFWAV2 f, uint256 id) internal view returns (IFWAView.Listing memory) {
        return IFWAView(address(f)).listings(id);
    }

    function _validate(IFWAView.Listing memory l, IShapePacks packs, uint256 packId, uint256 backing) private view {
        if (l.depositor != address(this) || l.collection != address(packs)
            || l.tokenId != packId || l.value != backing) revert InvalidListing();
    }

    function admit(Book storage b, IFWAV2 f, IShapePacks packs, uint256 packId, uint256 backing)
        public returns (uint256 id)
    {
        // Backing identifies this listing's cash receipt: two open listings may never share it.
        if (b.idForBacking[backing] != 0) revert Duplicate();
        _rebaseUnexposed(b, f);
        uint256 active = f.activeListingCount();
        // FWA's private staging FIFO may activate foreign listings during admission.
        // Bound even a reverting attempt, and reject every incidental activation atomically.
        try f.listNFT{value: backing, gas: LIST_CALL_GAS}(address(packs), packId) returns (uint256 admitted) {
            id = admitted;
        } catch {
            revert InvalidListing();
        }
        IFWAView.Listing memory l = listing(f, id);
        if (l.status != LISTING_ACTIVE || f.activeListingCount() != active + 1 || f.fwairListing(id)) revert InvalidListing();
        _validate(l, packs, packId, backing);
        b.receipts[id].initialized = true;
        b.idForBacking[backing] = id;
        ++b.reservedCount;
        list(b, id, packId, backing, l.feeDebt);
    }

    function release(Book storage b, uint256 id, uint256 backing) private {
        if (b.idForBacking[backing] != id) revert InvalidListing();
        delete b.idForBacking[backing];
        --b.reservedCount;
        if (b.receipts[id].kind != 0) {
            --b.pendingPlusOne;
            emit ReceiptConsumed(id);
        }
        delete b.receipts[id];
    }

    function syncChanges(Params storage p, Budget storage budget, Book storage b, IFWAV2 f, IShapePacks packs,
        uint256[] calldata ids, uint256 checkpointMode, uint256 witnessId)
        external returns (uint256 gasQ, uint256 units)
    {
        bool distributionTail;
        (gasQ, units, distributionTail) = _syncChanges(p, b, f, packs, ids, checkpointMode, witnessId);
        if (gasQ != 0) gasQ = _fundSync(p, budget, b, f, ids, gasQ, units, distributionTail, witnessId);
    }

    function syncUnfunded(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs,
        uint256[] calldata ids, uint256 checkpointMode, uint256 witnessId)
        external returns (uint256 gasQ, uint256 units)
    {
        (gasQ, units,) = _syncChanges(p, b, f, packs, ids, checkpointMode, witnessId);
    }

    function _syncChanges(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs,
        uint256[] calldata ids, uint256 checkpointMode, uint256 witnessId)
        private returns (uint256 gasQ, uint256 units, bool distributionTail)
    {
        if (ids.length > MAX_TERMINALS) revert BadBatch();
        Work memory work;
        // No outstanding custody, identifiers or receipts means an unseen selection cannot be ours.
        bool unexposed = _unexposed(b);
        bool rebased;
        if (unexposed) {
            rebased = _rebaseUnexposed(b, f);
        } else {
            // A scan of the vault's own positions replaces the global journal whenever it costs no
            // more than the next journal batch (ScanLib.rebase).
            (rebased, work.scanned, work.own) = ScanLib.rebase(b, f, p.gasSchedule);
            if (!rebased) (work.processed, work.own) = _syncJournal(b, f, packs);
        }
        for (uint256 i; i < ids.length; ++i) if (_syncTerminal(b, f, packs, ids[i])) ++work.resolved;
        work.pruned = prune(b, MAX_PRUNES);
        if (work.processed + work.resolved + work.pruned == 0 && !rebased) revert Nothing();
        // Rebase is unpaid. Empty-vault head cleanup also cannot consume its bootstrap cash.
        if ((unexposed && b.trackedValue == 0) || work.processed + work.scanned + work.resolved + work.pruned == 0) {
            return (0, 0, false);
        }
        bool journalPaid = work.processed == MAX_JOURNAL || work.own + work.resolved != 0;
        bool requiredTail;
        uint256 tailBase = p.gasSchedule.requiredTail;
        if (!journalPaid && work.processed + work.scanned != 0 && checkpointMode != 0) {
            journalPaid = f.isPurchaseBlackout() && f.unsettledAcquisitionCount() == 0;
            if (journalPaid && checkpointMode == 2) {
                tailBase += p.gasSchedule.distributionProof;
                journalPaid = _distributionTail(p, b, f, witnessId,
                    tailBase + work.processed * p.gasSchedule.journal + work.scanned * p.gasSchedule.scan + work.pruned * p.gasSchedule.pruned);
            }
            requiredTail = journalPaid;
        }
        if (!journalPaid && work.own + work.resolved + work.pruned == 0) return (0, 0, false);
        // A scan is paid only when it applied an own selection or is the required checkpoint proof:
        // splitting a cycle's terminal work into later calls cannot earn a second scan.
        gasQ = (requiredTail ? tailBase : p.gasSchedule.sync) + (journalPaid ? work.processed * p.gasSchedule.journal : 0)
            + (work.own != 0 || requiredTail ? work.scanned * p.gasSchedule.scan : 0) + work.own * p.gasSchedule.selected
            + work.resolved * p.gasSchedule.synced + work.pruned * p.gasSchedule.pruned;
        units = work.resolved;
        distributionTail = requiredTail && checkpointMode == 2;
    }

    /// @dev Terminal proceeds arrive first. Only real paid work may sweep economical credit or
    ///      claim the first bounded fee prefix needed to fund its complete payment envelope.
    function _fundSync(Params storage p, Budget storage budget, Book storage b, IFWAV2 f,
        uint256[] calldata ids, uint256 gasQ, uint256 units, bool distributionTail, uint256 witnessId)
        private returns (uint256)
    {
        (uint256 routine,) = budgetNow(p, budget);
        uint256 cost = quote(p, gasQ, units, false);
        if (routine < cost) return gasQ;
        uint256 credit = f.feeCredit(address(this));
        uint256 combined = quote(p, gasQ + p.gasSchedule.credit, units, false);
        if (credit != 0 && combined <= routine && (combined - cost) * BPS <= credit * p.keeperShareBps
            && (!distributionTail || _distributionTail(p, b, f, witnessId, gasQ + p.gasSchedule.credit))) {
            _withdrawCredit(b, f);
            gasQ += p.gasSchedule.credit;
            cost = combined;
            credit = 0;
        }
        uint256 free = ISyncVault(address(this)).keeperCash();
        if (free >= cost) return gasQ;
        uint256 deficit = ISyncVault(address(this)).fundingDeficit(false);
        uint256[] memory claims = new uint256[](ids.length);
        uint256 count;
        uint256 fees = credit;
        for (uint256 i; i < ids.length; ++i) {
            uint256 id = ids[i];
            if (b.positions[id].state != ACTIVE || listing(f, id).status != LISTING_ACTIVE) continue;
            bool duplicate;
            for (uint256 j; j < count; ++j) if (claims[j] == id) duplicate = true;
            if (duplicate) continue;
            uint256 pending = f.pendingFees(id);
            if (pending == 0) continue;
            claims[count++] = id;
            fees += pending;
            uint256 fundedGas = gasQ + p.gasSchedule.fund + count * p.gasSchedule.harvested + (credit != 0 ? p.gasSchedule.credit : 0);
            combined = quote(p, fundedGas, units, false);
            if (free + fees < deficit + combined) continue;
            // Once enough cash was found, extra IDs cannot increase the claim or its payment.
            if (combined > routine || (combined - cost) * BPS > fees * p.keeperShareBps
                || (distributionTail && !_distributionTail(p, b, f, witnessId, fundedGas))) return gasQ;
            assembly ("memory-safe") { mstore(claims, count) }
            uint256 before = address(this).balance;
            if (!_claimFees(b, f, claims)) return gasQ;
            if (credit != 0) _withdrawCredit(b, f);
            uint256 received = address(this).balance - before;
            if (ISyncVault(address(this)).keeperCash() < combined || (combined - cost) * BPS > received * p.keeperShareBps) revert Payment();
            return fundedGas;
        }
        return gasQ;
    }

    function _distributionTail(Params storage p, Book storage b, IFWAV2 f, uint256 witnessId, uint256 gasQ)
        private view returns (bool)
    {
        return ScanLib.distributionTail(p, b, f, witnessId, gasQ);
    }

    function _unexposed(Book storage b) private view returns (bool) {
        return b.open.length == 0 && b.reservedCount == 0 && b.activeCount == 0
            && b.activeBacking == 0 && b.allocatedValue == 0 && b.pendingPlusOne == 1;
    }

    function _rebaseUnexposed(Book storage b, IFWAV2 f) private returns (bool advanced) {
        if (!_unexposed(b)) return false;
        uint64 end = f.nextSequenceToProcess();
        if (b.acquisitionCursor < end) {
            b.acquisitionCursor = end;
            emit JournalProgress(end, 0, 0);
            return true;
        }
    }

    function _syncJournal(Book storage b, IFWAV2 f, IShapePacks packs)
        private returns (uint256 processed, uint256 own)
    {
        uint64 cursor = b.acquisitionCursor;
        uint64 end = f.nextSequenceToProcess();
        while (cursor < end && processed < MAX_JOURNAL) {
            uint256 requestId = f.requestIdAtSequence(cursor);
            if (requestId == 0) revert InvalidJournal();
            IFWAV2.Acquisition memory a = f.acquisitions(requestId);
            if (a.status == 2) {
                if (a.listingId == 0) revert InvalidJournal();
                if (b.positions[a.listingId].value != 0) {
                    if (own == MAX_SELECTIONS) break;
                    Position memory p = b.positions[a.listingId];
                    if (p.state != ACTIVE) revert InvalidJournal();
                    IFWAView.Listing memory l = listing(f, a.listingId);
                    _validate(l, packs, p.packId, p.backing);
                    if (l.status != LISTING_ALLOCATED && l.status != LISTING_SETTLED) revert InvalidJournal();
                    select(b, a.listingId, l.allocatedAt);
                    ++own;
                }
            } else if (a.status != 3 && a.status != 4) revert InvalidJournal();
            ++cursor;
            ++processed;
        }
        b.acquisitionCursor = cursor;
        if (processed != 0) emit JournalProgress(cursor, processed, own);
    }

    function _syncTerminal(Book storage b, IFWAV2 f, IShapePacks packs, uint256 id) private returns (bool) {
        Position memory p = b.positions[id];
        if (p.state == NONE) return false;
        IFWAView.Listing memory l = listing(f, id);
        _validate(l, packs, p.packId, p.backing);
        if (p.state == OWED) {
            if (f.stuckNFTRecipient(id) == address(this)) {
                (bool ok,) = address(f).call(abi.encodeCall(IFWAV2.recoverStuckNFT, (id)));
                if (!ok) return false;
            }
            if (!owns(packs, p.packId)) return false;
            claimReturned(b, id);
            return true;
        }
        if (l.status == LISTING_ALLOCATED) {
            if (p.state != ALLOCATED || block.timestamp < uint256(l.allocatedAt) + f.settlementWindow()) return false;
            // Expiry resolution must still identify its genuine keep payment.
            if (p.backing * (BPS - f.ownerSettlementFeeBps()) / BPS >= p.value) f.depositorReclaimBacking(id);
            else f.depositorReclaimNFT(id);
            l = listing(f, id);
        }
        if (l.status == LISTING_ACTIVE) return false;
        // FWA changes a listing's status and pays its depositor in the same transaction
        // (forceSafeTransferETH, which force-sends when receive() fails), so FWA's record alone
        // proves the outcome and its cash. The receipt only gates checkpoints until this sync;
        // a payment whose receipt was never recorded resolves here the same way.
        bool owned = owns(packs, p.packId);
        bool returned = owned || f.stuckNFTRecipient(id) == address(this);
        if (l.status == LISTING_SETTLED) {
            if (p.state == ACTIVE) return false;
            if (p.state != ALLOCATED) revert InvalidListing();
            // Keep, relist, expiry or default: B (1 - s) paid, the pack went to the purchaser.
            // A bid returns the pack to the depositor (or owes it) and pays nothing. A kept pack
            // that came back (a gift, perhaps with extra Shapes) joins inventory at its actual value.
            if (b.receipts[id].kind == 1 || !returned) {
                release(b, id, p.backing);
                keep(b, id);
                if (b.renewalEnabled) ++b.keptReplacements;
                if (owned) addInventory(b, p.packId, packs.valueOf(p.packId));
                return true;
            }
        } else if (l.status == LISTING_WITHDRAWN) {
            // Only a kick withdraws a listing outside this account's own calls: B refunded, pack returned.
            if (p.state != ACTIVE || !returned) revert InvalidListing();
        } else return false;
        if (b.renewalEnabled && l.status == LISTING_SETTLED && !b.renewalEligible[p.packId]) {
            b.renewalEligible[p.packId] = true;
            ++b.renewalEligibleCount;
        }
        release(b, id, p.backing);
        returnPack(b, id, owned);
        return true;
    }

    function withdraw(Book storage b, IFWAV2 f, IShapePacks packs, uint256 id) external {
        Position memory p = b.positions[id];
        if (p.state != ACTIVE) revert WrongState();
        b.controlled = true;
        f.withdrawListing(id);
        b.controlled = false;
        bool owned = owns(packs, p.packId);
        if (!owned && f.stuckNFTRecipient(id) != address(this)) revert InvalidListing();
        release(b, id, p.backing);
        returnPack(b, id, owned);
    }

    function harvest(Book storage b, IFWAV2 f, uint256[] calldata ids) external {
        if (ids.length > MAX_BATCH) revert BadBatch();
        for (uint256 i; i < ids.length; ++i) {
            if (i != 0 && ids[i] <= ids[i - 1]) revert BadBatch();
        }
        _claimFees(b, f, ids);
        if (f.feeCredit(address(this)) != 0) _withdrawCredit(b, f);
    }

    function claimFundingFees(Book storage b, IFWAV2 f, uint256[] memory ids) external returns (bool) {
        return _claimFees(b, f, ids);
    }

    function _claimFees(Book storage b, IFWAV2 f, uint256[] memory ids) private returns (bool claimed) {
        b.controlled = true;
        if (ids.length != 0) {
            try f.claimListingFees(ids) {
                for (uint256 i; i < ids.length; ++i) {
                    IFWAView.Listing memory l = listing(f, ids[i]);
                    if (b.positions[ids[i]].state == ACTIVE && l.status == LISTING_ACTIVE) updateFeeDebt(b, ids[i], l.feeDebt);
                }
                claimed = true;
            } catch {}
        }
        b.controlled = false;
    }

    function harvestCredit(Book storage b, IFWAV2 f) external {
        if (f.feeCredit(address(this)) != 0) _withdrawCredit(b, f);
    }

    function withdrawCredit(Book storage b, IFWAV2 f) external { _withdrawCredit(b, f); }

    function _withdrawCredit(Book storage b, IFWAV2 f) private {
        b.controlled = true;
        f.withdrawEarnings();
        b.controlled = false;
    }

    function accountedNav(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        external view returns (uint256 value)
    {
        (value,) = _accountedNav(p, b, f, packs, freeEth, witnessId);
    }

    /// @return value NAV; gasQ the checkpoint's quoted gas, including the allocation proof it read.
    function checkpointNav(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        external returns (uint256 value, uint256 gasQ)
    {
        _rebaseUnexposed(b, f);
        return _accountedNav(p, b, f, packs, freeEth, witnessId);
    }

    function _accountedNav(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        private view returns (uint256, uint256 gasQ)
    {
        if (b.acquisitionCursor != f.nextSequenceToProcess()) revert CatchUpFirst();
        if (b.pendingPlusOne != 1) revert PendingReceipts();
        (uint256 entries, uint256 reads) = ScanLib.requireAllocatedCurrent(b, f, packs);
        gasQ = p.gasSchedule.checkpoint + entries * p.gasSchedule.allocationEntry + reads * p.gasSchedule.allocationRead;
        uint256 pending;
        if (b.activeCount != 0) {
            Position memory pos = b.positions[witnessId];
            IFWAView.Listing memory l = listing(f, witnessId);
            if (pos.state != ACTIVE || l.status != LISTING_ACTIVE || pos.feeDebt != l.feeDebt) revert BadWitness();
            _validate(l, packs, pos.packId, pos.backing);
            pending = f.pendingFees(witnessId);
        }
        return (nav(b, freeEth, f.feeCredit(address(this)), witnessId, pending), gasQ);
    }

    function validateBacking(Params storage p, Book storage b, IFWAV2 f, address packs,
        uint256 units, uint256 backing, uint256 mintFee, bool newlyBuilt, uint256 retiredShapes) public view
    {
        _validateBacking(p, b, _backingTerms(p, f, packs, units, mintFee, retiredShapes), backing, newlyBuilt);
    }

    function _validateBacking(Params storage p, Book storage b, BackingTerms memory t,
        uint256 backing, bool newlyBuilt) private view
    {
        if (!t.ok || backing == 0 || backing > type(uint128).max || backing % BPS != 0
            || b.idForBacking[backing] != 0) revert InvalidBacking();
        uint256 delta = backing > t.desired ? backing - t.desired : t.desired - backing;
        if (delta > (b.reservedCount + 1) * BPS) revert InvalidBacking();
        if (backing < t.floor || (t.cap != type(uint256).max && backing > t.cap * (BPS - p.bufferBps) / BPS)
            || !_profitable(t, backing, newlyBuilt)) revert InvalidBacking();
    }

    /// @notice Mint `count` packs of `units` straight into ShapePacks (one paid primary mint per
    ///         Shape, no split) and list each at its validated backing proposal. `available` is the
    ///         account's spendable ETH; idle packs keep their reserved backing (`idleFunding`).
    function buildAndList(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs, IShapes shapes,
        uint256 units, uint256[] calldata backingProposals, uint256 available) external
    {
        uint256 count = backingProposals.length;
        if (shapes.mintFee() > p.acceptedMintFee) revert MintFeeNotAccepted();
        if (count == 0 || count > MAX_BUILD_BATCH || units < MIN_PACK_UNITS || units > MAX_PACK_UNITS
            || (p.packUnitsMask >> units) & 1 == 0) revert BadBatch();
        (uint32[] memory counts, uint256 n) = makeup(units);
        uint256 fee = shapes.mintFee();
        uint256 price = units * UNIT + n * fee;
        BackingTerms memory terms = _backingTerms(p, f, address(packs), units, fee, n);
        uint256 need = count * price;
        for (uint256 i; i < count; ++i) need += backingProposals[i];
        uint256 compensation = quote(p, uint256(p.gasSchedule.build) + count * (buildGas(p, n) + p.gasSchedule.listed), 2 * count, false);
        if (available < need + compensation) revert InsufficientBacking();
        uint256[] memory none = new uint256[](0);
        for (uint256 i; i < count; ++i) {
            // Validated one at a time, as in `list`: each admission widens the identifier interval.
            _validateBacking(p, b, terms, backingProposals[i], true);
            uint256 packId = packs.createPack{value: price}(none, counts);
            // ShapePacks records exactly the minted backing; a different value is not our pack.
            if (packs.valueOf(packId) != units * UNIT) revert MissingInventory();
            emit PrimaryMinted(1, n, units * UNIT, n * fee);
            addInventory(b, packId, units * UNIT);
            b.ordinaryShapeCount = b.ordinaryShapeCount - b.packShapeCount[packId] + n;
            b.packShapeCount[packId] = n;
            admit(b, f, packs, packId, backingProposals[i]);
        }
    }

    /// @dev An extended gift may contain arbitrarily many Shapes. Never enumerate its contents.
    function recoverInventory(Params storage p, Book storage b, IShapePacks packs, IShapes shapes) external returns (uint256 gasQ) {
        return ScanLib.recoverInventory(p, b, packs, shapes);
    }
}
