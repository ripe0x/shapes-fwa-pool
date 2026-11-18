// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

// Audit B throwaway tests (untracked). Copy kept in audit/release-c884959-B/AuditB.t.sol.
import {console2} from "forge-std/console2.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {LISTING_ACTIVE, LISTING_STAGED, LISTING_ALLOCATED} from "../../src/interfaces/External.sol";
import {SelectionBase, IFwaSettle} from "./ForkSelection.t.sol";
import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {Charges} from "../utils/Charges.sol";

/// Hostile floor oracle FWA's owner (or a broken oracle) could point at: valid by FWA's rules,
/// absurd ask.
contract HugeAskOracle {
    function getFloorRange(address) external view returns (uint256, uint256, uint48, uint48) {
        return (1, 1 << 255, uint48(block.timestamp), uint48(1 days));
    }
}

function canary() pure returns (VaultLib.Params memory p) {
    p.minEdgeBps = 100;
    p.keeperShareBps = 2_500;
    p.allocatedBoundBps = 1_000;
    p.packUnitsMask = 8;
    p.gasCeiling = 0.5 gwei;
    p.essentialCeiling = 2 gwei;
    p.maxTip = 0.05 gwei;
    p.workFee = 0.00002 ether;
    p.maxPositions = 30;
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
        vm.prank(makeAddr("sel-admin"));
        vault.setParams(p);
    }

    function _active() internal view returns (uint256[] memory ids) {
        uint256[] memory open = vault.openListings();
        ids = new uint256[](open.length - 1);
        uint256 j;
        for (uint256 i; i < open.length; ++i) {
            if (open[i] != selected) ids[j++] = open[i];
        }
    }

    /// E1: harvest counts every repeated id as a listing "with fees to claim".
    function test_harvestDuplicateIdsInflatePay() public {
        _select(late());
        _canaryParams();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.15 gwei);
        uint256[] memory ids = _active();
        uint256 snap = vm.snapshotState();

        uint256 b0 = address(this).balance;
        uint256 v0 = address(vault).balance;
        uint256 g0 = gasleft();
        uint256 honest = vault.harvest(ids, 0);
        uint256 honestGas = g0 - gasleft();
        uint256 fees = address(vault).balance + honest - v0;
        assertEq(address(this).balance - b0, honest);
        assertEq(seenBasefee, 0.15 gwei, "basefee inside the paid call");
        console2.log("fees harvested wei", fees);
        console2.log("honest: n ids, pay wei, gas", ids.length, honest, honestGas);

        vm.revertToState(snap);
        // Largest n whose quote still fits 25% of the fees.
        uint256 price = 0.2 gwei;
        uint256 n = (fees * 2_500 / 10_000 / price - 80_000) / 15_000;
        uint256[] memory dup = new uint256[](n);
        for (uint256 i; i < n; ++i) {
            dup[i] = ids[i % ids.length];
        }
        b0 = address(this).balance;
        g0 = gasleft();
        uint256 inflated = vault.harvest(dup, 0);
        uint256 dupGas = g0 - gasleft();
        assertEq(address(this).balance - b0, inflated);
        console2.log("duplicates: n ids, pay wei, gas", n, inflated, dupGas);
        console2.log("duplicate caller cost wei at 0.15 gwei, 0 tip (+21k intrinsic, calldata)", (dupGas + 21_000 + n * 16 * 32) * 0.15 gwei);
        assertGt(inflated, honest, "duplicates raise the pay");
        assertLe(dupGas, 16_777_216);
    }

    /// E2: a listing made into a busy FWA queue is staged: list is paid the full Q_LISTED and
    /// activate is paid again.
    function test_stagedListPaidTwice() public {
        Candidate memory c = late();
        _select(c);
        _canaryParams();
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.15 gwei);
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        uint256[] memory one = new uint256[](1);
        one[0] = selected;
        vault.sync(one, 0);
        console2.log("FWA unsettled count at list time", FWA.unsettledAcquisitionCount());
        uint256 g0 = gasleft();
        uint256 listPay = vault.list(1, 0);
        uint256 listGas = g0 - gasleft();
        uint256[] memory open = vault.openListings();
        one[0] = open[open.length - 1];
        (,,,,,,,,,, uint8 st) = FWA.listings(one[0]);
        console2.log("status after list (5 = staged)", st);
        console2.log("staged list: pay wei, gas", listPay, listGas);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        if (FWA.unsettledAcquisitionCount() != 0) IFwaSettle(address(FWA)).processAcquisitions(50);
        (,,,,,,,,,, st) = FWA.listings(one[0]);
        console2.log("status after queue drained", st);
        if (st == LISTING_STAGED) {
            g0 = gasleft();
            uint256 actPay = vault.activate(one, 20, 0);
            console2.log("activate: pay wei, gas", actPay, g0 - gasleft());
        }
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
        vault.restock(n, 3, 0);
        vault.list(n, 0);
        vm.stopPrank();
        ids = vault.openListings();
        assertEq(ids.length, n);
    }

    /// S1: an oracle answer valid by FWA's rules but with a huge ask makes `edge` overflow, and
    /// `unlist` calls `edge` first: positions cannot be withdrawn, even in wind-down.
    function test_hugeOracleAskBlocksUnlistAndWindDown() public {
        _build(3);
        HugeAskOracle o = new HugeAskOracle();
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(o));
        vm.expectRevert();
        vault.edge(3);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory open = ids;
        vm.prank(keeper);
        vm.expectRevert();
        vault.unlist(open, 0);
        // The holder exits what free ETH covers; the listed capital stays at FWA.
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        vm.prank(keeper);
        vm.expectRevert();
        vault.unlist(open, 0);
        toBlackout();
        checkpoint();
        vm.prank(alice);
        vault.claim();
        (, , uint128 backing) = vault.positions(ids[0]);
        console2.log("backing per position wei", backing);
        console2.log("alice paid out of 1 ETH deposited", alice.balance + 1 ether + rc - 50 ether);
        console2.log("positions still open, stuck value wei", vault.openListings().length, 3 * (uint256(backing) + 0.03 ether));
        console2.log("locked shares left", vault.lockedShares());
        assertEq(vault.openListings().length, 3);
        assertGt(vault.lockedShares(), 0);
    }

    /// S1b: same through FWA's uncapped surcharge.
    function test_hugeSurchargeBlocksUnlist() public {
        _build(3);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setUint(13, type(uint256).max / 1e17);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory open = ids;
        vm.prank(keeper);
        vm.expectRevert();
        vault.unlist(open, 0);
        assertEq(vault.openListings().length, 3);
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
        uint256 pay = vault.checkpoint(0);
        console2.log("checkpoint(0 pos): gas, pay", g - gasleft(), pay);
        vm.stopPrank();
        toOpen();
        vm.startPrank(keeper);
        g = gasleft();
        pay = vault.restock(1, 3, 0);
        console2.log("restock(1, mint): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = vault.restock(3, 3, 0);
        console2.log("restock(3, 1 mint): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = vault.restock(6, 3, 0);
        console2.log("restock(6, 2 mints): gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = vault.list(1, 0);
        console2.log("list(1): gas, pay", g - gasleft(), pay);
        (, , uint128 b1) = vault.positions(vault.openListings()[0]);
        console2.log("backing of first listing", b1);
        g = gasleft();
        pay = vault.list(9, 0);
        console2.log("list(9): gas, pay", g - gasleft(), pay);
        vm.stopPrank();
        ids = vault.openListings();
        (, , uint128 bl) = vault.positions(ids[ids.length - 1]);
        console2.log("backing of last listing, idle after", bl, vault.idleEth());
        // Redemption of everything: unlist, liquidate, checkpoint.
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        console2.log("redeem charge wei", rc);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        vm.startPrank(keeper);
        g = gasleft();
        pay = vault.unlist(ids, 0);
        console2.log("unlist(n): n", vault.idlePacks().length);
        console2.log("unlist: gas, pay", g - gasleft(), pay);
        g = gasleft();
        pay = vault.liquidate(40, 0);
        console2.log("liquidate: gas, pay", g - gasleft(), pay);
        console2.log("left: open, idle packs, loose", vault.openListings().length, vault.idlePacks().length, vault.looseShapeCount());
        vm.stopPrank();
        toBlackout();
        vm.startPrank(keeper);
        g = gasleft();
        pay = vault.checkpoint(0);
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
            try vault.restock(10, 3, 0) returns (uint256 pay) {
                routinePaid += pay;
                built += 10;
            } catch {
                break;
            }
        }
        for (uint256 i; i < 3; ++i) {
            try vault.list(10, 0) returns (uint256 pay) {
                routinePaid += pay;
            } catch {
                break;
            }
        }
        vm.stopPrank();
        uint256[] memory open = vault.openListings();
        (uint256 r, uint256 e) = vault.budget();
        console2.log("built, listed", built, open.length);
        console2.log("routine paid for the build, routine budget left", routinePaid, r);
        console2.log("idle packs, idle ETH", vault.idlePacks().length, vault.idleEth());

        vm.fee(0.95 gwei);
        vm.txGasPrice(1 gwei);
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        console2.log("alice's redeem charge (checkpoint + unwind) wei", rc);
        vm.startPrank(keeper);
        uint256 essentialPaid = vault.unlist(open, 0);
        console2.log("unlist pay", essentialPaid);
        uint256 lp = vault.liquidate(40, 0);
        console2.log("liquidate #1 pay", lp);
        essentialPaid += lp;
        (r, e) = vault.budget();
        console2.log("essential budget after unlist + liquidate", e);
        console2.log("idle packs left, loose shapes left", vault.idlePacks().length, vault.looseShapeCount());
        // A keeper asking for any pay is now refused; the work is only done unpaid.
        vm.expectRevert();
        vault.liquidate(40, 1e12);
        vm.stopPrank();
        console2.log("essential paid in total vs unwind charge alice paid", essentialPaid, rc);
        assertEq(e, 0, "essential budget empty after one exit");
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
        vault.restock(6, 3, 0);
        vault.list(6, 0);
        vm.stopPrank();
        uint256[] memory open = vault.openListings();
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
        uint256 pay = vault.unlist(one, 0);
        console2.log("t0: unlist 1 at maxima, routine pay", pay);
        vault.startWindDown();
        one[0] = open[1];
        pay = vault.unlist(one, 0);
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
