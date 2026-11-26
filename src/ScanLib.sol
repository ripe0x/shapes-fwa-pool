// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {LibBit} from "solady/utils/LibBit.sol";

import {VaultLib, ISyncVault} from "./VaultLib.sol";
import {IFWAV2, IFWAView, IFloorOracle, IShapes, IShapePacks, LISTING_ACTIVE, LISTING_ALLOCATED, LISTING_SETTLED} from "./interfaces/External.sol";

/// @notice Bounded proofs and configuration economics, shared through the existing linked library.
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

    function rebase(VaultLib.Book storage b, IFWAV2 f, VaultLib.GasSchedule storage g) external returns (bool, uint256 scanned, uint256 own) {
        uint64 end = f.nextSequenceToProcess();
        uint256 backlog = end - b.acquisitionCursor;
        // Taken only when it costs no more than the next journal batch: a small vault's upkeep then
        // scales with its own positions, not with FWA's global activity, and the scan stays within
        // the journal batch's gas envelope.
        uint256 batch = backlog < VaultLib.MAX_JOURNAL ? backlog : VaultLib.MAX_JOURNAL;
        if (backlog == 0 || b.open.length > VaultLib.MAX_REBASE_SCAN || b.open.length * uint256(g.scan) > batch * uint256(g.journal)) return (false, 0, 0);
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


    function checkBounds(VaultLib.Params storage p) external view { _checkBounds(p); }

    function _checkBounds(VaultLib.Params storage p) private view {
        if (
            p.minEdgeBps > VaultLib.MAX_MIN_EDGE_BPS || p.bufferBps > VaultLib.MAX_BUFFER_BPS || p.distributionBps > VaultLib.MAX_DISTRIBUTION_BPS
                || p.payMarkupBps > VaultLib.MAX_PAY_MARKUP_BPS || p.workFee > VaultLib.MAX_WORK_FEE || p.keeperShareBps > VaultLib.MAX_KEEPER_SHARE_BPS
                || p.upliftBoundBps > VaultLib.MAX_UPLIFT_BOUND_BPS
                || p.gasCeiling > VaultLib.MAX_GAS_CEILING || p.essentialCeiling > VaultLib.MAX_GAS_CEILING || p.maxTip > p.gasCeiling
                || p.routineCap > VaultLib.MAX_ROUTINE_CAP || p.routineRate > VaultLib.MAX_ROUTINE_RATE || p.essentialCap > VaultLib.MAX_ESSENTIAL_CAP
                || p.essentialRate > VaultLib.MAX_ESSENTIAL_RATE
                || p.backingRatioBps < VaultLib.BPS || p.backingRatioBps > VaultLib.MAX_BACKING_RATIO_BPS
                || p.minDeposit > 1 ether || p.minDistribution > 1 ether
                || p.packUnitsMask >> (VaultLib.MAX_PACK_UNITS + 1) != 0 || p.packUnitsMask & ((1 << VaultLib.MIN_PACK_UNITS) - 1) != 0
        ) revert VaultLib.OutOfBounds();
        VaultLib.GasSchedule memory g = p.gasSchedule;
        uint32[29] memory entries;
        assembly ("memory-safe") { entries := g }
        for (uint256 i; i < entries.length; ++i) if (entries[i] > VaultLib.MAX_GAS_QUOTE) revert VaultLib.OutOfBounds();
    }

    function preview(VaultLib.Params memory p, uint256 mintFee) external view returns (uint256 units, uint256 principal,
        uint256 backing, uint256 mintCost, uint256 openingCash, bytes32 expectedConfigHash)
    {
        units = p.packUnitsMask == 0 ? VaultLib.REF_UNITS : LibBit.ffs(p.packUnitsMask);
        principal = units * VaultLib.UNIT;
        backing = principal * p.backingRatioBps / VaultLib.BPS / VaultLib.BPS * VaultLib.BPS;
        (, uint256 n) = VaultLib.makeup(units);
        mintCost = n * mintFee;
        uint256 gasQ = uint256(p.gasSchedule.build) + p.gasSchedule.buildPack
            + n * p.gasSchedule.buildShape + p.gasSchedule.listed;
        uint256 compensation = VaultLib.calculatePayment(gasQ + p.gasSchedule.overhead, 2,
            M.min(block.basefee + p.maxTip, p.gasCeiling), p.payMarkupBps, p.workFee);
        openingCash = principal + backing + mintCost + compensation + p.reserve;
        expectedConfigHash = keccak256(abi.encode(p, mintFee, false, false));
    }

    function buildCost(VaultLib.Params storage p, uint256 units, uint256 mintFee) external view returns (uint256) { return _buildCost(p, units, mintFee); }

    function _buildCost(VaultLib.Params storage p, uint256 units, uint256 mintFee) private view returns (uint256) {
        (, uint256 n) = VaultLib.makeup(units);
        return VaultLib.quote(p, uint256(p.gasSchedule.build) + VaultLib.buildGas(p, n) + p.gasSchedule.listed, 2, false) + n * mintFee;
    }

    function positionValue(VaultLib.Params storage p) external view returns (uint256) {
        uint256 value = VaultLib.refUnits(p) * VaultLib.UNIT;
        return value + value * p.backingRatioBps / VaultLib.BPS;
    }





    function operatingReserve(VaultLib.Params storage p) external view returns (uint256) {
        return p.reserve;
    }

    function deployCharge(VaultLib.Params storage p, uint256 mintFee) external view returns (uint256 cost) {
        if (p.packUnitsMask == 0) return 0;
        // Compare every allowed recipe, at most 28, by cost per capital rather than face size.
        uint256 refCapital = VaultLib.refUnits(p) * VaultLib.UNIT * (VaultLib.BPS + p.backingRatioBps) / VaultLib.BPS;
        for (uint256 u = VaultLib.MIN_PACK_UNITS; u <= VaultLib.MAX_PACK_UNITS; ++u) {
            if ((p.packUnitsMask >> u) & 1 == 0) continue;
            uint256 capital = u * VaultLib.UNIT * (VaultLib.BPS + p.backingRatioBps) / VaultLib.BPS;
            cost = M.max(cost, M.mulDivUp(_buildCost(p, u, mintFee), refCapital, capital));
        }
    }

    function unwindCharge(VaultLib.Params storage p, VaultLib.Book storage b) external view returns (uint256 cost) {
        if (p.essentialCap == 0) return 0;
        uint256 refCapital = VaultLib.refUnits(p) * VaultLib.UNIT * (VaultLib.BPS + p.backingRatioBps) / VaultLib.BPS;
        uint256 count;
        uint256 largestUnits;
        uint256 ordinaryValue;
        for (uint256 u = 1; u <= VaultLib.MAX_PACK_UNITS; ++u) {
            uint256 n = b.recipeCounts[u];
            if (n == 0) continue;
            count += n;
            largestUnits = u;
            ordinaryValue += n * u * VaultLib.UNIT;
        }
        uint256 capital = b.trackedValue + b.activeBacking;
        uint256 recoveryPacks = b.recoveryPacks.length;
        if ((count != 0 || recoveryPacks != 0) && capital != 0) {
            // Full bounded calls fit this many packs even in an arbitrarily interleaved LIFO
            // book. Per-recipe grouped batch counts can underquote that actual order.
            uint256 perCall = largestUnits == 0 ? VaultLib.MAX_BATCH
                : M.min(VaultLib.MAX_BATCH, VaultLib.MAX_LIQUIDATE_UNITS / largestUnits);
            uint256 gasQ = b.activeCount * p.gasSchedule.unlisted + count * p.gasSchedule.liquidatePack
                + b.ordinaryShapeCount * p.gasSchedule.redeemShape
                + ((b.activeCount + VaultLib.MAX_BATCH - 1) / VaultLib.MAX_BATCH) * p.gasSchedule.unlist
                + ((count + perCall - 1) / perCall) * p.gasSchedule.liquidate;
            uint256 serviceUnits = b.activeCount + count;
            uint256 calls = (b.activeCount + VaultLib.MAX_BATCH - 1) / VaultLib.MAX_BATCH
                + (count + perCall - 1) / perCall;
            if (recoveryPacks != 0) {
                // ShapePacks rejects unbacked Shapes; every packed Shape has at least UNIT.
                // No contents enumeration: value bounds remaining Shapes, and all remaining
                // packs are conservatively treated as sealed, even after partial recovery.
                uint256 shapes = (b.trackedValue - ordinaryValue) / VaultLib.UNIT;
                uint256 chunks = (shapes + VaultLib.MAX_REDEEM_SHAPES - 1) / VaultLib.MAX_REDEEM_SHAPES
                    + recoveryPacks - 1;
                gasQ += shapes * p.gasSchedule.recoveryShape + recoveryPacks * p.gasSchedule.recoveryUnseal
                    + chunks * (uint256(p.gasSchedule.liquidate) + p.gasSchedule.recoveryBase);
                serviceUnits += chunks;
                calls += chunks;
            }
            return M.mulDivUp(VaultLib.quoteCalls(p, gasQ, serviceUnits, true, calls), refCapital, capital);
        }
        // No ordinary book yet: compare permitted recipes using their actual mint counts.
        for (uint256 u = VaultLib.MIN_PACK_UNITS; u <= VaultLib.MAX_PACK_UNITS; ++u) {
            if ((p.packUnitsMask >> u) & 1 == 0) continue;
            (, uint256 n) = VaultLib.makeup(u);
            uint256 gasQ = uint256(p.gasSchedule.unlist) + p.gasSchedule.unlisted + p.gasSchedule.liquidate
                + p.gasSchedule.liquidatePack + n * p.gasSchedule.redeemShape;
            uint256 recipeCapital = u * VaultLib.UNIT * (VaultLib.BPS + p.backingRatioBps) / VaultLib.BPS;
            cost = M.max(cost, M.mulDivUp(VaultLib.quoteCalls(p, gasQ, 2, true, 2), refCapital, recipeCapital));
        }
    }

    function economics(IFWAV2 f, address packs) internal view returns (uint256 k1e18, uint256 cap, uint256 s) {
        s = f.ownerSettlementFeeBps();
        uint256 w = f.totalWeight();
        if (w == 0) return (0, 0, s);
        // FWA exposes no getter for its surcharge: acquisitionFee = (wbt / w) (1 + surcharge).
        uint256 ev = f.weightedBackingTotal() / w;
        uint256 oneSur = f.acquisitionFee() * 1e18 / ev; // 1e18 x (1 + surcharge), floors
        k1e18 = oneSur * (VaultLib.BPS - f.ownerAcquisitionFeeBps()) / VaultLib.BPS * (VaultLib.BPS - f.topListingShareBps()) / VaultLib.BPS;
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
        uint256 oracleGas = VaultLib.ORACLE_GAS;
        assembly ("memory-safe") {
            let m := mload(0x40) // scratch past the free pointer; not kept
            ok := staticcall(oracleGas, o, add(c, 32), mload(c), m, 128)
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
        cap = ask * (VaultLib.BPS + f.oracleCeilingPremiumBps()) / VaultLib.BPS;
    }

    function recoverInventory(VaultLib.Params storage p, VaultLib.Book storage b, IShapePacks packs, IShapes shapes) external returns (uint256 gasQ) {
        uint256 id = b.recoveryPacks[b.recoveryPacks.length - 1];
        gasQ = p.gasSchedule.recoveryBase;
        if (!b.recoveryUnsealed[id]) {
            packs.unseal(id, address(this));
            b.recoveryUnsealed[id] = true;
            gasQ += p.gasSchedule.recoveryUnseal;
        }
        uint256 before = address(this).balance;
        uint256 supply = shapes.totalSupply();
        packs.claimEth(id, VaultLib.MAX_REDEEM_SHAPES, payable(address(this)));
        uint256 out = address(this).balance - before;
        // The immutable Shapes path burns exactly the claimed IDs before its sole ETH callback.
        // No other supply mutation can interleave while this guarded vault receives that ETH.
        uint256 burned = supply - shapes.totalSupply();
        if (out == 0 || burned == 0 || burned > VaultLib.MAX_REDEEM_SHAPES) revert VaultLib.MissingInventory();
        gasQ += burned * p.gasSchedule.recoveryShape;
        b.trackedValue -= out;
        b.idleValue -= out;
        b.idleValueOf[id] -= out;
        bool unsealed = true;
        if (packs.claimantOf(id) == address(0)) {
            if (b.idleValueOf[id] != 0) revert VaultLib.MissingInventory();
            delete b.idleValueOf[id];
            delete b.recoveryUnsealed[id];
            b.idleFunding -= b.idleQuote[id];
            delete b.idleQuote[id];
            b.recoveryPacks.pop();
            unsealed = false;
        }
        emit VaultLib.RecoveryUpdated(id, b.idleValueOf[id], unsealed);
    }


    function distributionTail(VaultLib.Params storage p, VaultLib.Book storage b, IFWAV2 f, uint256 witnessId, uint256 gasQ)
        external view returns (bool)
    {
        if (b.allocationHead < b.allocationQueue.length) {
            VaultLib.Position storage oldest = b.positions[b.allocationQueue[b.allocationHead]];
            if (oldest.state != VaultLib.ALLOCATED || block.timestamp >= uint256(oldest.allocatedAt) + f.settlementWindow()) return false;
        }
        ISyncVault v = ISyncVault(address(this));
        uint256 nav_;
        try v.accountedNav(witnessId) returns (uint256 n) { nav_ = n; } catch { return false; }
        // Prove a real distribution remains possible even after the largest sync payment.
        uint256 cost = VaultLib.quote(p, gasQ, 0, false);
        if (nav_ <= cost) return false;
        nav_ -= cost;
        if (b.unresolvedKeepUplift * VaultLib.BPS > nav_ * p.upliftBoundBps) return false;
        uint256 supply = v.totalShares();
        uint256 perShare = nav_ * 1e18 / supply;
        uint256 high = v.highWaterMark();
        if (supply <= VaultLib.DEAD_SHARES || perShare <= high) return false;
        uint256 liquid = v.freeEth() + f.feeCredit(address(this));
        uint256 reserve = p.reserve;
        if (liquid <= reserve) return false;
        liquid -= reserve;
        if (liquid <= cost) return false;
        uint256 gain = M.mulDiv(perShare - high, supply, 1e18);
        uint256 distribution = M.min(gain * p.distributionBps / VaultLib.BPS, liquid - cost);
        return distribution != 0 && distribution >= p.minDistribution;
    }


    function encodedParams(VaultLib.Params storage p) external view returns (bytes memory) {
        VaultLib.Params memory values = p;
        return abi.encode(values);
    }

    function configurationHash(VaultLib.Params storage p, uint256 liveMintFee, bool paused, bool windingDown)
        external view returns (bytes32)
    {
        VaultLib.Params memory values = p;
        return keccak256(abi.encode(values, liveMintFee, paused, windingDown));
    }

    function initializeParams(VaultLib.Strategy storage s, VaultLib.Params memory p) external {
        s.params = p;
        _checkBounds(s.params);
        s.budget = VaultLib.Budget(uint128(p.routineCap), uint128(p.essentialCap), block.timestamp);
    }

    function configure(VaultLib.Strategy storage s, VaultLib.Params calldata p) external {
        if (p.acceptedMintFee != s.params.acceptedMintFee) revert VaultLib.ExplicitFeeAcceptanceRequired();
        (uint256 r, uint256 e) = VaultLib.budgetNow(s.params, s.budget);
        s.budget = VaultLib.Budget(uint128(r), uint128(e), block.timestamp);
        s.params = p;
        _checkBounds(s.params);
        s.budget.routine = uint128(M.min(r, p.routineCap));
        s.budget.essential = uint128(M.min(e, p.essentialCap));
    }

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

    /// @notice One replacement's verified-work envelope; optional funding work is quoted separately.




    function backingTerms(VaultLib.Params storage p, IFWAV2 f, address packs, uint256 units, uint256, uint256)
        external view returns (VaultLib.BackingTerms memory t)
    {
        (t.k, t.cap, t.settlementFee) = economics(f, packs);
        t.value = units * VaultLib.UNIT;
        // Allocations are marked at pack face. Even a keep at FWA's immutable 5% fee cap
        // must cover that mark; the incremental checkpoint guard bounds positive uplift only.
        t.floor = t.value + t.value / 19 + (t.value % 19 == 0 ? 0 : 1);
        t.desired = t.value * p.backingRatioBps / VaultLib.BPS / VaultLib.BPS * VaultLib.BPS;
        if (t.cap != type(uint256).max) t.desired = M.min(t.desired, t.cap * (VaultLib.BPS - p.bufferBps) / VaultLib.BPS);
        t.ok = t.cap != 0 && t.k >= 1e18 + uint256(p.minEdgeBps) * 1e14 && t.desired >= t.floor
            && VaultLib._profitable(t, t.desired, false);
        if (!t.ok) t.desired = 0;
    }
}
