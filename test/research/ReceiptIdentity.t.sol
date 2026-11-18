// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {Test} from "forge-std/Test.sol";
import {Vm} from "forge-std/Vm.sol";

// Exact deployed FWA enum values, also recorded in src/interfaces/External.sol.
uint8 constant R_ACTIVE = 1;
uint8 constant R_ALLOCATED = 2;
uint8 constant R_WITHDRAWN = 3;
uint8 constant R_SETTLED = 4;

interface ReceiptFWA {
    struct Listing {
        address collection;
        address depositor;
        address purchaser;
        uint256 tokenId;
        uint256 weight;
        uint256 value;
        uint256 feeShare;
        uint256 feeDebt;
        uint256 slot;
        uint64 allocatedAt;
        uint8 status;
    }
    function listings(uint256 id) external view returns (Listing memory);
    function owner() external view returns (address);
    function ownerSettlementFeeBps() external view returns (uint256);
    function settlementWindow() external view returns (uint256);
    function unsettledAcquisitionCount() external view returns (uint256);
    function feeCredit(address depositor) external view returns (uint256);
    function accruedOwnerFees() external view returns (uint256);
    function floorOracle() external view returns (address);
    function stuckNFTRecipient(uint256 id) external view returns (address);
    function fwairListing(uint256 id) external view returns (bool);
    function listNFT(address collection, uint256 id) external payable returns (uint256);
    function keepNFT(uint256 id) external;
    function acceptDepositorBid(uint256 id) external;
    function relistNFT(uint256 id) external payable;
    function depositorReclaimBacking(uint256 id) external;
    function withdrawListing(uint256 id) external;
    function withdrawEarnings() external returns (uint256);
    function claimListingFees(uint256[] calldata ids) external returns (uint256);
    function processAcquisitions(uint256 maximum) external returns (uint256);
    function kickListing(uint256 id) external;
    function payoutFees() external returns (uint256);
    function setUint(uint256 key, uint256 value) external;
    function setAddr(uint256 key, address value) external;
    function setOracleExemptCollection(address collection, bool exempt) external;
}

interface ReceiptPacks {
    function createPack(uint256[] calldata ids, uint32[] calldata counts) external payable returns (uint256);
    function setApprovalForAll(address operator, bool approved) external;
    function ownerOf(uint256 id) external view returns (address);
    function valueOf(uint256 id) external view returns (uint256);
    function balanceOf(address owner) external view returns (uint256);
}

interface ReceiptShapes { function mintFee() external view returns (uint256); }
interface ReceiptOracle {
    function owner() external view returns (address);
    function setFloor(address collection, uint256 value) external;
}

