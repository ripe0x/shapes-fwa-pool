// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {ForkVaultInvariantTest} from "../fork/ForkVaultInvariant.t.sol";

contract AuditInvariantHarness is ForkVaultInvariantTest {
    function test_profitableHolderBreaksSignedNetInFormula() public {
        handler.deposit(1, 3 ether);
        handler.checkpoint();
        handler.requestRedeem(1, 100);
        handler.donate(0.5 ether);
        handler.checkpoint();
        handler.claim(1);
        emit log_named_uint("bob balance after donated gain", bob.balance);
        assertGt(bob.balance, 50 ether, "holder receives donated gain");
        invariant_reservesCovered();
        invariant_claimsWithinReserves();
        invariant_sharesConserved();
        vm.expectRevert();
        this.invariant_valueConserved();
    }
}
