// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {PackVault} from "../src/PackVault.sol";
import {VaultLib} from "../src/VaultLib.sol";
import {PackManagerFactory} from "../src/PackManagerFactory.sol";
import {PackManager} from "../src/PackManager.sol";
import {IShapes, IShapePacks, IFWAV2} from "../src/interfaces/External.sol";

/// @notice Shared deployment and readback path for scripts, local rehearsals and fork tests.
library DeployCore {
    function deploy(IFWAV2 fwa, IShapes shapes, IShapePacks packs, address owner,
        VaultLib.Params memory p, uint256 seed, bytes32 expected) internal returns (PackVault vault)
    {
        vault = new PackVault{value: seed}(fwa, shapes, packs, owner, p, expected);
        postflight(vault, fwa, owner, p, seed);
    }

    function deployFactory(IFWAV2 fwa, IShapes shapes, IShapePacks packs)
        internal returns (PackManagerFactory factory)
    {
        factory = new PackManagerFactory(fwa, shapes, packs);
        postflightFactory(factory, fwa, shapes, packs);
    }

    function postflightFactory(PackManagerFactory factory, IFWAV2 fwa, IShapes shapes, IShapePacks packs)
        internal view
    {
        PackManager impl = factory.implementation();
        require(impl.factory() == address(factory), "postflight: implementation factory");
        require(address(impl.fwa()) == address(fwa) && address(impl.shapes()) == address(shapes)
            && address(impl.packs()) == address(packs), "postflight: implementation externals");
        require(impl.owner() == address(0), "postflight: implementation has an owner");
        require(factory.managerCount() == 0, "postflight: no managers yet");
    }

    function postflight(PackVault vault, IFWAV2 fwa, address owner, VaultLib.Params memory p, uint256 seed)
        internal view
    {
        require(address(vault.fwa()) == address(fwa), "postflight: fwa");
        require(vault.owner() == owner, "postflight: owner");
        require(keccak256(abi.encode(vault.getParams())) == keccak256(abi.encode(p)), "postflight: params");
        (uint256 r, uint256 e) = vault.budget();
        require(r == p.routineCap && e == p.essentialCap, "postflight: budgets");
        require(vault.totalShares() == vault.DEAD_SHARES(), "postflight: seed shares");
        require(address(vault).balance >= seed, "postflight: seed");
        require(!vault.windingDown() && !vault.depositsPaused() && !vault.listingPaused(), "postflight: flags");
    }
}
