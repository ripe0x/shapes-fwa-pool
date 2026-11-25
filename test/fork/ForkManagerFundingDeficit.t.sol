// SPDX-License-Identifier: MIT
pragma solidity 0.8.30;

import {MainRenewalBase, IFwaSettle, IShapesFeeAdmin} from "./ForkMainRenewal.t.sol";
import {PackManager} from "../../src/PackManager.sol";
import {VaultLib} from "../../src/VaultLib.sol";
import {StrategyLib} from "../../src/StrategyLib.sol";
import {ReconcileTrace} from "../utils/ReconcileTrace.sol";
import {Vm} from "forge-std/Vm.sol";

interface IFwaFundingSlots {
    function slotToListing(uint256 slot) external view returns (uint256);
}

/// @notice Real protocol fees and actual owner cash withdrawals. Quoted payments are not billed gas.
abstract contract ManagerFundingTraceBase is MainRenewalBase {
    uint256 internal keeperPaid;
    uint256 internal primaryFees;
    uint256 internal witness;
    uint256 internal accumulatorBefore;
    bytes32 private constant EARNINGS = keccak256("EarningsAccrued(address,uint256,uint256)");

    function output() internal pure virtual returns (string memory);
    function parameters() internal pure virtual override returns (VaultLib.Params memory p) {
        p=super.parameters();
        p.essentialCeiling=0.5 gwei; p.tvlCap=0;
        p.routineCap=0.03 ether; p.routineRate=0.01 ether;
        p.essentialCap=0.01 ether; p.essentialRate=0.005 ether;
    }
    function _initialFunding() internal pure virtual override returns (uint256) { return 3 ether; }

    function assertContext() external {
        assertEq(block.basefee,0.15 gwei,"executed base fee");
        assertEq(tx.gasprice,0.2 gwei,"executed gas price");
    }
    function _context() internal {
        vm.fee(0.15 gwei); vm.txGasPrice(0.2 gwei); this.assertContext();
    }
    function _beforeInitialBuild() internal override {
        if(vm.exists(output()))vm.removeFile(output());
        _context();
        _trace("setup","create",0,string.concat('{"fundingWei":',vm.toString(_initialFunding()),'}'));
    }
    function _afterInitialBuild(uint256 paid) internal override {
        keeperPaid+=paid; primaryFees+=3*SHAPES.mintFee();
        uint256 id=account.openListingAt(account.openListingCount()-1);
        VaultLib.Position memory p=account.position(id);
        _trace("built","build",paid,string.concat('{"units":3,"id":',vm.toString(id),
            ',"packId":',vm.toString(p.packId),',"backing":',vm.toString(p.backing),'}'));
    }
    function _beforeRequest() internal override {
        for(uint256 slot;slot<32;++slot){
            uint256 id=IFwaFundingSlots(address(FWA)).slotToListing(slot);
            if(id!=0 && FWA.pendingFees(id)!=0){witness=id;break;}
        }
        assertGt(witness,0,"actual public fee accumulator witness");
        accumulatorBefore=_accumulator();
        _trace("beforeRequest","request",0,string.concat('{"accBefore":',vm.toString(accumulatorBefore),
            ',"acquisitionFee":',vm.toString(FWA.acquisitionFee()),',"activeCount":',vm.toString(FWA.activeListingCount()),'}'));
        vm.recordLogs();
    }
    function _accumulator() internal view returns(uint256){
        (,,,,,,,uint256 debt,,,uint8 status)=FWA.listings(witness);
        uint256 pending=FWA.pendingFees(witness);
        assertEq(status,1); assertGt(pending,0);
        return debt+pending;
    }
    function _acquisition() internal {
        Vm.Log[] memory logs=vm.getRecordedLogs();
        uint256 earned;
        string memory records="[";
        uint256 count;
        for(uint256 i;i<logs.length;++i){
            if(logs[i].emitter==address(FWA) && logs[i].topics.length==3 && logs[i].topics[0]==EARNINGS
                && address(uint160(uint256(logs[i].topics[1])))==address(account)) {
                uint256 amount=abi.decode(logs[i].data,(uint256));
                uint256 id=uint256(logs[i].topics[2]);
                (,,,,,,,,,uint64 allocatedAt,)=FWA.listings(id);
                if(count++!=0)records=string.concat(records,",");
                records=string.concat(records,'{"id":',vm.toString(id),',"amount":',vm.toString(amount),
                    ',"allocatedAt":',vm.toString(allocatedAt),'}');
                earned+=amount;
            }
        }
        records=string.concat(records,"]");
        assertGt(earned,0,"real requests accrue actual manager income");
        _context();
        _trace("acquired","acquisition",0,string.concat('{"accBefore":',vm.toString(accumulatorBefore),
            ',"accAfter":',vm.toString(_accumulator()),',"earningsAccrued":',vm.toString(earned),
            ',"earnedRecords":',records,'}'));
    }
    function _save(VaultLib.Params memory p) internal {
        bytes32 expected=account.configurationHash();
        vm.prank(accountOwner);account.setParams(p,expected);
        _trace("configured","setParams",0,"{}");
    }
    function _withdrawTo(uint256 cash) internal {
        uint256 amount=address(account).balance-cash;
        uint256 ownerBefore=accountOwner.balance;
        vm.prank(accountOwner);PackManager(payable(address(account))).withdraw(accountOwner,amount);
        assertEq(accountOwner.balance-ownerBefore,amount,"actual owner receipt");
        _trace("ownerWithdrawal","withdraw",0,string.concat('{"amount":',vm.toString(amount),'}'));
    }
    function _trace(string memory step,string memory action,uint256 pay,string memory input) internal {
        string memory pending="[";
        for(uint256 i;i<account.openListingCount();++i){
            if(i!=0)pending=string.concat(pending,",");
            uint256 id=account.openListingAt(i);
            pending=string.concat(pending,'{"id":',vm.toString(id),',"fees":',vm.toString(FWA.pendingFees(id)),'}');
        }
        pending=string.concat(pending,"]");
        string memory line=string.concat('{"step":"',step,'","action":"',action,'","account":"',vm.toString(address(account)),
            '","owner":"',vm.toString(accountOwner),'","keeper":"',vm.toString(address(this)),'","block":',vm.toString(block.number),
            ',"timestamp":',vm.toString(block.timestamp),',"baseFee":',vm.toString(block.basefee),',"gasPrice":',vm.toString(tx.gasprice));
        line=string.concat(line,',"params":"',vm.toString(abi.encode(account.getParams())),'","mintFee":',vm.toString(SHAPES.mintFee()),
            ',"keeperCash":',vm.toString(account.keeperCash()),',"renewalCash":',vm.toString(account.renewalCash()),
            ',"keeperDeficit":',vm.toString(account.fundingDeficit(false)),',"renewalDeficit":',vm.toString(account.fundingDeficit(true)),
            ',"keeperPayCumulativeWei":',vm.toString(keeperPaid),',"creatorFeesCumulativeWei":',vm.toString(primaryFees));
        line=string.concat(line,',"feeCandidates":',pending,',"input":',input,
            ',"state":',ReconcileTrace.renderStrategy(account,pay,primaryFees,step),'}');
        vm.writeLine(output(),line);
    }
    function _bookHash() internal view returns(bytes32){
        return keccak256(bytes(ReconcileTrace.renderStrategy(account,0,0,"atomic")));
    }
}

