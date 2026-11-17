// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";

/// @notice Independent release-candidate audit probes (commit 3e600e5). Attacks the real deployed
///         FWA/Shapes/ShapePacks on a mainnet fork. No mocks. These target the contract claim
///         "Neither role has any path that moves assets to itself" (PackVault natspec) and the
///         guardian stop-only trust boundary.
contract AuditRoleAndKeeperTest is ForkBase {
    uint256 constant TX_CAP = 16_777_216;

    /// A compromised/malicious admin proposes the worst parameters the bytecode allows
    /// (premium 50%, ceiling 50 gwei, maxTip 50 gwei, opGasCap at the EIP-7825 cap), waits out the
    /// delay, then acts as the keeper. Measures how much vault ETH the admin can pull per checkpoint
    /// and whether it is a net gain. Tests the natspec claim that no role can move assets to itself.
    function test_adminMaxParamsSelfKeepExtraction() public {
        // Seed real NAV first.
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();

        // Admin cranks every keeper-pay lever to its hard bytecode bound.
        PackVault.Params memory p = defaultParams();
        p.keeperPremiumBps = 5_000; // MAX_KEEPER_PREMIUM_BPS
        p.gasCeiling = 50 gwei; // MAX_GAS_CEILING
        p.maxTip = 50 gwei; // <= gasCeiling
        p.opGasCap = uint128(TX_CAP);
        vm.prank(admin);
        vault.proposeParams(p);
        vm.warp(block.timestamp + vault.paramDelay());
        vault.applyParams();

        // Create checkpoint "work" so the call is paid: admin escrows a dust deposit.
        vm.deal(admin, 1 ether);
        vm.prank(admin);
        vault.deposit{value: 0.01 ether}();

        toBlackout();
        // Worst case for extraction: the keeper bids the ceiling, so the reimbursed price is the
        // ceiling and the keeper actually pays it (tx.gasprice == price).
        vm.fee(0.15 gwei);
        vm.txGasPrice(50 gwei);

        uint256 before = admin.balance;
        uint256 navBefore = vault.lastNav();
        uint256 g = gasleft();
        vm.prank(admin);
        vault.checkpoint();
        uint256 gasUsed = g - gasleft();
        uint256 pay = admin.balance - before;

        emit log_named_uint("checkpoint gas used", gasUsed);
        emit log_named_uint("keeper pay (wei)", pay);
        emit log_named_uint("keeper real gas cost at 50 gwei (wei)", gasUsed * 50 gwei);
        emit log_named_uint("nav before checkpoint (wei)", navBefore);

        // 1. Extraction exists: the admin, as keeper, pulled vault ETH to itself.
        assertGt(pay, 0, "admin-as-keeper is paid vault ETH: a role-to-self asset path exists");

        // 2. But it is bounded by the reimbursement formula: (gasUsed + 30k) x ceiling x (1+premium).
        uint256 formulaCap = (gasUsed + vault.KEEPER_OVERHEAD_GAS()) * 50 gwei * 15_000 / 10_000;
        assertLe(pay, formulaCap, "pay never exceeds the reimbursement formula");

        // 3. And it is NOT a rational enrichment: to pull `pay` the admin burns `realCost` of its own
        //    gas; the only true surplus is the premium plus the 30k overhead, both on gas actually
        //    spent. Report the net so the owner can see the real exposure.
        uint256 realCost = gasUsed * 50 gwei; // what the keeper pays at tx.gasprice
        emit log_named_int("admin net (pay - realCost), wei", int256(pay) - int256(realCost));
        // The surplus over the keeper's own cost is bounded by premium*realCost + overhead pay.
        uint256 surplusBound =
            realCost * 5_000 / 10_000 + (vault.KEEPER_OVERHEAD_GAS()) * 50 gwei * 15_000 / 10_000;
        assertLe(pay > realCost ? pay - realCost : 0, surplusBound, "surplus bounded by premium+overhead");

        // Reset fee env.
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    /// The guardian is "stop only". Prove that even the most aggressive stop it can do to keeper
    /// economics -- lowering the gas ceiling to zero so every paid call reimburses nothing -- does
    /// not trap holder funds: redemption pricing and claim remain callable (unpaid) by holders.
    function test_guardianZeroCeilingDoesNotTrapHolderFunds() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();

        // Guardian zeroes the ceiling. Paid keeper work now reimburses 0.
        vm.prank(guardian);
        vault.lowerCaps(100 ether, 150, 0, 0);

        uint256 shares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(shares);

        toBlackout();
        // A keeper gets nothing now; alice must price her own redemption (callable by anyone).
        uint256 kBefore = keeper.balance;
        vm.prank(keeper);
        vault.checkpoint();
        // D55: the guardian zeroed both the ceiling and the work fee, so no keeper pay at all.
        assertEq(keeper.balance, kBefore, "zero ceiling and zero work fee => keeper reimbursed nothing");

        toOpen();
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        uint256 got = alice.balance - before;
        emit log_named_uint("alice redemption claimed under zero ceiling (wei)", got);
        // Alice's ~1 ETH is paid in full (within rounding + her share of earlier keeper gas).
        assertApproxEqAbs(got, 1 ether, 1e14, "holder funds not trapped by guardian zeroing the ceiling");
        assertLe(got, 1 ether);
    }
}
