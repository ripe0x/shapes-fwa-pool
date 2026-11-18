// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase} from "./ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {IFWAV2} from "../../src/interfaces/External.sol";

/// @dev An empty vault persists while the fork advances through authentic external history.
/// No protocol is persistent, mocked or given fabricated storage. There are no own listings.
contract ForkJournalGasTest is ForkBase {
    function assertGasContext() external {
        assertEq(block.basefee, 0.15 gwei); assertEq(tx.gasprice, 0.2 gwei);
    }

    function _cold() private {
        address policy = address(vault.keeperPolicy());
        vm.cool(address(vault)); vm.cool(address(FWA));
        vm.cool(policy); vm.cool(address(VaultLib));
    }

    function _intrinsic(bytes memory input) private pure returns (uint256 gas_) {
        gas_ = 21_000;
        for (uint256 i; i < input.length; ++i) gas_ += input[i] == 0 ? 4 : 16;
    }

    function _measure(uint256 count) private returns (uint256 used, uint256 pay) {
        bytes memory input = abi.encodeCall(PackVault.sync, (count, new uint256[](0), 0, 0));
        uint256 intrinsic = _intrinsic(input);
        uint256 keeperBefore = keeper.balance; // A real transaction sender is warm under EIP-2929.
        _cold();
        vm.prank(keeper);
        uint256 start = gasleft();
        (bool ok, bytes memory result) = address(vault).call(input);
        used = start - gasleft() + intrinsic;
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
        pay = abi.decode(result, (uint256));
        assertEq(keeper.balance - keeperBefore, pay, "the funded transaction sender receives the quoted payment");
        assertLt(used * 125 / 100, 16_777_216, "complete bounded call plus keeper gas margin");
    }

    function test_realForeignHistoryOneVersusSixteenEntriesAndSplitPay() public {
        uint64 begin = vault.acquisitionCursor();
        uint256 seed = address(vault).balance;
        vm.makePersistent(address(vault));
        vm.makePersistent(address(vault.keeperPolicy()));
        vm.makePersistent(address(VaultLib));
        vm.rollFork(BLOCK + 10_000);
        assertEq(keeper.code.length, 0, "real transaction sender has no delegated code");
        assertEq(keeper.balance, 0, "fork advancement drops the previous actor setup");
        vm.deal(keeper, 1 ether);
        assertEq(keeper.balance, 1 ether, "funded transaction sender, not a newly created payout account");
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertGasContext();
        assertEq(vault.openListingCount(), 0);
        assertEq(vault.acquisitionCursor(), begin);
        assertGe(FWA.nextSequenceToProcess(), uint256(begin) + 16);
        uint256 fulfilled;
        uint256 refunded;
        for (uint64 i; i < 16; ++i) {
            uint256 request = FWA.requestIdAtSequence(begin + i);
            IFWAV2.Acquisition memory a = FWA.acquisitions(request);
            assertTrue(a.status == 2 || a.status == 3 || a.status == 4, "authentic completed global journal record");
            if (a.status == 2) {
                (address collection, address depositor,,,,,,,,,) = FWA.listings(a.listingId);
                assertTrue(collection != address(0));
                assertTrue(depositor != address(vault), "all selected positions belong to real foreign depositors");
                ++fulfilled;
            } else ++refunded;
        }
        uint256 startup = vm.snapshotState();
        (uint256 startupGas, uint256 startupPay) = _measure(1);
        assertTrue(vm.revertToState(startup));
        // Ordinary first use initializes the real Solady guard before maintenance.
        uint256 deposit = vault.requestCharge() + 0.01 ether;
        assertEq(alice.code.length, 0); assertEq(alice.balance, 0);
        vm.deal(alice, deposit);
        vm.prank(alice); vault.deposit{value: deposit}();
        vm.prank(alice); vault.cancelDeposit();
        assertEq(address(vault).balance, seed, "the real request/cancel round trip preserves the seed");
        assertEq(vault.pendingDepositTotal(), 0); assertEq(vault.processingPool(), 0);
        assertEq(vault.acquisitionCursor(), begin);
        uint256 snapshot = vm.snapshotState();
        (uint256 oneGas, uint256 onePay) = _measure(1);
        assertEq(vault.acquisitionCursor(), begin + 1);
        assertEq(seed - address(vault).balance, onePay, "foreign processing paid exclusively from actual free seed ETH");
        assertTrue(vm.revertToState(snapshot));
        (uint256 batchGas, uint256 batchPay) = _measure(16);
        assertEq(vault.acquisitionCursor(), begin + 16);
        assertEq(seed - address(vault).balance, batchPay);
        assertEq(batchPay, (VaultLib.Q_SYNC + 16 * VaultLib.Q_JOURNAL) * 0.2 gwei, "foreign records earn quote component and no flat work fee");
        assertTrue(vm.revertToState(snapshot));
        uint256 splitGas;
        uint256 splitPay;
        for (uint256 i; i < 16; ++i) {
            (uint256 g, uint256 p) = _measure(1); splitGas += g; splitPay += p;
        }
        assertEq(vault.acquisitionCursor(), begin + 16);
        assertEq(vault.processingPool(), 0);
        assertEq(vault.pendingDepositTotal(), 0);
        emit log_named_uint("actual fulfilled foreign entries", fulfilled);
        emit log_named_uint("actual refunded entries", refunded);
        emit log_named_uint("startup one entry gross complete gas", startupGas);
        emit log_named_uint("startup one entry pay wei", startupPay);
        emit log_named_uint("steady one entry gross complete gas", oneGas);
        emit log_named_uint("steady sixteen entries gross complete gas", batchGas);
        emit log_named_uint("steady sixteen split calls gross complete gas", splitGas);
        emit log_named_uint("one entry pay wei", onePay);
        emit log_named_uint("sixteen entries pay wei", batchPay);
        emit log_named_uint("sixteen split calls pay wei", splitPay);
        assertLe(splitPay - batchPay, (splitGas - batchGas) * 0.2 gwei, "splitting cheap journal work must not profit");
    }
}
