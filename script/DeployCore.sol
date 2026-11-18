// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {PackVault} from "../src/PackVault.sol";
import {VaultLib} from "../src/VaultLib.sol";
import {KeeperPolicyV1} from "../src/KeeperPolicy.sol";
import {FWAExposureRegistry} from "../src/FWAExposureRegistry.sol";
import {IShapes, IShapePacks, IFWAV2} from "../src/interfaces/External.sol";

/// @notice The one deployment path: `script/Deploy.s.sol` (mainnet, rehearsals) and every fork
///         and scenario test call `deploy`, so tests exercise the exact code that deploys, and the
///         postflight runs in the simulation, the rehearsals and the real broadcast alike.
library DeployCore {
    function deploy(
        IFWAV2 fwa,
        IShapes shapes,
        IShapePacks packs,
        address owner,
        VaultLib.Params memory p,
        uint256 seed
    ) internal returns (PackVault vault, KeeperPolicyV1 policy) {
        // The keeper payment policy is its own immutable contract; the owner replaces it with
        // setPolicy (D57, D58).
        policy = new KeeperPolicyV1();
        vault = new PackVault{value: seed}(fwa, shapes, packs, owner, p, policy, FWAExposureRegistry(address(0)));
        postflight(vault, policy, fwa, owner, p, seed);
    }

    /// @notice Reads the deployed vault back and stops on any difference from what was asked for.
    function postflight(
        PackVault vault,
        KeeperPolicyV1 policy,
        IFWAV2 fwa,
        address owner,
        VaultLib.Params memory p,
        uint256 seed
    ) internal view {
        require(address(vault.fwa()) == address(fwa), "postflight: fwa");
        require(vault.owner() == owner, "postflight: owner");
        require(address(vault.keeperPolicy()) == address(policy), "postflight: policy");
        require(policy.policyVersion() == 1, "postflight: policy version");
        require(keccak256(abi.encode(vault.getParams())) == keccak256(abi.encode(p)), "postflight: params");
        (uint256 r, uint256 e) = vault.budget();
        require(r == p.routineCap && e == p.essentialCap, "postflight: budgets");
        require(vault.totalShares() == vault.DEAD_SHARES(), "postflight: seed shares");
        require(address(vault).balance >= seed, "postflight: seed");
        require(!vault.windingDown() && !vault.depositsPaused() && !vault.listingPaused(), "postflight: flags");
    }
}
