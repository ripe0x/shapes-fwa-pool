// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, ForceSender} from "./ForkBase.sol";
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
    function test_gasPriceAboveCeilingBlocksSpending() public {
        vm.prank(alice);
        vault.deposit{value: 1 ether}();
        toBlackout();
        checkpoint();
        toOpen();
        vm.txGasPrice(6 gwei); // ceiling is 5 gwei
        vm.prank(keeper);
        vm.expectRevert(PackVault.GasPrice.selector);
        vault.restock(1, 3);
        vm.txGasPrice(0.2 gwei);
        vm.prank(keeper);
        vault.restock(1, 3);
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
        toBlackout();
        uint256 kBefore = keeper.balance;
        checkpoint();
        assertEq(keeper.balance, kBefore);
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
        vault.lowerCaps(1 ether, 150, 5 gwei);
        vm.prank(alice);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 1.5 ether}();
    }

    function test_checkpointWindowRules() public {
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint();
        toBlackout();
        vault.checkpoint();
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint();
    }
}
