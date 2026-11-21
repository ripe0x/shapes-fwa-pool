// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {PackAccount} from "./PackAccount.sol";
import {VaultLib} from "./VaultLib.sol";
import {StrategyLib} from "./StrategyLib.sol";
import {IKeeperPolicy} from "./KeeperPolicy.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @title PackVault
/// @notice Pooled depositor vault for the FWA V2 main pool. It runs the shared pack strategy
///         (PackAccount: build, list, sync, unlist, liquidate) and adds only multi-depositor
///         ownership: non-transferable internal shares priced at checkpoints, escrowed deposits,
///         pro-rata redemptions, distributions, holder liabilities and wind-down.
/// @dev Economics, from FWAV2 source and validated against every historical EarningsAccrued event:
///      a listing with backing B earns expected fees k B before selection, where
///      k = (1 + surcharge)(1 - protocolCut)(1 - crownShare). On selection the purchaser either keeps
///      the pack (the vault gets B (1 - s) back: net B (k - s) - P, and builds a replacement) or takes
///      the bid (the vault keeps the pack, loses B: net B (k - 1)). Backing is set so keeping wins
///      for the purchaser (VaultLib.edge).
///
///      Keepers are paid from vault ETH (a holder expense, NAV-visible), never from a fee skim, by
///      quote (D56). Checkpoints are funded by charges on the deposit and redemption requests that
///      need them, so holders do not pay for work someone else manufactures.
///
///      Trust: FWA, its rewards module, Shapes, ShapePacks and the FWA token are immutable
///      addresses fixed here. FWA's owner can change fees, the floor quote and admission; every
///      such change is read live, never cached. One owner (D59; transferable, never renounced,
///      D76) sets parameters and the keeper policy at once, inside bytecode bounds (D58), pauses
///      and starts wind-down. The owner cannot take assets directly; a compromised owner can raise
///      keeper pay to the bytecode maxima and keep for itself, bounded by the budgets.
contract PackVault is PackAccount {
    using SafeTransferLib for address;

    uint256 internal constant BPS = 10_000;
    uint256 internal constant INTERVAL = 12 hours; // FWA purchase interval
    uint256 internal constant SCALE = 1e36;
    uint256 internal constant OP_CHECKPOINT = 8;
    uint256 internal constant MIN_DEPOSIT = 0.01 ether;
    uint256 internal constant MIN_DISTRIBUTION = VaultLib.MIN_DISTRIBUTION;
    uint256 public constant DEAD_SHARES = VaultLib.DEAD_SHARES;

    bool public depositsPaused;

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

    // Request charges held for the next checkpoint.
    uint256 public processingPool; // excluded from NAV until the checkpoint it funds

    // ------------------------------------------------------------------ events and errors

    event Deposited(address indexed holder, uint256 amount, uint256 epoch);
    event DepositCancelled(address indexed holder, uint256 amount);
    event RedeemRequested(address indexed holder, uint256 shares);
    event Checkpoint(uint256 indexed epoch, uint256 nav, uint256 supply, uint256 filledShares, uint256 paid, uint256 distributed);
    event Claimed(address indexed holder, uint256 amount);
    event WindDownStarted();

    error Paused();
    error WindingDown();
    error NotCheckpointWindow();
    error AlreadyCheckpointed();
    error AllocatedExposure();
    error Amount();
    error Nothing();
    error SyncFirst();

    // ------------------------------------------------------------------ construction

    constructor(
        IFWAV2 fwa_,
        IShapes shapes_,
        IShapePacks packs_,
        address owner_,
        VaultLib.Params memory initial,
        IKeeperPolicy policy_
    ) payable PackAccount(fwa_, shapes_, packs_) {
        _initStrategy(owner_, initial, address(policy_));
        // First issuance: the deployer's seed buys dead shares so the share price cannot be
        // inflated against a later first depositor.
        if (msg.value < MIN_DEPOSIT) revert Amount();
        totalShares = DEAD_SHARES;
        sharesOf[address(0xdead)] = DEAD_SHARES;
        highWaterMark = msg.value * 1e18 / DEAD_SHARES;
    }

    // ------------------------------------------------------------------ account hooks

    function _checkpointMode() internal view override returns (uint256) {
        if (block.timestamp / INTERVAL == lastCheckpointInterval) return 0;
        return pendingDepositTotal != 0 || lockedShares != 0 ? 1 : s.params.distributionBps != 0 ? 2 : 0;
    }

    /// @dev ETH locked redemptions need beyond free ETH and idle inventory.
    function _shortfall() internal view override returns (uint256) {
        uint256 owed = _owedEstimate();
        uint256 inventory = _free() + s.book.idleValue;
        return owed > inventory ? owed - inventory : 0;
    }

    /// @dev ETH locked redemptions need beyond free ETH and new deposits.
    function _need() internal view override returns (uint256) {
        uint256 owed = _owedEstimate();
        uint256 liquid = _free() + pendingDepositTotal;
        return owed > liquid ? owed - liquid : 0;
    }

    /// @dev The vault's own ETH: balance less escrowed deposits and every amount owed to holders,
    ///      whether still in a shared reserve or already settled to a holder's claimable balance.
    ///      Request charges held for the next checkpoint are excluded too. Forced ETH lands here,
    ///      so it is attributed by balance, never by callback.
    function _free() internal view override returns (uint256) {
        uint256 owed = pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal + processingPool;
        uint256 bal = address(this).balance;
        return bal > owed ? bal - owed : 0;
    }

    /// @dev ETH the strategy may spend: free ETH above the reserve and above what locked
    ///      redemptions will need, so ETH freed for redeemers cannot be relisted.
    function _idle() internal view override returns (uint256) {
        uint256 free = _free();
        uint256 keep = s.params.reserve + _owedEstimate();
        return free > keep ? free - keep : 0;
    }

    /// @dev ETH locked shares will need at the last checkpoint's price, rounded up.
    function _owedEstimate() internal view returns (uint256) {
        if (lockedShares == 0) return 0;
        return M.mulDivUp(lockedShares, lastNav, totalShares);
    }

    // ------------------------------------------------------------------ holders

    /// @notice Escrow ETH to buy shares at the next checkpoint. Cancellable until then. The
    ///         request charge (`requestCharge()`) is kept from `msg.value` to fund that checkpoint.
    function deposit() external payable nonReentrant {
        if (depositsPaused) revert Paused();
        if (s.windingDown) revert WindingDown();
        // Charges: the checkpoint (to the pool, kept on cancel) and building and listing positions
        // with this ETH (escrowed with the deposit and refunded on cancel; at pricing it joins the
        // vault's value, which pays for that work, and earns the depositor no shares).
        uint256 ck = requestCharge();
        if (msg.value < MIN_DEPOSIT + ck) revert Amount();
        uint256 amount = msg.value - ck;
        uint256 deploy = deployCharge();
        uint256 charge = amount * deploy / (VaultLib.POSITION_VALUE + deploy);
        if (lastNav + pendingDepositTotal + amount > s.params.tvlCap) revert Amount();
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
        uint256 keep = pendingDepositTotal != 0 || lockedShares != 0 ? VaultLib.requestCharge(s.params) : 0;
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
        if (!work && s.params.distributionBps == 0) revert Nothing();
        bool essential = lockedShares != 0 || s.windingDown;
        if (!work) StrategyLib.precheck(s, minPay, essential); // with flows, the charge pool pays (no budget)
        lastCheckpointInterval = interval;

        (uint256 oldest, uint64 allocatedAt) = VaultLib.oldestAllocation(s.book);
        if (oldest != 0 && block.timestamp >= uint256(allocatedAt) + f.settlementWindow()) revert SyncFirst();
        VaultLib.harvestCredit(s.book, f);
        uint256 nav = VaultLib.checkpointNav(s.book, f, packs, _free(), witnessId);
        if (s.book.allocatedValue * BPS > nav * s.params.allocatedBoundBps) revert AllocatedExposure();

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
        if (lockedShares == 0 && supply > DEAD_SHARES && perShare > highWaterMark && s.params.distributionBps != 0) {
            uint256 gain = M.mulDiv(perShare - highWaterMark, supply, 1e18);
            distributed = M.min(gain * s.params.distributionBps / BPS, _idle());
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
            return StrategyLib.pay(s, OP_CHECKPOINT, VaultLib.Q_CHECKPOINT, 1, essential, minPay, pool);
        }
        if (distributed != 0) {
            return StrategyLib.pay(s, OP_CHECKPOINT, VaultLib.Q_CHECKPOINT, 1, false, minPay, type(uint256).max);
        }
        // No flows and nothing distributed: revert, so the interval's one slot stays free (audit E3).
        revert Nothing();
    }

    // ------------------------------------------------------------------ charges

    /// @notice What a deposit or redemption request is charged now: what tops `processingPool` up
    ///         to one checkpoint at its quote (cost plus one work unit), rounded up to whole gwei;
    ///         0 when the pool already holds it. Requests in one interval share one checkpoint.
    function requestCharge() public view returns (uint256) {
        uint256 full = VaultLib.requestCharge(s.params);
        uint256 topUp = full > processingPool ? full - processingPool : 0;
        return (topUp + 1 gwei - 1) / 1 gwei * 1 gwei;
    }

    /// @notice Deployment charge per VaultLib.POSITION_VALUE deposited: building and listing one
    ///         reference position at its quote now plus its mint fees, and never less than the
    ///         keeper margin that building it can pay out at any gas price.
    function deployCharge() public view returns (uint256) {
        return VaultLib.deployCharge(s.params, shapes.mintFee());
    }

    /// @notice Unwind charge per VaultLib.POSITION_VALUE redeemed: unlisting and liquidating one position.
    function unwindCharge() public view returns (uint256) {
        return VaultLib.unwindCharge(s.params);
    }

    // ------------------------------------------------------------------ owner

    /// @notice Owner pauses or resumes deposits and listing. Wind-down is one-way.
    function guard(bool pauseDeposits, bool pauseListing) external onlyOwner {
        (depositsPaused, s.listingPaused) = (pauseDeposits, pauseListing);
    }

    function startWindDown() external onlyOwner {
        s.windingDown = true;
        depositsPaused = true;
        s.listingPaused = true;
        emit WindDownStarted();
    }

    // ------------------------------------------------------------------ views

    /// @notice Shares including a deposit already priced but not yet converted (lazy).
    function shareBalance(address h) external view returns (uint256 shares) {
        shares = sharesOf[h];
        PendingDeposit memory d = pendingDeposits[h];
        if (d.amount != 0 && d.epoch < epoch) shares += uint256(d.amount - d.charge) * epochSupply[d.epoch] / epochNav[d.epoch];
    }
}
