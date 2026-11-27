#!/usr/bin/env python3
"""Replay the fork trace from test/fork/ForkReconcile.t.sol through sim/vault.py and require
every vault number to match the chain.

Tolerance: zero wei for everything the vault computes. FWA's per-listing fee share is checked
against FWA's formula within 1 wei per listing (its accumulator floors per listing and ceils
each listing's starting debt); the model then takes the fee amounts FWA actually paid.

Run: forge test --match-path test/fork/ForkReconcile.t.sol ... && python3 sim/reconcile.py
"""
import json
import sys
from pathlib import Path

from vault import ACTIVE, OWED, BPS, Vault

TRACE = Path(__file__).parent / "out/reconcile-trace.jsonl"
MINT_FEE = 10**15  # Shapes mintFee per paid primary Shape, pinned fork input


def compare_snapshot(v, r, failures, actors=None):
    def check(field, model, chain):
        if model != chain:
            failures.append(f"{r['step']}.{field}: model {model} chain {chain} (diff {model - chain if isinstance(model, int) and isinstance(chain, int) else 'structured mismatch'})")

    if r["step"] not in ("checkpoint1", "checkpoint2", "partial"):
        v.pay_keeper(r["pay"])
    for field, amount in (("balance", v.balance), ("totalShares", v.total_shares), ("lastNav", v.last_nav),
                          ("pendingDepositTotal", v.pending_total), ("redemptionReserve", v.redemption_reserve),
                          ("lockedShares", v.locked_shares), ("open", len(v.positions)),
                          ("idle", len(v.idle_packs)),
                          ("aliceShares", v.share_balance("alice")), ("bobShares", v.share_balance("bob")),
                          ("trackedValue", v.tracked_value), ("idleValue", v.idle_value),
                          ("activeBacking", v.active_backing), ("activeCount", v.active_count),
                          ("idleFunding", v.idle_funding),
                          ("feeDebtSum", v.fee_debt_sum), ("allocatedValue", v.allocated_value),
                          ("pendingReceipts", len(v.receipts)), ("cursor", v.acquisition_cursor),
                          ("reservedCount", sum(p.state != OWED for p in v.positions.values())),
                          ("feeCredit", v.fee_credit), ("processingPool", v.processing_pool),
                          ("chargeRefundReserve", v.charge_refund_reserve),
                          ("chargeEra", v.charge_era), ("unresolvedKeepUplift", v.unresolved_keep_uplift),
                          ("distributionReserve", v.distribution_reserve), ("claimableTotal", v.claimable_total)):
        check(field, amount, r[field])
    check("aliceClaimable", v.claimable.get("alice", 0), r["aliceClaimable"])
    redemption = v.redemptions.get("alice")
    check("aliceLocked", redemption.shares if redemption else 0, r["aliceLocked"])
    if "renewalEligible" in r:
        check("renewalEligible",len(v.renewal_eligible),r["renewalEligible"])
    if "keptReplacements" in r:
        check("keptReplacements",v.kept_replacements,r["keptReplacements"])
    if set(v.positions) != {p["id"] for p in r["positions"]}:
        failures.append(f"{r['step']}: position identity sets differ")
    for live in r["positions"]:
        if live["id"] not in v.positions:
            continue
        p = v.positions[live["id"]]
        for field, amount in (("value", p.value), ("backing", p.backing), ("feeDebt", p.fee_debt),
                              ("allocatedAt", p.allocated_at), ("state", p.state)):
            check(f"position[{live['id']}].{field}", amount, live[field])

    def actor(label):
        if actors is None:
            raise ValueError('trace setup must include authenticated alice/bob actor addresses')
        return actors[label].lower()
    if 'contributions' in r:
        expected = [[actor(c[0]), c[1], c[2], c[3], c[4]] for c in v.contributions]
        actual = [[c['payer'].lower(), c['era'], c['start'], c['amount'], c['claimed']] for c in r['contributions']]
        check('contributions', expected, actual)
        for era in r['chargeEras']:
            check('chargeEra[' + str(era['era']) + ']', v.charge_eras.get(era['era'], [0, 0, False]),
                  [era['total'], era['refundable'], era['closed']])
        for issuance in r['issuances']:
            check('issuance[' + str(issuance['epoch']) + ']', v.issuances.get(issuance['epoch'], [0, 0, 0, 0]),
                  [issuance[k] for k in ('gross', 'issued', 'remainingGross', 'remainingShares')])


