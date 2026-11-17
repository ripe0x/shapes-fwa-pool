// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";

/// @notice Independent release-candidate audit probes (commit 3e600e5). Attacks the real deployed
///         FWA/Shapes/ShapePacks on a mainnet fork. No mocks. These target the contract claim
///         "Neither role has any path that moves assets to itself" (PackVault natspec) and the
///         guardian stop-only trust boundary.
contract AuditRoleAndKeeperTest is ForkBase {
    uint256 constant TX_CAP = 16_777_216;

    /// A compromised admin sets every keeper-pay lever to its bytecode maximum (premium 10%, ceiling
    /// 50 gwei, maxTip 50 gwei, work fee 0.00005 ETH, budgets at their maxima), applied at once (D58),
    /// then manufactures checkpoint work with a dust deposit and runs the checkpoint itself
    /// (originally written by the 3e600e5 auditor against measured-gas pay; rewritten for D56).
    /// The checkpoint is funded by the request charge the admin's own deposit paid, so the admin
    /// gets back at most what it put in.
    function test_adminMaxParamsSelfKeepExtraction() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();

        VaultLib.Params memory p = defaultParams();
        p.payMarkupBps = 1_000; // MAX_PAY_MARKUP_BPS
        p.gasCeiling = 50 gwei;
        p.maxTip = 50 gwei;
        p.workFee = uint64(vault.MAX_WORK_FEE());
        vm.prank(admin);
        vault.setParams(p);

        vm.deal(admin, 1 ether);
        vm.fee(0.15 gwei);
        vm.txGasPrice(50 gwei);
        uint256 charge = vault.requestCharge();
        uint256 gross = Charges.grossFor(vault, 0.01 ether);
        vm.prank(admin);
        vault.deposit{value: gross}();
        assertEq(vault.processingPool(), charge, "the checkpoint charge funds the pool");

        toBlackout();
        uint256 before = admin.balance;
        vm.prank(admin);
        uint256 pay = vault.checkpoint(0);
        assertEq(admin.balance - before, pay, "returned pay is what was paid");
        assertGt(pay, 0);
        emit log_named_uint("charge paid (wei)", charge);
        emit log_named_uint("checkpoint pay (wei)", pay);
        assertLe(pay, charge, "a manufactured checkpoint pays back at most the manufacturer's own charge");
        assertEq(vault.processingPool(), 0);
        vm.txGasPrice(0.2 gwei);
    }

    /// The guardian is "stop only". Prove that even the most aggressive stop it can do to keeper
    /// economics -- lowering the gas ceiling to zero so every paid call reimburses nothing -- does
    /// not trap holder funds: redemption pricing and claim remain callable (unpaid) by holders.
    function test_guardianZeroCeilingDoesNotTrapHolderFunds() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();

        // Guardian zeroes the ceiling. Paid keeper work now reimburses 0.
        lowerTo(100 ether, 150, 0, 0);

        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }

        toBlackout();
        // A keeper gets nothing now; alice must price her own redemption (callable by anyone).
        uint256 kBefore = keeper.balance;
        vm.prank(keeper);
        vault.checkpoint(0);
        // D55: the guardian zeroed both the ceiling and the work fee, so no keeper pay at all.
        assertEq(keeper.balance, kBefore, "zero ceiling and zero work fee => keeper reimbursed nothing");

        toOpen();
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        uint256 got = alice.balance - before;
        emit log_named_uint("alice redemption claimed under zero ceiling (wei)", got);
        // Alice's ~1 ETH is paid in full (within rounding + her share of earlier keeper gas).
        assertApproxEqAbs(got, 1 ether, 2e14, "holder funds not trapped by guardian zeroing the ceiling"); // dead shares keep ~1% of the deployment charge
        assertLe(got, 1 ether);
    }
}
