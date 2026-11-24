// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {Vm} from "forge-std/Vm.sol";
import {PackVault} from "../../src/PackVault.sol";
/// @dev Discover test-owned closed records and claim through the real bounded API.
library RefundClaims {
    Vm private constant vm = Vm(address(uint160(uint256(keccak256("hevm cheat code")))));
    function available(PackVault vault, address payer) internal view returns (uint256 amount) {
        for (uint256 id; id < vault.contributionCount(); ++id) {
            (address account,,,,) = vault.contributions(id);
            if (account == payer) amount += vault.checkpointRefund(id);
        }
    }
    function claim(PackVault vault, address payer) internal {
        uint256[] memory batch = new uint256[](16);
        uint256 count;
        uint256 total = vault.contributionCount();
        for (uint256 id; id < total; ++id) {
            (address account,,,,) = vault.contributions(id);
            if (account != payer || vault.checkpointRefund(id) == 0) continue;
            batch[count++] = id;
            if (count == 16) {
                vm.prank(payer);
                vault.claimCheckpointRefund(batch);
                count = 0;
            }
        }
        if (count != 0) {
            assembly ("memory-safe") { mstore(batch, count) }
            vm.prank(payer);
            vault.claimCheckpointRefund(batch);
        }
    }
}
