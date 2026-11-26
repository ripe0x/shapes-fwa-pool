// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {LibClone} from "solady/utils/LibClone.sol";
import {PackManager} from "./PackManager.sol";
import {VaultLib} from "./VaultLib.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @title PackManagerFactory
/// @notice Permissionless creation and discovery of personal PackManagers. Each manager is an
///         ERC-1167 clone of one immutable implementation, initialized in the same transaction
///         with its owner, bounded parameters, and funded with any
///         ETH sent. The factory has no owner, charges nothing, holds no ETH after a call and has
///         no authority over a manager once created.
contract PackManagerFactory {
    PackManager public immutable implementation;
    error ConfigurationChanged();

    address[] internal _managers;
    mapping(address => bool) public isManager;

    event ManagerCreated(address indexed manager, address indexed owner, uint256 indexed index, uint256 funding);

    constructor(IFWAV2 fwa, IShapes shapes, IShapePacks packs) {
        implementation = new PackManager(fwa, shapes, packs);
    }

    /// @notice Create a manager owned by `owner` with parameters `p`, funded with `msg.value`.
    function create(address owner, VaultLib.Params calldata p, bytes32 expected) external payable returns (PackManager manager) {
        return _create(owner, p, 0, expected);
    }

    /// @notice As `create`, with the owner's pack mix (`PackAccount.design`).
    function create(address owner, VaultLib.Params calldata p, uint256 design, bytes32 expected) external payable returns (PackManager manager) {
        return _create(owner, p, design, expected);
    }

    function _create(address owner, VaultLib.Params calldata p, uint256 design, bytes32 expected) private returns (PackManager manager) {
        if (expected != configHashFor(p)) revert ConfigurationChanged();
        manager = PackManager(payable(LibClone.clone(address(implementation))));
        manager.initialize{value: msg.value}(owner, p, design);
        isManager[address(manager)] = true;
        emit ManagerCreated(address(manager), owner, _managers.length, msg.value);
        _managers.push(address(manager));
    }

    function configHashFor(VaultLib.Params calldata p) public view returns (bytes32) {
        return keccak256(abi.encode(p, implementation.shapes().mintFee(), false, false));
    }

    function preview(VaultLib.Params calldata p) external view returns (uint256 units, uint256 principal,
        uint256 backing, uint256 mintCost, uint256 openingCash, bytes32 expectedConfigHash)
    {
        return VaultLib.preview(p, implementation.shapes().mintFee());
    }

    function managerCount() external view returns (uint256) {
        return _managers.length;
    }

    function managerAt(uint256 index) external view returns (address) {
        return _managers[index];
    }
}
