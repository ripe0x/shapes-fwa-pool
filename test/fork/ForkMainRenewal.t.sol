// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {ForkBase, IOwnable, IFwaAdmin} from "./ForkBase.sol";
import {IFwaSettle} from "./ForkSelection.t.sol";
import {IShapesFeeAdmin} from "./ForkMainConfiguration.t.sol";
import {ReceiptFixtureFiller, ReceiptFWA, ReceiptPacks, ReceiptShapes} from "../research/ReceiptIdentity.t.sol";
import {PackAccount} from "../../src/PackAccount.sol";
import {PackVault} from "../../src/PackVault.sol";
import {PackManager} from "../../src/PackManager.sol";
import {PackManagerFactory} from "../../src/PackManagerFactory.sol";
import {DeployCore} from "../../script/DeployCore.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {LISTING_ALLOCATED} from "../../src/interfaces/External.sol";

/// @notice The real request/proof at block 26385001 selects slot 339 after thirty .21 ETH listings.
abstract contract MainRenewalBase is ForkBase {
    uint256 internal constant REQUEST_BLOCK = 26_385_001;
    bytes32 internal constant REQUEST_TX = 0xf54ef3743c08e26cc43c125eef04188f114d47d38b9d801c0b56a051a19227ab;
    address internal constant BUYER = address(bytes20(hex"4de365ea3b8e94f30b4d5bfd9d89fae323bee55d"));
    struct ReplayCandidate { uint256 blockNumber; bytes32 requestTx; uint256 count; uint256 index; uint256 slot; address purchaser; }
    uint256 internal fixtureRequestBlock;
    address internal selectedPurchaser;
    uint256 internal selected;
    uint256 internal packId;
    PackAccount internal account;
    address internal accountOwner;

    receive() external payable {}

    function setUp() public virtual override {}

    function parameters() internal pure virtual returns (VaultLib.Params memory p) {
        p = defaultParams();
        p.packUnitsMask = 8;
        p.backingRatioBps = 70_000;
        p.upliftBoundBps = 25;
        p.reserve = 0.005 ether;
        p.gasCeiling = 0.5 gwei;
        p.essentialCeiling = 2 gwei;
    }

    function one(uint256 id) internal pure returns (uint256[] memory ids) {
        ids = new uint256[](1);
        ids[0] = id;
    }

    function backing() internal pure returns (uint256[] memory) { return one(0.21 ether); }

    function _select(bool pooled) internal {
        _selectCandidate(pooled, ReplayCandidate(REQUEST_BLOCK, REQUEST_TX, 30, 24, 339, BUYER));
    }

    function _selectCandidate(bool pooled, ReplayCandidate memory c) internal {
        vm.createSelectFork("mainnet", c.requestTx);
        vm.recordLogs();
        fixtureRequestBlock = c.blockNumber;
        selectedPurchaser = c.purchaser;
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
        accountOwner = makeAddr("pack-vault-test-main-renewal-owner");
        assertEq(accountOwner.code.length, 0);
        assertEq(accountOwner.balance, 0);
        vm.deal(address(this), 30 ether);
        address[] memory cols = new address[](1);
        cols[0] = address(PACKS);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaSettle(address(FWA)).setCollectionsWhitelisted(cols, true);
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        if (pooled) {
            account = DeployCore.deploy(FWA, SHAPES, PACKS, accountOwner, parameters(), _initialFunding(), keccak256(abi.encode(parameters(), SHAPES.mintFee(), false, false)));
        } else {
            PackManagerFactory factory = new PackManagerFactory(FWA, SHAPES, PACKS);
            VaultLib.Params memory p = parameters();
            account = factory.create{value: _initialFunding()}(accountOwner, p, factory.configHashFor(p));
        }
        _beforeInitialBuild();
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: _fillerFunding()}(
            ReceiptFWA(address(FWA)), ReceiptPacks(address(PACKS)), ReceiptShapes(address(SHAPES)));
        for (uint256 i; i < c.count; ++i) {
            if (i == c.index || _additionalBuild(i)) {
                uint256 supply = SHAPES.totalSupply();
                uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
                uint256[] memory initialBacking = _initialBacking(i);
                uint256 initialPay = account.build(3, initialBacking, 0, account.configurationHash());
                _afterInitialBuild(initialPay);
                assertEq(SHAPES.totalSupply() - supply, 3, "account's initial three paid primary mints");
                assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees() - fees, 0.003 ether);
                if (i == c.index) {
                    selected = account.openListingAt(account.openListingCount() - 1);
                    packId = account.position(selected).packId;
                }
                assertEq(account.position(account.openListingAt(account.openListingCount() - 1)).backing, initialBacking[0]);
            } else filler.createAndList(0.21 ether);
        }
        (,,,,,,,, uint256 slot,,) = FWA.listings(selected);
        assertEq(slot, c.slot, "reconstructed real slot");
        string memory fx = vm.readFile("test/fixtures/completion-selection.json");
        _beforeRequest();
        _call(fx, "req");
        string memory key = string.concat(".", vm.toString(fixtureRequestBlock));
        vm.roll(vm.parseJsonUint(fx, string.concat(key, ".fulBlock")));
        vm.warp(vm.parseJsonUint(fx, string.concat(key, ".fulTimestamp")));
        vm.setBlockhash(fixtureRequestBlock, vm.parseJsonBytes32(fx, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fx, string.concat(key, ".fulBaseFee")));
        _call(fx, "ful");
        for (uint256 i = 2; i <= _fulfillmentCount(); ++i) _call(fx, string.concat("ful", vm.toString(i)));
        (,, address purchaser,,,,,,,, uint8 status) = FWA.listings(selected);
        assertEq(status, LISTING_ALLOCATED, "actual Chainlink proof selected our listing");
        assertEq(purchaser, selectedPurchaser);
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function _call(string memory fx, string memory leg) internal {
        string memory key = string.concat(".", vm.toString(fixtureRequestBlock), ".", leg);
        address from = vm.parseJsonAddress(fx, string.concat(key, "From"));
        address to = vm.parseJsonAddress(fx, string.concat(key, "To"));
        bytes memory input = vm.parseJsonBytes(fx, string.concat(key, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req")
            ? vm.parseJsonUint(fx, string.concat(".", vm.toString(fixtureRequestBlock), ".reqValue")) : 0;
        vm.txGasPrice(vm.parseJsonUint(fx, string.concat(key, "GasPrice")));
        vm.prank(from, from);
        (bool ok, bytes memory result) = to.call{value: value}(input);
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
    }

    function _bidAndRecover() internal {
        uint256 paid = account.sync(new uint256[](0), 0, 0, account.configurationHash());
        _traceRenewalStep("allocated", paid);
        assertEq(account.unresolvedUplift(), 0.18 ether, "maximum positive keep uplift uses zero settlement fee");
        vm.prank(selectedPurchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _traceRenewalStep("bid", 0);
        account.recover(one(selected), 0);
        _traceRenewalStep("returned", 0);
        assertEq(account.unresolvedUplift(), 0, "exact stored contribution removed at terminal transition");
        assertEq(account.idleValueOf(packId), 0.03 ether, "returned original principal stays tracked");
        assertEq(PACKS.ownerOf(packId), address(account));
        _drainOtherRequest();
        _traceRenewalStep("drained", 0);
    }

    function _drainOtherRequest() internal {
        // This historical acquisition submitted two requests. Its other real request expires;
        // the public processor performs the same refund/queue progress production callers use.
        toOpen();
        IFwaSettle(address(FWA)).processAcquisitions(32);
        assertEq(FWA.unsettledAcquisitionCount(), 0, "real queue drained before new exposure");
        vm.fee(0.15 gwei);
        vm.txGasPrice(0.2 gwei);
    }

    function _initialFunding() internal pure virtual returns (uint256) { return 3 ether; }
    function _beforeInitialBuild() internal virtual {}
    function _afterInitialBuild(uint256) internal virtual {}
    function _beforeRequest() internal virtual {}
    function _traceRenewalStep(string memory, uint256) internal virtual {}
    function _additionalBuild(uint256) internal view virtual returns (bool) { return false; }
    function _initialBacking(uint256) internal view virtual returns (uint256[] memory) { return backing(); }
    function _fillerFunding() internal view virtual returns (uint256) { return 10 ether; }
    function _fulfillmentCount() internal view virtual returns (uint256) { return 1; }
}

/// @notice Acquisition returns reuse their exact existing pack; keeps alone require new builds.
contract ForkMainReuseTest is MainRenewalBase {
    function test_managerBidRelistsSamePackWithoutPrimaryMintOrRetirement() public {
        _select(false);
        _bidAndRecover();
        uint256 supply = SHAPES.totalSupply();
        uint256 fees = IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 paid = account.list(backing(), 0, account.configurationHash());
        assertGt(paid, 0);
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(), fees);
        assertEq(account.position(account.openListingAt(0)).packId, packId);
        assertEq(account.inventoryShapeCount(packId), 3);
        assertEq(account.idlePackCount(), 0);
    }

    function test_vaultBidRelistsSamePackWithoutFreshMints() public {
        _select(true);
        _bidAndRecover();
        uint256 supply = SHAPES.totalSupply();
        account.list(backing(), 0, account.configurationHash());
        assertEq(SHAPES.totalSupply(), supply);
        assertEq(account.position(account.openListingAt(0)).packId, packId);
    }

    function test_disablingBuildRecipeDoesNotDisableReturnedPackReuse() public {
        _select(false);
        _bidAndRecover();
        VaultLib.Params memory p = account.getParams();
        p.packUnitsMask = 0;
        bytes32 expected = account.configurationHash();
        vm.prank(accountOwner);
        account.setParams(p, expected);
        account.list(backing(), 0, account.configurationHash());
        assertEq(account.position(account.openListingAt(0)).packId, packId);
    }
}
