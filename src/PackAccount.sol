// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReentrancyGuard} from "solady/utils/ReentrancyGuard.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {VaultLib} from "./VaultLib.sol";
import {StrategyLib} from "./StrategyLib.sol";
import {ScanLib} from "./ScanLib.sol";
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
    uint256 public constant MAX_BUILD_BATCH = VaultLib.MAX_BUILD_BATCH;
    uint256 public constant MAX_WORK_FEE = VaultLib.MAX_WORK_FEE;

    VaultLib.Strategy internal s;
    uint256 public deploymentBlock;

    event ParamsSet();
    event MintFeeAccepted(uint256 maximum);
    error ConfigurationChanged();
    error ExplicitFeeAcceptanceRequired();

    error UnknownNft();

    constructor(IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_) {
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        rewards = IFWARewards(fwa_.rewards());
        token = IFWAToken(fwa_.token());
    }

    /// @dev Owner, parameters, budgets and the FWA approval, set once.
    function _initStrategy(address owner_, VaultLib.Params memory p) internal {
        if (owner_ == address(0)) revert NewOwnerIsZeroAddress();
        _initializeOwner(owner_);
        deploymentBlock = block.number;
        s.book.acquisitionCursor = fwa.nextSequenceToProcess();
        s.book.pendingPlusOne = 1;
        s.book.renewalEnabled = true;
        ScanLib.initializeParams(s, p);
        packs.setApprovalForAll(address(fwa), true);
    }

    // ------------------------------------------------------------------ account hooks

    /// @dev ETH this account may spend at all: balance less every liability it owes.
    function _free() internal view virtual returns (uint256);

    function _renewalHold() internal view virtual returns (uint256) {
        return s.params.reserve;
    }

    function _renewalCash() internal view virtual returns (uint256) {
        uint256 free = _free();
        uint256 held = _renewalHold();
        return free > held ? free - held : 0;
    }

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

    /// @notice Economics for existing inventory; excludes fresh mint expense in reuse mode.
    function relistEdge(uint256 units) external view returns (uint256, uint256, bool) {
        return StrategyLib.relistEdge(s, fwa, packs, shapes, units);
    }

    function relistEdgeFor(uint256 packId) external view returns (uint256, uint256, bool) {
        return StrategyLib.relistEdgeFor(s, fwa, packs, shapes, packId);
    }

    /// @notice Mint packs of `units` straight into ShapePacks and list each at once.
    function build(uint256 units, uint256[] calldata backingProposals, uint256 minPay, bytes32 expected)
        external nonReentrant returns (uint256)
    {
        _checkConfiguration(expected);
        return StrategyLib.build(s, fwa, packs, shapes, units, backingProposals, minPay);
    }

    /// @notice Relist idle packs at bounded backing proposals, checked against live economics.
    function list(uint256[] calldata backingProposals, uint256 minPay, bytes32 expected) external nonReentrant returns (uint256) {
        _checkConfiguration(expected);
        return StrategyLib.list(s, fwa, packs, shapes, backingProposals, minPay);
    }

    /// @notice Bounded journal or scan job, terminal resolutions and allocation cleanup.
    function sync(uint256[] calldata listingIds, uint256 witnessId, uint256 minPay, bytes32 expected)
        external nonReentrant returns (uint256)
    {
        _checkConfiguration(expected);
        return StrategyLib.sync(s, fwa, packs, listingIds, witnessId, _checkpointMode(), minPay);
    }

    /// @notice Withdraw active listings: in wind-down, when FWA's live fees leave no edge, or for
    ///         ETH owed that free ETH and inventory cannot cover.
    function unlist(uint256[] calldata listingIds, uint256 minPay, bytes32 expected) external nonReentrant returns (uint256) {
        _checkConfiguration(expected);
        return StrategyLib.unlist(s, fwa, packs, listingIds, minPay, _shortfall());
    }

    /// @notice Redeem idle packs to ETH while ETH is owed beyond liquid ETH, or in wind-down.
    function liquidate(uint256 maxCount, uint256 minPay, bytes32 expected) external nonReentrant returns (uint256) {
        _checkConfiguration(expected);
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

    function renew(uint256[] calldata returnedPackIds, uint256[] calldata backingProposals,
        uint256[] calldata feeIds, uint256 minPay, bytes32 expected) external nonReentrant returns (uint256)
    {
        _checkConfiguration(expected);
        return StrategyLib.renew(s, fwa, packs, shapes, returnedPackIds, backingProposals, feeIds, minPay);
    }

    /// @notice Necessary maintenance and exit work remain caller funded under configuration drift.
    function recover(uint256[] calldata ids, uint256 witnessId) external nonReentrant {
        StrategyLib.recover(s, fwa, packs, ids, witnessId, _checkpointMode());
    }

    function recoverUnlist(uint256[] calldata ids) external nonReentrant {
        s.callerFunded = true;
        StrategyLib.unlist(s, fwa, packs, ids, 0, _shortfall());
        s.callerFunded = false;
    }

    function recoverLiquidate(uint256 maxCount) external nonReentrant {
        s.callerFunded = true;
        StrategyLib.liquidate(s, packs, shapes, maxCount, 0, _need());
        s.callerFunded = false;
    }

    // ------------------------------------------------------------------ owner

    /// @notice Owner sets parameters at once, within the bytecode bounds (D58: no delay).
    function setParams(VaultLib.Params calldata p, bytes32 expected) external onlyOwner {
        _checkConfiguration(expected);
        ScanLib.configure(s, p);
        emit ParamsSet();
    }

    function acceptMintFee(uint64 maximum, bytes32 expected) external onlyOwner {
        _checkConfiguration(expected);
        s.params.acceptedMintFee = maximum;
        emit MintFeeAccepted(maximum);
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

    function configurationHash() public view returns (bytes32) {
        return ScanLib.configurationHash(s.params, shapes.mintFee(), s.listingPaused, s.windingDown);
    }

    function _checkConfiguration(bytes32 expected) internal view {
        if (expected != configurationHash()) revert ConfigurationChanged();
    }

    function referenceUnits() public view returns (uint256) { return VaultLib.refUnits(s.params); }
    function referencePositionValue() public view returns (uint256) { return VaultLib.positionValue(s.params); }
    function buildCost(uint256 units) public view returns (uint256) { return VaultLib.buildCost(s.params, units, shapes.mintFee()); }
    function quote(uint256 gasAllowance, uint256 units, bool essential) external view returns (uint256) {
        return VaultLib.quote(s.params, gasAllowance, units, essential);
    }
    function renewalQuote(uint256 returnedPackId, uint256 feeClaims, bool withdrawCredit) external view returns (uint256) {
        return ScanLib.renewalQuote(s.params, s.book, returnedPackId, feeClaims, withdrawCredit);
    }
    function operatingReserve() public view returns (uint256) { return VaultLib.operatingReserve(s.params); }
    function renewalFloat() public view returns (uint256) { return VaultLib.renewalFloat(s.params); }
    function unresolvedUplift() public view returns (uint256) { return s.book.unresolvedKeepUplift; }
    function inventoryShapeCount(uint256 packId) external view returns (uint256) { return s.book.packShapeCount[packId]; }
    function renewalEligible(uint256 packId) external view returns (bool) { return s.book.renewalEligible[packId]; }
    function renewalState() external view returns (uint256 eligibleReturned, uint256 keptReplacements,
        uint256 floatRequired, uint256 cashAvailable)
    {
        return (s.book.renewalEligibleCount, s.book.keptReplacements, renewalFloat(), _renewalCash());
    }

    // ------------------------------------------------------------------ views

    function getParams() external view returns (VaultLib.Params memory) {
        bytes memory encoded = ScanLib.encodedParams(s.params);
        assembly ("memory-safe") { return(add(encoded, 32), mload(encoded)) }
    }
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
        return VaultLib.accountedNav(s.params, s.book, fwa, packs, _free(), witnessId);
    }

    function keeperCash() public view returns (uint256) {
        uint256 free = _free();
        uint256 float = s.windingDown ? 0 : renewalFloat();
        return free > float ? free - float : 0;
    }
    /// @notice ETH still needed to refill the protected hold before incoming fees become spendable.
    function fundingDeficit(bool renewal) external view returns (uint256) {
        uint256 held = renewal ? _renewalHold() : s.windingDown ? 0 : renewalFloat();
        uint256 free = _free();
        return held > free ? held - free : 0;
    }
    function liquidityNeed() external view returns (uint256) { return _need(); }
    function liquidityShortfall() external view returns (uint256) { return _shortfall(); }
    function renewalCash() external view returns (uint256) { return _renewalCash(); }
    function freeEth() external view returns (uint256) { return _free(); }
    function idleEth() external view returns (uint256) { return _idle(); }

    /// @notice Keeper budget available now: routine (strategy) and essential (exit work).
    function budget() external view returns (uint256 routine, uint256 essential) {
        return VaultLib.budgetNow(s.params, s.budget);
    }
}
