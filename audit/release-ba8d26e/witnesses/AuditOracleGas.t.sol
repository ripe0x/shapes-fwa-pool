// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, IFwaAdmin} from "../fork/ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";

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

    function test_oracleGasBurnBlocksWindDownExitWithinTransactionCap() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
        p.gasCeiling = 0.5 gwei;
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

        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        assertFalse(succeeded, "gas-burning oracle must leave too little gas for exit");
        assertEq(vault.openListings().length, 3, "no position was unlisted");

        uint256[] memory one = new uint256[](1);
        one[0] = ids[0];
        vm.prank(keeper);
        (bool oneSucceeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (one, 0)));
        assertTrue(oneSucceeded, "single exit is possible but consumes nearly a full block");
        assertEq(vault.openListings().length, 2);

        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, originalOracle);
        vm.prank(keeper);
        vault.unlist(ids, 0);
        assertEq(vault.openListings().length, 0, "remaining exits work with normal oracle");
    }

    function test_malformedOracleBlocksEvenSinglePositionExit() public {
        this.assertGasContext();
        VaultLib.Params memory p = vault.getParams();
        p.tvlCap = 2 ether;
        p.maxPositions = 30;
        p.gasCeiling = 0.5 gwei;
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

        vm.prank(keeper);
        (bool succeeded,) = address(vault).call{gas: 16_000_000}(abi.encodeCall(vault.unlist, (ids, 0)));
        assertFalse(succeeded, "ABI decode fails before the position can be unlisted");
        assertEq(vault.openListings().length, 1);

        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, originalOracle);
        vm.prank(keeper);
        vault.unlist(ids, 0);
        assertEq(vault.openListings().length, 0);
        vm.prank(keeper);
        vault.liquidate(40, 0);
        toBlackout();
        checkpoint();
        assertEq(vault.lockedShares(), 0, "exit restarts only after oracle is restored");
        uint256 beforeClaim = alice.balance;
        vm.prank(alice);
        vault.claim();
        emit log_named_uint("holder claimed wei", alice.balance - beforeClaim);
        assertGt(alice.balance - beforeClaim, 0.95 ether);
    }
}
