// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {ForkBase} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";

contract AuditMaxPackGas is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    function test_maxPackRestockGas() public {
        this.assertGasContext();
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 63;
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
        vm.prank(alice);
        vault.deposit{value: Charges.grossFor(vault, 5 ether)}();
        toBlackout();
        checkpoint();
        toOpen();
        setPackAsk(0.63 ether);
        (uint256 k, uint256 backing, bool ok) = vault.edge(63);
        emit log_named_uint("edge k 1e18", k);
        emit log_named_uint("backing wei", backing);
        assertTrue(ok, "max pack edge must be live");
        vm.prank(keeper);
        (bool underCap,) = address(vault).call{gas: 16_777_216}(abi.encodeCall(PackVault.restock, (1, 63, 0)));
        emit log_named_uint("16777216 restock success", underCap ? 1 : 0);
        uint256 beforeGas = gasleft();
        vm.prank(keeper);
        vault.restock(1, 63, 0);
        uint256 used = beforeGas - gasleft();
        emit log_named_uint("63 unit restock gas", used);
        assertFalse(underCap, "single maximum pack cannot restock under transaction cap");
        assertGt(used, 16_777_216);
        assertEq(vault.idlePacks().length, 1);
    }
}
