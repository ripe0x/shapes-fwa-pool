// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

/// @dev Historical regression calibration. New calibration checks read the account GasSchedule.
library GasQuotes {
    uint256 internal constant Q_PURCHASER_REDEEM_PACK = 100_000;
    uint256 internal constant Q_PURCHASER_REDEEM_SHAPE = 30_000;
    uint256 internal constant Q_CHECKPOINT = 500_000;
    uint256 internal constant Q_ALLOCATION_ENTRY = 6_000;
    uint256 internal constant Q_ALLOCATION_READ = 30_000;
    uint256 internal constant Q_BUILD = 360_000;
    uint256 internal constant Q_BUILD_PACK = 300_000;
    uint256 internal constant Q_BUILD_SHAPE = 130_000;
    uint256 internal constant Q_LIST = 280_000;
    uint256 internal constant Q_LISTED = 825_000;
    uint256 internal constant Q_SYNC = 125_000;
    uint256 internal constant Q_REQUIRED_TAIL = 120_000;
    uint256 internal constant Q_DISTRIBUTION_PROOF = 80_000;
    uint256 internal constant Q_JOURNAL = 22_000;
    uint256 internal constant Q_SCAN = 30_000;
    uint256 internal constant Q_SELECTED = 180_000;
    uint256 internal constant Q_SYNCED = 120_000;
    uint256 internal constant Q_PRUNED = 45_000;
    uint256 internal constant Q_POSITION_SYNC = Q_JOURNAL + Q_SELECTED + Q_SYNCED + Q_PRUNED;
    uint256 internal constant Q_UNLIST = 340_000;
    uint256 internal constant Q_UNLISTED = 285_000;
    uint256 internal constant Q_LIQUIDATE = 75_000;
    uint256 internal constant Q_LIQ_PACK = 80_000;
    uint256 internal constant Q_REDEEM_SHAPE = 35_000;
    uint256 internal constant Q_RECOVERY_BASE = 100_000;
    uint256 internal constant Q_RECOVERY_SHAPE = 35_000;
    uint256 internal constant Q_RECOVERY_UNSEAL = 70_000;
    uint256 internal constant Q_HARVESTED = 80_000;
    uint256 internal constant Q_CREDIT = 40_000;
    uint256 internal constant Q_FUND = 40_000;
    uint256 internal constant CYCLE_GAS = Q_POSITION_SYNC + Q_LISTED + Q_HARVESTED;
    function buildGas(uint256 n) internal pure returns(uint256) { return Q_BUILD_PACK + n * Q_BUILD_SHAPE; }
}
