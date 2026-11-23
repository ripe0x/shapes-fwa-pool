// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {TestVaultOps} from "../utils/TestVaultOps.sol";

import {DeployCore} from "../../script/DeployCore.sol";
import {FlowBreakdown} from "../utils/FlowBreakdown.sol";
import {SelectionBase, IFwaSettle} from "../fork/ForkSelection.t.sol";
import {ForceSender, IOwnable, IOracleAdmin, IFwaAdmin} from "../fork/ForkBase.sol";
import {PackVault} from "../../src/PackVault.sol";
import {KeeperPolicyV1} from "../../src/KeeperPolicy.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {Charges} from "../utils/Charges.sol";
import {
    IShapes,
    IShapePacks,
    IFWAV2,
    IFWARewards,
    IFWAToken,
    LISTING_ACTIVE,
    LISTING_ALLOCATED,
    LISTING_STAGED,
    LISTING_SETTLED,
    LISTING_WITHDRAWN
} from "../../src/interfaces/External.sol";

/// @notice Asset-flow breakdown for PackVault (docs/SYSTEM-MAP.md). Every regime runs on a real
///         mainnet fork with the real FWA pool, its rewards module, oracle, Shapes, ShapePacks and
///         FWA token. Nothing is mocked. Selections come only from replaying real VRF requests and
///         fulfillments (the two historical fixtures sim/find_selection.py found, inherited through
///         SelectionBase); pinned-block regimes never fabricate a selection, so their listings stay
///         active and resolutions there come only from real oracle/FWA-owner actions (kicks).
///
///         Each regime calls flowReport, which prints where every wei that entered went, where
///         assets sit against each holder's own need, and which one-way flows reverse, then writes
///         docs/receipts/flow/<regime>.json for asset_gate.py. ETH conservation is asserted to the
///         wei (flowTolerance 0). FWA token entitlements are reported as flows and facts in token
///         units, never as ETH buckets: tokens are claimed and burned, worth zero to holders (D43),
///         so they never enter the ETH conservation sum.
///
///         Parameters are the mainnet deployment values (deploy/mainnet.json): gas ceiling
///         0.5 gwei, reserve 0.005 ETH, TVL cap 2 ETH, routine budget 0.03 ETH refilling 0.01 ETH a day,
///         no essential budget, no markup, 25% keeper share.
///         Stated variations are named in each regime that needs one (distributions on; the real
///         VRF fixtures carry SelectionBase's own deploy, noted in the selection regimes).
/// @dev Split into two test contracts sharing this base: one contract holding every regime
///      exceeded solc's via-IR assembly limit ("Tag too large for reserved space").
abstract contract VaultFlowBase is SelectionBase, FlowBreakdown {
    uint256 constant PINNED = 26_424_971; // queue empty, outside blackout, pack quote ~31h old
    uint256 constant UNIT = 0.01 ether;
    uint256 constant INTERVAL = 12 hours;
    uint256 constant BLACKOUT = 11 hours + 45 minutes;

    // Realistic gas for every regime that does not state otherwise (ForkBase's values).
    uint64 constant GAS_PRICE = 0.2 gwei;
    uint64 constant BASE_FEE = 0.15 gwei;

    address alice = makeAddr("pack-vault-test-alice");
    address bob = makeAddr("pack-vault-test-bob");
    address keeper = makeAddr("pack-vault-test-keeper");
    address owner = makeAddr("pack-vault-test-admin"); // one role (D59)

    uint256 preexisting; // ETH already at the deploy address (dust), part of the seed inflow

    // ---- cumulative ETH counters, each measured from a real balance change at the moment it moves
    uint256 depositedCum; // inflow: holder deposits plus the deploy seed and dust
    uint256 feeHarvestedCum; // inflow (realized part): FWA fees pulled into the vault balance
    uint256 forcedCum; // inflow: ETH forced in with no call (donations, FWA's forceSafeTransferETH)
    uint256 keeperPaidCum; // outflow: gas reimbursement plus premium paid to callers
    uint256 mintFeesCum; // outflow: Shapes mint fee, 0.001 ETH per 0.1 ETH minted
    uint256 bidBackingOutCum; // outflow: full backing that leaves on a bid (0.9 to purchaser, 0.1 to FWA)
    uint256 settlementCutCum; // outflow: FWA settlement fee kept on a keep/silent outcome
    uint256 packToPurchaserCum; // outflow: pack value delivered to a purchaser (keep/silent)
    uint256 claimsCum; // outflow: redemptions and distributions paid to holders
    uint256 guardChecks; // O5: liability checks run after every keeper call in this regime
    uint256 cancelsCum; // outflow: cancelled deposits refunded

    // ---- flow-only cumulatives (reported, not in the conservation sum)
    uint256 backingPostedCum; // vault -> FWA backing posted on list/relist
    uint256 backingReturnedCum; // FWA -> vault backing returned (kick, keep, silent, unlist)
    uint256 mintedValueCum; // vault -> Shapes redeemable value minted
    uint256 redeemedCum; // Shapes -> vault value redeemed (liquidate)
    uint256 tokensClaimedCum; // FWA token units claimed (token units, informational)
    uint256 tokensBurnedCum; // FWA token units burned

    receive() external payable {}

    // ------------------------------------------------------------------ helpers

    function _forkPinned() internal {
        vm.createSelectFork("mainnet", PINNED);
        address[4] memory actors = [alice, bob, keeper, owner];
        for (uint256 i; i < actors.length; ++i) {
            assertEq(actors[i].code.length, 0, "test actor has code on mainnet");
            assertEq(actors[i].balance, 0, "test actor has mainnet balance");
        }
        // D62 live mainnet state: ShapePacks is oracle-exempt, so the 6-unit backing (~0.065 ETH,
        // above the ~0.036 ETH oracle cap) can list. The real FWA owner makes the call.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        vm.deal(alice, 50 ether);
        vm.deal(bob, 50 ether);
    }

    /// @dev Un-exempt ShapePacks and set a fresh high oracle ask so the 6-unit backing still lists;
    ///      the oracle cap only bites the regimes that exercise it (kick, repoint, gas spike).
    function _useOracle(uint256 ask) internal {
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), false);
        _setPackAsk(ask);
    }

    /// @dev The mainnet deployment values, read from deploy/mainnet.json (the file
    ///      script/deploy.sh broadcasts), so every regime runs the configuration that ships.
    function _values() internal view returns (VaultLib.Params memory p) {
        string memory v = vm.readFile("deploy/mainnet.json");
        p.minEdgeBps = uint16(vm.parseJsonUint(v, ".minEdgeBps"));
        p.bufferBps = uint16(vm.parseJsonUint(v, ".bufferBps"));
        p.distributionBps = uint16(vm.parseJsonUint(v, ".distributionBps"));
        p.payMarkupBps = uint16(vm.parseJsonUint(v, ".payMarkupBps"));
        p.keeperShareBps = uint16(vm.parseJsonUint(v, ".keeperShareBps"));
        p.allocatedBoundBps = uint16(vm.parseJsonUint(v, ".allocatedBoundBps"));
        p.packUnitsMask = uint64(vm.parseJsonUint(v, ".packUnitsMask"));
        p.gasCeiling = uint64(vm.parseJsonUint(v, ".gasCeilingWei"));
        p.essentialCeiling = uint64(vm.parseJsonUint(v, ".essentialCeilingWei"));
        p.maxTip = uint64(vm.parseJsonUint(v, ".maxTipWei"));
        p.workFee = uint64(vm.parseJsonUint(v, ".workFeeWei"));
        p.reserve = uint128(vm.parseJsonUint(v, ".reserveWei"));
        p.tvlCap = uint128(vm.parseJsonUint(v, ".tvlCapWei"));
        p.routineCap = uint64(vm.parseJsonUint(v, ".routineCapWei"));
        p.routineRate = uint64(vm.parseJsonUint(v, ".routineRatePerDayWei"));
        p.essentialCap = uint64(vm.parseJsonUint(v, ".essentialCapWei"));
        p.essentialRate = uint64(vm.parseJsonUint(v, ".essentialRatePerDayWei"));
        p.keepAdvantage = uint64(vm.parseJsonUint(v, ".keepAdvantageWei"));
        p.purchaserGasPrice = uint64(vm.parseJsonUint(v, ".purchaserGasPriceWei"));
        p.purchaserRedeemPack = uint64(vm.parseJsonUint(v, ".purchaserRedeemPackGas"));
        p.purchaserRedeemShape = uint64(vm.parseJsonUint(v, ".purchaserRedeemShapeGas"));
        p.minDeposit = uint64(vm.parseJsonUint(v, ".minDepositWei"));
        p.minDistribution = uint64(vm.parseJsonUint(v, ".minDistributionWei"));
    }

    function _deploy(uint256 seed, VaultLib.Params memory p) internal {
        vm.fee(BASE_FEE);
        vm.txGasPrice(GAS_PRICE);
        vm.deal(address(this), seed + 1 ether);
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, seed);
        preexisting = address(vault).balance - seed; // mainnet dust at the deploy address
        depositedCum = address(vault).balance; // seed and dust are capitalization inflow
    }

    /// @dev Baselines after an inherited _select deploy (3 ETH seed, one six-unit vault listing among
    ///      30 real listings). The vault's own pack mints 2 Shapes (0.05 + 0.01) at 0.002 ETH fee.
    function _afterSelect() internal {
        vm.deal(alice, 1 ether);
        depositedCum = deployBalance;
        keeperPaidCum = selectPay; // the build in _select paid this contract
        mintFeesCum = COUNT * 2 * SHAPES.mintFee();
        mintedValueCum = COUNT * UNITS * UNIT;
        backingPostedCum = COUNT * B;
    }

    function _facts(string memory key, uint256 value) internal pure returns (Fact[] memory f) {
        f = new Fact[](6);
        f[0] = Fact(key, value);
        f[1] = Fact("_1", 0);
        f[2] = Fact("_2", 0);
        f[3] = Fact("_3", 0);
        f[4] = Fact("_4", 0);
        f[5] = Fact("_5", 0);
    }

    function _one(uint256 id) internal pure returns (uint256[] memory a) {
        a = new uint256[](1);
        a[0] = id;
    }

    function _idsOf(uint256) internal view returns (uint256[] memory) {
        return TestVaultOps.open(vault);
    }

    // ---- measured vault-call wrappers (accumulate keeper pay and realized fee income)

    /// @dev Build-and-list `count` packs of `units`. Build mints `n` Shapes per pack (0.001 ETH fee
    ///      each), mints `units x 0.01` of redeemable pack value, and posts each pack's backing to FWA.
    function _kRestock(address who, uint256 count, uint256 units) internal {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        TestVaultOps.restock(vault, count, units, 0);
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        (, uint256 n) = VaultLib.makeup(units);
        uint256 fees = count * n * SHAPES.mintFee();
        mintFeesCum += fees;
        mintedValueCum += count * units * UNIT;
        // The vault spends: backing (to FWA) + pack value + mint fees + keeper pay.
        backingPostedCum += (vb - address(vault).balance) - pay - count * units * UNIT - fees;
        _guard();
    }

    /// @dev _kRestock that returns false instead of reverting when the vault refuses the batch.
    function _kTryRestock(address who, uint256 count, uint256 units) internal returns (bool) {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        uint256[] memory proposed = TestVaultOps.proposals(vault, count, units);
        vm.prank(who);
        try vault.build(units, proposed, 0) {}
        catch {
            return false;
        }
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        (, uint256 n) = VaultLib.makeup(units);
        uint256 fees = count * n * SHAPES.mintFee();
        mintFeesCum += fees;
        mintedValueCum += count * units * UNIT;
        backingPostedCum += (vb - address(vault).balance) - pay - count * units * UNIT - fees;
        _guard();
        return true;
    }

    function _kList(address who, uint256 n) internal returns (uint256 listed) {
        uint256 open = TestVaultOps.open(vault).length;
        uint256 vaultBefore = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        TestVaultOps.list(vault, n, 0);
        keeperPaidCum += who.balance - b;
        listed = TestVaultOps.open(vault).length - open;
        backingPostedCum += vaultBefore - address(vault).balance - (who.balance - b);
        _guard();
    }

    function _kSync(address who, uint256[] memory ids) internal {
        uint256 b = who.balance;
        uint256 credit = FWA.feeCredit(address(vault));
        vm.prank(who);
        TestVaultOps.sync(vault, ids, 0);
        keeperPaidCum += who.balance - b;
        // A sync sweeps the fee credit into the balance when that pays: harvested fee income.
        feeHarvestedCum += credit - FWA.feeCredit(address(vault));
        _guard();
    }

    function _kUnlist(address who, uint256[] memory ids) internal {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        TestVaultOps.unlist(vault, ids, 0);
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        backingReturnedCum += (address(vault).balance - vb) + pay; // backing freed into the balance
        _guard();
    }

    function _kLiquidate(address who, uint256 maxCount) internal {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        vault.liquidate(maxCount, 0);
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        redeemedCum += (address(vault).balance - vb) + pay; // redeemed value into the balance
        _guard();
    }

    function _kHarvest(address who, uint256[] memory ids) internal {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        try vault.harvest(ids, 0) {} catch {}
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        feeHarvestedCum += (address(vault).balance + pay) - vb; // fees in, less keeper pay out
        _guard();
    }

    function _kCheckpoint(address who) internal {
        uint256 vb = address(vault).balance;
        uint256 b = who.balance;
        vm.prank(who);
        TestVaultOps.checkpoint(vault, 0);
        uint256 pay = who.balance - b;
        keeperPaidCum += pay;
        feeHarvestedCum += (address(vault).balance + pay) - vb; // checkpoint harvests credited fees
        _guard();
    }

    /// @dev O5 (D32): what the vault may spend never reaches what it owes. Checked after every
    ///      keeper call: balance >= liabilities, and idle ETH is zero or idle ETH + liabilities + the
    ///      owed estimate for unpriced redemptions + the reserve fit inside the balance.
    function _guard() internal {
        uint256 liab = vault.pendingDepositTotal() + vault.redemptionReserve() + vault.distributionReserve()
            + vault.claimableTotal();
        uint256 bal = address(vault).balance;
        assertGe(bal, liab, "balance below liabilities");
        // While redeemers are short of ETH (owed + reserve > free) nothing is spendable at all.
        uint256 idle = vault.idleEth();
        if (idle != 0) assertLe(idle + liab + _owed() + vault.getParams().reserve, bal, "spendable reaches owed ETH");
        ++guardChecks;
    }

    function _deposit(address who, uint256 amt) internal {
        {
            uint256 gross_ = Charges.grossFor(vault, amt);
            vm.prank(who);
            vault.deposit{value: gross_}();
            depositedCum += gross_; // inflow is all ETH sent: escrow + checkpoint charge + deployment charge
        }
    }

    function _claim(address who) internal {
        uint256 b = who.balance;
        vm.prank(who);
        try vault.claim() {} catch {}
        claimsCum += who.balance - b;
    }

    function _setPackAsk(uint256 ask) internal {
        address oracle = FWA.floorOracle();
        vm.prank(IOwnable(oracle).owner());
        IOracleAdmin(oracle).setFloor(address(PACKS), ask);
    }

    function _toBlackout() internal {
        uint256 t = block.timestamp;
        uint256 start = t - t % INTERVAL + BLACKOUT;
        if (t >= start) start += INTERVAL;
        vm.warp(start + 60);
        vm.roll(block.number + (start + 60 - t) / 12);
    }

    function _toOpen() internal {
        uint256 t = block.timestamp;
        uint256 next = t - t % INTERVAL + INTERVAL + 60;
        vm.warp(next);
        vm.roll(block.number + (next - t) / 12);
    }

    /// @dev Drain FWA's acquisition queue (expire any real pending requests from the forked block),
    ///      as ForkReconcile does, so a staged relist can be activated.
    function _drainQueue() internal {
        vm.warp(block.timestamp + 25 hours);
        vm.roll(block.number + 7_500);
        if (FWA.unsettledAcquisitionCount() != 0) IFwaSettle(address(FWA)).processAcquisitions(50);
    }

    function _feesHeld() internal view returns (uint256 sum) {
        uint256[] memory open = TestVaultOps.open(vault);
        for (uint256 i; i < open.length; ++i) {
            sum += FWA.pendingFees(open[i]);
        }
        sum += FWA.feeCredit(address(vault));
    }

    function _owed() internal view returns (uint256) {
        uint256 locked = vault.lockedShares();
        uint256 ts = vault.totalShares();
        if (locked == 0 || ts == 0) return 0;
        uint256 n = vault.lastNav();
        return (locked * n + ts - 1) / ts; // mulDivUp mirror of _owedEstimate
    }

    // ------------------------------------------------------------------ kit overrides

    function flowDir() internal pure override returns (string memory) {
        return "docs/receipts/flow";
    }

    function flowInflows() internal view override returns (Item[] memory i) {
        i = new Item[](3);
        i[0] = Item("holder deposits and deploy seed", depositedCum);
        i[1] = Item("FWA acquisition fees earned", feeHarvestedCum + _feesHeld());
        i[2] = Item("forced ETH (donations)", forcedCum);
    }

    function flowOutflows() internal view override returns (Item[] memory o) {
        o = new Item[](7);
        o[0] = Item("paid to keepers (gas + premium)", keeperPaidCum);
        o[1] = Item("Shapes mint fees", mintFeesCum);
        o[2] = Item("backing to purchaser and FWA on a bid", bidBackingOutCum);
        o[3] = Item("FWA settlement fee (keep/silent)", settlementCutCum);
        o[4] = Item("pack value delivered to purchasers", packToPurchaserCum);
        o[5] = Item("redemptions and distributions claimed", claimsCum);
        o[6] = Item("deposits cancelled", cancelsCum);
    }

    function flowBuckets() internal view override returns (Bucket[] memory k) {
        k = new Bucket[](10);
        uint256 pending = vault.pendingDepositTotal();
        uint256 redeem = vault.redemptionReserve();
        uint256 dist = vault.distributionReserve();
        uint256 claimable = vault.claimableTotal();
        uint256 bal = address(vault).balance;
        uint256 pool = vault.processingPool();
        uint256 liabilities = pending + redeem + dist + claimable + pool;
        uint256 free = bal > liabilities ? bal - liabilities : 0;
        VaultLib.Params memory p = vault.getParams();
        uint256 reserveNeed = uint256(p.reserve) + _owed();

        (uint256 backingHeld, uint256 backingImplied, uint256 packHeld) = _fwaHoldings();
        uint256 inv; // no loose Shapes in the direct-mint recipe
        uint256[] memory idle = TestVaultOps.idle(vault);
        for (uint256 j; j < idle.length; ++j) {
            inv += PACKS.valueOf(idle[j]);
        }

        // Liabilities: whole amount is owed, so each states its own need (above-need is zero).
        k[0] = Bucket("depositor escrow (pending deposits)", pending, false, 0, true, pending);
        k[1] = Bucket("redemption reserve", redeem, false, 0, true, redeem);
        k[2] = Bucket("distribution reserve", dist, false, 0, true, dist);
        k[3] = Bucket("claimable to holders (settled, unpaid)", claimable, false, 0, true, claimable);
        k[4] = Bucket("vault free ETH (reserve + idle)", free, false, 0, true, reserveNeed);
        k[5] = Bucket("backing held by FWA (active listings)", backingHeld, true, backingImplied, false, 0);
        k[6] = Bucket("pack value in FWA custody (listed)", packHeld, false, 0, false, 0);
        k[7] = Bucket("inventory held by vault (idle packs)", inv, false, 0, false, 0);
        k[8] = Bucket("FWA fees uncollected (pending + credit)", _feesHeld(), false, 0, false, 0);
        // Request charges held to pay the next checkpoint's keeper (D56); the remainder joins free ETH.
        k[9] = Bucket("request charges held for the next checkpoint", pool, false, 0, true, pool);
    }

    /// @dev Reads FWA's own listing records, not just vault counters. held/packHeld count only
    ///      listings FWA still escrows (active, staged or allocated); implied is the vault's
    ///      Position.backing sum across all open listings. A gap would be a resolved-but-unsynced
    ///      transient; every regime syncs before reporting, so held == implied at the snapshot.
    function _fwaHoldings() internal view returns (uint256 held, uint256 implied, uint256 packHeld) {
        uint256[] memory open = TestVaultOps.open(vault);
        for (uint256 i; i < open.length; ++i) {
            (,, uint128 backing) = TestVaultOps.position(vault, open[i]);
            implied += backing;
            (,,,,, uint256 value,,,,, uint8 status) = FWA.listings(open[i]);
            if (status == LISTING_ACTIVE || status == LISTING_STAGED || status == LISTING_ALLOCATED) {
                held += value;
                (, uint64 units,) = TestVaultOps.position(vault, open[i]);
                packHeld += uint256(units) * UNIT;
            }
        }
    }

    function flowFlows() internal view override returns (Flow[] memory f) {
        f = new Flow[](5);
        f[0] = Flow("holders -> vault: deposits | claimed back", depositedCum, true, claimsCum);
        f[1] = Flow("vault -> FWA: backing posted | returned (kick/keep/silent/unlist)", backingPostedCum, true, backingReturnedCum);
        f[2] = Flow("vault -> Shapes/Packs: value minted | redeemed (liquidate)", mintedValueCum, true, redeemedCum);
        f[3] = Flow("vault -> keepers: pay | fees harvested back", keeperPaidCum, true, feeHarvestedCum);
        f[4] = Flow("FWA token rewards: claimed | burned (token units, zero ETH)", tokensClaimedCum, true, tokensBurnedCum);
    }

    function flowTolerance() internal pure override returns (uint256) {
        return 0;
    }
}

