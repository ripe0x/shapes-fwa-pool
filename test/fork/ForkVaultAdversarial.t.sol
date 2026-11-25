// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MeasuredPay} from "../utils/MeasuredPay.sol";

import {GasQuotes} from "../utils/GasQuotes.sol";

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {ForkBase, ForceSender, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
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
        bytes32 _expected0 = vault.configurationHash();
        vault.deposit{value: msg.value}(_expected0);
    }

    function redeemAll() external payable {
        bytes32 _expected1 = vault.configurationHash();
        vault.requestRedeem{value: msg.value}(vault.shareBalance(address(this)), _expected1);
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
        bytes32 _expected2 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(p, _expected2);
        p.workFee = uint64(vault.MAX_WORK_FEE());
        bytes32 _expected3 = TestVaultOps.configurationHash(vault);
        vm.prank(owner);
        vault.setParams(p, _expected3);
        assertEq(vault.getParams().workFee, vault.MAX_WORK_FEE(), "applied at once (D58)");
        // With the ceiling and fee at 0 no pay remains.
        lowerTo(100 ether, 0, 0);
        assertEq(vault.getParams().workFee, 0);
        assertEq(vault.getParams().gasCeiling, 0);
    }

    /// D51/D56: above the gas ceiling a build is accepted and paid its quote at the ceiling price;
    ///      the caller pays the rest. One built six-unit pack is quoted Q_BUILD call base +
    ///      (buildGas(2) + Q_LISTED), at the ceiling price (V1: no markup), plus two work-unit fees.
    function test_buildAboveCeilingPaidAtCeilingPrice() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected4 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected4);
        }
        toBlackout();
        checkpoint();
        toOpen();
        lowerTo(100 ether, 0.25 gwei, 0.00002 ether);
        VaultLib.Params memory affordable = vault.getParams(); affordable.backingRatioBps = 15_000;
        bytes32 affordableConfig = vault.configurationHash();
        vm.prank(owner); vault.setParams(affordable, affordableConfig);
        vm.fee(1.9 gwei);
        vm.txGasPrice(2 gwei); // well above the ceiling
        uint256 open0 = TestVaultOps.open(vault).length;
        uint256 kb = keeper.balance;
        vm.prank(keeper);
        uint256 pay = TestVaultOps.restock(vault, 1, UNITS, 0);
        assertEq(TestVaultOps.open(vault).length, open0 + 1, "built and listed above the ceiling");
        assertEq(keeper.balance - kb, pay);
        assertEq(pay, MeasuredPay.gross(vault,
            GasQuotes.Q_BUILD + GasQuotes.buildGas(2) + GasQuotes.Q_LISTED, 2, false, 0.25 gwei));
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
            bytes32 _expected5 = TestVaultOps.configurationHash(vault);
            vm.prank(attacker);
            vault.deposit{value: gross_}(_expected5);
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(attacker);
        new ForceSender{value: 10 ether}(payable(address(vault)));
        {
            uint256 gross_ = Charges.grossFor(vault, 5 ether);
            bytes32 _expected6 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected6);
        }
        toBlackout();
        checkpoint();

        uint256 supply = vault.totalShares();
        uint256 aliceShares = vault.shareBalance(alice);
        uint256 nav = vault.lastNav();
        // Alice's claim on NAV equals her escrow less its deployment charge (that charge joins the
        // vault's value, shared by all holders, to pay for building positions with her ETH).
        uint256 charge = 5 ether * vault.deployCharge() / (vault.positionValue() + vault.deployCharge());
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
        vm.expectRevert(PackAccount.UnknownNft.selector);
        h.safeTransferFrom(address(this), address(vault), 1);
    }

    function test_reentrantHolderClaimsOnce() public {
        ReentrantHolder r = new ReentrantHolder(vault);
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
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        assertGe(address(vault).balance, 0.01 ether); // deploy addresses can hold mainnet dust
        {
            uint256 gross_ = Charges.grossFor(vault, 4 ether);
            bytes32 _expected7 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected7);
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
        bytes32 _expected8 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned18, 0, _expected8);
        assertApproxEqAbs(vault.distributionReserve(), distributed - (alice.balance - before), 1);
        // Nothing strands: after alice claims, only rounding dust remains reserved.
        assertLe(vault.distributionReserve(), 1e6);
    }

    /// Review finding (repair of L1): after every holder exits, a gain with distributions on
    /// divided by zero live shares and bricked checkpoints for new depositors.
    function test_checkpointAfterAllHoldersExitAndGain() public {
        VaultLib.Params memory p = defaultParams();
        p.distributionBps = 2_000;
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 0.01 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected9 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected9);
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            bytes32 _expected10 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares, _expected10);
        }
        toBlackout();
        checkpoint();
        assertEq(vault.totalShares(), vault.DEAD_SHARES());
        toOpen();
        new ForceSender{value: 0.5 ether}(payable(address(vault)));
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected11 = TestVaultOps.configurationHash(vault);
            vm.prank(bob);
            vault.deposit{value: gross_}(_expected11);
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
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 50 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        for (uint256 i; i < n; i += 10) {
            uint256 count = n - i < 10 ? n - i : 10;
            TestVaultOps.restock(vault, count, UNITS, 0); // build mints and lists at once
        }
        assertEq(TestVaultOps.open(vault).length, n);
        (uint256 tracked,, uint256 activeBacking, uint256 activeCount,,) = vault.totals();
        assertEq(activeCount, 301); assertEq(tracked, 301 * P, "301 six-unit packs: 301 x 0.06 ETH tracked value");
        assertGt(activeBacking, 10 ether);
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            bytes32 _expected12 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected12);
        }
        toBlackout();
        uint256 witness = TestVaultOps.witness(vault);
        bytes memory input = abi.encodeCall(PackVault.checkpoint, (witness, 0, vault.configurationHash()));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;

        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); uint256 g = gasleft();
        (bool ok, bytes memory result) = address(vault).call{gas: TX_GAS_CAP - intrinsic}(input);
        uint256 used = g - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        emit log_named_uint("cold complete checkpoint gas with 301 real listings", used);
        assertLt(used * 125 / 100, TX_GAS_CAP, "complete operation plus 25% keeper margin");
    }

    /// Kicks are actual cash receipts; pricing waits for their bounded reconciliation.
    function test_kickedReceiptsBlockPricingUntilReconciled() public {
        uint256[] memory ids = _listNForAccounting(10);
        // Un-exempt so the oracle cap can bite, then drop the ask below the backing to kick.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(0.03 ether);
        toBlackout();
        for (uint256 i; i < ids.length; ++i) IFwaAdmin(address(FWA)).kickListing(ids[i]);
        uint256 gross = Charges.grossFor(vault, 0.1 ether);
        bytes32 _expected13 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: gross}(_expected13);
        assertEq(vault.pendingReceipts(), ids.length);
        bytes32 _expected14 = TestVaultOps.configurationHash(vault);
        vm.expectRevert();
        vault.checkpoint(0, 0, _expected14);
        TestVaultOps.sync(vault, ids, 0);
        assertEq(vault.pendingReceipts(), 0);
        uint256 start = gasleft();
        bytes32 _expected15 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(0, 0, _expected15);
        assertLt((start - gasleft()) * 125 / 100, TX_GAS_CAP);
    }

    function _listNForAccounting(uint256 n) internal returns (uint256[] memory) {
        uint256 gross = Charges.grossFor(vault, 2 ether);
        bytes32 _expected16 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vault.deposit{value: gross}(_expected16);
        toBlackout();
        checkpoint();
        toOpen();
        TestVaultOps.restock(vault, n, UNITS, 0); // build mints and lists at once
        return TestVaultOps.open(vault);
    }

    /// Every keeper batch the reference keeper sends fits the transaction cap. `build` is the
    /// heaviest listing batch (it mints and lists); a `list` of the same count is strictly cheaper
    /// (no mint), so build and relist have separately bounded batch sizes.
    function test_keeperBatchesFitTxCap() public {
        VaultLib.Params memory p = defaultParams();
        p.reserve = 0;
        vm.deal(address(this), 100 ether);
        vault = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 20 ether, keccak256(abi.encode(p, SHAPES.mintFee(), false, false)));
        // Four max build batches (4 each) -> 16 listed.
        uint256[] memory build4 = TestVaultOps.proposals(vault, vault.MAX_BUILD_BATCH(), UNITS);
        uint256 g = gasleft();
        bytes32 _expected17 = TestVaultOps.configurationHash(vault);
        vault.build{gas: TX_GAS_CAP}(UNITS, build4, 0, _expected17);
        emit log_named_uint("build 4 packs", g - gasleft());
        TestVaultOps.restock(vault, 12, UNITS, 0);
        assertEq(TestVaultOps.open(vault).length, 16);
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory ids = TestVaultOps.open(vault); // 16, one MAX_BATCH
        g = gasleft();
        bytes32 _expected18 = TestVaultOps.configurationHash(vault);
        vault.unlist{gas: TX_GAS_CAP}(ids, 0, _expected18);
        emit log_named_uint("unlist 16", g - gasleft());
        // Liquidate caps at 60 units = 10 six-unit packs per call; two calls clear 16 idle packs.
        g = gasleft();
        bytes32 _expected19 = TestVaultOps.configurationHash(vault);
        vault.liquidate{gas: TX_GAS_CAP}(40, 0, _expected19);
        emit log_named_uint("liquidate 10 packs", g - gasleft());
        bytes32 _expected20 = TestVaultOps.configurationHash(vault);
        vault.liquidate{gas: TX_GAS_CAP}(40, 0, _expected20);
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
            bytes32 _expected21 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected21);
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
        bytes32 _expected22 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned17, 0, _expected22);
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected23 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected23);
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
            bytes32 _expected24 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected24);
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256[] memory planned16 = TestVaultOps.proposals(vault, 4, UNITS);
        vm.startPrank(keeper);
        // Capital: ~0.25 ETH above the reserve cannot cover four six-unit packs (~0.13 ETH each).
        bytes32 _expected25 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InsufficientBacking.selector);
        vault.build(UNITS, planned16, 0, _expected25);
        uint256[] memory planned15 = TestVaultOps.proposals(vault, 1, UNITS);
        // Gas: at 3 gwei (under the 5 gwei ceiling) a pack's build cost exceeds one cycle's net.
        vm.fee(3 gwei);
        vm.txGasPrice(3 gwei);
        bytes32 _expected26 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vault.build(UNITS, planned15, 0, _expected26);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        TestVaultOps.restock(vault, 1, UNITS, 0);
        vm.stopPrank();
    }

    /// Repair: ETH freed for redeemers could be relisted, so a keeper could loop unlist -> list
    /// and be paid both ways while redemptions never filled.
    function test_unlistListLoopClosed() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected27 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected27);
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 6, UNITS, 0);
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            bytes32 _expected28 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares, _expected28);
        }
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.startPrank(keeper);
        TestVaultOps.unlist(vault, ids, 0);
        // The freed backing and packs are owed to alice: nothing can be listed or built.
        assertEq(vault.idleEth(), 0);
        uint256[] memory planned14 = TestVaultOps.proposals(vault, 6, UNITS);
        bytes32 _expected29 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(planned14, 0, _expected29);
        vm.stopPrank();
    }

    /// Repair (custody): a filled redemption settled into a holder's claimable balance by another
    /// action (here a new deposit) but not yet claimed was counted as free ETH, so keepers could
    /// list it or be paid from it, and the later claim would take other holders' ETH.
    function test_settledUnclaimedEthIsNotDeployable() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected30 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected30);
        }
        {
            uint256 gross_ = Charges.grossFor(vault, 1 ether);
            bytes32 _expected31 = TestVaultOps.configurationHash(vault);
            vm.prank(bob);
            vault.deposit{value: gross_}(_expected31);
        }
        toBlackout();
        checkpoint();
        toOpen();
        uint256 shares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, shares);
            bytes32 _expected32 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(shares, _expected32);
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
            bytes32 _expected33 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected33);
        }
        assertEq(vault.claimableTotal(), vault.claimableEth(alice));
        assertApproxEqAbs(vault.claimableEth(alice), reserved, 2);
        // Idle ETH excludes it: keepers can deploy only bob's capital and the seed.
        uint256 liabilities = vault.pendingDepositTotal() + vault.redemptionReserve()
            + vault.distributionReserve() + vault.claimableTotal();
        assertLe(vault.idleEth(), address(vault).balance - liabilities);
        vm.startPrank(keeper);
        TestVaultOps.restock(vault, 5, UNITS, 0); // uses bob's deployable capital
        uint256[] memory planned13 = TestVaultOps.proposals(vault, 4, UNITS);
        bytes32 _expected34 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(); // nothing more is deployable
        vault.build(UNITS, planned13, 0, _expected34);
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
            bytes32 _expected35 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected35);
        }
        toBlackout();
        checkpoint();
        toOpen();
        vm.prank(keeper);
        TestVaultOps.restock(vault, 3, UNITS, 0);
        bytes32 _expected36 = TestVaultOps.configurationHash(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.liquidate(10, 0, _expected36);
    }

    function test_depositAboveTvlCapReverts() public {
        lowerTo(1 ether, 5 gwei, 0.00002 ether);
        bytes32 _expected37 = TestVaultOps.configurationHash(vault);
        vm.prank(alice);
        vm.expectRevert(PackVault.Amount.selector);
        vault.deposit{value: 1.5 ether}(_expected37);
    }

    function test_checkpointWindowRules() public {
        {
            uint256 gross_ = Charges.grossFor(vault, 0.1 ether);
            bytes32 _expected38 = TestVaultOps.configurationHash(vault);
            vm.prank(alice);
            vault.deposit{value: gross_}(_expected38);
        }
        uint256 planned12 = TestVaultOps.witness(vault);
        bytes32 _expected39 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint(planned12, 0, _expected39);
        toBlackout();
        uint256 planned11 = TestVaultOps.witness(vault);
        bytes32 _expected40 = TestVaultOps.configurationHash(vault);
        vault.checkpoint(planned11, 0, _expected40);
        uint256 planned10 = TestVaultOps.witness(vault);
        bytes32 _expected41 = TestVaultOps.configurationHash(vault);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint(planned10, 0, _expected41);
    }
}
