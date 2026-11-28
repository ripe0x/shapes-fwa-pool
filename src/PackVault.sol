// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {PackAccount} from "./PackAccount.sol";
import {VaultLib} from "./VaultLib.sol";
import {StrategyLib} from "./StrategyLib.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @title PackVault
/// @notice Pooled depositor vault for the FWA V2 main pool. It runs the shared pack strategy
///         (PackAccount: build, list, sync, unlist, liquidate) and adds only multi-depositor
///         ownership: non-transferable internal shares priced at checkpoints, escrowed deposits,
///         pro-rata redemptions, distributions, holder liabilities and wind-down.
/// @dev Economics, from FWAV2 source and validated against every historical EarningsAccrued event:
///      a listing with backing B earns expected fees k B before selection, where
///      k = (1 + surcharge)(1 - protocolCut)(1 - crownShare). On selection the purchaser either keeps
///      the pack (the vault gets B (1 - s) back) or takes the bid (the vault gets the pack back).
///      Account-owned backing settings price both outcomes without assuming a choice.
///
///      Keepers are paid from vault ETH (a holder expense, NAV-visible), never from a fee skim, by
///      quote (D56). Checkpoints are funded by charges on the deposit and redemption requests that
///      need them, so holders do not pay for work someone else manufactures.
///
///      Trust: FWA, its rewards module, Shapes, ShapePacks and the FWA token are immutable
///      addresses fixed here. FWA's owner can change fees, the floor quote and admission; every
///      such change is read live, never cached. One owner (D59; transferable, never renounced,
///      D76) sets economic parameters at once, inside bytecode bounds (D58), pauses
///      and starts wind-down. The owner cannot take assets directly; a compromised owner can raise
///      keeper pay to the bytecode maxima and keep for itself, bounded by the budgets.
contract PackVault is PackAccount {
    using SafeTransferLib for address;

    uint256 internal constant BPS = 10_000;
    uint256 internal constant INTERVAL = 12 hours; // FWA purchase interval
    uint256 internal constant SCALE = 1e36;
    uint256 internal constant MIN_SEED = 0.01 ether;
    uint256 public constant DEAD_SHARES = VaultLib.DEAD_SHARES;

    bool public depositsPaused;

    // ------------------------------------------------------------------ shares

    uint256 public totalShares;
    mapping(address => uint256) public sharesOf;

    uint256 public epoch; // deposit pricing epochs completed
    uint256 public lastCheckpointInterval;
    uint256 public highWaterMark; // NAV per share, 1e18 scale
    uint256 public lastNav;

    struct PendingDeposit {
        uint128 amount; // gross cancellable escrow; construction is priced only at commitment
        uint128 epoch;
    }

    mapping(address => PendingDeposit) public pendingDeposits;
    uint256 public pendingDepositTotal; // ETH escrowed, excluded from NAV
    struct Issuance {
        uint256 gross;
        uint256 issued;
        uint256 remainingGross;
        uint256 remainingShares;
    }
    mapping(uint256 epoch => Issuance) public issuances;
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
    uint256 public chargeRefundReserve;
    uint256 public chargeEra;
    uint256 public contributionCount;

    struct ChargeEra {
        uint256 total;
        uint256 refundable;
        bool closed;
    }
    struct Contribution {
        address payer;
        uint256 era;
        uint256 start;
        uint256 amount;
        bool claimed;
    }
    mapping(uint256 => ChargeEra) public chargeEras;
    mapping(uint256 => Contribution) public contributions;

    // ------------------------------------------------------------------ events and errors

    event Deposited(address indexed holder, uint256 amount, uint256 epoch);
    event DepositCancelled(address indexed holder, uint256 amount);
    event RedeemRequested(address indexed holder, uint256 shares);
    event Checkpoint(uint256 indexed epoch, uint256 nav, uint256 supply, uint256 filledShares, uint256 paid, uint256 distributed);
    event Claimed(address indexed holder, uint256 amount);
    event WindDownStarted();
    event ContributionFunded(uint256 indexed id, address indexed payer, uint256 indexed era, uint256 amount);
    event ContributionEraClosed(uint256 indexed era, uint256 total, uint256 refundable);
    event ContributionRefunded(uint256 indexed id, address indexed payer, uint256 amount);

    error Paused();
    error WindingDown();
    error NotCheckpointWindow();
    error AlreadyCheckpointed();
    error AllocatedExposure();
    error Amount();
    error Nothing();
    error SyncFirst();
    error MintFeeNotAccepted();

    // ------------------------------------------------------------------ construction

    constructor(
        IFWAV2 fwa_,
        IShapes shapes_,
        IShapePacks packs_,
        address owner_,
        VaultLib.Params memory initial,
        bytes32 expected
    ) payable PackAccount(fwa_, shapes_, packs_) {
        _initStrategy(owner_, initial);
        _checkConfiguration(expected);
        // First issuance: the deployer's seed buys dead shares so the share price cannot be
        // inflated against a later first depositor.
        if (msg.value < MIN_SEED) revert Amount();
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

    /// @dev Cancellable deposits are not liquidation liquidity. Only a checkpoint may commit them.
    function _need() internal view override returns (uint256) {
        uint256 owed = _owedEstimate();
        uint256 liquid = _free();
        return owed > liquid ? owed - liquid : 0;
    }

    /// @dev The vault's own ETH: balance less escrowed deposits and every amount owed to holders,
    ///      whether still in a shared reserve or already settled to a holder's claimable balance.
    ///      Request charges held for the next checkpoint are excluded too. Forced ETH lands here,
    ///      so it is attributed by balance, never by callback.
    function _free() internal view override returns (uint256) {
        uint256 owed = pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal
            + processingPool + chargeRefundReserve;
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

    /// @notice Gross escrow is cancellable until commitment. Construction quotes are estimates:
    ///         the committing checkpoint uses its effective configuration and live mint fee.
    function deposit(bytes32 expected) external payable nonReentrant {
        _checkConfiguration(expected);
        if (depositsPaused) revert Paused();
        if (s.windingDown) revert WindingDown();
        uint256 ck = requestCharge();
        if (msg.value <= ck || msg.value - ck < s.params.minDeposit) revert Amount();
        uint256 amount = msg.value - ck;
        if (lastNav + pendingDepositTotal + amount > s.params.tvlCap) revert Amount();
        _settleHolder(msg.sender);
        _contribute(msg.sender, ck);
        PendingDeposit storage d = pendingDeposits[msg.sender];
        if (amount > type(uint128).max - d.amount || epoch > type(uint128).max) revert Amount();
        d.amount += uint128(amount);
        d.epoch = uint128(epoch);
        pendingDepositTotal += amount;
        emit Deposited(msg.sender, amount, epoch);
    }

    function cancelDeposit() external nonReentrant {
        _settleHolder(msg.sender);
        PendingDeposit memory d = pendingDeposits[msg.sender];
        uint256 amount = d.amount;
        if (amount == 0) revert Nothing();
        delete pendingDeposits[msg.sender];
        pendingDepositTotal -= amount;
        _closeIdleEra();
        msg.sender.forceSafeTransferETH(amount);
        emit DepositCancelled(msg.sender, amount);
    }

    /// @notice Lock shares for redemption. Filled pro rata at checkpoints as ETH frees up; the
    ///         unfilled part stays exposed to the vault until filled. Send at least
    ///         `requestCharge()`: it funds the checkpoint; any excess is returned.
    function requestRedeem(uint256 amount, bytes32 expected) external payable nonReentrant {
        _checkConfiguration(expected);
        _settleHolder(msg.sender);
        if (amount == 0 || amount > sharesOf[msg.sender]) revert Amount();
        // Only charge the checkpoint (to the pool). Exit work is unpaid, so there is no unwind charge.
        uint256 charge = requestCharge();
        if (msg.value < charge) revert Amount();
        _contribute(msg.sender, charge);
        if (msg.value > charge) msg.sender.forceSafeTransferETH(msg.value - charge);
        _settleDist(msg.sender);
        sharesOf[msg.sender] -= amount;
        distDebt[msg.sender] = sharesOf[msg.sender] * distPerShare / 1e18;
        Redemption storage r = redemptions[msg.sender];
        if (amount > type(uint128).max - r.shares) revert Amount();
        r.shares += uint128(amount);
        lockedShares += amount;
        emit RedeemRequested(msg.sender, amount);
    }

    function _contribute(address payer, uint256 amount) internal {
        if (amount == 0) return;
        ChargeEra storage e = chargeEras[chargeEra];
        uint256 id = contributionCount++;
        contributions[id] = Contribution(payer, chargeEra, e.total, amount, false);
        e.total += amount;
        processingPool += amount;
        emit ContributionFunded(id, payer, chargeEra, amount);
    }

    function _closeIdleEra() internal {
        if (pendingDepositTotal == 0 && lockedShares == 0) _closeChargeEra();
    }

    function _closeChargeEra() internal {
        ChargeEra storage e = chargeEras[chargeEra];
        if (e.total == 0) return;
        e.closed = true;
        e.refundable = processingPool;
        chargeRefundReserve += processingPool;
        processingPool = 0;
        emit ContributionEraClosed(chargeEra, e.total, e.refundable);
        ++chargeEra;
    }

    /// @notice Refunds partition the era's remaining wei by contribution interval. Adjacent
    ///         floor differences telescope, attributing every wei regardless of claim order.
    function checkpointRefund(uint256 id) public view returns (uint256) {
        Contribution storage c = contributions[id];
        ChargeEra storage e = chargeEras[c.era];
        if (c.claimed || !e.closed || c.amount == 0) return 0;
        return M.mulDiv(c.start + c.amount, e.refundable, e.total) - M.mulDiv(c.start, e.refundable, e.total);
    }

    function claimCheckpointRefund(uint256[] calldata ids) external nonReentrant {
        if (ids.length == 0 || ids.length > MAX_BATCH) revert Amount();
        uint256 amount;
        for (uint256 i; i < ids.length; ++i) {
            Contribution storage c = contributions[ids[i]];
            if (c.payer != msg.sender) revert Amount();
            uint256 refund = checkpointRefund(ids[i]);
            if (c.claimed || !chargeEras[c.era].closed) continue;
            c.claimed = true;
            amount += refund;
            emit ContributionRefunded(ids[i], msg.sender, refund);
        }
        if (amount == 0) revert Nothing();
        chargeRefundReserve -= amount;
        msg.sender.forceSafeTransferETH(amount);
    }

    /// @notice Explicit checkpoint sponsorship while holder work exists; overpayment is returned.
    function fundCheckpoint(bytes32 expected) external payable nonReentrant returns (uint256 accepted) {
        _checkConfiguration(expected);
        if (pendingDepositTotal == 0 && lockedShares == 0) revert Nothing();
        accepted = M.min(msg.value, requestCharge());
        _contribute(msg.sender, accepted);
        if (msg.value > accepted) msg.sender.forceSafeTransferETH(msg.value - accepted);
    }

    /// @notice Required pricing work uses its explicit contribution source, never routine cash.
    function syncCheckpoint(uint256[] calldata ids, uint256 witnessId, uint256 minPay, bytes32 expected) external returns (uint256) {
        return _syncCheckpoint(ids, witnessId, minPay, expected, gasleft());
    }

    function _syncCheckpoint(uint256[] calldata ids, uint256 witnessId, uint256 minPay, bytes32 expected, uint256 gasStart) private nonReentrant returns (uint256 paid) {
        _checkConfiguration(expected);
        if (pendingDepositTotal == 0 && lockedShares == 0) revert Nothing();
        paid = StrategyLib.syncFunded(s, fwa, packs, ids, witnessId, 1, minPay, processingPool, gasStart - gasleft());
        processingPool -= paid;
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
            Issuance storage issuance = issuances[d.epoch];
            // The final settlement receives the aggregate floor residue. Total assigned shares
            // therefore equals checkpoint issuance without enumerating depositors.
            uint256 minted = d.amount == issuance.remainingGross ? issuance.remainingShares
                : M.mulDiv(d.amount, issuance.issued, issuance.gross);
            issuance.remainingGross -= d.amount;
            issuance.remainingShares -= minted;
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
    function checkpoint(uint256 witnessId, uint256 minPay, bytes32 expected) external returns (uint256) {
        return _checkpoint(witnessId, minPay, expected, gasleft());
    }

    function _checkpoint(uint256 witnessId, uint256 minPay, bytes32 expected, uint256 gasStart) private nonReentrant returns (uint256) {
        // Zero expectation selects the unpaid redemption-only recovery path. It cannot commit
        // pending deposits, distribute gains or earn compensation.
        bool recoveryOnly = expected == bytes32(0);
        if (!recoveryOnly) _checkConfiguration(expected);
        if (recoveryOnly && minPay != 0) revert Amount();
        IFWAV2 f = fwa;
        if (!f.isPurchaseBlackout() || f.unsettledAcquisitionCount() != 0) revert NotCheckpointWindow();
        uint256 interval = block.timestamp / INTERVAL;
        if (!recoveryOnly && interval == lastCheckpointInterval) revert AlreadyCheckpointed();
        // Only with holder flows to settle, or with distributions on: a no-op checkpoint would
        // use up the interval's one slot and delay flows that arrive later in the blackout.
        if (recoveryOnly && lockedShares == 0) revert Nothing();
        bool work = (!recoveryOnly && pendingDepositTotal != 0) || lockedShares != 0;
        if (!work && s.params.distributionBps == 0) revert Nothing();
        if (!work) StrategyLib.precheck(s, minPay, false); // distribution pays routine; holder flows use their pool
        if (!recoveryOnly) lastCheckpointInterval = interval;

        (uint256 oldest, uint64 allocatedAt) = VaultLib.oldestAllocation(s.book);
        if (oldest != 0 && block.timestamp >= uint256(allocatedAt) + f.settlementWindow()) revert SyncFirst();
        VaultLib.harvestCredit(s.book, f);
        (uint256 nav, uint256 gasQ) = VaultLib.checkpointNav(s.params, s.book, f, packs, _free(), witnessId);
        if (s.book.unresolvedKeepUplift * BPS > nav * s.params.upliftBoundBps) revert AllocatedExposure();

        uint256 supply = totalShares;
        // 1. Redemptions at the pre-flow price, funded by free ETH and new deposits. Inventory is
        //    turned into ETH beforehand by `liquidate`, so this call stays bounded.
        uint256 filled;
        uint256 paid;
        if (lockedShares != 0) {
            uint256 frac;
            uint256 unit;
            (frac, filled, unit, paid) = VaultLib.fill(lockedShares, nav, supply, _free() + (recoveryOnly ? 0 : pendingDepositTotal));
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
        if (!recoveryOnly && lockedShares == 0 && supply > DEAD_SHARES && perShare > highWaterMark && s.params.distributionBps != 0) {
            uint256 gain = M.mulDiv(perShare - highWaterMark, supply, 1e18);
            distributed = M.min(gain * s.params.distributionBps / BPS, _idle());
            if (distributed != 0 && distributed >= s.params.minDistribution) {
                // Live shares only: the dead seed shares never claim, so their slice would strand.
                distPerShare += distributed * 1e18 / (supply - DEAD_SHARES);
                distributionReserve += distributed;
                nav -= distributed;
            } else {
                distributed = 0;
            }
        }
        perShare = nav * 1e18 / supply;
        if (!recoveryOnly && perShare > highWaterMark) highWaterMark = perShare;

        // 3. Deposits at the post-flow price.
        if (!recoveryOnly) epochDistPerShare[epoch] = distPerShare;
        bool committed = !recoveryOnly && pendingDepositTotal != 0;
        if (committed) {
            if (s.params.packUnitsMask != 0 && shapes.mintFee() > s.params.acceptedMintFee) revert MintFeeNotAccepted();
            uint256 gross = pendingDepositTotal;
            uint256 charge = constructionCharge(gross);
            uint256 issued = M.mulDiv(gross - charge, supply, nav);
            if (issued == 0) revert Amount();
            issuances[epoch] = Issuance(gross, issued, gross, issued);
            totalShares += issued;
            nav += gross;
            pendingDepositTotal = 0;
            // Deployment charges lift NAV per share; that is not a gain to distribute.
            perShare = nav * 1e18 / totalShares;
            if (perShare > highWaterMark) highWaterMark = perShare;
        }
        if (!committed && filled == 0 && distributed == 0) revert Nothing();
        lastNav = nav;
        emit Checkpoint(epoch, nav, totalShares, filled, paid, distributed);
        if (!recoveryOnly) ++epoch;
        if (recoveryOnly) {
            // Unpriced deposits still need their funded normal checkpoint. An incumbent cannot
            // refund that sponsorship by front-running it with a tiny unpaid redemption.
            if (pendingDepositTotal == 0) _closeChargeEra();
            return 0;
        }
        if (work) {
            // Source classification survives the final redemption. Contributions never become
            // general free cash; unused wei move directly to their payers' protected reserve.
            uint256 paidKeeper = StrategyLib.payFunded(s, gasQ, 1, true, minPay, processingPool, gasStart - gasleft());
            processingPool -= paidKeeper;
            _closeChargeEra();
            return paidKeeper;
        }
        if (distributed != 0) {
            return StrategyLib.pay(s, gasQ, 1, false, minPay, type(uint256).max, gasStart - gasleft());
        }
        // No flows and nothing distributed: revert, so the interval's one slot stays free (audit E3).
        revert Nothing();
    }

    /// @notice Caller-funded redemption only. Pending deposits stay cancellable and mint fee
    ///         changes cannot veto recovery. The caller pays wallet gas and earns no compensation.
    function recoverCheckpoint(uint256 witnessId) external {
        // Reuse the guarded entry point so the large bounded pricing path has one implementation.
        this.checkpoint(witnessId, 0, bytes32(0));
    }

    // ------------------------------------------------------------------ charges

    /// @notice What a deposit or redemption request is charged now: what tops `processingPool` up
    ///         to one checkpoint at its quote (cost plus one work unit), in canonical wei;
    ///         0 when the pool already holds it. Requests in one interval share one checkpoint.
    function requestCharge() public view returns (uint256) {
        uint256 entries = s.book.allocationQueue.length - s.book.allocationHead;
        if (entries > VaultLib.MAX_ALLOCATION_SCAN) entries = VaultLib.MAX_ALLOCATION_SCAN;
        uint256 open = s.book.open.length;
        if (s.book.activeCount != 0 && open <= VaultLib.MAX_ALLOCATION_SCAN
            && !fwa.oracleExemptCollections(address(packs))) entries += open;
        uint256 full = VaultLib.quote(s.params, s.params.gasSchedule.checkpoint
            + entries * (uint256(s.params.gasSchedule.allocationEntry) + s.params.gasSchedule.allocationRead), 1, true);
        uint256 topUp = full > processingPool ? full - processingPool : 0;
        return topUp;
    }

    /// @notice Deployment allowance per reference position: building and listing one
    ///         reference position at its quote now plus its mint fees, and never less than the
    ///         keeper margin that building it can pay out at any gas price.
    function deployCharge() public view returns (uint256) {
        return VaultLib.deployCharge(s.params, shapes.mintFee());
    }

    function positionValue() public view returns (uint256) {
        return VaultLib.positionValue(s.params);
    }

    function constructionCharge(uint256 gross) public view returns (uint256) {
        uint256 cost = deployCharge();
        return M.mulDiv(gross, cost, positionValue() + cost);
    }

    /// @param escrowGross Cancellable principal, excluding the separately quoted checkpoint topup.
    function previewDeposit(uint256 escrowGross) external view returns (
        uint256 checkpointTopup, uint256 estimatedConstruction, uint256 estimatedNetPrincipal
    ) {
        checkpointTopup = requestCharge();
        estimatedConstruction = constructionCharge(escrowGross);
        estimatedNetPrincipal = escrowGross - estimatedConstruction;
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
        if (d.amount != 0 && d.epoch < epoch) {
            Issuance storage issuance = issuances[d.epoch];
            shares += d.amount == issuance.remainingGross ? issuance.remainingShares
                : M.mulDiv(d.amount, issuance.issued, issuance.gross);
        }
    }

    /// @notice Lazy claim and surviving redemption preview without RPC transaction simulation.
    function holderState(address h) external view returns (uint256 shares, uint256 locked, uint256 claimable) {
        shares = sharesOf[h];
        uint256 debt = distDebt[h];
        PendingDeposit memory d = pendingDeposits[h];
        if (d.amount != 0 && d.epoch < epoch) {
            Issuance storage issuance = issuances[d.epoch];
            uint256 minted = d.amount == issuance.remainingGross ? issuance.remainingShares
                : M.mulDiv(d.amount, issuance.issued, issuance.gross);
            shares += minted;
            debt += minted * epochDistPerShare[d.epoch] / 1e18;
        }
        claimable = claimableEth[h] + shares * distPerShare / 1e18 - debt;
        Redemption storage r = redemptions[h];
        if (r.shares != 0) {
            uint256 q = r.era < redeemEra ? eraFinalQ[r.era] : redeemQ;
            claimable += M.mulDiv(r.shares, q - r.q0, r.g0);
            if (r.era == redeemEra) locked = M.mulDiv(r.shares, redeemG, r.g0);
        }
    }
}
