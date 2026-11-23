// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {LibClone} from "solady/utils/LibClone.sol";
import {PackManager} from "./PackManager.sol";
import {VaultLib} from "./VaultLib.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @title PackManagerFactory
/// @notice Permissionless creation and discovery of personal PackManagers. Each manager is an
///         ERC-1167 clone of one immutable implementation, initialized in the same transaction
///         with its owner, bounded parameters and the default keeper policy, and funded with any
///         ETH sent. The factory has no owner, charges nothing, holds no ETH after a call and has
///         no authority over a manager once created.
contract PackManagerFactory {
    PackManager public immutable implementation;
    /// @notice Keeper payment policy every new manager starts with; its owner may replace it.
    address public immutable policy;

    address[] internal _managers;
    mapping(address => bool) public isManager;

    event ManagerCreated(address indexed manager, address indexed owner, uint256 indexed index, uint256 funding);

    constructor(IFWAV2 fwa, IShapes shapes, IShapePacks packs, address policy_) {
        VaultLib.checkPolicy(policy_);
        policy = policy_;
        implementation = new PackManager(fwa, shapes, packs);
    }

    /// @notice Create a manager owned by `owner` with parameters `p`, funded with `msg.value`.
    function create(address owner, VaultLib.Params calldata p) external payable returns (PackManager manager) {
        manager = PackManager(payable(LibClone.clone(address(implementation))));
        manager.initialize{value: msg.value}(owner, p, policy);
        isManager[address(manager)] = true;
        emit ManagerCreated(address(manager), owner, _managers.length, msg.value);
        _managers.push(address(manager));
    }

    function managerCount() external view returns (uint256) {
        return _managers.length;
    }

    function managerAt(uint256 index) external view returns (address) {
        return _managers[index];
    }
}
