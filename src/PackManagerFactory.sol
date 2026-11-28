// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {LibClone} from "solady/utils/LibClone.sol";
import {PackManager} from "./PackManager.sol";
import {VaultLib} from "./VaultLib.sol";
import {IShapes, IShapePacks, IFWAV2} from "./interfaces/External.sol";

/// @title PackManagerFactory
/// @notice Permissionless creation and discovery of personal PackManagers. Each manager is an
///         ERC-1167 clone of the current implementation, initialized in the same transaction
///         with its owner, bounded parameters, and funded with any ETH sent. The admin may change
///         the implementation new clones copy; existing clones never change. The factory charges
///         nothing, holds no ETH after a call and has no authority over a manager once created.
contract PackManagerFactory {
    /// @notice The code new managers clone. Changing it affects only managers created afterwards:
    ///         each clone is a fixed EIP-1167 proxy of the implementation it was created with. It is
    ///         part of `configHashFor`, so a creation reviewed against another implementation is refused.
    /// @dev Trust: the admin chooses the code future managers run. A replacement is constructed with
    ///      this factory's address and must keep `factory()`, `initialize` and `shapes()`, which this
    ///      factory calls. The `factory()` check catches a mistaken address, not a hostile contract.
    address public implementation;
    address public admin;
    address public pendingAdmin;

    error ConfigurationChanged();
    error Unauthorized();
    error InvalidImplementation();

    address[] internal _managers;
    mapping(address => bool) public isManager;

    event ManagerCreated(address indexed manager, address indexed owner, uint256 indexed index, uint256 funding);
    event ImplementationChanged(address indexed previousImplementation, address indexed newImplementation);
    event AdminTransferStarted(address indexed admin, address indexed pendingAdmin);
    event AdminTransferred(address indexed previousAdmin, address indexed newAdmin);

    /// @dev The deployer is the first admin.
    constructor(IFWAV2 fwa, IShapes shapes, IShapePacks packs) {
        implementation = address(new PackManager(fwa, shapes, packs, address(this)));
        admin = msg.sender;
        emit ImplementationChanged(address(0), implementation);
        emit AdminTransferred(address(0), msg.sender);
    }

    /// @notice Clone `next` for managers created after this call. Existing managers keep their code.
    function setImplementation(address next) external {
        if (msg.sender != admin) revert Unauthorized();
        if (next.code.length == 0 || PackManager(payable(next)).factory() != address(this)) revert InvalidImplementation();
        emit ImplementationChanged(implementation, next);
        implementation = next;
    }

    function transferAdmin(address next) external {
        if (msg.sender != admin) revert Unauthorized();
        pendingAdmin = next;
        emit AdminTransferStarted(msg.sender, next);
    }

    function acceptAdmin() external {
        if (msg.sender != pendingAdmin || msg.sender == address(0)) revert Unauthorized();
        emit AdminTransferred(admin, msg.sender);
        admin = msg.sender;
        pendingAdmin = address(0);
    }

    /// @notice Create a manager owned by `owner` with parameters `p` and the owner's exact pack
    ///         mix (`PackAccount.design`, nonzero), funded with `msg.value`.
    function create(address owner, VaultLib.Params calldata p, uint256 design, bytes32 expected) external payable returns (PackManager manager) {
        if (expected != configHashFor(p)) revert ConfigurationChanged();
        manager = PackManager(payable(LibClone.clone(implementation)));
        manager.initialize{value: msg.value}(owner, p, design);
        isManager[address(manager)] = true;
        emit ManagerCreated(address(manager), owner, _managers.length, msg.value);
        _managers.push(address(manager));
    }

    function configHashFor(VaultLib.Params calldata p) public view returns (bytes32) {
        return keccak256(abi.encode(p, PackManager(payable(implementation)).shapes().mintFee(), false, false, implementation));
    }

    function preview(VaultLib.Params calldata p) external view returns (uint256 units, uint256 principal,
        uint256 backing, uint256 mintCost, uint256 openingCash, bytes32 expectedConfigHash)
    {
        (units, principal, backing, mintCost, openingCash,) = VaultLib.preview(p, PackManager(payable(implementation)).shapes().mintFee());
        expectedConfigHash = configHashFor(p);
    }

    function managerCount() external view returns (uint256) {
        return _managers.length;
    }

    function managerAt(uint256 index) external view returns (address) {
        return _managers[index];
    }
}
