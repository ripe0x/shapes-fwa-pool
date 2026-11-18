// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable} from "./ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {PackVault} from "../../src/PackVault.sol";

interface IFWAExemption {
    function setOracleExemptCollection(address collection, bool yes) external;
}

contract ForkPackSizesTest is ForkBase {
    function _setupForSizes() internal {
        vm.prank(IOwnable(address(FWA)).owner());
        IFWAExemption(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        VaultLib.Params memory p = vault.getParams();
        p.packUnitsMask = (uint64(1) << 3) | (uint64(1) << 5) | (uint64(1) << 10) | (uint64(1) << 20);
        p.gasCeiling = 0.5 gwei;
        vm.prank(owner);
        vault.setParams(p);
        vm.prank(alice);
        vault.deposit{value: 5 ether + vault.requestCharge()}();
        toBlackout();
        checkpoint();
        toOpen();
    }

    function test_wholeShapeMintInside01PackPreservesPaidPrimaryMint() public {
        _setupForSizes();
        (,, bool ok) = vault.edge(10);
        assertTrue(ok);
        vm.prank(keeper);
        vault.restock(1, 10, 0);
        uint256[] memory ids = vault.idlePacks();
        assertEq(ids.length, 1);
        assertEq(PACKS.valueOf(ids[0]), 0.1 ether);
        uint256[] memory parts = PACKS.contentsOf(ids[0]);
        assertEq(parts.length, 1, "one 0.1 ETH primary mint, no redundant split");
        assertEq(SHAPES.backingOf(parts[0]), 0.1 ether);
        assertEq(vault.looseShapeCount(), 0);
        vm.prank(keeper);
        vault.list(1, 0);
        assertEq(vault.openListings().length, 1);
    }

    function test_twoPaidWholeShapesInside02Pack() public {
        _setupForSizes();
        (,, bool ok) = vault.edge(20);
        assertTrue(ok);
        vm.prank(keeper);
        vault.restock(1, 20, 0);
        uint256[] memory ids = vault.idlePacks();
        assertEq(ids.length, 1);
        assertEq(PACKS.valueOf(ids[0]), 0.2 ether);
        uint256[] memory parts = PACKS.contentsOf(ids[0]);
        assertEq(parts.length, 2, "two paid 0.1 ETH primary mints");
        assertEq(SHAPES.backingOf(parts[0]), 0.1 ether);
        assertEq(SHAPES.backingOf(parts[1]), 0.1 ether);
        assertEq(vault.looseShapeCount(), 0);
        vm.prank(keeper);
        vault.list(1, 0);
        uint256[] memory active = vault.openListings();
        assertEq(active.length, 1);
        (,uint64 units,uint128 backing) = vault.positions(active[0]);
        assertEq(units, 20);
        assertGe(backing, 0.2 ether);
    }
}
