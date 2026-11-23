// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {SafeTransferLib} from "solady/utils/SafeTransferLib.sol";
import {PackAccount} from "./PackAccount.sol";
import {VaultLib} from "./VaultLib.sol";
import {IShapes, IShapePacks, IFWAV2, IERC721Min} from "./interfaces/External.sol";

/// @title PackManager
/// @notice A personal FWA pack manager: one owner's ETH, Shape packs and FWA listings, run by the
///         same strategy as the pooled PackVault (PackAccount). No shares, NAV or checkpoints: every
///         asset belongs to the owner, who can withdraw free ETH and idle packs at any time and
///         exit FWA positions through the ordinary unlist and settlement path. Deployed as an
///         ERC-1167 clone by PackManagerFactory, which initializes it atomically and keeps no
///         authority over it afterwards.
/// @dev Maintenance is permissionless and paid by quote from this manager's own budgets and ETH
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

    error Tracked();

    constructor(IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_) PackAccount(fwa_, shapes_, packs_) {
        factory = msg.sender;
        _initialized = true; // the implementation itself can never be initialized
    }

    /// @notice Set the owner, parameters (within bytecode bounds) and keeper policy, and approve
    ///         FWA for pack listings. Once, by the factory, in the clone's creation transaction.
    function initialize(address owner_, VaultLib.Params calldata p, address policy) external payable {
        if (msg.sender != factory) revert Unauthorized();
        if (_initialized) revert AlreadyInitialized();
        _initialized = true;
        // Neither the factory nor the manager itself can act as an owner: funds would lock.
        if (owner_ == msg.sender || owner_ == address(this)) revert Unauthorized();
        _initStrategy(owner_, p, policy);
    }

    // ------------------------------------------------------------------ account hooks

    /// @dev Everything the manager holds belongs to its owner: no liabilities.
    function _free() internal view override returns (uint256) {
        return address(this).balance;
    }

    function _idle() internal view override returns (uint256) {
        uint256 reserve = s.params.reserve;
        return address(this).balance > reserve ? address(this).balance - reserve : 0;
    }

    // ------------------------------------------------------------------ owner

    /// @notice Send `amount` of this manager's ETH (any part of its balance) to `to`.
    function withdraw(address to, uint256 amount) external onlyOwner nonReentrant {
        to.safeTransferETH(amount);
        emit Withdrawn(to, amount);
    }

    /// @notice Take up to `count` idle packs (the most recently returned first) out of the book
    ///         and transfer them to `to`.
    function withdrawPacks(address to, uint256 count) external onlyOwner nonReentrant {
        VaultLib.Book storage b = s.book;
        uint256 n;
        while (n < count && b.idlePacks.length != 0) {
            uint256 packId = b.idlePacks[b.idlePacks.length - 1];
            VaultLib.redeemInventory(b, packId);
            packs.transferFrom(address(this), to, packId);
            ++n;
        }
        if (n == 0) revert Tracked();
        emit PacksWithdrawn(to, n);
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
    ///         liquidate idle packs (essential work, paid only if the essential budget allows).
    ///         Reversible; leaving exit mode keeps listing paused until the owner resumes it.
    function setExiting(bool exiting) external onlyOwner {
        s.windingDown = exiting;
        if (exiting) s.listingPaused = true;
        emit Exiting(exiting);
    }
}
