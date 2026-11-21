// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {Ownable} from "solady/auth/Ownable.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {IKeeperPolicy, KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {Charges} from "../utils/Charges.sol";

/// @dev A replacement with a materially different formula: a flat 3 work fees per unit, no gas.
contract KeeperPolicyFlat is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) {
        return 2;
    }

    function quote(uint256, uint256 units, uint256, bool, uint256, uint256, uint256 workFee)
        external
        pure
        returns (uint256)
    {
        return 3 * units * workFee;
    }
}

/// @dev Hostile policies an owner could propose. Each is a real deployed contract the vault calls.
contract PolicyGreedy is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) {
        return 1;
    }

    function quote(uint256, uint256, uint256, bool, uint256, uint256, uint256) external pure returns (uint256) {
        return type(uint256).max;
    }
}

contract PolicyReverting is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) {
        return 1;
    }

    function quote(uint256, uint256, uint256, bool, uint256, uint256, uint256) external pure returns (uint256) {
        revert("no");
    }
}

contract PolicyGasBurner is IKeeperPolicy {
    function policyVersion() external pure returns (uint256) {
        return 1;
    }

    function quote(uint256, uint256, uint256, bool, uint256, uint256, uint256) external view returns (uint256 x) {
        while (gasleft() > 100) x = uint256(keccak256(abi.encode(x)));
    }
}

contract PolicyShortReturn {
    function policyVersion() external pure returns (uint256) {
        return 1;
    }

    fallback() external {
        assembly {
            return(0, 16)
        }
    }
}

contract PolicyVersionZero {
    function policyVersion() external pure returns (uint256) {
        return 0;
    }
}

contract PolicyNoVersion {}

