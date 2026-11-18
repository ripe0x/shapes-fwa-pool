// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;
import {DeployCore} from "../../../script/DeployCore.sol";
import {ForkBase} from "../../fork/ForkBase.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../../src/KeeperPolicy.sol";
import {VaultLib} from "../../../src/VaultLib.sol";
import {Charges} from "../../utils/Charges.sol";

contract AuditMaxPackGas is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }
    /// Repaired (E11): pack sizes above 30 units are rejected; the largest allowed pack builds from
    /// empty inventory inside EIP-7825's per-transaction cap.
    function test_maxPackFitsTransactionCap() public {
        this.assertGasContext();
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = uint64(1) << 63;
        vm.expectRevert(PackVault.OutOfBounds.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
        p.packUnitsMask = uint64(1) << 31;
        vm.expectRevert(PackVault.OutOfBounds.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());

        p.packUnitsMask = uint64(1) << 30;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
        vm.prank(alice);
        vault.deposit{value: Charges.grossFor(vault, 5 ether)}();
        toBlackout();
        checkpoint();
        toOpen();
        setPackAsk(0.30 ether);
        (,, bool ok) = vault.edge(30);
        assertTrue(ok, "30-unit pack edge must be live");
        assertEq(vault.looseShapeCount(), 0, "empty inventory");
        uint256 beforeGas = gasleft();
        vm.prank(keeper);
        (bool underCap,) = address(vault).call{gas: 16_777_216}(abi.encodeCall(PackVault.restock, (1, 30, 0)));
        uint256 used = beforeGas - gasleft();
        emit log_named_uint("30 unit restock gas", used);
        assertTrue(underCap, "largest allowed pack builds under the transaction cap");
        assertLt(used, 12_000_000, "with headroom");
        assertEq(vault.idlePacks().length, 1);
    }
}
