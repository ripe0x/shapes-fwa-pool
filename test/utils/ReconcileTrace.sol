// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm} from "forge-std/Vm.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "./TestVaultOps.sol";

library ReconcileTrace {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function uints(uint256[] memory values) internal pure returns (string memory out) {
        out = "[";
        for (uint256 i; i < values.length; ++i) {
            if (i != 0) out = string.concat(out, ",");
            out = string.concat(out, vm.toString(values[i]));
        }
        return string.concat(out, "]");
    }

    function position(PackVault v, uint256 id) private view returns (string memory out) {
        VaultLib.Position memory p = v.position(id);
        (,,,,,,, uint256 liveDebt,, uint64 liveAt,) = v.fwa().listings(id);
        out = string.concat('{"id":', vm.toString(id), ',"packId":', vm.toString(p.packId), ',"value":', vm.toString(p.value));
        out = string.concat(out, ',"backing":', vm.toString(p.backing), ',"feeDebt":', vm.toString(p.feeDebt));
        out = string.concat(out, ',"liveFeeDebt":', vm.toString(liveDebt), ',"liveAllocatedAt":', vm.toString(liveAt));
        out = string.concat(out, ',"allocatedAt":', vm.toString(p.allocatedAt), ',"state":', vm.toString(p.state), '}');
    }

    function book(PackVault v) private view returns (string memory out) {
        (uint256 tracked, uint256 idle, uint256 backing, uint256 active, uint256 debt, uint256 allocated) = v.totals();
        out = string.concat(',"trackedValue":', vm.toString(tracked), ',"idleValue":', vm.toString(idle), ',"activeBacking":', vm.toString(backing));
        out = string.concat(out, ',"activeCount":', vm.toString(active), ',"feeDebtSum":', vm.toString(debt), ',"allocatedValue":', vm.toString(allocated));
        out = string.concat(out, ',"idleFunding":', vm.toString(v.idleFunding()));
        out = string.concat(out, ',"completedPrefix":', vm.toString(v.fwa().nextSequenceToProcess()), ',"cursor":', vm.toString(v.acquisitionCursor()));
        out = string.concat(out, ',"pendingReceipts":', vm.toString(v.pendingReceipts()), ',"reservedCount":', vm.toString(v.reservedCount()), ',"positions":[');
        uint256[] memory ids = TestVaultOps.open(v);
        for (uint256 i; i < ids.length; ++i) {
            if (i != 0) out = string.concat(out, ',');
            out = string.concat(out, position(v, ids[i]));
        }
        out = string.concat(out, ']');
    }

    function snapshot(PackVault v, address alice, address bob, uint256 pay, string memory step, string memory output) internal {
        uint256[] memory open = TestVaultOps.open(v);
        uint256 fees;
        for (uint256 i; i < open.length; ++i) fees += v.fwa().pendingFees(open[i]);
        (uint128 aLocked,,,) = v.redemptions(alice);
        string memory line = string.concat('{"step":"', step, '","pay":', vm.toString(pay), ',"balance":', vm.toString(address(v).balance));
        line = string.concat(line, ',"totalShares":', vm.toString(v.totalShares()), ',"lastNav":', vm.toString(v.lastNav()));
        line = string.concat(line, ',"pendingDepositTotal":', vm.toString(v.pendingDepositTotal()), ',"redemptionReserve":', vm.toString(v.redemptionReserve()), ',"lockedShares":', vm.toString(v.lockedShares()));
        line = string.concat(line, ',"open":', vm.toString(open.length), ',"idle":', vm.toString(v.idlePackCount()));
        line = string.concat(line, ',"aliceShares":', vm.toString(v.shareBalance(alice)), ',"bobShares":', vm.toString(v.shareBalance(bob)), ',"aliceLocked":', vm.toString(uint256(aLocked)));
        line = string.concat(line, ',"aliceClaimable":', vm.toString(v.claimableEth(alice)), ',"pendingFeesSum":', vm.toString(fees), ',"feeCredit":', vm.toString(v.fwa().feeCredit(address(v))));
        line = string.concat(line, book(v), ',"processingPool":', vm.toString(v.processingPool()));
        line = string.concat(line, ',"distributionReserve":', vm.toString(v.distributionReserve()), ',"claimableTotal":', vm.toString(v.claimableTotal()));
        line = string.concat(line, ',"windingDown":', v.windingDown() ? "true" : "false", '}');
        vm.writeLine(output, line);
    }
}
