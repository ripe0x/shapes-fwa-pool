// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {IKeeperPolicy} from "./KeeperPolicy.sol";
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

interface ISyncVault {
    function accountedNav(uint256 witnessId) external view returns (uint256);
    function freeEth() external view returns (uint256);
    function totalShares() external view returns (uint256);
    function highWaterMark() external view returns (uint256);
}

/// @notice Linked library for PackVault: the live FWA economics read. Split out only to keep
///         PackVault under EIP-170; it runs in the vault's context and holds no state.
library VaultLib {
    uint256 internal constant BPS = 10_000;
    uint256 internal constant DEAD_SHARES = 1e15;
    uint256 internal constant MIN_DISTRIBUTION = 0.01 ether;

    /// @notice PackVault's governed parameters (moved here so library code can read them by
    ///         storage pointer; EIP-170 size).
    struct Params {
        uint16 minEdgeBps; // require k >= 1 + minEdge
        uint16 bufferBps; // list at cap x (1 - buffer), so a small ask cut does not trigger kicks
        uint16 distributionBps; // share of new gains above the high-water mark paid out
        uint16 payMarkupBps; // envelope markup on the quoted gas of routine work (V1 pays none)
        uint16 keeperShareBps; // optional calls are paid only if pay <= this share of value realized
        uint16 allocatedBoundBps; // checkpoint skips when Allocated value exceeds this share of NAV
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
    }


    uint256 internal constant UNIT = 0.01 ether;

    // ---------------------------------------------------------------- bounds and quotes

    uint256 internal constant MAX_WORK_FEE = 0.00005 ether; // per unit of work (D55, D56)
    uint256 internal constant MAX_MIN_EDGE_BPS = 1_000;
    uint256 internal constant MAX_BUFFER_BPS = 2_000;
    uint256 internal constant MAX_GAS_CEILING = 50 gwei;
    uint256 internal constant MAX_DISTRIBUTION_BPS = 5_000;
    uint256 internal constant MAX_PAY_MARKUP_BPS = 1_000; // routine work only (D56, D57)
    uint256 internal constant MAX_KEEPER_SHARE_BPS = 5_000;
    uint256 internal constant MAX_ALLOCATED_BOUND_BPS = 1_000;
    uint256 internal constant MAX_ROUTINE_CAP = 0.3 ether;
    uint256 internal constant MAX_ROUTINE_RATE = 0.01 ether;
    uint256 internal constant MAX_ESSENTIAL_CAP = 0.1 ether;
    uint256 internal constant MAX_ESSENTIAL_RATE = 0.005 ether;
    uint256 internal constant MAX_PACK_UNITS = 30; // a first build from empty inventory fits EIP-7825 (audit E11)
    uint256 internal constant MIN_PACK_UNITS = 3;
    uint256 internal constant SHAPES_PER_MINT = 10;

    /// Quoted gas schedule: a base per call plus a marginal amount per completed unit, from billed
    /// gas on real receipts (keeper/measure_gas.py, docs/GAS.md). Each base sits at most at the
    /// measured fixed cost of a call divided by 1.1, so splitting a job never earns a second base.
    // One checkpoint per interval cannot be split, so it is quoted at measured billed gas.
    uint256 internal constant Q_CHECKPOINT = 360_000;
    uint256 internal constant Q_RESTOCK = 280_000;
    uint256 internal constant Q_PACK = 325_000; // createPack at the three-Shape reference size
    uint256 internal constant Q_PACK_UNIT = 35_000; // each additional packed Shape
    uint256 internal constant Q_MINT = 2_200_000; // one 0.1 ETH mint split ten ways (2.10M-2.26M by block)
    uint256 internal constant Q_LIST = 280_000;
    uint256 internal constant Q_LISTED = 825_000;
    uint256 internal constant Q_SYNC = 85_000;
    uint256 internal constant Q_REQUIRED_TAIL = 85_000;
    uint256 internal constant Q_JOURNAL = 30_000; // each completed global acquisition
    uint256 internal constant Q_SELECTED = 160_000; // own selection bookkeeping
    uint256 internal constant Q_SYNCED = 120_000; // terminal or recovered return
    uint256 internal constant Q_PRUNED = 45_000; // resolved allocation head
    uint256 internal constant Q_POSITION_SYNC = Q_JOURNAL + Q_SELECTED + Q_SYNCED + Q_PRUNED;
    uint256 internal constant Q_UNLIST = 340_000;
    uint256 internal constant Q_UNLISTED = 285_000;
    uint256 internal constant Q_LIQUIDATE = 75_000;
    uint256 internal constant Q_LIQ_PACK = 80_000; // fixed work per ordinary pack
    uint256 internal constant Q_REDEEM_SHAPE = 35_000;
    uint256 internal constant Q_RECOVERY_BASE = 100_000;
    uint256 internal constant Q_RECOVERY_SHAPE = 35_000;
    uint256 internal constant Q_RECOVERY_UNSEAL = 70_000;
    uint256 internal constant Q_LIQ_SHAPE = 65_000;
    uint256 internal constant Q_HARVEST = 125_000;
    uint256 internal constant Q_HARVESTED = 80_000; // per listing with fees claimed
    /// A 3-unit position (0.03 ETH pack + ~0.0363 backing): what request charges are scaled by.
    uint256 internal constant POSITION_VALUE = 0.0663 ether;

    uint256 internal constant MAX_BATCH = 16;
    uint256 internal constant MAX_JOURNAL = 128;
    uint256 internal constant MAX_SELECTIONS = 16;
    uint256 internal constant MAX_TERMINALS = 16;
    uint256 internal constant MAX_PRUNES = 16;
    uint256 internal constant MAX_LIST_BATCH = 8;
    uint256 internal constant LIST_CALL_GAS = 1_200_000;
    uint256 internal constant MAX_RESTOCK_UNITS = 30;
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
    }

    struct Work { uint256 processed; uint256 own; uint256 resolved; uint256 pruned; }

    struct BackingTerms {
        uint256 k;
        uint256 desired;
        uint256 cap;
        uint256 settlementFee;
        uint256 value;
        uint256 floor;
        uint256 cycleCost;
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
        uint256[] allocationQueue;
        uint256 allocationHead;
        uint64 lastAllocatedAt;
        uint256[] open;
        mapping(uint256 => uint256) openIndex;
        uint256[] idlePacks;
        uint256[] recoveryPacks;
        mapping(uint256 => bool) recoveryUnsealed;
        uint256[] looseShapes;
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
    error MissingReceipt();
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
        uint256 owed = M.mulDivUp(locked, nav, supply);
        frac = owed <= liquid ? 1e36 : M.mulDiv(liquid > 2 ? liquid - 2 : 0, 1e36, owed);
        filled = M.mulDiv(locked, frac, 1e36);
        unit = M.mulDiv(frac, nav, supply);
        paid = M.mulDivUp(locked, unit, 1e36);
    }

    error OutOfBounds();

    /// Gas a keeper policy's quote may use: enough for arithmetic and reads, not for griefing.
    uint256 internal constant POLICY_GAS = 50_000;
    uint256 internal constant ORACLE_GAS = 100_000; // floor oracle read; FWA's own oracle uses far less

    /// @notice The active keeper policy's proposed pay for verified work, from a bounded-gas
    ///         staticcall. A revert, out-of-gas or short answer is zero; only the first word of
    ///         the answer is read, so a policy cannot grief with huge return data.
    function offer(
        address policy,
        uint256 op,
        uint256 units,
        uint256 gasQ,
        bool essential,
        uint256 gasCeiling,
        uint256 maxTip,
        uint256 workFee
    ) public view returns (uint256 o) {
        bytes memory c = abi.encodeCall(IKeeperPolicy.quote, (op, units, gasQ, essential, gasCeiling, maxTip, workFee));
        assembly ("memory-safe") {
            // Yul evaluates arguments right to left: check returndatasize only after the call.
            let ok := staticcall(POLICY_GAS, policy, add(c, 32), mload(c), 0, 32)
            if and(ok, gt(returndatasize(), 31)) { o := mload(0) }
        }
    }

    /// @notice A keeper policy must be a contract answering `policyVersion()` with a nonzero value.
    function checkPolicy(address policy) external view {
        if (policy.code.length == 0) revert OutOfBounds();
        try IKeeperPolicy(policy).policyVersion() returns (uint256 v) {
            if (v == 0) revert OutOfBounds();
        } catch {
            revert OutOfBounds();
        }
    }

    // ---------------------------------------------------------------- keeper pay (D56, D57)

    /// Keeper budgets: levels as of `at`; each refills at its daily rate up to its cap.
    struct Budget {
        uint128 routine;
        uint128 essential;
        uint256 at;
    }

    event KeeperPaid(address indexed keeper, uint256 amount);

    error Payment();

    /// @notice The vault's envelope for work: quoted gas at basefee + maxTip, capped at the
    ///         ceiling, markup on routine work, plus work fees. The most this work may ever pay.
    function quote(Params storage p, uint256 gasQ, uint256 units, bool essential) public view returns (uint256 q) {
        q = gasQ * M.min(block.basefee + p.maxTip, essential ? p.essentialCeiling : p.gasCeiling);
        if (!essential) q = q * (BPS + p.payMarkupBps) / BPS;
        q += units * p.workFee;
    }

    function budgetNow(Params storage p, Budget storage b) public view returns (uint256 r, uint256 e) {
        uint256 dt = block.timestamp - b.at;
        r = M.min(p.routineCap, b.routine + dt * p.routineRate / 1 days);
        e = M.min(p.essentialCap, b.essential + dt * p.essentialRate / 1 days);
    }

    /// @notice Accrue both budgets to now; caps lowered since only clamp, never refill.
    function syncBudget(Params storage p, Budget storage b) external {
        (uint256 r, uint256 e) = budgetNow(p, b);
        (b.routine, b.essential, b.at) = (uint128(r), uint128(e), block.timestamp);
    }

    /// @notice Pay the caller for verified work: the least of the policy's offer, the vault's
    ///         envelope for that work, `cap` (a funding source), free ETH and the budget. Below
    ///         `minPay` the whole call reverts; with 0 the work is done for whatever is paid.
    function pay(
        Params storage p,
        Budget storage b,
        address policy,
        uint256 op,
        uint256 gasQ,
        uint256 units,
        bool essential,
        uint256 minPay,
        uint256 cap,
        uint256 free
    ) external returns (uint256 amount) {
        (uint256 r, uint256 e) = budgetNow(p, b);
        // A finite `cap` is the request-charge pool: requesters already paid for this work, so it
        // is bounded by the pool, not by the holders' budgets.
        bool charged = cap != type(uint256).max;
        if (charged) (r, e) = (type(uint256).max, type(uint256).max);
        uint256 o =
            offer(policy, op, units, gasQ, essential, essential ? p.essentialCeiling : p.gasCeiling, p.maxTip, p.workFee);
        amount = M.min(M.min(o, M.min(quote(p, gasQ, units, essential), cap)), M.min(free, essential ? e : r));
        if (amount < minPay) revert Payment();
        if (!charged) {
            (b.routine, b.essential, b.at) =
                (uint128(essential ? r : r - amount), uint128(essential ? e - amount : e), block.timestamp);
        }
        if (amount == 0) return 0;
        (bool ok,) = msg.sender.call{value: amount}("");
        if (!ok) revert Payment();
        emit KeeperPaid(msg.sender, amount);
    }

    // ---------------------------------------------------------------- parameters and charges

    /// @notice Bytecode bounds on every parameter.
    function checkBounds(Params storage p) external view {
        if (
            p.minEdgeBps > MAX_MIN_EDGE_BPS || p.bufferBps > MAX_BUFFER_BPS || p.distributionBps > MAX_DISTRIBUTION_BPS
                || p.payMarkupBps > MAX_PAY_MARKUP_BPS || p.workFee > MAX_WORK_FEE || p.keeperShareBps > MAX_KEEPER_SHARE_BPS
                || p.allocatedBoundBps > MAX_ALLOCATED_BOUND_BPS
                || p.gasCeiling > MAX_GAS_CEILING || p.essentialCeiling > MAX_GAS_CEILING || p.maxTip > p.gasCeiling
                || p.routineCap > MAX_ROUTINE_CAP || p.routineRate > MAX_ROUTINE_RATE || p.essentialCap > MAX_ESSENTIAL_CAP
                || p.essentialRate > MAX_ESSENTIAL_RATE
                || p.packUnitsMask >> (MAX_PACK_UNITS + 1) != 0 || p.packUnitsMask & ((1 << MIN_PACK_UNITS) - 1) != 0
        ) revert OutOfBounds();
    }

    function packGas(uint256 units) internal pure returns (uint256) {
        return Q_PACK + (units > MIN_PACK_UNITS ? units - MIN_PACK_UNITS : 0) * Q_PACK_UNIT;
    }

    function cycleNet(Params storage p, uint256 k1e18, uint256 backing) external view returns (uint256) {
        return _cycleNet(p, k1e18, backing);
    }

    /// @notice A request's checkpoint charge: one checkpoint at its envelope, at cost plus one unit.
    function requestCharge(Params storage p) external view returns (uint256) {
        return quote(p, Q_CHECKPOINT, 1, true);
    }

    /// @notice Deployment charge per POSITION_VALUE deposited: building and listing one position
    ///         at its envelope now plus its Shapes mint fee share, and never less than the most a
    ///         builder can net over its own gas (markup at the ceiling, the tip it is repaid but
    ///         need not pay, and the two work fees).
    function deployCharge(Params storage p, uint256 mintFee) external view returns (uint256) {
        uint256 g = Q_PACK + Q_MINT * MIN_PACK_UNITS / SHAPES_PER_MINT + Q_LISTED;
        return M.max(quote(p, g, 2, false) + mintFee * MIN_PACK_UNITS / SHAPES_PER_MINT,
            g * (p.gasCeiling * p.payMarkupBps + p.maxTip * (BPS + p.payMarkupBps)) / BPS + 2 * p.workFee);
    }

    /// @notice Unwind charge per POSITION_VALUE redeemed: unlisting and liquidating one position.
    function unwindCharge(Params storage p) external view returns (uint256) {
        // No essential budget means exit work is unpaid (withdrawers run it): nothing to charge.
        if (p.essentialCap == 0) return 0;
        return quote(p, Q_UNLISTED + Q_LIQ_PACK + MIN_PACK_UNITS * Q_REDEEM_SHAPE, 2, true);
    }


    /// @notice Live edge for a pack of `units` x 0.01 ETH: k, the backing a new listing would post
    ///         (cap less the buffer, zero when the gate fails) and whether the gate passes.
    /// @notice Backing for a new listing and whether to list (D62). Every position earns the same
    ///         per acquisition whatever its backing (FWA splits fees evenly and selects by 1/B), so
    ///         backing only moves capital per position and gas per cycle:
    ///         - floor: P / d, so a purchaser prefers FWA's bid payout d x B to keeping a pack worth P
    ///           and the pack keeps cycling (a keep forces a rebuild), and P / (1 - s), so a keep
    ///           never loses;
    ///         - `build`: enough that one bid cycle repays building a pack at today's price (the
    ///           build gate), so new packs stay possible as gas rises;
    ///         - gas-optimal (c + sqrt(c^2 + a c P)) / a, with a = k - 1 and c a cycle's pay at the
    ///           routine ceiling: above the floor only when gas is high;
    ///         capped at FWA's oracle cap less the buffer unless FWA exempts the collection.
    function edge(Params storage p, IFWAV2 f, address packs, uint256 units, uint256 build)
        public
        view
        returns (uint256 k1e18, uint256 backing, bool ok)
    {
        BackingTerms memory t = _backingTerms(p, f, packs, units, build);
        return (t.k, t.desired, t.ok);
    }

    function _backingTerms(Params storage p, IFWAV2 f, address packs, uint256 units, uint256 build)
        private view returns (BackingTerms memory t)
    {
        (t.k, t.cap, t.settlementFee) = economics(f, packs);
        t.value = units * UNIT;
        uint256 floor = M.max(M.divUp(t.value * BPS, BPS - t.settlementFee),
            M.divUp(t.value * BPS, f.settlementDiscountBps()));
        t.desired = floor;
        if (t.k > 1e18) {
            t.cycleCost = quote(p, Q_POSITION_SYNC + Q_LISTED + Q_HARVESTED, 2, false);
            uint256 a = t.k - 1e18;
            uint256 c = (Q_POSITION_SYNC + Q_LISTED + Q_HARVESTED) * p.gasCeiling * (BPS + p.payMarkupBps) / BPS + 2 * p.workFee;
            t.desired = M.max(t.desired, (c + M.sqrt(c * c + a * c / 1e18 * t.value)) * 1e18 / a);
            t.desired = M.max(t.desired, M.divUp((build + t.cycleCost) * 1e18, a));
        }
        if (t.cap != type(uint256).max) t.desired = M.min(t.desired, t.cap * (BPS - p.bufferBps) / BPS);
        // Bid outcome B (k - 1) > 0 given k >= 1 + edge; spending callers also require it to clear
        // the keeper pay it causes (cycleNet). Keep outcome B (k - s) >= P holds from the floor.
        t.ok = t.cap != 0 && t.k >= 1e18 + uint256(p.minEdgeBps) * 1e14 && t.k > t.settlementFee * 1e14
            && t.desired >= floor && t.desired * (t.k - t.settlementFee * 1e14) >= t.value * 1e18;
        if (!t.ok) t.desired = 0;
        t.floor = M.max(floor, t.value + t.value / 19 + (t.value % 19 == 0 ? 0 : 1));
    }


    /// @notice Revert before the work when `minPay` already exceeds what could be paid.
    function precheck(Params storage p, Budget storage b, uint256 minPay, bool essential, uint256 free)
        external
        view
    {
        (uint256 r, uint256 e) = budgetNow(p, b);
        if (minPay > M.min(free, essential ? e : r)) revert Payment();
    }

    function owns(IShapePacks packs, uint256 packId) public view returns (bool) {
        try packs.ownerOf(packId) returns (address o) {
            return o == address(this);
        } catch {
            return false;
        }
    }

    /// @notice Live k (1e18 scale) and FWA's backing cap for `packs` (zero when FWA would refuse
    ///         a listing). k = (1 + surcharge)(1 - protocolCut)(1 - crownShare).
    function economics(IFWAV2 f, address packs) public view returns (uint256 k1e18, uint256 cap, uint256 s) {
        s = f.ownerSettlementFeeBps();
        uint256 w = f.totalWeight();
        if (w == 0) return (0, 0, s);
        // FWA exposes no getter for its surcharge: acquisitionFee = (wbt / w) (1 + surcharge).
        uint256 ev = f.weightedBackingTotal() / w;
        uint256 oneSur = f.acquisitionFee() * 1e18 / ev; // 1e18 x (1 + surcharge), floors
        k1e18 = oneSur * (BPS - f.ownerAcquisitionFeeBps()) / BPS * (BPS - f.topListingShareBps()) / BPS;
        if (!f.canDeposit(packs)) return (k1e18, 0, s);
        // FWA exempts the collection from its floor cap: no cap applies (D62).
        if (f.oracleExemptCollections(packs)) return (k1e18, type(uint256).max, s);
        // The oracle ask plus premium when the quote passes FWA's own validity rules.
        // A failing or malformed oracle means no cap (nothing new lists); it must not block
        // unlisting, wind-down or redemptions. FWA's owner can repoint the oracle to any contract,
        // so the read is a raw staticcall: a revert or short return data both mean "no cap".
        // Bounded gas and a manual four-word read: a gas-burning oracle or one returning words that
        // do not fit their types (which would make abi.decode revert) also means "no cap" (audit S1).
        address o = f.floorOracle();
        bytes memory c = abi.encodeCall(IFloorOracle.getFloorRange, (packs));
        bool ok;
        uint256 bid;
        uint256 ask;
        uint256 observedAt;
        uint256 periodUsed;
        assembly ("memory-safe") {
            let m := mload(0x40) // scratch past the free pointer; not kept
            ok := staticcall(ORACLE_GAS, o, add(c, 32), mload(c), m, 128)
            if lt(returndatasize(), 128) { ok := 0 }
            bid := mload(m)
            ask := mload(add(m, 32))
            observedAt := mload(add(m, 64))
            periodUsed := mload(add(m, 96))
        }
        if (!ok || observedAt > type(uint48).max || periodUsed > type(uint48).max) return (k1e18, 0, s);
        if (bid == 0 || bid >= ask || observedAt == 0 || observedAt > block.timestamp) return (k1e18, 0, s);
        if (block.timestamp - observedAt > f.maxOracleAge()) return (k1e18, 0, s);
        if (periodUsed < f.minOracleChallengePeriod()) return (k1e18, 0, s);
        cap = ask * (BPS + f.oracleCeilingPremiumBps()) / BPS;
    }

    function _emitPosition(Book storage b, uint256 id) private {
        Position storage p = b.positions[id];
        emit PositionUpdated(id, p.packId, p.value, p.backing, p.feeDebt, p.allocatedAt, p.state);
    }

    function addInventory(Book storage b, uint256 packId, uint256 value) internal {
        addInventory(b, packId, value, 0);
    }

    function addInventory(Book storage b, uint256 packId, uint256 value, uint256 backingQuote) internal {
        if (value == 0 || b.idleValueOf[packId] != 0 || b.packToListing[packId] != 0) revert Duplicate();
        b.trackedValue += value;
        b.idleValue += value;
        _toIdle(b, packId, value, backingQuote);
    }

    function _toIdle(Book storage b, uint256 packId, uint256 value, uint256 backingQuote) private {
        if (b.idleValueOf[packId] != 0) revert Duplicate();
        b.idleValueOf[packId] = value;
        if (value > MAX_PACK_UNITS * UNIT) {
            b.recoveryPacks.push(packId);
            emit RecoveryUpdated(packId, value, false);
        } else {
            b.idlePacks.push(packId);
            emit InventoryUpdated(packId, value);
        }
        b.idleQuote[packId] = backingQuote;
        b.idleFunding += backingQuote;
    }

    function list(Book storage b, uint256 id, uint256 packId, uint256 backing, uint256 debt) internal {
        if (id == 0 || b.positions[id].value != 0 || b.packToListing[packId] != 0) revert Duplicate();
        uint256 value = b.idleValueOf[packId];
        if (value == 0) revert MissingInventory();
        if (backing < value + value / 19 + (value % 19 == 0 ? 0 : 1)) revert InsufficientBacking();
        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.idleFunding -= b.idleQuote[packId];
        delete b.idleQuote[packId];
        if (b.idlePacks[b.idlePacks.length - 1] != packId) revert MissingInventory();
        b.idlePacks.pop();
        emit InventoryUpdated(packId, 0);
        b.positions[id] = Position(packId, value, backing, debt, 0, ACTIVE);
        b.packToListing[packId] = id;
        b.open.push(id);
        b.openIndex[id] = b.open.length;
        b.activeBacking += backing;
        ++b.activeCount;
        b.feeDebtSum += debt;
        ++b.countByDebt[debt];
        _emitPosition(b, id);
    }

    function select(Book storage b, uint256 id, uint64 at) internal {
        Position storage p = b.positions[id];
        if (p.state != ACTIVE) revert WrongState();
        if (at < b.lastAllocatedAt) revert OutOfOrder();
        _removeActive(b, p);
        p.state = ALLOCATED;
        p.allocatedAt = at;
        b.lastAllocatedAt = at;
        b.allocatedValue += p.value;
        b.allocationQueue.push(id);
        _emitPosition(b, id);
    }

    function keep(Book storage b, uint256 id) internal returns (Position memory p) {
        p = b.positions[id];
        if (p.state != ALLOCATED) revert WrongState();
        b.allocatedValue -= p.value;
        b.trackedValue -= p.value;
        _retire(b, id, p.packId);
    }

    function returnPack(Book storage b, uint256 id, bool owned) internal returns (Position memory p) {
        Position storage live = b.positions[id];
        p = live;
        if (p.state == ACTIVE) _removeActive(b, live);
        else if (p.state == ALLOCATED) b.allocatedValue -= p.value;
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
        if (value == 0 || b.idlePacks[b.idlePacks.length - 1] != packId) revert MissingInventory();
        delete b.idleValueOf[packId];
        b.idleValue -= value;
        b.trackedValue -= value;
        b.idleFunding -= b.idleQuote[packId];
        delete b.idleQuote[packId];
        b.idlePacks.pop();
        emit InventoryUpdated(packId, 0);
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

    function _removeActive(Book storage b, Position storage p) private {
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
        external returns (uint256 id)
    {
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

    function syncChanges(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs,
        uint256[] calldata ids, uint256 checkpointMode, uint256 witnessId)
        external returns (uint256 gasQ, uint256 units)
    {
        if (ids.length > MAX_TERMINALS) revert BadBatch();
        Work memory work;
        // No outstanding custody, identifiers or receipts means an unseen selection cannot be ours.
        bool unexposed = _unexposed(b);
        bool rebased;
        if (unexposed) {
            rebased = _rebaseUnexposed(b, f);
        } else {
            (work.processed, work.own) = _syncJournal(b, f, packs);
        }
        for (uint256 i; i < ids.length; ++i) if (_syncTerminal(b, f, packs, ids[i])) ++work.resolved;
        work.pruned = prune(b, MAX_PRUNES);
        if (work.processed + work.resolved + work.pruned == 0 && !rebased) revert Nothing();
        // Rebase is unpaid. Empty-vault head cleanup also cannot consume its bootstrap cash.
        if ((unexposed && b.trackedValue == 0) || work.processed + work.resolved + work.pruned == 0) return (0, 0);
        bool journalPaid = work.processed == MAX_JOURNAL || work.own + work.resolved != 0;
        bool requiredTail;
        if (!journalPaid && work.processed != 0 && checkpointMode != 0) {
            journalPaid = f.isPurchaseBlackout() && f.unsettledAcquisitionCount() == 0;
            if (journalPaid && checkpointMode == 2) {
                journalPaid = _distributionTail(p, b, f, witnessId,
                    Q_REQUIRED_TAIL + work.processed * Q_JOURNAL + work.pruned * Q_PRUNED);
            }
            requiredTail = journalPaid;
        }
        if (!journalPaid && work.own + work.resolved + work.pruned == 0) return (0, 0);
        gasQ = (requiredTail ? Q_REQUIRED_TAIL : Q_SYNC) + (journalPaid ? work.processed * Q_JOURNAL : 0) + work.own * Q_SELECTED
            + work.resolved * Q_SYNCED + work.pruned * Q_PRUNED;
        units = work.resolved;
    }

    function _distributionTail(Params storage p, Book storage b, IFWAV2 f, uint256 witnessId, uint256 gasQ)
        private view returns (bool)
    {
        if (b.allocationHead < b.allocationQueue.length) {
            Position storage oldest = b.positions[b.allocationQueue[b.allocationHead]];
            if (oldest.state != ALLOCATED || block.timestamp >= uint256(oldest.allocatedAt) + f.settlementWindow()) return false;
        }
        ISyncVault v = ISyncVault(address(this));
        uint256 nav_;
        try v.accountedNav(witnessId) returns (uint256 n) { nav_ = n; } catch { return false; }
        // Prove a real distribution remains possible even after the largest sync payment.
        uint256 cost = quote(p, gasQ, 0, false);
        if (nav_ <= cost) return false;
        nav_ -= cost;
        if (b.allocatedValue * BPS > nav_ * p.allocatedBoundBps) return false;
        uint256 supply = v.totalShares();
        uint256 perShare = nav_ * 1e18 / supply;
        uint256 high = v.highWaterMark();
        if (supply <= DEAD_SHARES || perShare <= high) return false;
        uint256 liquid = v.freeEth() + f.feeCredit(address(this));
        if (liquid <= p.reserve) return false;
        liquid -= p.reserve;
        if (liquid <= cost) return false;
        uint256 gain = M.mulDiv(perShare - high, supply, 1e18);
        return M.min(gain * p.distributionBps / BPS, liquid - cost) >= MIN_DISTRIBUTION;
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
        uint8 kind = b.receipts[id].kind;
        if (l.status == LISTING_SETTLED) {
            if (p.state == ACTIVE) return false;
            if (p.state != ALLOCATED) revert InvalidListing();
            if (kind == 1) {
                release(b, id, p.backing);
                keep(b, id);
                if (owns(packs, p.packId)) addInventory(b, p.packId, packs.valueOf(p.packId));
                return true;
            }
            if (kind != 0) revert MissingReceipt();
        } else if (l.status == LISTING_WITHDRAWN) {
            if (p.state != ACTIVE || kind != 2) revert MissingReceipt();
        } else return false;
        bool owned = owns(packs, p.packId);
        if (!owned && f.stuckNFTRecipient(id) != address(this)) revert MissingReceipt();
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

    function harvest(Book storage b, IFWAV2 f, uint256[] calldata ids) external returns (uint256 n) {
        if (ids.length > MAX_BATCH) revert BadBatch();
        uint256 eligible;
        for (uint256 i; i < ids.length; ++i) {
            if (i != 0 && ids[i] <= ids[i - 1]) revert BadBatch();
            Position memory p = b.positions[ids[i]];
            IFWAView.Listing memory l = listing(f, ids[i]);
            if (p.state == ACTIVE && l.status == LISTING_ACTIVE && f.pendingFees(ids[i]) != 0) ++eligible;
        }
        b.controlled = true;
        if (ids.length != 0) {
            try f.claimListingFees(ids) {
                for (uint256 i; i < ids.length; ++i) {
                    IFWAView.Listing memory l = listing(f, ids[i]);
                    if (b.positions[ids[i]].state == ACTIVE && l.status == LISTING_ACTIVE) updateFeeDebt(b, ids[i], l.feeDebt);
                }
                n = eligible;
            } catch {}
        }
        if (f.feeCredit(address(this)) != 0) f.withdrawEarnings();
        b.controlled = false;
    }

    function harvestCredit(Book storage b, IFWAV2 f) external {
        b.controlled = true;
        if (f.feeCredit(address(this)) != 0) f.withdrawEarnings();
        b.controlled = false;
    }

    function accountedNav(Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        external view returns (uint256)
    {
        return _accountedNav(b, f, packs, freeEth, witnessId);
    }

    function checkpointNav(Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        external returns (uint256)
    {
        _rebaseUnexposed(b, f);
        return _accountedNav(b, f, packs, freeEth, witnessId);
    }

    function _accountedNav(Book storage b, IFWAV2 f, IShapePacks packs, uint256 freeEth, uint256 witnessId)
        private view returns (uint256)
    {
        if (b.acquisitionCursor != f.nextSequenceToProcess()) revert CatchUpFirst();
        if (b.pendingPlusOne != 1) revert PendingReceipts();
        uint256 pending;
        if (b.activeCount != 0) {
            Position memory p = b.positions[witnessId];
            IFWAView.Listing memory l = listing(f, witnessId);
            if (p.state != ACTIVE || l.status != LISTING_ACTIVE || p.feeDebt != l.feeDebt) revert BadWitness();
            _validate(l, packs, p.packId, p.backing);
            pending = f.pendingFees(witnessId);
        }
        return nav(b, freeEth, f.feeCredit(address(this)), witnessId, pending);
    }

    function validateBacking(Params storage p, Book storage b, IFWAV2 f, address packs,
        uint256 units, uint256 backing, uint256 build, bool newlyBuilt) public view
    {
        _validateBacking(p, b, _backingTerms(p, f, packs, units, build), backing, build, newlyBuilt);
    }

    function _validateBacking(Params storage p, Book storage b, BackingTerms memory t,
        uint256 backing, uint256 build, bool newlyBuilt) private view
    {
        if (!t.ok || backing == 0 || backing > type(uint128).max || backing % BPS != 0
            || b.idForBacking[backing] != 0) revert InvalidBacking();
        uint256 delta = backing > t.desired ? backing - t.desired : t.desired - backing;
        if (delta > (b.reservedCount + 1) * BPS) revert InvalidBacking();
        if (backing < t.floor || (t.cap != type(uint256).max && backing > t.cap * (BPS - p.bufferBps) / BPS)
            || backing * (t.k - t.settlementFee * 1e14) < t.value * 1e18) revert InvalidBacking();
        uint256 gross = backing * (t.k - 1e18) / 1e18;
        uint256 net = gross > t.cycleCost ? gross - t.cycleCost : 0;
        if (net == 0 || (newlyBuilt && build > net)) revert InvalidBacking();
    }

    function _cycleNet(Params storage p, uint256 k, uint256 backing) private view returns (uint256) {
        if (k <= 1e18) return 0;
        uint256 gross = backing * (k - 1e18) / 1e18;
        uint256 cost = quote(p, Q_POSITION_SYNC + Q_LISTED + Q_HARVESTED, 2, false);
        return gross > cost ? gross - cost : 0;
    }

    function restock(Params storage p, Book storage b, IFWAV2 f, IShapePacks packs, IShapes shapes,
        uint256 units, uint256[] calldata backingProposals, uint256 available) external returns (uint256 mints)
    {
        uint256 count = backingProposals.length;
        if (count == 0 || units < MIN_PACK_UNITS || units > MAX_PACK_UNITS
            || count * units > MAX_RESTOCK_UNITS || (p.packUnitsMask >> units) & 1 == 0) revert BadBatch();
        uint256 fee = shapes.mintFee();
        uint256 build = quote(p, packGas(units) + Q_MINT * units / SHAPES_PER_MINT + Q_LISTED, 2, false) + fee * units / SHAPES_PER_MINT;
        BackingTerms memory terms = _backingTerms(p, f, address(packs), units, build);
        uint256 funding = b.idleFunding;
        for (uint256 i; i < count; ++i) {
            _validateBacking(p, b, terms, backingProposals[i], build, true);
            funding += backingProposals[i];
        }
        uint256 need = count * units;
        uint256 have = b.looseShapes.length;
        mints = need > have ? (need - have + SHAPES_PER_MINT - 1) / SHAPES_PER_MINT : 0;
        if (available < mints * (0.1 ether + fee) + funding) revert InsufficientBacking();
        uint256 freshCount = mints * SHAPES_PER_MINT;
        uint256[] memory fresh = new uint256[](freshCount);
        if (mints != 0) {
            uint8[] memory outs = new uint8[](SHAPES_PER_MINT);
            for (uint256 i; i < mints; ++i) {
                uint256 big = shapes.mint{value: 0.1 ether + fee}(0.1 ether);
                b.trackedValue += 0.1 ether;
                b.idleValue += 0.1 ether;
                uint256[] memory ids = shapes.split(big, outs);
                for (uint256 j; j < ids.length; ++j) fresh[i * SHAPES_PER_MINT + j] = ids[j];
            }
        }
        uint32[] memory noMint = new uint32[](9);
        for (uint256 c; c < count; ++c) {
            uint256[] memory ids = new uint256[](units);
            for (uint256 j; j < units; ++j) {
                if (freshCount != 0) ids[j] = fresh[--freshCount];
                else {
                    ids[j] = b.looseShapes[b.looseShapes.length - 1];
                    b.looseShapes.pop();
                }
            }
            uint256 packId = packs.createPack(ids, noMint);
            _toIdle(b, packId, units * UNIT, backingProposals[c]);
        }
        // Only genuine leftovers enter the persistent loose-Shape stack.
        for (uint256 i; i < freshCount; ++i) b.looseShapes.push(fresh[i]);
    }

    /// @dev An extended gift may contain arbitrarily many Shapes. Never enumerate its contents.
    function recoverInventory(Book storage b, IShapePacks packs, IShapes shapes) external returns (uint256 gasQ) {
        uint256 id = b.recoveryPacks[b.recoveryPacks.length - 1];
        gasQ = Q_RECOVERY_BASE;
        if (!b.recoveryUnsealed[id]) {
            packs.unseal(id, address(this));
            b.recoveryUnsealed[id] = true;
            gasQ += Q_RECOVERY_UNSEAL;
        }
        uint256 before = address(this).balance;
        uint256 supply = shapes.totalSupply();
        packs.claimEth(id, MAX_RESTOCK_UNITS, payable(address(this)));
        uint256 out = address(this).balance - before;
        // The immutable Shapes path burns exactly the claimed IDs before its sole ETH callback.
        // No other supply mutation can interleave while this guarded vault receives that ETH.
        uint256 burned = supply - shapes.totalSupply();
        if (out == 0 || burned == 0 || burned > MAX_RESTOCK_UNITS) revert MissingInventory();
        gasQ += burned * Q_RECOVERY_SHAPE;
        b.trackedValue -= out;
        b.idleValue -= out;
        b.idleValueOf[id] -= out;
        bool unsealed = true;
        if (packs.claimantOf(id) == address(0)) {
            if (b.idleValueOf[id] != 0) revert MissingInventory();
            delete b.idleValueOf[id];
            delete b.recoveryUnsealed[id];
            b.idleFunding -= b.idleQuote[id];
            delete b.idleQuote[id];
            b.recoveryPacks.pop();
            unsealed = false;
        }
        emit RecoveryUpdated(id, b.idleValueOf[id], unsealed);
    }
}
