// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

import {ForkBase} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";

contract AuditOwnerExtraction is ForkBase {
    function test_compromisedOwnerRaisesCanaryCapsImmediatelyAndCollectsPay() public {
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;

        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;
        p.maxTip = 0.05 gwei;
        p.workFee = 0.00002 ether;
        p.payMarkupBps = 0;
        p.reserve = 0.005 ether;
        p.routineCap = 0.03 ether;
        p.routineRate = 0.0008 ether;
        p.essentialCap = 0.01 ether;
        p.essentialRate = 0.0002 ether;
        vm.prank(owner);
        vault.setParams(p);
        uint256 ck = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + ck}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        // build mints and lists three packs at once.
        TestVaultOps.restock(vault, 3, UNITS, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 3);

        p = vault.getParams();
        p.minEdgeBps = 1_000; // legal value makes unlisting permissionless
        p.gasCeiling = 50 gwei;
        p.essentialCeiling = 50 gwei;
        p.maxTip = 50 gwei;
        p.workFee = 0.00005 ether;
        p.payMarkupBps = 1_000;
        p.routineCap = 0.3 ether;
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;

        p.tvlCap = type(uint128).max;
        vm.prank(owner);
        vault.setParams(p);
        (uint256 routine, uint256 essential) = vault.budget();
        assertLt(routine, 0.03 ether, "raising cap did not refill spent budget");
        assertEq(essential, 0.01 ether);
        emit log_named_uint("canary routine remaining before extraction", routine);

        uint256 beforePay = owner.balance;
        vm.prank(owner);
        uint256 paidUnlist = TestVaultOps.unlist(vault, ids, 0);
        assertEq(paidUnlist, routine, "unlist pays entire remaining routine budget");
        vm.prank(owner);
        vault.startWindDown();
        vm.prank(owner);
        uint256 paidLiquidate = vault.liquidate(40, 0);
        assertEq(paidLiquidate, essential, "liquidate pays entire essential budget");
        assertEq(owner.balance - beforePay, routine + essential);
        emit log_named_uint("owner keeper pay extracted wei", owner.balance - beforePay);
        (routine, essential) = vault.budget();
        assertEq(routine, 0);
        assertEq(essential, 0);
        vm.warp(block.timestamp + 1 days);
        (routine, essential) = vault.budget();
        assertEq(routine, 0.01 ether);
        assertEq(essential, 0.005 ether);
    }
}
