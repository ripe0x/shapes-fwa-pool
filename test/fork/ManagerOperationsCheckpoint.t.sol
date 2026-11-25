// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MainRenewalBase} from "./ForkMainRenewal.t.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Vm, VmSafe} from "forge-std/Vm.sol";

/// @dev Export only state derived from the real request and authenticated proof.
contract ManagerOperationsCheckpointTest is MainRenewalBase {
    string private stem;

    function parameters() internal pure override returns (VaultLib.Params memory p) {
        p = super.parameters();
        p.essentialCeiling = 0.5 gwei;
        p.routineCap = 0.03 ether;
        p.essentialCap = 0.01 ether;
        p.tvlCap = 0;
        p.minDeposit = 0.01 ether;
        p.minDistribution = 0.01 ether;
    }

    function test_exportAuthenticatedAllocatedCheckpoint() public {
        vm.skip(!vm.envOr("EXPORT_MANAGER_OPERATING", false));
        stem = vm.envOr("MANAGER_CHECKPOINT_STEM", string("sim/out/manager-measured-checkpoint"));
        require(!vm.exists(string.concat(stem, "-diff.json")) && !vm.exists(string.concat(stem, "-alloc.json"))
            && !vm.exists(string.concat(stem, "-metadata.json")), "preserve prior checkpoint evidence");
        vm.startStateDiffRecording();
        _select(false);
        assertEq(accountOwner.code.length, 0);
        assertEq(accountOwner.balance, 0);
        assertEq(vm.getNonce(accountOwner), 0);
        assertEq(address(PACKS.ownerOf(packId)), address(FWA));
        vm.writeFile(string.concat(stem, "-diff.json"), vm.getStateDiffJson());
        Vm.AccountAccess[] memory accesses = vm.stopAndReturnStateDiff();
        for (uint256 i; i < accesses.length; ++i) {
            require(accesses[i].reverted || accesses[i].kind != VmSafe.AccountAccessKind.SelfDestruct, "unsupported deletion");
        }
        this.exportFixture();
    }

    function exportFixture() external {
        require(msg.sender == address(this), "export only");
        assertEq(block.basefee, 0.15 gwei, "executed export basefee");
        assertEq(tx.gasprice, 0.2 gwei, "executed export gas price");
        address[] memory critical = new address[](4);
        critical[0] = address(account); critical[1] = address(FWA);
        critical[2] = address(SHAPES); critical[3] = address(PACKS);
        uint256[] memory balances = new uint256[](4);
        uint256[] memory nonces = new uint256[](4);
        bytes[] memory codes = new bytes[](4);
        for (uint256 i; i < 4; ++i) {
            balances[i] = critical[i].balance;
            nonces[i] = vm.getNonce(critical[i]);
            codes[i] = critical[i].code;
        }
        vm.dumpState(string.concat(stem, "-alloc.json"));
        string memory meta = "manager-operating";
        vm.serializeAddress(meta, "manager", address(account));
        vm.serializeAddress(meta, "owner", accountOwner);
        vm.serializeAddress(meta, "purchaser", selectedPurchaser);
        vm.serializeAddress(meta, "harness", address(this));
        vm.serializeBytes32(meta, "requestTx", REQUEST_TX);
        vm.serializeUint(meta, "requestBlock", REQUEST_BLOCK);
        vm.serializeUint(meta, "block", block.number);
        vm.serializeUint(meta, "timestamp", block.timestamp);
        vm.serializeUint(meta, "basefee", block.basefee);
        vm.serializeUint(meta, "listing", selected);
        vm.serializeUint(meta, "pack", packId);
        vm.serializeUint(meta, "mintFeeWei", SHAPES.mintFee());
        vm.serializeBytes(meta, "criticalAccountsAbi", abi.encode(critical, balances, nonces, codes));
        vm.serializeBytes32(meta, "configurationHash", account.configurationHash());
        vm.serializeBytes(meta, "paramsAbi", abi.encode(account.getParams()));
        (bool ok, bytes memory listingData) = address(FWA).staticcall(abi.encodeWithSignature("listings(uint256)", selected));
        require(ok, "listing read failed");
        vm.serializeBytes(meta, "listingAbi", listingData);
        vm.serializeUint(meta, "managerCashWei", address(account).balance);
        vm.serializeUint(meta, "feeCreditWei", FWA.feeCredit(address(account)));
        vm.serializeUint(meta, "openListingCount", account.openListingCount());
        vm.serializeUint(meta, "unsettledAcquisitionCount", FWA.unsettledAcquisitionCount());
        vm.serializeUint(meta, "shapeSupply", SHAPES.totalSupply());
        string memory result = vm.serializeAddress(meta, "packOwner", PACKS.ownerOf(packId));
        vm.writeJson(result, string.concat(stem, "-metadata.json"));
    }
}
