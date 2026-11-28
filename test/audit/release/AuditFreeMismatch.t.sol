// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {RefundClaims} from "../../utils/RefundClaims.sol";

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

        p.reserve = 0.005 ether;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected0);
        uint256 ck = vault.requestCharge();
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: 1 ether + ck}(_expected1);
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        // build mints and lists one pack at once.
        TestVaultOps.restock(vault, 1, UNITS, 0);
        assertEq(TestVaultOps.open(vault).length, 1);
        // Repaired (E4 root): a cancel refunds its checkpoint charge, so cycles retain nothing
        // and no reserved ETH builds up for the keeper to misread. The keeper also subtracts the
        // pool now (keeper/test_policy.py replays the audit's balances).
        uint256 pool0 = vault.processingPool();
        vm.deal(bob, 1 ether);
        uint256 b0 = bob.balance;
        for (uint256 i; i < 20; ++i) {
            uint256 charge = vault.requestCharge();
            bytes32 _expected2 = TestVaultOps.configurationHash(vault);
            vm.prank(bob);
            vault.deposit{value: 0.01 ether + charge}(_expected2);
            vm.prank(bob);
            vault.cancelDeposit();
        RefundClaims.claim(vault, bob);
        }
        assertEq(vault.processingPool(), pool0, "nothing retained");
        assertEq(bob.balance, b0, "every wei back");
        assertEq(vault.pendingDepositTotal(), 0);
    }
}
