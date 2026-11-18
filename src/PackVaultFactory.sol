// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {PackVault} from "./PackVault.sol";
import {VaultLib} from "./VaultLib.sol";
import {KeeperPolicyV1} from "./KeeperPolicy.sol";
import {FWAExposureRegistry} from "./FWAExposureRegistry.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @notice Deploys independently priced pools with a single aggregate FWA guard.
/// @dev Each new pool is seeded and holds its own assets and holder claims. No
///      global shares or global NAV. The owner creates pools as capacity needs grow.
contract PackVaultFactory {
    error Unauthorized();

    address public immutable owner;
    IFWAV2 public immutable fwa;
    IShapes public immutable shapes;
    IShapePacks public immutable packs;
    KeeperPolicyV1 public immutable policy;
    FWAExposureRegistry public immutable exposure;
    address[] private _vaults;

    event VaultCreated(uint256 indexed index, address indexed vault, uint256 seed);

    constructor(IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_, address owner_, uint256 maxShareBps) {
        if (owner_ == address(0)) revert Unauthorized();
        owner = owner_;
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        policy = new KeeperPolicyV1();
        exposure = new FWAExposureRegistry(fwa_, maxShareBps);
    }

    function createVault(VaultLib.Params calldata params) external payable returns (PackVault vault) {
        if (msg.sender != owner) revert Unauthorized();
        vault = new PackVault{value: msg.value}(
            fwa, shapes, packs, owner, params, policy, exposure
        );
        exposure.registerVault(address(vault));
        _vaults.push(address(vault));
        emit VaultCreated(_vaults.length - 1, address(vault), msg.value);
    }

    function vaultCount() external view returns (uint256) {
        return _vaults.length;
    }

    function vaultAt(uint256 index) external view returns (address) {
        return _vaults[index];
    }
}
