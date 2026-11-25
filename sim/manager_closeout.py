#!/usr/bin/env python3
"""Receipt-bound single-cycle manager sensitivity; no simulation or network calls."""
import argparse
import hashlib
import json
from pathlib import Path
from fractions import Fraction
from manager_standard_backing import diagnostic

ROOT = Path(__file__).resolve().parent.parent
E = 10**18
PINS = {
    'docs/receipts/manager-r2-cost-calibration.json': 'ff946f9c65a3f5dd40ccd1e4aed1258982a73484a44029ecd14640c942c6c977',
    'docs/receipts/manager-r2-closeout.json': '51f824ae75c58bfdb46875cf72cdf63ea944d583d80dea2278930e4d141522a8',
    'docs/receipts/manager-r2-live-observation.json': 'ae53f7fa2025ce2c0483813409fdff0c2c9bcfd4f20e2c705cc550d3b86a97f3',
    'docs/receipts/manager-standard-backing-fork.json': '5347a7b2060cf8a1eacd63cfd8e2aabb829507038a54ad7be425e2449b3be8b2',
    'docs/receipts/manager-operating-reconciliation.json': '6d1215ffa053bd0e951a0ad5d6d9a6cbe0a0405c3c47853120fb5b92963b5924',
}

SOURCE_PINS = {
    'sim/manager_standard_backing.py': 'f4f471427189a8cd642cdb967d7d192c0ecbc4867ca43cc410fd166a1519f8c1',
    'sim/manager_monte_carlo.py': '99992c7ec87e58370b769239176f6162459b2cb161dd93a6828b7c0c7ce204a2',
    'keeper/keeper.py': '5bfe7f9b9965dcab42eeb92e7707e2a791132c5880b03fa2b3b929e2426816a1',
    'keeper/config.py': '39acb35f93fb64916dd4c8c8ab64da76742ec8c8b1c90902c9c1b014a6a22f06',
    'keeper/policy.py': '42a40400cee6acd7ad1b3342548bd5f0754d11636a9b890118caa346bd4f219a',
}

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_json(path, expected):
    if digest(path) != expected:
        raise ValueError('changed receipt: ' + str(path))
    return json.loads(path.read_text())


def verify_sources(root, sources):
    for name, expected in sources.items():
        if digest(root / name) != expected:
            raise ValueError('stale evidence for source: ' + name)


