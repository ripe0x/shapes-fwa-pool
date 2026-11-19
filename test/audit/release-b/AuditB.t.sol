// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";

// Audit B throwaway tests (untracked). Copy kept in audit/release-c884959-B/AuditB.t.sol.
import {console2} from "forge-std/console2.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {IFloorOracle, LISTING_ACTIVE, LISTING_STAGED, LISTING_ALLOCATED} from "../../../src/interfaces/External.sol";
import {SelectionBase, IFwaSettle} from "../../fork/ForkSelection.t.sol";
import {ForkBase, IOwnable, IFwaAdmin} from "../../fork/ForkBase.sol";
import {Charges} from "../../utils/Charges.sol";

function canary() pure returns (VaultLib.Params memory p) {
    p.minEdgeBps = 100;
    p.keeperShareBps = 2_500;
    p.allocatedBoundBps = 1_000;
    p.packUnitsMask = 8;
    p.gasCeiling = 0.5 gwei;
    p.essentialCeiling = 2 gwei;
    p.maxTip = 0.05 gwei;
    p.workFee = 0.00002 ether;

    p.reserve = 0.005 ether;
    p.tvlCap = 2 ether;
    p.routineCap = 0.03 ether;
    p.routineRate = 0.0008 ether;
    p.essentialCap = 0.01 ether;
    p.essentialRate = 0.0002 ether;
}

contract AuditBSelection is SelectionBase {
    uint256 seenBasefee;

    receive() external payable {
        seenBasefee = block.basefee; // read inside the paid call
    }

    function _canaryParams() internal {
        VaultLib.Params memory p = canary();
        p.tvlCap = 100 ether;
        address vaultOwner = vault.owner();
        vm.prank(vaultOwner);
        vault.setParams(p);
    }

    /// E1: repeated identifiers never count as multiple successful fee claims.
    /// The production two-active-witness case also lives in ForkProductionFeeWitnessTest.
    function test_harvestRefusesRepeatedIds() public {
        _select(late());
        _canaryParams();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        uint256 credit = FWA.feeCredit(address(vault));
        uint256 debt = vault.position(selected).feeDebt;
        uint256 before = address(this).balance;
        uint256[] memory duplicate = new uint256[](2);
        duplicate[0] = selected; duplicate[1] = selected;
        vm.expectRevert(VaultLib.BadBatch.selector);
        vault.harvest(duplicate, 0);
        assertEq(FWA.feeCredit(address(vault)), credit, "rejected batch cannot spend fee credit");
        assertEq(vault.position(selected).feeDebt, debt, "rejected batch cannot alter cached debt");
        assertEq(address(this).balance, before, "repeated identifiers earn no payment");
    }

    /// E2: a listing made into a busy FWA queue is staged: list is paid the full Q_LISTED and
    /// activate is paid again.
    function test_noListingIntoBusyQueue() public {
        Candidate memory c = late();
        _select(c);
        _canaryParams();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.15 gwei);
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        TestVaultOps.sync(vault, one, 0);
        // Repaired: the vault refuses to list into a busy FWA queue, so nothing stages.
        assertGt(FWA.unsettledAcquisitionCount(), 0, "queue busy");
        uint256[] memory planned26 = TestVaultOps.proposals(vault, 1, 3);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(planned26, 0);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        if (FWA.unsettledAcquisitionCount() != 0) IFwaSettle(address(FWA)).processAcquisitions(50);
        uint256 listPay = TestVaultOps.list(vault, 1, 0);
        uint256[] memory open = TestVaultOps.open(vault);
        (,,,,,,,,,, uint8 st) = FWA.listings(open[open.length - 1]);
        assertEq(st, LISTING_ACTIVE, "listed active once the queue drained");
        assertGt(listPay, 0);
    }
}

