// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReentrancyGuard} from "solady/utils/ReentrancyGuard.sol";
import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {VaultLib} from "./VaultLib.sol";
import {IKeeperPolicy} from "./KeeperPolicy.sol";
import {
    IShapes,
    IShapePacks,
    IFWAV2,
    IFWAView,
    IFWARewards,
    IFWAToken,
    IFloorOracle,
    LISTING_ACTIVE,
    LISTING_ALLOCATED,
    LISTING_WITHDRAWN,
    LISTING_SETTLED
} from "./interfaces/External.sol";

/// @title PackVault
/// @notice Pooled depositor vault for the FWA V2 main pool. It holds Shape packs, lists each at the
///         FWA oracle backing cap, and earns FWA's flat per-listing acquisition fees. Holders own
///         non-transferable internal shares priced at checkpoints.
/// @dev Economics, from FWAV2 source and validated against every historical EarningsAccrued event:
///      a listing with backing B earns expected fees k B before selection, where
///      k = (1 + surcharge)(1 - protocolCut)(1 - crownShare). On selection the purchaser either takes
///      the bid (vault keeps the pack, loses B: net B (k - 1)) or keeps the pack (vault gets
///      B (1 - s) back, loses the pack worth P: net B (k - s) - P). `edgeOk` recomputes k and the cap
///      from live FWA reads, so the vault stops listing by itself when FWA's owner moves a number.
///
///      Keepers are paid from vault ETH (a holder expense, NAV-visible), never from a fee skim.
///      Pay is a quote fixed by the operation and the work it verifiably completed (D56): quoted
///      gas x min(basefee + maxTip, gasCeiling), plus a premium on routine strategy work only,
///      plus `workFee` per unit of work. A caller's gas use, calldata, gas limit or tip never
///      changes it. Checkpoints are funded by charges on the deposit and redemption requests that
///      need them, so holders do not pay for work someone else manufactures. All pay draws on two
///      refilling budgets (routine, essential) bounded in bytecode.
///
///      Trust: FWA, its rewards module, Shapes, ShapePacks and the FWA token are immutable
///      addresses fixed here. FWA's owner can change fees, the floor quote and admission; every
///      such change is read live, never cached. One owner (D59) sets parameters and the keeper
///      policy at once, inside bytecode bounds (D58), pauses and starts wind-down. The owner
///      cannot take assets directly; a compromised owner can raise keeper pay to the bytecode
///      maxima and keep for itself, bounded by the budgets' balance and refill rates.
contract PackVault is ReentrancyGuard {
    using SafeTransferLib for address;

    // ------------------------------------------------------------------ constants

    uint256 internal constant BPS = 10_000;
    uint256 internal constant UNIT = 0.01 ether; // smallest Shape denomination
    uint8 internal constant DENOM_0_1 = 2; // Shapes ladder index of 0.1 ETH
    uint256 internal constant SHAPES_PER_MINT = 10; // one 0.1 Shape splits into ten 0.01 Shapes
    uint256 internal constant INTERVAL = 12 hours; // FWA purchase interval
    uint256 internal constant CROWN_EXIT_WINDOW = 12 hours; // FWA early crown exit window (1% fee)
    uint256 internal constant SCALE = 1e36;

    /// @notice Hard bounds fixed in bytecode. Governance moves parameters only inside them.
    /// Per-call bounds keep work independent of total unchanged inventory.
    uint256 public constant MAX_BATCH = VaultLib.MAX_BATCH;
    uint256 public constant MAX_LIST_BATCH = VaultLib.MAX_LIST_BATCH;
    uint256 public constant MAX_RESTOCK_UNITS = VaultLib.MAX_RESTOCK_UNITS;
    /// Operation ids passed to the keeper policy.
    uint256 internal constant OP_RESTOCK = 1;
    uint256 internal constant OP_LIST = 2;
    uint256 internal constant OP_SYNC = 3;
    // Operation 4 (staged activation) is retired; policy identifiers remain stable.
    uint256 internal constant OP_UNLIST = 5;
    uint256 internal constant OP_LIQUIDATE = 6;
    uint256 internal constant OP_HARVEST = 7;
    uint256 internal constant OP_CHECKPOINT = 8;
    uint256 public constant MAX_WORK_FEE = VaultLib.MAX_WORK_FEE; // per unit of work (D55, D56)
    /// Spending budgets: capacity and refill per day, maxima in bytecode (D56).
    uint256 internal constant MIN_PACK_UNITS = 3; // ShapePacks minimum pack value 0.03 ETH
    uint256 internal constant MIN_DEPOSIT = 0.01 ether;
    uint256 internal constant MIN_DISTRIBUTION = VaultLib.MIN_DISTRIBUTION;
    uint256 public constant DEAD_SHARES = VaultLib.DEAD_SHARES;
    uint256 internal constant MAX_LIQUIDATIONS = MAX_BATCH;

    // ------------------------------------------------------------------ immutables

    IFWAV2 public immutable fwa;
    IShapes public immutable shapes;
    IShapePacks public immutable packs;
    IFWARewards public immutable rewards;
    IFWAToken public immutable token;
    address public immutable owner;
    uint256 public immutable deploymentBlock;

    // ------------------------------------------------------------------ parameters

    // Governed parameters (VaultLib.Params); library code reads them by storage pointer.


    VaultLib.Params internal params;

    // Keeper payment policy (D57): proposes pay for verified work; replaced by the owner at once (D58).
    IKeeperPolicy public keeperPolicy;

    bool public depositsPaused;
    bool public listingPaused;
    bool public windingDown;

    // ------------------------------------------------------------------ positions and inventory

    VaultLib.Book internal book;

    // ------------------------------------------------------------------ shares

    uint256 public totalShares;
    mapping(address => uint256) public sharesOf;

    uint256 public epoch; // checkpoints completed
    uint256 public lastCheckpointInterval;
    uint256 public highWaterMark; // NAV per share, 1e18 scale
    uint256 public lastNav;

    struct PendingDeposit {
        // uint96 holds 7.9e10 ETH, more than exists, so neither field can truncate.
        uint96 amount; // escrowed, deployment charge included
        uint32 epoch; // priced at the checkpoint that ends this epoch
        uint96 charge; // deployment charge: escrowed with the deposit, earns no shares
        uint32 checkpointGwei; // checkpoint charge paid, in gwei (at most ~0.51 ETH at the maxima)
    }

    mapping(address => PendingDeposit) public pendingDeposits;
    uint256 public pendingDepositTotal; // ETH escrowed, excluded from NAV
    uint256 internal pendingChargeTotal; // deployment charges inside pendingDepositTotal
    mapping(uint256 epoch => uint256) internal epochNav; // post-flow NAV used to price deposits
    mapping(uint256 epoch => uint256) internal epochSupply;
    mapping(uint256 epoch => uint256) internal epochDistPerShare; // accumulator when deposits were priced

    // Pro-rata redemption index. Each checkpoint fills fraction f of all locked shares at the
    // checkpoint price; g tracks the surviving fraction, q the ETH paid per original share.
    struct Redemption {
        uint128 shares;
        uint64 era;
        uint256 g0;
        uint256 q0;
    }

    mapping(address => Redemption) public redemptions;
    uint256 public lockedShares;
    uint256 internal redeemEra;
    uint256 internal redeemG = SCALE;
    uint256 internal redeemQ;
    mapping(uint256 era => uint256) internal eraFinalQ;
    uint256 public redemptionReserve; // ETH owed to redeemers, excluded from NAV
    mapping(address => uint256) public claimableEth;
    uint256 public claimableTotal; // settled to holders, not yet paid: a liability like the reserves

    // Distributions: per-share accumulator over all live shares.
    uint256 public distPerShare; // wei x 1e18 per share
    mapping(address => uint256) internal distDebt;
    uint256 public distributionReserve;

    // Keeper pay: request charges held for the next checkpoint, and the two spending budgets.
    uint256 public processingPool; // excluded from NAV until the checkpoint it funds
    VaultLib.Budget internal _budget;

    // ------------------------------------------------------------------ events and errors

    event Deposited(address indexed holder, uint256 amount, uint256 epoch);
    event DepositCancelled(address indexed holder, uint256 amount);
    event RedeemRequested(address indexed holder, uint256 shares);
    event Checkpoint(uint256 indexed epoch, uint256 nav, uint256 supply, uint256 filledShares, uint256 paid, uint256 distributed);
    event Listed(uint256 indexed listingId, uint256 packId, uint256 backing);
    event Resolved(uint256 indexed listingId, uint8 status, bool packReturned);
    event PackOwed(uint256 indexed listingId); // FWA holds the pack as a pull claim; sync retries
    event Liquidated(uint256 packs, uint256 shapes, uint256 ethOut);
    event Unlisted(uint256 indexed listingId);
    event Restocked(uint256 packs, uint256 units);
    event TokensBurned(uint256 amount);
    event KeeperPaid(address indexed keeper, uint256 amount);
    event ParamsSet();
    event PolicyChanged(address indexed oldPolicy, address indexed newPolicy);
    event Claimed(address indexed holder, uint256 amount);
    event WindDownStarted();

    error NotOwner();
    error OutOfBounds();
    error Paused();
    error WindingDown();
    error EdgeGate();
    error NotCheckpointWindow();
    error AlreadyCheckpointed();
    error AllocatedExposure();
    error Amount();
    error Nothing();
    error SyncFirst();
    error Liquidity();
    error UnlistNotAllowed();
    error UnknownNft();
    error Payment();

    // ------------------------------------------------------------------ construction

    constructor(
        IFWAV2 fwa_,
        IShapes shapes_,
        IShapePacks packs_,
        address owner_,
        VaultLib.Params memory initial,
        IKeeperPolicy policy_
    ) payable {
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        rewards = IFWARewards(fwa_.rewards());
        token = IFWAToken(fwa_.token());
        owner = owner_;
        deploymentBlock = block.number;
        book.acquisitionCursor = fwa_.nextSequenceToProcess();
        book.pendingPlusOne = 1;
        params = initial;
        VaultLib.checkBounds(params);
        VaultLib.checkPolicy(address(policy_));
        keeperPolicy = policy_;
        _budget = VaultLib.Budget(uint128(initial.routineCap), uint128(initial.essentialCap), block.timestamp);
        shapes_.setApprovalForAll(address(packs_), true);
        packs_.setApprovalForAll(address(fwa_), true);
        // First issuance: the deployer's seed buys dead shares so the share price cannot be
        // inflated against a later first depositor.
        if (msg.value < MIN_DEPOSIT) revert Amount();
        totalShares = DEAD_SHARES;
        sharesOf[address(0xdead)] = DEAD_SHARES;
        highWaterMark = msg.value * 1e18 / DEAD_SHARES;
    }

    event CashReceipt(uint256 indexed listingId, uint8 outcome, uint256 amount);

    receive() external payable {
        if (msg.sender != address(fwa) || book.controlled) return;
        uint256 fee = fwa.ownerSettlementFeeBps();
        if (fee < BPS) {
            uint256 denominator = BPS - fee;
            if (msg.value % denominator == 0 && msg.value / denominator <= type(uint256).max / BPS) {
                if (_identify(msg.value / denominator * BPS, 1, fee)) return;
            }
        }
        _identify(msg.value, 2, fee);
    }

    function _identify(uint256 backing, uint8 kind, uint256 fee) private returns (bool) {
        uint256 id = book.idForBacking[backing];
        if (id == 0 || book.receipts[id].kind != 0 || msg.value > type(uint128).max) return false;
        IFWAView.Listing memory l = IFWAView(address(fwa)).listings(id);
        // Admission authenticates the original pack and ordinary classification. FWA never
        // changes that identity; a live lookup is retired before its pack can leave/relist.
        if (l.depositor != address(this) || l.collection != address(packs) || l.value != backing) return false;
        if (kind == 1) {
            if (l.status != LISTING_SETTLED || fwa.stuckNFTRecipient(id) != address(0)
                || packs.ownerOf(l.tokenId) != address(fwa)) return false;
        } else if (l.status != LISTING_WITHDRAWN) return false;
        book.receipts[id] = VaultLib.Receipt(uint128(msg.value), uint16(fee), kind, true);
        ++book.pendingPlusOne;
        emit CashReceipt(id, kind, msg.value);
        return true;
    }

    /// @dev Only Shapes and pack NFTs, the only ones the vault creates or gets back from FWA.
    function onERC721Received(address, address, uint256, bytes calldata) external view returns (bytes4) {
        if (msg.sender != address(shapes) && msg.sender != address(packs)) revert UnknownNft();
        return this.onERC721Received.selector;
    }

    // ------------------------------------------------------------------ strategy gate

    /// @notice Live economics from FWA. `backing` is what a new listing would post; zero when the
    ///         gate fails for a pack of `units` x 0.01 ETH.
    function edge(uint256 units) public view returns (uint256, uint256, bool) {
        return VaultLib.edge(params, fwa, address(packs), units, _buildCost(units));
    }

    function _buildCost(uint256 units) internal view returns (uint256) {
        return VaultLib.quote(params, VaultLib.packGas(units) + VaultLib.Q_MINT * units / SHAPES_PER_MINT + VaultLib.Q_LISTED, 2, false)
            + shapes.mintFee() * units / SHAPES_PER_MINT;
    }

    /// @dev Keeper pay for `gasQ` quoted gas and `units` of work: priced at basefee + maxTip,
    ///      capped at the ceiling, never at the caller's own gas price; premium on routine work.
    function _quote(uint256 gasQ, uint256 units, bool essential) internal view returns (uint256) {
        return VaultLib.quote(params, gasQ, units, essential);
    }

    // ------------------------------------------------------------------ inventory

    /// @notice Build `count` packs of `units` x 0.01 ETH: mint 0.1 ETH Shapes, split each into ten
    ///         0.01 Shapes (one mint fee per ten units), then pack them. Only when every new pack
    ///         can be listed right away and its build cost is repaid by one bid cycle.
    function restock(uint256 units, uint256[] calldata backingProposals, uint256 minPay)
        external nonReentrant returns (uint256)
    {
        _requireOperating();
        _precheck(minPay, false);
        if (listingPaused) revert Paused();
        uint256 count = backingProposals.length;
        uint256 mints = VaultLib.restock(params, book, fwa, packs, shapes, units, backingProposals, _idle());
        emit Restocked(count, units);
        return _pay(OP_RESTOCK, VaultLib.Q_RESTOCK + count * VaultLib.packGas(units) + mints * VaultLib.Q_MINT, count, false, minPay, type(uint256).max);
    }

    /// @notice Admit bounded offchain backing proposals, checked against live economics.
    function list(uint256[] calldata backingProposals, uint256 minPay) external nonReentrant returns (uint256) {
        _requireOperating();
        _precheck(minPay, false);
        if (listingPaused) revert Paused();
        if (backingProposals.length > MAX_LIST_BATCH) revert Amount();
        if (fwa.unsettledAcquisitionCount() != 0) revert Nothing();
        uint256 listed;
        while (listed < backingProposals.length && book.idlePacks.length != 0) {
            uint256 packId = book.idlePacks[book.idlePacks.length - 1];
            uint256 units = book.idleValueOf[packId] / UNIT;
            uint256 backing = backingProposals[listed];
            VaultLib.validateBacking(params, book, fwa, address(packs), units, backing, _buildCost(units), false);
            if (_idle() < backing) break;
            uint256 id = VaultLib.admit(book, fwa, packs, packId, backing);
            emit Listed(id, packId, backing);
            ++listed;
        }
        if (listed == 0) revert Nothing();
        return _pay(OP_LIST, VaultLib.Q_LIST + listed * VaultLib.Q_LISTED, listed, false, minPay, type(uint256).max);
    }

    /// @notice Process a full bounded journal job, independent terminal IDs and head cleanup.
    function sync(uint256[] calldata listingIds, uint256 witnessId, uint256 minPay)
        external nonReentrant returns (uint256)
    {
        uint256 checkpointMode;
        if (block.timestamp / INTERVAL != lastCheckpointInterval) {
            checkpointMode = pendingDepositTotal != 0 || lockedShares != 0 ? 1 : params.distributionBps != 0 ? 2 : 0;
        }
        (uint256 gasQ, uint256 units) = VaultLib.syncChanges(params, book, fwa, packs, listingIds, checkpointMode, witnessId);
        return _pay(OP_SYNC, gasQ, units, false, minPay, type(uint256).max);
    }

    /// @notice Withdraw active listings: allowed in wind-down, when FWA's live fees leave no edge
    ///         (k below 1 + minEdge), or to cover locked redemptions free ETH and inventory cannot.
    ///         A stale quote or a gas spike stops new listings but never unwinds earning ones.
    function unlist(uint256[] calldata listingIds, uint256 minPay) external nonReentrant returns (uint256) {
        if (listingIds.length > MAX_BATCH) revert Amount();
        uint256 shortfall = _redemptionShortfall();
        // Essential when it frees ETH for redeemers or winds down; routine when only the edge failed.
        // Exits never read FWA's economics: a broken or hostile oracle or fee cannot block them.
        bool essential = windingDown || shortfall != 0;
        bool ok = true;
        if (!essential) {
            (uint256 k,,) = edge(MIN_PACK_UNITS);
            if (k >= 1e18 + uint256(params.minEdgeBps) * 1e14) revert UnlistNotAllowed();
            ok = false;
        }
        _precheck(minPay, essential);
        uint256 realized;
        uint256 moved;
        for (uint256 i; i < listingIds.length; ++i) {
            uint256 id = listingIds[i];
            if (book.openIndex[id] == 0) continue;
            // An early crown exit costs 1% of backing; wait out the crown window instead.
            if (fwa.topListingId() == id && block.timestamp < fwa.topListingSince() + CROWN_EXIT_WINDOW) continue;
            (,,,,,,,,,, uint8 status) = fwa.listings(id);
            if (status != LISTING_ACTIVE) continue;
            VaultLib.Position memory pos = book.positions[id];
            VaultLib.withdraw(book, fwa, packs, id);
            emit Unlisted(id);
            realized += pos.backing + pos.value;
            ++moved;
            if (!windingDown && ok && realized >= shortfall) break;
        }
        if (realized == 0) revert Nothing();
        return _pay(OP_UNLIST, VaultLib.Q_UNLIST + moved * VaultLib.Q_UNLISTED, moved, essential, minPay, type(uint256).max);
    }

    /// @notice Pull FWA fees into the vault: pending fees of `activeIds` (they keep earning) and
    ///         credited fees of resolved listings. Paid only if the pay is a small share of it.
    ///         Gas is quoted only for the vault's own listings that had fees to claim.
    function harvest(uint256[] calldata activeIds, uint256 minPay) external nonReentrant returns (uint256) {
        uint256 before = address(this).balance;
        uint256 n = VaultLib.harvest(book, fwa, activeIds);
        uint256 amount = address(this).balance - before;
        if (amount == 0) revert Nothing();
        // Optional work: paid only when the quote is at most keeperShareBps of the fees collected.
        uint256 g = VaultLib.Q_HARVEST + n * VaultLib.Q_HARVESTED;
        return _pay(OP_HARVEST, g, 0, false, minPay, _quote(g, 0, false) * BPS > amount * params.keeperShareBps ? 0 : type(uint256).max);
    }

    function _harvest() internal {
        VaultLib.harvestCredit(book, fwa);
    }

    // ------------------------------------------------------------------ FWA token rewards

    /// @notice Claim depositor FWA token rewards (pending on `activeIds`, plus credit from removed
    ///         or repriced listings) and burn every FWA token the vault holds. Holders get no
    ///         token value: tokens never count in NAV and the vault never sells them. Unpaid:
    ///         burning realizes nothing for holders to reimburse from.
    function burnTokens(uint256[] calldata activeIds) external nonReentrant {
        if (activeIds.length > MAX_BATCH) revert Amount();
        // FWA's claim reverts for the whole batch on one listing that is no longer active, or
        // when nothing is pending. Neither may block the credit withdrawal or the burn.
        if (activeIds.length != 0) try rewards.claimDepositorTokens(activeIds) {} catch {}
        if (rewards.tokenCredit(address(this)) != 0) rewards.withdrawTokens();
        uint256 amount = token.balanceOf(address(this));
        if (amount == 0) revert Nothing();
        token.burn(amount);
        emit TokensBurned(amount);
    }

    // ------------------------------------------------------------------ holders

    /// @notice Escrow ETH to buy shares at the next checkpoint. Cancellable until then. The
    ///         request charge (`requestCharge()`) is kept from `msg.value` to fund that checkpoint.
    function deposit() external payable nonReentrant {
        if (depositsPaused) revert Paused();
        if (windingDown) revert WindingDown();
        // Charges: the checkpoint (to the pool, kept on cancel) and building and listing positions
        // with this ETH (escrowed with the deposit and refunded on cancel; at pricing it joins the
        // vault's value, which pays for that work, and earns the depositor no shares).
        uint256 ck = requestCharge();
        if (msg.value < MIN_DEPOSIT + ck) revert Amount();
        uint256 amount = msg.value - ck;
        uint256 deploy = deployCharge();
        uint256 charge = amount * deploy / (VaultLib.POSITION_VALUE + deploy);
        if (lastNav + pendingDepositTotal + amount > params.tvlCap) revert Amount();
        _settleHolder(msg.sender);
        processingPool += ck;
        PendingDeposit storage d = pendingDeposits[msg.sender];
        d.amount += uint96(amount);
        d.charge += uint96(charge);
        d.epoch = uint32(epoch);
        d.checkpointGwei += uint32(ck / 1 gwei);
        pendingDepositTotal += amount;
        pendingChargeTotal += charge;
        emit Deposited(msg.sender, amount, epoch);
    }

    function cancelDeposit() external nonReentrant {
        _settleHolder(msg.sender);
        PendingDeposit memory d = pendingDeposits[msg.sender];
        uint256 amount = d.amount;
        if (amount == 0) revert Nothing();
        delete pendingDeposits[msg.sender];
        pendingDepositTotal -= amount;
        pendingChargeTotal -= d.charge;
        // Refund the checkpoint charge, keeping the pool funded for any flows still waiting.
        uint256 keep = pendingDepositTotal != 0 || lockedShares != 0 ? VaultLib.requestCharge(params) : 0;
        uint256 back = M.min(uint256(d.checkpointGwei) * 1 gwei, processingPool > keep ? processingPool - keep : 0);
        processingPool -= back;
        msg.sender.forceSafeTransferETH(amount + back);
        emit DepositCancelled(msg.sender, amount + back);
    }

    /// @notice Lock shares for redemption. Filled pro rata at checkpoints as ETH frees up; the
    ///         unfilled part stays exposed to the vault until filled. Send at least
    ///         `requestCharge()`: it funds the checkpoint; any excess is returned.
    function requestRedeem(uint256 amount) external payable nonReentrant {
        _settleHolder(msg.sender);
        if (amount == 0 || amount > sharesOf[msg.sender]) revert Amount();
        // Charges: the checkpoint (to the pool) and unwinding positions worth the shares' value
        // (to the vault, which pays for that work).
        uint256 ck = requestCharge();
        uint256 charge = ck + M.mulDiv(M.mulDiv(amount, lastNav, totalShares), unwindCharge(), VaultLib.POSITION_VALUE);
        if (msg.value < charge) revert Amount();
        processingPool += ck;
        if (msg.value > charge) msg.sender.forceSafeTransferETH(msg.value - charge);
        _settleDist(msg.sender);
        sharesOf[msg.sender] -= amount;
        distDebt[msg.sender] = sharesOf[msg.sender] * distPerShare / 1e18;
        Redemption storage r = redemptions[msg.sender];
        r.shares += uint128(amount);
        lockedShares += amount;
        emit RedeemRequested(msg.sender, amount);
    }

    /// @notice Withdraw redeemed ETH and distributions.
    function claim() external nonReentrant {
        _settleHolder(msg.sender);
        _settleDist(msg.sender);
        uint256 amount = claimableEth[msg.sender];
        if (amount == 0) revert Nothing();
        claimableEth[msg.sender] = 0;
        claimableTotal -= amount;
        msg.sender.forceSafeTransferETH(amount);
        emit Claimed(msg.sender, amount);
    }

    /// @dev Convert a priced deposit to shares and apply redemption fills. Idempotent.
    function _settleHolder(address h) internal {
        PendingDeposit memory d = pendingDeposits[h];
        if (d.amount != 0 && d.epoch < epoch) {
            _settleDist(h);
            uint256 minted = uint256(d.amount - d.charge) * epochSupply[d.epoch] / epochNav[d.epoch];
            sharesOf[h] += minted;
            // New shares earn every distribution after their pricing, even if converted later.
            distDebt[h] += minted * epochDistPerShare[d.epoch] / 1e18;
            delete pendingDeposits[h];
        }
        Redemption storage r = redemptions[h];
        if (r.shares == 0) {
            r.era = uint64(redeemEra);
            r.g0 = redeemG;
            r.q0 = redeemQ;
            return;
        }
        uint256 paid;
        uint256 remaining;
        if (r.era < redeemEra) {
            paid = M.mulDiv(r.shares, eraFinalQ[r.era] - r.q0, r.g0);
        } else {
            paid = M.mulDiv(r.shares, redeemQ - r.q0, r.g0);
            remaining = M.mulDiv(r.shares, redeemG, r.g0);
        }
        if (paid != 0) {
            redemptionReserve -= paid;
            claimableEth[h] += paid;
            claimableTotal += paid;
        }
        r.shares = uint128(remaining);
        r.era = uint64(redeemEra);
        r.g0 = redeemG;
        r.q0 = redeemQ;
    }

    function _settleDist(address h) internal {
        uint256 owed = sharesOf[h] * distPerShare / 1e18 - distDebt[h];
        if (owed != 0) {
            distributionReserve -= owed;
            claimableEth[h] += owed;
            claimableTotal += owed;
            distDebt[h] += owed;
        }
    }

    // ------------------------------------------------------------------ checkpoint

    /// @notice Price the vault and settle flows. Only during FWA's purchase blackout with its
    ///         acquisition queue drained: no listing can be selected until the blackout ends, so
    ///         every Active position is worth exactly what a withdrawal would return.
    ///         Paid at cost plus one work unit, from the request charges of the flows it settles
    ///         (`processingPool`); with no flows, from the routine budget for a distribution.
    function checkpoint(uint256 witnessId, uint256 minPay) external nonReentrant returns (uint256) {
        IFWAV2 f = fwa;
        if (!f.isPurchaseBlackout() || f.unsettledAcquisitionCount() != 0) revert NotCheckpointWindow();
        uint256 interval = block.timestamp / INTERVAL;
        if (interval == lastCheckpointInterval) revert AlreadyCheckpointed();
        // Only with holder flows to settle, or with distributions on: a no-op checkpoint would
        // use up the interval's one slot and delay flows that arrive later in the blackout.
        bool work = pendingDepositTotal != 0 || lockedShares != 0;
        if (!work && params.distributionBps == 0) revert Nothing();
        bool essential = lockedShares != 0 || windingDown;
        if (!work) _precheck(minPay, essential); // with flows, the charge pool pays (no budget)
        lastCheckpointInterval = interval;
        uint256 gasQ = VaultLib.Q_CHECKPOINT;

        (uint256 oldest, uint64 allocatedAt) = VaultLib.oldestAllocation(book);
        if (oldest != 0 && block.timestamp >= uint256(allocatedAt) + f.settlementWindow()) revert SyncFirst();
        _harvest();
        uint256 nav = VaultLib.checkpointNav(book, f, packs, _free(), witnessId);
        if (book.allocatedValue * BPS > nav * params.allocatedBoundBps) revert AllocatedExposure();

        uint256 supply = totalShares;
        // 1. Redemptions at the pre-flow price, funded by free ETH and new deposits. Inventory is
        //    turned into ETH beforehand by `liquidate`, so this call stays bounded.
        uint256 filled;
        uint256 paid;
        if (lockedShares != 0) {
            uint256 frac;
            uint256 unit;
            (frac, filled, unit, paid) = VaultLib.fill(lockedShares, nav, supply, _free() + pendingDepositTotal);
            redeemQ += M.mulDiv(redeemG, unit, SCALE);
            if (frac == SCALE) {
                eraFinalQ[redeemEra] = redeemQ;
                ++redeemEra;
                redeemG = SCALE;
                redeemQ = 0;
                lockedShares = 0;
            } else {
                redeemG = M.mulDiv(redeemG, SCALE - frac, SCALE);
                lockedShares -= filled;
            }
            redemptionReserve += paid;
            totalShares = supply - filled;
            nav -= paid;
            supply -= filled;
        }

        // 2. Distribution of new gains, only when no shares are waiting to exit.
        uint256 distributed;
        uint256 perShare = nav * 1e18 / supply;
        if (lockedShares == 0 && supply > DEAD_SHARES && perShare > highWaterMark && params.distributionBps != 0) {
            uint256 gain = M.mulDiv(perShare - highWaterMark, supply, 1e18);
            distributed = M.min(gain * params.distributionBps / BPS, _idle());
            if (distributed >= MIN_DISTRIBUTION) {
                // Live shares only: the dead seed shares never claim, so their slice would strand.
                distPerShare += distributed * 1e18 / (supply - DEAD_SHARES);
                distributionReserve += distributed;
                nav -= distributed;
            } else {
                distributed = 0;
            }
        }
        perShare = nav * 1e18 / supply;
        if (perShare > highWaterMark) highWaterMark = perShare;

        // 3. Deposits at the post-flow price.
        epochNav[epoch] = nav;
        epochSupply[epoch] = supply;
        epochDistPerShare[epoch] = distPerShare;
        if (pendingDepositTotal != 0) {
            totalShares += (pendingDepositTotal - pendingChargeTotal) * supply / nav;
            nav += pendingDepositTotal;
            pendingDepositTotal = 0;
            pendingChargeTotal = 0;
            // Deployment charges lift NAV per share; that is not a gain to distribute.
            perShare = nav * 1e18 / totalShares;
            if (perShare > highWaterMark) highWaterMark = perShare;
        }
        lastNav = nav;
        emit Checkpoint(epoch, nav, totalShares, filled, paid, distributed);
        ++epoch;
        if (work) {
            // Pay comes out of the request charges; what is left over joins the vault's ETH.
            uint256 pool = processingPool;
            processingPool = 0;
            return _pay(OP_CHECKPOINT, gasQ, 1, essential, minPay, pool);
        }
        if (distributed != 0) return _pay(OP_CHECKPOINT, gasQ, 1, false, minPay, type(uint256).max);
        // No flows and nothing distributed: revert, so the interval's one slot stays free (audit E3).
        revert Nothing();
    }

    /// @notice Redeem up to `maxCount` idle packs (then loose Shapes) to ETH at their exact
    ///         backing, while locked redemptions exceed free ETH, or freely in wind-down.
    function liquidate(uint256 maxCount, uint256 minPay) external nonReentrant returns (uint256) {
        if (!windingDown && _owedEstimate() <= _free() + pendingDepositTotal) revert Nothing();
        _precheck(minPay, true);
        maxCount = M.min(maxCount, MAX_LIQUIDATIONS);
        uint256 before = address(this).balance;
        uint256 supplyBefore = shapes.totalSupply();
        uint256 n;
        uint256 m;
        uint256 units;
        uint256 recovery;
        uint256 recoveryGas;
        while (n + m + recovery < maxCount && (windingDown || _owedEstimate() > _free() + pendingDepositTotal)) {
            if (book.idlePacks.length != 0) {
                uint256 packId = book.idlePacks[book.idlePacks.length - 1];
                uint256 value = book.idleValueOf[packId];
                if (units + value / UNIT > MAX_RESTOCK_UNITS) break;
                units += value / UNIT;
                VaultLib.redeemInventory(book, packId);
                packs.redeem(packId);
                ++n;
            } else if (book.looseShapes.length != 0) {
                if (++units > MAX_RESTOCK_UNITS) break;
                book.trackedValue -= UNIT;
                book.idleValue -= UNIT;
                shapes.redeem(book.looseShapes[book.looseShapes.length - 1]);
                book.looseShapes.pop();
                ++m;
            } else if (book.recoveryPacks.length != 0) {
                if (n + m != 0) break;
                // Recovery is one isolated chunk of at most 30 underlying Shapes.
                recoveryGas = VaultLib.recoverInventory(book, packs, shapes);
                ++recovery;
                break;
            } else {
                break;
            }
        }
        if (n + m + recovery == 0) revert Nothing();
        // Ordinary packs can contain larger denominations. Pay only for their actual burns.
        // Recovery is isolated from this loop, and loose Shapes each contribute one burn.
        uint256 packShapes = n == 0 ? 0 : supplyBefore - shapes.totalSupply() - m;
        if (n != 0 && (packShapes == 0 || packShapes + m > MAX_RESTOCK_UNITS)) revert Amount();
        emit Liquidated(n + recovery, m, address(this).balance - before);
        return _pay(OP_LIQUIDATE, VaultLib.Q_LIQUIDATE + n * VaultLib.Q_LIQ_PACK + packShapes * VaultLib.Q_REDEEM_SHAPE + m * VaultLib.Q_LIQ_SHAPE + recoveryGas, n + m + recovery, true, minPay, type(uint256).max);
    }

    /// @dev ETH locked shares will need at the last checkpoint's price, rounded up.
    function _owedEstimate() internal view returns (uint256) {
        if (lockedShares == 0) return 0;
        return M.mulDivUp(lockedShares, lastNav, totalShares);
    }

    function _redemptionShortfall() internal view returns (uint256) {
        uint256 owed = _owedEstimate();
        uint256 inventory = _free() + book.idleValue;
        return owed > inventory ? owed - inventory : 0;
    }

    /// @dev The vault's own ETH: balance less escrowed deposits and every amount owed to holders,
    ///      whether still in a shared reserve or already settled to a holder's claimable balance.
    ///      Request charges held for the next checkpoint are excluded too. Forced ETH lands here,
    ///      so it is attributed by balance, never by callback.
    function _free() internal view returns (uint256) {
        uint256 owed = pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool;
        uint256 bal = address(this).balance;
        return bal > owed ? bal - owed : 0;
    }

    /// @dev ETH the strategy may spend: free ETH above the reserve and above what locked
    ///      redemptions will need, so ETH freed for redeemers cannot be relisted.
    function _idle() internal view returns (uint256) {
        uint256 free = _free();
        uint256 keep = params.reserve + _owedEstimate();
        return free > keep ? free - keep : 0;
    }

    // ------------------------------------------------------------------ keeper pay

    /// @notice What a deposit or redemption request is charged now: what tops `processingPool` up
    ///         to one checkpoint at its quote (cost plus one work unit), rounded up to whole gwei;
    ///         0 when the pool already holds it. Requests in one interval share one checkpoint.
    function requestCharge() public view returns (uint256) {
        uint256 full = VaultLib.requestCharge(params);
        uint256 topUp = full > processingPool ? full - processingPool : 0;
        return (topUp + 1 gwei - 1) / 1 gwei * 1 gwei;
    }

    /// @notice Deployment charge per VaultLib.POSITION_VALUE deposited: building and listing one position at
    ///         its quote now plus its Shapes mint fee share, and never less than the keeper margin
    ///         that building it can pay out at any gas price.
    function deployCharge() public view returns (uint256) {
        return VaultLib.deployCharge(params, shapes.mintFee());
    }

    /// @notice Unwind charge per VaultLib.POSITION_VALUE redeemed: unlisting and liquidating one position.
    function unwindCharge() public view returns (uint256) {
        return VaultLib.unwindCharge(params);
    }

    /// @dev Pay the caller for completed work. The vault states the facts (operation, units,
    ///      quoted gas); the active policy proposes the pay in a bounded-gas staticcall whose
    ///      failure or malformed answer counts as zero. The vault pays the least of that offer,
    ///      its own envelope (`_quote`, the most this work may ever cost), `cap` (a funding source
    ///      such as request charges), free ETH and the budget. Below `minPay` the whole call
    ///      reverts; with `minPay` 0 the work is done for whatever is paid (VaultLib.pay).
    function _pay(uint256 op, uint256 gasQ, uint256 units, bool essential, uint256 minPay, uint256 cap)
        internal
        returns (uint256)
    {
        return VaultLib.pay(params, _budget, address(keeperPolicy), op, gasQ, units, essential, minPay, cap, _free());
    }

    /// @dev Revert before the work when `minPay` already exceeds what could be paid.
    function _precheck(uint256 minPay, bool essential) internal view {
        if (minPay != 0) VaultLib.precheck(params, _budget, minPay, essential, _free());
    }

    /// @dev Budget levels now: each refills at its rate since the last update, never above its cap.
    function _budgetNow() internal view returns (uint256, uint256) {
        return VaultLib.budgetNow(params, _budget);
    }

    function _syncBudget() internal {
        VaultLib.syncBudget(params, _budget);
    }

    /// @dev No gas-price gate: above `gasCeiling` a call is still accepted and its quote is priced
    ///      at the ceiling; the caller covers the rest (D51).
    function _requireOperating() internal view {
        if (windingDown) revert WindingDown();
    }

    // ------------------------------------------------------------------ roles

    /// @notice Owner sets parameters at once, within the bytecode bounds (D58: no delay).
    function setParams(VaultLib.Params calldata p) external {
        if (msg.sender != owner) revert NotOwner();
        // Budgets accrue at the old rates up to now; the new caps then only clamp, never refill.
        _syncBudget();
        params = p;
        VaultLib.checkBounds(params);
        _syncBudget();
        emit ParamsSet();
    }

    /// @notice Owner replaces the keeper payment policy at once (D57, D58). The vault still caps
    ///         every offer at its envelope, free ETH and budget.
    function setPolicy(address policy) external {
        if (msg.sender != owner) revert NotOwner();
        VaultLib.checkPolicy(policy);
        emit PolicyChanged(address(keeperPolicy), policy);
        keeperPolicy = IKeeperPolicy(policy);
    }

    /// @notice Owner pauses or resumes deposits and listing. Wind-down is one-way.
    function guard(bool pauseDeposits, bool pauseListing) external {
        if (msg.sender != owner) revert NotOwner();
        (depositsPaused, listingPaused) = (pauseDeposits, pauseListing);
    }

    function startWindDown() external {
        if (msg.sender != owner) revert NotOwner();
        windingDown = true;
        depositsPaused = true;
        listingPaused = true;
        emit WindDownStarted();
    }


    // ------------------------------------------------------------------ views

    function getParams() external view returns (VaultLib.Params memory) {
        return params;
    }

    function openListingCount() external view returns (uint256) { return book.open.length; }
    function openListingAt(uint256 index) external view returns (uint256) { return book.open[index]; }
    function idlePackCount() external view returns (uint256) { return book.idlePacks.length; }
    function idlePackAt(uint256 index) external view returns (uint256) { return book.idlePacks[index]; }
    function recoveryPackCount() external view returns (uint256) { return book.recoveryPacks.length; }
    function recoveryPackAt(uint256 index) external view returns (uint256) { return book.recoveryPacks[index]; }
    function recoveryUnsealed(uint256 id) external view returns (bool) { return book.recoveryUnsealed[id]; }
    function looseShapeCount() external view returns (uint256) { return book.looseShapes.length; }
    function position(uint256 id) external view returns (VaultLib.Position memory) { return book.positions[id]; }
    function idleValueOf(uint256 id) external view returns (uint256) { return book.idleValueOf[id]; }
    function idleFunding() external view returns (uint256) { return book.idleFunding; }
    function acquisitionCursor() external view returns (uint64) { return book.acquisitionCursor; }
    function pendingReceipts() external view returns (uint256) { return book.pendingPlusOne - 1; }
    function reservedCount() external view returns (uint256) { return book.reservedCount; }
    function idForBacking(uint256 backing) external view returns (uint256) { return book.idForBacking[backing]; }
    function receipts(uint256 id) external view returns (VaultLib.Receipt memory) { return book.receipts[id]; }
    function debtCount(uint256 debt) external view returns (uint256) { return book.countByDebt[debt]; }
    function totals() external view returns (uint256 tracked, uint256 idle, uint256 backing, uint256 active, uint256 debt, uint256 allocated) {
        return (book.trackedValue, book.idleValue, book.activeBacking, book.activeCount, book.feeDebtSum, book.allocatedValue);
    }
    function allocationState() external view returns (uint256 head, uint256 length, uint256 id, uint64 at, bool stale) {
        head = book.allocationHead;
        length = book.allocationQueue.length;
        if (head != length) {
            id = book.allocationQueue[head];
            at = book.positions[id].allocatedAt;
            stale = book.positions[id].state != VaultLib.ALLOCATED;
        }
    }
    function accountedNav(uint256 witnessId) external view returns (uint256) {
        return VaultLib.accountedNav(book, fwa, packs, _free(), witnessId);
    }

    /// @notice Shares including a deposit already priced but not yet converted (lazy).
    function shareBalance(address h) external view returns (uint256 shares) {
        shares = sharesOf[h];
        PendingDeposit memory d = pendingDeposits[h];
        if (d.amount != 0 && d.epoch < epoch) shares += uint256(d.amount - d.charge) * epochSupply[d.epoch] / epochNav[d.epoch];
    }

    function idleEth() external view returns (uint256) {
        return _idle();
    }
    function freeEth() external view returns (uint256) {
        return _free();
    }

    /// @notice Keeper budget available now: routine (strategy) and essential (redemption, wind-down).
    function budget() external view returns (uint256 routine, uint256 essential) {
        return _budgetNow();
    }
}