def build_report(root=ROOT):
    inputs = {name: checked_json(root / name, sha) for name, sha in PINS.items()}
    costs, receipts, observation, standard, reconciliation = inputs.values()
    verify_sources(root, SOURCE_PINS)
    verify_sources(root, costs['contract_source_sha256'])
    verify_sources(root, reconciliation['source_sha256'])
    if receipts['contractSourceSha256'] != costs['contract_source_sha256']:
        raise ValueError('receipt/calibration source mismatch')
    if costs['receipts_sha256'] != PINS[costs['receipts']]:
        raise ValueError('calibration receipt mismatch')
    if any(x.get('status') != 'PASS' for x in (receipts, standard, reconciliation)):
        raise ValueError('nonpassing receipt evidence')
    if not all(d['runtimeMatch'] for d in standard['dependencies'].values()):
        raise ValueError('unverified external dependency runtime')
    values = json.loads((root / 'deploy/manager.json').read_text())
    if values != receipts['managerValues']:
        raise ValueError('manager values differ from current receipt')
    live_path = 'docs/receipts/manager-final-live-observation.json'
    live = json.loads((root / live_path).read_text())
    if live['mintFeeWei'] != observation['mintFeeWei'] or not live['readOnly'] or not all(d['matchesReceiptDependency'] for d in live['dependencies'].values()):
        raise ValueError('live fee or dependencies changed from the receipt calibration')
    p = observation['protocol']
    k = int((1 + Fraction(p['surchargeBps'], 10000)) *
            (1 - Fraction(p['ownerAcquisitionFeeBps'], 10000)) *
            (1 - Fraction(p['topListingShareBps'], 10000)) * E)
    if abs(k - p['inferredGrossMultiplier1e18']) > p['inferredGrossMultiplierRoundingBound']:
        raise ValueError('observed multiplier differs from protocol fee rules')
    comparison = diagnostic(dict(manager_values=values, mint_fee_observation=observation,
                                model_gross_multiplier_1e18=k, mint_fee_wei=observation['mintFeeWei']))
    comparison['rows'] = [r for r in comparison['rows'] if r['backing_wei'] in (3*10**16, 21*10**16)]
    for case in receipts['cases']:
        if any(case['final'].values()) or case['ownerLedgerGapWei'] or case['ownerNetWei'] != case['withdrawnWei'] - case['fundingWei'] - case['walletGasWei']:
            raise ValueError('incomplete or inconsistent owner cash ledger')
    keeper = receipts['keeper']
    if keeper['netWei'] != keeper['compensationWei'] - keeper['walletGasWei']:
        raise ValueError('keeper cash ledger mismatch')
    if sum(c['fundingWei'] - c['withdrawnWei'] for c in receipts['cases']) != receipts['creatorPrimaryFeesAccruedWei'] + keeper['compensationWei'] or receipts['accountLedgerGapWei']:
        raise ValueError('account cash partition mismatch')
    standard_cases = []
    for c in standard['cases']:
        if c['ledgerGapWei'] or c['ownerNetWei'] != -c['paidPrimaryMintFeesWei'] - c['totalWalletGasWei']:
            raise ValueError('standard round trip ledger mismatch')
        standard_cases.append({name: c[name] for name in ('totalGasPriceWei', 'returnedPackFaceWei', 'returnedListingBackingWei', 'paidPrimaryMintFeesWei', 'totalWalletGasWei', 'ownerNetWei')})
    wallet = [{ 'total_gas_gwei': price, 'operation_costs_wei': {
        name: costs['gas_proxy'][name] * wei for name in
        ('create', 'setExiting', 'withdraw', 'unlist', 'liquidate', 'recover_sync', 'processAcquisitions')}}
        for price, wei in ((.2, 200000000), (.5, 500000000))]
    return dict(kind='Bounded quoted single-cycle sensitivity and separate actual unselected round trips',
        input_sha256=PINS | {'deploy/manager.json': digest(root/'deploy/manager.json'), live_path: digest(root/live_path)},
        latest_read_only_observation=live,
        contract_source_sha256=costs['contract_source_sha256'], model_source_sha256=reconciliation['source_sha256'] | SOURCE_PINS,
        report_writer_sha256=digest(root/'sim/manager_closeout.py'),
        observation_block=observation['block'], mint_fee_wei=observation['mintFeeWei'], accepted_mint_fee_wei=values['acceptedMintFeeWei'],
        gross_multiplier_1e18=k, standard_fresh_bid_pre_gas_break_even_fee_wei=(k-E)*(3*10**16)//E//3,
        comparison=comparison, owner_wallet_gas_sensitivity=wallet,
        actual_standard_round_trips=standard_cases,
        actual_manager_round_trips=[{name: c[name] for name in ('label', 'fundingWei', 'withdrawnWei', 'walletGasWei', 'ownerNetWei', 'final')} for c in receipts['cases']],
        actual_keeper=keeper, actual_creator_gross_fees_wei=receipts['creatorPrimaryFeesAccruedWei'],
        actual_deployer_startup_gas_wei=receipts['deploymentWalletGasWei'],
        unmeasured_operations=costs['unmeasured_operations'], limitations=[
            'No monthly return, APR, Monte Carlo inference or viability proof. No partial campaign outcomes are inputs.',
            '.03 backing is an isolated hypothetical for the current manager, whose admission rejects it; actual FWA admission is separately proven.',
            'The cycle screen assumes gross listing-fee income k times backing per own selection under fixed proportional selection/fee weights. It is an analytical expected-fee attribution, not fees actually received on an individual acquisition or a measured return period. Cycle costs include fresh mints and full quoted keeper payments, not billed renewal/harvest/list/sync operating costs.',
            'Owner wallet sensitivity reprices measured operation gas individually; do not sum mutually conditional recovery calls or interpret them as a measured complete path.',
            'Actual round trips are unselected exits, use their own receipt gas prices, and are not added to cycle quotes. Creator accrual is gross; deployer startup is separate from owner cash.',
            'Historical input receipt/runtime bindings are checked locally; no fresh mainnet observation or new transaction is performed.',
            'The incomplete funded campaigns remain incomplete and earlier invalid campaigns remain excluded.'],
        things_that_do_not_make_sense=['Quoted keeper margins do not establish actual billed profitability.', 'A balanced cash ledger does not establish positive owner returns.'])


