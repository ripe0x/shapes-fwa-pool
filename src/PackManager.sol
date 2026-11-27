// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {PackAccount} from "./PackAccount.sol";
import {VaultLib} from "./VaultLib.sol";
import {StrategyLib} from "./StrategyLib.sol";
import {IShapes, IShapePacks, IFWAV2, IERC721Min} from "./interfaces/External.sol";

interface IImportPackCustody {
    function shapes() external view returns (address);
    function packOf(uint256 shapeId) external view returns (uint256);
}

/// @title PackManager
/// @notice A personal FWA pack manager: one owner's ETH, Shape packs and FWA listings, run by the
///         same strategy as the pooled PackVault (PackAccount). No shares, NAV or checkpoints: every
///         asset belongs to the owner, who can withdraw free ETH and idle packs at any time and
///         exit FWA positions through the ordinary unlist and settlement path. Deployed as an
///         ERC-1167 clone by PackManagerFactory, which initializes it atomically and keeps no
///         authority over it afterwards.
/// @dev Maintenance is permissionless and paid for bounded measured work from this manager's budgets and ETH
///      only; the owner may run any of it unpaid. The owner can raise keeper pay to the bytecode
///      maxima, which only moves the owner's own ETH. Committed FWA positions are never withdrawn
///      instantly: exiting unlists Active positions (outside the crown window) and waits for
///      Allocated ones to settle.
contract PackManager is PackAccount {
    using SafeTransferLib for address;

    /// @notice The factory allowed to initialize clones of this implementation; it has no other role.
    address public immutable factory;
    bool private _initialized;

    event Withdrawn(address indexed to, uint256 amount);
    event PacksWithdrawn(address indexed to, uint256 count);
    event Rescued(address indexed collection, uint256 indexed tokenId, address indexed to);
    event ListingPaused(bool paused);
    event Exiting(bool exiting);
    event PackImported(uint256 indexed packId, uint256 value, uint256 shapeCount);

    error Tracked();
    error InvalidPack();

    uint256 private constant PACK_CONTENTS_GAS = 150_000;

    constructor(IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_) PackAccount(fwa_, shapes_, packs_) {
        factory = msg.sender;
        _initialized = true; // the implementation itself can never be initialized
    }

    /// @notice Set the owner, parameters (within bytecode bounds), and approve
    ///         FWA for pack listings. Once, by the factory, in the clone's creation transaction.
    function initialize(address owner_, VaultLib.Params calldata p, uint256 design_) external payable {
        if (msg.sender != factory) revert Unauthorized();
        if (_initialized) revert AlreadyInitialized();
        _initialized = true;
        // Neither the factory nor the manager itself can act as an owner: funds would lock.
        if (owner_ == msg.sender || owner_ == address(this)) revert Unauthorized();
        _initStrategy(owner_, p);
        _setDesign(design_);
    }

    // ------------------------------------------------------------------ account hooks

    /// @dev Everything the manager holds belongs to its owner: no liabilities.
    function _free() internal view override returns (uint256) {
        return address(this).balance;
    }

    function _idle() internal view override returns (uint256) {
        uint256 reserve = operatingReserve();
        return address(this).balance > reserve ? address(this).balance - reserve : 0;
    }

    // ------------------------------------------------------------------ owner

    /// @notice Send `amount` of this manager's ETH (any part of its balance) to `to`.
    function withdraw(address to, uint256 amount) external onlyOwner nonReentrant {
        to.safeTransferETH(amount);
        emit Withdrawn(to, amount);
    }

    /// @notice Transfer up to `count` intact packs: idle first, then sealed recovery inventory.
    ///         Unsealed recovery is a claim, not a transferable pack NFT.
    function withdrawPacks(address to, uint256 count) external onlyOwner nonReentrant {
        if (count > MAX_BATCH) revert VaultLib.BadBatch();
        VaultLib.Book storage b = s.book;
        uint256 n;
        while (n < count && (b.idlePacks.length != 0 || b.recoveryPacks.length != 0)) {
            uint256 packId;
            if (b.idlePacks.length != 0) {
                packId = b.idlePacks[b.idlePacks.length - 1];
                VaultLib.redeemInventory(b, packId);
            } else {
                packId = b.recoveryPacks[b.recoveryPacks.length - 1];
                if (b.recoveryUnsealed[packId] || packs.claimantOf(packId) != address(0)
                    || packs.ownerOf(packId) != address(this)) revert InvalidPack();
                VaultLib.withdrawRecoveryInventory(b, b.recoveryPacks.length - 1);
            }
            packs.transferFrom(address(this), to, packId);
            ++n;
        }
        if (n == 0) revert Tracked();
        emit PacksWithdrawn(to, n);
    }

    /// @notice Withdraw a sealed recovery pack without being blocked by another unsealed claim.
    function withdrawRecoveryPack(address to, uint256 index, uint256 expectedPackId) external onlyOwner nonReentrant {
        VaultLib.Book storage b = s.book;
        if (index >= b.recoveryPacks.length || b.recoveryPacks[index] != expectedPackId) revert InvalidPack();
        if (b.recoveryUnsealed[expectedPackId] || packs.claimantOf(expectedPackId) != address(0)
            || packs.ownerOf(expectedPackId) != address(this)) revert InvalidPack();
        VaultLib.withdrawRecoveryInventory(b, index);
        packs.transferFrom(address(this), to, expectedPackId);
        emit PacksWithdrawn(to, 1);
    }

    /// @notice Adopt sealed canonical packs held here, or pull approved packs from this owner.
    ///         Import records existing principal and actual Shapes; it never mints or pays a keeper.
    function importPacks(uint256[] calldata ids, bytes32 expected) external onlyOwner nonReentrant {
        _checkConfiguration(expected);
        if (ids.length == 0 || ids.length > MAX_BATCH) revert VaultLib.BadBatch();
        IImportPackCustody custody = IImportPackCustody(address(packs));
        if (custody.shapes() != address(shapes)) revert InvalidPack();
        VaultLib.Book storage b = s.book;
        for (uint256 i; i < ids.length; ++i) {
            uint256 packId = ids[i];
            if (b.idleValueOf[packId] != 0 || b.packToListing[packId] != 0) revert Tracked();
            address holder = packs.ownerOf(packId);
            if ((holder != msg.sender && holder != address(this)) || packs.claimantOf(packId) != address(0)) {
                revert InvalidPack();
            }
            uint256 value = packs.valueOf(packId);
            if (value == 0 || value % VaultLib.UNIT != 0) revert InvalidPack();
            uint256[] memory contents = _importContents(packId);
            uint256 actualValue;
            for (uint256 j; j < contents.length; ++j) {
                uint256 shapeId = contents[j];
                if (shapes.ownerOf(shapeId) != address(packs) || custody.packOf(shapeId) != packId) revert InvalidPack();
                uint256 backing = shapes.backingOf(shapeId);
                if (backing == 0) revert InvalidPack();
                actualValue += backing;
            }
            if (actualValue != value) revert InvalidPack();
            if (holder == msg.sender) packs.transferFrom(msg.sender, address(this), packId);
            VaultLib.addInventory(b, packId, value);
            // addInventory assumes one .01 Shape per unit for ordinary external returns.
            if (value <= VaultLib.MAX_PACK_UNITS * VaultLib.UNIT) {
                b.ordinaryShapeCount = b.ordinaryShapeCount - b.packShapeCount[packId] + contents.length;
            }
            b.packShapeCount[packId] = contents.length;
            emit PackImported(packId, value, contents.length);
        }
    }

    /// @dev Canonical unseal burns the NFT. The live NFT, zero claimant and Shape custody prove
    ///      sealed inventory. Bound both execution and returndata before copying a contents array.
    function _importContents(uint256 packId) private view returns (uint256[] memory ids) {
        bytes memory input = abi.encodeWithSelector(IShapePacks.contentsOf.selector, packId);
        address target = address(packs);
        bool success;
        uint256 size;
        assembly ("memory-safe") {
            success := staticcall(PACK_CONTENTS_GAS, target, add(input, 32), mload(input), 0, 0)
            size := returndatasize()
        }
        if (!success || size < 96 || size > 64 + 32 * VaultLib.MAX_REDEEM_SHAPES) revert InvalidPack();
        bytes memory result = new bytes(size);
        assembly ("memory-safe") {
            returndatacopy(add(result, 32), 0, size)
        }
        ids = abi.decode(result, (uint256[]));
        if (ids.length == 0 || ids.length > VaultLib.MAX_REDEEM_SHAPES) revert InvalidPack();
    }

    /// @notice Owner-funded unlisting preserves packs for withdrawal without enabling liquidation.
    function unlistForWithdrawal(uint256[] calldata listingIds) external onlyOwner nonReentrant {
        if (listingIds.length == 0 || listingIds.length > MAX_BATCH) revert VaultLib.BadBatch();
        s.callerFunded = true;
        StrategyLib.unlist(s, fwa, packs, listingIds, 0, type(uint256).max, 0);
        s.callerFunded = false;
    }

    /// @notice Transfer an ERC-721 the book does not track (sent here from outside) to `to`.
    function rescue(IERC721Min collection, uint256 tokenId, address to) external onlyOwner nonReentrant {
        if (address(collection) == address(packs)
            && (s.book.idleValueOf[tokenId] != 0 || s.book.packToListing[tokenId] != 0)) revert Tracked();
        collection.transferFrom(address(this), to, tokenId);
        emit Rescued(address(collection), tokenId, to);
    }

    /// @notice Stop or resume new listings and builds. Positions, settlement and exits continue.
    function setListingPaused(bool paused) external onlyOwner {
        s.listingPaused = paused;
        emit ListingPaused(paused);
    }

    /// @notice Exit mode: pauses listing and lets anyone unlist every Active position and
    ///         liquidate idle packs. This exit work is unpaid; callers cover their own gas.
    ///         Reversible; leaving exit mode keeps listing paused until the owner resumes it.
    function setExiting(bool exiting) external onlyOwner {
        s.windingDown = exiting;
        if (exiting) s.listingPaused = true;
        emit Exiting(exiting);
    }
}