contract AuditBPinned is ForkBase {
    uint256[] ids;

    function _build(uint256 n) internal {
        VaultLib.Params memory p = canary();
        vm.prank(owner);
        vault.setParams(p);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, n, 3, 0);
        TestVaultOps.list(vault, n, 0);
        vm.stopPrank();
        ids = TestVaultOps.open(vault);
        assertEq(ids.length, n);
    }

    /// The real oracle bounds asks at uint128. The archived 2^255 substitute is not real-oracle coverage.
    function test_maximumRealOracleAskDoesNotBlockExit() public {
        _build(3);
        address actualOracle = FWA.floorOracle();
        setPackAsk(type(uint128).max);
        (, uint256 ask,,) = IFloorOracle(actualOracle).getFloorRange(address(PACKS));
        assertEq(ask, type(uint128).max, "maximum value accepted by the real oracle");
        vault.edge(3); // No uint256 overflow at the real uint128 boundary.
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory open = ids;
        // Repaired: exits never read FWA's economics.
        vm.prank(keeper);
        TestVaultOps.unlist(vault, open, 0);
        assertEq(TestVaultOps.open(vault).length, 0, "all positions unlisted in wind-down");
        vm.prank(keeper);
        vault.liquidate(40, 0);
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        toBlackout();
        checkpoint();
        vm.prank(alice);
        vault.claim();
        assertEq(vault.lockedShares(), 0, "holder fully exits under the hostile oracle");
    }

    /// S1b: same through FWA's uncapped surcharge.
    function test_hugeSurchargeDoesNotBlockUnlist() public {
        _build(3);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(13, type(uint256).max / 1e17);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory open = ids;
        vm.prank(keeper);
        TestVaultOps.unlist(vault, open, 0); // repaired: no economics read on exit
        assertEq(TestVaultOps.open(vault).length, 0);
    }

    /// E3/E4: gas used per operation at canary values, for the pay-versus-cost table.
    function test_measureOps() public {
        VaultLib.Params memory p = canary();
        vm.prank(owner);
        vault.setParams(p);
        uint256 gross = Charges.grossFor(vault, 1.9 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        vm.startPrank(keeper);
        uint256 g = gasleft();
        uint256 pay = TestVaultOps.checkpoint(vault, 0);
        console2.log("checkpoint(0 pos): gas, pay", g - gasleft(), pay);
        vm.stopPrank();
        toOpen();
        vm.startPrank(keeper);
        g = gasleft();
        pay = TestVaultOps.restock(vault, 1, 3, 0);
        console2.log("restock(1, mint): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = TestVaultOps.restock(vault, 3, 3, 0);
        console2.log("restock(3, 1 mint): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = TestVaultOps.restock(vault, 6, 3, 0);
        console2.log("restock(6, 2 mints): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = TestVaultOps.list(vault, 1, 0);
        console2.log("list(1): gas, pay", g - gasleft(), pay);
        (, , uint128 b1) = TestVaultOps.position(vault, TestVaultOps.open(vault)[0]);
        console2.log("backing of first listing", b1);
        g = gasleft();
        pay = TestVaultOps.list(vault, 9, 0);
        console2.log("list(9): gas, pay", g - gasleft(), pay);
        vm.stopPrank();
        ids = TestVaultOps.open(vault);
        (, , uint128 bl) = TestVaultOps.position(vault, ids[ids.length - 1]);
        console2.log("backing of last listing, idle after", bl, vault.idleEth());
        // Redemption of everything: unlist, liquidate, checkpoint.
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        console2.log("redeem charge wei", rc);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        vm.startPrank(keeper);
        g = gasleft();
        pay = TestVaultOps.unlist(vault, ids, 0);
        console2.log("unlist(n): n", TestVaultOps.idle(vault).length);
        console2.log("unlist: gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = vault.liquidate(40, 0);
        console2.log("liquidate: gas, pay", g - gasleft(), pay);
        console2.log("left: open, idle packs, loose", TestVaultOps.open(vault).length, TestVaultOps.idle(vault).length, vault.looseShapeCount());
        vm.stopPrank();
        toBlackout();
        vm.startPrank(keeper);
        g = gasleft();
        pay = TestVaultOps.checkpoint(vault, 0);
        console2.log("checkpoint(redeem): gas, pay", g - gasleft(), pay);
        vm.stopPrank();
        uint256 a0 = alice.balance;
        vm.prank(alice);
        vault.claim();
        console2.log("alice claim wei (deposited 1.9 + charges)", alice.balance - a0, gross + rc);
        (uint256 r, uint256 e) = vault.budget();
        console2.log("budgets left routine, essential", r, e);
        console2.log("vault balance, lastNav", address(vault).balance, vault.lastNav());
    }
}

contract AuditBBudget is ForkBase {
    /// E5: pay funded by the requester's own charges still debits the budgets. One holder's full
    /// exit at 0.95 gwei basefee empties the essential budget; refill is 0.0002 ETH a day.
    function test_oneExitEmptiesEssentialBudget() public {
        VaultLib.Params memory p = canary();
        vm.prank(owner);
        vault.setParams(p);
        uint256 gross = Charges.grossFor(vault, 1.95 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        uint256 built;
        uint256 routinePaid;
        for (uint256 i; i < 3; ++i) {
            try vault.restock(3, TestVaultOps.buildProposals(vault, 10, 3), 0) returns (uint256 pay) {
                routinePaid += pay;
                built += 10;
            } catch {
                break;
            }
        }
        for (uint256 i; i < 3; ++i) {
            uint256 count = vault.idlePackCount();
            if (count == 0) break;
            if (count > vault.MAX_LIST_BATCH()) count = vault.MAX_LIST_BATCH();
            try vault.list(TestVaultOps.proposals(vault, count, 3), 0) returns (uint256 pay) {
                routinePaid += pay;
            } catch {
                break;
            }
        }
        vm.stopPrank();
        uint256[] memory open = TestVaultOps.open(vault);
        (uint256 r, uint256 e) = vault.budget();
        console2.log("built, listed", built, open.length);
        console2.log("routine paid for the build, routine budget left", routinePaid, r);
        console2.log("idle packs, idle ETH", TestVaultOps.idle(vault).length, vault.idleEth());

        vm.fee(0.95 gwei);
        vm.txGasPrice(1 gwei);
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        console2.log("alice's redeem charge (checkpoint + unwind) wei", rc);
        vm.startPrank(keeper);
        uint256 essentialPaid = TestVaultOps.unlist(vault, open, 0);
        console2.log("unlist pay", essentialPaid);
        uint256 lp = vault.liquidate(40, 0);
        console2.log("liquidate #1 pay", lp);
        essentialPaid += lp;
        lp = vault.liquidate(16, 0);
        console2.log("liquidate #2 pay", lp);
        essentialPaid += lp;
        (r, e) = vault.budget();
        console2.log("essential budget after unlist + liquidate", e);
        console2.log("idle packs left, loose shapes left", TestVaultOps.idle(vault).length, vault.looseShapeCount());
        // A keeper asking for any pay is now refused; the work is only done unpaid.
        vm.expectRevert();
        vault.liquidate(40, 1e12);
        vm.stopPrank();
        console2.log("essential paid in total vs unwind charge alice paid", essentialPaid, rc);
        assertEq(e, 0, "essential budget empty after one exit");
        assertEq(vault.openListingCount(), 0); assertEq(vault.idlePackCount(), 0);
        toBlackout(); checkpoint();
        assertEq(vault.lockedShares(), 0, "the exhausted-budget exit completes from requester-funded checkpoint work");
        uint256 before = alice.balance;
        vm.prank(alice); vault.claim();
        assertGt(alice.balance - before, 1.8 ether, "absolute proceeds from the full1.95ETH principal exit");
        assertEq(vault.shareBalance(alice), 0); assertEq(vault.claimableEth(alice), 0);
        (uint128 remaining,,,) = vault.redemptions(alice);
        assertEq(remaining, 0);
    }

    /// Q6: compromised owner, first transaction: maxima, then one paid call takes the routine budget.
    function test_ownerKeyFirstDay() public {
        VaultLib.Params memory p = canary();
        vm.prank(owner);
        vault.setParams(p);
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, 6, 3, 0);
        TestVaultOps.list(vault, 6, 0);
        vm.stopPrank();
        uint256[] memory open = TestVaultOps.open(vault);
        // The attacker holds the owner key and keeps for itself.
        p.minEdgeBps = 1_000; // edge "fails": unlisting becomes routine paid work
        p.gasCeiling = 50 gwei;
        p.essentialCeiling = 50 gwei;
        p.maxTip = 50 gwei;
        p.payMarkupBps = 1_000;
        p.workFee = 0.00005 ether;
        p.keeperShareBps = 5_000;
        p.routineCap = 0.3 ether;
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;
        vm.startPrank(owner);
        vault.setParams(p);
        uint256 b0 = owner.balance;
        uint256[] memory one = new uint256[](1);
        one[0] = open[0];
        uint256 pay = TestVaultOps.unlist(vault, one, 0);
        console2.log("t0: unlist 1 at maxima, routine pay", pay);
        vault.startWindDown();
        one[0] = open[1];
        pay = TestVaultOps.unlist(vault, one, 0);
        console2.log("t0: wind-down unlist 1, essential pay", pay);
        vm.warp(block.timestamp + 1 days);
        vm.roll(block.number + 7200);
        pay = vault.liquidate(1, 0);
        console2.log("t+24h: liquidate 1, essential pay", pay);
        (uint256 r, uint256 e) = vault.budget();
        console2.log("t+24h budgets routine (not reachable in wind-down?), essential", r, e);
        vm.stopPrank();
        console2.log("owner took in ~24 h", owner.balance - b0);
    }
}