contract ForkManagerHalfEthFundingTest is ManagerFundingTraceBase {
    function output() internal pure override returns(string memory){return "sim/out/manager-half-eth-float-wait-trace.jsonl";}
    function _initialFunding() internal pure override returns(uint256){return 0.5 ether;}

    function test_halfEthPaidFreshRenewalLeavesRealFloatDeficitAndCreditDoesNotSupplyPay() public {
        _select(false);_acquisition();
        uint256 paid=account.sync(new uint256[](0),0,1,account.configurationHash());
        keeperPaid+=paid; assertGt(paid,0);
        _trace("allocationApplied","sync",paid,"{\"ids\":[]}");
        vm.prank(selectedPurchaser);IFwaSettle(address(FWA)).acceptDepositorBid(selected);
        _trace("bid","bid",0,string.concat('{"id":',vm.toString(selected),'}'));
        vm.prank(accountOwner);account.recover(one(selected),0);
        _trace("returned","recover",0,string.concat('{"callerFunded":true,"ids":[',vm.toString(selected),']}'));
        _drainOtherRequest();
        _trace("queueDrained","processAcquisitions",0,"{\"callerFunded\":true,\"bound\":32}");
        uint256 beforeCash=address(account).balance;
        uint256 beforeFees=IShapesFeeAdmin(address(SHAPES)).pendingFees();
        uint256 quote=account.renewalQuote(packId,0,false);
        paid=account.renew(one(packId),backing(),new uint256[](0),quote,account.configurationHash());
        keeperPaid+=paid;primaryFees+=IShapesFeeAdmin(address(SHAPES)).pendingFees()-beforeFees;
        assertEq(paid,quote);
        assertEq(beforeCash-address(account).balance,0.213 ether+paid,"actual returned principal funds new principal");
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees()-beforeFees,0.003 ether);
        assertLt(address(account).balance,account.renewalFloat());
        assertEq(account.keeperCash(),0);
        assertEq(account.fundingDeficit(false),account.renewalFloat()-address(account).balance);
        (uint256 routine,)=account.budget(); assertGt(routine,0,"cash wait is not exhausted permission");
        uint256 credit=FWA.feeCredit(address(account));
        assertGt(credit,0); assertLt(credit,account.fundingDeficit(false),"accrued NAV cannot refill the missing float");
        _trace("paidRenewalCashWait","renew",paid,string.concat('{"returnedPack":',vm.toString(packId),',"backing":210000000000000000}'));
        // Admission rebased the only position's journal. Another authenticated selection is not
        // invented: no new work earns pay, even when the caller supplies a positive minimum.
        bytes32 beforeBook=_bookHash(); bytes32 expected=account.configurationHash();
        vm.expectRevert(VaultLib.Nothing.selector);
        account.sync(new uint256[](0),0,1,expected);
        assertEq(_bookHash(),beforeBook);assertEq(FWA.feeCredit(address(account)),credit);
        _trace("noNewPaidWork","declined",0,"{\"minimumPay\":1,\"reason\":\"Nothing; no second acquisition fixture\"}");
    }
}

