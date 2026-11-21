// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
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
    function setOracleExemptCollection(address collection, bool exempt) external;
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
    uint256 constant UNITS = 6; // the 0.06 ETH recipe: one 0.05 and one 0.01 Shape
    uint256 constant P = 0.06 ether;
    uint256 constant FEE_PER_PACK = 0.002 ether; // two paid primary mints at 0.001

    PackVault vault;
    uint256 preexisting;
    address owner = makeAddr("pack-vault-test-admin"); // one role (D59)
    address keeper = makeAddr("pack-vault-test-keeper");
    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");

    function setUp() public virtual {
        vm.createSelectFork("mainnet", BLOCK);
        // Well-known labels map to real mainnet addresses, some with EIP-7702 sweepers. Every
        // test actor must be a clean wallet.
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0, "test actor has code on mainnet");
            assertEq(actors[i].balance, 0, "test actor has mainnet balance");
        }
        // Real fee environment, so every ETH flow carries its real gas price.
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        // FWA's owner exempted ShapePacks from the floor cap after this block (live since D62):
        // the same real admin call, made before anything lists.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, defaultParams(), 0.01 ether);
        preexisting = address(vault).balance - 0.01 ether; // ETH already at the deploy address
        vm.deal(alice, 50 ether);
        vm.deal(bob, 50 ether);
        vm.deal(keeper, 1 ether);
    }

    function defaultParams() internal pure returns (VaultLib.Params memory p) {
        p.minEdgeBps = 100;
        p.bufferBps = 0;
        p.distributionBps = 0;
        p.payMarkupBps = 1_000;
        p.maxTip = 0.05 gwei;
        p.workFee = 0.00002 ether;
        p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200;
        p.packUnitsMask = uint64(1) << UNITS;
        p.gasCeiling = 5 gwei;
        p.essentialCeiling = 5 gwei;

        p.reserve = 0.05 ether;
        p.tvlCap = 100 ether;
        p.routineCap = 0.3 ether; // bytecode maxima: these suites test mechanics, not budgets
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;
    }

    /// @dev Owner sets caps and pay limits (everything else unchanged); the tip follows a lower ceiling.
    function lowerTo(uint128 tvl, uint64 ceiling, uint64 fee) internal {
        VaultLib.Params memory q = vault.getParams();
        (q.tvlCap, q.gasCeiling, q.essentialCeiling, q.workFee) = (tvl, ceiling, ceiling, fee);
        if (q.maxTip > ceiling) q.maxTip = ceiling;
        vm.prank(owner);
        vault.setParams(q);
    }

    /// @dev Owner sets the routine and essential budget caps.
    function setCaps(uint64 routine, uint64 essential) internal {
        VaultLib.Params memory q = vault.getParams();
        (q.routineCap, q.essentialCap) = (routine, essential);
        vm.prank(owner);
        vault.setParams(q);
    }

    /// @dev Warp to the next FWA purchase blackout (no new acquisitions can open).
    /// @dev vm.getBlockTimestamp, not block.timestamp: via_ir may reuse a timestamp read before an
    ///      earlier vm.warp in the same test.
    function toBlackout() internal {
        uint256 t = vm.getBlockTimestamp();
        uint256 start = t - t % INTERVAL + BLACKOUT;
        if (t >= start) start += INTERVAL;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
    }

    /// @dev Warp out of the blackout into the next open interval.
    function toOpen() internal {
        uint256 t = vm.getBlockTimestamp();
        uint256 next = t - t % INTERVAL + INTERVAL + 60;
        vm.warp(next);
        vm.roll(block.number + (next - t) / 12);
    }

    /// @dev Backing a new 0.06 ETH listing posts now (VaultLib.edge), at the vault's parameters.
    function B() internal view returns (uint256 backing) {
        (, backing,) = vault.edge(UNITS);
    }

    function checkpoint() internal {
        vm.prank(keeper);
        TestVaultOps.checkpoint(vault, 0);
    }

    function setPackAsk(uint256 ask) internal {
        address oracle = FWA.floorOracle();
        vm.prank(IOwnable(oracle).owner());
        IOracleAdmin(oracle).setFloor(address(PACKS), ask);
    }
}
