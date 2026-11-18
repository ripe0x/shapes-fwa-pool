// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {IFWAV2, LISTING_ACTIVE} from "./interfaces/External.sol";

/// @notice Admission guard shared by independently accounted FWA pack vaults.
/// @dev Uses *booked*, not merely active, weight: stale terminal records only
///      make the guard more conservative. It never prices contributor shares.
///      Each accepted listing must be Active before it can be booked.
contract FWAExposureRegistry {
    error Unauthorized();
    error InvalidListing();
    error ExposureExceeded();

    IFWAV2 public immutable fwa;
    address public immutable factory;
    uint256 public immutable maxShareBps;

    mapping(address => bool) public isVault;
    mapping(uint256 => address) public listingVault;
    mapping(uint256 => uint256) public listingWeight;
    uint256 public bookedWeight;

    event VaultRegistered(address indexed vault);
    event Booked(address indexed vault, uint256 indexed listingId, uint256 weight);
    event Released(address indexed vault, uint256 indexed listingId, uint256 weight);

    constructor(IFWAV2 fwa_, uint256 maxShareBps_) {
        if (address(fwa_) == address(0) || maxShareBps_ == 0 || maxShareBps_ > 2_500) {
            revert ExposureExceeded();
        }
        fwa = fwa_;
        factory = msg.sender;
        maxShareBps = maxShareBps_;
    }

    function registerVault(address vault) external {
        if (msg.sender != factory || vault == address(0) || isVault[vault]) revert Unauthorized();
        isVault[vault] = true;
        emit VaultRegistered(vault);
    }

    function book(uint256 listingId) external {
        if (!isVault[msg.sender] || listingVault[listingId] != address(0)) revert Unauthorized();
        (, address depositor,,, uint256 weight,,,,,, uint8 status) = fwa.listings(listingId);
        if (depositor != msg.sender || status != LISTING_ACTIVE || weight == 0) revert InvalidListing();
        uint256 afterWeight = bookedWeight + weight;
        // totalWeight already contains the newly listed active position. Do not
        // add weight to the denominator a second time.
        if (afterWeight * 10_000 > fwa.totalWeight() * maxShareBps) revert ExposureExceeded();
        listingVault[listingId] = msg.sender;
        listingWeight[listingId] = weight;
        bookedWeight = afterWeight;
        emit Booked(msg.sender, listingId, weight);
    }

    function release(uint256 listingId) external {
        if (listingVault[listingId] != msg.sender) revert Unauthorized();
        uint256 weight = listingWeight[listingId];
        delete listingVault[listingId];
        delete listingWeight[listingId];
        bookedWeight -= weight;
        emit Released(msg.sender, listingId, weight);
    }
}