def checkpoint_from_trace(v, row):
    v.construction_cost, v.reference_capital = row['constructionCost'], row['referenceCapital']
    v.live_mint_fee = row['liveMintFee']
    v.checkpoint(keeper_payment=row['pay'])


def reconcile_cycle():
    rows = [json.loads(line) for line in TRACE.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    s = by["setup"]
    v = Vault(seed=3 * 10**18, balance=s["deployBalance"], reserve=0, renewal_mode=1, pack_units_mask=1 << s["units"])
    failures = []

    def check(step, field, model, chain):
        if model != chain:
            failures.append(f"{step}.{field}: model {model} chain {chain} (diff {model - chain if isinstance(model, int) and isinstance(chain, int) else 'structured mismatch'})")

    # Only the selected listing belongs to this vault. Real third-party filler preserves
    # the historical VRF weight; it is neither vault capital nor simulated inventory.
    sel = by["selected"]
    selected = s["selectedListing"]
    v.acquisition_cursor = s["initCursor"]
    # Admissions precede the real selection. Do not expose its future journal prefix
    # to the legitimate unexposed advance performed by the first admission.
    v.completed_prefix = s["initCursor"]
    # build mints each pack straight into ShapePacks and lists it at once (one call, no loose Shapes).
    v.build([live["id"] for live in sel["positions"]], s["units"], MINT_FEE, s["backings"],
            fee_debt=s["activationDebt"])
    v.completed_prefix = sel["completedPrefix"]
    v.pay_keeper(s["selectPay"])
    check("setup", "balance", v.balance, s["balance"])

    fee = s["acqFee"]
    distributable = fee - fee * s["acqCutBps"] // BPS
    distributable -= distributable * s["acqCrownBps"] // BPS
    share = distributable // s["acqActive"]
    paid_by_fwa = sel["pendingFeesSum"] + sel["feeCredit"]
    if abs(paid_by_fwa - share * s["count"]) > s["count"]:
        failures.append(f"fee share: chain {paid_by_fwa} vs formula {share * s['count']}")
    credit = sel["feeCredit"]
    v.fee_credit = credit

    def compare(step):
        compare_snapshot(v, by[step], failures, s.get("actors"))

    compare("selected")
    v.bid_settled(selected)
    compare("bid")  # purchaser takes the bid: no vault ETH moves
    ch = by["charges"]
    v.deposit("alice", 10**18, ch["ckA"])
    v.deposit("bob", 5 * 10**17, ch["ckB"])
    compare("deposits")
    v.select(selected, sel["positions"][0]["liveAllocatedAt"])
    v.acquisition_cursor += 1
    v.sync_owned(selected)
    v.prune(16)
    compare("sync")
    for i in v.positions:
        v.harvest_listing(i)
    v.receive_fees(sel["pendingFeesSum"] + credit)
    v.fee_credit = 0
    compare("harvest")
    # FWA expires the remaining real request. Its external completed prefix is an input;
    # these entries are foreign/refunded and cannot change vault principal or membership.
    v.completed_prefix = by["catchup"]["completedPrefix"]
    while v.acquisition_cursor < v.completed_prefix:
        v.process_journal([None] * min(16, v.completed_prefix - v.acquisition_cursor))
    compare("catchup")
    live = by["list"]["positions"][0]
    v.list(live["id"], by["relistBacking"]["backing"], fee_debt=live["liveFeeDebt"])
    compare("list")
    checkpoint_from_trace(v, by["checkpoint1"])
    compare("checkpoint1")
    rc = by["redeemCharge"]
    v.request_redeem("alice", v.share_balance("alice"), rc["ck"], rc["total"] - rc["ck"])
    compare("redeem")
    checkpoint_from_trace(v, by["checkpoint2"])
    compare("checkpoint2")
    got = v.claim("alice")
    compare("claim")
    check("claim", "aliceReceived", got, by["aliceReceived"]["amount"])

    # The ledger: every wei in equals every wei out plus what the vault still holds.
    held = (v.balance + sum(p.backing + p.value for p in v.positions.values()) + sum(v.idle_packs))
    ins = s["deployBalance"] + 15 * 10**17 + ch["ckA"] + ch["ckB"] + rc["total"] + v.fees_received
    outs = v.keeper_paid + v.mint_fees + got + v.backing_lost
    check("ledger", "held + out == in", held + outs, ins)
    steps = [r["step"] for r in rows]
    print(f"steps: {', '.join(steps)}")
    print(f"ledger: fees received {v.fees_received}, keeper paid {v.keeper_paid}, mint fees {v.mint_fees}, "
          f"backing lost {v.backing_lost}")
    if failures:
        print("MISMATCH")
        print("\n".join(failures))
        return 1
    print("reconciled: every vault number matches the fork run to the wei")
    return 0


def reconcile_partial():
    trace = TRACE.with_name("reconcile-partial-trace.jsonl")
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    setup = by["setup"]
    v = Vault(seed=10**16, balance=setup["deployBalance"], reserve=5 * 10**15, renewal_mode=1,
              pack_units_mask=1 << by["buildInputs"]["units"])
    v.acquisition_cursor = v.completed_prefix = setup["initCursor"]
    failures = []

    def compare(step):
        compare_snapshot(v, by[step], failures, setup.get("actors"))

    charges = by["depositCharge"]
    v.deposit("alice", 10**18, charges["ck"])
    compare("deposit")
    checkpoint_from_trace(v, by["checkpoint1"])
    compare("checkpoint1")
    # build-and-list: one keeper step mints and lists every pack (batched at MAX_LIST_BATCH on chain).
    bi = by["buildInputs"]
    live = {p["id"]: p for p in by["build"]["positions"]}
    debt = live[bi["ids"][0]]["liveFeeDebt"] if bi["ids"] else None
    for start in range(0, len(bi["ids"]), 4):
        chunk = bi["ids"][start:start + 4]
        v.build(chunk, bi["units"], setup["mintFee"], bi["backings"][start:start + len(chunk)], fee_debt=debt)
    compare("build")
    rc = by["redeemCharge"]
    v.request_redeem("alice", v.share_balance("alice"), rc["ck"], rc["total"] - rc["ck"])
    compare("redeem")
    checkpoint_from_trace(v, by["partial"])
    if not 0 < v.locked_shares < v.redemptions["alice"].shares:
        failures.append("partial: real first fill must leave some, but not all, shares locked")
    compare("partial")
    compare("windDown")  # owner flag changes no financial bucket
    for id_ in list(v.positions):
        v.unlist(id_)
    compare("unlist")
    while v.idle_packs:
        v.liquidate_one()
    compare("liquidate")
    checkpoint_from_trace(v, by["checkpoint2"])
    compare("checkpoint2")
    got = v.claim("alice")
    compare("claim")
    if got != by["aliceReceived"]["amount"]:
        failures.append(f"claim: model {got} vs actual {by['aliceReceived']['amount']}")
    ins = setup["deployBalance"] + 10**18 + charges["ck"] + rc["total"]
    outs = v.balance + got + v.keeper_paid + v.mint_fees
    if ins != outs:
        failures.append(f"partial ledger: in {ins} vs held+out {outs}")
    print(f"partial/wind-down: claim {got}, keeper pay {v.keeper_paid}, mint fees {v.mint_fees}, "
          f"remaining redemption-rounding reserve {v.redemption_reserve} wei")
    if failures:
        print("MISMATCH\n" + "\n".join(failures))
        return 1
    print("reconciled: partial fill, wind-down, full exit and every bucket match to the wei")
    return 0


def reconcile_scan():
    """Replay test/fork/ForkScanReconcile.t.sol: a real own selection, a real >= 41-entry foreign
    backlog, then one paid scan sync that reads the single own position and jumps the cursor over
    the whole backlog. The model takes the same scan path via Vault.scan_rebase and must match every
    vault number to the wei."""
    trace = TRACE.with_name("reconcile-scan-trace.jsonl")
    rows = [json.loads(line) for line in trace.read_text().splitlines()]
    by = {r["step"]: r for r in rows}
    s = by["setup"]
    sel = by["selected"]
    selected = s["selectedListing"]
    failures = []

    v = Vault(seed=3 * 10**18, balance=s["deployBalance"], reserve=0, renewal_mode=1, pack_units_mask=1 << s["units"])
    v.acquisition_cursor = s["initCursor"]
    v.completed_prefix = s["initCursor"]
    v.build([live["id"] for live in sel["positions"]], s["units"], MINT_FEE, s["backings"],
            fee_debt=s["activationDebt"])
    v.completed_prefix = sel["completedPrefix"]
    v.pay_keeper(s["selectPay"])
    if v.balance != s["balance"]:
        failures.append(f"setup.balance: model {v.balance} chain {s['balance']}")

    # FWA's per-listing share from its own formula, within 1 wei per listing.
    fee = s["acqFee"]
    distributable = fee - fee * s["acqCutBps"] // BPS
    distributable -= distributable * s["acqCrownBps"] // BPS
    share = distributable // s["acqActive"]
    paid_by_fwa = sel["pendingFeesSum"] + sel["feeCredit"]
    if abs(paid_by_fwa - share * s["count"]) > s["count"]:
        failures.append(f"fee share: chain {paid_by_fwa} vs formula {share * s['count']}")
    v.fee_credit = sel["feeCredit"]

    def compare(step):
        compare_snapshot(v, by[step], failures, s.get("actors"))

    compare("selected")

    # The real foreign backlog is an external input: it moves FWA's completed prefix but touches no
    # vault bucket until the scan reads it.
    v.completed_prefix = by["backlog"]["completedPrefix"]
    compare("backlog")

    at = sel["positions"][0]["liveAllocatedAt"]
    scanned = v.scan_rebase([(at, selected)])
    if scanned != 1:
        failures.append(f"scan: model scanned {scanned}, expected 1")
    if v.acquisition_cursor != v.completed_prefix:
        failures.append(f"scan: cursor {v.acquisition_cursor} did not jump to {v.completed_prefix}")
    v.prune(16)
    compare("scan")

    # Every wei in equals the vault's holdings plus keeper pay out; the uncollected fee credit stays
    # on FWA (never swept here), so it is neither an inflow nor a holding yet.
    held = (v.balance + sum(p.backing + p.value for p in v.positions.values()) + sum(v.idle_packs))
    ins = s["deployBalance"]
    outs = v.keeper_paid + v.mint_fees + v.backing_lost
    if held + outs != ins:
        failures.append(f"scan ledger: held+out {held + outs} vs in {ins}")
    print(f"scan: backlog {by['backlog']['completedPrefix'] - s['initCursor']} entries cleared, "
          f"keeper paid {v.keeper_paid}, fee credit still on FWA {v.fee_credit}")
    if failures:
        print("MISMATCH\n" + "\n".join(failures))
        return 1
    print("reconciled: scan path, one selection applied over a 47-entry backlog, every bucket to the wei")
    return 0


def reconcile_contributions():
    path = TRACE.with_name('reconcile-contributions-trace.jsonl')
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    setup, actors = rows[0]['expected'], rows[0]['actors']
    v = Vault(seed=setup['balance'], balance=setup['balance'], reserve=5 * 10**15)
    v.acquisition_cursor = v.completed_prefix = setup['cursor']
    failures, received, returned = [], setup['balance'], 0
    for index, row in enumerate(rows):
        action, payer = row['action'], row.get('payer')
        if action == 'deposit':
            v.deposit(payer, row['amount'], row['pay'])
            received += row['amount'] + row['pay']
        elif action == 'cancel':
            returned += v.cancel(payer)
        elif action == 'fund':
            excess = v.fund_checkpoint(payer, row['amount'], row['quote'] + v.processing_pool)
            if excess != row['amount'] - row['quote']:
                failures.append(f'{index}: incorrect excess funding refund')
            received += row['amount'] - excess
        elif action == 'closeCheckpoint':
            v.construction_cost, v.reference_capital = row['constructionCost'], row['referenceCapital']
            v.checkpoint(keeper_payment=row['pay'])
        elif action == 'claimRefund':
            returned += v.claim_checkpoint_refund(payer, row['ids'])
        elif action != 'setup':
            raise ValueError('unknown contribution trace action: ' + action)
        expected = row['expected'] | {'pay': 0, 'step': str(index) + ':' + action}
        compare_snapshot(v, expected, failures, actors)
        if v.balance + returned + v.keeper_paid != received:
            failures.append(f'{index}: absolute contribution/cash conservation mismatch')
    if failures:
        print('contribution MISMATCH\n' + '\n'.join(failures))
        return 1
    print(f'reconciled: {len(rows)} real contribution transitions, every interval, issuance and wei')
    return 0


def reconcile_fresh():
    path=TRACE.with_name('reconcile-renewal-trace.jsonl')
    rows=[json.loads(line) for line in path.read_text().splitlines()]
    by={row['step']:row for row in rows}
    s,sel=by['setup'],by['selected']
    v=Vault(seed=s['deployBalance'],balance=s['deployBalance'],reserve=s['reserve'],renewal_mode=0,
            renewal_float=s['renewalFloat'],pack_units_mask=8,accepted_mint_fee=s['liveMintFee'],live_mint_fee=s['liveMintFee'])
    v.acquisition_cursor=v.completed_prefix=s['initCursor']
    selected=s['selectedListing']
    v.build([selected],s['units'],s['liveMintFee'],s['backings'],fee_debt=s['activationDebt'])
    v.pay_keeper(s['selectPay'])
    v.completed_prefix=sel['completedPrefix']
    v.fee_credit=sel['feeCredit']
    failures=[]
    fee=s['acqFee']-s['acqFee']*s['acqCutBps']//BPS
    fee-=fee*s['acqCrownBps']//BPS
    formula=fee//s['acqActive']*s['count']
    actual=sel['pendingFeesSum']+sel['feeCredit']
    if abs(actual-formula)>s['count']:
        failures.append(f'fresh fee share: actual {actual}, formula {formula}')
    def compare(step):
        compare_snapshot(v,by[step],failures,s['actors'])
    compare('selected')
    v.select(selected,sel['positions'][0]['liveAllocatedAt'])
    v.acquisition_cursor+=1
    v.prune(16)
    compare('allocated')
    v.bid_settled(selected)
    compare('bid')
    v.sync_owned(selected)
    v.prune(16)
    compare('returned')
    v.completed_prefix=by['drained']['completedPrefix']
    compare('drained')
    renewed=by['renewed']['positions'][0]
    v.fee_accumulator=renewed['liveFeeDebt']
    v.renew([renewed['id']],s['units'],s['liveMintFee'],[renewed['backing']],returned_count=1)
    compare('renewed')
    held=v.balance+sum(p.backing+p.value for p in v.positions.values())+sum(v.idle_packs)
    if held+v.keeper_paid+v.mint_fees+v.backing_lost != s['deployBalance']+v.fees_received:
        failures.append('fresh renewal absolute cash/asset conservation mismatch')
    if failures:
        print('fresh renewal MISMATCH\n'+'\n'.join(failures))
        return 1
    print(f'reconciled fresh renewal: {len(rows)-1} real transitions; paid mint fees {v.mint_fees}, keeper {v.keeper_paid}, backing spent {v.backing_lost}, eligibility consumed once')
    return 0


def reconcile_funding():
    """Conditional manager funding begins from an observed real strategy slice, with no holder liabilities."""
    from eth_abi import decode
    import sys
    sys.path.insert(0,str(TRACE.parent.parent.parent/'keeper'))
    from config import PARAMS_T,PARAMS_ORDER,GAS_FIELDS,gas_schedule
    from policy import State,quote,shape_count
    rows=[json.loads(line) for line in TRACE.with_name('reconcile-renewal-funding-trace.jsonl').read_text().splitlines()]
    by={row['step']:row for row in rows}
    inputs,before,after=by['inputs'],by['before'],by['after']
    if not all(k in inputs for k in ('params','baseFee','gasPrice')):
        raise ValueError('funding trace must bind full actual Params and executed fee context')
    raw=decode([PARAMS_T],bytes.fromhex(inputs['params'][2:]))[0]
    values=dict(zip(PARAMS_ORDER,raw[:-1]))|{'gasSchedule':dict(zip(GAS_FIELDS,raw[-1]))}
    state=State(now=0,gas_price=inputs['gasPrice'],base_fee=inputs['baseFee'],gas_ceiling=values['gasCeilingWei'],
        essential_ceiling=values['essentialCeilingWei'],max_tip=values['maxTipWei'],
        share_bps=values['keeperShareBps'],k=0,backing=0,min_edge_bps=values['minEdgeBps'],mint_fee=inputs['mintFee'],
        settlement_window=0,blackout=False,queue_drained=True,checkpoint_done_this_interval=False,
        work_fee=values['workFeeWei'],gas_schedule=gas_schedule(values))
    if before['positions'] or before['pendingReceipts']:
        raise ValueError('funding slice must expose its complete pre-renewal ordinary book')
    v=Vault(seed=0,balance=before['balance'],reserve=before['reserve'],renewal_float=before['renewalFloat'],
        renewal_mode=values['renewalMode'],pack_units_mask=values['packUnitsMask'],accepted_mint_fee=values['acceptedMintFeeWei'])
    v.idle_packs=list(inputs['idleValues']);v.idle_shapes=list(inputs['idleShapes']);v.idle_quotes=list(inputs['idleQuotes'])
    v.idle_acquired=[True]*len(v.idle_packs);v.renewal_eligible=list(reversed(v.idle_packs))
    v.tracked_value=v.idle_value=sum(v.idle_packs);v.idle_funding=sum(v.idle_quotes)
    v.fee_credit=before['feeCredit'];v.kept_replacements=before['keptReplacements']
    v.acquisition_cursor=before['cursor'];v.completed_prefix=before['completedPrefix']
    v.routine_budget=before['routineBudget']
    failures=[]
    def compare(row):
        amounts={'balance':v.balance,'open':len(v.positions),'idle':len(v.idle_packs),'trackedValue':v.tracked_value,
            'idleValue':v.idle_value,'activeBacking':v.active_backing,'activeCount':v.active_count,'feeDebtSum':v.fee_debt_sum,
            'allocatedValue':v.allocated_value,'idleFunding':v.idle_funding,'completedPrefix':v.completed_prefix,
            'cursor':v.acquisition_cursor,'pendingReceipts':len(v.receipts),'reservedCount':sum(p.state!=OWED for p in v.positions.values()),
            'feeCredit':v.fee_credit,'renewalEligible':len(v.renewal_eligible),'keptReplacements':v.kept_replacements,
            'renewalFloat':v.renewal_float,'reserve':v.reserve,'creatorFees':v.mint_fees,
            'routineBudget':v.routine_budget}
        for field,amount in amounts.items():
            if amount!=row[field]: failures.append(f'{row["step"]}.{field}: model {amount}, actual {row[field]}')
        for actual in row['positions']:
            p=v.positions.get(actual['id'])
            if p is None:
                failures.append('missing actual funded-renewal position');continue
            for field,amount in [('value',p.value),('backing',p.backing),('feeDebt',p.fee_debt),('state',p.state),('allocatedAt',p.allocated_at)]:
                if amount!=actual[field]:failures.append(f'funded position.{field}: model {amount}, actual {actual[field]}')
    compare(before)
    units=next(u for u in range(3,31) if values['packUnitsMask']>>u&1)
    minted=shape_count(units);retired=v.idle_shapes[-1]
    q=state.gas_schedule
    gas=q['build']+q['build_pack']+minted*q['build_shape']+q['listed']+q['liquidate']+q['liq_pack']+retired*q['redeem_shape']
    bare=quote(state,gas,3)
    position=after['positions'][0]
    need=units*10**16+minted*inputs['mintFee']+position['backing']
    funded,take_credit,claims=v.renewal_fee_plan([],v.fee_credit,gas,3,need,lambda g,u:quote(state,g,u),inputs['feeShareBps'],
        q['sync_funding'],q['harvested'],q['sync_credit'],cash_delta=v.idle_packs[-1])
    if bare!=inputs['bareQuote'] or quote(state,funded,3)!=inputs['fundedQuote'] or take_credit!=before['feeCredit'] or claims:
        failures.append('conditional fee plan/quote differs from actual credit-only funding')
    v.receive_fees(take_credit);v.fee_credit=0
    v.fee_accumulator=position['liveFeeDebt']
    v.renew([position['id']],units,inputs['mintFee'],[position['backing']],returned_count=1)
    actual_pay=v.pay_keeper(quote(state,funded,3),source='renewal')
    if actual_pay!=after['pay']:failures.append('actual funded compensation differs')
    compare(after)
    opening=before['balance']+before['trackedValue']+before['activeBacking']+before['feeCredit']
    closing=v.balance+v.tracked_value+v.active_backing+v.fee_credit+v.keeper_paid+v.mint_fees
    if opening!=closing:failures.append('conditional renewal absolute cash/assets/credit ledger mismatch')
    if failures:
        print('conditional renewal MISMATCH\n'+'\n'.join(failures));return 1
    print(f'reconciled conditional funding: credit {take_credit}, paid {actual_pay}, creator {v.mint_fees}, cash {v.balance}; every book and permission bucket matches')
    return 0


def main():
    raise SystemExit('Historical fixed/Fresh assessment: use the preserved evidence and its pinned revision; current measured reuse evaluations use manager_operating_assessment.py and manager_reconcile.py')
    cycle = reconcile_cycle()
    partial = reconcile_partial()
    scan = reconcile_scan()
    return max(cycle, partial, scan, reconcile_contributions(), reconcile_fresh(), reconcile_funding())


if __name__ == "__main__":
    sys.exit(main())
