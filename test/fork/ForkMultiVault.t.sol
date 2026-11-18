// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackVaultFactory} from "../../src/PackVaultFactory.sol";
import {FWAExposureRegistry} from "../../src/FWAExposureRegistry.sol";
import {VaultLib} from "../../src/VaultLib.sol";

contract ForkMultiVaultTest is ForkBase {
    function _create(PackVaultFactory factory) internal returns (PackVault v) {
        VaultLib.Params memory p = defaultParams();
        p.gasCeiling = 0.5 gwei;
        p.packUnitsMask = (uint64(1) << 3) | (uint64(1) << 5) | (uint64(1) << 10) | (uint64(1) << 20);
        p.maxPositions = 150;
        vm.prank(owner);
        v = factory.createVault{value: 0.01 ether}(p);
        assertTrue(factory.exposure().isVault(address(v)));
    }

    function _fund(PackVault v, address depositor) internal {
        vm.prank(depositor);
        v.deposit{value: 1 ether + v.requestCharge()}();
    }

    function test_twoVaultsShareOneExposureGuardAndRelease() public {
        vm.deal(owner, 2 ether);
        PackVaultFactory factory = new PackVaultFactory(FWA, SHAPES, PACKS, owner, 2500);
        PackVault a = _create(factory);
        PackVault b = _create(factory);
        assertEq(factory.vaultCount(), 2);
        assertEq(factory.vaultAt(0), address(a));
        assertEq(factory.vaultAt(1), address(b));
        _fund(a, alice);
        _fund(b, bob);
        toBlackout();
        vm.prank(keeper);
        a.checkpoint(0);
        vm.prank(keeper);
        b.checkpoint(0);
        toOpen();
        vm.prank(keeper);
        a.restock(1, 3, 0);
        vm.prank(keeper);
        b.restock(1, 3, 0);
        vm.prank(keeper);
        a.list(1, 0);
        vm.prank(keeper);
        b.list(1, 0);
        uint256[] memory ia = a.openListings();
        uint256[] memory ib = b.openListings();
        assertEq(ia.length, 1);
        assertEq(ib.length, 1);
        FWAExposureRegistry guard = factory.exposure();
        assertEq(guard.listingVault(ia[0]), address(a));
        assertEq(guard.listingVault(ib[0]), address(b));
        assertGt(guard.bookedWeight(), 0);
        uint256 prior = guard.bookedWeight();
        vm.prank(owner);
        a.startWindDown();
        vm.prank(keeper);
        a.unlist(ia, 0);
        assertEq(guard.listingVault(ia[0]), address(0));
        assertLt(guard.bookedWeight(), prior);
        assertEq(guard.listingVault(ib[0]), address(b));
    }

    function test_admissionRevertLeavesPackAndBackingUnchanged() public {
        vm.deal(owner, 1 ether);
        // Tiny permitted share: one ordinary listing should exceed this.
        PackVaultFactory factory = new PackVaultFactory(FWA, SHAPES, PACKS, owner, 1);
        PackVault a = _create(factory);
        _fund(a, alice);
        toBlackout();
        vm.prank(keeper);
        a.checkpoint(0);
        toOpen();
        vm.prank(keeper);
        a.restock(1, 3, 0);
        uint256 balanceBefore = address(a).balance;
        uint256 packBefore = a.idlePacks().length;
        vm.prank(keeper);
        vm.expectRevert(FWAExposureRegistry.ExposureExceeded.selector);
        a.list(1, 0);
        assertEq(a.openListings().length, 0);
        assertEq(a.idlePacks().length, packBefore);
        assertEq(address(a).balance, balanceBefore);
        assertEq(factory.exposure().bookedWeight(), 0);
    }
}