/// @notice Replaceable keeper payment policy (D57) on the real FWA, Shapes and ShapePacks at a
///         pinned mainnet block. The vault verifies the work, caps the policy's offer at its own
///         envelope, free ETH and budget, and never lets a policy block maintenance. No mocks.
contract ForkKeeperPolicyTest is ForkBase {
    uint256 constant PRICE = 0.2 gwei; // min(basefee 0.15 + maxTip 0.05, ceiling 5)
    // Build-and-list 3 six-unit packs: Q_BUILD call base + per pack (buildGas(2) + Q_LISTED).
    uint256 constant BUILD3_GAS = VaultLib.Q_BUILD + 3 * (VaultLib.Q_BUILD_PACK + 2 * VaultLib.Q_BUILD_SHAPE
        + VaultLib.Q_LISTED);
    uint256 constant BUILD3_UNITS = 6; // 2 work units per built pack

    function _priced() internal {
        uint256 gross = Charges.grossFor(vault, 2 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 6, 6, 0);
    }

    function _swap(address policy) internal {
        vm.prank(owner);
        vault.setPolicy(policy); // at once (D58)
        assertEq(address(vault.keeperPolicy()), policy);
    }

    /// @dev `build` is now the primary paid strategy op (it mints and lists at once); `list` only
    ///      relists returned packs, of which routine flow produces none, so keeper pay is exercised
    ///      through `build` here.
    function _build3(uint256 minPay) internal returns (uint256 pay) {
        uint256 b = keeper.balance;
        vm.prank(keeper);
        pay = TestVaultOps.restock(vault, 3, 6, minPay);
        assertEq(keeper.balance - b, pay, "returned pay is the ETH received");
    }

    /// Full swap V1 -> a materially different V2 on the fork: assets, shares, positions, charges
    /// and budgets carry over unchanged; the next payment follows V2's formula exactly.
    function test_swapToDifferentFormulaPreservesAccounting() public {
        _priced();
        uint256 fee = vault.getParams().workFee;
        assertEq(_build3(0), BUILD3_GAS * PRICE + BUILD3_UNITS * fee, "V1: quoted gas at basefee + tip, plus work fee");

        KeeperPolicyFlat v2 = new KeeperPolicyFlat();
        address v1 = address(vault.keeperPolicy());

        uint256 bal = address(vault).balance;
        uint256 shares = vault.totalShares();
        uint256 nav = vault.lastNav();
        uint256 aliceShares = vault.shareBalance(alice);
        uint256[] memory open = TestVaultOps.open(vault);
        uint256 idle = TestVaultOps.idle(vault).length;
        uint256 pool = vault.processingPool();
        uint256 rc = vault.requestCharge();
        uint256 dc = vault.deployCharge();

        vm.prank(bob);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.setPolicy(address(v2));
        vm.expectEmit(true, true, false, false, address(vault));
        emit PackAccount.PolicyChanged(v1, address(v2));
        vm.prank(owner);
        vault.setPolicy(address(v2));
        assertEq(address(vault.keeperPolicy()), address(v2));

        assertEq(address(vault).balance, bal, "balance");
        assertEq(vault.totalShares(), shares, "supply");
        assertEq(vault.lastNav(), nav, "nav");
        assertEq(vault.shareBalance(alice), aliceShares, "holder shares");
        assertEq(TestVaultOps.open(vault).length, open.length, "positions");
        assertEq(TestVaultOps.idle(vault).length, idle, "idle packs");
        assertEq(vault.processingPool(), pool, "pool");
        // Gates and charges use the vault's envelope, so a policy cannot move them.
        assertEq(vault.requestCharge(), rc, "request charge independent of policy");
        assertEq(vault.deployCharge(), dc, "deploy charge independent of policy");
        for (uint256 i; i < open.length; ++i) {
            (uint64 packId,,) = TestVaultOps.position(vault, open[i]);
            assertTrue(packId != 0, "position record kept");
        }

        uint256 expected = v2.quote(1, BUILD3_UNITS, BUILD3_GAS, false, 5 gwei, 0.05 gwei, fee);
        assertEq(expected, 3 * BUILD3_UNITS * fee);
        assertEq(_build3(expected), expected, "V2 pays its own quote, to the wei");
        assertEq(TestVaultOps.open(vault).length, open.length + 3);
    }

    /// The vault rejects an EOA, version 0, a contract without policyVersion, a non-owner proposer,
    /// and an invalid constructor policy.
    function test_invalidPolicyRejected() public {
        address eoa = makeAddr("pack-vault-test-eoa-policy");
        assertEq(eoa.code.length, 0); assertEq(eoa.balance, 0);
        address v0 = address(new PolicyVersionZero());
        address nv = address(new PolicyNoVersion());
        vm.startPrank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setPolicy(eoa);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setPolicy(v0);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setPolicy(nv);
        vm.stopPrank();
        address ok = address(new KeeperPolicyFlat());
        vm.prank(keeper);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.setPolicy(ok);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        new PackVault(FWA, SHAPES, PACKS, owner, defaultParams(), KeeperPolicyV1(eoa));
    }

    /// A policy asking for everything is paid the envelope (quoted gas x ceiling-capped price with
    /// the markup, plus the work fee): never the vault's ETH.
    function test_greedyPolicyCappedAtEnvelope() public {
        _priced();
        _swap(address(new PolicyGreedy()));
        uint256 envelope = BUILD3_GAS * PRICE * 11_000 / 10_000 + BUILD3_UNITS * vault.getParams().workFee;
        assertEq(_build3(0), envelope, "capped at the vault's envelope");
    }

    /// A reverting, gas-burning or short-return policy pays nothing; maintenance still runs unpaid,
    /// and minPay > 0 reverts the whole call atomically.
    function test_failingPolicyNeverBlocksWork() public {
        _priced();
        address[3] memory bad =
            [address(new PolicyReverting()), address(new PolicyGasBurner()), address(new PolicyShortReturn())];
        uint256 g = gasleft();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 1, 6, 0);
        uint256 gasV1 = g - gasleft();
        uint256 snap = vm.snapshotState();
        for (uint256 i; i < 3; ++i) {
            vm.revertToState(snap);
            _swap(bad[i]);
            uint256 open = TestVaultOps.open(vault).length;
            uint256[] memory planned7 = TestVaultOps.proposals(vault, 1, 6);
            vm.prank(keeper);
            vm.expectRevert(VaultLib.Payment.selector);
            vault.build(6, planned7, 1);
            g = gasleft();
            vm.prank(keeper);
            uint256 pay = TestVaultOps.restock(vault, 1, 6, 0);
            uint256 used = g - gasleft();
            assertEq(pay, 0, "failing policy pays nothing");
            assertEq(TestVaultOps.open(vault).length, open + 1, "work still done");
            assertLt(used, gasV1 + 60_000, "policy gas bounded at 50k");
        }
    }

    /// Only the owner pauses; pauses are one-way.
    function test_ownerPauses() public {
        vm.prank(keeper);
        vm.expectRevert(Ownable.Unauthorized.selector);
        vault.guard(true, false);
        vm.prank(owner);
        vault.guard(true, false);
        assertTrue(vault.depositsPaused());
    }

    /// Even under the greedy policy, the owner stops all pay at once (budget caps 0), and the
    /// keeper's work still runs unpaid.
    function test_ownerDisablesPayImmediately() public {
        _priced();
        _swap(address(new PolicyGreedy()));
        setCaps(0, 0);
        (uint256 r, uint256 e) = vault.budget();
        assertEq(r + e, 0, "budgets emptied");
        uint256 open = TestVaultOps.open(vault).length;
        assertEq(_build3(0), 0, "no pay");
        assertEq(TestVaultOps.open(vault).length, open + 3, "work runs unpaid");
        uint256[] memory planned6 = TestVaultOps.proposals(vault, 1, 6);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Payment.selector);
        vault.build(6, planned6, 1);
    }

    /// Review H1: a deployment charge above 2^64 wei (18.4 ETH) is stored whole, so shares mint on
    /// the same net amount the checkpoint credits, and a cancel restores the totals exactly.
    function test_largeDepositChargeNotTruncated() public {
        VaultLib.Params memory p = defaultParams();
        p.gasCeiling = 50 gwei;
        p.essentialCeiling = 50 gwei;
        p.maxTip = 50 gwei;
        p.tvlCap = 1_000 ether;
        vm.fee(50 gwei);
        vm.txGasPrice(50 gwei);
        (PackVault v,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
        // The direct-mint deploy charge is a smaller fraction of each escrowed unit than the old
        // 0.1-ETH recipe, so a larger deposit is needed to drive the stored charge above 2^64 wei.
        uint256 gross = Charges.grossFor(v, 60 ether);
        vm.deal(alice, gross);
        vm.prank(alice);
        v.deposit{value: gross}();
        (uint96 amount,, uint96 charge,) = v.pendingDeposits(alice);
        uint256 deploy = v.deployCharge();
        assertEq(charge, uint256(amount) * deploy / (VaultLib.POSITION_VALUE + deploy), "charge stored whole");
        assertGt(charge, type(uint64).max, "above the old uint64 width");
        uint256 snap = vm.snapshotState();
        vm.prank(alice);
        v.cancelDeposit();
        assertEq(v.pendingDepositTotal(), 0);
        assertEq(alice.balance, gross, "escrow and checkpoint charge refunded");
        vm.revertToState(snap);
        toBlackout();
        vm.prank(keeper);
        v.checkpoint(0, 0);
        // Shares on the holder's balance equal the shares the checkpoint added to the supply.
        assertEq(v.shareBalance(alice), v.totalShares() - v.DEAD_SHARES(), "no unbacked shares");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }
}