abstract contract ManagerFiveProofFundingBase is ManagerFundingTraceBase {
    function _additionalBuild(uint256 i) internal pure override returns(bool){return i<6;}
    // Reconstructs slot1846 under five recorded words while respecting backing-offset admission.
    function _initialBacking(uint256 i) internal pure override returns(uint256[] memory){return one(0.21 ether+(i<6?i:7)*10000);}
    function _fillerFunding() internal pure override returns(uint256){return 20 ether;}
    function _fulfillmentCount() internal pure override returns(uint256){return 5;}
    function _prepare() internal returns(uint256 terminal,uint256[] memory fees){
        _selectCandidate(false,ReplayCandidate(26_272_979,
            0x1adee9be0b88eb3ca2176e0b19ec408bd34907df93a34122c86212902942fe88,
            72,42,1846,address(bytes20(hex"184b487d36aea8aa5990569c326c269de246179a"))));
        _acquisition();
        vm.prank(accountOwner);account.recover(new uint256[](0),0);
        _trace("ownerJournalPreparation","recover",0,"{\"callerFunded\":true,\"ids\":[]}");
        (,,terminal,,)=account.allocationState();assertGt(terminal,0);
        (,,address purchaser,,,,,,,,uint8 state)=FWA.listings(terminal);assertEq(state,2);
        vm.prank(purchaser);IFwaSettle(address(FWA)).acceptDepositorBid(terminal);
        _trace("terminalBid","bid",0,string.concat('{"id":',vm.toString(terminal),'}'));
        fees=new uint256[](account.openListingCount());uint256 count;
        for(uint256 i;i<account.openListingCount();++i){
            uint256 id=account.openListingAt(i);(,,,,,,,,,,uint8 status)=FWA.listings(id);
            if(status==1 && FWA.pendingFees(id)>0)fees[count++]=id;
        }
        assembly("memory-safe"){mstore(fees,count)}
        assertGe(count,2,"actual proofs leave two genuine active fee sources");
    }
}

