// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {ForkBase, IFwaAdmin, IOwnable} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {PolicyGreedy} from "./ForkKeeperPolicy.t.sol";

/// @notice Keeper pay (D56) on the real FWA, Shapes and ShapePacks at a pinned mainnet block. Pay is
///         a quote fixed by the operation and its completed work; checkpoints are funded by request
///         charges; every payment draws on a refilling budget. No mocks.
contract ForkKeeperPayTest is ForkBase {
    uint256 constant PRICE = 0.2 gwei; // min(basefee 0.15 + maxTip 0.05, ceiling 5): ForkBase fees

    function _deposit(address who, uint256 escrow) internal returns (uint256 gross) {
        gross = Charges.grossFor(vault, escrow);
        vm.deal(who, who.balance + gross);
        vm.prank(who);
        vault.deposit{value: gross}();
    }

    function _priced(address who, uint256 escrow) internal {
        _deposit(who, escrow);
        toBlackout();
        checkpoint();
        toOpen();
    }

    function _restock(uint256 n) internal returns (uint256 pay) {
        vm.prank(keeper);
        pay = TestVaultOps.restock(vault, n, 6, 0);
    }

    /// 1-3, 13: the payment is the quote, whatever gas limit, gas use or tip the caller chooses,
    /// and it equals the returned value and the ETH the caller received.
    function test_payIgnoresCallerGasAndTip() public {
        _priced(alice, 1 ether);
        uint256 snap = vm.snapshotState();
        uint256 b = keeper.balance;
        vm.prank(keeper);
        uint256 p1 = TestVaultOps.restock(vault, 3, 6, 0); // build 3
        assertEq(keeper.balance - b, p1, "returned pay is the paid amount");
        assertEq(p1, _buildQuote(3) * PRICE + 6 * vault.getParams().workFee, "build quote");
        vm.revertToState(snap);
        vm.txGasPrice(5 gwei); // the caller bids a 4.85 gwei tip
        uint256[] memory proposals = TestVaultOps.proposals(vault, 3, 6);
        vm.prank(keeper);
        uint256 p2 = vault.build{gas: 15_000_000}(6, proposals, 0);
        assertEq(p2, p1, "tip and gas limit do not change pay");
        vm.txGasPrice(0.2 gwei);
    }

    /// @dev Quoted gas for building-and-listing `n` six-unit packs in one call (<= MAX_LIST_BATCH).
    function _buildQuote(uint256 n) internal pure returns (uint256) {
        return VaultLib.Q_BUILD + n * (VaultLib.buildGas(2) + VaultLib.Q_LISTED);
    }

    function _coldBuild(uint256[] memory quotes) internal returns (uint256 pay, uint256 used) {
        bytes memory input = abi.encodeCall(PackAccount.build, (6, quotes, 0));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(policy);
        assertGt(keeper.balance, 0); assertEq(keeper.code.length, 0);
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        used = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        pay = abi.decode(result, (uint256));
    }

    /// 4: splitting a job across calls earns one extra base per call, and each extra base is less
    /// than the gas the extra call itself costs, so splitting loses money.
    function test_splittingDoesNotPay() public { _split(false); }

    function test_splittingDoesNotPayAtMaximumMarkup() public { _split(true); }

    function _split(bool maximumMarkup) internal {
        _priced(alice, 1 ether);
        uint256 premiumBps;
        if (maximumMarkup) {
            premiumBps = 1_000;
            VaultLib.Params memory p = vault.getParams(); p.payMarkupBps = uint16(premiumBps);
            vm.prank(owner); vault.setParams(p);
            PolicyGreedy policy = new PolicyGreedy();
            vm.prank(owner); vault.setPolicy(address(policy));
        }
        uint256[] memory proposals = TestVaultOps.proposals(vault, 3, 6);
        uint256 snap = vm.snapshotState();
        (uint256 one, uint256 gasOne) = _coldBuild(proposals);
        assertEq(one, _buildQuote(3) * PRICE * (10_000 + premiumBps) / 10_000
            + 6 * vault.getParams().workFee, "real replaceable policy reaches the specified envelope");
        assertEq(vault.openListingCount(), 3);
        vm.revertToState(snap);
        uint256 split;
        uint256 gasSplit;
        for (uint256 i; i < 3; ++i) {
            uint256[] memory single = new uint256[](1); single[0] = proposals[i];
            (uint256 paid, uint256 used) = _coldBuild(single);
            split += paid; gasSplit += used;
        }
        assertEq(vault.openListingCount(), 3);
        emit log_named_uint("batch three complete gross gas", gasOne);
        emit log_named_uint("three singleton complete gross gas", gasSplit);
        emit log_named_uint("batch three pay wei", one);
        emit log_named_uint("three singleton pay wei", split);
        // Each split call earns one extra Q_BUILD call base; two extra calls for the split of three.
        assertEq(split - one, 2 * VaultLib.Q_BUILD * PRICE * (10_000 + premiumBps) / 10_000, "exactly two extra bases");
        assertGt((gasSplit - gasOne) * PRICE, split - one, "the extra calls cost more gas than they earn");
    }

    /// 5: repeating completed work pays nothing: it reverts.
    function test_repeatedWorkPaysNothing() public {
        _priced(alice, 1 ether);
        _restock(2); // build mints and lists 2
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        setPackAsk(0.03 ether);
        toBlackout();
        IFwaAdmin(address(FWA)).kickListing(ids[0]);
        uint256[] memory one = new uint256[](1);
        one[0] = ids[0];
        vm.prank(keeper);
        TestVaultOps.sync(vault, one, 0);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        TestVaultOps.sync(vault, one, 0);
        _deposit(bob, 0.1 ether);
        checkpoint();
        uint256 planned5 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.AlreadyCheckpointed.selector);
        vault.checkpoint(planned5, 0);
    }

    /// 6: a dust deposit funds its own checkpoint: the checkpoint pays back at most the charge the
    /// depositor paid, so a depositor who also keeps loses at least its own gas. A cancelled
    /// deposit leaves no work: the checkpoint is refused, and its charge stays for the vault.
    function test_dustDepositCannotManufacturePay() public {
        address attacker = makeAddr("pack-vault-test-attacker");
        assertEq(attacker.code.length, 0); assertEq(attacker.balance, 0);
        uint256 ck = vault.requestCharge();
        _deposit(attacker, 0.01 ether);
        assertEq(vault.processingPool(), ck);
        toBlackout();
        vm.prank(attacker);
        uint256 pay = TestVaultOps.checkpoint(vault, 0);
        assertLe(pay, ck, "pay is at most the attacker's own charge");
        assertEq(vault.processingPool(), 0);

        toOpen();
        uint256 b = attacker.balance;
        uint256 gross = _deposit(attacker, 0.01 ether);
        vm.prank(attacker);
        vault.cancelDeposit();
        assertEq(attacker.balance, b + gross, "deposit and charge refunded in full");
        assertGt(gross, 0.01 ether);
        toBlackout();
        uint256 planned4 = TestVaultOps.witness(vault);
        vm.prank(attacker);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned4, 0);
        assertEq(vault.processingPool(), 0, "a cancelled request leaves no paid work and no charge");
    }

    /// 7: a tiny redemption pays its checkpoint charge: the checkpoint it triggers pays back at
    /// most that charge.
    function test_tinyRedemptionCannotManufacturePay() public {
        _priced(alice, 1 ether);
        uint256 ck = vault.requestCharge();
        uint256 rc = Charges.redeemCharge(vault, 1);
        assertGe(rc, ck);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(1);
        toBlackout();
        vm.prank(alice);
        uint256 pay = TestVaultOps.checkpoint(vault, 0);
        assertLe(pay, ck);
    }

    /// 8: the whole cycle at the bytecode maxima, one attacker as depositor, keeper and
    /// redeemer, with another holder present to absorb socialized costs: deposit, price, build
    /// and list with its ETH, redeem, unwind, price, claim. Its net after its own gas is negative.
    function test_manufacturedCycleLosesAtMaxima() public {
        // Larger deposits than the 3-unit recipe: six-unit packs cost ~0.13 ETH each to list.
        _priced(alice, 2 ether);
        // Alice's capital is deployed first, so the attacker's redemption really needs unwinding.
        vm.prank(keeper);
        TestVaultOps.restock(vault, 13, 6, 0); // build mints and lists 13
        VaultLib.Params memory p = defaultParams();
        p.payMarkupBps = 1_000;
        p.workFee = uint64(vault.MAX_WORK_FEE());
        // 8 gwei is the effective ceiling maximum at which the 6-unit recipe still lists: above it
        // the purchaser-redeem margin (160,000 x gasCeiling) pushes the backing below P / 0.95. A
        // lower cap only lowers the attacker's pay, so the loss conclusion holds a fortiori.
        p.gasCeiling = 8 gwei;
        p.essentialCeiling = 8 gwei;
        p.maxTip = 0.05 gwei;
        vm.prank(owner);
        vault.setParams(p);

        address a = makeAddr("pack-vault-test-attacker");
        assertEq(a.code.length, 0); assertEq(a.balance, 0);
        vm.deal(a, 10 ether);
        uint256 start = a.balance;
        uint256 gasUsed;
        uint256 gasCost;
        // Deposit, priced by the attacker (basefee 0.15 gwei).
        uint256 ck = vault.requestCharge();
        vm.prank(a);
        vault.deposit{value: ck + 2 ether}();
        toBlackout();
        uint256 g = gasleft();
        vm.prank(a);
        TestVaultOps.checkpoint(vault, 0);
        gasUsed = g - gasleft() + 21_000;
        gasCost += gasUsed * 0.15 gwei;
        toOpen();
        // Build with the attacker's ETH (15 positions), at a basefee where the gate lets it.
        g = gasleft();
        vm.prank(a);
        TestVaultOps.restock(vault, 15, 6, 0);
        gasCost += (g - gasleft() + 5 * 21_000) * 0.15 gwei;
        assertGe(TestVaultOps.open(vault).length, 25, "the attacker's ETH was deployed");
        // Redeem everything; unwind at a 5 gwei spike (essential work pays at the ceiling-capped price).
        uint256 shares = vault.shareBalance(a);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(a);
        vault.requestRedeem{value: rc}(shares);
        vm.fee(5 gwei);
        vm.txGasPrice(5 gwei);
        uint256[] memory ids = TestVaultOps.open(vault);
        uint256[] memory unwind = new uint256[](16);
        for (uint256 i; i < 16; ++i) unwind[i] = ids[i];
        g = gasleft();
        vm.startPrank(a);
        vault.unlist(unwind, 0);
        vault.liquidate(40, 0);
        vm.stopPrank();
        gasCost += (g - gasleft() + 2 * 21_000) * 5 gwei;
        assertLt(TestVaultOps.open(vault).length, 28, "positions were unlisted for the redemption");
        assertLt(vault.openListingCount(), ids.length, "the real redemption trigger frees listed positions");
        assertGe(vault.openListingCount(), ids.length - 16, "only the submitted bounded prefix can be unwound");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        toBlackout();
        g = gasleft();
        vm.prank(a);
        TestVaultOps.checkpoint(vault, 0);
        gasCost += (g - gasleft() + 21_000) * 0.15 gwei;
        // Payment after the first liquidation can leave a small second fill to fund.
        for (uint256 attempt; attempt < 3 && vault.lockedShares() != 0; ++attempt) {
            toOpen();
            ids = TestVaultOps.open(vault);
            uint256[] memory single = new uint256[](1); single[0] = ids[0];
            bool hasInventory = vault.idlePackCount() != 0;
            g = gasleft();
            vm.prank(a);
            if (hasInventory) vault.liquidate(16, 0); else vault.unlist(single, 0);
            gasCost += (g - gasleft() + 21_000) * 0.15 gwei;
            toBlackout();
            g = gasleft();
            vm.prank(a); TestVaultOps.checkpoint(vault, 0);
            gasCost += (g - gasleft() + 21_000) * 0.15 gwei;
        }
        assertEq(vault.lockedShares(), 0, "the attacker completes the exit before net profit is measured");
        vm.prank(a);
        vault.claim();
        assertEq(vault.shareBalance(a), 0); assertEq(vault.claimableEth(a), 0);
        (uint128 remaining,,,) = vault.redemptions(a);
        assertEq(remaining, 0, "no residual redemption value is omitted from the net calculation");
        int256 net = int256(a.balance) - int256(start) - int256(gasCost);
        emit log_named_int("attacker net after its own gas (wei)", net);
        assertLt(net, 0, "a manufactured cycle loses money at the bytecode maxima");
    }

    /// 9: with both budgets at zero no keeper is paid, but every operation still runs unpaid;
    /// a caller asking for pay is refused before the work.
    function test_unpaidWorkWhenBudgetsAreEmpty() public {
        _priced(alice, 1 ether);
        _restock(2);
        setCaps(0, 0);
        (uint256 r, uint256 e) = vault.budget();
        assertEq(r + e, 0);
        uint256[] memory planned3 = TestVaultOps.proposals(vault, 2, 6);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Payment.selector);
        vault.build(6, planned3, 1);
        uint256[] memory planned2 = TestVaultOps.proposals(vault, 2, 6);
        vm.prank(keeper);
        assertEq(vault.build(6, planned2, 0), 0, "built unpaid");
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.startPrank(alice);
        assertEq(TestVaultOps.unlist(vault, ids, 0), 0);
        assertEq(vault.liquidate(40, 0), 0);
        vm.stopPrank();
        toBlackout();
        // The checkpoint is paid from her own request charge, not the empty budgets (audit B).
        uint256 pool = vault.processingPool();
        vm.prank(alice);
        uint256 ckPay = TestVaultOps.checkpoint(vault, 0);
        assertGt(ckPay, 0, "charge-funded checkpoint paid with budgets empty");
        assertLe(ckPay, pool);
        vm.prank(alice);
        vault.claim();
        assertGt(alice.balance, 0.98 ether);
    }

    /// 11-12: the budgets bound total pay over time. A level never refills above its cap, a
    /// parameter change never refills spent capacity, the owner cannot exceed the bytecode
    /// maxima, and the owner's lowering cancels a pending raise.
    function test_budgetsBoundSpendingOverTime() public {
        _priced(alice, 3 ether);
        VaultLib.Params memory q = vault.getParams();
        setCaps(0.002 ether, q.essentialCap);
        (uint256 r,) = vault.budget();
        assertEq(r, 0.002 ether, "lowering clamps the level to the cap");
        // Build until the routine budget runs out: total pay never exceeds it.
        uint256 paid;
        for (uint256 i; i < 4; ++i) {
            vm.prank(keeper);
            paid += TestVaultOps.restock(vault, 1, 6, 0);
        }
        assertLe(paid, 0.002 ether);
        (r,) = vault.budget();
        assertEq(r, 0.002 ether - paid);
        // One day refills at most the daily rate; a month never exceeds the cap.
        vm.warp(block.timestamp + 1 days);
        (r,) = vault.budget();
        assertLe(r, 0.002 ether - paid + q.routineRate);
        vm.warp(block.timestamp + 30 days);
        (r,) = vault.budget();
        assertEq(r, 0.002 ether);
        // Raise the cap: the level stays where it was (0.002), not 0.3.
        VaultLib.Params memory up = vault.getParams();
        up.routineCap = 0.3 ether;
        vm.prank(owner);
        vault.setParams(up);
        (r,) = vault.budget();
        assertEq(r, 0.002 ether, "applying a raise refills nothing");
        // Above the bytecode maxima: refused.
        up.routineCap = 0.3 ether + 1;
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(up);
        up.routineRate = 0.02 ether + 1;
        up.routineCap = 0.3 ether;
        vm.prank(owner);
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vault.setParams(up);
        // A owner lowering clamps the level at once.
        q = vault.getParams();
        setCaps(0.001 ether, q.essentialCap);
        (r,) = vault.budget();
        assertEq(r, 0.001 ether, "lowered cap clamps the level");
    }

    function test_newRoutineRateCeilingOnlyRefillsPermission() public {
        VaultLib.Params memory p = vault.getParams();
        p.routineCap = 0;
        vm.prank(owner); vault.setParams(p);
        p.routineCap = 0.1 ether; p.routineRate = 0.02 ether;
        uint256 cash = address(vault).balance;
        vm.prank(owner); vault.setParams(p);
        (uint256 routine, uint256 essential) = vault.budget();
        assertEq(routine, 0, "raising the ceiling grants no immediate spending permission");
        assertEq(vault.getParams().routineRate, 0.02 ether);
        vm.warp(vm.getBlockTimestamp() + 1 days);
        (routine,) = vault.budget();
        assertEq(routine, 0.02 ether);
        assertEq(address(vault).balance, cash, "refill creates permission, never ETH");
        vm.warp(vm.getBlockTimestamp() + 10 days);
        (routine, essential) = vault.budget();
        assertEq(routine, p.routineCap, "capacity remains independently bounded");
        assertEq(essential, p.essentialCap, "routine rate does not change essential capacity");
        assertEq(address(vault).balance, cash);
        p.routineRate = 0.02 ether + 1;
        vm.expectRevert(VaultLib.OutOfBounds.selector);
        vm.prank(owner); vault.setParams(p);
        assertEq(vault.getParams().routineRate, 0.02 ether, "over-limit change is atomic");
    }

    /// 8 (essential): routine work cannot use the essential budget: with routine empty, unwinding
    /// for a redemption is still paid from the essential budget.
    function test_routineCannotDrainEssential() public {
        _priced(alice, 1 ether);
        _restock(3); // build mints and lists 3
        VaultLib.Params memory q = vault.getParams();
        setCaps(0, q.essentialCap);
        _restock(1); // routine: unpaid now
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.prank(keeper);
        uint256 pay = TestVaultOps.unlist(vault, ids, 0);
        assertGt(pay, 0, "essential work is paid from its own budget");
        (uint256 r, uint256 e) = vault.budget();
        assertEq(r, 0);
        assertEq(e, q.essentialCap - pay);
    }

    /// 10: keeper pay never touches ETH owed to holders: after every paid call the balance still
    /// covers escrow, the pool, both reserves and settled claimables.
    function test_payNeverUsesLiabilities() public {
        _priced(alice, 1 ether);
        _deposit(bob, 0.5 ether); // escrow, a liability until priced
        uint256 shares = vault.shareBalance(alice) / 4;
        uint256 rc = Charges.redeemCharge(vault, shares);
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        _restock(1); // build mints and lists
        _check();
        toBlackout();
        checkpoint();
        _check();
    }

    function _check() internal view {
        uint256 owed = vault.pendingDepositTotal() + vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal() + vault.processingPool();
        assertGe(address(vault).balance, owed, "liabilities covered");
    }

    /// minPay: the exact quote is accepted, one wei more reverts the whole call.
    function test_minPayIsAllOrNothing() public {
        _priced(alice, 1 ether);
        uint256 quote = _buildQuote(1) * PRICE + 2 * vault.getParams().workFee;
        uint256 snap = vm.snapshotState();
        uint256[] memory planned1 = TestVaultOps.proposals(vault, 1, 6);
        vm.prank(keeper);
        vm.expectRevert(VaultLib.Payment.selector);
        vault.build(6, planned1, quote + 1);
        vm.revertToState(snap);
        vm.prank(keeper);
        assertEq(TestVaultOps.restock(vault, 1, 6, quote), quote);
    }

    /// Requests in one interval share one checkpoint: the first tops the pool up to one
    /// checkpoint's cost, later ones pay nothing; the checkpoint pays its measured-gas quote.
    function test_requestChargeTopsUpOnce() public {
        uint256 full = vault.requestCharge();
        assertEq(full % 1 gwei, 0, "whole gwei");
        // 225k base, no positions, at basefee 0.15 + tip 0.05, plus one work fee; rounded up.
        assertEq(full, ((VaultLib.Q_CHECKPOINT * PRICE + vault.getParams().workFee) + 1 gwei - 1) / 1 gwei * 1 gwei);
        _deposit(alice, 1 ether);
        assertEq(vault.processingPool(), full);
        assertEq(vault.requestCharge(), 0, "pool already funded");
        uint256 b = bob.balance;
        vm.prank(bob);
        vault.deposit{value: 1 ether}();
        (uint96 amount,,, uint32 ckGwei) = vault.pendingDeposits(bob);
        assertEq(amount, 1 ether, "no checkpoint charge taken");
        assertEq(ckGwei, 0);
        assertEq(b - bob.balance, 1 ether);
        toBlackout();
        vm.prank(keeper);
        uint256 pay = TestVaultOps.checkpoint(vault, 0);
        assertEq(pay, VaultLib.Q_CHECKPOINT * PRICE + vault.getParams().workFee, "measured-gas quote");
        assertEq(vault.processingPool(), 0);
    }

    /// A cancel refunds its checkpoint charge only beyond what other waiting flows still need.
    function test_cancelKeepsPoolForOtherFlows() public {
        uint256 ckA = vault.requestCharge();
        uint256 grossA = _deposit(alice, 1 ether);
        vm.prank(bob);
        vault.deposit{value: 1 ether}(); // pays no checkpoint charge
        uint256 a0 = alice.balance;
        vm.prank(alice);
        vault.cancelDeposit();
        assertEq(alice.balance - a0, grossA - ckA, "escrow back; charge kept for bob's checkpoint");
        assertEq(vault.processingPool(), ckA);
        uint256 b0 = bob.balance;
        vm.prank(bob);
        vault.cancelDeposit();
        assertEq(bob.balance - b0, 1 ether, "bob paid no charge, gets none");
        assertEq(vault.processingPool(), 0, "the final cancellation closes this charge era");
        assertEq(vault.chargeRefundReserve(), ckA, "alice's funded charge remains claimable");
        uint256 era = vault.chargeEra();
        vm.prank(alice);
        vault.claimCheckpointRefund(era);
        assertEq(vault.chargeRefundReserve(), 0);
    }

    /// Redemption and wind-down work is paid up to the essential ceiling; routine work stops at
    /// the routine ceiling. Canary: 0.5 and 2 gwei.
    function test_essentialCeilingPaysExitsInSpikes() public {
        VaultLib.Params memory p = vault.getParams();
        (p.gasCeiling, p.essentialCeiling, p.payMarkupBps) = (0.5 gwei, 2 gwei, 0);
        vm.prank(owner);
        vault.setParams(p);
        _priced(alice, 1 ether);
        vm.fee(1 gwei);
        vm.txGasPrice(1.05 gwei);
        vm.prank(keeper);
        uint256 buildPay = TestVaultOps.restock(vault, 2, 6, 0); // routine build of two listings
        assertEq(buildPay, _buildQuote(2) * 0.5 gwei + 4 * p.workFee, "routine: capped at 0.5 gwei");
        vm.prank(owner);
        vault.startWindDown();
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.prank(keeper);
        uint256 unlistPay = TestVaultOps.unlist(vault, ids, 0);
        assertEq(unlistPay, (VaultLib.Q_UNLIST + 2 * VaultLib.Q_UNLISTED) * 1.05 gwei + 2 * p.workFee, "essential: basefee + tip under 2 gwei");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    /// D64: without an essential budget exit work is unpaid and redeemers pay no unwind charge; the
    /// withdrawer unlists and liquidates herself and the redemption completes.
    function test_selfServeExitWithoutEssentialBudget() public {
        _priced(alice, 1 ether);
        _restock(3); // build mints and lists 3
        setCaps(vault.getParams().routineCap, 0);
        assertEq(vault.unwindCharge(), 0, "no unwind charge");
        uint256 shares = vault.shareBalance(alice);
        uint256 rc = Charges.redeemCharge(vault, shares);
        assertEq(rc, vault.requestCharge(), "only the shared checkpoint charge");
        vm.prank(alice);
        vault.requestRedeem{value: rc}(shares);
        uint256[] memory ids = TestVaultOps.open(vault);
        vm.startPrank(alice);
        assertEq(TestVaultOps.unlist(vault, ids, 0), 0, "unpaid");
        assertEq(vault.liquidate(40, 0), 0, "unpaid");
        vm.stopPrank();
        toBlackout();
        vm.prank(alice);
        TestVaultOps.checkpoint(vault, 0);
        assertEq(vault.lockedShares(), 0, "redemption filled");
        uint256 b = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertGt(alice.balance - b, 0.97 ether);
    }
}
