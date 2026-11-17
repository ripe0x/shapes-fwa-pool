// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Script} from "forge-std/Script.sol";
import {PackVault} from "../src/PackVault.sol";
import {VaultLib} from "../src/VaultLib.sol";
import {KeeperPolicyV1} from "../src/KeeperPolicy.sol";
import {IShapes, IShapePacks, IFWAV2} from "../src/interfaces/External.sol";

/// @notice The one deployment path. Every value comes from a JSON values file (DEPLOY_VALUES);
///         the signer comes from the forge command line (keystore account, or an unlocked
///         local node for rehearsal). Never from this file.
contract Deploy is Script {
    function run() external returns (PackVault vault) {
        string memory v = vm.readFile(vm.envString("DEPLOY_VALUES"));
        VaultLib.Params memory p;
        p.minEdgeBps = uint16(vm.parseJsonUint(v, ".minEdgeBps"));
        p.bufferBps = uint16(vm.parseJsonUint(v, ".bufferBps"));
        p.distributionBps = uint16(vm.parseJsonUint(v, ".distributionBps"));
        p.payMarkupBps = uint16(vm.parseJsonUint(v, ".payMarkupBps"));
        p.keeperShareBps = uint16(vm.parseJsonUint(v, ".keeperShareBps"));
        p.allocatedBoundBps = uint16(vm.parseJsonUint(v, ".allocatedBoundBps"));
        p.packUnitsMask = uint64(vm.parseJsonUint(v, ".packUnitsMask"));
        p.gasCeiling = uint64(vm.parseJsonUint(v, ".gasCeilingWei"));
        p.maxTip = uint64(vm.parseJsonUint(v, ".maxTipWei"));
        p.workFee = uint64(vm.parseJsonUint(v, ".workFeeWei"));
        p.maxPositions = uint96(vm.parseJsonUint(v, ".maxPositions"));
        p.reserve = uint128(vm.parseJsonUint(v, ".reserveWei"));
        p.tvlCap = uint128(vm.parseJsonUint(v, ".tvlCapWei"));
        p.routineCap = uint64(vm.parseJsonUint(v, ".routineCapWei"));
        p.routineRate = uint64(vm.parseJsonUint(v, ".routineRatePerDayWei"));
        p.essentialCap = uint64(vm.parseJsonUint(v, ".essentialCapWei"));
        p.essentialRate = uint64(vm.parseJsonUint(v, ".essentialRatePerDayWei"));
        vm.startBroadcast();
        // The keeper payment policy is its own immutable contract; the admin replaces it with
        // setPolicy (D57, D58).
        KeeperPolicyV1 policy = new KeeperPolicyV1();
        vault = new PackVault{value: vm.parseJsonUint(v, ".seedWei")}(
            IFWAV2(vm.parseJsonAddress(v, ".fwa")),
            IShapes(vm.parseJsonAddress(v, ".shapes")),
            IShapePacks(vm.parseJsonAddress(v, ".packs")),
            vm.parseJsonAddress(v, ".guardian"),
            vm.parseJsonAddress(v, ".admin"),
            p,
            policy
        );
        vm.stopBroadcast();
    }
}
