// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

import {ForkBase, IOwnable, IFwaAdmin} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {Charges} from "../../utils/Charges.sol";

contract AuditOracleGas is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function test_emptyOracleAddressRejectedBeforeWindDownExit() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;

        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;
        p.payMarkupBps = 0;
        p.reserve = 0.005 ether;
        vm.prank(owner);
        vault.setParams(p);

        uint256 charge = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + charge}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 3, UNITS, 0);
        vm.prank(keeper);
        TestVaultOps.list(vault, 3, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 3);
        address originalOracle = FWA.floorOracle();
        address wrongOracle = makeAddr("pack-vault-test-misconfigured-oracle");
        assertEq(wrongOracle.code.length, 0); assertEq(wrongOracle.balance, 0);
        vm.prank(IOwnable(address(FWA)).owner());
        vm.expectRevert(bytes4(keccak256("InvalidConfig()")));
        IFwaAdmin(address(FWA)).setAddr(64, wrongOracle);
        assertEq(FWA.floorOracle(), originalOracle, "real FWA rejects an oracle with no code");
        vm.prank(owner);
        vault.startWindDown();

        // The rejected configuration cannot prevent a subsequent wind-down.
        uint256 g = gasleft();
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        g -= gasleft();
        assertTrue(succeeded, "empty oracle configuration cannot block the exit");
        assertEq(TestVaultOps.open(vault).length, 0, "every position unlisted");
        assertLt(g, 3_000_000, "well inside one transaction");
        assertEq(FWA.floorOracle(), originalOracle);
    }

    function test_wrongOracleAbiDoesNotBlockRedemption() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;

        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;
        p.payMarkupBps = 0;
        p.reserve = 0.005 ether;
        vm.prank(owner);
        vault.setParams(p);

        uint256 depositCharge = vault.requestCharge();
        vm.prank(alice);
        vault.deposit{value: 1 ether + depositCharge}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 1, UNITS, 0);
        vm.prank(keeper);
        TestVaultOps.list(vault, 1, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 1);
        uint256 shares = vault.shareBalance(alice);
        uint256 redeemCharge = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: redeemCharge}(shares);
        toBlackout();
        checkpoint();
        assertGt(vault.lockedShares(), 0, "listed pack leaves a holder exit shortfall");
        emit log_named_uint("locked shares after first checkpoint", vault.lockedShares());
        address originalOracle = FWA.floorOracle();
        address wrongOracle = address(PACKS); // Real deployed contract with an unrelated ABI.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, wrongOracle);
        vm.prank(owner);
        vault.startWindDown();

        // The real pack contract rejects the unknown oracle call and remains configured throughout.
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        assertTrue(succeeded, "wrong oracle ABI cannot block the exit");
        assertEq(TestVaultOps.open(vault).length, 0);
        assertEq(FWA.floorOracle(), wrongOracle);
        originalOracle;
        vm.prank(keeper);
        vault.liquidate(40, 0);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "redemption filled with the wrong oracle ABI");
        uint256 beforeClaim = alice.balance;
        vm.prank(alice);
        vault.claim();
        emit log_named_uint("holder claimed wei", alice.balance - beforeClaim);
        assertGt(alice.balance - beforeClaim, 0.95 ether);
    }
}
