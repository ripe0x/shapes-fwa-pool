// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm} from "forge-std/Vm.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "./TestVaultOps.sol";

library ReconcileTrace {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));

    function actors(PackVault vault, address alice, address bob, address keeper) internal view returns (string memory) {
        return string.concat('{"alice":"', vm.toString(alice), '","bob":"', vm.toString(bob),
            '","keeper":"', vm.toString(keeper), '","owner":"', vm.toString(vault.owner()), '"}');
    }

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
        vm.writeLine(output, render(v, alice, bob, pay, step));
        vm.recordLogs();
    }

    /// @dev A manager has no depositor liabilities or share accounting. Record its actual
    ///      strategy book separately, without pretending that it implements holder getters.
    function measuredWork(PackAccount account, uint256 pay) private view returns (string memory out) {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        bytes32 topic = keccak256("KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)");
        bytes32 paidTopic = keccak256("KeeperPaid(address,uint256)");
        VaultLib.Params memory p = account.getParams();
        uint256 count;
        uint256 paidTotal;
        out = ',"measuredWork":[';
        for (uint256 i; i < logs.length; ++i) {
            Vm.Log memory entry = logs[i];
            if (entry.emitter != address(account) || entry.topics.length == 0 || entry.topics[0] != topic) continue;
            (uint256 measured, uint256 allowance, uint256 price, uint256 units, bool essential) =
                abi.decode(entry.data, (uint256, uint256, uint256, uint256, bool));
            uint256 amount;
            for (uint256 j = i + 1; j < logs.length; ++j) {
                if (logs[j].emitter != address(account) || logs[j].topics.length == 0) continue;
                if (logs[j].topics[0] == topic) break;
                if (logs[j].topics[0] == paidTopic) { amount = abi.decode(logs[j].data, (uint256)); break; }
            }
            paidTotal += amount;
            if (count++ != 0) out = string.concat(out, ",");
            out = string.concat(out, '{"measuredGas":', vm.toString(measured),
                ',"gasAllowance":', vm.toString(allowance), ',"gasPrice":', vm.toString(price),
                ',"workUnits":', vm.toString(units), ',"essential":', essential ? "true" : "false",
                ',"overhead":', vm.toString(p.gasSchedule.overhead),
                ',"txGasPrice":', vm.toString(tx.gasprice), ',"baseFee":', vm.toString(block.basefee),
                ',"paid":', vm.toString(amount), '}');
        }
        require(paidTotal == pay, "keeper log window does not match actual cash delta");
        return count == 0 ? ',"measuredWork":null' : string.concat(out, "]");
    }

    function renderStrategy(PackAccount account, uint256 pay, uint256 creatorFees, string memory step)
        internal view returns (string memory line)
    {
        PackVault facade = PackVault(payable(address(account)));
        line = string.concat('{"compensationMode":"bounded-measured-v1","step":"', step, '","pay":', vm.toString(pay),
            ',"creatorFees":', vm.toString(creatorFees), ',"balance":', vm.toString(address(account).balance),
            ',"open":', vm.toString(account.openListingCount()), ',"idle":', vm.toString(account.idlePackCount()));
        line = string.concat(line, book(facade), ',"feeCredit":', vm.toString(account.fwa().feeCredit(address(account))), measuredWork(account, pay));
        uint256 routine = account.budget();
        line = string.concat(line, ',"reserve":', vm.toString(account.getParams().reserve),
            ',"routineBudget":', vm.toString(routine), '}');
    }

    function render(PackVault v, address alice, address bob, uint256 pay, string memory step) internal view returns (string memory line) {
        uint256[] memory open = TestVaultOps.open(v);
        uint256 fees;
        for (uint256 i; i < open.length; ++i) fees += v.fwa().pendingFees(open[i]);
        (uint128 aLocked,,,) = v.redemptions(alice);
        line = string.concat('{"compensationMode":"bounded-measured-v1","step":"', step, '","pay":', vm.toString(pay), ',"balance":', vm.toString(address(v).balance));
        line = string.concat(line, ',"totalShares":', vm.toString(v.totalShares()), ',"lastNav":', vm.toString(v.lastNav()));
        line = string.concat(line, ',"pendingDepositTotal":', vm.toString(v.pendingDepositTotal()), ',"redemptionReserve":', vm.toString(v.redemptionReserve()), ',"lockedShares":', vm.toString(v.lockedShares()));
        line = string.concat(line, ',"open":', vm.toString(open.length), ',"idle":', vm.toString(v.idlePackCount()));
        line = string.concat(line, ',"aliceShares":', vm.toString(v.shareBalance(alice)), ',"bobShares":', vm.toString(v.shareBalance(bob)), ',"aliceLocked":', vm.toString(uint256(aLocked)));
        line = string.concat(line, ',"aliceClaimable":', vm.toString(v.claimableEth(alice)), ',"pendingFeesSum":', vm.toString(fees), ',"feeCredit":', vm.toString(v.fwa().feeCredit(address(v))));
        line = string.concat(line, book(v), ',"processingPool":', vm.toString(v.processingPool()), measuredWork(v, pay));
        line = string.concat(line, ',"distributionReserve":', vm.toString(v.distributionReserve()), ',"claimableTotal":', vm.toString(v.claimableTotal()));
        line = string.concat(line, ',"chargeRefundReserve":', vm.toString(v.chargeRefundReserve()),
            ',"chargeEra":', vm.toString(v.chargeEra()), ',"constructionCost":', vm.toString(v.deployCharge()),
            ',"referenceCapital":', vm.toString(v.positionValue()), ',"liveMintFee":', vm.toString(v.shapes().mintFee()),
            ',"unresolvedKeepUplift":', vm.toString(v.unresolvedUplift()));
        line = string.concat(line, contributionState(v));
        line = string.concat(line, ',"windingDown":', v.windingDown() ? "true" : "false", '}');
    }

    function contributionState(PackVault v) private view returns (string memory out) {
        out = ',"contributions":[';
        for (uint256 i; i < v.contributionCount(); ++i) {
            (address payer, uint256 era, uint256 start, uint256 amount, bool claimed) = v.contributions(i);
            if (i != 0) out = string.concat(out, ',');
            out = string.concat(out, '{"id":', vm.toString(i), ',"payer":"', vm.toString(payer),
                '","era":', vm.toString(era), ',"start":', vm.toString(start), ',"amount":', vm.toString(amount),
                ',"claimed":', claimed ? 'true' : 'false', '}');
        }
        out = string.concat(out, '],"chargeEras":[');
        for (uint256 i; i <= v.chargeEra(); ++i) {
            (uint256 total, uint256 refundable, bool closed) = v.chargeEras(i);
            if (i != 0) out = string.concat(out, ',');
            out = string.concat(out, '{"era":', vm.toString(i), ',"total":', vm.toString(total),
                ',"refundable":', vm.toString(refundable), ',"closed":', closed ? 'true' : 'false', '}');
        }
        out = string.concat(out, '],"issuances":[');
        for (uint256 i; i < v.epoch(); ++i) {
            (uint256 gross, uint256 issued, uint256 remainingGross, uint256 remainingShares) = v.issuances(i);
            if (i != 0) out = string.concat(out, ',');
            out = string.concat(out, '{"epoch":', vm.toString(i), ',"gross":', vm.toString(gross),
                ',"issued":', vm.toString(issued), ',"remainingGross":', vm.toString(remainingGross),
                ',"remainingShares":', vm.toString(remainingShares), '}');
        }
        out = string.concat(out, ']');
    }
}
