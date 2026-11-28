// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

import {ForkBase} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";

contract AuditDistribution is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function test_distributionDueWithoutFlowsNeedsKeeperCheckpoint() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;

        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;

        p.distributionBps = 5_000;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected0);

        uint256 depositCharge = vault.requestCharge();
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: 1 ether + depositCharge}(_expected1);
        toBlackout();
        checkpoint();
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.lockedShares(), 0);
        assertEq(vault.distributionReserve(), 0);
        toOpen();
        vm.prank(bob);
        (bool ok,) = address(vault).call{value: 0.04 ether}("");
        assertTrue(ok);
        toBlackout();
        assertEq(vault.pendingDepositTotal(), 0, "no holder deposits pending");
        assertEq(vault.lockedShares(), 0, "no holder redemptions pending");
        assertEq(vault.distributionReserve(), 0);
        uint256 before = address(vault).balance;
        vm.prank(keeper);
        uint256 pay = TestVaultOps.checkpoint(vault, 0);
        uint256 reserve = vault.distributionReserve();
        assertGe(reserve, 0.019 ether, "distribution was due and funded");
        assertLe(reserve, 0.021 ether);
        assertGt(pay, 0, "checkpoint was paid work");
        emit log_named_uint("distribution reserve wei", reserve);
        emit log_named_uint("checkpoint pay wei", pay);
        assertEq(address(vault).balance, before - pay);
    }
}
