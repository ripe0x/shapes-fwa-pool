// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {PackVault} from "../../src/PackVault.sol";

/// @notice Request charges (D56), from the vault's own views. Compute before `vm.prank`: these are
///         external calls and would consume the prank.
library Charges {

    /// @dev ETH to send so that `escrow` is escrowed (deployment charge included): the
    ///      checkpoint charge goes to the pool on top.
    function grossFor(PackVault v, uint256 escrow) internal view returns (uint256) {
        return v.requestCharge() + escrow;
    }

    /// @dev Exact charge for redeeming `shares` now.
    function redeemCharge(PackVault v, uint256 shares) internal view returns (uint256) {
        uint256 value = shares * v.lastNav() / v.totalShares();
        return v.requestCharge() + value * v.unwindCharge() / v.positionValue();
    }
}
