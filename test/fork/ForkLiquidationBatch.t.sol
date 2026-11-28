// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

/// @notice Exit work is unpaid, and a wind-down still completes: the LIFO liquidation batching
///         respects the sixty-unit work bound (legacy and mixed recipes) and every call pays nothing.
contract ForkLiquidationBatchTest is ForkBase {
    receive() external payable {}

    function _exercise(bool mixed) internal {
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = (uint64(1) << 30) | (uint64(1) << 6);
        p.reserve = 0;
        vm.deal(address(this), 10 ether);
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 5 ether,
            keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        for (uint256 i; i < 4; ++i) {
            TestVaultOps.restock(vault, 1, 30, 0);
            if (mixed) TestVaultOps.restock(vault, 1, 6, 0);
        }
        uint256[] memory ids = TestVaultOps.open(vault);
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        bytes32 expected = vault.configurationHash();
        vm.prank(owner);
        vault.setParams(p, expected);
        vm.warp(vm.getBlockTimestamp() + 13 hours);
        vm.prank(owner);
        vault.startWindDown();
        uint256 paid = vault.unlist(ids, 0, vault.configurationHash());
        uint256 calls;
        while (vault.idlePackCount() != 0) {
            paid += vault.liquidate(16, 0, vault.configurationHash());
            ++calls;
        }
        assertEq(calls, mixed ? 4 : 2, "actual LIFO calls obey sixty-unit work bound");
        assertEq(paid, 0, "every bounded exit call is unpaid");
        assertEq(vault.openListingCount() + vault.idlePackCount(), 0);
    }

    function test_largeLegacyRecipeUsesEveryRequiredLiquidationCall() public { _exercise(false); }
    function test_mixedLifoRecipesCannotUseGroupedBatchUnderestimate() public { _exercise(true); }
}
