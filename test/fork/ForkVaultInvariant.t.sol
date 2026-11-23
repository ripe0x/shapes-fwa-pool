// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {Test} from "forge-std/Test.sol";
import {ForkBase, ForceSender} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";

/// @dev Drives the vault through holder, keeper and donor actions on the real mainnet fork. No
///      FWA selections happen here (those need replayed VRF transactions, see ForkSelection).
contract VaultHandler is Test {
    PackVault immutable vault;
    address immutable keeper;
    address[3] actors;
    uint256 constant INTERVAL = 12 hours;
    uint256 constant BLACKOUT = 11 hours + 45 minutes;

    uint256 public mintFeesPaid; // ETH that left NAV by design: Shapes mint fees
    uint256 public donated;
    uint256 public calls;

    constructor(PackVault v, address k, address[3] memory a) {
        vault = v;
        keeper = k;
        actors = a;
    }

    function _actor(uint256 seed) internal view returns (address) {
        return actors[seed % actors.length];
    }

    function deposit(uint256 seed, uint256 amount) external {
        address a = _actor(seed);
        amount = bound(amount, 0.01 ether, 3 ether);
        if (a.balance < amount) return;
        vm.prank(a);
        try vault.deposit{value: amount}() {} catch {}
        ++calls;
    }

    function cancel(uint256 seed) external {
        vm.prank(_actor(seed));
        try vault.cancelDeposit() {} catch {}
        ++calls;
    }

    function requestRedeem(uint256 seed, uint256 frac) external {
        address a = _actor(seed);
        uint256 bal = vault.shareBalance(a);
        if (bal == 0) return;
        uint256 amount = bal * bound(frac, 1, 100) / 100;
        vm.prank(a);
        try vault.requestRedeem{value: 0.01 ether}(amount) {} catch {}
        ++calls;
    }

    function claim(uint256 seed) external {
        vm.prank(_actor(seed));
        try vault.claim() {} catch {}
        ++calls;
    }

    function checkpoint() external {
        uint256 t = block.timestamp;
        uint256 start = t - t % INTERVAL + BLACKOUT;
        if (t >= start) start += INTERVAL;
        vm.warp(start + 60);
        uint256 witness = TestVaultOps.witness(vault);
        vm.prank(keeper);
        try vault.checkpoint(witness, 0) {} catch {}
        // Leave the blackout so listing-side actions see an open interval next.
        vm.warp(start - BLACKOUT + INTERVAL + 60);
        ++calls;
    }

    function build(uint256 n) external {
        n = bound(n, 1, 4);
        vm.startPrank(keeper);
        // Build mints and lists at once; each six-unit pack mints two Shapes at 0.001 ETH.
        try vault.build(6, TestVaultOps.proposals(vault, n, 6), 0) {
            mintFeesPaid += n * 0.002 ether;
        } catch {}
        vm.stopPrank();
        ++calls;
    }

    function relist() external {
        vm.startPrank(keeper);
        // Relist whatever idle (returned) packs exist; no mint, so mintFeesPaid is unchanged.
        try vault.list(TestVaultOps.proposals(vault, 4, 6), 0) {} catch {}
        vm.stopPrank();
        ++calls;
    }

    function unlist() external {
        uint256[] memory ids = TestVaultOps.open(vault);
        if (ids.length == 0) return;
        vm.prank(keeper);
        try vault.unlist(ids, 0) {} catch {}
        ++calls;
    }

    function liquidate(uint256 n) external {
        vm.prank(keeper);
        try vault.liquidate(bound(n, 1, 10), 0) {} catch {}
        ++calls;
    }

    function donate(uint256 amount) external {
        amount = bound(amount, 1, 0.5 ether);
        vm.deal(address(this), amount);
        new ForceSender{value: amount}(payable(address(vault)));
        donated += amount;
        ++calls;
    }
}

contract ForkVaultInvariantTest is ForkBase {
    VaultHandler handler;
    address carol = makeAddr("pack-vault-test-carol");

    function setUp() public override {
        super.setUp();
        assertEq(carol.code.length, 0); assertEq(carol.balance, 0);
        vm.deal(carol, 50 ether);
        handler = new VaultHandler(vault, keeper, [alice, bob, carol]);
        targetContract(address(handler));
        // One fresh fuzz sender: the fuzzer otherwise picks addresses it has seen (the holders, the
        // vault itself) as transaction senders, and funding or charging a sender for gas then moves
        // a tracked balance outside the vault's accounting.
        address sender = makeAddr("pack-vault-test-fuzz-sender");
        assertEq(sender.code.length, 0); assertEq(sender.balance, 0);
        targetSender(sender);
    }

    /// INV01: the vault always holds every amount it owes outside the strategy.
    function invariant_reservesCovered() public view {
        uint256 owed = vault.pendingDepositTotal() + vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal();
        assertGe(address(vault).balance, owed);
    }

    /// INV02: holders' unconverted claims never exceed the reserve backing them.
    function invariant_claimsWithinReserves() public view {
        address[3] memory a = [alice, bob, carol];
        uint256 claimable;
        for (uint256 i; i < a.length; ++i) {
            claimable += vault.claimableEth(a[i]);
        }
        // Settled entitlements are tracked as one liability and are all part of the vault balance.
        assertEq(claimable, vault.claimableTotal(), "claimable total tracks every holder");
        assertGe(address(vault).balance, claimable + vault.redemptionReserve() + vault.distributionReserve());
    }

    /// INV03: shares are conserved: supply = dead + holders' live shares + locked shares, up to
    ///        per-holder rounding of lazily converted deposits and redemption remainders.
    function invariant_sharesConserved() public view {
        address[3] memory a = [alice, bob, carol];
        uint256 sum = vault.DEAD_SHARES() + vault.lockedShares();
        for (uint256 i; i < a.length; ++i) {
            sum += vault.shareBalance(a[i]);
        }
        assertApproxEqAbs(sum, vault.totalShares(), 10);
        assertLe(sum, vault.totalShares(), "never more shares owned than issued");
    }

    /// INV04: with no selections, value only leaves NAV as Shapes mint fees and keeper gas pay:
    ///        everything paid in equals assets held plus those two expenses, to the wei.
    function invariant_valueConserved() public view {
        // No loose Shapes (direct-mint recipe); each six-unit pack holds 0.06 ETH of value.
        uint256 assets = address(vault).balance + TestVaultOps.idle(vault).length * (UNITS * 0.01 ether);
        uint256[] memory ids = TestVaultOps.open(vault);
        for (uint256 i; i < ids.length; ++i) {
            (, uint64 units, uint128 backing) = TestVaultOps.position(vault, ids[i]);
            assets += backing + uint256(units) * 0.01 ether;
        }
        // Paid in: seed, pre-existing dust, holder deposits net of cancels and claims, donations.
        // Tracked as: assets + mint fees == seed + preexisting + net holder inflow + donations.
        // Signed: a holder can end above the 50 ETH start when the vault gains (audit V1).
        int256 netIn = int256(0.01 ether + preexisting + handler.donated());
        address[3] memory a = [alice, bob, carol];
        for (uint256 i; i < a.length; ++i) {
            netIn += int256(50 ether) - int256(a[i].balance); // holder balances only move through the vault
        }
        uint256 keeperPay = keeper.balance - 1 ether; // the keeper's balance moves only by vault pay
        assertEq(int256(assets + handler.mintFeesPaid() + keeperPay), netIn, "every wei is held, a mint fee or keeper pay");
    }
}
