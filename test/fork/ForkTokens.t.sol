// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {
    IShapes, IShapePacks, IFWAV2, IFWARewards, IFWAToken, IPoolManager, PoolKey, SwapParams
} from "../../src/interfaces/External.sol";

/// @notice FWA token rewards end to end: our listings are live when a real buyback transaction
///         (replayed as its original call) routes tokens to depositors; the vault claims them and
///         sells through the token's v4 pool. NAV ignores tokens until ETH arrives.
contract ForkTokensTest is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint256 constant BUYBACK_BLOCK = 26_423_454;

    PackVault vault;
    address admin = makeAddr("tok-admin");
    IFWAToken token;
    PoolKey key;

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    receive() external payable {}

    function setUp() public {
        string memory fx = vm.readFile("test/fixtures/buyback.json");
        vm.createSelectFork("mainnet", vm.parseJsonBytes32(fx, ".tx"));
        assertEq(block.number, BUYBACK_BLOCK);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        vm.fee(0.1 gwei);
        vm.txGasPrice(0.15 gwei);
        token = IFWAToken(FWA.token());
        key = token.poolKey();

        PackVault.Params memory p;
        p.minEdgeBps = 100;
        p.keeperPremiumBps = 1_000;
        p.maxTip = 0.05 gwei;
        p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200;
        p.clipSlippageBps = 500;
        p.packUnitsMask = uint64(1) << 3;
        p.gasCeiling = 1.5 gwei;
        p.maxPositions = 150;
        p.tvlCap = 100 ether;
        p.opGasCap = 3_000_000;
        p.clipMax = type(uint128).max;
        vm.deal(address(this), 5 ether);
        vault = new PackVault{value: 2 ether}(FWA, SHAPES, PACKS, makeAddr("tok-guardian"), admin, 1 days, p);
        vault.restock(20, 3);
        vault.list(20);

        // The real buyback, replayed as its original self-call (EIP-7702 delegated sender).
        address from = vm.parseJsonAddress(fx, ".from");
        bytes memory input = vm.parseJsonBytes(fx, ".input");
        vm.txGasPrice(vm.parseJsonUint(fx, ".gasPrice"));
        vm.prank(from, from);
        (bool ok,) = vm.parseJsonAddress(fx, ".to").call(input);
        assertTrue(ok, "real buyback replays");
        vm.txGasPrice(0.15 gwei);
    }

    function _quotePrice() internal returns (uint256 weiPer1e18) {
        // Reference from a real round trip in a snapshot: sell price per 1e18 tokens.
        uint256 snap = vm.snapshotState();
        uint256 got = abi.decode(IPoolManager(token.poolManager()).unlock(abi.encode(true, 0.01 ether)), (uint256));
        uint256 back = abi.decode(IPoolManager(token.poolManager()).unlock(abi.encode(false, got)), (uint256));
        vm.revertToState(snap);
        weiPer1e18 = back * 1e18 / got;
    }

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        IPoolManager m = IPoolManager(token.poolManager());
        (bool buy, uint256 amountIn) = abi.decode(data, (bool, uint256));
        int256 delta = m.swap(
            key,
            SwapParams({
                zeroForOne: buy,
                amountSpecified: -int256(amountIn),
                sqrtPriceLimitX96: buy
                    ? uint160(4_295_128_740)
                    : uint160(1_461_446_703_485_210_103_287_273_052_203_988_822_378_723_970_341)
            }),
            ""
        );
        int128 a0 = int128(delta >> 128);
        int128 a1 = int128(delta);
        if (buy) {
            m.settle{value: uint256(uint128(-a0))}();
            m.take(key.currency1, address(this), uint256(uint128(a1)));
            return abi.encode(uint256(uint128(a1)));
        }
        m.sync(key.currency1);
        token.transfer(address(m), uint256(uint128(-a1)));
        m.settle();
        m.take(address(0), address(this), uint256(uint128(a0)));
        return abi.encode(uint256(uint128(a0)));
    }

    function _pending(uint256[] memory ids) internal view returns (uint256 sum) {
        for (uint256 i; i < ids.length; ++i) {
            sum += IFWARewards(FWA.rewards()).pendingDepositorTokens(ids[i]);
        }
    }

    function _setParams(uint256 ref, uint256 clip) internal {
        PackVault.Params memory p = vault.getParams();
        if (ref != 0) p.refPrice = uint128(ref);
        p.clipMax = uint128(clip);
        vm.prank(admin);
        vault.proposeParams(p);
        vm.warp(block.timestamp + 1 days);
        vault.applyParams();
    }

    function _nextInterval() internal {
        vm.warp(block.timestamp + 12 hours);
    }

    /// Active rewards: one paid-only-if-worth-it call claims and sells; NAV gets every wei.
    function test_convertClaimsAndSellsActiveRewards() public {
        uint256[] memory ids = vault.openListings();
        uint256 pending = _pending(ids);
        assertGt(pending, 0, "the real buyback accrued tokens to our listings");
        uint256 ref = _quotePrice();
        _setParams(ref, type(uint128).max);

        uint256 vBefore = address(vault).balance;
        uint256 kBefore = address(this).balance;
        uint256 minOut = pending * ref / 1e18 * 9_500 / 10_000;
        uint256 out = vault.convert(ids, type(uint256).max, minOut);
        assertEq(token.balanceOf(address(vault)), 0, "claimed exactly the pending amount and sold it");
        assertEq(_pending(ids), 0);
        assertApproxEqRel(out, pending * ref / 1e18, 0.001e18);
        // Dust: pay would exceed 25% of 2.5e12 wei, so the sale is unpaid and NAV keeps all of it.
        assertEq(address(this).balance, kBefore, "dust sale unpaid");
        assertEq(address(vault).balance - vBefore, out);
    }

    /// No reference price: nothing is claimed or sold; rewards stay pending in FWA.
    function test_noReferencePricePreservesRewards() public {
        uint256[] memory ids = vault.openListings();
        uint256 pending = _pending(ids);
        vm.expectRevert(PackVault.Slippage.selector);
        vault.convert(ids, type(uint256).max, 0);
        assertEq(_pending(ids), pending);
        assertEq(token.balanceOf(address(vault)), 0);
    }

    /// A failed sale (caller's minOut above what the pool gives) reverts whole; a retry with a
    /// correct quote in the same interval succeeds.
    function test_failedSaleThenRetry() public {
        uint256[] memory ids = vault.openListings();
        uint256 pending = _pending(ids);
        uint256 ref = _quotePrice();
        _setParams(ref, type(uint128).max);
        vm.expectRevert(PackVault.Slippage.selector);
        vault.convert(ids, type(uint256).max, pending * ref / 1e18 * 2);
        assertEq(_pending(ids), pending, "nothing moved");
        uint256 out = vault.convert(ids, type(uint256).max, pending * ref / 1e18 * 9_500 / 10_000);
        assertGt(out, 0);
    }

    /// Settled credit and a stale id: a listing removed after the keeper looked must not block the
    /// credit its removal created, and the other listings are claimed on the next pass.
    function test_staleIdDoesNotBlockCredit() public {
        uint256[] memory ids = vault.openListings();
        uint256 ref = _quotePrice();
        _setParams(ref, type(uint128).max);
        uint256 pendingAll = _pending(ids);
        vm.prank(makeAddr("tok-guardian"));
        vault.startWindDown();
        uint256[] memory one = new uint256[](1);
        one[0] = ids[0];
        uint256 firstPending = IFWARewards(FWA.rewards()).pendingDepositorTokens(ids[0]);
        vault.unlist(one); // its pending tokens become the vault's token credit
        assertEq(IFWARewards(FWA.rewards()).tokenCredit(address(vault)), firstPending, "credit on removal");

        // The keeper's stale list still includes ids[0]: FWA's batch claim reverts, the credit is
        // still withdrawn and sold.
        uint256 out = vault.convert(ids, type(uint256).max, firstPending * ref / 1e18 * 9_500 / 10_000);
        assertGt(out, 0);
        assertEq(IFWARewards(FWA.rewards()).tokenCredit(address(vault)), 0);
        assertEq(_pending(ids), pendingAll - firstPending, "others still pending, not lost");

        // Next interval, refreshed ids: the rest is claimed and sold.
        _nextInterval();
        uint256[] memory rest = vault.openListings();
        uint256 left = _pending(rest);
        vault.convert(rest, type(uint256).max, left * ref / 1e18 * 9_500 / 10_000);
        assertEq(_pending(rest), 0);
        assertEq(token.balanceOf(address(vault)), 0);
    }

    /// Above clipMax: one sale per interval sells at most clipMax; the remainder waits for the
    /// next interval instead of making every attempt revert.
    function test_balanceAboveClipMax() public {
        uint256[] memory ids = vault.openListings();
        uint256 pending = _pending(ids);
        uint256 ref = _quotePrice();
        _setParams(ref, pending / 2);
        uint256 clip = pending / 2;
        vault.convert(ids, type(uint256).max, clip * ref / 1e18 * 9_500 / 10_000);
        assertEq(token.balanceOf(address(vault)), pending - clip, "only clipMax sold");
        vm.expectRevert(PackVault.TooEarly.selector);
        vault.convert(new uint256[](0), type(uint256).max, 0);
        _nextInterval();
        uint256 rest = pending - clip;
        vault.convert(new uint256[](0), type(uint256).max, rest * ref / 1e18 * 9_500 / 10_000);
        assertEq(token.balanceOf(address(vault)), 0);
    }

    /// Zero rewards: nothing to claim or sell reverts without moving anything.
    function test_zeroRewards() public {
        uint256 ref = _quotePrice();
        _setParams(ref, type(uint128).max);
        vm.expectRevert(PackVault.Amount.selector);
        vault.convert(new uint256[](0), type(uint256).max, 0);
    }
}
