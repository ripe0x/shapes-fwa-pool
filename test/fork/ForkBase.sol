// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {IShapes, IShapePacks, IFWAV2, IFloorOracle} from "../../src/interfaces/External.sol";

/// @dev Sends ETH by self-destruct: arrives with no call, as FWA's forceSafeTransferETH can.
contract ForceSender {
    constructor(address payable to) payable {
        selfdestruct(to);
    }
}

interface IOwnable {
    function owner() external view returns (address);
}

interface IOracleAdmin {
    function setFloor(address collection, uint256 askPrice) external;
}

interface IFwaAdmin {
    function setUint(uint256 key, uint256 value) external;
    function kickListing(uint256 listingId) external;
    function setAddr(uint256 key, address value) external;
}

/// @notice Mainnet fork at a pinned block with the real FWA, rewards, oracle, Shapes, ShapePacks
///         and token pool. Nothing is mocked: other parties act through their real entry points
///         (the oracle owner sets a floor, FWA's owner sets a fee, a purchaser settles).
abstract contract ForkBase is Test {
    uint256 constant BLOCK = 26_424_971; // queue empty, outside blackout, pack quote 31 h old
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint256 constant INTERVAL = 12 hours;
    uint256 constant BLACKOUT = 11 hours + 45 minutes;
    uint256 constant B = 0.0363 ether;

    PackVault vault;
    uint256 preexisting;
    address guardian = makeAddr("pack-vault-test-guardian");
    address admin = makeAddr("pack-vault-test-admin");
    address keeper = makeAddr("pack-vault-test-keeper");
    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");

    function setUp() public virtual {
        vm.createSelectFork("mainnet", BLOCK);
        // Well-known labels map to real mainnet addresses, some with EIP-7702 sweepers. Every
        // test actor must be a clean wallet.
        address[5] memory actors = [guardian, admin, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0, "test actor has code on mainnet");
            assertEq(actors[i].balance, 0, "test actor has mainnet balance");
        }
        // Real fee environment, so every ETH flow carries its real gas price.
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, defaultParams());
        preexisting = address(vault).balance - 0.01 ether; // ETH already at the deploy address
        vm.deal(alice, 50 ether);
        vm.deal(bob, 50 ether);
        vm.deal(keeper, 1 ether);
    }

    function defaultParams() internal pure returns (PackVault.Params memory p) {
        p.minEdgeBps = 100;
        p.bufferBps = 0;
        p.distributionBps = 0;
        p.keeperPremiumBps = 1_000;
        p.maxTip = 0.05 gwei;
        p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200;
        p.packUnitsMask = uint64(1) << 3;
        p.gasCeiling = 5 gwei;
        p.maxPositions = 150;
        p.reserve = 0.05 ether;
        p.tvlCap = 100 ether;
        p.opGasCap = 15_000_000;
    }

    /// @dev Warp to the next FWA purchase blackout (no new acquisitions can open).
    function toBlackout() internal {
        uint256 t = block.timestamp;
        uint256 start = t - t % INTERVAL + BLACKOUT;
        if (t >= start) start += INTERVAL;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
    }

    /// @dev Warp out of the blackout into the next open interval.
    function toOpen() internal {
        uint256 t = block.timestamp;
        uint256 next = t - t % INTERVAL + INTERVAL + 60;
        vm.warp(next);
        vm.roll(block.number + (next - t) / 12);
    }

    function checkpoint() internal {
        vm.prank(keeper);
        vault.checkpoint();
    }

    function setPackAsk(uint256 ask) internal {
        address oracle = FWA.floorOracle();
        vm.prank(IOwnable(oracle).owner());
        IOracleAdmin(oracle).setFloor(address(PACKS), ask);
    }
}
