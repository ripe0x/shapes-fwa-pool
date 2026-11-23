// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, ForceSender} from "./ForkBase.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Charges} from "../utils/Charges.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Ownable} from "solady/auth/Ownable.sol";

/// @notice The behaviour-shaping Params added in the settings rework (keepAdvantage,
///         purchaserGasPrice, purchaserRedeemPack/Shape, minDeposit, minDistribution) and the
///         packUnitsMask-derived reference position. Every change is owner-only, immediate (D58)
///         and bounded; a compromised owner at the ceilings cannot move depositor funds.
contract ForkSettingsTest is ForkBase {
    receive() external payable {}

    function _set(VaultLib.Params memory p) internal {
        vm.prank(owner);
        vault.setParams(p);
    }

    // ----------------------------------------------------------------- bounds

    /// Each new param is accepted at its ceiling and rejected one wei above it.
    function test_boundsOnNewParams() public {
        VaultLib.Params memory p = vault.getParams();
        // At the ceilings: accepted.
        p.keepAdvantage = 0.01 ether;
        p.purchaserGasPrice = 100 gwei;
        p.purchaserRedeemPack = 200_000;
        p.purchaserRedeemShape = 60_000;
        p.minDeposit = 1 ether;
        p.minDistribution = 1 ether;
        _set(p); // no revert

        _expectOutOfBounds(_with(p, 0, 0.01 ether + 1));
        _expectOutOfBounds(_with(p, 1, 100 gwei + 1));
        _expectOutOfBounds(_with(p, 2, 200_001));
        _expectOutOfBounds(_with(p, 3, 60_001));
        _expectOutOfBounds(_with(p, 4, 1 ether + 1));
        _expectOutOfBounds(_with(p, 5, 1 ether + 1));
    }

    function _with(VaultLib.Params memory base, uint256 field, uint64 v)
        internal
        pure
        returns (VaultLib.Params memory p)
    {
        p = base;
        if (field == 0) p.keepAdvantage = v;
        if (field == 1) p.purchaserGasPrice = v;
        if (field == 2) p.purchaserRedeemPack = v;
        if (field == 3) p.purchaserRedeemShape = v;
        if (field == 4) p.minDeposit = v;
        if (field == 5) p.minDistribution = v;
    }

    function _expectOutOfBounds(VaultLib.Params memory p) internal {
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(p);
    }

    /// Only the owner may set the new params.
    function test_onlyOwnerSets() public {
        VaultLib.Params memory p = vault.getParams();
        p.keepAdvantage = 0.0005 ether;
        vm.prank(alice);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.setParams(p);
    }

    // ----------------------------------------------------------------- immediate effect

    /// Raising keepAdvantage or purchaserGasPrice lowers the backing a new listing targets, in the
    /// same transaction (no delay), and raising them far enough stops new listings entirely.
    function test_keepIncentiveParamsMoveBackingAtOnce() public {
        _lowCeiling();
        (,, bool ok0) = vault.edge(UNITS);
        assertTrue(ok0, "lists at defaults");
        uint256 b0 = B();

        VaultLib.Params memory p = vault.getParams();
        p.keepAdvantage = 0.0005 ether; // up from 0.0003, still above the P/0.95 floor
        _set(p);
        uint256 b1 = B();
        assertGt(b1, 0, "still lists at the modest bump");
        assertLt(b1, b0, "higher keepAdvantage lowers backing immediately");

        p = vault.getParams();
        p.purchaserGasPrice = 50 gwei; // a far larger assumed purchaser gas price
        _set(p);
        (, uint256 b2, bool ok2) = vault.edge(UNITS);
        assertLt(b2, b1, "higher purchaser gas price lowers backing further");
        // Pushed below the P/0.95 floor: listing stops, but nothing is lost.
        assertFalse(ok2, "an extreme purchaser-gas assumption pauses new listing");
    }

    /// A compromised owner setting every keep-incentive param to its ceiling cannot touch holder
    /// funds: it only stops new listing. An already-priced holder keeps her exact NAV claim and can
    /// still redeem.
    function test_hostileKeepIncentiveCannotHarmDepositors() public {
        _lowCeiling();
        // A real holder with priced shares.
        uint256 gross = Charges.grossFor(vault, 2 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        uint256 navBefore = vault.lastNav();
        uint256 supplyBefore = vault.totalShares();
        assertGt(shares, 0, "alice priced in");

        VaultLib.Params memory p = vault.getParams();
        p.keepAdvantage = 0.01 ether;
        p.purchaserGasPrice = 100 gwei;
        p.purchaserRedeemPack = 200_000;
        p.purchaserRedeemShape = 60_000;
        _set(p);

        (, uint256 backing, bool ok) = vault.edge(UNITS);
        assertFalse(ok, "hostile margins stop new listings");
        assertEq(backing, 0, "no backing posted");
        // A build at any proposal is refused (no valid backing); funds stay put.
        uint256[] memory proposal = new uint256[](1);
        proposal[0] = 0.065 ether;
        vm.prank(keeper);
        vm.expectRevert(); // InvalidBacking (hostile margins leave no listable backing)
        vault.build(UNITS, proposal, 0);

        // Holder accounting is untouched by the param change.
        assertEq(vault.shareBalance(alice), shares, "shares unchanged");
        assertEq(vault.lastNav(), navBefore, "NAV unchanged");
        assertEq(vault.totalShares(), supplyBefore, "supply unchanged");

        // And she can still exit.
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        assertEq(vault.lockedShares(), shares, "redemption still works under hostile params");
    }

    // ----------------------------------------------------------------- minDeposit

    /// minDeposit is enforced immediately and independently of the fixed first-issuance seed floor.
    function test_minDepositImmediate() public {
        uint256 ck = vault.requestCharge();
        // Default 0.01 ETH: a 0.02 ETH deposit is fine.
        vm.prank(alice);
        vault.deposit{value: 0.02 ether + ck}();

        VaultLib.Params memory p = vault.getParams();
        p.minDeposit = 1 ether;
        _set(p);

        ck = vault.requestCharge();
        vm.prank(bob);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 0.5 ether + ck}(); // below the new minimum

        vm.prank(bob);
        vault.deposit{value: 1 ether + ck}(); // at the new minimum: ok
    }

    // ----------------------------------------------------------------- minDistribution

    /// minDistribution withholds a gain below it (the gain stays in NAV, to holders' benefit) and
    /// the change is immediate.
    function test_minDistributionWithholdsSmallGain() public {
        VaultLib.Params memory p = vault.getParams();
        p.distributionBps = 5_000;
        _set(p);
        // A priced holder, then a donation that creates a distributable gain.
        uint256 gross = Charges.grossFor(vault, 3 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        new ForceSender{value: 0.5 ether}(payable(address(vault)));

        uint256 snap = vm.snapshotState();

        // High minDistribution: the gain is withheld, so a no-flow checkpoint reverts Nothing.
        p = vault.getParams();
        p.minDistribution = 1 ether;
        _set(p);
        toBlackout();
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(0, 0);

        vm.revertToState(snap);

        // Default minDistribution (0.01 ETH): the same gain is distributed.
        toBlackout();
        uint256 reserveBefore = vault.distributionReserve();
        vm.prank(keeper);
        vault.checkpoint(0, 0);
        assertGt(vault.distributionReserve(), reserveBefore, "gain distributed at the low minimum");
    }

    // ----------------------------------------------------------------- reference position

    /// positionValue and the per-position charges are derived from the smallest enabled pack size.
    function test_positionValueFollowsSmallestEnabledSize() public {
        // Default mask enables only the 6-unit recipe.
        assertEq(vault.getParams().packUnitsMask, uint64(1) << 6, "default mask");
        uint256 pv6 = vault.positionValue();
        uint256 deploy6 = vault.deployCharge();
        // ~0.06 value + ~0.0649 backing.
        assertApproxEqAbs(pv6, 0.1249 ether, 0.0005 ether, "6-unit reference capital");

        // Also enable the 3-unit recipe: the reference drops to the smaller pack.
        VaultLib.Params memory p = vault.getParams();
        p.packUnitsMask = uint64(1) << 6 | uint64(1) << 3;
        _set(p);
        uint256 pv3 = vault.positionValue();
        uint256 deploy3 = vault.deployCharge();
        assertLt(pv3, pv6, "reference capital follows the smallest enabled size");
        assertApproxEqAbs(pv3, 0.0620 ether, 0.0010 ether, "3-unit reference capital (0.03 value + backing)");
        // A 3-unit pack is three 0.01 Shapes (three mints) vs the 6-unit's two, so its per-position
        // deploy cost is actually higher; the charge tracks the real cost of the pack built.
        assertGt(deploy3, deploy6, "the 3-unit reference (3 Shapes) costs more to deploy than the 6-unit (2)");
    }

    /// @dev The default params list 6-unit packs at a low ceiling (mirrors ForkBacking).
    function _lowCeiling() internal {
        VaultLib.Params memory p = vault.getParams();
        (p.gasCeiling, p.essentialCeiling) = (0.5 gwei, 0.5 gwei);
        if (p.maxTip > 0.5 gwei) p.maxTip = 0.5 gwei;
        _set(p);
    }
}
