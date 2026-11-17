// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @notice Keeper payment policy: proposes what verified work pays. PackVault calls it with a
///         bounded-gas staticcall, after the work, with facts the vault established itself; the
///         vault then pays at most its own envelope, free ETH and budget. A policy holds nothing,
///         moves nothing and cannot decide whether work happened. Replace it by deploying a new
///         contract and activating its address through the vault's admin delay (D57).
interface IKeeperPolicy {
    /// @notice Nonzero; the vault checks it before accepting a policy address.
    function policyVersion() external view returns (uint256);

    /// @param op          PackVault.OP_* (1 restock, 2 list, 3 sync, 4 activate, 5 unlist,
    ///                    6 liquidate, 7 harvest, 8 checkpoint).
    /// @param units       completed units of work the vault counted (packs built, positions
    ///                    listed, resolved, activated or unlisted, items liquidated, 1 checkpoint).
    /// @param gasAllowance the vault's calibrated quoted gas for this work (base + per unit).
    /// @param essential   redemption or wind-down work.
    /// @param gasCeiling  the vault's gas ceiling, wei per gas.
    /// @param maxTip      the vault's tip allowance over basefee, wei per gas.
    /// @param workFee     the vault's flat fee per unit, wei.
    /// @return payment    proposed wei; the vault caps it.
    function quote(
        uint256 op,
        uint256 units,
        uint256 gasAllowance,
        bool essential,
        uint256 gasCeiling,
        uint256 maxTip,
        uint256 workFee
    ) external view returns (uint256 payment);
}

/// @notice V1: the gas allowance at basefee + maxTip, capped at the ceiling, plus the flat work fee
///         per completed unit. No premium: the work fee is the keeper's margin.
contract KeeperPolicyV1 is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) {
        return 1;
    }

    function quote(uint256, uint256 units, uint256 gasAllowance, bool, uint256 gasCeiling, uint256 maxTip, uint256 workFee)
        external
        view
        returns (uint256)
    {
        uint256 price = block.basefee + maxTip;
        if (price > gasCeiling) price = gasCeiling;
        return gasAllowance * price + units * workFee;
    }
}
