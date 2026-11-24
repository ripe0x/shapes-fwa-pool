// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Script} from "forge-std/Script.sol";
import {PackVault} from "../src/PackVault.sol";
import {VaultLib} from "../src/VaultLib.sol";
import {DeployCore} from "./DeployCore.sol";
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
        p.upliftBoundBps = uint16(fit(v, ".upliftBoundBps", type(uint16).max));
        p.packUnitsMask = uint64(fit(v, ".packUnitsMask", type(uint64).max));
        p.gasCeiling = uint64(fit(v, ".gasCeilingWei", type(uint64).max));
        p.essentialCeiling = uint64(fit(v, ".essentialCeilingWei", type(uint64).max));
        p.maxTip = uint64(fit(v, ".maxTipWei", type(uint64).max));
        p.workFee = uint64(fit(v, ".workFeeWei", type(uint64).max));
        p.routineCap = uint64(fit(v, ".routineCapWei", type(uint64).max));
        p.routineRate = uint64(fit(v, ".routineRatePerDayWei", type(uint64).max));
        p.essentialCap = uint64(fit(v, ".essentialCapWei", type(uint64).max));
        p.essentialRate = uint64(fit(v, ".essentialRatePerDayWei", type(uint64).max));
        p.reserve = uint128(fit(v, ".reserveWei", type(uint128).max));
        p.tvlCap = uint128(fit(v, ".tvlCapWei", type(uint128).max));
        p.backingRatioBps = uint32(fit(v, ".backingRatioBps", type(uint32).max));
        p.renewalMode = VaultLib.RenewalMode(fit(v, ".renewalMode", 1));
        p.renewalFloatCount = uint16(fit(v, ".renewalFloatCount", type(uint16).max));
        p.acceptedMintFee = uint64(fit(v, ".acceptedMintFeeWei", type(uint64).max));
        p.minDeposit = uint64(fit(v, ".minDepositWei", type(uint64).max));
        p.minDistribution = uint64(fit(v, ".minDistributionWei", type(uint64).max));
        p.gasSchedule.checkpoint = uint32(fit(v, ".gasSchedule.checkpoint", type(uint32).max));
        p.gasSchedule.allocationEntry = uint32(fit(v, ".gasSchedule.allocationEntry", type(uint32).max));
        p.gasSchedule.allocationRead = uint32(fit(v, ".gasSchedule.allocationRead", type(uint32).max));
        p.gasSchedule.build = uint32(fit(v, ".gasSchedule.build", type(uint32).max));
        p.gasSchedule.buildPack = uint32(fit(v, ".gasSchedule.buildPack", type(uint32).max));
        p.gasSchedule.buildShape = uint32(fit(v, ".gasSchedule.buildShape", type(uint32).max));
        p.gasSchedule.list = uint32(fit(v, ".gasSchedule.list", type(uint32).max));
        p.gasSchedule.listed = uint32(fit(v, ".gasSchedule.listed", type(uint32).max));
        p.gasSchedule.sync = uint32(fit(v, ".gasSchedule.sync", type(uint32).max));
        p.gasSchedule.requiredTail = uint32(fit(v, ".gasSchedule.requiredTail", type(uint32).max));
        p.gasSchedule.distributionProof = uint32(fit(v, ".gasSchedule.distributionProof", type(uint32).max));
        p.gasSchedule.journal = uint32(fit(v, ".gasSchedule.journal", type(uint32).max));
        p.gasSchedule.scan = uint32(fit(v, ".gasSchedule.scan", type(uint32).max));
        p.gasSchedule.selected = uint32(fit(v, ".gasSchedule.selected", type(uint32).max));
        p.gasSchedule.synced = uint32(fit(v, ".gasSchedule.synced", type(uint32).max));
        p.gasSchedule.pruned = uint32(fit(v, ".gasSchedule.pruned", type(uint32).max));
        p.gasSchedule.unlist = uint32(fit(v, ".gasSchedule.unlist", type(uint32).max));
        p.gasSchedule.unlisted = uint32(fit(v, ".gasSchedule.unlisted", type(uint32).max));
        p.gasSchedule.liquidate = uint32(fit(v, ".gasSchedule.liquidate", type(uint32).max));
        p.gasSchedule.liquidatePack = uint32(fit(v, ".gasSchedule.liquidatePack", type(uint32).max));
        p.gasSchedule.redeemShape = uint32(fit(v, ".gasSchedule.redeemShape", type(uint32).max));
        p.gasSchedule.recoveryBase = uint32(fit(v, ".gasSchedule.recoveryBase", type(uint32).max));
        p.gasSchedule.recoveryShape = uint32(fit(v, ".gasSchedule.recoveryShape", type(uint32).max));
        p.gasSchedule.recoveryUnseal = uint32(fit(v, ".gasSchedule.recoveryUnseal", type(uint32).max));
        p.gasSchedule.harvest = uint32(fit(v, ".gasSchedule.harvest", type(uint32).max));
        p.gasSchedule.harvested = uint32(fit(v, ".gasSchedule.harvested", type(uint32).max));
        p.gasSchedule.credit = uint32(fit(v, ".gasSchedule.credit", type(uint32).max));
        p.gasSchedule.fund = uint32(fit(v, ".gasSchedule.fund", type(uint32).max));
        address owner_ = vm.parseJsonAddress(v, ".owner");
        require(uint160(owner_) > 0xffff, "owner must be a real account, not a placeholder or precompile");
        vm.startBroadcast();
        vault = DeployCore.deploy(
            IFWAV2(vm.parseJsonAddress(v, ".fwa")),
            IShapes(vm.parseJsonAddress(v, ".shapes")),
            IShapePacks(vm.parseJsonAddress(v, ".packs")),
            owner_,
            p,
            vm.parseJsonUint(v, ".seedWei"),
            keccak256(abi.encode(p, vm.parseJsonUint(v, ".expectedMintFeeWei"), false, false))
        );
        PackManagerFactory factory = DeployCore.deployFactory(vault.fwa(), vault.shapes(), vault.packs());
        vm.stopBroadcast();
        console2.log("PackVault", address(vault));
        console2.log("PackManagerFactory", address(factory));
        console2.log("PackManager implementation", address(factory.implementation()));
        console2.log("postflight passed");
    }
}
