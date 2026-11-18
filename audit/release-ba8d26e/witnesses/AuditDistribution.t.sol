// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "../fork/ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";

contract AuditDistribution is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function test_distributionDueWithoutFlowsNeedsKeeperCheckpoint() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
        p.gasCeiling = 0.5 gwei;
        p.payMarkupBps = 0;
        p.distributionBps = 5_000;
        vm.prank(owner);
        vault.setParams(p);

        uint256 depositCharge = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + depositCharge}();
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
        uint256 pay = vault.checkpoint(0);
        uint256 reserve = vault.distributionReserve();
        assertGe(reserve, 0.019 ether, "distribution was due and funded");
        assertLe(reserve, 0.021 ether);
        assertGt(pay, 0, "checkpoint was paid work");
        emit log_named_uint("distribution reserve wei", reserve);
        emit log_named_uint("checkpoint pay wei", pay);
        assertEq(address(vault).balance, before - pay);
    }
}
