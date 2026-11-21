// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm} from "forge-std/Vm.sol";
import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";

/// @dev Independent Python replay of a real partial fill and complete wind-down, no FWA selection.
contract ForkPartialReconcileTest is ForkBase {
    string private constant OUT = "sim/out/reconcile-partial-trace.jsonl";
    uint256 private lastKeeper;

    function setUp() public override {
        vm.createSelectFork("mainnet", BLOCK);
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0); assertEq(actors[i].balance, 0);
        }
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei);
        // D62: ShapePacks is oracle-exempt (the real admin call ForkBase makes), so a 0.06 ETH pack
        // lists at its edge backing instead of being clamped to the stale historical floor cap.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        VaultLib.Params memory p = defaultParams();
        p.gasCeiling = 0.5 gwei; p.essentialCeiling = 2 gwei; p.payMarkupBps = 0;
        p.reserve = 0.005 ether; p.tvlCap = 2 ether;
        p.routineCap = 0.03 ether; p.routineRate = 0.0008 ether;
        p.essentialCap = 0; p.essentialRate = 0;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
        preexisting = address(vault).balance - 0.01 ether;
        vm.deal(owner, 1 ether); vm.deal(keeper, 1 ether); vm.deal(alice, 50 ether); vm.deal(bob, 50 ether);
        lastKeeper = keeper.balance;
    }

    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function _snap(string memory step) private {
        ReconcileTrace.snapshot(vault, alice, bob, keeper.balance - lastKeeper, step, OUT);
        lastKeeper = keeper.balance;
    }

    function _listedIds(uint256 count) private returns (uint256[] memory ids) {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        ids = new uint256[](count);
        bytes32 listed = keccak256("NFTListed(uint256,uint256,address,address,uint256,uint256,uint256)");
        uint256 found;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter == address(FWA) && logs[i].topics.length == 4 && logs[i].topics[0] == listed
                && address(uint160(uint256(logs[i].topics[3]))) == address(vault)) {
                assertLt(found, count); ids[found++] = uint256(logs[i].topics[1]);
            }
        }
        assertEq(found, count, "real FWA admission events identify every submitted position");
    }

    function test_reconcilePartialRedemptionAndWindDown() public {
        this.assertGasContext();
        if (vm.exists(OUT)) vm.removeFile(OUT);
        vm.writeLine(OUT, string.concat('{"step":"setup","deployBalance":', vm.toString(address(vault).balance),
            ',"initCursor":', vm.toString(vault.acquisitionCursor()), ',"count":6,"units":', vm.toString(UNITS),
            ',"essentialCap":0,"mintFee":', vm.toString(SHAPES.mintFee()), '}'));
        uint256 ck = vault.requestCharge();
        uint256 gross = Charges.grossFor(vault, 1 ether);
        vm.prank(alice); vault.deposit{value: gross}();
        (,, uint96 deploy,) = vault.pendingDeposits(alice);
        vm.writeLine(OUT, string.concat('{"step":"depositCharge","ck":', vm.toString(ck),
            ',"escrow":1000000000000000000,"charge":', vm.toString(uint256(deploy)), '}'));
        _snap("deposit");
        toBlackout(); checkpoint(); _snap("checkpoint1"); toOpen();

        // Build-and-list six UNITS packs: each mints its Shapes straight into ShapePacks and lists at
        // once (no separate list step). Six fits a 1 ETH deposit at 0.06 ETH value plus backing.
        vm.recordLogs();
        vm.prank(keeper); TestVaultOps.restock(vault, 6, UNITS, 0);
        uint256[] memory builtIds = _listedIds(6);
        uint256[] memory backings = new uint256[](builtIds.length);
        for (uint256 i; i < builtIds.length; ++i) { (,, uint128 b) = TestVaultOps.position(vault, builtIds[i]); backings[i] = b; }
        vm.writeLine(OUT, string.concat('{"step":"buildInputs","count":6,"units":', vm.toString(UNITS),
            ',"ids":', ReconcileTrace.uints(builtIds), ',"backings":', ReconcileTrace.uints(backings), '}'));
        _snap("build");
        uint256 shares = vault.shareBalance(alice);
        ck = vault.requestCharge();
        uint256 unwind = Charges.redeemCharge(vault, shares);
        vm.writeLine(OUT, string.concat('{"step":"redeemCharge","shares":', vm.toString(shares),
            ',"ck":', vm.toString(ck), ',"total":', vm.toString(unwind), '}'));
        vm.prank(alice); vault.requestRedeem{value: unwind}(shares); _snap("redeem");
        toBlackout(); checkpoint(); _snap("partial");
        assertGt(vault.lockedShares(), 0, "real first fill leaves locked shares");
        assertGt(vault.redemptionReserve(), 0.2 ether, "absolute liquid first fill");
        toOpen();
        vm.prank(owner); vault.startWindDown(); _snap("windDown");
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.prank(keeper); vault.unlist(ids, 0); _snap("unlist");
        assertEq(vault.openListingCount(), 0);
        vm.prank(keeper); vault.liquidate(16, 0); _snap("liquidate");
        assertEq(vault.idlePackCount(), 0);
        toBlackout(); checkpoint(); _snap("checkpoint2");
        assertEq(vault.lockedShares(), 0);
        uint256 before = alice.balance;
        vm.prank(alice); vault.claim(); _snap("claim");
        vm.writeLine(OUT, string.concat('{"step":"aliceReceived","amount":', vm.toString(alice.balance - before), '}'));
        assertEq(vault.totalShares(), vault.DEAD_SHARES());
    }
}