contract VaultFlowPinnedTest is VaultFlowBase {
    // ------------------------------------------------------------------ pinned-block regimes

    /// @dev Initial capitalization: deploy at the mainnet seed, then the first deposit priced into
    ///      shares. Shows the seed and the first holder's capital resting as free vault ETH.
    function test_flow_init() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        Fact[] memory f = _facts("open_listings", 0);
        f[1] = Fact("holder_shares_minted", vault.shareBalance(alice));
        flowReport("init", a, f);
    }

    /// @dev Maximum load: deposit to the 2 ETH cap and build and list as many packs as the capital
    ///      allows, in batches of up to 10 as keeper/policy.py does (largest batch the capital check
    ///      accepts). O2 reports quoted gas per position, removing both verified work fees from pay. GAP: a real high-volume settlement burst needs several real VRF
    ///      selections in one fork; only two historical fixtures exist, so this shows the maximum
    ///      standing load instead (see report).
    function test_flow_max_load() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1.98 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        uint256 listed;
        uint256 built;
        uint256 pay0 = keeperPaidCum;
        (uint256 routineBefore,) = vault.budget();
        // Build mints and lists at once; the batch is capped at MAX_LIST_BATCH (8), so counts above
        // it are refused and the loop steps down. Each admitted pack is both built and listed.
        for (uint256 c = 10; c != 0;) {
            if (_kTryRestock(keeper, c, 6)) { built += c; listed += c; }
            else --c;
        }
        // Fixed quote price: min(0.2 gwei bid, basefee 0.15 + maxTip 0.05, ceiling 0.5), no markup (V1).
        // Both completed construction and listing earn their stated work units.
        assertLt(keeperPaidCum - pay0, routineBefore, "payment is not clipped by the starting budget");
        (uint256 routineAfter,) = vault.budget();
        assertEq(routineBefore - routineAfter, keeperPaidCum - pay0, "no intervening refill or budget clipping");
        uint256 feePaid = (built + listed) * vault.getParams().workFee;
        assertGt(listed, 0, "max-load reaches real pack admission");
        assertEq(feePaid, listed * 0.00004 ether, "two unchanged work fees per admitted position");
        uint256 quotedGasPerPosition = (keeperPaidCum - pay0 - feePaid) / 0.2 gwei / listed;
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("packs_listed", listed);
        f[2] = Fact("keeper_gas_per_position", quotedGasPerPosition);
        f[3] = Fact("work_fee_per_position_wei", feePaid / listed);
        flowReport("max_load", a, f);
    }

    /// @dev Low volume / prolonged inactivity, short window. Identical inputs to inactive_long;
    ///      grouped for drift. No real acquisition happens at the pinned block, so listings sit
    ///      and ETH destinations do not move with time.
    function test_flow_inactive_short() public {
        _inactive("inactive_short", 2);
    }

    function test_flow_inactive_long() public {
        _inactive("inactive_long", 20);
    }

    function _inactive(string memory regime, uint256 intervals) internal {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 5, 6);
        _kList(keeper, 5);
        for (uint256 i; i < intervals; ++i) {
            vm.warp(block.timestamp + INTERVAL);
            vm.roll(block.number + INTERVAL / 12);
        }
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("idle_intervals", intervals);
        flowReport(regime, a, f);
    }

    /// @dev Gas spike after deployment: a position is listed at low gas (setup), then the basefee is
    ///      lifted to 2 gwei, four times the 0.5 gwei ceiling. No call is refused for gas price (D51):
    ///      a profitable build still runs, and both it and the checkpoint are paid at the ceiling
    ///      price, never the spiked basefee (D56). The spike never reaches holder ETH (O6 limit).
    function test_flow_gas_spike() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        // Setup at low gas, before the measured window.
        vm.fee(BASE_FEE);
        vm.txGasPrice(GAS_PRICE);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 3, 6);
        // The spike: 2 gwei, four times the ceiling.
        Snap memory a = flowBegin(2 gwei, 1.95 gwei, PINNED);
        uint256 paid0 = keeperPaidCum;
        assertTrue(_kTryRestock(keeper, 1, 6), "D51: a profitable build runs even at a 2 gwei spike");
        uint256 buildPay = keeperPaidCum - paid0;
        VaultLib.Params memory pp = vault.getParams();
        // Priced at the ceiling (min(basefee+tip, ceiling) = gasCeiling), not the 2 gwei basefee.
        assertEq(buildPay, (VaultLib.Q_BUILD + VaultLib.buildGas(2) + VaultLib.Q_LISTED) * pp.gasCeiling
            + 2 * pp.workFee, "build paid at the ceiling price, not the spike");
        _deposit(bob, 0.5 ether);
        _toBlackout();
        uint256 kb = keeper.balance;
        _kCheckpoint(keeper); // prices bob's deposit; keeper pay capped at the ceiling
        uint256 pay = keeper.balance - kb;
        assertGt(pay, 0, "checkpoint compensation is funded");
        assertLe(pay, 0.0002 ether, "O6 existing absolute holder expense limit");
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("gas_price_gwei_x100", 200);
        f[2] = Fact("checkpoint_pay_wei", pay);
        f[3] = Fact("build_pay_wei", buildPay);
        flowReport("gas_spike", a, f);
    }

    /// @dev Oracle owner lowers the pack ask below the posted backing, so FWA's owner can kick the
    ///      listing and the full backing returns to the vault. Then the floor oracle is repointed to
    ///      a contract with no such function: edge() yields no cap and nothing new lists, but
    ///      unlisting/redemption still work (D34). Positions are synced before the snapshot.
    function test_flow_oracle_change() public {
        _forkPinned();
        _useOracle(0.1 ether); // real oracle active (cap 0.11 > the 6-unit backing): needed to kick
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 3, 6);
        uint256[] memory ids = _idsOf(_kList(keeper, 3));
        _setPackAsk(0.025 ether); // cap 0.0275 < the ~0.065 posted backing: FWA may kick
        _toBlackout();
        uint256 vb = address(vault).balance;
        IFwaAdmin(address(FWA)).kickListing(ids[0]);
        backingReturnedCum += address(vault).balance - vb; // full backing B returns on a kick
        _kSync(keeper, ids);
        // Repoint the oracle so no cap can be read; edge fails, nothing new lists.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setAddr(64, address(PACKS));
        (, uint256 backing, bool ok) = vault.edge(6);
        uint256 packsBack = TestVaultOps.idle(vault).length;
        assertGe(packsBack, 1, "kicked pack recovered to inventory");
        // With the oracle broken, alice redeems everything: the vault unlists the rest, liquidates
        // and pays her (D34).
        _toOpen();
        uint256 aShares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        _kUnlist(keeper, TestVaultOps.open(vault));
        _kLiquidate(keeper, 40);
        _toBlackout();
        _kCheckpoint(keeper);
        uint256 c0 = claimsCum;
        _claim(alice);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("edge_ok_after_repoint", ok ? 1 : 0);
        f[2] = Fact("cap_after_repoint_wei", backing);
        f[3] = Fact("packs_back_in_inventory", packsBack);
        f[4] = Fact("redemption_paid_after_repoint_wei", claimsCum - c0);
        flowReport("oracle_change", a, f);
    }

    /// @dev Failed or delayed keeper execution: keepers never harvest and an idle checkpoint is
    ///      refused, so fees sit uncollected at FWA and no interval slot is wasted. ETH stays safe
    ///      and recoverable; the backing counter still matches real FWA holdings (held == implied).
    function test_flow_keeper_delay() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 4, 6);
        _kList(keeper, 4);
        // No keeper acts for a long time. A no-flow checkpoint is refused (LOW-1 repair).
        vm.warp(block.timestamp + INTERVAL);
        _toBlackout();
        uint256 planned20 = TestVaultOps.witness(vault);
        vm.prank(keeper);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.checkpoint(planned20, 0);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("idle_checkpoint_refused", 1);
        f[2] = Fact("fees_uncollected_wei", _feesHeld());
        flowReport("keeper_delay", a, f);
    }

    /// @dev Partial and simultaneous withdrawals: two holders redeem; the first checkpoint fills
    ///      pro rata from free ETH, the backing is unwound, the next checkpoint fills the rest.
    function test_flow_withdrawals() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _deposit(bob, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 10, 6);
        uint256[] memory ids = _idsOf(_kList(keeper, 10));
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        {
            uint256 rc_ = Charges.redeemCharge(vault, bShares / 2);
            vm.prank(bob);
            vault.requestRedeem{value: rc_}(bShares / 2);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        _toBlackout();
        _kCheckpoint(keeper); // partial fill from free ETH
        uint256 lockedAfterFirst = vault.lockedShares();
        _kUnlist(keeper, ids);
        _kLiquidate(keeper, 40);
        _toOpen();
        _toBlackout();
        _kCheckpoint(keeper); // fills the rest
        _claim(alice);
        _claim(bob);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("locked_shares_after_first_checkpoint", lockedAfterFirst);
        f[2] = Fact("locked_shares_at_end", vault.lockedShares());
        flowReport("withdrawals", a, f);
    }

    /// @dev Settled-but-unclaimed ETH is a liability, never deployable (D32). Alice is filled in
    ///      full, her entitlement settles to claimable on an unrelated touch, and keepers can still
    ///      only deploy bob's capital and the seed.
    function test_flow_settled_unclaimed() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _deposit(bob, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        uint256 aShares = vault.shareBalance(alice);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        _toBlackout();
        _kCheckpoint(keeper); // fills alice in full from free ETH
        _toOpen();
        _deposit(alice, 0.01 ether); // touch: her entitlement settles to claimableEth
        uint256 liabilities = vault.pendingDepositTotal() + vault.redemptionReserve()
            + vault.distributionReserve() + vault.claimableTotal();
        // Only bob's ~1 ETH is deployable (alice's filled redemption is a liability); five six-unit
        // packs (~0.65 ETH) fit, more would exceed it.
        _kRestock(keeper, 5, 6);
        _kList(keeper, 5);
        // Checked before the claim, while the entitlement is still a liability: idle ETH excludes
        // it, and the vault balance never falls below its liabilities.
        uint256 spendable = vault.idleEth();
        assertGt(vault.claimableTotal(), 0, "alice's entitlement settled to claimable (state reached)");
        // The gap is the margin by which spendable ETH stays under the unowed balance: never negative.
        uint256 unowed = address(vault).balance - liabilities;
        _claim(alice);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("spendable_over_unowed_wei", spendable > unowed ? spendable - unowed : 0);
        f[2] = Fact("liabilities_wei", liabilities);
        f[3] = Fact("guard_checks", guardChecks);
        flowReport("settled_unclaimed", a, f);
    }

    /// @dev Distributions on (stated variation: distributionBps 2000; mainnet ships 0). A 1 ETH
    ///      forced gain above the high-water mark is distributed to live shares and claimed.
    function test_flow_distributions() public {
        _forkPinned();
        VaultLib.Params memory p = _values();
        p.distributionBps = 2_000;
        _deploy(0.01 ether, p);
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        new ForceSender{value: 1 ether}(payable(address(vault)));
        forcedCum += 1 ether;
        _toBlackout();
        _kCheckpoint(keeper); // distributes 20% of the gain above the high-water mark
        uint256 distributed = vault.distributionReserve();
        _claim(alice);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("distributed_wei", distributed);
        f[2] = Fact("distribution_bps", 2_000);
        flowReport("distributions", a, f);
    }

    /// @dev Complete wind-down and final claims: all positions unlisted, inventory liquidated, both
    ///      holders redeem in full. Only the dead-share seed slice remains in the vault.
    function test_flow_wind_down() public {
        _forkPinned();
        _deploy(0.01 ether, _values());
        Snap memory a = flowBegin(GAS_PRICE, BASE_FEE, PINNED);
        _deposit(alice, 1 ether);
        _deposit(bob, 0.5 ether);
        _toBlackout();
        _kCheckpoint(keeper);
        _toOpen();
        _kRestock(keeper, 8, 6);
        uint256[] memory ids = _idsOf(_kList(keeper, 8));
        vm.prank(owner);
        vault.startWindDown();
        _kUnlist(keeper, ids);
        uint256 aShares = vault.shareBalance(alice);
        uint256 bShares = vault.shareBalance(bob);
        {
            uint256 rc_ = Charges.redeemCharge(vault, aShares);
            vm.prank(alice);
            vault.requestRedeem{value: rc_}(aShares);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        {
            uint256 rc_ = Charges.redeemCharge(vault, bShares);
            vm.prank(bob);
            vault.requestRedeem{value: rc_}(bShares);
            depositedCum += rc_; // the request charge is holder ETH entering the vault
        }
        _kLiquidate(keeper, 40);
        _toBlackout();
        // Independent expectation: with every position unlisted and liquidated, the vault's whole
        // value is its ETH less the request-charge pool. The checkpoint prices redemptions first and
        // pays its keeper (from the pool) after, so each holder is owed that value x their shares /
        // all shares, the seed's dead shares included.
        uint256 total = vault.totalShares();
        uint256 kb = keeper.balance;
        uint256 pool = vault.processingPool(); // request charges: not holder value, excluded from NAV
        _kCheckpoint(keeper);
        uint256 nav = address(vault).balance + (keeper.balance - kb) - pool;
        uint256 expA = nav * aShares / total;
        uint256 expB = nav * bShares / total;
        uint256 c0 = claimsCum;
        _claim(alice);
        uint256 gotA = claimsCum - c0;
        _claim(bob);
        uint256 gotB = claimsCum - c0 - gotA;
        uint256 gap = (gotA > expA ? gotA - expA : expA - gotA) + (gotB > expB ? gotB - expB : expB - gotB);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("locked_shares_at_end", vault.lockedShares());
        f[2] = Fact("vault_eth_at_end_wei", address(vault).balance);
        f[3] = Fact("holder_claim_gap_wei", gap);
        f[4] = Fact("holder_loss_bps", (1.5 ether - (gotA + gotB)) * 10_000 / 1.5 ether);
        flowReport("wind_down", a, f);
    }

}

