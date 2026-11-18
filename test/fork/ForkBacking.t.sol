// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable} from "./ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";

interface IFwaExempt {
    function setOracleExemptCollection(address collection, bool exempt) external;
}

/// @notice Backing rule (D62) on the real FWA, Shapes and ShapePacks: floor max(P / d, P / (1 - s)),
///         build repayment at the current price, gas-optimal above it only at high ceilings, spare capital spread when the position
///         count binds, FWA's oracle cap unless the collection is exempt. No mocks.
contract ForkBackingTest is ForkBase {
    uint256 constant FLOOR = 33_333_333_333_333_334; // ceil(0.03 ETH x 10,000 / 9,000): purchasers prefer the bid

    function _exempt(bool on) internal {
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaExempt(address(FWA)).setOracleExemptCollection(address(PACKS), on);
        assertEq(FWA.oracleExemptCollections(address(PACKS)), on);
    }

    function _priced(uint256 escrow) internal {
        uint256 gross = vault.requestCharge() + escrow;
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
    }

    function _setPositions(uint96 maxPositions, uint64 ceiling) internal {
        VaultLib.Params memory p = vault.getParams();
        (p.maxPositions, p.gasCeiling, p.maxTip) = (maxPositions, ceiling, ceiling < p.maxTip ? ceiling : p.maxTip);
        vm.prank(owner);
        vault.setParams(p);
    }

    /// Capital binds (150 slots, 1 ETH): exempt, the vault lists at the floor without any oracle.
    function test_exemptListsAtFloor() public {
        _setPositions(150, 0.5 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        assertEq(backing, FLOOR, "floor: a purchaser takes the bid, so the pack keeps cycling");
        vm.startPrank(keeper);
        vault.restock(2, 3, 0);
        vault.list(2, 0);
        vm.stopPrank();
        uint256[] memory ids = vault.openListings();
        (,, uint128 posted) = vault.positions(ids[0]);
        assertEq(posted, FLOOR);
    }

    /// The position count binds (3 slots, 1 ETH): spare capital is spread as backing; exempt,
    /// no cap applies. With the oracle in force, the cap less the buffer limits it.
    function test_spareCapitalDoesNotIncreaseBacking() public {
        _setPositions(3, 0.5 gwei);
        _priced(1 ether);
        (, uint256 capped,) = vault.edge(3);
        assertEq(capped, 0.0363 ether, "oracle cap 0.033 x 1.10 binds when not exempt");
        _exempt(true);
        (, uint256 spread, bool ok) = vault.edge(3);
        assertTrue(ok);
        // Additional vault instances can accept new capital, so spare ETH need
        // not push FWA backing higher merely because local slots are full.
        assertEq(spread, FLOOR, "no artificial backing spread on a full vault");
        vm.startPrank(keeper);
        vault.restock(3, 3, 0);
        vault.list(3, 0);
        vm.stopPrank();
        assertEq(vault.openListings().length, 3, "all three listed at the spread backing");
    }

    /// A high routine ceiling raises backing above the floor: fewer cycles, less gas per ETH.
    function test_gasOptimalAboveFloorAtHighCeiling() public {
        _setPositions(150, 1 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        // (c + sqrt(c^2 + a c P)) / a, c = 620k x 1 gwei x 1.10 + 2 x 0.00002, a = k - 1.
        assertGt(backing, 0.045 ether);
        assertLt(backing, 0.05 ether);
    }
}
