// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, ForceSender, IFwaAdmin} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
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

    function redeemAll() external {
        vault.requestRedeem(vault.shareBalance(address(this)));
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
    uint256 constant PER_GAS = 0.22 gwei; // min(0.2 bid, 0.15 basefee + 0.05 maxTip, 5 ceiling) x 1.10

    /// D55: the work fee is paid per unit of work, not per call. Listing three packs in one call and
    /// in three calls earns the same fee (3 units); only the per-call gas overhead differs. Each
    /// pay is exactly gas x 0.22 gwei plus units x workFee, and a checkpoint that priced flows is
    /// one unit.
    function test_workFeePerUnitNotPerCall() public {
        uint256 fee = vault.getParams().workFee;
        assertEq(fee, 0.00002 ether);
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        uint256 cp = keeper.balance;
        checkpoint();
        cp = keeper.balance - cp;
        assertEq((cp - fee) % PER_GAS, 0, "checkpoint with flows: gas + 1 unit");
        toOpen();
        vm.prank(keeper);
        vault.restock(3, 3);
        uint256 snap = vm.snapshotState();

        uint256 b = keeper.balance;
        vm.prank(keeper);
        vault.list(3);
        uint256 one = keeper.balance - b;
        assertEq((one - 3 * fee) % PER_GAS, 0, "one call: gas + 3 units");
        assertGt(one - 3 * fee, 0);

        vm.revertToState(snap);
        uint256 split;
        for (uint256 i; i < 3; ++i) {
            b = keeper.balance;
            vm.prank(keeper);
            vault.list(1);
            uint256 pay = keeper.balance - b;
            assertEq((pay - fee) % PER_GAS, 0, "split call: gas + 1 unit");
            split += pay;
        }
        // Same 3 units of fee either way. Splitting is paid more only as gas: separate calls write
        // FWA's storage cold, so the keeper also spends that gas; the difference carries no fee.
        assertGt(split, one);
        assertEq((split - one) % PER_GAS, 0, "the split premium is gas reimbursement only, no extra fee");
        // Nothing to list: the call reverts, so no fee.
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(1);
    }

    function test_workFeeBounded() public {
        PackVault.Params memory p = defaultParams();
        p.workFee = uint64(vault.MAX_WORK_FEE() + 1);
        vm.prank(admin);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.proposeParams(p);
        p.workFee = uint64(vault.MAX_WORK_FEE());
        vm.prank(admin);
        vault.proposeParams(p);
        // The guardian lowers the fee at once (never raises it); with the ceiling at 0 no pay remains.
        vm.startPrank(guardian);
        vm.expectRevert(PackVault.OutOfBounds.selector);
        vault.lowerCaps(100 ether, 150, 5 gwei, 0.00003 ether);
        vault.lowerCaps(100 ether, 150, 0, 0);
        vm.stopPrank();
        assertEq(vault.getParams().workFee, 0);
        assertEq(vault.getParams().gasCeiling, 0);
        // The admin's queued proposal (made above) was cancelled by the stop: it cannot restore the
        // old fee or ceiling when its delay passes.
        assertEq(vault.pendingParamsEta(), 0);
        vm.warp(block.timestamp + 3 days);
        vm.expectRevert(PackVault.TooEarly.selector);
        vault.applyParams();
        assertEq(vault.getParams().workFee, 0);
    }

    /// D51: above the gas ceiling a build is accepted and reimbursed at the ceiling price only; the
    ///      caller pays the rest. The guardian lowers the ceiling to the canary's 0.5 gwei (at 5 gwei
    ///      a build fails its own payback gate). Exact pay: (gas measured + 30k) x 0.5 gwei x 1.10.
    function test_buildAboveCeilingPaidAtCeilingPrice() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(guardian);
        vault.lowerCaps(100 ether, 150, 0.5 gwei, 0.00002 ether);
        vm.fee(1.9 gwei);
        vm.txGasPrice(2 gwei); // four times the ceiling; basefee + maxTip is above it too
        uint256 idle0 = vault.idlePacks().length;
        uint256 kb = keeper.balance;
        vm.recordLogs();
        vm.prank(keeper);
        vault.restock(1, 3);
        assertEq(vault.idlePacks().length, idle0 + 1, "built above the ceiling");
        uint256 pay = keeper.balance - kb;
        assertGt(pay, 0);
        assertEq(pay % 0.55 gwei, 0, "priced at 0.5 gwei x 1.10 per gas, a whole number of gas units");
        uint256 gasPaid = pay / 0.55 gwei;
        // One pack from no loose Shapes: a whole 0.1 ETH mint split into ten, then packed (~2.77M).
        assertGt(gasPaid, 2_000_000);
        assertLt(gasPaid, 3_200_000);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function test_forcedEthAccruesToHolders_firstDepositorCannotInflate() public {
        // Attacker is first depositor with the minimum, then donates 10 ETH before the victim prices.
        address attacker = makeAddr("pack-vault-test-attacker");
        vm.deal(attacker, 20 ether);
        vm.prank(attacker);
        vault.deposit{value: 0.01 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(attacker);
        new ForceSender{value: 10 ether}(payable(address(vault)));
        vm.prank(alice);
        vault.deposit{value: 5 ether}();
        toBlackout();
        checkpoint();

        uint256 supply = vault.totalShares();
        uint256 aliceShares = vault.shareBalance(alice);
        uint256 nav = vault.lastNav();
        // Alice's claim on NAV equals what she paid in, less her share of the last checkpoint's
        // keeper pay (about 4e13 wei at 0.2 gwei, paid after pricing).
        assertApproxEqAbs(nav * aliceShares / supply, 5 ether, 1e14, "victim keeps her deposit");
        // The donation is shared by everyone who held shares before it, dead shares included.
        uint256 seed = 0.01 ether + preexisting;
        uint256 attackerValue = nav * vault.shareBalance(attacker) / supply;
        assertApproxEqAbs(attackerValue, (0.01 ether + 10 ether) - 10 ether * seed / (seed + 0.01 ether), 1e14);
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
        r.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        r.redeemAll();
        toBlackout();
        checkpoint();
        uint256 owed = vault.claimableEth(address(r));
        r.claim();
        // The holder bears its share of keeper gas paid after its pricing (two checkpoints at
        // 0.2 gwei, about 4e13 wei), and holder-side rounding is down: never over.
        assertApproxEqAbs(address(r).balance, 1 ether, 1e14, "claimed its redemption");
        assertLe(address(r).balance, 1 ether);
        assertEq(owed, 0, "claimable is settled lazily inside claim");
        assertEq(r.reentryReverted(), 1, "re-entry from receive reverted");
        vm.expectRevert(PackVault.Nothing.selector);
        r.claim();
    }

    function test_distributionPaysGainsOnce() public {
        PackVault.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        assertGe(address(vault).balance, 0.01 ether); // deploy addresses can hold mainnet dust
        vm.prank(alice);
        vault.deposit{value: 4 ether}();
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
        // Next checkpoint with no new gain pays nothing more.
        toOpen();
        toBlackout();
        checkpoint();
        assertApproxEqAbs(vault.distributionReserve(), distributed - (alice.balance - before), 1);
        // Nothing strands: after alice claims, only rounding dust remains reserved.
        assertLe(vault.distributionReserve(), 1e6);
    }

    /// Review finding (repair of L1): after every holder exits, a gain with distributions on
    /// divided by zero live shares and bricked checkpoints for new depositors.
    function test_checkpointAfterAllHoldersExitAndGain() public {
        PackVault.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        vault = new PackVault{value: 0.01 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(shares);
        toBlackout();
        checkpoint();
        assertEq(vault.totalShares(), vault.DEAD_SHARES());
        toOpen();
        new ForceSender{value: 0.5 ether}(payable(address(vault)));
        vm.prank(bob);
        vault.deposit{value: 1 ether}();
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
        PackVault.Params memory p = defaultParams();
        p.maxPositions = uint96(n);
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 25 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        for (uint256 i; i < n; i += 10) {
            vault.restock(10, 3);
            vault.list(10);
        }
        assertEq(vault.openListings().length, n);
        vm.prank(alice);
        vault.deposit{value: 0.1 ether}();
        toBlackout();
        uint256 g = gasleft();
        vault.checkpoint{gas: TX_GAS_CAP - 100_000}();
        uint256 used = g - gasleft();
        emit log_named_uint("checkpoint gas at MAX_POSITIONS", used);
        assertLt(used, TX_GAS_CAP * 80 / 100, "20% margin under the transaction cap");
    }

    /// Worst supported state for the checkpoint loop: every position settled or withdrawn but not
    /// yet synced (ownership read per position), produced here by real kicks after the oracle
    /// owner lowers the ask, plus a pending deposit to price.
    function test_checkpointGasAllPositionsKickedUnsynced() public {
        uint256 n = vault.MAX_POSITIONS();
        PackVault.Params memory p = defaultParams();
        p.maxPositions = uint96(n);
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 25 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        uint256 seed = address(vault).balance;
        uint256 b0 = address(this).balance;
        for (uint256 i; i < n; i += 10) {
            vault.restock(10, 3);
            vault.list(10);
        }
        uint256 buildPay = address(this).balance - b0; // this contract was the paid keeper
        uint256[] memory ids = vault.openListings();
        setPackAsk(0.03 ether); // cap 0.033 < posted 0.0363: every position may be kicked
        toBlackout();
        for (uint256 i; i < ids.length; ++i) {
            IFwaAdmin(address(FWA)).kickListing(ids[i]);
        }
        vm.prank(alice);
        vault.deposit{value: 0.1 ether}();
        uint256 g = gasleft();
        vault.checkpoint{gas: TX_GAS_CAP - 100_000}();
        uint256 used = g - gasleft();
        emit log_named_uint("checkpoint gas, 300 kicked unsynced", used);
        assertLt(used, TX_GAS_CAP * 80 / 100);
        // Valued at the packs held (backing already back in the balance): NAV is seed + deposit
        // less 90 mint fees and the build's keeper pay, to the wei.
        assertEq(vault.lastNav(), seed + 0.1 ether - 90 * 0.001 ether - buildPay);
    }

    /// Every keeper batch the reference keeper sends fits the transaction cap.
    function test_keeperBatchesFitTxCap() public {
        PackVault.Params memory p = defaultParams();
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = new PackVault{value: 10 ether}(FWA, SHAPES, PACKS, guardian, admin, 2 days, p);
        uint256 g = gasleft();
        vault.restock{gas: TX_GAS_CAP}(10, 3);
        emit log_named_uint("restock 10 packs", g - gasleft());
        g = gasleft();
        vault.list{gas: TX_GAS_CAP}(10);
        emit log_named_uint("list 10", g - gasleft());
        vm.prank(guardian);
        vault.startWindDown();
        uint256[] memory ids = vault.openListings();
        g = gasleft();
        vault.unlist{gas: TX_GAS_CAP}(ids);
        emit log_named_uint("unlist 10", g - gasleft());
        g = gasleft();
        vault.liquidate{gas: TX_GAS_CAP}(40);
        emit log_named_uint("liquidate 10 packs + loose", g - gasleft());
        assertEq(vault.idlePacks().length, 0);
    }

    /// Repair: with the old 5% keeper fee, a bid cycle lost money for holders (0.05 kB = 1.885
    /// mETH > B (k - 1) = 1.396 mETH). Now no fee is skimmed: every harvested wei is NAV, and
    /// the only keeper cost is reimbursed gas.
    function test_noFeeSkimOnHarvest() public {
        assertEq(address(vault).balance, 0.01 ether + preexisting);
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        uint256 kBefore = keeper.balance;
        checkpoint();
        assertGt(keeper.balance, kBefore, "a checkpoint pricing a deposit is paid");
        // The keeper's pay came out of free ETH after pricing; nothing else is set aside from NAV.
        assertEq(address(vault).balance + (keeper.balance - kBefore), vault.lastNav());
    }

    /// Repair: a checkpoint with no holder flows pays nothing (it cost about 6M gas at 150
    /// positions and could be farmed every 12 hours).
    function test_idleCheckpointUnpaid() public {
        // Review LOW-1: with no flows and distributions off, a checkpoint is refused, so nobody
        // can use up the interval's slot ahead of a deposit arriving later in the blackout.
        toBlackout();
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint();
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        uint256 kBefore = keeper.balance;
        checkpoint(); // the same blackout still prices the deposit, paid
        assertGt(keeper.balance, kBefore);
        assertGt(vault.shareBalance(alice), 0);
    }

    /// Repair: restock spent ETH on packs whatever the gate said and whether or not they could be
    /// listed. Now it needs the live edge, payback within one cycle, and capital for the backing.
    function test_restockGated() public {
        vm.prank(alice);
        vault.deposit{value: 0.3 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        // Capital: 0.26 ETH above the reserve covers two 0.101 mints, not five packs' backing on top.
        vm.expectRevert(PackVault.Liquidity.selector);
        vault.restock(5, 3);
        // Gas: at 3 gwei (under the 5 gwei ceiling) a pack's build cost exceeds one cycle's net.
        vm.fee(3 gwei);
        vm.txGasPrice(3 gwei);
        vm.expectRevert(PackVault.EdgeGate.selector);
        vault.restock(1, 3);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        vault.restock(1, 3);
        vm.stopPrank();
    }

    /// Repair: ETH freed for redeemers could be relisted, so a keeper could loop unlist -> list
    /// and be paid both ways while redemptions never filled.
    function test_unlistListLoopClosed() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.startPrank(keeper);
        vault.restock(6, 3);
        vault.list(6);
        vm.stopPrank();
        uint256 shares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(shares);
        uint256[] memory ids = vault.openListings();
        vm.startPrank(keeper);
        vault.unlist(ids);
        // The freed backing and packs are owed to alice: nothing can be listed or restocked.
        assertEq(vault.idleEth(), 0);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(6);
        vm.stopPrank();
    }

    /// Repair (custody): a filled redemption settled into a holder's claimable balance by another
    /// action (here a new deposit) but not yet claimed was counted as free ETH, so keepers could
    /// list it or be paid from it, and the later claim would take other holders' ETH.
    function test_settledUnclaimedEthIsNotDeployable() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        vm.prank(bob);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        vm.prank(alice);
        vault.requestRedeem(shares);
        toBlackout();
        checkpoint(); // fills alice in full from free ETH
        toOpen();
        assertEq(vault.lockedShares(), 0);
        uint256 reserved = vault.redemptionReserve();
        assertGt(reserved, 0.9 ether);
        // Alice touches the vault without claiming: her entitlement moves to claimableEth.
        vm.prank(alice);
        vault.deposit{value: 0.01 ether}();
        assertEq(vault.claimableTotal(), vault.claimableEth(alice));
        assertApproxEqAbs(vault.claimableEth(alice), reserved, 2);
        // Idle ETH excludes it: keepers can deploy only bob's capital and the seed.
        uint256 liabilities = vault.pendingDepositTotal() + vault.redemptionReserve()
            + vault.distributionReserve() + vault.claimableTotal();
        assertLe(vault.idleEth(), address(vault).balance - liabilities);
        vm.startPrank(keeper);
        vault.restock(10, 3);
        vault.list(10);
        vm.expectRevert(); // nothing more is deployable
        vault.restock(10, 3);
        vm.stopPrank();
        assertGe(address(vault).balance, liabilities, "liabilities never spent");
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertApproxEqAbs(alice.balance - before, reserved, 2, "claim paid in full");
    }

    /// Liquidation only runs when redeemers need ETH (or in wind-down).
    function test_liquidateOnlyWhenNeeded() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        vault.restock(3, 3);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.liquidate(10);
    }

    function test_depositAboveTvlCapReverts() public {
        vm.prank(guardian);
        vault.lowerCaps(1 ether, 150, 5 gwei, 0.00002 ether);
        vm.prank(alice);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 1.5 ether}();
    }

    function test_checkpointWindowRules() public {
        vm.prank(alice);
        vault.deposit{value: 0.1 ether}();
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint();
        toBlackout();
        vault.checkpoint();
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint();
    }
}
