// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {ForkBase, ForceSender, IFwaAdmin} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {ERC721} from "solady/tokens/ERC721.sol";

/// @dev An attacker-chosen NFT collection pushing tokens at the vault.
contract HostileNft is ERC721 {
    function name() public pure override returns (string memory) {
        return "Hostile";
    }

    function symbol() public pure override returns (string memory) {
        return "H";
    }

    function tokenURI(uint256) public pure override returns (string memory) {
        return "";
    }

    function mint(address to, uint256 id) external {
        _mint(to, id);
    }
}

/// @dev Holder that tries to re-enter the vault from its ETH receive hook.
contract ReentrantHolder {
    PackVault immutable vault;
    uint256 public reentryReverted;

    constructor(PackVault v) {
        vault = v;
    }

    function deposit() external payable {
        vault.deposit{value: msg.value}();
    }

    function redeemAll() external payable {
        vault.requestRedeem{value: msg.value}(vault.shareBalance(address(this)));
    }

    function claim() external {
        vault.claim();
    }

    receive() external payable {
        try vault.claim() {} catch {
            ++reentryReverted;
        }
    }
}

contract ForkVaultAdversarialTest is ForkBase {
    receive() external payable {} // this contract calls paid work directly

    // D55's per-unit fee test moved to ForkKeeperPay.t.sol (quoted pay, D56).

    function test_workFeeBounded() public {
        VaultLib.Params memory p = defaultParams();
        p.workFee = uint64(vault.MAX_WORK_FEE() + 1);
        vm.prank(owner);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.setParams(p);
        p.workFee = uint64(vault.MAX_WORK_FEE());
        vm.prank(owner);
        vault.setParams(p);
        assertEq(vault.getParams().workFee, vault.MAX_WORK_FEE(), "applied at once (D58)");
        // With the ceiling and fee at 0 no pay remains.
        lowerTo(100 ether, 0, 0);
        assertEq(vault.getParams().workFee, 0);
        assertEq(vault.getParams().gasCeiling, 0);
    }

    /// D51/D56: above the gas ceiling a build is accepted and paid its quote at the ceiling price;
    ///      the caller pays the rest. Ceiling lowered to 0.3 gwei, where a build passes its payback
    ///      gate; one pack from no loose Shapes = 280k base + 200k pack + 2.2M mint, x 0.3 gwei (V1: no markup).
    function test_buildAboveCeilingPaidAtCeilingPrice() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        lowerTo(100 ether, 0.3 gwei, 0.00002 ether);
        vm.fee(1.9 gwei);
        vm.txGasPrice(2 gwei); // well above the ceiling
        uint256 idle0 = TestVaultOps.idle(vault).length;
        uint256 kb = keeper.balance;
        vm.prank(keeper);
        uint256 pay = TestVaultOps.restock(vault, 1, 3, 0);
        assertEq(TestVaultOps.idle(vault).length, idle0 + 1, "built above the ceiling");
        assertEq(keeper.balance - kb, pay);
        assertEq(pay, (VaultLib.Q_RESTOCK + VaultLib.Q_PACK + VaultLib.Q_MINT) * 0.3 gwei + vault.getParams().workFee, "quote at the ceiling price + one pack's work fee");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function test_forcedEthAccruesToHolders_firstDepositorCannotInflate() public {
        // Attacker is first depositor with the minimum, then donates 10 ETH before the victim prices.
        address attacker = makeAddr("pack-vault-test-attacker");
        assertEq(attacker.code.length, 0); assertEq(attacker.balance, 0);
        vm.deal(attacker, 20 ether);
        {
            uint256 gross_ = Charges.grossFor(vault, 0.01 ether);
            vm.prank(attacker);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(attacker);
        new ForceSender{value: 10 ether}(payable(address(vault)));
        {
            uint256 gross_ = Charges.grossFor(vault, 5 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();

        uint256 supply = vault.totalShares();
        uint256 aliceShares = vault.shareBalance(alice);
        uint256 nav = vault.lastNav();
        // Alice's claim on NAV equals her escrow less its deployment charge (that charge joins the
        // vault's value, shared by all holders, to pay for building positions with her ETH).
        uint256 charge = 5 ether * vault.deployCharge() / (0.0663 ether + vault.deployCharge());
        assertApproxEqAbs(
            nav * aliceShares / supply, 5 ether - charge + charge * aliceShares / supply, 1e14, "victim keeps her deposit"
        );
        // The donation is shared by everyone who held shares before it, dead shares included.
        uint256 seed = 0.01 ether + preexisting;
        uint256 attackerValue = nav * vault.shareBalance(attacker) / supply;
        // The attacker's donation is shared with the dead shares; it never gets back what it put in.
        assertLt(attackerValue, 0.01 ether + 10 ether - 10 ether * seed / (seed + 0.01 ether) / 2);
        assertLt(attackerValue, 10.01 ether, "attacker loses part of the donation to the seed");
    }

    function test_hostileNftRejected() public {
        HostileNft h = new HostileNft();
        h.mint(address(this), 1);
        vm.expectRevert(PackVault.UnknownNft.selector);
        h.safeTransferFrom(address(this), address(vault), 1);
    }

    function test_reentrantHolderClaimsOnce() public {
        ReentrantHolder r = new ReentrantHolder(vault);
        vm.deal(address(r), 0);
        r.deposit{value: Charges.grossFor(vault, 1 ether)}(); // escrows exactly 1 ETH
        toBlackout();
        checkpoint();
        toOpen();
        r.redeemAll{value: Charges.redeemCharge(vault, vault.shareBalance(address(r)))}(); // exact: no refund
        toBlackout();
        checkpoint();
        uint256 owed = vault.claimableEth(address(r));
        r.claim();
        // The holder bears its share of keeper gas paid after its pricing (two checkpoints at
        // 0.2 gwei, about 4e13 wei), and holder-side rounding is down: never over.
        // Its own redemption charge joined the vault's value before its fill (it is nearly the
        // only holder), so it gets about that back too.
        assertApproxEqAbs(address(r).balance, 1 ether, 2e15, "claimed its redemption");
        assertEq(owed, 0, "claimable is settled lazily inside claim");
        assertEq(r.reentryReverted(), 1, "re-entry from receive reverted");
        vm.expectRevert(PackVault.Nothing.selector);
        r.claim();
    }

    function test_distributionPaysGainsOnce() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
        assertGe(address(vault).balance, 0.01 ether); // deploy addresses can hold mainnet dust
        {
            uint256 gross_ = Charges.grossFor(vault, 4 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        new ForceSender{value: 1 ether}(payable(address(vault)));
        toBlackout();
        checkpoint();
        uint256 distributed = vault.distributionReserve();
        // 20% of the 1 ETH gain above the high-water mark, less the first checkpoint's keeper pay
        // (paid after pricing, so it lowers the next gain).
        assertApproxEqAbs(distributed, 0.2 ether, 2e13);
        assertLe(distributed, 0.2 ether);
        uint256 supply = vault.totalShares();
        // Distributions accrue to live shares only (D13): alice holds all of them.
        uint256 aliceShare = distributed * vault.shareBalance(alice) / (supply - vault.DEAD_SHARES());
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertApproxEqAbs(alice.balance - before, aliceShare, 1e6);
        // Next checkpoint with no new gain distributes nothing: it reverts and leaves the slot free (E3).
        toOpen();
        toBlackout();
        uint256 planned18 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned18, 0);
        assertApproxEqAbs(vault.distributionReserve(), distributed - (alice.balance - before), 1);
        // Nothing strands: after alice claims, only rounding dust remains reserved.
        assertLe(vault.distributionReserve(), 1e6);
    }

    /// Review finding (repair of L1): after every holder exits, a gain with distributions on
    /// divided by zero live shares and bricked checkpoints for new depositors.
    function test_checkpointAfterAllHoldersExitAndGain() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether);
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }
        toBlackout();
        checkpoint();
        assertEq(vault.totalShares(), vault.DEAD_SHARES());
        toOpen();
        new ForceSender{value: 0.5 ether}(payable(address(vault)));
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(bob);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint(); // must not revert
        assertGt(vault.shareBalance(bob), 0);
        assertEq(vault.distributionReserve(), 0, "no live shares, nothing distributed");
    }

    uint256 constant TX_GAS_CAP = 16_777_216; // EIP-7825 (Fusaka) per-transaction gas cap

    /// Actual listings cross the former ceiling. Fixture construction is separate from the
    /// checkpoint, whose bounded valuation must fit EIP-7825 with the keeper margin.
    function test_checkpointGasWith301RealListings() public {
        uint256 n = 301;
        VaultLib.Params memory p = defaultParams();

        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 25 ether);
        for (uint256 i; i < n; i += 10) {
            uint256 count = n - i < 10 ? n - i : 10;
            TestVaultOps.restock(vault, count, 3, 0);
            TestVaultOps.list(vault, count, 0);
        }
        assertEq(TestVaultOps.open(vault).length, n);
        (uint256 tracked,, uint256 activeBacking, uint256 activeCount,,) = vault.totals();
        assertEq(activeCount, 301); assertEq(tracked, 9.1 ether, "ninety-one real paid mints back the packs and seven loose Shapes");
        assertGt(activeBacking, 10 ether);
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        bytes memory input = abi.encodeCall(PackVault.checkpoint, (witness, 0));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(policy);
        uint256 g = gasleft();
        (bool ok, bytes memory result) = address(vault).call{gas: TX_GAS_CAP - intrinsic}(input);
        uint256 used = g - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        emit log_named_uint("cold complete checkpoint gas with 301 real listings", used);
        assertLt(used * 125 / 100, TX_GAS_CAP, "complete operation plus 25% keeper margin");
    }

    /// Kicks are actual cash receipts; pricing waits for their bounded reconciliation.
    function test_kickedReceiptsBlockPricingUntilReconciled() public {
        uint256[] memory ids = _listNForAccounting(10);
        setPackAsk(0.03 ether);
        toBlackout();
        for (uint256 i; i < ids.length; ++i) IFwaAdmin(address(FWA)).kickListing(ids[i]);
        uint256 gross = Charges.grossFor(vault, 0.1 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        assertEq(vault.pendingReceipts(), ids.length);
        vm.expectRevert();
        vault.checkpoint(0, 0);
        TestVaultOps.sync(vault, ids, 0);
        assertEq(vault.pendingReceipts(), 0);
        uint256 start = gasleft();
        vault.checkpoint(0, 0);
        assertLt((start - gasleft()) * 125 / 100, TX_GAS_CAP);
    }

    function _listNForAccounting(uint256 n) internal returns (uint256[] memory) {
        uint256 gross = Charges.grossFor(vault, 2 ether);
        vm.prank(alice);
        vault.deposit{value: gross}();
        toBlackout();
        checkpoint();
        toOpen();
        TestVaultOps.restock(vault, n, 3, 0);
        TestVaultOps.list(vault, n, 0);
        return TestVaultOps.open(vault);
    }

    /// Every keeper batch the reference keeper sends fits the transaction cap.
    function test_keeperBatchesFitTxCap() public {
        VaultLib.Params memory p = defaultParams();
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 10 ether);
        uint256[] memory proposals = TestVaultOps.buildProposals(vault, 10, 3);
        uint256 g = gasleft();
        vault.restock{gas: TX_GAS_CAP}(3, proposals, 0);
        emit log_named_uint("restock 10 packs", g - gasleft());
        proposals = TestVaultOps.proposals(vault, vault.MAX_LIST_BATCH(), 3);
        g = gasleft();
        vault.list{gas: TX_GAS_CAP}(proposals, 0);
        emit log_named_uint("list 8", g - gasleft());
        TestVaultOps.list(vault, 2, 0);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory ids = TestVaultOps.open(vault);
        g = gasleft();
        vault.unlist{gas: TX_GAS_CAP}(ids, 0);
        emit log_named_uint("unlist 10", g - gasleft());
        g = gasleft();
        vault.liquidate{gas: TX_GAS_CAP}(40, 0);
        emit log_named_uint("liquidate 10 packs + loose", g - gasleft());
        assertEq(TestVaultOps.idle(vault).length, 0);
    }

    /// Repair: with the old 5% keeper fee, a bid cycle lost money for holders (0.05 kB = 1.885
    /// mETH > B (k - 1) = 1.396 mETH). Now no fee is skimmed: every harvested wei is NAV, and
    /// the only keeper cost is reimbursed gas.
    function test_noFeeSkimOnHarvest() public {
        assertEq(address(vault).balance, 0.01 ether + preexisting);
        uint256 ck = vault.requestCharge();
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        uint256 kBefore = keeper.balance;
        checkpoint();
        assertGt(keeper.balance, kBefore, "a checkpoint pricing a deposit is paid");
        // The keeper's pay came out of the request charge; the rest of the charge joins the
        // vault's ETH after pricing. Nothing else is set aside from NAV.
        assertEq(address(vault).balance + (keeper.balance - kBefore), vault.lastNav() + ck);
    }

    /// Repair: a checkpoint with no holder flows pays nothing (it cost about 6M gas at 150
    /// positions and could be farmed every 12 hours).
    function test_idleCheckpointUnpaid() public {
        // Review LOW-1: with no flows and distributions off, a checkpoint is refused, so nobody
        // can use up the interval's slot ahead of a deposit arriving later in the blackout.
        toBlackout();
        uint256 planned17 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned17, 0);
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        uint256 kBefore = keeper.balance;
        checkpoint(); // the same blackout still prices the deposit, paid
        assertGt(keeper.balance, kBefore);
        assertGt(vault.shareBalance(alice), 0);
    }

    /// Repair: restock spent ETH on packs whatever the gate said and whether or not they could be
    /// listed. Now it needs the live edge, payback within one cycle, and capital for the backing.
    function test_restockGated() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 0.3 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256[] memory planned16 = TestVaultOps.buildProposals(vault, 5, 3);
        vm.startPrank(keeper);
        // Capital: 0.26 ETH above the reserve covers two 0.101 mints, not five packs' backing on top.
        vm.expectRevert(VaultLib.InsufficientBacking.selector);
        vault.restock(3, planned16, 0);
        uint256[] memory planned15 = TestVaultOps.proposals(vault, 1, 3);
        // Gas: at 3 gwei (under the 5 gwei ceiling) a pack's build cost exceeds one cycle's net.
        vm.fee(3 gwei);
        vm.txGasPrice(3 gwei);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.restock(3, planned15, 0);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        TestVaultOps.restock(vault, 1, 3, 0);
        vm.stopPrank();
    }

    /// Repair: ETH freed for redeemers could be relisted, so a keeper could loop unlist -> list
    /// and be paid both ways while redemptions never filled.
    function test_unlistListLoopClosed() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, 6, 3, 0);
        TestVaultOps.list(vault, 6, 0);
        vm.stopPrank();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.startPrank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        // The freed backing and packs are owed to alice: nothing can be listed or restocked.
        assertEq(vault.idleEth(), 0);
        uint256[] memory planned14 = TestVaultOps.proposals(vault, 6, 3);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(planned14, 0);
        vm.stopPrank();
    }

    /// Repair (custody): a filled redemption settled into a holder's claimable balance by another
    /// action (here a new deposit) but not yet claimed was counted as free ETH, so keepers could
    /// list it or be paid from it, and the later claim would take other holders' ETH.
    function test_settledUnclaimedEthIsNotDeployable() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(bob);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }
        toBlackout();
        checkpoint(); // fills alice in full from free ETH
        toOpen();
        assertEq(vault.lockedShares(), 0);
        uint256 reserved = vault.redemptionReserve();
        assertGt(reserved, 0.9 ether);
        // Alice touches the vault without claiming: her entitlement moves to claimableEth.
        {
            uint256 gross_ = Charges.grossFor(vault, 0.01 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        assertEq(vault.claimableTotal(), vault.claimableEth(alice));
        assertApproxEqAbs(vault.claimableEth(alice), reserved, 2);
        // Idle ETH excludes it: keepers can deploy only bob's capital and the seed.
        uint256 liabilities = vault.pendingDepositTotal() + vault.redemptionReserve()
            + vault.distributionReserve() + vault.claimableTotal();
        assertLe(vault.idleEth(), address(vault).balance - liabilities);
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, 10, 3, 0);
        TestVaultOps.list(vault, 10, 0);
        uint256[] memory planned13 = TestVaultOps.buildProposals(vault, 10, 3);
        vm.expectRevert(); // nothing more is deployable
        vault.restock(3, planned13, 0);
        vm.stopPrank();
        assertGe(address(vault).balance, liabilities, "liabilities never spent");
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertApproxEqAbs(alice.balance - before, reserved, 2, "claim paid in full");
    }

    /// Liquidation only runs when redeemers need ETH (or in wind-down).
    function test_liquidateOnlyWhenNeeded() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 3, 3, 0);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.liquidate(10, 0);
    }

    function test_depositAboveTvlCapReverts() public {
        lowerTo(1 ether, 5 gwei, 0.00002 ether);
        vm.prank(alice);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 1.5 ether}();
    }

    function test_checkpointWindowRules() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        uint256 planned12 = TestVaultOps.witness(vault);
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint(planned12, 0);
        toBlackout();
        uint256 planned11 = TestVaultOps.witness(vault);
        vault.checkpoint(planned11, 0);
        uint256 planned10 = TestVaultOps.witness(vault);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint(planned10, 0);
    }
}