/// @notice RESEARCH ONLY. Tests whether the deployed FWA's ETH payment identifies
///         a fresh terminal listing cheaply enough to update a separate change ledger.
///         This is not a vault or a production accounting implementation.
contract ReceiptIdentityProbe {
    ReceiptFWA public immutable fwa;
    ReceiptPacks public immutable packs;
    ReceiptShapes public immutable shapes;
    mapping(uint256 backing => uint256 listingId) public idForBacking;
    // Prepare the slot during listing. The later bounded receiver must never
    // need a zero-to-nonzero storage write for a legitimate terminal payment.
    struct Receipt { uint128 amount; uint16 feeBps; uint8 kind; bool initialized; }
    mapping(uint256 listingId => Receipt) public receipts;
    uint256 internal pendingPlusOne = 1;
    bool internal controlled;

    // Gas reported excludes this final instrumentation log. The test adds a
    // conservative 3,000 gas allowance and also inspects actual FWA execution.
    event ReceiptObserved(uint256 indexed listingId, uint8 kind, uint256 logicGas);

    constructor(ReceiptFWA f, ReceiptPacks p, ReceiptShapes s) payable {
        fwa = f;
        packs = p;
        shapes = s;
        p.setApprovalForAll(address(f), true);
    }

    receive() external payable {
        uint256 start = gasleft();
        if (msg.sender != address(fwa) || controlled) return;
        uint256 fee = fwa.ownerSettlementFeeBps();
        if (fee < 10_000) {
            uint256 denominator = 10_000 - fee;
            // Divide before multiplying: unrelated receipts never overflow.
            if (msg.value % denominator == 0 && msg.value / denominator <= type(uint256).max / 10_000) {
                if (_identify(msg.value / denominator * 10_000, 1, fee)) {
                    emit ReceiptObserved(idForBacking[msg.value / denominator * 10_000], 1, start - gasleft());
                    return;
                }
            }
        }
        if (_identify(msg.value, 2, fee)) {
            emit ReceiptObserved(idForBacking[msg.value], 2, start - gasleft());
        }
    }

    function _identify(uint256 backing, uint8 kind, uint256 fee) private returns (bool) {
        uint256 id = idForBacking[backing];
        if (id == 0 || receipts[id].kind != 0 || msg.value > type(uint128).max) return false;
        ReceiptFWA.Listing memory listing = fwa.listings(id);
        if (listing.depositor != address(this) || listing.collection != address(packs)) return false;
        if (kind == 1) {
            // A previous failed bid also leaves a Settled pack in FWA custody.
            // A genuine keep ETH payment precedes NFT delivery and its claim.
            if (listing.status != R_SETTLED || fwa.stuckNFTRecipient(id) != address(0)
                || packs.ownerOf(listing.tokenId) != address(fwa)) return false;
        } else if (listing.status != R_WITHDRAWN) {
            return false;
        }
        receipts[id] = Receipt(uint128(msg.value), uint16(fee), kind, true);
        ++pendingPlusOne;
        return true;
    }

    function pendingCount() external view returns (uint256) { return pendingPlusOne - 1; }

    function createAndList(uint256 backing) external virtual returns (uint256 id) {
        require(backing % 10_000 == 0 && idForBacking[backing] == 0, "unique quantized backing");
        uint32[] memory mintCounts = new uint32[](9);
        mintCounts[0] = 3;
        // Test fixture only: independent fresh packs, not a production mint policy.
        uint256 pack = packs.createPack{value: 0.03 ether + 3 * shapes.mintFee()}(new uint256[](0), mintCounts);
        id = fwa.listNFT{value: backing}(address(packs), pack);
        require(!fwa.fwairListing(id), "ordinary listing only");
        require(fwa.listings(id).status == R_ACTIVE, "active admission");
        idForBacking[backing] = id;
        receipts[id].initialized = true;
    }

    function reclaimBacking(uint256 id) external virtual { fwa.depositorReclaimBacking(id); }

    function controlledWithdraw(uint256 id) external virtual {
        uint256 backing = fwa.listings(id).value;
        controlled = true;
        fwa.withdrawListing(id);
        controlled = false;
        delete idForBacking[backing];
    }

    function controlledHarvest(uint256[] calldata ids) external virtual {
        controlled = true;
        if (ids.length != 0) fwa.claimListingFees(ids);
        if (fwa.feeCredit(address(this)) != 0) fwa.withdrawEarnings();
        controlled = false;
    }

    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }
}

/// @dev Historical replay filler, with separate ownership from the probe. The
///      real fixture's randomness depends on the EXACT total selection weight.
contract ReceiptFixtureFiller {
    ReceiptFWA private immutable fwa;
    ReceiptPacks private immutable packs;
    ReceiptShapes private immutable shapes;
    constructor(ReceiptFWA f, ReceiptPacks p, ReceiptShapes s) payable {
        fwa = f; packs = p; shapes = s;
        p.setApprovalForAll(address(f), true);
    }
    function createAndList(uint256 backing) external returns (uint256) {
        uint32[] memory counts = new uint32[](9);
        counts[0] = 3;
        uint256 pack = packs.createPack{value: 0.03 ether + 3 * shapes.mintFee()}(new uint256[](0), counts);
        return fwa.listNFT{value: backing}(address(packs), pack);
    }
    function onERC721Received(address, address, uint256, bytes calldata) external pure returns (bytes4) {
        return this.onERC721Received.selector;
    }
}

