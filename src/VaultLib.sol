// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {IKeeperPolicy} from "./KeeperPolicy.sol";
import {
    IFWAV2,
    IFloorOracle,
    IShapePacks,
    LISTING_ACTIVE,
    LISTING_STAGED,
    LISTING_ALLOCATED,
    LISTING_SETTLED,
    LISTING_WITHDRAWN
} from "./interfaces/External.sol";

/// @notice Linked library for PackVault: the live FWA economics read. Split out only to keep
///         PackVault under EIP-170; it runs in the vault's context and holds no state.
library VaultLib {
    uint256 internal constant BPS = 10_000;

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
        uint64 workFee; // flat wei per unit of work done: position listed, resolved, activated,
        //                 unlisted, item liquidated, or a checkpoint that priced flows
        uint64 routineCap; // keeper budget for strategy work: capacity (wei) and refill per day
        uint64 routineRate;
        uint64 essentialCap; // keeper budget for redemption and wind-down work
        uint64 essentialRate;
        uint96 maxPositions;
        uint128 reserve; // ETH kept idle
        uint128 tvlCap; // deposits refused above this NAV
    }


    uint256 internal constant UNIT = 0.01 ether;

    // ---------------------------------------------------------------- bounds and quotes

    uint256 internal constant MAX_POSITIONS = 300;
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
    uint256 internal constant Q_CHECKPOINT = 225_000;
    uint256 internal constant Q_CHECKPOINT_POS = 33_000; // per open position valued
    uint256 internal constant Q_RESTOCK = 280_000;
    uint256 internal constant Q_PACK = 200_000; // createPack
    uint256 internal constant Q_MINT = 2_200_000; // one 0.1 ETH mint split ten ways (2.10M-2.26M by block)
    uint256 internal constant Q_LIST = 255_000;
    uint256 internal constant Q_LISTED = 530_000;
    uint256 internal constant Q_SYNC = 75_000;
    uint256 internal constant Q_SYNCED = 75_000;
    uint256 internal constant Q_ACTIVATE = 50_000;
    uint256 internal constant Q_ACTIVATED = 450_000; // FWA inserts it into its selection tree (~470k measured)
    uint256 internal constant Q_UNLIST = 240_000;
    uint256 internal constant Q_UNLISTED = 170_000;
    uint256 internal constant Q_LIQUIDATE = 75_000;
    uint256 internal constant Q_LIQ_PACK = 150_000;
    uint256 internal constant Q_LIQ_SHAPE = 65_000;
    uint256 internal constant Q_HARVEST = 80_000;
    uint256 internal constant Q_HARVESTED = 15_000; // per listing with fees claimed
    /// A 3-unit position (0.03 ETH pack + ~0.0363 backing): what request charges are scaled by.
    uint256 internal constant POSITION_VALUE = 0.0663 ether;

    struct Position {
        uint64 packId;
        uint64 units; // pack value in 0.01 ETH
        uint128 backing;
    }

    /// @notice Value of every open position from FWA state, read-only (checkpoint pricing).
    ///         Active: pack + backing + pending fees. Staged: pack + backing. Allocated: the lesser of
    ///         the pack and the net backing (both outcomes pay at least that). Settled or withdrawn
    ///         and not yet synced: the pack, if the vault holds it or FWA owes it (every ETH leg
    ///         already reached the balance or fee credit).
    function valueOpen(IFWAV2 f, IShapePacks packs, mapping(uint256 => Position) storage positions, uint256[] storage open)
        external
        view
        returns (uint256 nav, uint256 allocated, bool expired)
    {
        uint256 s = f.ownerSettlementFeeBps();
        uint256 window = f.settlementWindow();
        for (uint256 i; i < open.length; ++i) {
            uint256 id = open[i];
            Position memory pos = positions[id];
            (,,,,,,,,, uint64 allocatedAt, uint8 status) = f.listings(id);
            uint256 value = pos.units * UNIT;
            if (status == LISTING_ACTIVE) {
                nav += value + pos.backing + f.pendingFees(id);
            } else if (status == LISTING_STAGED) {
                nav += value + pos.backing;
            } else if (status == LISTING_ALLOCATED) {
                // Past the window the vault can resolve it with sync (the purchaser may still act
                // first, so the value is not certain); pricing waits for that (audit E6).
                if (block.timestamp >= allocatedAt + window) expired = true;
                uint256 floorValue = value < pos.backing * (BPS - s) / BPS ? value : pos.backing * (BPS - s) / BPS;
                nav += floorValue;
                allocated += floorValue;
            } else if (owns(packs, pos.packId) || f.stuckNFTRecipient(id) == address(this)) {
                nav += value;
            }
        }
    }

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
        uint256 o =
            offer(policy, op, units, gasQ, essential, essential ? p.essentialCeiling : p.gasCeiling, p.maxTip, p.workFee);
        amount = M.min(M.min(o, M.min(quote(p, gasQ, units, essential), cap)), M.min(free, essential ? e : r));
        if (amount < minPay) revert Payment();
        (b.routine, b.essential, b.at) =
            (uint128(essential ? r : r - amount), uint128(essential ? e - amount : e), block.timestamp);
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
                || p.gasCeiling > MAX_GAS_CEILING || p.essentialCeiling > MAX_GAS_CEILING || p.maxTip > p.gasCeiling || p.maxPositions > MAX_POSITIONS
                || p.routineCap > MAX_ROUTINE_CAP || p.routineRate > MAX_ROUTINE_RATE || p.essentialCap > MAX_ESSENTIAL_CAP
                || p.essentialRate > MAX_ESSENTIAL_RATE
                || p.packUnitsMask >> (MAX_PACK_UNITS + 1) != 0 || p.packUnitsMask & ((1 << MIN_PACK_UNITS) - 1) != 0
        ) revert OutOfBounds();
    }

    function cycleNet(Params storage p, uint256 k1e18, uint256 backing) external view returns (uint256) {
        if (k1e18 <= 1e18) return 0;
        uint256 gross = backing * (k1e18 - 1e18) / 1e18;
        uint256 cost = quote(p, Q_SYNCED + Q_LISTED + Q_HARVESTED, 2, false);
        return gross > cost ? gross - cost : 0;
    }

    /// @notice A request's checkpoint charge: one checkpoint at its envelope, at cost plus one unit.
    function requestCharge(Params storage p, uint256 openPositions) external view returns (uint256) {
        return quote(p, Q_CHECKPOINT + openPositions * Q_CHECKPOINT_POS, 1, true);
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
        return quote(p, Q_UNLISTED + Q_LIQ_PACK, 2, true);
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
    ///         - `spread`: spare capital per open slot when the position count, not capital, binds;
    ///         capped at FWA's oracle cap less the buffer unless FWA exempts the collection.
    function edge(Params storage p, IFWAV2 f, address packs, uint256 units, uint256 spread, uint256 build)
        public
        view
        returns (uint256 k1e18, uint256 backing, bool ok)
    {
        uint256 cap;
        uint256 s;
        (k1e18, cap, s) = economics(f, packs);
        uint256 value = units * UNIT;
        uint256 floor = M.max(M.divUp(value * BPS, BPS - s), M.divUp(value * BPS, f.settlementDiscountBps()));
        backing = M.max(floor, spread);
        if (k1e18 > 1e18) {
            uint256 a = k1e18 - 1e18;
            uint256 c = (Q_SYNCED + Q_LISTED + Q_HARVESTED) * p.gasCeiling * (BPS + p.payMarkupBps) / BPS + 2 * p.workFee;
            backing = M.max(backing, (c + M.sqrt(c * c + a * c / 1e18 * value)) * 1e18 / a);
            backing = M.max(backing, M.divUp((build + quote(p, Q_SYNCED + Q_LISTED + Q_HARVESTED, 2, false)) * 1e18, a));
        }
        if (cap != type(uint256).max) backing = M.min(backing, cap * (BPS - p.bufferBps) / BPS);
        // Bid outcome B (k - 1) > 0 given k >= 1 + edge; spending callers also require it to clear
        // the keeper pay it causes (cycleNet). Keep outcome B (k - s) >= P holds from the floor.
        ok = cap != 0 && k1e18 >= 1e18 + uint256(p.minEdgeBps) * 1e14 && k1e18 > s * 1e14 && backing >= floor
            && backing * (k1e18 - s * 1e14) >= value * 1e18;
        if (!ok) backing = 0;
    }


    /// @notice Revert before the work when `minPay` already exceeds what could be paid.
    function precheck(Params storage p, Budget storage b, uint256 minPay, bool essential, uint256 free)
        external
        view
    {
        (uint256 r, uint256 e) = budgetNow(p, b);
        if (minPay > M.min(free, essential ? e : r)) revert Payment();
    }

    event Resolved(uint256 indexed listingId, uint8 status, bool packReturned);
    event PackOwed(uint256 indexed listingId); // FWA holds the pack as a pull claim; sync retries

    /// @notice Resolve a position FWA has moved on: reclaim an allocated one the purchaser left past
    ///         the settlement window, fold a settled or withdrawn one back into inventory. A pack
    ///         FWA failed to deliver stays open until it arrives; a later sync retries the pull.
    ///         The outcome comes from FWA's own record, never from inference: a pack is the
    ///         vault's if the vault holds it or FWA owes it; anything else went to the purchaser.
    function sync(
        mapping(uint256 => Position) storage positions,
        uint256[] storage open,
        mapping(uint256 => uint256) storage openIndex,
        uint256[] storage idle,
        IFWAV2 f,
        IShapePacks packs,
        uint256 listingId
    ) external returns (bool) {
        Position memory pos = positions[listingId];
        if (openIndex[listingId] == 0) return false;
        (,,,,,,,,, uint64 allocatedAt, uint8 status) = f.listings(listingId);
        if (status == LISTING_ALLOCATED) {
            if (block.timestamp < allocatedAt + f.settlementWindow()) return false;
            // Purchaser went silent: pick the better outcome for the vault.
            uint256 back = pos.backing * (BPS - f.ownerSettlementFeeBps()) / BPS;
            if (back >= pos.units * UNIT) f.depositorReclaimBacking(listingId);
            else f.depositorReclaimNFT(listingId);
            (,,,,,,,,,, status) = f.listings(listingId);
        }
        if (status != LISTING_SETTLED && status != LISTING_WITHDRAWN) return false;
        if (f.stuckNFTRecipient(listingId) == address(this)) {
            // Reverts while the collection still fails; the claim survives for the next try.
            (bool ok,) = address(f).call(abi.encodeCall(IFWAV2.recoverStuckNFT, (listingId)));
            if (!ok || !owns(packs, pos.packId)) {
                emit PackOwed(listingId);
                return false;
            }
        }
        bool packBack = owns(packs, pos.packId);
        if (packBack) idle.push(pos.packId);
        removeOpen(positions, open, openIndex, listingId);
        emit Resolved(listingId, status, packBack);
        return true;
    }

    function removeOpen(
        mapping(uint256 => Position) storage positions,
        uint256[] storage open,
        mapping(uint256 => uint256) storage openIndex,
        uint256 listingId
    ) public {
        uint256 idx = openIndex[listingId] - 1;
        uint256 last = open[open.length - 1];
        open[idx] = last;
        openIndex[last] = idx + 1;
        open.pop();
        delete openIndex[listingId];
        delete positions[listingId];
    }

    /// @notice Redeemable value of idle packs.
    function valueIdle(IShapePacks packs, uint256[] storage idle) external view returns (uint256 v) {
        for (uint256 i; i < idle.length; ++i) {
            v += packs.valueOf(idle[i]);
        }
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
}
