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

        p.reserve = 0.005 ether;
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected0);

        uint256 charge = vault.requestCharge();
        bytes32 _expected1 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: 1 ether + charge}(_expected1);
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 3, UNITS, 0); // build lists all three at once
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
        bytes32 expectedUnlist = vault.configurationHash();
        bytes memory unlistCall = abi.encodeCall(vault.unlist, (ids, 0, expectedUnlist));
        uint256 g = gasleft();
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(unlistCall);
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

        p.reserve = 0.005 ether;
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected2);

        uint256 depositCharge = vault.requestCharge();
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: 1 ether + depositCharge}(_expected3);
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 1, UNITS, 0); // build lists it at once
        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 1);
        uint256 shares = vault.shareBalance(alice);
        uint256 redeemCharge = Charges.redeemCharge(vault, shares);
        bytes32 _expected4 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.requestRedeem{value: redeemCharge}(shares, _expected4);
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
        bytes32 expectedUnlist = vault.configurationHash();
        bytes memory unlistCall = abi.encodeCall(vault.unlist, (ids, 0, expectedUnlist));
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(unlistCall);
        assertTrue(succeeded, "wrong oracle ABI cannot block the exit");
        assertEq(TestVaultOps.open(vault).length, 0);
        assertEq(FWA.floorOracle(), wrongOracle);
        originalOracle;
        bytes32 _expected5 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vault.liquidate(40, 0, _expected5);
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
