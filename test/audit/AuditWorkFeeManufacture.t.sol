// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {Charges} from "../utils/Charges.sol";

/// @notice Release-candidate audit of the D55 workFee (uncommitted change). Attacks the two fee
///         manufacture vectors not already covered by the repo's workFee tests:
///         (1) can a caller farm the per-checkpoint work fee by forcing paid checkpoints, and
///         (2) can a caller farm list/unlist units in healthy normal operation.
///         Real mainnet FWA/Shapes/ShapePacks; no mocks.
contract AuditWorkFeeManufactureTest is ForkBase {
    /// The paid-checkpoint unit is capped at one per 12h interval and requires a real holder flow
    /// each time. An attacker cannot manufacture more than one checkpoint fee per interval.
    function test_checkpointFeeIsOnePerIntervalAndNeedsAFlow() public {
        uint256 fee = vault.getParams().workFee;
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }

        toBlackout();
        uint256 b = keeper.balance;
        checkpoint(); // prices alice's deposit: work == true, pays 1 unit
        uint256 pay1 = keeper.balance - b;
        assertGt(pay1, fee, "paid checkpoint includes the work fee plus gas");
        uint256 planned22 = TestVaultOps.witness(vault);

        // Same interval: a second checkpoint is refused outright (no second fee this interval).
        vm.prank(keeper);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint(planned22, 0);

        // Next interval with NO holder flow: refused (distributionBps is 0). So the fee cannot be
        // farmed by just calling checkpoint every interval; a real deposit/redeem is required.
        toOpen();
        toBlackout();
        uint256 planned21 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned21, 0);

        // The cheapest manufacture: the attacker escrows the 0.01 ETH minimum deposit (their own
        // money, recoverable as shares) to force one paid checkpoint. Measure the drain.
        toOpen();
        vm.deal(bob, 1 ether);
        {
            uint256 gross_ = Charges.grossFor(vault, 0.01 ether);
            vm.prank(bob);
            vault.deposit{value: gross_}();
        } // MIN_DEPOSIT
        toBlackout();
        uint256 kb = keeper.balance;
        vm.prank(keeper);
        TestVaultOps.checkpoint(vault, 0);
        uint256 pay2 = keeper.balance - kb;
        emit log_named_uint("manufactured checkpoint pay (wei)", pay2);
        emit log_named_uint("work-fee portion drained to keeper (wei)", fee);
        // Over a year this vector is bounded by 2 intervals/day * 365 = 730 units.
        emit log_named_uint("max work-fee drain/yr via checkpoint (wei)", 730 * fee);
    }

    /// In healthy, non-winding-down operation with no redemption shortfall, unlist() reverts. So the
    /// list -> unlist -> list fee loop is not reachable: the only way to earn an unlist unit is a
    /// state the attacker cannot cheaply manufacture (wind-down, dead edge, or a real redemption).
    function test_listUnlistLoopIsGated() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();

        uint256 fee = vault.getParams().workFee;
        uint256 b = keeper.balance;
        vm.prank(keeper);
        // build mints and lists one pack at once (two work units); `list` has nothing idle to relist.
        TestVaultOps.restock(vault, 1, UNITS, 0);
        uint256 buildPay = keeper.balance - b;
        assertGt(buildPay, fee, "build pays the per-pack work fees");
        emit log_named_uint("build pay (1 pack of 6 units)", buildPay);

        uint256[] memory ids = TestVaultOps.open(vault);
        assertEq(ids.length, 1, "build lists one pack at once");

        // Healthy edge, not winding down, no redemption request: unlist must revert. No fee loop.
        vm.prank(keeper);
        vm.expectRevert(StrategyLib.UnlistNotAllowed.selector);
        TestVaultOps.unlist(vault, ids, 0);
    }
}
