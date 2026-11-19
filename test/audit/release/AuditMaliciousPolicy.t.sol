// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

import {ForkBase} from "../../fork/ForkBase.sol";
import {IKeeperPolicy} from "../../../src/KeeperPolicy.sol";
import {PackVault} from "../../../src/PackVault.sol";

contract GasPriceSwitchPolicy is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) { return 1; }
    function quote(uint256, uint256, uint256, bool, uint256, uint256, uint256)
        external view returns (uint256) {
        return tx.gasprice == 0 ? type(uint256).max : 0;
    }
}

contract AuditMaliciousPolicy is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function test_policyQuotesForSimulationThenZeroesPaidTransaction() public {
        this.assertGasContext();
        GasPriceSwitchPolicy hostile = new GasPriceSwitchPolicy();
        vm.prank(owner);
        vault.setPolicy(address(hostile));
        uint256 depositCharge = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + depositCharge}();
        toBlackout();
        uint256 snap = vm.snapshotState();

        // eth_call and eth_estimateGas omit a fee field in keeper.py and see tx.gasprice = 0.
        vm.txGasPrice(0);
        vm.prank(keeper);
        uint256 simulated = TestVaultOps.checkpoint(vault, 0);
        assertEq(simulated, depositCharge);
        vm.revertToState(snap);

        // The real keeper transaction has a nonzero gas price. The exact same work reverts at
        // the keeper's 80% minPay, leaving the deposit unpriced and the keeper's gas unreimbursed.
        vm.txGasPrice(0.2 gwei);
        this.assertGasContext();
        uint256 planned23 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Payment.selector);
        vault.checkpoint(planned23, simulated * 8 / 10);
        assertEq(vault.pendingDepositTotal(), 1 ether);
        assertEq(vault.epoch(), 0);

        // Anyone may still do the work with minPay zero. A hostile policy cannot trap holders.
        vm.prank(keeper);
        uint256 actual = TestVaultOps.checkpoint(vault, 0);
        assertEq(actual, 0);
        assertEq(vault.pendingDepositTotal(), 0);
    }
}
