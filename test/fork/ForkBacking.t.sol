// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase, IOwnable} from "./ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";

interface IFwaExempt {
    function setOracleExemptCollection(address collection, bool exempt) external;
}

/// @notice Live backing economics with paid mint payback, economic floors, a bounded gas-optimal
///         target, and the real oracle ceiling. No fixed position count or spare-capital spread.
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

    function _setCeiling(uint64 ceiling) internal {
        VaultLib.Params memory p = vault.getParams();
        (p.gasCeiling, p.maxTip) = (ceiling, ceiling < p.maxTip ? ceiling : p.maxTip);
        vm.prank(owner);
        vault.setParams(p);
    }

    function _sqrt(uint256 x) private pure returns (uint256) {
        uint256 low; uint256 high = uint256(1) << 128;
        while (high - low > 1) {
            uint256 middle = (low + high) / 2;
            if (middle <= x / middle) low = middle; else high = middle;
        }
        return low;
    }

    /// An exempt collection uses the live economic target without an oracle ceiling.
    function test_exemptListsAtFloor() public {
        _setCeiling(0.5 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        assertGe(backing, FLOOR, "cash bid coverage floor");
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, 2, 3, 0);
        TestVaultOps.list(vault, 2, 0);
        vm.stopPrank();
        uint256[] memory ids = TestVaultOps.open(vault);
        (,, uint128 posted) = TestVaultOps.position(vault, ids[0]);
        assertGe(posted, FLOOR);
        uint256 distance = posted > backing ? posted - backing : backing - posted;
        assertLt(distance, 30_000, "quantized proposal stays near the economic target");
    }

    /// More available capital does not spread it over a fixed slot count.
    function test_targetIndependentOfPortfolioRoom() public {
        _setCeiling(0.5 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 before,) = vault.edge(3);
        _priced(5 ether);
        (, uint256 afterTarget, bool ok) = vault.edge(3);
        assertTrue(ok);
        assertEq(before, afterTarget, "target depends on economics, not spare capital slots");
    }

    /// A high routine ceiling raises backing above the floor: fewer cycles, less gas per ETH.
    function test_gasOptimalAboveFloorAtHighCeiling() public {
        _setCeiling(1 gwei);
        _exempt(true);
        _priced(1 ether);
        (uint256 k, uint256 backing, bool ok) = vault.edge(3);
        assertTrue(ok);
        // The build repayment target can dominate the gas optimum after gas calibration.
        assertGt(backing, FLOOR);
        VaultLib.Params memory p = vault.getParams();
        uint256 a = k - 1e18;
        uint256 c = (VaultLib.Q_POSITION_SYNC + VaultLib.Q_LISTED + VaultLib.Q_HARVESTED)
            * uint256(p.gasCeiling) * (10_000 + p.payMarkupBps) / 10_000 + 2 * p.workFee;
        uint256 expected = (c + _sqrt(c * c + a * c / 1e18 * 0.03 ether)) * 1e18 / a;
        uint256 price = block.basefee + p.maxTip;
        uint256 build = (VaultLib.Q_PACK + VaultLib.Q_MINT * 3 / 10 + VaultLib.Q_LISTED)
            * price * (10_000 + p.payMarkupBps) / 10_000 + 2 * p.workFee + SHAPES.mintFee() * 3 / 10;
        uint256 cycle = (VaultLib.Q_POSITION_SYNC + VaultLib.Q_LISTED + VaultLib.Q_HARVESTED)
            * price * (10_000 + p.payMarkupBps) / 10_000 + 2 * p.workFee;
        uint256 payback = ((build + cycle) * 1e18 + a - 1) / a;
        if (payback > expected) expected = payback;
        if (FLOOR > expected) expected = FLOOR;
        assertEq(backing, expected, "independent integer optimum and build-payback target");
    }
}