contract ReceiptIdentityTest is Test {
    ReceiptFWA constant FWA = ReceiptFWA(0x958C41181182e76F221331b2755b77D9e1426A98);
    ReceiptPacks constant PACKS = ReceiptPacks(0xf21514B090Da7dF4390803497d6ae673801E5cA7);
    ReceiptShapes constant SHAPES = ReceiptShapes(0x6fE9193276bF7aBCbEE44AB7aFd717d637D6FAf0);
    bytes32 constant REQUEST_TX = 0x7a2e33446681244f37d801df737f7017e3e9258d49fa6465e95983f5a3b81a6f;
    bytes32 constant OBSERVED = keccak256("ReceiptObserved(uint256,uint8,uint256)");
    address constant PURCHASER = 0x6A51eEe3a2C2d33921844965738aE99b81dbFf95;
    uint256 constant FEE_KEY = 19;
    uint256 constant PAYOUT_KEY = 61;
    ReceiptIdentityProbe probe;
    uint256 selected;
    uint256 selectedBacking;

    receive() external payable {}

    function _deploy() internal virtual {
        vm.deal(address(this), 20 ether);
        probe = new ReceiptIdentityProbe{value: 10 ether}(FWA, PACKS, SHAPES);
    }

    function _quiet() internal {
        vm.createSelectFork("mainnet", 26_424_971);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        _deploy();
    }

    function _select(uint256 fee) internal {
        vm.createSelectFork("mainnet", REQUEST_TX);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        vm.prank(FWA.owner());
        FWA.setUint(FEE_KEY, fee);
        _deploy();
        ReceiptFixtureFiller filler = new ReceiptFixtureFiller{value: 3 ether}(FWA, PACKS, SHAPES);
        uint256[] memory ids = new uint256[](30);
        for (uint256 i; i < ids.length; ++i) {
            // Backing tags only need to be unique within one depositor's live
            // book. Separate filler ownership preserves exact historical weight.
            ids[i] = i == 28 ? probe.createAndList(0.0363 ether) : filler.createAndList(0.0363 ether);
        }
        selected = ids[28];
        selectedBacking = FWA.listings(selected).value;
        assertEq(FWA.listings(selected).slot, 1631, "historical slot");

        string memory fixture = vm.readFile("test/fixtures/selection.json");
        string memory key = ".26417086";
        _replay(fixture, key, "req");
        vm.roll(26_417_091);
        vm.warp(1_794_705_887);
        vm.setBlockhash(26_417_086, vm.parseJsonBytes32(fixture, string.concat(key, ".reqBlockHash")));
        vm.fee(vm.parseJsonUint(fixture, string.concat(key, ".fulBaseFee")));
        _replay(fixture, key, "ful");
        assertEq(FWA.listings(selected).status, R_ALLOCATED, "real VRF selected tagged listing");
        assertEq(FWA.listings(selected).purchaser, PURCHASER);
    }

    function _replay(string memory fixture, string memory key, string memory leg) internal {
        address from = vm.parseJsonAddress(fixture, string.concat(key, ".", leg, "From"));
        address to = vm.parseJsonAddress(fixture, string.concat(key, ".", leg, "To"));
        bytes memory input = vm.parseJsonBytes(fixture, string.concat(key, ".", leg, "Input"));
        uint256 value = keccak256(bytes(leg)) == keccak256("req")
            ? vm.parseJsonUint(fixture, string.concat(key, ".reqValue")) : 0;
        vm.txGasPrice(vm.parseJsonUint(fixture, string.concat(key, ".", leg, "GasPrice")));
        vm.prank(from, from);
        (bool ok, bytes memory result) = to.call{value: value}(input);
        if (!ok) assembly ("memory-safe") { revert(add(result, 32), mload(result)) }
    }

    function _assertReceipt(uint256 id, uint256 amount, uint256 fee, uint8 kind) internal view {
        (uint128 paid, uint16 usedFee, uint8 actualKind, bool initialized) = probe.receipts(id);
        assertTrue(initialized, "receipt storage prepared at listing");
        assertEq(paid, amount, "exact receipt amount");
        assertEq(usedFee, fee, "fee at payment");
        assertEq(actualKind, kind, "identified terminal state");
    }

    function _assertGas(Vm.Log[] memory logs, uint256 id) internal {
        bool found;
        for (uint256 i; i < logs.length; ++i) {
            if (logs[i].emitter != address(probe) || logs[i].topics.length != 2 || logs[i].topics[0] != OBSERVED) continue;
            if (uint256(logs[i].topics[1]) != id) continue;
            (, uint256 gasUsed) = abi.decode(logs[i].data, (uint8, uint256));
            emit log_named_uint("receiver logic gas", gasUsed);
            emit log_named_uint("receiver gas bound including instrumentation", gasUsed + 3_000);
            assertLt(gasUsed + 3_000, 100_000, "below FWA stipend including log allowance");
            found = true;
        }
        assertTrue(found, "receiver ran and identified the payment");
    }

    function _cold() internal {
        // Fixture creation and replay share a Solidity test call. Explicitly
        // reset account/slot warmth to model a separate real settlement tx.
        vm.cool(address(probe));
        vm.cool(address(FWA));
        vm.cool(address(PACKS));
    }

    function _keepAtFee(uint256 fee) internal {
        _select(fee);
        uint256 before = address(probe).balance;
        uint256 expected = selectedBacking * (10_000 - fee) / 10_000;
        vm.recordLogs();
        _cold();
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        _assertGas(vm.getRecordedLogs(), selected);
        _assertReceipt(selected, expected, fee, 1);
        assertEq(address(probe).balance - before, expected);
        assertEq(probe.pendingCount(), 1);
        assertEq(PACKS.ownerOf(FWA.listings(selected).tokenId), PURCHASER);
    }

    function test_realKeepAtDefaultFee() public { _keepAtFee(100); }
    function test_realKeepAtZeroFee() public { _keepAtFee(0); }
    function test_realKeepAtMaximumFee() public { _keepAtFee(500); }

    function test_realCashBidDoesNotInventETHReceipt() public {
        _select(100);
        uint256 before = address(probe).balance;
        vm.prank(PURCHASER);
        FWA.acceptDepositorBid(selected);
        assertEq(address(probe).balance, before);
        assertEq(probe.pendingCount(), 0);
        assertEq(PACKS.ownerOf(FWA.listings(selected).tokenId), address(probe));
        assertEq(FWA.listings(selected).status, R_SETTLED);
    }

    function test_realSilentPurchaserReclaimIdentifiesReceipt() public {
        _select(100);
        vm.warp(block.timestamp + FWA.settlementWindow());
        uint256 before = address(probe).balance;
        vm.recordLogs();
        _cold();
        probe.reclaimBacking(selected);
        _assertGas(vm.getRecordedLogs(), selected);
        _assertReceipt(selected, selectedBacking * 9_900 / 10_000, 100, 1);
        assertEq(address(probe).balance - before, selectedBacking * 9_900 / 10_000);
    }

    function test_realRelistIdentifiesReceiptWithoutNFTTransfer() public {
        _select(100);
        uint256 before = address(probe).balance;
        vm.recordLogs();
        _cold();
        vm.prank(PURCHASER);
        FWA.relistNFT{value: selectedBacking}(selected);
        _assertGas(vm.getRecordedLogs(), selected);
        _assertReceipt(selected, selectedBacking * 9_900 / 10_000, 100, 1);
        assertEq(address(probe).balance - before, selectedBacking * 9_900 / 10_000);
        assertEq(PACKS.ownerOf(FWA.listings(selected).tokenId), address(FWA));
    }

    function _prepareKickWithSettledBidDecoy() internal returns (uint256 kicked, uint256 kickBacking) {
        _select(100);
        vm.prank(PURCHASER);
        FWA.acceptDepositorBid(selected);
        assertEq(PACKS.ownerOf(FWA.listings(selected).tokenId), address(probe));
        assertEq(FWA.stuckNFTRecipient(selected), address(0));
        assertEq(probe.pendingCount(), 0);
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        FWA.processAcquisitions(100);
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        kickBacking = selectedBacking * 9_900 / 10_000;
        assertEq(kickBacking % 10_000, 0);
        kicked = probe.createAndList(kickBacking);
        assertEq(FWA.ownerSettlementFeeBps(), 100);
        vm.prank(FWA.owner());
        FWA.setOracleExemptCollection(address(PACKS), false);
        ReceiptOracle oracle = ReceiptOracle(FWA.floorOracle());
        vm.prank(oracle.owner());
        oracle.setFloor(address(PACKS), 0.03 ether);
        uint256 next = block.timestamp - block.timestamp % 12 hours + 11 hours + 46 minutes;
        if (next <= block.timestamp) next += 12 hours;
        vm.warp(next);
    }

    function test_realKickChecksSettledBidDecoyAndRecordsCorrectID() public {
        (uint256 kicked, uint256 backing) = _prepareKickWithSettledBidDecoy();
        uint256 before = address(probe).balance;
        vm.recordLogs();
        _cold();
        FWA.kickListing(kicked);
        _assertGas(vm.getRecordedLogs(), kicked);
        _assertReceipt(kicked, backing, 100, 2);
        _assertReceipt(selected, 0, 0, 0);
        assertEq(probe.pendingCount(), 1);
        assertEq(address(probe).balance - before, backing);
        assertEq(PACKS.ownerOf(FWA.listings(kicked).tokenId), address(probe));
    }

    function test_lowGasKickNeverCommitsAnUnrecordedPayment() public {
        (uint256 kicked, uint256 backing) = _prepareKickWithSettledBidDecoy();
        uint256 snapshot = vm.snapshotState();
        uint256 before = address(probe).balance;
        uint256 succeeded;
        uint256 failed;
        uint256 stuck;
        uint256 firstSuccess;
        for (uint256 gasLimit = 20_000; gasLimit <= 600_000; gasLimit += 10_000) {
            assertTrue(vm.revertToState(snapshot));
            _cold();
            (bool ok,) = address(FWA).call{gas: gasLimit}(abi.encodeCall(ReceiptFWA.kickListing, (kicked)));
            if (ok) {
                if (firstSuccess == 0) firstSuccess = gasLimit;
                ++succeeded;
                assertEq(probe.pendingCount(), 1, "successful kick payment must be recorded");
                assertEq(address(probe).balance - before, backing);
                _assertReceipt(kicked, backing, 100, 2);
                _assertReceipt(selected, 0, 0, 0);
                if (FWA.stuckNFTRecipient(kicked) != address(0)) ++stuck;
            } else {
                ++failed;
                assertEq(probe.pendingCount(), 0);
                assertEq(address(probe).balance, before, "failed kick is atomic");
                assertEq(FWA.listings(kicked).status, R_ACTIVE);
            }
        }
        emit log_named_uint("failed kick gas limits", failed);
        emit log_named_uint("successful kick gas limits", succeeded);
        emit log_named_uint("successful kicks with stuck NFT", stuck);
        emit log_named_uint("first successful kick gas limit", firstSuccess);
        assertGt(failed, 0);
        assertGt(succeeded, 0);
    }

    function test_controlledWithdrawalDoesNotCreateAsyncReceipt() public {
        _quiet();
        uint256 id = probe.createAndList(0.032 ether);
        uint256 before = address(probe).balance;
        probe.controlledWithdraw(id);
        assertEq(address(probe).balance - before, 0.032 ether);
        assertEq(probe.pendingCount(), 0);
        assertEq(probe.idForBacking(0.032 ether), 0);
        assertEq(PACKS.ownerOf(FWA.listings(id).tokenId), address(probe));
    }

    function test_controlledFeeCreditHarvestDoesNotCreateAsyncReceipt() public {
        _select(100);
        uint256 credit = FWA.feeCredit(address(probe));
        assertGt(credit, 0);
        uint256 before = address(probe).balance;
        probe.controlledHarvest(new uint256[](0));
        assertEq(address(probe).balance - before, credit);
        assertEq(FWA.feeCredit(address(probe)), 0);
        assertEq(probe.pendingCount(), 0);
    }

    function test_protocolAndStrangerGiftsDoNotDuplicateTerminalReceipt() public {
        _select(100);
        vm.prank(FWA.owner());
        FWA.setAddr(PAYOUT_KEY, address(probe));
        assertGt(FWA.accruedOwnerFees(), 0);
        uint256 before = address(probe).balance;
        uint256 gift = FWA.payoutFees();
        assertEq(address(probe).balance - before, gift);
        assertEq(probe.pendingCount(), 0);
        vm.prank(PURCHASER);
        FWA.keepNFT(selected);
        assertEq(probe.pendingCount(), 1);
        // Settlement creates another genuine protocol-fee payout to the probe.
        FWA.payoutFees();
        (bool donated,) = address(probe).call{value: selectedBacking * 9_900 / 10_000}("");
        assertTrue(donated);
        assertEq(probe.pendingCount(), 1);
        _assertReceipt(selected, selectedBacking * 9_900 / 10_000, 100, 1);
    }

    function test_lowGasKeepNeverCommitsAnUnrecordedPayment() public {
        _select(100);
        uint256 snapshot = vm.snapshotState();
        uint256 before = address(probe).balance;
        uint256 succeeded;
        uint256 failed;
        uint256 firstSuccess;
        for (uint256 gasLimit = 20_000; gasLimit <= 800_000; gasLimit += 20_000) {
            assertTrue(vm.revertToState(snapshot));
            _cold();
            vm.prank(PURCHASER);
            (bool ok,) = address(FWA).call{gas: gasLimit}(abi.encodeCall(ReceiptFWA.keepNFT, (selected)));
            if (ok) {
                if (firstSuccess == 0) firstSuccess = gasLimit;
                ++succeeded;
                assertEq(probe.pendingCount(), 1, "successful payment must be recorded");
                assertEq(address(probe).balance - before, selectedBacking * 9_900 / 10_000);
                _assertReceipt(selected, selectedBacking * 9_900 / 10_000, 100, 1);
            } else {
                ++failed;
                assertEq(probe.pendingCount(), 0);
                assertEq(address(probe).balance, before, "failed attempt is atomic");
                assertEq(FWA.listings(selected).status, R_ALLOCATED);
            }
        }
        emit log_named_uint("failed gas limits", failed);
        emit log_named_uint("successful gas limits", succeeded);
        emit log_named_uint("first successful gas limit", firstSuccess);
        assertGt(failed, 0);
        assertGt(succeeded, 0);
    }
}
