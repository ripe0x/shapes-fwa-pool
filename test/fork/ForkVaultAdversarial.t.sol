// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

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
        lowerTo(100 ether, 150, 0, 0);
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
        lowerTo(100 ether, 150, 0.3 gwei, 0.00002 ether);
        vm.fee(1.9 gwei);
        vm.txGasPrice(2 gwei); // well above the ceiling
        uint256 idle0 = vault.idlePacks().length;
        uint256 kb = keeper.balance;
        vm.prank(keeper);
        uint256 pay = vault.restock(1, 3, 0);
        assertEq(vault.idlePacks().length, idle0 + 1, "built above the ceiling");
        assertEq(keeper.balance - kb, pay);
        assertEq(pay, 2_680_000 * 0.3 gwei + vault.getParams().workFee, "quote at the ceiling price + one pack's work fee");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function test_forcedEthAccruesToHolders_firstDepositorCannotInflate() public {
        // Attacker is first depositor with the minimum, then donates 10 ETH before the victim prices.
        address attacker = makeAddr("pack-vault-test-attacker");
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
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
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
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(0);
        assertApproxEqAbs(vault.distributionReserve(), distributed - (alice.balance - before), 1);
        // Nothing strands: after alice claims, only rounding dust remains reserved.
        assertLe(vault.distributionReserve(), 1e6);
    }

    /// Review finding (repair of L1): after every holder exits, a gain with distributions on
    /// divided by zero live shares and bricked checkpoints for new depositors.
    function test_checkpointAfterAllHoldersExitAndGain() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
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

    /// Limits at maximum: the checkpoint loop over every position must fit EIP-7825's per-
    /// transaction cap with margin. Old code: 16.08M at 400 positions, 4% under the cap.
    function test_checkpointGasAtMaxPositions() public {
        uint256 n = vault.MAX_POSITIONS();
        VaultLib.Params memory p = defaultParams();
        p.maxPositions = uint96(n);
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 25 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
        for (uint256 i; i < n; i += 10) {
            vault.restock(10, 3, 0);
            vault.list(10, 0);
        }
        assertEq(vault.openListings().length, n);
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        toBlackout();
        uint256 g = gasleft();
        vault.checkpoint{gas: TX_GAS_CAP - 100_000}(0);
        uint256 used = g - gasleft();
        emit log_named_uint("checkpoint gas at MAX_POSITIONS", used);
        assertLt(used, TX_GAS_CAP * 80 / 100, "20% margin under the transaction cap");
    }

    /// Worst supported state for the checkpoint loop: every position settled or withdrawn but not
    /// yet synced (ownership read per position), produced here by real kicks after the oracle
    /// owner lowers the ask, plus a pending deposit to price.
    function test_checkpointGasAllPositionsKickedUnsynced() public {
        uint256 n = vault.MAX_POSITIONS();
        VaultLib.Params memory p = defaultParams();
        p.maxPositions = uint96(n);
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 25 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
        uint256 seed = address(vault).balance;
        uint256 b0 = address(this).balance;
        for (uint256 i; i < n; i += 10) {
            vault.restock(10, 3, 0);
            vault.list(10, 0);
        }
        uint256 buildPay = address(this).balance - b0; // this contract was the paid keeper
        uint256[] memory ids = vault.openListings();
        setPackAsk(0.03 ether); // cap 0.033 < posted 0.0363: every position may be kicked
        toBlackout();
        for (uint256 i; i < ids.length; ++i) {
            IFwaAdmin(address(FWA)).kickListing(ids[i]);
        }
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            vm.prank(alice);
            vault.deposit{value: gross_}();
        }
        uint256 g = gasleft();
        vault.checkpoint{gas: TX_GAS_CAP - 100_000}(0);
        uint256 used = g - gasleft();
        emit log_named_uint("checkpoint gas, 300 kicked unsynced", used);
        assertLt(used, TX_GAS_CAP * 80 / 100);
        // Valued at the packs held (backing already back in the balance): NAV is seed + deposit
        // less 90 mint fees and the build's keeper pay, to the wei.
        assertEq(vault.lastNav(), seed + 0.1 ether - 90 * 0.001 ether - buildPay);
    }

    /// Every keeper batch the reference keeper sends fits the transaction cap.
    function test_keeperBatchesFitTxCap() public {
        VaultLib.Params memory p = defaultParams();
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 10 ether}(FWA, SHAPES, PACKS, owner, p, new KeeperPolicyV1());
        uint256 g = gasleft();
        vault.restock{gas: TX_GAS_CAP}(10, 3, 0);
        emit log_named_uint("restock 10 packs", g - gasleft());
        g = gasleft();
        vault.list{gas: TX_GAS_CAP}(10, 0);
        emit log_named_uint("list 10", g - gasleft());
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory ids = vault.openListings();
        g = gasleft();
        vault.unlist{gas: TX_GAS_CAP}(ids, 0);
        emit log_named_uint("unlist 10", g - gasleft());
        g = gasleft();
        vault.liquidate{gas: TX_GAS_CAP}(40, 0);
        emit log_named_uint("liquidate 10 packs + loose", g - gasleft());
        assertEq(vault.idlePacks().length, 0);
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
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(0);
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
        vm.startPrank(keeper);
        // Capital: 0.26 ETH above the reserve covers two 0.101 mints, not five packs' backing on top.
        vm.expectRevert(PackVault.Liquidity.selector);
        vault.restock(5, 3, 0);
        // Gas: at 3 gwei (under the 5 gwei ceiling) a pack's build cost exceeds one cycle's net.
        vm.fee(3 gwei);
        vm.txGasPrice(3 gwei);
        vm.expectRevert(PackVault.EdgeGate.selector);
        vault.restock(1, 3, 0);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vault.restock(1, 3, 0);
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
        vault.restock(6, 3, 0);
        vault.list(6, 0);
        vm.stopPrank();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares);
        }
        uint256[] memory ids = vault.openListings();
        vm.startPrank(keeper);
        vault.unlist(ids, 0);
        // The freed backing and packs are owed to alice: nothing can be listed or restocked.
        assertEq(vault.idleEth(), 0);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(6, 0);
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
        vault.restock(10, 3, 0);
        vault.list(10, 0);
        vm.expectRevert(); // nothing more is deployable
        vault.restock(10, 3, 0);
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
        vault.restock(3, 3, 0);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.liquidate(10, 0);
    }

    function test_depositAboveTvlCapReverts() public {
        lowerTo(1 ether, 150, 5 gwei, 0.00002 ether);
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
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint(0);
        toBlackout();
        vault.checkpoint(0);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint(0);
    }
}