contract ForkManagerSyncFundingDeficitTest is ManagerFiveProofFundingBase {
    function output() internal pure override returns(string memory){return "sim/out/manager-sync-funding-deficit-trace.jsonl";}
    function test_syncRefillsActualFloatGapBeforeSelectingSmallestPaidFeePrefix() public {
        (uint256 terminal,uint256[] memory fees)=_prepare();
        uint256 credit=FWA.feeCredit(address(account));assertGt(credit,0);
        uint256 beforeCash=address(account).balance;
        vm.prank(accountOwner);account.harvest(new uint256[](0),0);
        assertEq(address(account).balance-beforeCash,credit);
        assertEq(FWA.feeCredit(address(account)),0);
        _trace("ownerCollectedCredit","harvest",0,string.concat('{"callerFunded":true,"credit":',vm.toString(credit),'}'));
        // Deliberately cheap owner calibration isolates the cash boundary with actual modest
        // archived fees. It is not a production gas schedule or a keeper profitability claim.
        VaultLib.Params memory p=account.getParams();
        p.workFee=1;p.gasSchedule.sync=1;p.gasSchedule.synced=1;p.gasSchedule.pruned=1;
        p.gasSchedule.fund=1;p.gasSchedule.harvested=1;p.gasSchedule.credit=1;
        _save(p);_context();
        uint256 first=FWA.pendingFees(fees[0]);uint256 second=FWA.pendingFees(fees[1]);
        uint256 bareGas=uint256(p.gasSchedule.sync)+p.gasSchedule.synced+p.gasSchedule.pruned;
        uint256 oneQuote=account.quote(bareGas+p.gasSchedule.fund+p.gasSchedule.harvested,1,false);
        uint256 twoQuote=account.quote(bareGas+p.gasSchedule.fund+2*p.gasSchedule.harvested,1,false);
        assertGt(first,oneQuote,"old optimistic first-prefix cash test is actually reached");
        assertGt(second,oneQuote);
        uint256 deficit=(first-oneQuote+first+second-twoQuote)/2;
        assertLt(first,deficit+oneQuote);assertLt(second,deficit+oneQuote);
        assertGe(first+second,deficit+twoQuote);
        _withdrawTo(account.renewalFloat()-deficit);
        assertEq(account.fundingDeficit(false),deficit);assertEq(account.keeperCash(),0);
        (uint256 routine,)=account.budget();assertGe(routine,twoQuote);
        uint256[] memory shortIds=new uint256[](2);shortIds[0]=terminal;shortIds[1]=fees[0];
        bytes32 beforeBook=_bookHash();bytes32 expected=account.configurationHash();
        vm.expectRevert(VaultLib.Payment.selector);
        account.sync(shortIds,0,1,expected);
        assertEq(_bookHash(),beforeBook,"short-prefix revert preserves book, balance and budget");
        assertEq(FWA.pendingFees(fees[0]),first);assertEq(FWA.pendingFees(fees[1]),second);
        _trace("shortPrefixRejected","syncRejected",0,string.concat('{"terminal":',vm.toString(terminal),
            ',"first":',vm.toString(fees[0]),',"minimumPay":1}'));
        uint256[] memory ids=new uint256[](fees.length+1);ids[0]=terminal;
        for(uint256 i;i<fees.length;++i)ids[i+1]=fees[i];
        uint256 untouched=fees.length>2?FWA.pendingFees(fees[2]):0;
        uint256 keeperBefore=address(this).balance;beforeCash=address(account).balance;
        uint256 paid=account.sync(ids,0,twoQuote,account.configurationHash());keeperPaid+=paid;
        assertEq(paid,twoQuote);assertEq(address(this).balance-keeperBefore,paid);
        assertEq(address(account).balance,beforeCash+first+second-paid,"every actually collected wei reconciles");
        assertGe(address(account).balance,account.renewalFloat());assertEq(account.fundingDeficit(false),0);
        assertEq(FWA.pendingFees(fees[0]),0);assertEq(FWA.pendingFees(fees[1]),0);
        if(fees.length>2)assertEq(FWA.pendingFees(fees[2]),untouched,"stop after the first actually funded prefix");
        assertEq(FWA.feeCredit(address(account)),0);assertTrue(account.renewalEligible(account.idlePackAt(0)));
        _trace("twoFeePrefixPaid","sync",paid,string.concat('{"ids":',ReconcileTrace.uints(ids),
            ',"feeIdsConsumed":[',vm.toString(fees[0]),',',vm.toString(fees[1]),'],"received":',vm.toString(first+second),'}'));
    }
}

