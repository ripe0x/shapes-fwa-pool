// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm} from "forge-std/Vm.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";

/// @dev Reads genuine account events; callers independently check funding, budgets and cash deltas.
library MeasuredPay {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    bytes32 private constant METER = keccak256("KeeperWorkMeasured(uint256,uint256,uint256,uint256,bool)");
    bytes32 private constant PAID = keccak256("KeeperPaid(address,uint256)");

    function gross(PackAccount account, uint256 allowance, uint256 units, bool essential, uint256 price)
        internal view returns (uint256)
    {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        for (uint256 i = logs.length; i != 0; --i) {
            Vm.Log memory entry = logs[i - 1];
            if (entry.emitter != address(account) || entry.topics.length == 0 || entry.topics[0] != METER) continue;
            (uint256 measured, uint256 cap, uint256 chargedPrice, uint256 work, bool exitWork) =
                abi.decode(entry.data, (uint256, uint256, uint256, uint256, bool));
            require(measured != 0 && cap == allowance && work == units && exitWork == essential && chargedPrice == price,
                "unexpected actual measurement context");
            return amount(account.getParams(), measured, cap, price, units, essential);
        }
        revert("missing actual measurement");
    }

    function amount(VaultLib.Params memory p, uint256 measured, uint256 allowance, uint256 price,
        uint256 units, bool) private pure returns (uint256)
    {
        uint256 reimbursed = measured < allowance ? measured : allowance;
        return (reimbursed + p.gasSchedule.overhead) * price + units * p.workFee;
    }

    /// @dev Aggregate a whole lifecycle, retaining every call and any zero-clipped measurement.
    ///      Only paid frames contribute service units/caps; their receipts must fit their meters.
    function total(PackAccount account, address recipient, uint256 price)
        internal view returns (uint256 paid, uint256 units, uint256 allowances)
    {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        VaultLib.Params memory p = account.getParams();
        for (uint256 i; i < logs.length; ++i) {
            Vm.Log memory entry = logs[i];
            if (entry.emitter != address(account) || entry.topics.length == 0 || entry.topics[0] != METER) continue;
            (uint256 measured, uint256 cap, uint256 chargedPrice, uint256 work, bool essential) =
                abi.decode(entry.data, (uint256, uint256, uint256, uint256, bool));
            require(measured != 0 && chargedPrice == price, "lifecycle measurement context");
            for (uint256 j = i + 1; j < logs.length; ++j) {
                Vm.Log memory payment = logs[j];
                if (payment.emitter != address(account) || payment.topics.length == 0) continue;
                if (payment.topics[0] == METER) break;
                if (payment.topics[0] != PAID) continue;
                require(payment.topics.length == 2 && address(uint160(uint256(payment.topics[1]))) == recipient,
                    "unexpected lifecycle keeper");
                uint256 value = abi.decode(payment.data, (uint256));
                require(value <= amount(p, measured, cap, price, work, essential), "payment exceeds actual meter");
                paid += value;
                units += work;
                allowances += cap;
                break;
            }
        }
    }
}
