// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {PackVault} from "./PackVault.sol";
import {VaultLib} from "./VaultLib.sol";
import {KeeperPolicyV1} from "./KeeperPolicy.sol";
import {FWAExposureRegistry} from "./FWAExposureRegistry.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @notice Factory for independently priced pools sharing one FWA exposure cap.
/// @dev Creation code is supplied as calldata and verified by its immutable
///      hash. Embedding the vault's creation code would exceed EIP-170.
///      Only the owner may deploy, and each instance has isolated holder NAV.
contract PackVaultFactory {
    error Unauthorized();
    error InvalidCode();
    error DeployFailed();

    address public immutable owner;
    IFWAV2 public immutable fwa;
    IShapes public immutable shapes;
    IShapePacks public immutable packs;
    KeeperPolicyV1 public immutable policy;
    FWAExposureRegistry public immutable exposure;
    bytes32 public immutable vaultCreationHash;
    address[] private _vaults;

    event VaultCreated(uint256 indexed index, address indexed vault, uint256 seed);

    constructor(
        IFWAV2 fwa_, IShapes shapes_, IShapePacks packs_, address owner_,
        uint256 maxShareBps, bytes32 expectedVaultCreationHash
    ) {
        if (owner_ == address(0) || expectedVaultCreationHash == bytes32(0)) revert Unauthorized();
        owner = owner_;
        fwa = fwa_;
        shapes = shapes_;
        packs = packs_;
        vaultCreationHash = expectedVaultCreationHash;
        policy = new KeeperPolicyV1();
        exposure = new FWAExposureRegistry(fwa_, maxShareBps);
    }

    function createVault(VaultLib.Params calldata params, bytes calldata creationCode)
        external payable returns (PackVault vault)
    {
        if (msg.sender != owner) revert Unauthorized();
        if (keccak256(creationCode) != vaultCreationHash) revert InvalidCode();
        // The checked code plus constructor args guarantees the vault immutables,
        // including the coordinator and the fee policy, cannot be substituted.
        bytes memory code = bytes.concat(creationCode, abi.encode(
            fwa, shapes, packs, owner, params, policy, exposure
        ));
        address deployed;
        assembly ("memory-safe") {
            deployed := create(callvalue(), add(code, 32), mload(code))
        }
        if (deployed == address(0) || deployed.code.length == 0) revert DeployFailed();
        vault = PackVault(payable(deployed));
        exposure.registerVault(deployed);
        _vaults.push(deployed);
        emit VaultCreated(_vaults.length - 1, deployed, msg.value);
    }

    function vaultCount() external view returns (uint256) {
        return _vaults.length;
    }

    function vaultAt(uint256 index) external view returns (address) {
        return _vaults[index];
    }
}
