// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReentrancyGuard} from "solady/utils/ReentrancyGuard.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {VaultLib} from "./VaultLib.sol";
import {StrategyLib} from "./StrategyLib.sol";
import {IKeeperPolicy} from "./KeeperPolicy.sol";
import {IShapes, IShapePacks, IFWAV2, IFWARewards, IFWAToken} from "./interfaces/External.sol";

/// @title PackAccount
/// @notice One FWA strategy account: the shared operating surface of PackVault (pooled depositors)
///         and PackManager (one owner). Every operation runs the single strategy implementation
///         (StrategyLib, VaultLib, ScanLib) against this account's own `VaultLib.Strategy`, so this
///         contract is the FWA depositor and the owner of every Shape pack, listing and wei it
///         holds. Accounts share code, never assets or accounting.
/// @dev The concrete account defines what ETH is free (`_free`) and spendable on new exposure
///      (`_idle`), plus the facts only it knows: whether a checkpoint is due (`_checkpointMode`)
///      and how much ETH its owners are owed beyond what it holds (`_shortfall`, `_need`).
///      Maintenance is permissionless and paid by quote (D56) from this account's budgets only.
///      One owner (Solady Ownable): two-step handover only, never renounced (D76).
abstract contract PackAccount is ReentrancyGuard, Ownable {
    IFWAV2 public immutable fwa;
    IShapes public immutable shapes;
    IShapePacks public immutable packs;
    IFWARewards public immutable rewards;
    IFWAToken public immutable token;

    /// @notice Bytecode bounds shared by every account.
    uint256 public constant MAX_BATCH = VaultLib.MAX_BATCH;
    uint256 public constant MAX_LIST_BATCH = VaultLib.MAX_LIST_BATCH;
    uint256 public constant MAX_WORK_FEE = VaultLib.MAX_WORK_FEE;

    VaultLib.Strategy internal s;
    uint256 public deploymentBlock;

    event ParamsSet();
    event PolicyChanged(address indexed oldPolicy, address indexed newPolicy);

    error UnknownNft();

    constructor(IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_) {
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        rewards = IFWARewards(fwa_.rewards());
        token = IFWAToken(fwa_.token());
    }

    /// @dev Owner, parameters, keeper policy, budgets and the FWA approval, set once.
    function _initStrategy(address owner_, VaultLib.Params memory p, address policy) internal {
        if (owner_ == address(0)) revert NewOwnerIsZeroAddress();
        _initializeOwner(owner_);
        deploymentBlock = block.number;
        s.book.acquisitionCursor = fwa.nextSequenceToProcess();
        s.book.pendingPlusOne = 1;
        s.params = p;
        VaultLib.checkBounds(s.params);
        VaultLib.checkPolicy(policy);
        s.policy = policy;
        s.budget = VaultLib.Budget(uint128(p.routineCap), uint128(p.essentialCap), block.timestamp);
        packs.setApprovalForAll(address(fwa), true);
    }

    // ------------------------------------------------------------------ account hooks

    /// @dev ETH this account may spend at all: balance less every liability it owes.
    function _free() internal view virtual returns (uint256);

    /// @dev ETH the strategy may commit to new exposure.
    function _idle() internal view virtual returns (uint256);

    /// @dev 0 none, 1 holder flows wait for a checkpoint, 2 a distribution checkpoint may be due.
    function _checkpointMode() internal view virtual returns (uint256) {
        return 0;
    }

    /// @dev ETH owed beyond free ETH and idle inventory: unlisting for it is essential.
    function _shortfall() internal view virtual returns (uint256) {
        return 0;
    }

    /// @dev ETH owed beyond liquid ETH: liquidation for it is allowed.
    function _need() internal view virtual returns (uint256) {
        return 0;
    }

    // ------------------------------------------------------------------ ETH and NFT intake

    /// @notice FWA's pushed payments are matched to their listing (StrategyLib.receipt); any
    ///         other ETH, and ETH forced in without a call, simply joins the balance.
    receive() external payable virtual {
        if (msg.sender == address(fwa)) StrategyLib.receipt(s.book, fwa, packs, msg.value);
    }

    /// @dev Only pack NFTs, the only NFTs the strategy creates or gets back from FWA.
    function onERC721Received(address, address, uint256, bytes calldata) external view returns (bytes4) {
        if (msg.sender != address(packs)) revert UnknownNft();
        return this.onERC721Received.selector;
    }

    // ------------------------------------------------------------------ strategy operations

    /// @notice Live economics: k, the backing a new listing of `units` x 0.01 ETH posts (0 when
    ///         it must not list) and whether it lists.
    function edge(uint256 units) public view returns (uint256, uint256, bool) {
        return StrategyLib.edge(s, fwa, packs, shapes, units);
    }

    /// @notice Mint packs of `units` straight into ShapePacks and list each at once.
    function build(uint256 units, uint256[] calldata backingProposals, uint256 minPay)
        external nonReentrant returns (uint256)
    {
        return StrategyLib.build(s, fwa, packs, shapes, units, backingProposals, minPay);
    }

    /// @notice Relist idle packs at bounded backing proposals, checked against live economics.
    function list(uint256[] calldata backingProposals, uint256 minPay) external nonReentrant returns (uint256) {
        return StrategyLib.list(s, fwa, packs, shapes, backingProposals, minPay);
    }

    /// @notice Bounded journal or scan job, terminal resolutions and allocation cleanup.
    function sync(uint256[] calldata listingIds, uint256 witnessId, uint256 minPay)
        external nonReentrant returns (uint256)
    {
        return StrategyLib.sync(s, fwa, packs, listingIds, witnessId, _checkpointMode(), minPay);
    }

    /// @notice Withdraw active listings: in wind-down, when FWA's live fees leave no edge, or for
    ///         ETH owed that free ETH and inventory cannot cover.
    function unlist(uint256[] calldata listingIds, uint256 minPay) external nonReentrant returns (uint256) {
        return StrategyLib.unlist(s, fwa, packs, listingIds, minPay, _shortfall());
    }

    /// @notice Redeem idle packs to ETH while ETH is owed beyond liquid ETH, or in wind-down.
    function liquidate(uint256 maxCount, uint256 minPay) external nonReentrant returns (uint256) {
        return StrategyLib.liquidate(s, packs, shapes, maxCount, minPay, _need());
    }

    /// @notice Caller-funded fee collection (never paid).
    function harvest(uint256[] calldata activeIds, uint256 minPay) external nonReentrant returns (uint256) {
        StrategyLib.harvest(s, fwa, activeIds, minPay);
        return 0;
    }

    /// @notice Claim and burn FWA token rewards (never valued, never sold; unpaid).
    function burnTokens(uint256[] calldata activeIds) external nonReentrant {
        StrategyLib.burnTokens(rewards, token, activeIds);
    }

    // ------------------------------------------------------------------ owner

    /// @notice Owner sets parameters at once, within the bytecode bounds (D58: no delay).
    function setParams(VaultLib.Params calldata p) external onlyOwner {
        // Budgets accrue at the old rates up to now; the new caps then only clamp, never refill.
        VaultLib.syncBudget(s.params, s.budget);
        s.params = p;
        VaultLib.checkBounds(s.params);
        VaultLib.syncBudget(s.params, s.budget);
        emit ParamsSet();
    }

    /// @notice Owner replaces the keeper payment policy at once (D57, D58); the account still caps
    ///         every offer at its envelope, free ETH and budget.
    function setPolicy(address policy) external onlyOwner {
        VaultLib.checkPolicy(policy);
        emit PolicyChanged(s.policy, policy);
        s.policy = policy;
    }

    /// @notice Disabled (D76): ownership moves only by the two-step handover (the new key calls
    ///         `requestOwnershipHandover`, then the owner calls `completeOwnershipHandover` within
    ///         48 hours). A renounced or mistyped owner could never pause or exit again.
    function renounceOwnership() public payable override {
        revert Unauthorized();
    }

    function transferOwnership(address) public payable override {
        revert Unauthorized();
    }

    // ------------------------------------------------------------------ views

    function getParams() external view returns (VaultLib.Params memory) { return s.params; }
    function keeperPolicy() external view returns (IKeeperPolicy) { return IKeeperPolicy(s.policy); }
    function listingPaused() external view returns (bool) { return s.listingPaused; }
    function windingDown() external view returns (bool) { return s.windingDown; }
    function openListingCount() external view returns (uint256) { return s.book.open.length; }
    function openListingAt(uint256 index) external view returns (uint256) { return s.book.open[index]; }
    function idlePackCount() external view returns (uint256) { return s.book.idlePacks.length; }
    function idlePackAt(uint256 index) external view returns (uint256) { return s.book.idlePacks[index]; }
    function recoveryPackCount() external view returns (uint256) { return s.book.recoveryPacks.length; }
    function recoveryPackAt(uint256 index) external view returns (uint256) { return s.book.recoveryPacks[index]; }
    function recoveryUnsealed(uint256 id) external view returns (bool) { return s.book.recoveryUnsealed[id]; }
    function position(uint256 id) external view returns (VaultLib.Position memory) { return s.book.positions[id]; }
    function idleValueOf(uint256 id) external view returns (uint256) { return s.book.idleValueOf[id]; }
    function idleFunding() external view returns (uint256) { return s.book.idleFunding; }
    function acquisitionCursor() external view returns (uint64) { return s.book.acquisitionCursor; }
    function pendingReceipts() external view returns (uint256) { return s.book.pendingPlusOne - 1; }
    function reservedCount() external view returns (uint256) { return s.book.reservedCount; }
    function idForBacking(uint256 backing) external view returns (uint256) { return s.book.idForBacking[backing]; }
    function receipts(uint256 id) external view returns (VaultLib.Receipt memory) { return s.book.receipts[id]; }
    function debtCount(uint256 debt) external view returns (uint256) { return s.book.countByDebt[debt]; }

    function totals() external view returns (uint256 tracked, uint256 idle, uint256 backing, uint256 active,
        uint256 debt, uint256 allocated)
    {
        VaultLib.Book storage b = s.book;
        return (b.trackedValue, b.idleValue, b.activeBacking, b.activeCount, b.feeDebtSum, b.allocatedValue);
    }

    function allocationState() external view returns (uint256 head, uint256 length, uint256 id, uint64 at, bool stale) {
        VaultLib.Book storage b = s.book;
        head = b.allocationHead;
        length = b.allocationQueue.length;
        if (head != length) {
            id = b.allocationQueue[head];
            at = b.positions[id].allocatedAt;
            stale = b.positions[id].state != VaultLib.ALLOCATED;
        }
    }

    /// @notice Book value now: free ETH, tracked inventory, active backing, FWA fee credit and
    ///         pending fees (exact, by witness). Reverts until the journal and receipts are current.
    function accountedNav(uint256 witnessId) public view returns (uint256) {
        return VaultLib.accountedNav(s.book, fwa, packs, _free(), witnessId);
    }

    function freeEth() external view returns (uint256) { return _free(); }
    function idleEth() external view returns (uint256) { return _idle(); }

    /// @notice Keeper budget available now: routine (strategy) and essential (exit work).
    function budget() external view returns (uint256 routine, uint256 essential) {
        return VaultLib.budgetNow(s.params, s.budget);
    }
}
