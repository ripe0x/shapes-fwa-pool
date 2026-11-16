// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {
    IShapes,
    IShapePacks,
    IFWAV2,
    IFWAToken,
    IPoolManager,
    PoolKey,
    SwapParams,
    LISTING_ACTIVE,
    LISTING_WITHDRAWN
} from "../../src/interfaces/External.sol";

/// @notice Phase 0.4: gas and token-route measurements against live mainnet contracts at a pinned
///         block. Every call is the real deployed code; this contract plays the vault as depositor.
///         Results go to sim/out/gas.json for sim/model.py.
contract ForkMeasureTest is Test {
    uint256 constant BLOCK = 26_424_971;
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint160 constant MIN_SQRT_PRICE_PLUS_ONE = 4_295_128_740;
    uint160 constant MAX_SQRT_PRICE_MINUS_ONE = 1_461_446_703_485_210_103_287_273_052_203_988_822_378_723_970_341;

    uint256 constant B = 0.0363 ether; // oracle cap at the pinned block: 0.033 ask x 1.10

    IPoolManager manager;
    PoolKey key;
    string json = "gas";

    function setUp() public {
        vm.createSelectFork("mainnet", BLOCK);
        // Real tx economics: nonzero basefee and gas price, so ETH flows match mainnet.
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vm.deal(address(this), 20 ether);
        SHAPES.setApprovalForAll(address(PACKS), true);
        PACKS.setApprovalForAll(address(FWA), true);
        IFWAToken token = IFWAToken(FWA.token());
        manager = IPoolManager(token.poolManager());
        key = token.poolKey();
    }

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    receive() external payable {}

    /// @dev Every touched contract starts cold, as in a fresh transaction.
    function _cool() internal {
        vm.cool(address(SHAPES));
        vm.cool(address(PACKS));
        vm.cool(address(FWA));
        vm.cool(FWA.rewards());
        vm.cool(FWA.floorOracle());
    }

    /// @dev Mint one 0.1 shape and split it into ten 0.01 shapes: three packs' worth plus one.
    function _shapes() internal returns (uint256[] memory ids) {
        uint256 fee = SHAPES.mintFee();
        uint256 big = SHAPES.mint{value: 0.1 ether + fee}(0.1 ether);
        uint8[] memory outs = new uint8[](10);
        ids = SHAPES.split(big, outs);
    }

    function _pack(uint256[] memory ids, uint256 from) internal returns (uint256) {
        uint256[] memory three = new uint256[](3);
        for (uint256 i; i < 3; ++i) {
            three[i] = ids[from + i];
        }
        return PACKS.createPack(three, new uint32[](9));
    }

    function test_measureInventoryAndListing() public {
        assertEq(FWA.unsettledAcquisitionCount(), 0, "pinned block has an empty queue");
        assertFalse(FWA.isPurchaseBlackout(), "pinned block is outside blackout");
        uint256 fee = SHAPES.mintFee();
        assertEq(fee, 0.001 ether);

        _cool();
        uint256 g = gasleft();
        uint256 big = SHAPES.mint{value: 0.1 ether + fee}(0.1 ether);
        vm.serializeUint(json, "mint_0_1", g - gasleft());
        assertEq(SHAPES.backingOf(big), 0.1 ether);

        _cool();
        uint8[] memory outs = new uint8[](10);
        g = gasleft();
        uint256[] memory ids = SHAPES.split(big, outs);
        vm.serializeUint(json, "split_1_into_10", g - gasleft());
        assertEq(ids.length, 10);

        _cool();
        g = gasleft();
        uint256 packId = _pack(ids, 0);
        vm.serializeUint(json, "create_pack_pull_3", g - gasleft());
        assertEq(PACKS.valueOf(packId), 0.03 ether);

        // Direct-mint pack for comparison: 3 x (0.01 + fee).
        uint32[] memory counts = new uint32[](9);
        counts[0] = 3;
        _cool();
        g = gasleft();
        uint256 minted = PACKS.createPack{value: 3 * (0.01 ether + fee)}(new uint256[](0), counts);
        vm.serializeUint(json, "create_pack_mint_3", g - gasleft());
        assertEq(PACKS.valueOf(minted), 0.03 ether);

        _cool();
        g = gasleft();
        uint256 listingId = FWA.listNFT{value: B}(address(PACKS), packId);
        uint256 listGas = g - gasleft();
        vm.serializeUint(json, "list", listGas);
        (,,,,, uint256 value,,,,, uint8 status) = FWA.listings(listingId);
        assertEq(value, B);
        assertEq(status, LISTING_ACTIVE, "empty queue lists straight into the pool");

        // One cap above the oracle cap reverts: the cap rule is live.
        uint256 second = _pack(ids, 3);
        vm.expectRevert();
        FWA.listNFT{value: B + 1}(address(PACKS), second);

        // Batch of 10 listings in one transaction (vault batch shape).
        uint256[] memory packs10 = new uint256[](10);
        packs10[0] = second;
        packs10[1] = _pack(ids, 6);
        for (uint256 i = 2; i < 10; ++i) {
            uint256[] memory more = _shapes();
            packs10[i] = _pack(more, 0);
        }
        _cool();
        g = gasleft();
        uint256[] memory listed = new uint256[](10);
        for (uint256 i; i < 10; ++i) {
            listed[i] = FWA.listNFT{value: B}(address(PACKS), packs10[i]);
        }
        vm.serializeUint(json, "list_batch_10", g - gasleft());

        // Fees: none accrue without an acquisition at this block, so the claim reverts.
        assertEq(FWA.pendingFees(listingId), 0);
        vm.expectRevert();
        FWA.claimListingFees(listed);

        _cool();
        uint256 balBefore = address(this).balance;
        g = gasleft();
        FWA.withdrawListing(listingId);
        vm.serializeUint(json, "withdraw", g - gasleft());
        assertEq(address(this).balance - balBefore, B, "full backing back, not the crown");
        assertEq(PACKS.ownerOf(packId), address(this));
        (,,,,,,,,,, status) = FWA.listings(listingId);
        assertEq(status, LISTING_WITHDRAWN);

        _cool();
        balBefore = address(this).balance;
        g = gasleft();
        PACKS.redeem(packId);
        uint256 redeemGas = g - gasleft();
        vm.serializeUint(json, "redeem_pack", redeemGas);
        // Absolute amount: a 0.03 pack redeems to exactly 0.03 ETH.
        assertEq(address(this).balance - balBefore, 0.03 ether);

        string memory out = vm.serializeUint(json, "block", BLOCK);
        vm.writeJson(out, "sim/out/gas-fork.json");
    }

    // ---------------------------------------------------------------- token route

    uint256 internal _mode; // 1 buy (ETH in), 2 sell (token in)

    function unlockCallback(bytes calldata data) external returns (bytes memory) {
        require(msg.sender == address(manager), "not manager");
        (bool buy, uint256 amountIn) = abi.decode(data, (bool, uint256));
        int256 delta = manager.swap(
            key,
            SwapParams({
                zeroForOne: buy,
                amountSpecified: -int256(amountIn),
                sqrtPriceLimitX96: buy ? MIN_SQRT_PRICE_PLUS_ONE : MAX_SQRT_PRICE_MINUS_ONE
            }),
            ""
        );
        int128 a0 = int128(delta >> 128);
        int128 a1 = int128(delta);
        if (buy) {
            manager.settle{value: uint256(uint128(-a0))}();
            manager.take(key.currency1, address(this), uint256(uint128(a1)));
            return abi.encode(uint256(uint128(a1)));
        }
        manager.sync(key.currency1);
        IFWAToken(key.currency1).transfer(address(manager), uint256(uint128(-a1)));
        manager.settle();
        manager.take(address(0), address(this), uint256(uint128(a0)));
        return abi.encode(uint256(uint128(a0)));
    }

    function _swap(bool buy, uint256 amountIn) internal returns (uint256 out) {
        out = abi.decode(manager.unlock(abi.encode(buy, amountIn)), (uint256));
    }

    /// @notice Can a contract with no distributor role sell FWA for ETH through the token's v4 pool,
    ///         and what does a round trip cost at increasing size? Can it transfer FWA directly?
    function test_measureTokenRoute() public {
        IFWAToken token = IFWAToken(key.currency1);
        assertEq(key.currency0, address(0), "currency0 is native ETH");
        assertFalse(token.isDistributor(address(this)));
        emit log_named_address("hook", key.hooks);
        emit log_named_uint("lp fee", key.fee);

        uint256[4] memory sizes = [uint256(0.001 ether), 0.01 ether, 0.1 ether, 1 ether];
        for (uint256 i; i < sizes.length; ++i) {
            uint256 snap = vm.snapshotState();
            uint256 tokensOut;
            try this.buyExternal(sizes[i]) returns (uint256 t) {
                tokensOut = t;
            } catch {
                emit log_named_uint("buy reverted at size", sizes[i]);
                continue;
            }
            assertEq(token.balanceOf(address(this)), tokensOut);
            uint256 g = gasleft();
            uint256 ethBack = _swap(false, tokensOut);
            uint256 sellGas = g - gasleft();
            emit log_named_uint("size wei", sizes[i]);
            emit log_named_uint("  round trip bps kept", ethBack * 10_000 / sizes[i]);
            emit log_named_uint("  sell gas", sellGas);
            vm.serializeUint("token", string.concat("roundtrip_bps_", vm.toString(sizes[i])), ethBack * 10_000 / sizes[i]);
            vm.serializeUint("token", "sell_gas", sellGas);
            vm.revertToState(snap);
        }

        // Direct transfer of FWA from a non-distributor contract to an EOA: expected to be locked.
        uint256 t = this.buyExternal(0.01 ether);
        address eoa = makeAddr("holder");
        bool ok;
        try token.transfer(eoa, t) returns (bool r) {
            ok = r;
        } catch {}
        emit log_named_uint("direct transfer succeeded", ok ? 1 : 0);
        string memory out = vm.serializeUint("token", "direct_transfer_ok", ok ? 1 : 0);
        vm.writeJson(out, "sim/out/token-fork.json");
    }

    function buyExternal(uint256 ethIn) external returns (uint256) {
        require(msg.sender == address(this));
        return _swap(true, ethIn);
    }
}
