// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {VaultLib, IAccount} from "./VaultLib.sol";
import {
    IShapes,
    IShapePacks,
    IFWAV2,
    IFWAView,
    IFWARewards,
    IFWAToken,
    LISTING_ACTIVE,
    LISTING_WITHDRAWN,
    LISTING_SETTLED
} from "./interfaces/External.sol";

/// @notice The one implementation of the FWA pack strategy's operations, shared by the pooled
///         PackVault and every PackManager. Linked and DELEGATECALLed: it runs in the calling
///         account's context against that account's `VaultLib.Strategy`, so the account is the
///         FWA depositor, holds every asset and pays its own keepers. It has no asset withdrawal
///         path: ETH leaves only as FWA backing, Shapes mint payments, or keeper pay capped by the
///         account's budgets and `freeEth()`. Ownership rules (shares, owner withdrawals) stay in
///         the accounts. Callers wrap every entry point in their own reentrancy guard.
library StrategyLib {
    uint256 internal constant BPS = 10_000;
    uint256 internal constant UNIT = 0.01 ether;
    uint256 internal constant CROWN_EXIT_WINDOW = 12 hours; // FWA early crown exit costs 1%
    uint256 internal constant MAX_LIQUIDATE_UNITS = VaultLib.MAX_LIQUIDATE_UNITS; // ordinary packs: at most 60 Shapes burned

    event Built(uint256 packs, uint256 units);
    event Listed(uint256 indexed listingId, uint256 packId, uint256 backing);
    event Unlisted(uint256 indexed listingId);
    event Liquidated(uint256 packs, uint256 shapes, uint256 ethOut);
    event TokensBurned(uint256 amount);

    error WindingDown();
    error Paused();
    error Nothing();
    error Amount();
    error Payment();
    error UnlistNotAllowed();

    struct LiquidationWork { uint256 n; uint256 units; uint256 recovery; }

    // ------------------------------------------------------------------ economics

    /// @notice Live economics for a pack of `units`: k, the backing a new listing posts (0 when it
    ///         must not list) and whether it lists.
    function edge(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, IShapes shapes, uint256 units)
        public view returns (uint256, uint256, bool)
    {
        (, uint256 n) = VaultLib.makeup(units);
        return VaultLib.edge(s.params, f, address(packs), units, shapes.mintFee(), true, n);
    }

    function relistEdge(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, IShapes shapes, uint256 units)
        external view returns (uint256, uint256, bool)
    {
        // Unknown inventory composition is bounded by one 0.01 ETH Shape per unit.
        return VaultLib.edge(s.params, f, address(packs), units, shapes.mintFee(), false, units);
    }

    function relistEdgeFor(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, IShapes shapes, uint256 packId)
        external view returns (uint256, uint256, bool)
    {
        uint256 value = s.book.idleValueOf[packId];
        if (value == 0 || s.book.idleIndex[packId] == 0) revert VaultLib.MissingInventory();
        return VaultLib.edge(s.params, f, address(packs), value / UNIT, shapes.mintFee(), false,
            s.book.packShapeCount[packId]);
    }

    // ------------------------------------------------------------------ inventory

    /// @notice Mint new packs of `units` straight into ShapePacks and list each at once, one
    ///         backing proposal per pack. Only while listing is open and a keep cycle repays the
    ///         build at today's quoted price (VaultLib.buildAndList).
    function build(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, IShapes shapes, uint256 units,
        uint256[] calldata proposals, uint256 minPay, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        _requireListing(s, f);
        _precheck(s, minPay, false);
        // Returned packs relist first: a build may not spend the backing booked for idle inventory.
        uint256 idle = IAccount(address(this)).idleEth();
        uint256 booked = s.book.idleFunding;
        VaultLib.buildAndList(s.params, s.book, f, packs, shapes, units, proposals, idle > booked ? idle - booked : 0);
        uint256 count = proposals.length;
        emit Built(count, units);
        (, uint256 n) = VaultLib.makeup(units);
        return _pay(s, s.params.gasSchedule.build + count * (VaultLib.buildGas(s.params, n) + s.params.gasSchedule.listed), 2 * count,
            false, minPay, type(uint256).max, gasStart);
    }

    /// @notice Relist idle packs (returned by bids, withdrawals or expiry) at bounded proposals,
    ///         checked against live economics. No mint: a returned pack is reused as is.
    function list(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, IShapes shapes,
        uint256[] calldata proposals, uint256 minPay, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        _requireListing(s, f);
        _precheck(s, minPay, false);
        if (proposals.length > VaultLib.MAX_LIST_BATCH) revert Amount();
        VaultLib.Book storage b = s.book;
        uint256 available = IAccount(address(this)).idleEth();
        uint256 fee = shapes.mintFee();
        uint256 listed;
        while (listed < proposals.length && b.idlePacks.length != 0) {
            uint256 packId = b.idlePacks[b.idlePacks.length - 1];
            uint256 units = b.idleValueOf[packId] / UNIT;
            uint256 backing = proposals[listed];
            VaultLib.validateBacking(s.params, b, f, address(packs), units, backing,
                fee, false, b.packShapeCount[packId]);
            uint256 compensation = VaultLib.quote(s.params,
                uint256(s.params.gasSchedule.list) + (listed + 1) * s.params.gasSchedule.listed, listed + 1, false);
            if (available < backing + compensation) break;
            available -= backing;
            emit Listed(VaultLib.admit(b, f, packs, packId, backing), packId, backing);
            ++listed;
        }
        if (listed == 0) revert Nothing();
        if (listed != proposals.length) revert VaultLib.UnusedPaidInput();
        return _pay(s, s.params.gasSchedule.list + listed * s.params.gasSchedule.listed, listed, false, minPay, type(uint256).max, gasStart);
    }





    function recover(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, uint256[] calldata ids,
        uint256 witness, uint256 checkpointMode) external {
        VaultLib.syncUnfunded(s.params, s.book, f, packs, ids, checkpointMode, witness, false);
    }

    function syncFunded(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, uint256[] calldata ids,
        uint256 witness, uint256 checkpointMode, uint256 minPay, uint256 fundingCap, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        if (checkpointMode != 1) revert Nothing();
        (uint256 gasQ, uint256 units) = VaultLib.syncUnfunded(s.params, s.book, f, packs, ids, checkpointMode, witness, true);
        return VaultLib.payFunded(s.params, gasQ, units, true, minPay, fundingCap, gasStart - gasleft());
    }

    function _requireListing(VaultLib.Strategy storage s, IFWAV2 f) private view {
        if (s.windingDown) revert WindingDown();
        if (s.listingPaused) revert Paused();
        // FWA stages listings while acquisitions are unsettled; nothing this account lists is staged.
        if (f.unsettledAcquisitionCount() != 0) revert Nothing();
    }

    // ------------------------------------------------------------------ positions

    /// @notice Bounded journal or scan job, terminal resolutions and allocation cleanup.
    ///         `checkpointMode` is 0 for an account without checkpoints.
    function sync(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, uint256[] calldata listingIds,
        uint256 witnessId, uint256 checkpointMode, uint256 minPay, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        (uint256 gasQ, uint256 units) =
            VaultLib.syncChanges(s.params, s.budget, s.book, f, packs, listingIds, checkpointMode, witnessId);
        return _pay(s, gasQ, units, false, minPay, type(uint256).max, gasStart);
    }

    /// @notice Withdraw active listings: in wind-down (exit), when `shortfall` ETH is owed beyond
    ///         what free ETH and inventory cover (essential), or when FWA's live fees leave no edge
    ///         (routine). A stale quote or a gas spike stops new listings but never unwinds earning
    ///         ones. Exits never read FWA's economics, so a hostile oracle or fee cannot block them.
    function unlist(VaultLib.Strategy storage s, IFWAV2 f, IShapePacks packs, uint256[] calldata listingIds,
        uint256 minPay, uint256 shortfall, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        if (listingIds.length > VaultLib.MAX_BATCH) revert Amount();
        bool essential = s.windingDown || shortfall != 0;
        if (!essential) {
            (uint256 k,,) = VaultLib.economics(f, address(packs));
            if (k >= 1e18 + uint256(s.params.minEdgeBps) * 1e14) revert UnlistNotAllowed();
        }
        _precheckPermission(s, minPay, essential);
        VaultLib.Book storage b = s.book;
        uint256 realized;
        uint256 moved;
        bool covered; // shortfall satisfied: the loop stopped early, the untouched tail is not unused input
        for (uint256 i; i < listingIds.length; ++i) {
            uint256 id = listingIds[i];
            if (b.openIndex[id] == 0) continue;
            if (f.topListingId() == id && block.timestamp < f.topListingSince() + CROWN_EXIT_WINDOW) continue;
            (,,,,,,,,,, uint8 status) = f.listings(id);
            if (status != LISTING_ACTIVE) continue;
            VaultLib.Position memory pos = b.positions[id];
            VaultLib.withdraw(b, f, packs, id);
            emit Unlisted(id);
            realized += pos.backing + pos.value;
            ++moved;
            if (!s.windingDown && shortfall != 0 && realized >= shortfall) { covered = true; break; }
        }
        if (realized == 0) revert Nothing();
        // The unused-input guard rejects stale/invalid hints the keeper should fix. But a shortfall
        // unlist deliberately stops once it covers the shortfall (the break above), leaving the rest
        // of the batch valid-but-unneeded; a caller legitimately passes the whole open set, so that
        // early stop is not unused input. Skip the guard only for that case.
        if (!s.callerFunded && !covered && moved != listingIds.length) revert VaultLib.UnusedPaidInput();
        return _pay(s, s.params.gasSchedule.unlist + moved * s.params.gasSchedule.unlisted, moved, essential, minPay,
            type(uint256).max, gasStart);
    }

    /// @notice Redeem up to `maxCount` idle packs to ETH at their exact backing, or one bounded
    ///         recovery chunk, while `need` ETH is still owed beyond free ETH, or freely in wind-down.
    function liquidate(VaultLib.Strategy storage s, IShapePacks packs, IShapes shapes, uint256 maxCount,
        uint256 minPay, uint256 need, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        if (!s.windingDown && need == 0) revert Nothing();
        _precheckPermission(s, minPay, true);
        VaultLib.Book storage b = s.book;
        maxCount = M.min(M.min(maxCount, VaultLib.MAX_BATCH),
            b.idlePacks.length + (b.recoveryPacks.length != 0 ? 1 : 0));
        uint256 before = address(this).balance;
        uint256 supplyBefore = shapes.totalSupply();
        LiquidationWork memory w;
        while (w.n + w.recovery < maxCount && (s.windingDown || address(this).balance - before < need)) {
            if (b.idlePacks.length != 0) {
                uint256 packId = b.idlePacks[b.idlePacks.length - 1];
                uint256 value = b.idleValueOf[packId];
                if (w.units + value / UNIT > MAX_LIQUIDATE_UNITS) break;
                w.units += value / UNIT;
                VaultLib.redeemInventory(b, packId);
                packs.redeem(packId);
                ++w.n;
            } else if (b.recoveryPacks.length != 0) {
                if (w.n != 0) break;
                // Recovery is one isolated chunk of at most 30 underlying Shapes.
                VaultLib.recoverInventory(s.params, b, packs, shapes);
                ++w.recovery;
                break;
            } else {
                break;
            }
        }
        if (w.n + w.recovery == 0) revert Nothing();
        // Pay only for the Shapes actually burned; w.recovery is isolated from this loop.
        uint256 burned = w.n == 0 ? 0 : supplyBefore - shapes.totalSupply();
        if (w.n != 0 && (burned == 0 || burned > MAX_LIQUIDATE_UNITS)) revert Amount();
        emit Liquidated(w.n + w.recovery, burned, address(this).balance - before);
        // Liquidation and recovery are exit work: always unpaid, so no gas is quoted. `_pay` only
        // enforces callerFunded / nonzero-minPay here (essential path).
        return _pay(s, 0, 0, true, minPay, type(uint256).max, gasStart);
    }

    // ------------------------------------------------------------------ fees, tokens, receipts

    /// @notice Caller-funded fee collection: never paid (positive `minPay` reverts).
    function harvest(VaultLib.Strategy storage s, IFWAV2 f, uint256[] calldata activeIds, uint256 minPay) external {
        if (minPay != 0) revert Payment();
        uint256 before = address(this).balance;
        VaultLib.harvest(s.book, f, activeIds);
        if (address(this).balance == before) revert Nothing();
    }

    /// @notice Claim depositor FWA token rewards and burn every FWA token held. Tokens are never
    ///         valued or sold (D43). Unpaid.
    function burnTokens(IFWARewards rewards, IFWAToken token, uint256[] calldata activeIds) external {
        if (activeIds.length > VaultLib.MAX_BATCH) revert Amount();
        // FWA's claim reverts for the whole batch on one inactive listing, or with nothing pending.
        if (activeIds.length != 0) try rewards.claimDepositorTokens(activeIds) {} catch {}
        if (rewards.tokenCredit(address(this)) != 0) rewards.withdrawTokens();
        uint256 amount = token.balanceOf(address(this));
        if (amount == 0) revert Nothing();
        token.burn(amount);
        emit TokensBurned(amount);
    }

    /// @notice Identify ETH FWA pushes to this account outside its own calls: a keep payment
    ///         B (1 - s) or a kick refund B, matched to the open listing with exactly that unique
    ///         backing. Unmatched ETH stays in the balance as free ETH. Called from `receive()`,
    ///         which FWA invokes with a 100,000 gas stipend.
    function receipt(VaultLib.Book storage b, IFWAV2 f, IShapePacks packs, uint256 amount) external {
        if (b.controlled) return;
        uint256 fee = f.ownerSettlementFeeBps();
        if (fee < BPS) {
            uint256 denominator = BPS - fee;
            if (amount % denominator == 0 && amount / denominator <= type(uint256).max / BPS) {
                if (_identify(b, f, packs, amount / denominator * BPS, 1, fee, amount)) return;
            }
        }
        _identify(b, f, packs, amount, 2, fee, amount);
    }

    function _identify(VaultLib.Book storage b, IFWAV2 f, IShapePacks packs, uint256 backing, uint8 kind,
        uint256 fee, uint256 amount) private returns (bool)
    {
        uint256 id = b.idForBacking[backing];
        if (id == 0 || b.receipts[id].kind != 0 || amount > type(uint128).max) return false;
        IFWAView.Listing memory l = IFWAView(address(f)).listings(id);
        // Admission authenticated the pack and ordinary classification; FWA never changes that
        // identity, and a lookup is retired before its pack can leave or relist.
        if (l.depositor != address(this) || l.collection != address(packs) || l.value != backing) return false;
        if (kind == 1) {
            if (l.status != LISTING_SETTLED || f.stuckNFTRecipient(id) != address(0)
                || packs.ownerOf(l.tokenId) != address(f)) return false;
        } else if (l.status != LISTING_WITHDRAWN) return false;
        b.receipts[id] = VaultLib.Receipt(uint128(amount), uint16(fee), kind, true);
        ++b.pendingPlusOne;
        emit VaultLib.CashReceipt(id, kind, amount);
        return true;
    }

    // ------------------------------------------------------------------ keeper pay

    /// @notice Pay the caller for verified work (VaultLib.pay): the least of the quote, `cap`, the account's free ETH and its budget.
    function pay(VaultLib.Strategy storage s, uint256 gasQ, uint256 units, bool essential,
        uint256 minPay, uint256 cap, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        return _pay(s, gasQ, units, essential, minPay, cap, gasStart);
    }

    /// @notice Revert before the work when `minPay` already exceeds what could be paid.
    function precheck(VaultLib.Strategy storage s, uint256 minPay, bool essential) external view {
        _precheckPermission(s, minPay, essential);
    }

    function _pay(VaultLib.Strategy storage s, uint256 gasQ, uint256 units, bool essential,
        uint256 minPay, uint256 cap, uint256 gasStart) private returns (uint256)
    {
        if (s.callerFunded) return 0;
        // Exit work (wind-down / shortfall unlist and liquidate, recovery) is unpaid (owner
        // decision). The work still runs; the caller gets 0 and a nonzero minPay reverts.
        if (essential) {
            if (minPay != 0) revert Payment();
            return 0;
        }
        return VaultLib.pay(s.params, s.budget, gasQ, units, minPay, cap,
            IAccount(address(this)).keeperCash(), gasStart - gasleft());
    }

    function payFunded(VaultLib.Strategy storage s, uint256 gasQ, uint256 units, bool essential,
        uint256 minPay, uint256 fundingCap, uint256 spent) external returns (uint256)
    {
        uint256 gasStart = gasleft() + spent;
        return VaultLib.payFunded(s.params, gasQ, units, essential, minPay, fundingCap, gasStart - gasleft());
    }

    function _precheck(VaultLib.Strategy storage s, uint256 minPay, bool essential) private view {
        if (minPay == 0) return;
        if (essential) revert Payment(); // exit work is unpaid
        VaultLib.precheck(s.params, s.budget, minPay, IAccount(address(this)).keeperCash());
    }

    /// @dev Proceeds-realizing operations check only the budget before the work: requiring cash
    ///      before a withdrawal, redemption or fee sweep would reject funded work.
    function _precheckPermission(VaultLib.Strategy storage s, uint256 minPay, bool essential) private view {
        if (minPay == 0) return;
        if (essential) revert Payment(); // exit work is unpaid
        VaultLib.precheck(s.params, s.budget, minPay, type(uint256).max);
    }
}
