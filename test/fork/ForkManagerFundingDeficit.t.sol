// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MainRenewalBase} from "./ForkMainRenewal.t.sol";
import {PackManager} from "../../src/PackManager.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @notice Reuse holds only the configured reserve; actual backing and pay still need cash.
contract ForkManagerReuseFundingTest is MainRenewalBase {
    function _initialFunding() internal pure override returns (uint256) { return 0.5 ether; }

    function test_returnedPackWaitsForRealBackingCashWithoutRetiringOrMinting() public {
        _select(false);
        _bidAndRecover();
        PackManager manager = PackManager(payable(address(account)));
        uint256 reserve = account.getParams().reserve;
        vm.prank(accountOwner);
        manager.withdraw(accountOwner, address(account).balance - reserve);
        assertEq(account.keeperCash(), reserve, "no removed renewal float hides actual cash");
        assertEq(account.idleEth(), 0);
        uint256 supply = SHAPES.totalSupply();
        bytes32 expected = account.configurationHash();
        vm.expectRevert(StrategyLib.Nothing.selector);
        account.list(backing(), 0, expected);
        assertEq(PACKS.ownerOf(packId), address(account));
        assertEq(account.idleValueOf(packId), 0.03 ether);
        assertEq(SHAPES.totalSupply(), supply);
        (bool ok,) = payable(address(account)).call{value: 0.22 ether}("");
        require(ok, "real external actor funding");
        uint256 paid = account.list(backing(), 0, account.configurationHash());
        assertGt(paid, 0);
        assertEq(account.position(account.openListingAt(0)).packId, packId);
        assertEq(SHAPES.totalSupply(), supply, "restoring cash reuses the same three Shapes");
    }

    function test_zeroPermissionPreservesInventoryAndUnpaidOwnerExit() public {
        _select(false);
        _bidAndRecover();
        VaultLib.Params memory p = account.getParams();
        p.routineCap = 0; p.routineRate = 0;
        bytes32 expected = account.configurationHash();
        vm.prank(accountOwner); account.setParams(p, expected);
        expected = account.configurationHash();
        vm.expectRevert(VaultLib.Payment.selector);
        account.list(backing(), 1, expected);
        assertEq(account.idleValueOf(packId), 0.03 ether);
        PackManager manager = PackManager(payable(address(account)));
        vm.prank(accountOwner); manager.setExiting(true);
        uint256 before = address(account).balance;
        account.recoverLiquidate(1);
        assertEq(address(account).balance - before, 0.03 ether);
        assertEq(account.idlePackCount(), 0);
    }
}
