// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {DeployCore} from "../../script/DeployCore.sol";
import {IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {MainRenewalBase} from "./ForkMainRenewal.t.sol";
import {IFwaSettle} from "./ForkSelection.t.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

/// @notice Real three-mint allocation, genuine checkpoint-priced incumbent and complete claims.
/// @dev The initial cash-only checkpoint uses the preceding blackout timestamp with external
///      state pinned to the request block. It has no protocol exposure or foreign income then.
///      All subsequent acquisition/VRF/settlement calls use their real chronological context.
contract ForkMainCheckpointFairnessTest is MainRenewalBase {
    uint256 internal constant INCUMBENT = 73 ether;
    uint256 internal secondSelected;
    bool internal multipleFixture;
    uint256 internal incumbentStart;
    uint256 internal entrantStart;

    struct Result {
        uint256 incumbentClaim;
        uint256 entrantClaim;
        uint256 incumbentSpend;
        uint256 entrantSpend;
        uint256 entryNav;
    }

    function parameters() internal pure override returns (VaultLib.Params memory p) {
        p = super.parameters();
        p.tvlCap = 200 ether;
        p.essentialCap = 0;
        p.essentialRate = 0;
    }

    function _initialFunding() internal pure override returns (uint256) { return 0.01 ether; }

    function _beforeInitialBuild() internal override {
        vault = PackVault(payable(address(account)));
        assertEq(alice.code.length + alice.balance, 0, "incumbent is a clean actor on the selected fork");
        assertEq(bob.code.length + bob.balance, 0, "entrant is a clean actor on the selected fork");
        vm.deal(alice, 200 ether);
        vm.deal(bob, 10 ether);
        incumbentStart = alice.balance;
        entrantStart = bob.balance;
        uint256 requestTime = vm.getBlockTimestamp();
        uint256 priorBlackout = requestTime - requestTime % INTERVAL - INTERVAL + BLACKOUT + 60;
        vm.warp(priorBlackout);
        uint256 charge = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(alice);
        vault.deposit{value: (multipleFixture ? 146 ether : INCUMBENT) + charge}(expected);
        vault.checkpoint(0, 0, expected);
        assertGt(vault.shareBalance(alice), 0, "incumbent owns real shares priced at an actual checkpoint");
        assertEq(vault.pendingDepositTotal(), 0);
        vm.warp(requestTime);
    }

    function _nearSelection() internal {
        _selectCandidate(true, ReplayCandidate(
            26_438_035,
            0x6968774f4c0bf7bb7134119c67483e13bd1a006acfac0bd7d2e414af9da0bd98,
            10, 3, 4878,
            address(bytes20(hex"57511d586ad667b7e5032dfb51acfcf41952e601"))
        ));
        account.recover(new uint256[](0), 0);
        assertEq(account.unresolvedUplift(), 0.18 ether);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "authentic single request and fulfillment drain the queue");
        toBlackout();
        assertTrue(FWA.isPurchaseBlackout());
        assertLt(vm.getBlockTimestamp(), uint256(account.position(selected).allocatedAt) + FWA.settlementWindow(),
            "unresolved allocation is still inside its real settlement window");
    }

    function _keepOne(uint256 id) internal {
        uint256 cash = address(account).balance;
        uint256 backingValue = account.position(id).backing;
        uint256 fee = FWA.ownerSettlementFeeBps();
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).keepNFT(id);
        assertEq(address(account).balance - cash, backingValue * (10_000 - fee) / 10_000);
        account.recover(one(id), 0);
    }

    function _keep() internal {
        _keepOne(selected);
        if (secondSelected != 0) _keepOne(secondSelected);
        assertEq(account.unresolvedUplift(), 0);
    }

    function _finish(bool beforePricing) internal returns (Result memory r) {
        if (beforePricing) _keep();
        r.entryNav = account.accountedNav(0);
        if (!beforePricing) {
            assertLe(account.unresolvedUplift() * 10_000, r.entryNav * 25);
            assertGt(account.unresolvedUplift() * 10_000, r.entryNav * 24,
                "actual allocation lies near the configured 25bps bound");
        }
        uint256 topup = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(bob);
        vault.deposit{value: 1 ether + topup}(expected);
        vault.checkpoint(0, 0, expected);
        assertGt(vault.shareBalance(bob), 0);
        if (!beforePricing) _keep();

        uint256 incumbentShares = vault.shareBalance(alice);
        uint256 entrantShares = vault.shareBalance(bob);
        topup = vault.requestCharge();
        expected = vault.configurationHash();
        vm.prank(alice);
        vault.requestRedeem{value: topup}(incumbentShares, expected);
        vm.prank(bob);
        vault.requestRedeem(entrantShares, expected);
        toBlackout();
        vault.checkpoint(0, 0, expected);
        assertEq(vault.lockedShares(), 0, "all actual holder redemptions finish");
        assertEq(vault.totalShares(), vault.DEAD_SHARES());
        (,, r.incumbentClaim) = vault.holderState(alice);
        (,, r.entrantClaim) = vault.holderState(bob);
        uint256 before = alice.balance;
        vm.prank(alice);
        vault.claim();
        assertEq(alice.balance - before, r.incumbentClaim);
        before = bob.balance;
        vm.prank(bob);
        vault.claim();
        assertEq(bob.balance - before, r.entrantClaim);
        for (uint256 i; i < vault.contributionCount(); ++i) {
            if (vault.checkpointRefund(i) == 0) continue;
            (address payer,,,,) = vault.contributions(i);
            vm.prank(payer);
            vault.claimCheckpointRefund(one(i));
        }
        assertEq(vault.chargeRefundReserve(), 0, "all payer funding is consumed or actually refunded");
        // These are contract cash flows. Wallet transaction gas is additional and measured by
        // the local receipt campaign, never inferred from Forge aggregate test gas.
        r.incumbentSpend = incumbentStart + r.incumbentClaim - alice.balance;
        r.entrantSpend = entrantStart + r.entrantClaim - bob.balance;
        assertLe(vault.redemptionReserve() + vault.claimableTotal(), 2, "no material holder claim remains");
    }

    function test_liveIncumbentAndEntrantKeepOrderingAt25bpsCompleteBothExits() public {
        _nearSelection();
        _compareKeepOrder();
    }

    function _compareKeepOrder() internal {
        uint256 snapshot = vm.snapshotState();
        Result memory settledFirst = _finish(true);
        assertTrue(vm.revertToState(snapshot));
        Result memory settledAfter = _finish(false);
        int256 incumbentWealthEffect = int256(settledAfter.incumbentClaim) - int256(settledAfter.incumbentSpend)
            - int256(settledFirst.incumbentClaim) + int256(settledFirst.incumbentSpend);
        int256 entrantEffect = int256(settledAfter.entrantClaim) - int256(settledAfter.entrantSpend)
            - int256(settledFirst.entrantClaim) + int256(settledFirst.entrantSpend);
        emit log_named_int("incumbent wealth effect keep after vs before pricing (wei, before wallet gas)", incumbentWealthEffect);
        emit log_named_int("entrant wealth effect keep after vs before pricing (wei, before wallet gas)", entrantEffect);
        emit log_named_int("entrant full exit result keep after pricing (wei, before wallet gas)",
            int256(settledAfter.entrantClaim) - int256(settledAfter.entrantSpend));
        assertGt(entrantEffect, 0, "bounded unresolved uplift still transfers wealth toward the entrant");
        assertLt(incumbentWealthEffect, 0, "incumbent loses wealth even if entrant is unprofitable");
        assertLt(settledAfter.entrantClaim, settledAfter.entrantSpend, "complete charged entrant round trip is not profitable");
    }

    function test_multipleRealAllocationsNear25bpsCompleteBothHolderExits() public {
        multipleFixture = true;
        vm.createSelectFork("mainnet", bytes32(0x1adee9be0b88eb3ca2176e0b19ec408bd34907df93a34122c86212902942fe88));
        fixtureRequestBlock = 26_272_979;
        selectedPurchaser = address(bytes20(hex"184b487d36aea8aa5990569c326c269de246179a"));
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        accountOwner = makeAddr("pack-vault-test-main-renewal-owner");
        assertEq(accountOwner.code.length + accountOwner.balance, 0);
        vm.deal(address(this), 30 ether);
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaSettle(address(FWA)).setCollectionsWhitelisted(cols, true);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        account = DeployCore.deploy(FWA, SHAPES, PACKS, accountOwner, parameters(), 0.01 ether,
            keccak256(abi.encode(parameters(), SHAPES.mintFee(), false, false)));
        _beforeInitialBuild();
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 20 ether}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES)));
        for (uint256 i; i < 72; ++i) {
            if (i == 3 || i == 6) {
                uint256[] memory values = one(0.21 ether + (i == 6 ? 10_000 : 0));
                account.build(3, values, 0, account.configurationHash());
                uint256 id = account.openListingAt(account.openListingCount() - 1);
                if (i == 6) selected = id;
                else secondSelected = id;
            } else filler.createAndList(0.21 ether);
        }
        (,,,,,,,, uint256 slot,,) = FWA.listings(selected);
        assertEq(slot, 539);
        (,,,,,,,, slot,,) = FWA.listings(secondSelected);
        assertEq(slot, 6292);
        string memory fx = vm.readFile("test/fixtures/completion-selection.json");
        _call(fx, "req");
        string memory key = string.concat(".", vm.toString(fixtureRequestBlock));
        vm.roll(vm.parseJsonUint(fx, string.concat(key, ".fulBlock")));
        vm.warp(vm.parseJsonUint(fx, string.concat(key, ".fulTimestamp")));
        vm.setBlockhash(fixtureRequestBlock, vm.parseJsonBytes32(fx, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fx, string.concat(key, ".fulBaseFee")));
        _call(fx, "ful");
        for (uint256 i = 2; i <= 5; ++i) _call(fx, string.concat("ful", vm.toString(i)));
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        uint256[] memory ids = new uint256[](2);
        ids[0] = selected;
        ids[1] = secondSelected;
        account.recover(ids, 0);
        assertEq(account.position(selected).state, 2, "first authenticated proof selects real owned listing");
        assertEq(account.position(secondSelected).state, 2, "second authenticated proof selects distinct real owned listing");
        assertEq(account.unresolvedUplift(), 0.36 ether + 10_000, "sum of two exact stored uplifts");
        assertEq(FWA.unsettledAcquisitionCount(), 0, "five actual proofs drain the real queue");
        toBlackout();
        assertLt(vm.getBlockTimestamp(), uint256(account.position(selected).allocatedAt) + FWA.settlementWindow());
        _compareKeepOrder();
    }

    function test_lateAllocationCannotUseMissedWindowAndRecoversThroughRealSettlement() public {
        _select(true);
        account.recover(new uint256[](0), 0);
        toBlackout();
        assertGe(vm.getBlockTimestamp(), uint256(account.position(selected).allocatedAt) + FWA.settlementWindow());
        assertGt(FWA.unsettledAcquisitionCount(), 0, "the actual second historical request is still pending");
        uint256 charge = vault.requestCharge();
        bytes32 expected = vault.configurationHash();
        vm.prank(bob);
        vault.deposit{value: 1 ether + charge}(expected);
        vm.expectRevert(PackVault.NotCheckpointWindow.selector);
        vault.checkpoint(0, 0, expected);
        account.recover(one(selected), 0); // real public expiry settlement, no fabricated VRF
        assertEq(account.position(selected).state, 0);
        _drainOtherRequest();
        toBlackout();
        vault.checkpoint(0, 0, vault.configurationHash());
        assertGt(vault.shareBalance(bob), 0, "later actual window resumes pricing");
    }
}
