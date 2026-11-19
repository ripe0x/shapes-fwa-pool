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

    function _measure() private returns (uint256 used, uint256 pay) {
        bytes memory input = abi.encodeCall(PackVault.sync, (new uint256[](0), 0, 0));
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

    function test_realUnexposedForeignHistoryIsOneUnpaidJob() public {
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
        (uint256 callMeter, uint256 pay) = _measure();
        assertEq(pay, 0, "provably unexposed history earns no journal compensation");
        assertEq(vault.acquisitionCursor(), FWA.nextSequenceToProcess());
        assertEq(address(vault).balance, seed);
        assertEq(vault.processingPool(), 0);
        assertEq(vault.pendingDepositTotal(), 0);
        emit log_named_uint("actual fulfilled foreign sample", fulfilled);
        emit log_named_uint("actual refunded foreign sample", refunded);
        emit log_named_uint("unpaid rebase caller meter plus intrinsic proxy", callMeter);
        vm.expectRevert(VaultLib.Nothing.selector);
        vault.sync(new uint256[](0), 0, 0);
    }
}