contract VaultFlowSelectionTest is VaultFlowBase {
    // ------------------------------------------------------------------ selection-fork regimes
    // The real VRF fixtures (SelectionBase) carry their own deploy: 3 ETH seed, gasCeiling 50 gwei,
    // One vault listing among 30 real listings. Resolution and harvest run at a realistic 0.45/0.4 gwei.

    /// @dev Bid outcome: the purchaser takes the bid; the vault keeps the pack and loses the
    ///      backing. The pack returns to inventory on sync, the fee share is harvested.
    function test_flow_acquire_bid() public {
        Candidate memory c = primary();
        _select(c);
        _afterSelect();
        Snap memory a = flowBegin(0.45 gwei, 0.4 gwei, c.requestBlock);
        _deposit(alice, 0.2 ether); // in-window holder inflow so inflow_base is positive
        (,, uint128 backing) = TestVaultOps.position(vault, selected);
        uint256 pb = c.purchaser.balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        assertEq(c.purchaser.balance - pb, backing * 9_000 / 10_000, "purchaser got 90% of backing");
        bidBackingOutCum += backing; // 0.9 to purchaser, 0.1 to FWA: the whole backing leaves
        _kSync(address(this), _one(selected)); // pack returns to inventory
        _kHarvest(address(this), TestVaultOps.open(vault));
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("outcome_bid", 1);
        f[2] = Fact("packs_back_in_inventory", TestVaultOps.idle(vault).length);
        flowReport("acquire_bid", a, f);
    }

    /// @dev Keep outcome: the purchaser keeps the pack; the vault gets the backing back less FWA's
    ///      settlement fee, and the pack value leaves to the purchaser.
    function test_flow_acquire_keep() public {
        Candidate memory c = primary();
        _select(c);
        _afterSelect();
        Snap memory a = flowBegin(0.45 gwei, 0.4 gwei, c.requestBlock);
        _deposit(alice, 0.2 ether);
        (, uint64 units, uint128 backing) = TestVaultOps.position(vault, selected);
        uint256 vb = address(vault).balance;
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).keepNFT(selected);
        uint256 reclaimed = address(vault).balance - vb;
        assertEq(reclaimed, uint256(backing) * 9_900 / 10_000, "backing back less the 1% settlement fee");
        backingReturnedCum += reclaimed;
        settlementCutCum += backing - reclaimed;
        packToPurchaserCum += uint256(units) * UNIT;
        _kSync(address(this), _one(selected));
        _kHarvest(address(this), TestVaultOps.open(vault));
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("outcome_keep", 1);
        f[2] = Fact("packs_held", TestVaultOps.idle(vault).length);
        flowReport("acquire_keep", a, f);
    }

    /// @dev Silent purchaser: past the settlement window the vault reclaims the better outcome
    ///      (backing, since B(1-s) > P), inside sync. The pack goes to the purchaser.
    function test_flow_acquire_silent() public {
        Candidate memory c = primary();
        _select(c);
        _afterSelect();
        Snap memory a = flowBegin(0.45 gwei, 0.4 gwei, c.requestBlock);
        _deposit(alice, 0.2 ether);
        vm.warp(block.timestamp + FWA.settlementWindow());
        (, uint64 units, uint128 backing) = TestVaultOps.position(vault, selected);
        uint256 vb = address(vault).balance;
        uint256 kb = address(this).balance;
        uint256 creditBefore = FWA.feeCredit(address(vault));
        vm.prank(address(this));
        TestVaultOps.sync(vault, _one(selected), 0);
        uint256 pay = address(this).balance - kb;
        keeperPaidCum += pay;
        // The sync also economically sweeps the selection fee credit into the balance; that is
        // harvested fee income, not returned backing, so it is reported separately.
        uint256 swept = creditBefore - FWA.feeCredit(address(vault));
        feeHarvestedCum += swept;
        uint256 reclaimed = (address(vault).balance - vb) + pay - swept;
        assertEq(reclaimed, uint256(backing) * (10_000 - FWA.ownerSettlementFeeBps()) / 10_000,
            "vault reclaimed backing on silence");
        backingReturnedCum += reclaimed;
        settlementCutCum += backing - reclaimed;
        packToPurchaserCum += uint256(units) * UNIT;
        _kHarvest(address(this), TestVaultOps.open(vault));
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("outcome_silent", 1);
        flowReport("acquire_silent", a, f);
    }

    /// @dev Busy FWA queue (D62, audit B): after a bid the vault refuses to relist while FWA's queue
    ///      is busy (a listing would be staged and earn nothing); once the queue drains the relist
    ///      goes in active. Regime name kept for the asset-flow config.
    function test_flow_staged_activation() public {
        Candidate memory c = primary();
        _select(c);
        _afterSelect();
        Snap memory a = flowBegin(0.45 gwei, 0.4 gwei, c.requestBlock);
        _pendForeignAcquisition(); // real pending request keeps FWA's queue busy for the relist refusal
        _deposit(alice, 0.2 ether);
        (,, uint128 backing) = TestVaultOps.position(vault, selected);
        vm.prank(c.purchaser);
        IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        bidBackingOutCum += backing;
        _kSync(address(this), _one(selected));
        _kHarvest(address(this), TestVaultOps.open(vault));
        assertGt(FWA.unsettledAcquisitionCount(), 0, "queue busy");
        uint256[] memory planned19 = TestVaultOps.proposals(vault, 1, 6);
        vm.expectRevert(PackVault.Nothing.selector);
        vault.list(planned19, 0);
        _drainQueue();
        uint256 relisted = _kList(address(this), 1);
        uint256[] memory open = TestVaultOps.open(vault);
        (,,,,,,,,,, uint8 st) = FWA.listings(open[open.length - 1]);
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("relist_refused_while_busy", 1);
        f[2] = Fact("relist_active_after_drain", st == LISTING_ACTIVE ? 1 : 0);
        f[3] = Fact("relisted_count", relisted);
        flowReport("staged_activation", a, f);
    }

    // ------------------------------------------------------------------ token-fork regime

    /// @dev FWA token lifecycle (D43): a real buyback routes tokens to live vault listings; anyone's
    ///      unpaid call claims and burns every token the vault holds. Supply falls by exactly the
    ///      claimed amount; no ETH moves for the burn. Tokens are reported in token units as a flow
    ///      and facts, never as an ETH bucket (worth zero to holders).
    function test_flow_tokens() public {
        string memory fx = vm.readFile("test/fixtures/buyback.json");
        vm.createSelectFork("mainnet", vm.parseJsonBytes32(fx, ".tx"));
        assertEq(FWA.unsettledAcquisitionCount(), 0);
        preexisting = 0;
        vm.fee(0.1 gwei);
        vm.txGasPrice(0.15 gwei);
        // D62 live state: ShapePacks is oracle-exempt so the 6-unit backing can list.
        vm.prank(IOwnable(address(FWA)).owner());
        IFwaAdmin(address(FWA)).setOracleExemptCollection(address(PACKS), true);
        IFWAToken token = IFWAToken(FWA.token());
        IFWARewards rewards = IFWARewards(FWA.rewards());

        VaultLib.Params memory p = _values();
        vm.deal(address(this), 6 ether);
        // Seed covers 20 six-unit packs (~0.13 ETH each to list).
        (vault,) = DeployCore.deploy(FWA, SHAPES, PACKS, owner, p, 3 ether);
        depositedCum = address(vault).balance;
        mintFeesCum = 20 * 2 * SHAPES.mintFee(); // 20 packs x 2 Shapes x 0.001 ETH
        mintedValueCum = 20 * 6 * UNIT;
        uint256 bthis = address(this).balance;
        TestVaultOps.restock(vault, 20, 6, 0);
        TestVaultOps.list(vault, 20, 0);
        keeperPaidCum = address(this).balance - bthis; // restock + list reimburse this contract
        backingPostedCum = 0;
        uint256[] memory posted = TestVaultOps.open(vault);
        for (uint256 i; i < posted.length; ++i) backingPostedCum += vault.position(posted[i]).backing;
        // Replay the real buyback as its original self-call (EIP-7702 delegated sender).
        address from = vm.parseJsonAddress(fx, ".from");
        bytes memory input = vm.parseJsonBytes(fx, ".input");
        vm.txGasPrice(vm.parseJsonUint(fx, ".gasPrice"));
        vm.prank(from, from);
        (bool ok,) = vm.parseJsonAddress(fx, ".to").call(input);
        assertTrue(ok, "real buyback replays");
        vm.txGasPrice(0.15 gwei);

        Snap memory a = flowBegin(0.15 gwei, 0.1 gwei, BUYBACK_block());
        vm.deal(alice, 1 ether);
        _deposit(alice, 0.1 ether); // in-window holder inflow so inflow_base is positive
        uint256[] memory ids = TestVaultOps.open(vault);
        uint256 pending = _pendingTokens(rewards, ids);
        tokensClaimedCum = pending;
        uint256 supply = token.totalSupply();
        address anyone = makeAddr("pack-vault-test-anyone");
        assertEq(anyone.code.length, 0); assertEq(anyone.balance, 0);
        vm.prank(anyone);
        TestVaultOps.burnTokens(vault, ids);
        tokensBurnedCum = supply - token.totalSupply();
        assertEq(tokensBurnedCum, pending, "burned exactly what was claimed");
        assertEq(anyone.balance, 0, "unpaid: no ETH to the caller");
        Fact[] memory f = _facts("open_listings", TestVaultOps.open(vault).length);
        f[1] = Fact("tokens_claimed_units", tokensClaimedCum);
        f[2] = Fact("tokens_burned_units", tokensBurnedCum);
        f[3] = Fact("burn_paid_any_eth", 0);
        flowReport("tokens", a, f);
    }

    function BUYBACK_block() internal pure returns (uint256) {
        return 26_423_454;
    }

    function _pendingTokens(IFWARewards rewards, uint256[] memory ids) internal view returns (uint256 sum) {
        for (uint256 i; i < ids.length; ++i) {
            sum += rewards.pendingDepositorTokens(ids[i]);
        }
    }

}
