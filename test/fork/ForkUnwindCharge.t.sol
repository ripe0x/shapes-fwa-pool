// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

/// @notice Actual legacy recipes retain their liquidation batch costs after a recipe change.
contract ForkUnwindChargeTest is ForkBase {
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
        uint256 capital;
        for (uint256 i; i < ids.length; ++i) {
            VaultLib.Position memory position = vault.position(ids[i]);
            capital += position.value + position.backing;
        }
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        bytes32 expected = vault.configurationHash();
        vm.prank(owner);
        vault.setParams(p, expected);
        uint256 perReference = vault.unwindCharge();
        uint256 referenceCapital = vault.positionValue();
        assertEq(referenceCapital, 0.24 ether);
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
        assertEq(paid, mixed ? 0.001172 ether : 0.000634 ether,
            "absolute verified keeper payments include each real base exactly once");
        uint256 required = (paid * referenceCapital + capital - 1) / capital;
        assertEq(perReference, required, "normalized charge covers all actual bounded calls");
        assertEq(vault.openListingCount() + vault.idlePackCount(), 0);
    }

    function test_largeLegacyRecipeChargesEveryRequiredLiquidationBase() public { _exercise(false); }
    function test_mixedLifoRecipesCannotUseGroupedBatchUnderestimate() public { _exercise(true); }
}
