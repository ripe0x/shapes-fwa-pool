// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Script} from "forge-std/Script.sol";
import {PackVault} from "../src/PackVault.sol";
import {VaultLib} from "../src/VaultLib.sol";
import {DeployCore} from "./DeployCore.sol";
import {KeeperPolicyV1} from "../src/KeeperPolicy.sol";
import {PackManagerFactory} from "../src/PackManagerFactory.sol";
import {console2} from "forge-std/console2.sol";
import {IShapes, IShapePacks, IFWAV2} from "../src/interfaces/External.sol";

/// @notice Mainnet and rehearsal entry to the one deployment path (DeployCore, also used by every
///         fork and scenario test). Every value comes from a JSON values file (DEPLOY_VALUES);
///         the signer comes from the forge command line (keystore account, or an unlocked
///         local node for rehearsal). Never from this file.
contract Deploy is Script {
    /// @dev Parse a value and refuse one that does not fit its field (no silent truncation).
    function fit(string memory v, string memory key, uint256 max) internal pure returns (uint256 x) {
        x = vm.parseJsonUint(v, key);
        require(x <= max, string.concat("value does not fit: ", key));
    }

    function run() external returns (PackVault vault) {
        string memory v = vm.readFile(vm.envString("DEPLOY_VALUES"));
        VaultLib.Params memory p;
        p.minEdgeBps = uint16(fit(v, ".minEdgeBps", type(uint16).max));
        p.bufferBps = uint16(fit(v, ".bufferBps", type(uint16).max));
        p.distributionBps = uint16(fit(v, ".distributionBps", type(uint16).max));
        p.payMarkupBps = uint16(fit(v, ".payMarkupBps", type(uint16).max));
        p.keeperShareBps = uint16(fit(v, ".keeperShareBps", type(uint16).max));
        p.allocatedBoundBps = uint16(fit(v, ".allocatedBoundBps", type(uint16).max));
        p.packUnitsMask = uint64(fit(v, ".packUnitsMask", type(uint64).max));
        p.gasCeiling = uint64(fit(v, ".gasCeilingWei", type(uint64).max));
        p.essentialCeiling = uint64(fit(v, ".essentialCeilingWei", type(uint64).max));
        p.maxTip = uint64(fit(v, ".maxTipWei", type(uint64).max));
        p.workFee = uint64(fit(v, ".workFeeWei", type(uint64).max));
        p.reserve = uint128(fit(v, ".reserveWei", type(uint128).max));
        p.tvlCap = uint128(fit(v, ".tvlCapWei", type(uint128).max));
        p.routineCap = uint64(fit(v, ".routineCapWei", type(uint64).max));
        p.routineRate = uint64(fit(v, ".routineRatePerDayWei", type(uint64).max));
        p.essentialCap = uint64(fit(v, ".essentialCapWei", type(uint64).max));
        p.essentialRate = uint64(fit(v, ".essentialRatePerDayWei", type(uint64).max));
        p.keepAdvantage = uint64(fit(v, ".keepAdvantageWei", type(uint64).max));
        p.purchaserGasPrice = uint64(fit(v, ".purchaserGasPriceWei", type(uint64).max));
        p.purchaserRedeemPack = uint64(fit(v, ".purchaserRedeemPackGas", type(uint64).max));
        p.purchaserRedeemShape = uint64(fit(v, ".purchaserRedeemShapeGas", type(uint64).max));
        p.minDeposit = uint64(fit(v, ".minDepositWei", type(uint64).max));
        p.minDistribution = uint64(fit(v, ".minDistributionWei", type(uint64).max));
        address owner_ = vm.parseJsonAddress(v, ".owner");
        require(uint160(owner_) > 0xffff, "owner must be a real account, not a placeholder or precompile");
        vm.startBroadcast();
        KeeperPolicyV1 policy;
        (vault, policy) = DeployCore.deploy(
            IFWAV2(vm.parseJsonAddress(v, ".fwa")),
            IShapes(vm.parseJsonAddress(v, ".shapes")),
            IShapePacks(vm.parseJsonAddress(v, ".packs")),
            owner_,
            p,
            vm.parseJsonUint(v, ".seedWei")
        );
        // Personal managers run the same strategy and share the keeper policy as their default.
        PackManagerFactory factory = DeployCore.deployFactory(vault.fwa(), vault.shapes(), vault.packs(), policy);
        vm.stopBroadcast();
        console2.log("PackVault", address(vault));
        console2.log("PackManagerFactory", address(factory));
        console2.log("PackManager implementation", address(factory.implementation()));
        console2.log("KeeperPolicy", address(vault.keeperPolicy()));
        console2.log("postflight passed");
    }
}
