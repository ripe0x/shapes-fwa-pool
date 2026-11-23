// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase, IOwnable} from "./ForkBase.sol";
import {VaultLib} from "../../src/VaultLib.sol";

interface IFwaExempt {
    function setOracleExemptCollection(address collection, bool exempt) external;
}

/// @notice Live backing economics for the direct-mint recipe. Backing is a linear target
///         `floor_10000((P - margin) x 10,000 / bid)` where `margin = 0.0003 ETH +
///         160,000 x PURCHASER_GAS_PRICE` (the purchaser's redeem gas priced at a fixed 2 gwei
///         bound, not the keeper's gas ceiling) and `bid = max(settlementDiscountBps,
///         tokenSettlementDiscountBps)`, capped by the oracle only when ShapePacks is not
///         oracle-exempt. The old sqrt gas-optimum and the 0.03/0.9 cash-bid floor are gone
///         (VaultLib._backingTerms, direct-mint rewrite), so those assertions are replaced by the
///         linear-target checks below.
contract ForkBackingTest is ForkBase {
    // ceil(P x 10,000 / 9,500): a keep never loses at FWA's immutable 5% settlement-fee cap.
    uint256 constant FLOOR = 63_157_894_736_842_106;

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
        (p.gasCeiling, p.essentialCeiling, p.maxTip) =
            (ceiling, ceiling, ceiling < p.maxTip ? ceiling : p.maxTip);
        vm.prank(owner);
        vault.setParams(p);
    }

    function _bid() internal view returns (uint256) {
        uint256 a = FWA.settlementDiscountBps();
        uint256 b = FWA.tokenSettlementDiscountBps();
        return a > b ? a : b;
    }

    /// @dev The exact economic target `edge` posts for an exempt collection (no oracle ceiling).
    function _target(uint256 units) internal view returns (uint256) {
        uint256 value = units * 0.01 ether;
        // Redeem gas is priced at the owner-set purchaserGasPrice (default 2 gwei), not the keeper's
        // gas ceiling, so the target no longer moves with the ceiling.
        (, uint256 shapes) = VaultLib.makeup(units);
        VaultLib.Params memory p = vault.getParams();
        uint256 margin = uint256(p.keepAdvantage)
            + (p.purchaserRedeemPack + shapes * p.purchaserRedeemShape) * p.purchaserGasPrice;
        if (value <= margin || _bid() == 0) return 0;
        return (value - margin) * 10_000 / _bid() / 10_000 * 10_000; // floored to 10,000 wei
    }

    /// An exempt collection lists at the live linear target with no oracle ceiling, above the
    /// keep-never-loses floor, and building posts exactly that backing.
    function test_exemptListsAtTarget() public {
        _setCeiling(0.5 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 backing, bool ok) = vault.edge(UNITS);
        assertTrue(ok);
        assertEq(backing, _target(UNITS), "edge posts the live linear target");
        assertGe(backing, FLOOR, "at least ceil(P / 0.95)");
        vm.prank(keeper);
        TestVaultOps.restock(vault, 2, UNITS, 0);
        uint256[] memory ids = TestVaultOps.open(vault);
        (,, uint128 posted) = TestVaultOps.position(vault, ids[0]);
        assertGe(posted, FLOOR);
        uint256 distance = posted > backing ? posted - backing : backing - posted;
        assertLt(distance, 30_000, "quantized proposal stays near the economic target");
    }

    /// The target depends on economics, not on how much spare capital the vault holds.
    function test_targetIndependentOfPortfolioRoom() public {
        _setCeiling(0.5 gwei);
        _exempt(true);
        _priced(1 ether);
        (, uint256 before,) = vault.edge(UNITS);
        _priced(5 ether);
        (, uint256 afterTarget, bool ok) = vault.edge(UNITS);
        assertTrue(ok);
        assertEq(before, afterTarget, "target depends on economics, not spare capital slots");
    }

    /// The purchaser-redeem margin is priced at a fixed 2 gwei bound (PURCHASER_GAS_PRICE), so the
    /// linear target no longer moves with the keeper's gas ceiling: unlike the retired sqrt optimum
    /// (which rose with the ceiling) and the earlier gasCeiling-priced margin (which lowered it).
    function test_ceilingDoesNotMoveBacking() public {
        _exempt(true);
        _setCeiling(0.5 gwei);
        _priced(1 ether);
        (, uint256 lowCeil, bool ok0) = vault.edge(UNITS);
        assertTrue(ok0);
        assertEq(lowCeil, _target(UNITS), "linear target at 0.5 gwei");

        _setCeiling(5 gwei);
        (, uint256 highCeil, bool ok1) = vault.edge(UNITS);
        assertTrue(ok1);
        assertEq(highCeil, _target(UNITS), "linear target at 5 gwei");
        assertEq(highCeil, lowCeil, "backing is independent of the keeper gas ceiling");
    }
}
