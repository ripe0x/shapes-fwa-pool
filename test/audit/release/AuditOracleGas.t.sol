// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, IFwaAdmin} from "../../fork/ForkBase.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {Charges} from "../../utils/Charges.sol";

contract GasBurningOracle {
    fallback() external {
        assembly { for {} 1 {} {} }
    }
}

contract MalformedOracle {
    fallback() external {
        assembly {
            mstore(0x00, 1)
            mstore(0x20, 2)
            mstore(0x40, not(0)) // invalid uint48 encoding
            mstore(0x60, 1)
            return(0x00, 0x80)
        }
    }
}

contract AuditOracleGas is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function test_gasBurningOracleDoesNotBlockWindDownExit() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
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
        vault.restock(3, 3, 0);
        vm.prank(keeper);
        vault.list(3, 0);
        uint256[] memory ids = vault.openListings();
        assertEq(ids.length, 3);
        address originalOracle = FWA.floorOracle();
        GasBurningOracle hostile = new GasBurningOracle();
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(hostile));
        vm.prank(owner);
        vault.startWindDown();

        // Repaired (S1): the oracle read is capped at 100k gas, so all three exit in one call.
        uint256 g = gasleft();
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        g -= gasleft();
        assertTrue(succeeded, "gas-burning oracle no longer blocks the exit");
        assertEq(vault.openListings().length, 0, "every position unlisted");
        assertLt(g, 3_000_000, "well inside one transaction");
        originalOracle; // the hostile oracle stays installed throughout
    }

    function test_malformedOracleDoesNotBlockExit() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
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
        vault.restock(1, 3, 0);
        vm.prank(keeper);
        vault.list(1, 0);
        uint256[] memory ids = vault.openListings();
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
        MalformedOracle hostile = new MalformedOracle();
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(hostile));
        vm.prank(owner);
        vault.startWindDown();

        // Repaired (S1): malformed words mean "no cap", so the exit runs with the hostile oracle
        // still installed; the oracle is never restored in this test.
        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        assertTrue(succeeded, "malformed oracle no longer blocks the exit");
        assertEq(vault.openListings().length, 0);
        assertEq(FWA.floorOracle(), address(hostile));
        originalOracle;
        vm.prank(keeper);
        vault.liquidate(40, 0);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "redemption filled under the malformed oracle");
        uint256 beforeClaim = alice.balance;
        vm.prank(alice);
        vault.claim();
        emit log_named_uint("holder claimed wei", alice.balance - beforeClaim);
        assertGt(alice.balance - beforeClaim, 0.95 ether);
    }
}
