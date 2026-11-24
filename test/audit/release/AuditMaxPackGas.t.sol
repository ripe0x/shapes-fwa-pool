// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../../utils/TestVaultOps.sol";
import {DeployCore} from "../../../script/DeployCore.sol";
import {ForkBase} from "../../fork/ForkBase.sol";
import {PackVault} from "../../../src/PackVault.sol";
import {PackAccount} from "../../../src/PackAccount.sol";
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
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, keccak256(abi.encode(p, uint256(0.001 ether), false, false)));
        p.packUnitsMask = uint64(1) << 31;
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, keccak256(abi.encode(p, uint256(0.001 ether), false, false)));

        p.packUnitsMask = uint64(1) << 30;
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        uint256 gross = Charges.grossFor(vault, 5 ether);
        bytes32 _expected0 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: gross}(_expected0);
        toBlackout();
        checkpoint();
        toOpen();
        setPackAsk(0.33 ether); // Ceiling 0.363 covers a 0.30 / 0.9 cash bid.
        (,, bool ok) = vault.edge(30);
        assertTrue(ok, "30-unit pack edge must be live");
        assertEq(vault.idlePackCount(), 0, "empty inventory");
        assertEq(vault.openListingCount(), 0, "empty inventory");
        uint256[] memory proposals = TestVaultOps.proposals(vault, 1, 30);
        uint256 beforeGas = gasleft();
        vm.prank(keeper);
        // build mints the pack straight into ShapePacks and lists it at once (no idle leftover).
        (bool underCap,) = address(vault).call{gas: 16_777_216}(abi.encodeCall(PackAccount.build, (30, proposals, 0, vault.configurationHash())));
        uint256 used = beforeGas - gasleft();
        emit log_named_uint("30 unit build gas", used);
        assertTrue(underCap, "largest allowed pack builds under the transaction cap");
        assertLt(used, 12_000_000, "with headroom");
        assertEq(TestVaultOps.idle(vault).length, 0, "build leaves no idle pack");
        assertEq(TestVaultOps.open(vault).length, 1, "build lists the pack");
    }
}
