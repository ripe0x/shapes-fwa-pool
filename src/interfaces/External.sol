// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @dev Minimal surfaces of the deployed contracts this repo calls, taken from their verified
///      sources: FWAV2 0x958C41181182e76F221331b2755b77D9e1426A98, FWAV2Rewards
///      0xA54b44C7a894AA19C49734A753D01f9B8C5f6516, Shapes 0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0,
///      ShapePacks 0xf21514B090Da7dF4390803497d6ae673801E5cA7, the FWA floor oracle and the
///      Uniswap v4 PoolManager the FWA token reports.

interface IERC721Min {
    function ownerOf(uint256 tokenId) external view returns (address);
    function setApprovalForAll(address operator, bool approved) external;
    function transferFrom(address from, address to, uint256 tokenId) external;
}

interface IShapes is IERC721Min {
    function mint(uint256 amountWei) external payable returns (uint256 tokenId);
    function mintFee() external view returns (uint256);
    function split(uint256 tokenId, uint8[] calldata outDenoms) external returns (uint256[] memory newIds);
    function redeem(uint256 tokenId) external;
    function backingOf(uint256 tokenId) external view returns (uint256);
}

interface IShapePacks is IERC721Min {
    function createPack(uint256[] calldata shapeIds, uint32[] calldata mintCounts)
        external
        payable
        returns (uint256 packId);
    function redeem(uint256 packId) external;
    function valueOf(uint256 packId) external view returns (uint256);
    function contentsOf(uint256 packId) external view returns (uint256[] memory);
}

interface IFloorOracle {
    function getFloorRange(address collection)
        external
        view
        returns (uint256 bidPrice, uint256 askPrice, uint48 observedAt, uint48 periodUsed);
}

/// @dev FWAV2 ListingStatus values.
uint8 constant LISTING_ACTIVE = 1;
uint8 constant LISTING_ALLOCATED = 2;
uint8 constant LISTING_WITHDRAWN = 3;
uint8 constant LISTING_SETTLED = 4;
uint8 constant LISTING_STAGED = 5;

interface IFWAV2 {
    function listNFT(address collection, uint256 tokenId) external payable returns (uint256 listingId);
    function withdrawListing(uint256 listingId) external;
    function activateListings(uint256 maxCount) external;
    function claimListingFees(uint256[] calldata listingIds) external returns (uint256 total);
    function withdrawEarnings() external returns (uint256 amount);
    function depositorReclaimBacking(uint256 listingId) external;
    function depositorReclaimNFT(uint256 listingId) external;
    function recoverStuckNFT(uint256 listingId) external;
    function stuckNFTRecipient(uint256 listingId) external view returns (address);
    function finalizeUnsettled(uint256 listingId) external;
    function pendingFees(uint256 listingId) external view returns (uint256);
    function feeCredit(address depositor) external view returns (uint256);
    function listings(uint256 listingId)
        external
        view
        returns (
            address collection,
            address depositor,
            address purchaser,
            uint256 tokenId,
            uint256 weight,
            uint256 value,
            uint256 feeShare,
            uint256 feeDebt,
            uint256 slot,
            uint64 allocatedAt,
            uint8 status
        );
    function unsettledAcquisitionCount() external view returns (uint256);
    function stagingHead() external view returns (uint256);
    function isPurchaseBlackout() external view returns (bool);
    function canDeposit(address collection) external view returns (bool);
    function oracleExemptCollections(address collection) external view returns (bool);
    function floorOracle() external view returns (address);
    function oracleCeilingPremiumBps() external view returns (uint256);
    function maxOracleAge() external view returns (uint48);
    function minOracleChallengePeriod() external view returns (uint48);
    function ownerAcquisitionFeeBps() external view returns (uint256);
    function ownerSettlementFeeBps() external view returns (uint256);
    function topListingShareBps() external view returns (uint256);
    function topListingId() external view returns (uint256);
    function topListingSince() external view returns (uint64);
    function settlementDiscountBps() external view returns (uint256);
    function settlementWindow() external view returns (uint256);
    function finalizeWindow() external view returns (uint256);
    function acquisitionFee() external view returns (uint256);
    function totalWeight() external view returns (uint256);
    function weightedBackingTotal() external view returns (uint256);
    function activeListingCount() external view returns (uint256);
    function token() external view returns (address);
    function rewards() external view returns (address);
}

interface IFWARewards {
    function claimDepositorTokens(uint256[] calldata listingIds) external returns (uint256 total);
    function withdrawTokens() external returns (uint256 amount);
    function pendingDepositorTokens(uint256 listingId) external view returns (uint256);
    function tokenCredit(address depositor) external view returns (uint256);
}

interface IERC20Min {
    function balanceOf(address account) external view returns (uint256);
    function totalSupply() external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @dev Uniswap v4 types, ABI-compatible with v4-core: Currency is an address, BalanceDelta packs
///      amount0 in the high 128 bits and amount1 in the low 128 bits.
struct PoolKey {
    address currency0;
    address currency1;
    uint24 fee;
    int24 tickSpacing;
    address hooks;
}

struct SwapParams {
    bool zeroForOne;
    int256 amountSpecified;
    uint160 sqrtPriceLimitX96;
}

interface IFWAToken is IERC20Min {
    function poolManager() external view returns (address);
    function poolKey() external view returns (PoolKey memory);
    function isDistributor(address account) external view returns (bool);
    /// Allowed for any holder, though transfers are otherwise locked (probed on a fork).
    function burn(uint256 amount) external;
}

interface IPoolManager {
    function unlock(bytes calldata data) external returns (bytes memory);
    function swap(PoolKey calldata key, SwapParams calldata params, bytes calldata hookData)
        external
        returns (int256 delta);
    function take(address currency, address to, uint256 amount) external;
    function sync(address currency) external;
    function settle() external payable returns (uint256);
}
