// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Vm} from "forge-std/Vm.sol";
import {ForkBase} from "./ForkBase.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {TestVaultOps} from "../utils/TestVaultOps.sol";

interface RestockShapesFees {
    function redeemableBacking() external view returns (uint256);
    function pendingFees() external view returns (uint256);
    function feeRecipient() external view returns (address);
    function feesOwedTo(address recipient) external view returns (uint256);
}

contract RestockEfficiencyTest is ForkBase {
    bytes32 private constant TRANSFER = keccak256("Transfer(address,address,uint256)");
    uint256[] private expectedLoose;

    function setUp() public override {
        super.setUp();
        _deployMatrixVault();
    }

    function _deployMatrixVault() private {
        setPackAsk(0.33 ether);
        VaultLib.Params memory p = defaultParams();
        p.packUnitsMask = (uint64(1) << 3) | (uint64(1) << 4) | (uint64(1) << 30);
        p.gasCeiling = 0.5 gwei; p.payMarkupBps = 0;
        vm.deal(address(this), 40 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 20 ether);
        assertEq(SHAPES.mintFee(), 0.001 ether);
    }

    function assertEnvironment() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function _cold() private {
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(VaultLib)); vm.cool(policy);
        vm.cool(address(FWA)); vm.cool(address(PACKS)); vm.cool(address(SHAPES)); vm.cool(keeper);
    }

    function _recordStack(Vm.Log[] memory logs, uint256 firstPack, uint256 count, uint256 units) private {
        for (uint256 i; i < logs.length; ++i) {
            Vm.Log memory l = logs[i];
            if (l.emitter != address(SHAPES) || l.topics.length != 4 || l.topics[0] != TRANSFER
                || l.topics[1] != bytes32(0) || address(uint160(uint256(l.topics[2]))) != address(vault)) continue;
            uint256 id = uint256(l.topics[3]);
            // The primary 0.1 ETH Shape is burned by its real ten-way split.
            (bool ok, bytes memory data) = address(SHAPES).staticcall(abi.encodeCall(SHAPES.backingOf, (id)));
            if (ok && data.length >= 32 && abi.decode(data, (uint256)) == 0.01 ether) expectedLoose.push(id);
        }
        for (uint256 c; c < count; ++c) {
            uint256 pack = vault.idlePackAt(firstPack + c);
            uint256[] memory contents = PACKS.contentsOf(pack);
            assertEq(contents.length, units);
            assertEq(PACKS.ownerOf(pack), address(vault));
            assertEq(PACKS.valueOf(pack), units * 0.01 ether);
            for (uint256 j; j < units; ++j) {
                assertEq(contents[j], expectedLoose[expectedLoose.length - 1], "preserve existing LIFO mint/split/pack recipe");
                expectedLoose.pop();
            }
        }
        assertEq(vault.looseShapeCount(), expectedLoose.length);
        for (uint256 i; i < expectedLoose.length; ++i) {
            assertEq(SHAPES.ownerOf(expectedLoose[i]), address(vault));
            assertEq(SHAPES.backingOf(expectedLoose[i]), 0.01 ether);
        }
    }

    function _restock(string memory label, uint256 count, uint256 units) private {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertEnvironment();
        assertTrue(vm.isIsolateMode(), "receipt-equivalent frame gas requires isolated calls");
        uint256[] memory proposals = TestVaultOps.buildProposals(vault, count, units);
        uint256 firstPack = vault.idlePackCount();
        uint256 beforeLoose = vault.looseShapeCount();
        uint256 need = count * units;
        uint256 mints = need > beforeLoose ? (need - beforeLoose + 9) / 10 : 0;
        uint256 vaultBefore = address(vault).balance;
        uint256 shapesBefore = address(SHAPES).balance;
        RestockShapesFees sf = RestockShapesFees(address(SHAPES));
        uint256 backingBefore = sf.redeemableBacking();
        uint256 feesBefore = sf.pendingFees();
        address recipient = sf.feeRecipient();
        uint256 recipientFeesBefore = sf.feesOwedTo(recipient);
        uint256 keeperBefore = keeper.balance;
        (uint256 trackedBefore, uint256 idleBefore,,,,) = vault.totals();
        uint256 fundingBefore = vault.idleFunding();
        bytes memory input = abi.encodeCall(PackVault.restock, (units, proposals, 0));
        uint256 intrinsic = 21_000;
        for (uint256 i; i < input.length; ++i) intrinsic += input[i] == 0 ? 4 : 16;
        vm.recordLogs(); _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        uint256 callMeter = start - gasleft() + intrinsic;
        Vm.Gas memory frame = vm.lastCallGas();
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        Vm.Log[] memory logs = vm.getRecordedLogs();
        uint256 pay = abi.decode(result, (uint256));
        assertEq(keeper.balance - keeperBefore, pay);
        assertEq(vaultBefore - address(vault).balance - pay, mints * 0.101 ether, "primary value plus actual mint fees");
        assertEq(address(SHAPES).balance - shapesBefore, mints * 0.101 ether, "Shapes holds both backing and claimable artist fees");
        assertEq(sf.redeemableBacking() - backingBefore, mints * 0.1 ether);
        assertEq(sf.pendingFees() - feesBefore, mints * 0.001 ether);
        assertEq(sf.feesOwedTo(recipient) - recipientFeesBefore, mints * 0.001 ether);
        (uint256 tracked, uint256 idle,,,,) = vault.totals();
        assertEq(tracked, trackedBefore + mints * 0.1 ether);
        assertEq(idle, idleBefore + mints * 0.1 ether);
        assertEq(vault.idlePackCount(), firstPack + count);
        uint256 funding = fundingBefore;
        for (uint256 i; i < count; ++i) funding += proposals[i];
        assertEq(vault.idleFunding(), funding);
        _recordStack(logs, firstPack, count, units);
        uint256 quoted = VaultLib.Q_RESTOCK + count * VaultLib.packGas(units) + mints * VaultLib.Q_MINT;
        assertEq(pay, quoted * 0.2 gwei + count * vault.getParams().workFee);
        assertGe(frame.gasRefunded, 0);
        uint256 refund = uint256(uint64(frame.gasRefunded));
        uint256 gross = uint256(frame.gasTotalUsed) + refund;
        emit log_named_uint(string.concat(label, " call meter plus intrinsic"), callMeter);
        emit log_named_uint(string.concat(label, " isolated receipt-equivalent gas"), frame.gasTotalUsed);
        emit log_named_uint(string.concat(label, " finalized frame refund"), refund);
        emit log_named_uint(string.concat(label, " isolated gross before refund"), gross);
        emit log_named_uint(string.concat(label, " keeper pay wei"), pay);
        emit log_named_uint(string.concat(label, " newly paid mints"), mints);
        assertLt((gross * 125 + 99) / 100, 16_777_216);
    }

    function test_threeUnitLeftoversAndMixedMintsPreserveExactRecipe() public {
        _restock("three first leftover7", 1, 3);
        _restock("three leftover only4", 1, 3);
        _restock("three mixed old4 new10", 3, 3);
    }

    function test_fourUnitLeftoversAndMixedMintsPreserveExactRecipe() public {
        _restock("four first leftover6", 1, 4);
        _restock("four mixed old6 new10", 2, 4);
        _restock("four leftover only0", 2, 4);
    }

    function test_maximumThirtyUnitNoLeftovers() public {
        _restock("thirty units ten small packs", 10, 3);
        _restock("thirty units one large pack", 1, 30);
    }

    function test_largePackLeavesExistingLoosePrefixUntouched() public {
        _restock("large prefix setup", 1, 3);
        _restock("large consumes thirty new leaves old7", 1, 30);
    }

    function test_allProposalsValidatedBeforeAnyPaidMint() public {
        uint256[] memory proposals = TestVaultOps.buildProposals(vault, 2, 3); proposals[1] = 0;
        uint256 balance = address(vault).balance;
        uint256 supply = SHAPES.totalSupply();
        vm.expectRevert(VaultLib.InvalidBacking.selector);
        vm.prank(keeper); vault.restock(3, proposals, 0);
        assertEq(address(vault).balance, balance); assertEq(SHAPES.totalSupply(), supply);
        assertEq(vault.idlePackCount(), 0); assertEq(vault.looseShapeCount(), 0);
    }

    function test_recentHeadSmallRestock() public {
        uint256 recent = vm.envOr("RESTOCK_RECENT_BLOCK", uint256(0));
        if (recent == 0) { vm.skip(true); return; }
        vm.createSelectFork("https://mainnet.gateway.tenderly.co", recent);
        assertEq(block.number, recent);
        address[4] memory actors = [owner, keeper, alice, bob];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0); assertEq(actors[i].balance, 0);
        }
        vm.deal(keeper, 1 ether);
        _deployMatrixVault();
        emit log_named_uint("recent explicitly pinned mainnet block", recent);
        _restock("recent three-unit primary mint", 1, 3);
    }

    function test_existingIdleFundingPreventsUnfundedLeftoverPack() public {
        uint256 backing = TestVaultOps.buildProposals(vault, 1, 3)[0];
        VaultLib.Params memory p = vault.getParams(); p.reserve = 0.005 ether;
        uint256 pay = (VaultLib.Q_RESTOCK + VaultLib.Q_PACK + VaultLib.Q_MINT) * 0.2 gwei + p.workFee;
        uint256 seed = 0.101 ether + p.reserve + backing + pay + 1;
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, seed);
        _restock("funding boundary first pack", 1, 3);
        uint256[] memory proposals = TestVaultOps.buildProposals(vault, 1, 3);
        assertLt(address(vault).balance - p.reserve, vault.idleFunding() + proposals[0]);
        uint256 balance = address(vault).balance;
        uint256 supply = SHAPES.totalSupply();
        vm.expectRevert(VaultLib.InsufficientBacking.selector);
        vm.prank(keeper); vault.restock(3, proposals, 0);
        assertEq(address(vault).balance, balance); assertEq(SHAPES.totalSupply(), supply);
        assertEq(vault.idlePackCount(), 1); assertEq(vault.looseShapeCount(), 7);
    }

    function test_mintedPrincipalRoundTripRetainsArtistFeeRevenue() public {
        _restock("roundtrip two small packs", 2, 3);
        uint256 before = address(vault).balance;
        uint256 shapesBefore = address(SHAPES).balance;
        RestockShapesFees sf = RestockShapesFees(address(SHAPES));
        uint256 fees = sf.pendingFees();
        uint256 backing = sf.redeemableBacking();
        vm.prank(owner); vault.startWindDown();
        vm.prank(keeper); uint256 pay = vault.liquidate(16, 0);
        assertEq(address(vault).balance - before + pay, 0.1 ether, "all minted principal returns through real redemption");
        assertEq(shapesBefore - address(SHAPES).balance, 0.1 ether);
        assertEq(backing - sf.redeemableBacking(), 0.1 ether);
        assertEq(sf.pendingFees(), fees, "redeeming never takes the artist's accrued fee");
        (uint256 tracked, uint256 idle,,,,) = vault.totals();
        assertEq(tracked, 0); assertEq(idle, 0);
        assertEq(vault.idleFunding(), 0); assertEq(vault.idlePackCount(), 0); assertEq(vault.looseShapeCount(), 0);
    }
}
