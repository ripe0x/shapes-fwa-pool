// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MainRenewalBase, IFwaSettle, IShapesFeeAdmin} from "./ForkMainRenewal.t.sol";
import {PackManager} from "../../src/PackManager.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {Vm} from "forge-std/Vm.sol";

interface IFWASlots {
    function slotToListing(uint256 slot) external view returns (uint256);
}

/// @notice Exact owner/account/keeper/creator traces against real acquisition proofs. Foundry
///      call-frame gas is not a billed receipt; direct wallet gas comes from the local UI campaign.
abstract contract ManagerCloseoutBase is MainRenewalBase {
    uint256 private initialCash;
    uint256 private keeperPaid;
    uint256 private primaryFees;
    uint256 private ownerInitial;
    uint256 private feeWitness;
    uint256 private accumulatorBefore;
    uint256 private acquisitionIncome;
    mapping(uint256 => uint256) private storedBacking;
    bytes32 private constant EARNINGS = keccak256("EarningsAccrued(address,uint256,uint256)");

    function parameters() internal pure virtual override returns (VaultLib.Params memory p) {
        p = super.parameters();
        p.essentialCeiling = 0.5 gwei;
        p.tvlCap = 0;
        p.routineCap = 0.03 ether;
        p.routineRate = 0.01 ether;


    }

    function output() internal pure virtual returns (string memory);
    function _initialFunding() internal pure override returns (uint256) { return 1 ether; }

    function assertGasEnvironment() external {
        assertEq(block.basefee, 0.15 gwei);
        assertEq(tx.gasprice, 0.2 gwei);
    }

    function _beforeInitialBuild() internal override {
        require(!vm.exists(output()), "preserve prior measured manager trace");
        initialCash = address(account).balance;
        ownerInitial = accountOwner.balance;
        this.assertGasEnvironment();
        _snapshot("setup", "create", 0, string.concat('{"fundingWei":', vm.toString(_initialFunding()),
            ',"deployBalance":', vm.toString(initialCash), ',"initialCursor":', vm.toString(account.acquisitionCursor()), '}'));
    }

    function _afterInitialBuild(uint256 paid) internal override {
        keeperPaid += paid;
        uint256 id = account.openListingAt(account.openListingCount() - 1);
        VaultLib.Position memory p = account.position(id);
        storedBacking[p.packId] = p.backing;
        uint256 actualMintFees = initialCash - address(account).balance - p.value - p.backing - paid;
        assertEq(actualMintFees, 0.003 ether, "actual account debit pays three primary mint fees");
        primaryFees += actualMintFees;
        _snapshot("built", "build", paid, string.concat('{"units":3,"ids":[', vm.toString(id),
            '],"packId":', vm.toString(p.packId), ',"backings":[', vm.toString(p.backing),
            '],"feeDebt":', vm.toString(p.feeDebt), ',"shapeCount":', vm.toString(PACKS.contentsOf(p.packId).length), '}'));
    }

    function _beforeRequest() internal override {
        // A positive foreign pending balance makes debt+pending the exact public projection
        // floor(accFeePerEV/SCALE), without reading or altering private protocol storage.
        for (uint256 slot; slot < 32; ++slot) {
            uint256 id = IFWASlots(address(FWA)).slotToListing(slot);
            if (id != 0 && FWA.pendingFees(id) != 0) { feeWitness = id; break; }
        }
        assertGt(feeWitness, 0, "fixture has a real active fee-bearing witness");
        accumulatorBefore = _accumulator();
        assertTrue(FWA.topListingId() != selected, "selected manager listing is not the crown");
        _snapshot("beforeRequest", "request", 0, string.concat('{"selectedListing":', vm.toString(selected),
            ',"feeWitness":', vm.toString(feeWitness), ',"accBefore":', vm.toString(accumulatorBefore),
            ',"acqFee":', vm.toString(FWA.acquisitionFee()), ',"acqCutBps":', vm.toString(FWA.ownerAcquisitionFeeBps()),
            ',"acqCrownBps":', vm.toString(FWA.topListingShareBps()), ',"acqActive":', vm.toString(FWA.activeListingCount()), '}'));
        vm.recordLogs();
    }

    function _accumulator() private view returns (uint256) {
        (,,,,,,, uint256 debt,,, uint8 status) = FWA.listings(feeWitness);
        uint256 pending = FWA.pendingFees(feeWitness);
        assertEq(status, 1, "foreign fee witness remains actually active");
        assertGt(pending, 0, "positive pending makes the accumulator projection exact");
        return debt + pending;
    }

    function _selectedSnapshot() private {
        Vm.Log[] memory logs = vm.getRecordedLogs();
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter == address(FWA) && logs[i].topics.length == 3
                && logs[i].topics[0] == EARNINGS && address(uint160(uint256(logs[i].topics[1]))) == address(account)) {
                assertEq(uint256(logs[i].topics[2]), selected, "real fee accrual is for this selected position");
                acquisitionIncome += abi.decode(logs[i].data, (uint256));
            }
        }
        assertGt(acquisitionIncome, 0, "actual acquisition accrued positive protocol income");
        uint256 afterAcc = _accumulator();
        VaultLib.Position memory p = account.position(selected);
        (,,,,,,,,, uint64 allocatedAt,) = FWA.listings(selected);
        assertEq(acquisitionIncome, afterAcc - p.feeDebt, "actual event matches independent public accumulator projection");
        _snapshot("selected", "acquisition", 0, string.concat('{"selectedListing":', vm.toString(selected),
            ',"packId":', vm.toString(packId), ',"allocatedAt":', vm.toString(allocatedAt),
            ',"accBefore":', vm.toString(accumulatorBefore), ',"accAfter":', vm.toString(afterAcc),
            ',"earningsAccrued":', vm.toString(acquisitionIncome), '}'));
    }

    function _traceRenewalStep(string memory step, uint256 paid) internal override {
        keeperPaid += paid;
        _snapshot(step, step, paid, string.concat('{"selectedListing":', vm.toString(selected),
            ',"packId":', vm.toString(packId), ',"ids":[', vm.toString(selected), ']}'));
    }

    function _snapshot(string memory step, string memory action, uint256 pay, string memory input) internal {
        string memory idle = "[";
        for (uint256 i; i < account.idlePackCount(); ++i) {
            uint256 id = account.idlePackAt(i);
            if (i != 0) idle = string.concat(idle, ",");
            idle = string.concat(idle, '{"id":', vm.toString(id), ',"value":', vm.toString(account.idleValueOf(id)),
                ',"shapes":', vm.toString(account.inventoryShapeCount(id)), ',"quote":', vm.toString(storedBacking[id]),
                '}');
        }
        idle = string.concat(idle, "]");
        uint256 pending;
        for (uint256 i; i < account.openListingCount(); ++i) pending += FWA.pendingFees(account.openListingAt(i));
        string memory line = string.concat('{"compensationMode":"bounded-measured-v1","step":"', step, '","action":"', action, '","account":"',
            vm.toString(address(account)), '","owner":"', vm.toString(accountOwner), '","keeper":"', vm.toString(address(this)),
            '","block":', vm.toString(block.number), ',"timestamp":', vm.toString(block.timestamp));
        line = string.concat(line, ',"baseFee":', vm.toString(block.basefee), ',"gasPrice":', vm.toString(tx.gasprice),
            ',"params":"', vm.toString(abi.encode(account.getParams())), '","liveMintFee":', vm.toString(SHAPES.mintFee()),
            ',"keeperPayCumulativeWei":', vm.toString(keeperPaid), ',"creatorFeesCumulativeWei":', vm.toString(primaryFees),
            ',"ownerReceivedWei":', vm.toString(accountOwner.balance - ownerInitial), ',"pendingFeesSum":', vm.toString(pending));
        line = string.concat(line, ',"idlePacks":', idle, ',"recovery":', vm.toString(account.recoveryPackCount()),
            ',"windingDown":', account.windingDown() ? "true" : "false", ',"listingPaused":', account.listingPaused() ? "true" : "false",
            ',"input":', input, ',"state":', ReconcileTrace.renderStrategy(account, pay, primaryFees, step), '}');
        vm.writeLine(output(), line);
        vm.recordLogs();
    }

    function _finish(bool) internal {
        _selectedSnapshot();
        _bidAndRecover();
        uint256 supply = SHAPES.totalSupply();
        uint256 beforeFees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 paid = account.list(backing(), 0, account.configurationHash());
        keeperPaid += paid;
        uint256 feeDelta = IShapesFeeAdmin(address(SHAPES)).pendingFees() - beforeFees;
        assertEq(feeDelta, 0, "returned pack reuse pays no primary mint fees");
        assertEq(SHAPES.totalSupply(), supply, "returned pack is neither retired nor replaced");
        assertEq(account.position(account.openListingAt(0)).packId, packId);
        uint256 id = account.openListingAt(0);
        VaultLib.Position memory replacement = account.position(id);
        storedBacking[replacement.packId] = replacement.backing;
        assertEq(replacement.value, 0.03 ether);
        assertEq(replacement.backing, 0.21 ether);
        _snapshot("reinvested", "list", paid, string.concat('{"units":3,"ids":[', vm.toString(id),
            '],"returnedPack":', vm.toString(packId), ',"packId":', vm.toString(replacement.packId),
            ',"backings":[', vm.toString(replacement.backing), '],"feeDebt":', vm.toString(replacement.feeDebt), '}'));

        VaultLib.Params memory p = account.getParams();
        p.routineCap = 0; p.routineRate = 0;
        bytes32 expected = account.configurationHash();
        vm.prank(accountOwner); account.setParams(p, expected);
        _snapshot("permissionExhausted", "setParams", 0, "{}");
        PackManager manager = PackManager(payable(address(account)));
        vm.prank(accountOwner); manager.setExiting(true);
        _snapshot("exiting", "setExiting", 0, "{\"exiting\":true}");
        toOpen();
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasEnvironment();
        _snapshot("exitWindow", "wait", 0, "{}");
        if (account.acquisitionCursor() < FWA.nextSequenceToProcess() || account.pendingReceipts() != 0) {
            vm.prank(accountOwner); account.recover(new uint256[](0), 0);
            _snapshot("exitRecovered", "recover", 0, "{\"ids\":[]}");
        }
        uint256 cash = address(account).balance;
        vm.prank(accountOwner); account.recoverUnlist(one(id));
        assertEq(address(account).balance - cash, 0.21 ether, "actual backing returns to its manager");
        _snapshot("unlisted", "unlist", 0, string.concat('{"ids":[', vm.toString(id), ']}'));
        cash = address(account).balance;
        vm.prank(accountOwner); account.recoverLiquidate(1);
        assertEq(address(account).balance - cash, 0.03 ether, "actual pack principal redeemed for owner exit");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), beforeFees + feeDelta, "exits never remint");
        _snapshot("liquidated", "liquidate", 0, "{\"count\":1}");
        uint256 credit = FWA.feeCredit(address(account));
        if (credit != 0) {
            cash = address(account).balance;
            vm.prank(accountOwner); account.harvest(new uint256[](0), 0);
            assertEq(address(account).balance - cash, credit);
            _snapshot("earningsWithdrawn", "harvest", 0, string.concat('{"credit":', vm.toString(credit), '}'));
        }
        assertEq(account.openListingCount(), 0); assertEq(account.idlePackCount(), 0); assertEq(account.recoveryPackCount(), 0);
        assertEq(FWA.feeCredit(address(account)), 0);
        assertEq(account.budget(), 0);
        uint256 returned = address(account).balance;
        vm.prank(accountOwner); manager.withdraw(accountOwner, returned);
        assertEq(accountOwner.balance - ownerInitial, returned, "withdrawal transfers actual cash only to the owner");
        assertEq(returned, initialCash - 0.21 ether - primaryFees - keeperPaid + acquisitionIncome,
            "independent full-cycle owner cash, paid mint fees, keeper and external earnings equation");
        assertEq(address(account).balance, 0);
        _snapshot("withdrawn", "withdraw", 0, string.concat('{"amount":', vm.toString(returned), '}'));
    }
}

contract ForkManagerCloseoutReuseTest is ManagerCloseoutBase {
    function parameters() internal pure override returns (VaultLib.Params memory p) {
        p = super.parameters();
    }
    function output() internal pure override returns (string memory) { return "sim/out/manager-measured-final-reuse-trace.jsonl"; }
    function test_managerReuseOwnerPaidExitReconcilesEveryWei() public { _select(false); _finish(false); }
}
