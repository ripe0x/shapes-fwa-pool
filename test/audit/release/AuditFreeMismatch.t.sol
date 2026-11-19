// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";
import {ForkBase} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {Charges} from "../../utils/Charges.sol";

contract AuditFreeMismatch is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    function test_cancelCyclesRetainNothing() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;

        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;
        p.payMarkupBps = 0;
        p.reserve = 0.005 ether;
        vm.prank(owner);
        vault.setParams(p);
        uint256 ck = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + ck}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 1, 3, 0);
        vm.prank(keeper);
        TestVaultOps.list(vault, 1, 0);
        assertEq(TestVaultOps.open(vault).length, 1);
        // Repaired (E4 root): a cancel refunds its checkpoint charge, so cycles retain nothing
        // and no reserved ETH builds up for the keeper to misread. The keeper also subtracts the
        // pool now (keeper/test_policy.py replays the audit's balances).
        uint256 pool0 = vault.processingPool();
        vm.deal(bob, 1 ether);
        uint256 b0 = bob.balance;
        for (uint256 i; i < 20; ++i) {
            uint256 charge = vault.requestCharge();
            vm.prank(bob);
            vault.deposit{value: 0.01 ether + charge}();
            vm.prank(bob);
            vault.cancelDeposit();
        }
        assertEq(vault.processingPool(), pool0, "nothing retained");
        assertEq(bob.balance, b0, "every wei back");
        assertEq(vault.pendingDepositTotal(), 0);
    }
}