def markdown(report):
    eth = lambda value: format(Fraction(value, E).numerator / Fraction(value, E).denominator, '.12f')
    lines = ['# Manager economic closeout', '', '**Bounded single-cycle sensitivity, not monthly return, APR or viability proof.**', '',
             f"Receipt fee .0005 ETH at block {report['observation_block']}; confirmed again at block {report['latest_read_only_observation']['block']}. Accepted maximum and historical comparison .001 ETH. Standard fresh-bid mint-fee break-even before all gas: **{eth(report['standard_fresh_bid_pre_gas_break_even_fee_wei'])} ETH per Shape**.", '',
             '.03 backing is hypothetical for the current manager. FWA admission and actual unselected round trips are separate evidence.', '',
             '| Backing ETH | Mint fee ETH | Gas gwei | Bid net after quoted cycle costs ETH | Keep net after quoted cycle costs ETH |',
             '|---:|---:|---:|---:|---:|']
    for r in report['comparison']['rows']:
        lines.append(f"| {eth(r['backing_wei'])} | {eth(r['mint_fee_per_shape_wei'])} | {r['total_gas_gwei']} | {eth(r['bid_cycle_net_after_quoted_cost_wei'])} | {eth(r['keep_cycle_net_after_quoted_cost_wei'])} |")
    lines += ['', 'The screen attributes k times backing in gross listing-fee income per own selection, assuming fixed proportional selection and fee weights. Actual fees need not arrive with that selection. Keep gains at .21 backing assume a purchaser voluntarily keeps a .03 pack rather than taking the larger bid; that is not a buyer forecast. Costs include three primary mints and full construction/maintenance keeper quotes, plus retirement for bids. Clone creation and final owner exit are additional measured-gas sensitivities:', '', '| Gas gwei | Operation | Wallet gas ETH |', '|---:|---|---:|']
    for row in report['owner_wallet_gas_sensitivity']:
        lines += [f"| {row['total_gas_gwei']} | {name} | {eth(cost)} |" for name, cost in row['operation_costs_wei'].items()]
    lines += ['', 'Actual FWA standard unselected round trips:', '', '| Gas gwei | Face + backing returned ETH | Primary fees ETH | Wallet gas ETH | Owner net ETH |', '|---:|---:|---:|---:|---:|']
    for c in report['actual_standard_round_trips']:
        lines.append(f"| {c['totalGasPriceWei']/10**9:g} | {eth(c['returnedPackFaceWei']+c['returnedListingBackingWei'])} | {eth(c['paidPrimaryMintFeesWei'])} | {eth(c['totalWalletGasWei'])} | {eth(c['ownerNetWei'])} |")
    lines += ['', 'Actual current-source manager unselected exits:', '', '| Account | Funded ETH | Withdrawn ETH | Wallet gas ETH | Owner net ETH |', '|---|---:|---:|---:|---:|']
    for c in report['actual_manager_round_trips']:
        lines.append(f"| {c['label']} | {eth(c['fundingWei'])} | {eth(c['withdrawnWei'])} | {eth(c['walletGasWei'])} | {eth(c['ownerNetWei'])} |")
    k = report['actual_keeper']
    lines += ['', f"Actual keeper compensation / gas / net: {eth(k['compensationWei'])} / {eth(k['walletGasWei'])} / {eth(k['netWei'])} ETH. Creator gross fees: {eth(report['actual_creator_gross_fees_wei'])} ETH. Separate deployer startup gas: {eth(report['actual_deployer_startup_gas_wei'])} ETH.", '', 'Unmeasured operating gas: ' + ', '.join(report['unmeasured_operations']) + '.', '']
    lines += [paragraph for limit in report['limitations'] for paragraph in (limit, '')]
    lines += ["Things that don't make sense: " + ' '.join(report['things_that_do_not_make_sense']), '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', default='docs/receipts/manager-closeout-economics', help='Output stem, without extension')
    args = parser.parse_args()
    report = build_report()
    output = ROOT / args.out
    output.parent.mkdir(parents=True, exist_ok=True)
    output.with_suffix('.json').write_text(json.dumps(report, indent=2) + '\n')
    output.with_suffix('.md').write_text(markdown(report))


if __name__ == '__main__':
    main()
