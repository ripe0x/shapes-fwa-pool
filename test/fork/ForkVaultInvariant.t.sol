// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

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
        try vault.requestRedeem(amount) {} catch {}
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
        vm.prank(keeper);
        try vault.checkpoint() {} catch {}
        // Leave the blackout so listing-side actions see an open interval next.
        vm.warp(start - BLACKOUT + INTERVAL + 60);
        ++calls;
    }

    function restockAndList(uint256 n) external {
        n = bound(n, 1, 4);
        uint256 loose = vault.looseShapeCount();
        uint256 before = address(vault).balance;
        vm.startPrank(keeper);
        try vault.restock(n, 3) {
            uint256 mints = loose >= 3 * n ? 0 : (3 * n - loose + 9) / 10;
            mintFeesPaid += mints * 0.001 ether;
            before;
        } catch {}
        try vault.list(n) {} catch {}
        vm.stopPrank();
        ++calls;
    }

    function unlist() external {
        uint256[] memory ids = vault.openListings();
        if (ids.length == 0) return;
        vm.prank(keeper);
        try vault.unlist(ids) {} catch {}
        ++calls;
    }

    function liquidate(uint256 n) external {
        vm.prank(keeper);
        try vault.liquidate(bound(n, 1, 10)) {} catch {}
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
        vm.deal(carol, 50 ether);
        handler = new VaultHandler(vault, keeper, [alice, bob, carol]);
        targetContract(address(handler));
    }

    /// INV01: the vault always holds every amount it owes outside the strategy.
    function invariant_reservesCovered() public view {
        uint256 owed = vault.pendingDepositTotal() + vault.redemptionReserve() + vault.distributionReserve();
        assertGe(address(vault).balance, owed);
    }

    /// INV02: holders' unconverted claims never exceed the reserve backing them.
    function invariant_claimsWithinReserves() public view {
        address[3] memory a = [alice, bob, carol];
        uint256 claimable;
        for (uint256 i; i < a.length; ++i) {
            claimable += vault.claimableEth(a[i]);
        }
        // claimableEth is credited out of the reserves, so it is part of the vault balance.
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
        uint256 assets = address(vault).balance + vault.looseShapeCount() * 0.01 ether
            + vault.idlePacks().length * 0.03 ether;
        uint256[] memory ids = vault.openListings();
        for (uint256 i; i < ids.length; ++i) {
            (,, uint128 backing) = vault.positions(ids[i]);
            assets += backing + 0.03 ether;
        }
        // Paid in: seed, pre-existing dust, holder deposits net of cancels and claims, donations.
        // Tracked as: assets + mint fees == seed + preexisting + net holder inflow + donations.
        uint256 netIn = 0.01 ether + preexisting + handler.donated();
        address[3] memory a = [alice, bob, carol];
        for (uint256 i; i < a.length; ++i) {
            netIn += 50 ether - a[i].balance; // holder balances only move through the vault
        }
        uint256 keeperPay = keeper.balance - 1 ether; // the keeper's balance moves only by vault pay
        assertEq(assets + handler.mintFeesPaid() + keeperPay, netIn, "every wei is held, a mint fee or keeper pay");
    }
}
