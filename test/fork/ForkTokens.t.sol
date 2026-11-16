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

    function test_claimAndConvertTokens() public {
        uint256[] memory ids = vault.openListings();
        uint256 pending;
        for (uint256 i; i < ids.length; ++i) {
            pending += IFWARewards(FWA.rewards()).pendingDepositorTokens(ids[i]);
        }
        assertGt(pending, 0, "the real buyback accrued tokens to our listings");

        vault.harvestTokens(ids);
        uint256 held = token.balanceOf(address(vault));
        assertEq(held, pending, "claimed exactly the pending amount");

        // No sale without a reference price.
        vm.expectRevert(PackVault.Slippage.selector);
        vault.convert(held, 0);

        uint256 ref = _quotePrice();
        PackVault.Params memory p = vault.getParams();
        p.refPrice = uint128(ref);
        vm.prank(admin);
        vault.proposeParams(p);
        vm.warp(block.timestamp + 1 days);
        vault.applyParams();

        // A keeper asking for less than the floor is refused.
        vm.expectRevert(PackVault.Slippage.selector);
        vault.convert(held, held * ref / 1e18 / 2);

        uint256 navEthBefore = address(vault).balance;
        uint256 minOut = held * ref / 1e18 * 9_500 / 10_000;
        uint256 out = vault.convert(held, minOut);
        assertEq(token.balanceOf(address(vault)), 0);
        assertGe(out, minOut);
        // Absolute: within 0.1% of the round-trip reference, so the pool's ~2% round-trip cost
        // sits on the sell side. Value is tiny: one buyback paid 20 listings about 2.5e12 wei.
        assertApproxEqRel(out, held * ref / 1e18, 0.001e18);
        assertLt(out, 1e13);
        assertEq(address(vault).balance - navEthBefore, out - 0, "ETH lands in the vault");
        // Nothing left to sell; the once-per-interval guard is checked after the balance.
        vm.expectRevert(PackVault.Amount.selector);
        vault.convert(1, 0);
    }
}
