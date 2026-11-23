// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {Charges} from "../utils/Charges.sol";

/// @dev A depositor can cancel and checkpoint atomically while controlling the checkpoint caller.
contract CancelCheckpointAttacker {
    PackVault immutable vault;

    constructor(PackVault v) {
        vault = v;
    }
    receive() external payable {}

    function enter() external payable {
        vault.deposit{value: msg.value}();
    }

    function cancelAndCheckpoint(uint256 witness) external {
        vault.cancelDeposit();
        vault.checkpoint(witness, 0);
    }
}

contract ForkCancellationTimingTest is ForkBase {
    receive() external payable {}

    function test_cancelledRequestsRefundFirstSponsorAndChargeNextRequester() public {
        uint256 first = vault.requestCharge();
        uint256 aliceGross = Charges.grossFor(vault, 0.1 ether);
        vm.prank(alice);
        vault.deposit{value: aliceGross}();
        assertEq(vault.processingPool(), first);
        uint256 bobGross = Charges.grossFor(vault, 0.1 ether);
        assertEq(bobGross, 0.1 ether, "later requester shares the existing charge");
        uint256 gasBefore = gasleft();
        vm.prank(bob);
        vault.deposit{value: bobGross}();
        uint256 bobDepositGas = gasBefore - gasleft();
        vm.prank(alice);
        vault.cancelDeposit();
        gasBefore = gasleft();
        vm.prank(bob);
        vault.cancelDeposit();
        uint256 bobCancelGas = gasBefore - gasleft();
        assertEq(vault.pendingDepositTotal(), 0);
        assertEq(vault.processingPool(), 0, "no canceled charge can fund an unrelated checkpoint");
        assertEq(vault.chargeRefundReserve(), first, "first payer retains a protected refund claim");
        assertEq(vault.requestCharge(), first, "the next requester must fund its own checkpoint");
        uint256 free = vault.freeEth();
        uint256 aliceBefore = alice.balance;
        uint256 refundableEra = vault.chargeEra();
        assertGt(refundableEra, 0, "first request opens a distinct charge era");
        vm.prank(alice);
        vault.claimCheckpointRefund(refundableEra);
        assertEq(alice.balance - aliceBefore, first, "first payer recovers its exact charge");
        assertEq(vault.chargeRefundReserve(), 0);
        assertEq(vault.freeEth(), free, "refund does not consume strategy capital");
        vm.prank(alice);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.claimCheckpointRefund(refundableEra);
        emit log_named_uint("first checkpoint charge refunded (wei)", first);
        emit log_named_uint("attacker deposit plus cancel measured gas", bobDepositGas + bobCancelGas);
    }

    function test_gasRepriceTopUpsReturnToTheirOwnPayers() public {
        VaultLib.Params memory p = vault.getParams();
        p.essentialCeiling = 0.1 gwei;
        vm.prank(owner);
        vault.setParams(p);
        uint256 aliceCharge = vault.requestCharge();
        uint256 aliceGross = Charges.grossFor(vault, 0.1 ether);
        vm.prank(alice);
        vault.deposit{value: aliceGross}();

        p.essentialCeiling = 0.5 gwei;
        vm.prank(owner);
        vault.setParams(p);
        uint256 bobCharge = vault.requestCharge();
        assertGt(bobCharge, 0, "new quote requires a second payer");
        uint256 bobGross = Charges.grossFor(vault, 0.1 ether);
        vm.prank(bob);
        vault.deposit{value: bobGross}();
        vm.prank(alice);
        vault.cancelDeposit();
        uint256 bobBefore = bob.balance;
        vm.prank(bob);
        vault.cancelDeposit();
        assertEq(bob.balance - bobBefore, 0.1 ether + bobCharge, "last payer receives its own top-up");
        assertEq(vault.chargeRefundReserve(), aliceCharge);
        uint256 aliceBefore = alice.balance;
        uint256 refundableEra = vault.chargeEra();
        vm.prank(alice);
        vault.claimCheckpointRefund(refundableEra);
        assertEq(alice.balance - aliceBefore, aliceCharge, "first payer recovers its retained charge");
    }

    function test_firstSponsorFundsRemainingUsersCheckpoint() public {
        uint256 charge = vault.requestCharge();
        uint256 aliceGross = Charges.grossFor(vault, 0.1 ether);
        vm.prank(alice);
        vault.deposit{value: aliceGross}();
        uint256 bobGross = Charges.grossFor(vault, 0.1 ether);
        assertEq(bobGross, 0.1 ether);
        vm.prank(bob);
        vault.deposit{value: bobGross}();
        vm.prank(alice);
        vault.cancelDeposit();
        assertEq(vault.processingPool(), charge, "Alice still funds Bob's live request");
        toBlackout();
        checkpoint();
        assertGt(vault.shareBalance(bob), 0);
        assertEq(vault.chargeRefundReserve(), 0);
        assertFalse(vault.chargeRefundable(vault.chargeEra()), "a completed checkpoint consumes its charge");
    }

    function test_cancellableEscrowCannotBlockLiquidation() public {
        uint256 aliceGross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: aliceGross}();
        toBlackout();
        checkpoint();
        toOpen();
        TestVaultOps.restock(vault, 1, UNITS, 0);
        uint256 listing = vault.openListingAt(0);

        uint256 aliceShares = vault.shareBalance(alice);
        uint256 redeemCharge = Charges.redeemCharge(vault, aliceShares);
        vm.prank(alice);
        vault.requestRedeem{value: redeemCharge}(aliceShares);
        uint256[] memory one = new uint256[](1);
        one[0] = listing;
        TestVaultOps.unlist(vault, one, 0);
        assertEq(vault.idlePackCount(), 1, "real returned ShapePack is available to redeem");
        CancelCheckpointAttacker attacker = new CancelCheckpointAttacker(vault);
        uint256 gross = Charges.grossFor(vault, 0.1 ether);
        attacker.enter{value: gross}();
        uint256 escrow = vault.pendingDepositTotal();
        assertEq(escrow, 0.1 ether);
        uint256 before = address(vault).balance;
        uint256 pay = vault.liquidate(1, 0);
        assertEq(vault.idlePackCount(), 0, "redeemer can release real idle pack despite cancellable escrow");
        assertEq(vault.pendingDepositTotal(), escrow, "liquidation preserves escrow liability");
        assertEq(address(vault).balance - before + pay, P, "pack redemption returns face value before keeper pay");
        toBlackout();
        attacker.cancelAndCheckpoint(0);
        assertEq(vault.pendingDepositTotal(), 0, "attacker receives cancellation refund");
        assertEq(vault.idlePackCount(), 0, "same-block checkpoint cannot strand an idle pack");
        uint256 reserve = vault.redemptionReserve();
        uint256 free = vault.freeEth();
        uint256 aliceBefore = alice.balance;
        assertGt(reserve, 0, "checkpoint fills a real redemption");
        vm.prank(alice);
        vault.claim();
        uint256 received = alice.balance - aliceBefore;
        assertGt(received, 0);
        assertEq(vault.redemptionReserve() + received, reserve, "holder claim consumes only reserved ETH");
        assertEq(vault.claimableTotal(), 0, "no settled liability remains after claim");
        assertEq(vault.freeEth(), free, "claim cannot consume strategy capital");
    }
}
