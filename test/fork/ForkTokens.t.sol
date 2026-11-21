// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {Test} from "forge-std/Test.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {
    IShapes, IShapePacks, IFWAV2, IFWARewards, IFWAToken
} from "../../src/interfaces/External.sol";
import {IOwnable, IFwaAdmin} from "./ForkBase.sol";

/// @notice FWA token rewards end to end: our listings are live when a real buyback transaction
///         (replayed as its original call) routes tokens to depositors; the vault claims them and
///         burns them (D43). Holders get no token value and pay nothing for the burn.
contract ForkTokensTest is Test {
    IShapes constant SHAPES = IShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    IShapePacks constant PACKS = IShapePacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    IFWAV2 constant FWA = IFWAV2(0x958C41181182e76F221331b2755b77D9e1426A98);
    uint256 constant BUYBACK_BLOCK = 26_423_454;

    PackVault vault;
    address owner = makeAddr("pack-vault-test-token-owner");
    IFWAToken token;

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }

    receive() external payable {}

    function setUp() public {
        string memory fx = vm.readFile("test/fixtures/buyback.json");
        vm.createSelectFork("mainnet", vm.parseJsonBytes32(fx, ".tx"));
        assertEq(block.number, BUYBACK_BLOCK);
        assertEq(owner.code.length, 0); assertEq(owner.balance, 0);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        vm.fee(0.1 gwei);
        vm.txGasPrice(0.15 gwei);
        token = IFWAToken(FWA.token());
        // The 6-unit backing (~0.065 ETH) exceeds the oracle floor cap, so list it the way D62 does:
        // FWA's owner oracle-exempts ShapePacks (its real live call, also made in ForkBase).
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);

        VaultLib.Params memory p;
        p.minEdgeBps = 100;
        p.payMarkupBps = 1_000;
        p.maxTip = 0.05 gwei;
        p.keeperShareBps = 2_500;
        p.allocatedBoundBps = 200;
        p.packUnitsMask = uint64(1) << 6; // the 6-unit direct-mint recipe
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 0.5 gwei;

        p.tvlCap = 100 ether;
        p.routineCap = 0.3 ether; // bytecode maxima: these suites test mechanics, not budgets
        p.routineRate = 0.01 ether;
        p.essentialCap = 0.1 ether;
        p.essentialRate = 0.005 ether;
        vm.deal(address(this), 6 ether);
        // Seed covers 16 six-unit packs: each costs P + 0.002 mint fee + backing (~0.13 ETH).
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 3 ether);
        TestVaultOps.restock(vault, 16, 6, 0); // build mints and lists all 16 at once

        // The real buyback, replayed as its original self-call (EIP-7702 delegated sender).
        address from = vm.parseJsonAddress(fx, ".from");
        bytes memory input = vm.parseJsonBytes(fx, ".input");
        vm.txGasPrice(vm.parseJsonUint(fx, ".gasPrice"));
        vm.prank(from, from);
        (bool ok,) = vm.parseJsonAddress(fx, ".to").call(input);
        assertTrue(ok, "real buyback replays");
        vm.txGasPrice(0.15 gwei);
    }

    function _pending(uint256[] memory ids) internal view returns (uint256 sum) {
        for (uint256 i; i < ids.length; ++i) {
            sum += IFWARewards(FWA.rewards()).pendingDepositorTokens(ids[i]);
        }
    }

    function assertTokenGasContext() external {
        assertEq(block.basefee, 0.1 gwei); assertEq(tx.gasprice, 0.15 gwei);
    }

    /// Active rewards: anyone's unpaid call claims every pending token and burns it; supply falls
    /// by exactly that amount and no ETH moves.
    function test_burnClaimsActiveRewards() public {
        uint256[] memory ids = TestVaultOps.open(vault);
        uint256 pending = _pending(ids);
        assertGt(pending, 0, "the real buyback accrued tokens to our listings");
        uint256 supply = token.totalSupply();
        uint256 vEth = address(vault).balance;
        address caller = makeAddr("pack-vault-test-token-caller");
        assertEq(caller.code.length, 0); assertEq(caller.balance, 0);
        vm.deal(caller, 0.01 ether);
        this.assertTokenGasContext();
        bytes memory input = abi.encodeCall(PackAccount.burnTokens, (ids));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        address rewardModule = FWA.rewards();
        vm.cool(address(vault)); vm.cool(address(token)); vm.cool(rewardModule);
        vm.prank(caller);
        uint256 start = gasleft();
        vault.burnTokens(ids);
        uint256 used = start - gasleft() + intrinsic;
        emit log_named_uint("burn maximum sixteen real token rewards gross complete gas", used);
        assertLt(used * 125 / 100, 16_777_216);
        assertEq(_pending(ids), 0);
        assertEq(token.balanceOf(address(vault)), 0);
        assertEq(supply - token.totalSupply(), pending, "burned exactly what was claimed");
        assertEq(address(vault).balance, vEth, "unpaid: vault ETH unchanged");
        assertEq(caller.balance, 0.01 ether, "vault pays no ETH for token burning");
    }

    /// Settled credit and a stale id: a listing removed after the keeper looked must not block the
    /// credit its removal created, and the other listings are burned on the next call.
    function test_staleIdDoesNotBlockCredit() public {
        uint256[] memory ids = TestVaultOps.open(vault);
        uint256 pendingAll = _pending(ids);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory one = new uint256[](1);
        one[0] = ids[0];
        uint256 firstPending = IFWARewards(FWA.rewards()).pendingDepositorTokens(ids[0]);
        TestVaultOps.unlist(vault, one, 0); // its pending tokens become the vault's token credit
        assertEq(IFWARewards(FWA.rewards()).tokenCredit(address(vault)), firstPending, "credit on removal");

        // The stale list still includes ids[0]: FWA's batch claim reverts, the credit still burns.
        uint256 supply = token.totalSupply();
        TestVaultOps.burnTokens(vault, ids);
        assertEq(supply - token.totalSupply(), firstPending);
        assertEq(IFWARewards(FWA.rewards()).tokenCredit(address(vault)), 0);
        assertEq(_pending(ids), pendingAll - firstPending, "others still pending, not lost");

        uint256[] memory rest = TestVaultOps.open(vault);
        TestVaultOps.burnTokens(vault, rest);
        assertEq(_pending(rest), 0);
        assertEq(token.balanceOf(address(vault)), 0);
    }

    /// Zero rewards: nothing to claim or burn reverts without moving anything.
    function test_zeroRewards() public {
        vm.expectRevert(PackVault.Nothing.selector);
        TestVaultOps.burnTokens(vault, new uint256[](0));
    }
}
