// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ReentrancyGuard} from "solady/utils/ReentrancyGuard.sol";
import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {FixedPointMathLib as M} from "solady/utils/FixedPointMathLib.sol";
import {VaultLib} from "./VaultLib.sol";
import {
    IShapes,
    IShapePacks,
    IFWAV2,
    IFWARewards,
    IFWAToken,
    IFloorOracle,
    IPoolManager,
    PoolKey,
    SwapParams,
    LISTING_ACTIVE,
    LISTING_ALLOCATED,
    LISTING_WITHDRAWN,
    LISTING_SETTLED,
    LISTING_STAGED
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
///      Keepers are reimbursed gas from vault ETH (a holder expense, NAV-visible), never from a
///      fee skim: the edge per selection is only about 3.85% of backing, so any fixed share of
///      fees large enough to pay keepers exceeds it. A call is paid only when it did necessary
///      work or realized more than its cost.
///
///      Trust: FWA, its rewards module, Shapes, ShapePacks and the token's v4 pool are immutable
///      addresses fixed here. FWA's owner can change fees, the floor quote and admission; every
///      such change is read live, never cached. The guardian can only stop things and lower caps.
///      The admin can move parameters inside bytecode bounds after `PARAM_DELAY`. Neither role has
///      any path that moves assets to itself.
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
    /// Bounds the checkpoint loop: open plus idle positions never exceed it, and the worst-case
    /// checkpoint must fit EIP-7825's 16,777,216 gas transaction cap with margin.
    uint256 public constant MAX_POSITIONS = 300;
    uint256 public constant MAX_MIN_EDGE_BPS = 1_000;
    uint256 public constant MAX_BUFFER_BPS = 2_000;
    uint256 public constant MAX_GAS_CEILING = 50 gwei;
    uint256 public constant MAX_DISTRIBUTION_BPS = 5_000;
    uint256 public constant MAX_KEEPER_PREMIUM_BPS = 5_000;
    uint256 public constant MAX_KEEPER_SHARE_BPS = 5_000;
    uint256 public constant MAX_ALLOCATED_BOUND_BPS = 1_000;
    uint256 public constant MAX_CLIP_SLIPPAGE_BPS = 500;
    uint256 public constant MIN_PACK_UNITS = 3; // ShapePacks minimum pack value 0.03 ETH
    uint256 public constant MAX_PACK_UNITS = 63; // highest bit of the uint64 mask
    uint256 public constant MIN_DEPOSIT = 0.01 ether;
    uint256 public constant MIN_DISTRIBUTION = 0.01 ether;
    uint256 public constant KEEPER_OVERHEAD_GAS = 30_000;
    uint256 public constant DEAD_SHARES = 1e15;
    /// Gas a bid-outcome cycle costs the vault: relist plus its share of sync and harvest.
    uint256 public constant CYCLE_GAS = 800_000;
    /// Gas to build one 3-unit pack: a third of a 0.1 mint and ten-way split, plus createPack.
    uint256 public constant RESTOCK_GAS_PER_PACK = 1_050_000;
    uint256 public constant MAX_LIQUIDATIONS = 40; // packs redeemed per call, about 8M gas
    /// Most gas `sync` and `unlist` reimburse per position they actually moved, so padding a call
    /// with ids it skips cannot earn the premium (measured: sync ~160k, unlist ~200k per id).
    uint256 public constant GAS_PER_MOVED = 300_000;

    // ------------------------------------------------------------------ immutables

    IFWAV2 public immutable fwa;
    IShapes public immutable shapes;
    IShapePacks public immutable packs;
    IFWARewards public immutable rewards;
    IFWAToken public immutable token;
    IPoolManager public immutable poolManager;
    address public immutable guardian;
    address public immutable admin;
    uint256 public immutable paramDelay;

    // ------------------------------------------------------------------ parameters

    struct Params {
        uint16 minEdgeBps; // require k >= 1 + minEdge
        uint16 bufferBps; // list at cap x (1 - buffer), so a small ask cut does not trigger kicks
        uint16 distributionBps; // share of new gains above the high-water mark paid out
        uint16 keeperPremiumBps; // paid on top of reimbursed gas
        uint16 keeperShareBps; // optional calls are paid only if pay <= this share of value realized
        uint16 allocatedBoundBps; // checkpoint skips when Allocated value exceeds this share of NAV
        uint16 clipSlippageBps; // token sale must clear refPrice x (1 - this)
        uint64 packUnitsMask; // bit u set: packs of u x 0.01 ETH may be built and listed
        uint64 gasCeiling; // wei per gas
        uint64 maxTip; // reimbursed price is at most basefee + this
        uint96 maxPositions;
        uint128 reserve; // ETH kept idle
        uint128 tvlCap; // deposits refused above this NAV
        uint128 opGasCap; // reimbursed gas per call
        uint128 clipMax; // tokens per conversion
        uint128 refPrice; // wei per 1e18 token units, last fill or admin-set
    }

    Params internal params;
    Params internal pendingParams;
    uint256 public pendingParamsEta;

    bool public depositsPaused;
    bool public listingPaused;
    bool public conversionDisabled;
    bool public windingDown;

    // ------------------------------------------------------------------ positions and inventory

    struct Position {
        uint64 packId;
        uint64 units; // pack value in 0.01 ETH
        uint128 backing;
    }

    mapping(uint256 listingId => Position) public positions;
    uint256[] internal _open; // non-terminal FWA listing ids
    mapping(uint256 listingId => uint256 indexPlusOne) internal _openIndex;
    uint256[] internal _idlePacks;
    uint256[] internal _looseShapes; // 0.01 ETH Shapes

    // ------------------------------------------------------------------ shares

    uint256 public totalShares;
    mapping(address => uint256) public sharesOf;

    uint256 public epoch; // checkpoints completed
    uint256 public lastCheckpointInterval;
    uint256 public highWaterMark; // NAV per share, 1e18 scale
    uint256 public lastNav;

    struct PendingDeposit {
        uint128 amount;
        uint64 epoch; // priced at the checkpoint that ends this epoch
    }

    mapping(address => PendingDeposit) public pendingDeposits;
    uint256 public pendingDepositTotal; // ETH escrowed, excluded from NAV
    mapping(uint256 epoch => uint256) public epochNav; // post-flow NAV used to price deposits
    mapping(uint256 epoch => uint256) public epochSupply;
    mapping(uint256 epoch => uint256) public epochDistPerShare; // accumulator when deposits were priced

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
    uint256 public redeemEra;
    uint256 public redeemG = SCALE;
    uint256 public redeemQ;
    mapping(uint256 era => uint256) public eraFinalQ;
    uint256 public redemptionReserve; // ETH owed to redeemers, excluded from NAV
    mapping(address => uint256) public claimableEth;
    uint256 public claimableTotal; // settled to holders, not yet paid: a liability like the reserves

    // Distributions: per-share accumulator over all live shares.
    uint256 public distPerShare; // wei x 1e18 per share
    mapping(address => uint256) public distDebt;
    uint256 public distributionReserve;

    uint256 public conversionInterval; // last INTERVAL index with a token sale

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
    event Converted(uint256 tokensIn, uint256 ethOut);
    event KeeperPaid(address indexed keeper, uint256 amount);
    event ParamsProposed(uint256 eta);
    event ParamsApplied();
    event Claimed(address indexed holder, uint256 amount);
    event WindDownStarted();

    error NotGuardian();
    error NotAdmin();
    error OutOfBounds();
    error TooEarly();
    error Paused();
    error WindingDown();
    error EdgeGate();
    error GasPrice();
    error NotCheckpointWindow();
    error AlreadyCheckpointed();
    error AllocatedExposure();
    error Amount();
    error Nothing();
    error Liquidity();
    error UnlistNotAllowed();
    error Slippage();
    error UnknownNft();

    // ------------------------------------------------------------------ construction

    constructor(
        IFWAV2 fwa_,
        IShapes shapes_,
        IShapePacks packs_,
        address guardian_,
        address admin_,
        uint256 paramDelay_,
        Params memory initial
    ) payable {
        if (paramDelay_ < 1 days || paramDelay_ > 30 days) revert OutOfBounds();
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        rewards = IFWARewards(fwa_.rewards());
        token = IFWAToken(fwa_.token());
        poolManager = IPoolManager(token.poolManager());
        guardian = guardian_;
        admin = admin_;
        paramDelay = paramDelay_;
        _checkBounds(initial);
        params = initial;
        shapes_.setApprovalForAll(address(packs_), true);
        packs_.setApprovalForAll(address(fwa_), true);
        // First issuance: the deployer's seed buys dead shares so the share price cannot be
        // inflated against a later first depositor.
        if (msg.value < MIN_DEPOSIT) revert Amount();
        totalShares = DEAD_SHARES;
        sharesOf[address(0xdead)] = DEAD_SHARES;
        highWaterMark = msg.value * 1e18 / DEAD_SHARES;
    }

    receive() external payable {}

    /// @dev Only Shapes and pack NFTs, the only ones the vault creates or gets back from FWA.
    function onERC721Received(address, address, uint256, bytes calldata) external view returns (bytes4) {
        if (msg.sender != address(shapes) && msg.sender != address(packs)) revert UnknownNft();
        return this.onERC721Received.selector;
    }

    // ------------------------------------------------------------------ strategy gate

    /// @notice Live economics from FWA. `backing` is what a new listing would post; zero when the
    ///         gate fails for a pack of `units` x 0.01 ETH.
    function edge(uint256 units) public view returns (uint256 k1e18, uint256 backing, bool ok) {
        Params memory p = params;
        uint256 cap;
        uint256 s;
        (k1e18, cap, s) = VaultLib.economics(fwa, address(packs));
        backing = cap * (BPS - p.bufferBps) / BPS;
        // Keep outcome must not lose: B (k - s) >= P. Bid outcome is B (k - 1) > 0 given k >= 1 +
        // edge; spending callers also require it to clear gas (`_cycleNet`).
        ok = cap != 0 && k1e18 >= 1e18 + uint256(p.minEdgeBps) * 1e14 && k1e18 > s * 1e14
            && backing * (k1e18 - s * 1e14) >= units * UNIT * 1e18;
        if (!ok) backing = 0;
    }

    /// @dev Expected net of one bid-outcome cycle after its gas, zero when not positive.
    function _cycleNet(uint256 k1e18, uint256 backing) internal view returns (uint256) {
        if (k1e18 <= 1e18) return 0;
        uint256 gross = backing * (k1e18 - 1e18) / 1e18;
        uint256 gas = _gasCost(CYCLE_GAS);
        return gross > gas ? gross - gas : 0;
    }

    /// @dev Wei the vault pays a keeper for `gasUnits`: price capped at basefee + tip and the
    ///      ceiling, plus the premium.
    function _gasCost(uint256 gasUnits) internal view returns (uint256) {
        Params memory p = params;
        uint256 price = M.min(M.min(tx.gasprice, block.basefee + p.maxTip), p.gasCeiling);
        return gasUnits * price * (BPS + p.keeperPremiumBps) / BPS;
    }

    // ------------------------------------------------------------------ inventory

    /// @notice Build `count` packs of `units` x 0.01 ETH: mint 0.1 ETH Shapes, split each into ten
    ///         0.01 Shapes (one mint fee per ten units), then pack them. Only when every new pack
    ///         can be listed right away and its build cost is repaid by one bid cycle.
    function restock(uint256 count, uint256 units) external nonReentrant {
        uint256 g0 = gasleft();
        _requireOperating();
        if (listingPaused) revert Paused();
        if (count == 0 || (params.packUnitsMask >> units) & 1 == 0) revert Amount();
        if (_open.length + _idlePacks.length + count > params.maxPositions) revert Amount();
        (uint256 k, uint256 backing, bool ok) = edge(units);
        uint256 fee = shapes.mintFee();
        if (!ok || _gasCost(RESTOCK_GAS_PER_PACK) + fee * units / SHAPES_PER_MINT > _cycleNet(k, backing)) {
            revert EdgeGate();
        }
        uint256 need = count * units;
        uint256 have = _looseShapes.length;
        uint256 mints = need > have ? (need - have + SHAPES_PER_MINT - 1) / SHAPES_PER_MINT : 0;
        // Capital for the Shapes and the backing of every pack waiting to list, new ones included.
        if (_idle() < mints * (0.1 ether + fee) + (count + _idlePacks.length) * backing) revert Liquidity();
        if (mints != 0) {
            uint8[] memory outs = new uint8[](SHAPES_PER_MINT); // index 0 = 0.01 ETH
            for (uint256 i; i < mints; ++i) {
                uint256 big = shapes.mint{value: 0.1 ether + fee}(0.1 ether);
                uint256[] memory ids = shapes.split(big, outs);
                for (uint256 j; j < ids.length; ++j) {
                    _looseShapes.push(ids[j]);
                }
            }
        }
        uint32[] memory noMint = new uint32[](9);
        for (uint256 c; c < count; ++c) {
            uint256[] memory ids = new uint256[](units);
            for (uint256 j; j < units; ++j) {
                ids[j] = _looseShapes[_looseShapes.length - 1];
                _looseShapes.pop();
            }
            _idlePacks.push(packs.createPack(ids, noMint));
        }
        emit Restocked(count, units);
        _reimburse(g0, type(uint256).max);
    }

    /// @notice List up to `maxCount` idle packs at the live gated backing.
    function list(uint256 maxCount) external nonReentrant {
        uint256 g0 = gasleft();
        _requireOperating();
        if (listingPaused) revert Paused();
        uint256 listed;
        while (listed < maxCount && _idlePacks.length != 0 && _open.length < params.maxPositions) {
            uint256 packId = _idlePacks[_idlePacks.length - 1];
            uint256 units = packs.valueOf(packId) / UNIT;
            (uint256 k, uint256 backing, bool ok) = edge(units);
            if (!ok || _cycleNet(k, backing) == 0) revert EdgeGate();
            if (_idle() < backing) break;
            _idlePacks.pop();
            uint256 listingId = fwa.listNFT{value: backing}(address(packs), packId);
            positions[listingId] = Position(uint64(packId), uint64(units), uint128(backing));
            _open.push(listingId);
            _openIndex[listingId] = _open.length;
            emit Listed(listingId, packId, backing);
            ++listed;
        }
        if (listed == 0) revert Nothing();
        _reimburse(g0, type(uint256).max);
    }

    /// @notice Resolve positions FWA has moved on: reclaim allocated ones the purchaser left past
    ///         the settlement window, fold settled and withdrawn ones back into inventory.
    ///         A pack FWA failed to deliver stays an open position until it arrives; calling sync
    ///         again retries the pull. Paid only when something resolved.
    function sync(uint256[] calldata listingIds) external nonReentrant {
        uint256 g0 = gasleft();
        uint256 resolved;
        for (uint256 i; i < listingIds.length; ++i) {
            if (_sync(listingIds[i])) ++resolved;
        }
        if (resolved == 0) revert Nothing();
        _reimburse(M.min(g0, gasleft() + resolved * GAS_PER_MOVED), type(uint256).max);
    }

    function _sync(uint256 listingId) internal returns (bool) {
        Position memory pos = positions[listingId];
        if (_openIndex[listingId] == 0) return false;
        IFWAV2 f = fwa;
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
        // FWA delivers NFTs best-effort; a failed delivery is a pull claim held for the vault.
        // The outcome comes from FWA's own record, never from inference: a pack is the vault's
        // if the vault holds it or FWA owes it. Anything else went to the purchaser.
        if (f.stuckNFTRecipient(listingId) == address(this)) {
            // Reverts while the collection still fails; the claim survives for the next try.
            (bool ok,) = address(f).call(abi.encodeCall(IFWAV2.recoverStuckNFT, (listingId)));
            if (!ok || !_owns(pos.packId)) {
                emit PackOwed(listingId);
                return false;
            }
        }
        bool packBack = _owns(pos.packId);
        if (packBack) _idlePacks.push(pos.packId);
        _removeOpen(listingId);
        emit Resolved(listingId, status, packBack);
        return true;
    }

    function _owns(uint256 packId) internal view returns (bool) {
        try packs.ownerOf(packId) returns (address o) {
            return o == address(this);
        } catch {
            return false;
        }
    }

    function _removeOpen(uint256 listingId) internal {
        uint256 idx = _openIndex[listingId] - 1;
        uint256 last = _open[_open.length - 1];
        _open[idx] = last;
        _openIndex[last] = idx + 1;
        _open.pop();
        delete _openIndex[listingId];
        delete positions[listingId];
    }

    /// @notice Activate vault listings FWA staged because its acquisition queue was busy when they
    ///         were listed: a staged listing earns no fees or token rewards. Runs FWA's own
    ///         permissionless FIFO activation; paid only per vault listing it actually activated.
    function activate(uint256[] calldata listingIds, uint256 maxCount) external nonReentrant {
        uint256 g0 = gasleft();
        bool[] memory staged = new bool[](listingIds.length);
        for (uint256 i; i < listingIds.length; ++i) {
            // Strictly increasing ids: a repeated id cannot count twice toward the pay cap.
            if (i != 0 && listingIds[i] <= listingIds[i - 1]) revert Amount();
            if (_openIndex[listingIds[i]] == 0) continue;
            (,,,,,,,,,, uint8 status) = fwa.listings(listingIds[i]);
            staged[i] = status == LISTING_STAGED;
        }
        fwa.activateListings(maxCount);
        uint256 moved;
        for (uint256 i; i < listingIds.length; ++i) {
            if (!staged[i]) continue;
            (,,,,,,,,,, uint8 status) = fwa.listings(listingIds[i]);
            if (status == LISTING_ACTIVE) ++moved;
        }
        if (moved == 0) revert Nothing();
        _reimburse(M.min(g0, gasleft() + moved * GAS_PER_MOVED), type(uint256).max);
    }

    /// @notice Withdraw active listings: allowed in wind-down, when FWA's live fees leave no edge
    ///         (k below 1 + minEdge), or to cover locked redemptions free ETH and inventory cannot.
    ///         A stale quote or a gas spike stops new listings but never unwinds earning ones.
    function unlist(uint256[] calldata listingIds) external nonReentrant {
        uint256 g0 = gasleft();
        (uint256 k,,) = edge(MIN_PACK_UNITS);
        bool ok = k >= 1e18 + uint256(params.minEdgeBps) * 1e14;
        uint256 shortfall = _redemptionShortfall();
        if (!windingDown && ok && shortfall == 0) revert UnlistNotAllowed();
        uint256 realized;
        uint256 moved;
        for (uint256 i; i < listingIds.length; ++i) {
            uint256 id = listingIds[i];
            if (_openIndex[id] == 0) continue;
            // An early crown exit costs 1% of backing; wait out the crown window instead.
            if (fwa.topListingId() == id && block.timestamp < fwa.topListingSince() + CROWN_EXIT_WINDOW) continue;
            (,,,,,,,,,, uint8 status) = fwa.listings(id);
            if (status != LISTING_ACTIVE) continue;
            Position memory pos = positions[id];
            fwa.withdrawListing(id); // reverts while FWA's queue is not drained
            _idlePacks.push(pos.packId);
            _removeOpen(id);
            emit Unlisted(id);
            realized += pos.backing + pos.units * UNIT;
            ++moved;
            if (!windingDown && ok && realized >= shortfall) break;
        }
        if (realized == 0) revert Nothing();
        _reimburse(M.min(g0, gasleft() + moved * GAS_PER_MOVED), type(uint256).max);
    }

    /// @notice Pull FWA fees into the vault: pending fees of `activeIds` (they keep earning) and
    ///         credited fees of resolved listings. Paid only if the pay is a small share of it.
    function harvest(uint256[] calldata activeIds) external nonReentrant {
        uint256 g0 = gasleft();
        uint256 before = address(this).balance;
        // One listing that moved on since the caller looked must not block the rest.
        if (activeIds.length != 0) try fwa.claimListingFees(activeIds) {} catch {}
        _harvest();
        uint256 amount = address(this).balance - before;
        if (amount == 0) revert Nothing();
        _reimburse(g0, amount);
    }

    function _harvest() internal {
        if (fwa.feeCredit(address(this)) != 0) fwa.withdrawEarnings();
    }

    // ------------------------------------------------------------------ FWA token rewards

    /// @notice Claim depositor FWA token rewards: pending rewards of `activeIds` and credit from
    ///         removed or repriced listings. Unpaid; `convert` claims and sells in one paid call.
    function harvestTokens(uint256[] calldata activeIds) external nonReentrant {
        _claimTokens(activeIds);
    }

    /// @dev FWA's claim reverts for the whole batch on one listing that is no longer active, or
    ///      when nothing is pending. Neither may block the credit withdrawal or the sale.
    function _claimTokens(uint256[] calldata activeIds) internal {
        if (activeIds.length != 0) try rewards.claimDepositorTokens(activeIds) {} catch {}
        if (rewards.tokenCredit(address(this)) != 0) rewards.withdrawTokens();
    }

    /// @notice Claim token rewards (as `harvestTokens`), then sell min(maxAmount, clipMax, held)
    ///         FWA tokens for ETH through the token's own v4 pool, at most once per FWA interval.
    ///         FWAToken transfers are locked except into that pool under its hook, so selling
    ///         there is the only way the vault can realize them; tokens count as zero in NAV
    ///         until the ETH arrives. The sale must clear both the caller's `minOut` and the
    ///         reference floor; the caller is paid only out of what the sale realized.
    function convert(uint256[] calldata activeIds, uint256 maxAmount, uint256 minOut)
        external
        nonReentrant
        returns (uint256 ethOut)
    {
        uint256 g0 = gasleft();
        Params memory p = params;
        if (conversionDisabled) revert Paused();
        uint256 interval = block.timestamp / INTERVAL;
        if (interval == conversionInterval) revert TooEarly();
        _claimTokens(activeIds);
        uint256 amount = M.min(M.min(maxAmount, p.clipMax), token.balanceOf(address(this)));
        if (amount == 0) revert Amount();
        if (p.refPrice == 0 || minOut < amount * p.refPrice / 1e18 * (BPS - p.clipSlippageBps) / BPS) {
            revert Slippage();
        }
        conversionInterval = interval;
        uint256 before = address(this).balance;
        poolManager.unlock(abi.encode(amount));
        ethOut = address(this).balance - before;
        if (ethOut < minOut) revert Slippage();
        // The floor only ratchets up: a sandwiched fill cannot lower the next sale's floor. A
        // real price fall stalls sales until the admin sets a lower reference via the delay.
        uint256 fill = ethOut * 1e18 / amount;
        if (fill > p.refPrice) params.refPrice = uint128(fill);
        emit Converted(amount, ethOut);
        _reimburse(g0, ethOut);
    }

    /// @dev v4 exact-input sell of FWA (currency1) for native ETH (currency0).
    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        if (msg.sender != address(poolManager)) revert Nothing();
        VaultLib.swapTokens(poolManager, token, abi.decode(data, (uint256)));
        return "";
    }

    // ------------------------------------------------------------------ holders

    /// @notice Escrow ETH to buy shares at the next checkpoint. Cancellable until then.
    function deposit() external payable nonReentrant {
        if (depositsPaused) revert Paused();
        if (windingDown) revert WindingDown();
        if (msg.value < MIN_DEPOSIT) revert Amount();
        if (lastNav + pendingDepositTotal + msg.value > params.tvlCap) revert Amount();
        _settleHolder(msg.sender);
        PendingDeposit storage d = pendingDeposits[msg.sender];
        d.amount += uint128(msg.value);
        d.epoch = uint64(epoch);
        pendingDepositTotal += msg.value;
        emit Deposited(msg.sender, msg.value, epoch);
    }

    function cancelDeposit() external nonReentrant {
        _settleHolder(msg.sender);
        uint256 amount = pendingDeposits[msg.sender].amount;
        if (amount == 0) revert Nothing();
        delete pendingDeposits[msg.sender];
        pendingDepositTotal -= amount;
        msg.sender.forceSafeTransferETH(amount);
        emit DepositCancelled(msg.sender, amount);
    }

    /// @notice Lock shares for redemption. Filled pro rata at checkpoints as ETH frees up; the
    ///         unfilled part stays exposed to the vault until filled.
    function requestRedeem(uint256 amount) external nonReentrant {
        _settleHolder(msg.sender);
        if (amount == 0 || amount > sharesOf[msg.sender]) revert Amount();
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
            uint256 minted = uint256(d.amount) * epochSupply[d.epoch] / epochNav[d.epoch];
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
    function checkpoint() external nonReentrant {
        uint256 g0 = gasleft();
        IFWAV2 f = fwa;
        if (!f.isPurchaseBlackout() || f.unsettledAcquisitionCount() != 0) revert NotCheckpointWindow();
        uint256 interval = block.timestamp / INTERVAL;
        if (interval == lastCheckpointInterval) revert AlreadyCheckpointed();
        // Only with holder flows to settle, or with distributions on: a no-op checkpoint would
        // use up the interval's one slot and delay flows that arrive later in the blackout.
        bool work = pendingDepositTotal != 0 || lockedShares != 0;
        if (!work && params.distributionBps == 0) revert Nothing();
        lastCheckpointInterval = interval;

        // Value every open position from FWA state, read-only: resolving is sync's job, so the
        // loop costs the same per position whatever FWA did to them.
        uint256 navPositions;
        uint256 allocatedValue;
        uint256 s = f.ownerSettlementFeeBps();
        for (uint256 i; i < _open.length; ++i) {
            uint256 id = _open[i];
            Position memory pos = positions[id];
            (,,,,,,,,,, uint8 status) = f.listings(id);
            uint256 value = pos.units * UNIT;
            if (status == LISTING_ACTIVE) {
                navPositions += value + pos.backing + f.pendingFees(id);
            } else if (status == LISTING_STAGED) {
                navPositions += value + pos.backing;
            } else if (status == LISTING_ALLOCATED) {
                // Both outcomes pay at least the lesser of the pack and the net backing.
                uint256 floorValue = M.min(value, pos.backing * (BPS - s) / BPS);
                navPositions += floorValue;
                allocatedValue += floorValue;
            } else if (_owns(pos.packId) || f.stuckNFTRecipient(id) == address(this)) {
                // Settled or withdrawn, not yet synced: every ETH leg already reached the
                // balance or fee credit; the pack is held or owed to the vault.
                navPositions += value;
            }
        }
        _harvest();
        uint256 inventory = _looseShapes.length * UNIT;
        for (uint256 i; i < _idlePacks.length; ++i) {
            inventory += packs.valueOf(_idlePacks[i]);
        }
        uint256 nav = _free() + navPositions + inventory;
        if (allocatedValue * BPS > nav * params.allocatedBoundBps) revert AllocatedExposure();

        uint256 supply = totalShares;
        // 1. Redemptions at the pre-flow price, funded by free ETH and new deposits. Inventory is
        //    turned into ETH beforehand by `liquidate`, so this call stays bounded.
        uint256 filled;
        uint256 paid;
        if (lockedShares != 0) {
            // Owed rounds up and a partial fill leaves 2 wei of headroom, so the rounded-up
            // reserve below never exceeds the ETH actually freed.
            uint256 owed = M.mulDivUp(lockedShares, nav, supply);
            uint256 liquid = _free() + pendingDepositTotal;
            uint256 frac = owed <= liquid ? SCALE : M.mulDiv(liquid > 2 ? liquid - 2 : 0, SCALE, owed);
            filled = M.mulDiv(lockedShares, frac, SCALE);
            // ETH per locked share this checkpoint, x SCALE. Holders claim floor(shares x unit);
            // the reserve rounds the same unit up over the (never understated) locked total, so
            // it always covers the sum of claims.
            uint256 unit = M.mulDiv(frac, nav, supply);
            paid = M.mulDivUp(lockedShares, unit, SCALE);
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
            totalShares += pendingDepositTotal * supply / nav;
            nav += pendingDepositTotal;
            pendingDepositTotal = 0;
        }
        lastNav = nav;
        emit Checkpoint(epoch, nav, totalShares, filled, paid, distributed);
        ++epoch;
        _reimburse(g0, work || distributed != 0 ? type(uint256).max : 0);
    }

    /// @notice Redeem up to `maxCount` idle packs (then loose Shapes) to ETH at their exact
    ///         backing, while locked redemptions exceed free ETH, or freely in wind-down.
    function liquidate(uint256 maxCount) external nonReentrant {
        uint256 g0 = gasleft();
        if (!windingDown && _owedEstimate() <= _free() + pendingDepositTotal) revert Nothing();
        maxCount = M.min(maxCount, MAX_LIQUIDATIONS);
        uint256 before = address(this).balance;
        uint256 n;
        uint256 m;
        while (n + m < maxCount && (windingDown || _owedEstimate() > _free() + pendingDepositTotal)) {
            if (_idlePacks.length != 0) {
                packs.redeem(_idlePacks[_idlePacks.length - 1]);
                _idlePacks.pop();
                ++n;
            } else if (_looseShapes.length != 0) {
                shapes.redeem(_looseShapes[_looseShapes.length - 1]);
                _looseShapes.pop();
                ++m;
            } else {
                break;
            }
        }
        if (n + m == 0) revert Nothing();
        emit Liquidated(n, m, address(this).balance - before);
        _reimburse(g0, type(uint256).max);
    }

    /// @dev ETH locked shares will need at the last checkpoint's price, rounded up.
    function _owedEstimate() internal view returns (uint256) {
        if (lockedShares == 0) return 0;
        return M.mulDivUp(lockedShares, lastNav, totalShares);
    }

    function _redemptionShortfall() internal view returns (uint256) {
        uint256 owed = _owedEstimate();
        uint256 inventory = _free() + _looseShapes.length * UNIT;
        for (uint256 i; i < _idlePacks.length; ++i) {
            inventory += packs.valueOf(_idlePacks[i]);
        }
        return owed > inventory ? owed - inventory : 0;
    }

    /// @dev The vault's own ETH: balance less escrowed deposits and every amount owed to holders,
    ///      whether still in a shared reserve or already settled to a holder's claimable balance.
    ///      Forced ETH lands here, so it is attributed by balance, never by callback.
    function _free() internal view returns (uint256) {
        uint256 owed = pendingDepositTotal + redemptionReserve + distributionReserve + claimableTotal;
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

    /// @dev Reimburse the caller's gas plus premium from vault ETH, at most `opGasCap` gas.
    ///      `realized` is the value an optional call produced: it pays only when the pay is at
    ///      most `keeperShareBps` of that value, so dust harvests and sales earn nothing.
    ///      type(uint256).max marks necessary work (always paid); zero marks no work.
    function _reimburse(uint256 g0, uint256 realized) internal {
        uint256 amount = _gasCost(M.min(g0 - gasleft() + KEEPER_OVERHEAD_GAS, params.opGasCap));
        if (realized != type(uint256).max && amount * BPS > realized * params.keeperShareBps) return;
        amount = M.min(amount, _free());
        if (amount == 0) return;
        msg.sender.forceSafeTransferETH(amount);
        emit KeeperPaid(msg.sender, amount);
    }

    function _requireOperating() internal view {
        if (windingDown) revert WindingDown();
        if (tx.gasprice > params.gasCeiling) revert GasPrice();
    }

    // ------------------------------------------------------------------ roles

    function proposeParams(Params calldata p) external {
        if (msg.sender != admin) revert NotAdmin();
        _checkBounds(p);
        pendingParams = p;
        pendingParamsEta = block.timestamp + paramDelay;
        emit ParamsProposed(pendingParamsEta);
    }

    function applyParams() external {
        if (pendingParamsEta == 0 || block.timestamp < pendingParamsEta) revert TooEarly();
        Params memory p = pendingParams;
        // refPrice follows fills; a proposal moves it only when it names a nonzero value.
        if (p.refPrice == 0) p.refPrice = params.refPrice;
        params = p;
        delete pendingParams;
        pendingParamsEta = 0;
        emit ParamsApplied();
    }

    /// @notice Guardian stops: each flag can only be raised, and wind-down is one-way.
    function guard(bool pauseDeposits, bool pauseListing, bool disableConversion, bool cancelProposal) external {
        if (msg.sender != guardian) revert NotGuardian();
        if (pauseDeposits) depositsPaused = true;
        if (pauseListing) listingPaused = true;
        if (disableConversion) conversionDisabled = true;
        if (cancelProposal) {
            delete pendingParams;
            pendingParamsEta = 0;
        }
    }

    /// @notice Guardian may lower caps immediately; raising goes through the admin delay.
    function lowerCaps(uint128 tvlCap, uint96 maxPositions, uint64 gasCeiling) external {
        if (msg.sender != guardian) revert NotGuardian();
        Params storage p = params;
        if (tvlCap > p.tvlCap || maxPositions > p.maxPositions || gasCeiling > p.gasCeiling) revert OutOfBounds();
        p.tvlCap = tvlCap;
        p.maxPositions = maxPositions;
        p.gasCeiling = gasCeiling;
    }

    function startWindDown() external {
        if (msg.sender != guardian) revert NotGuardian();
        windingDown = true;
        depositsPaused = true;
        listingPaused = true;
        emit WindDownStarted();
    }

    /// @notice Admin unpause goes through the delay like any parameter, never immediately.
    function _checkBounds(Params memory p) internal pure {
        if (
            p.minEdgeBps > MAX_MIN_EDGE_BPS || p.bufferBps > MAX_BUFFER_BPS || p.distributionBps > MAX_DISTRIBUTION_BPS
                || p.keeperPremiumBps > MAX_KEEPER_PREMIUM_BPS || p.keeperShareBps > MAX_KEEPER_SHARE_BPS
                || p.allocatedBoundBps > MAX_ALLOCATED_BOUND_BPS || p.clipSlippageBps > MAX_CLIP_SLIPPAGE_BPS
                || p.gasCeiling > MAX_GAS_CEILING || p.maxTip > p.gasCeiling || p.maxPositions > MAX_POSITIONS || p.opGasCap > 16_777_216
                || p.packUnitsMask >> (MAX_PACK_UNITS + 1) != 0 || p.packUnitsMask & ((1 << MIN_PACK_UNITS) - 1) != 0
        ) revert OutOfBounds();
    }

    // ------------------------------------------------------------------ views

    function getParams() external view returns (Params memory) {
        return params;
    }

    function getPendingParams() external view returns (Params memory) {
        return pendingParams;
    }

    function openListings() external view returns (uint256[] memory) {
        return _open;
    }

    function idlePacks() external view returns (uint256[] memory) {
        return _idlePacks;
    }

    function looseShapeCount() external view returns (uint256) {
        return _looseShapes.length;
    }

    /// @notice Shares including a deposit already priced but not yet converted (lazy).
    function shareBalance(address h) external view returns (uint256 shares) {
        shares = sharesOf[h];
        PendingDeposit memory d = pendingDeposits[h];
        if (d.amount != 0 && d.epoch < epoch) shares += uint256(d.amount) * epochSupply[d.epoch] / epochNav[d.epoch];
    }

    function idleEth() external view returns (uint256) {
        return _idle();
    }
}