contract ForkManagerRenewalReserveDeficitTest is ManagerFiveProofFundingBase {
    function output() internal pure override returns(string memory){return "sim/out/manager-renewal-reserve-deficit-trace.jsonl";}
    function test_renewalInsufficientRealFeesCannotConsumeReserveOrRetiredPrincipal() public {
        (uint256 terminal,uint256[] memory fees)=_prepare();
        vm.prank(accountOwner);account.recover(one(terminal),0);
        uint256 returned=account.idlePackAt(0);
        _trace("ownerRecoveredReturn","recover",0,string.concat('{"callerFunded":true,"ids":[',vm.toString(terminal),']}'));
        VaultLib.Params memory p=account.getParams();p.reserve=0.5 ether;_save(p);
        _withdrawTo(0.001 ether);
        assertEq(account.fundingDeficit(true),0.499 ether);assertEq(account.renewalCash(),0);
        uint256 credit=FWA.feeCredit(address(account));assertGt(credit,0);
        uint256 available=credit;
        for(uint256 i;i<fees.length;++i)available+=FWA.pendingFees(fees[i]);
        assertLt(available,0.21 ether,"fixture cannot manufacture a fundable below-reserve renewal");
        // Renewal requires sorted fee IDs. All sources and the returned pack are genuine.
        for(uint256 i;i<fees.length;++i)for(uint256 j=i+1;j<fees.length;++j)if(fees[j]<fees[i]){
            uint256 swap=fees[i];fees[i]=fees[j];fees[j]=swap;
        }
        bytes32 beforeBook=_bookHash();bytes32 expected=account.configurationHash();
        uint256 supply=SHAPES.totalSupply();uint256 mintFees=IShapesFeeAdmin(address(SHAPES)).pendingFees();
        vm.expectRevert(StrategyLib.Payment.selector);
        account.renew(one(returned),backing(),fees,1,expected);
        assertEq(_bookHash(),beforeBook);assertEq(PACKS.ownerOf(returned),address(account));
        assertTrue(account.renewalEligible(returned));assertEq(SHAPES.totalSupply(),supply);
        assertEq(IShapesFeeAdmin(address(SHAPES)).pendingFees(),mintFees);assertEq(FWA.feeCredit(address(account)),credit);
        _trace("reserveDeficitRejected","renewRejected",0,string.concat('{"returnedPack":',vm.toString(returned),
            ',"feeIds":',ReconcileTrace.uints(fees),',"availableFees":',vm.toString(available),
            ',"fundableReserveDeficitCase":"not reached with actual modest archived earnings"}'));
    }
}
