#!/usr/bin/env python3
"""Prepare or execute the separately owner-approved efficient-journal local batch.

The historical successful-ready route is recorded as blocked for paid production-vault
measurement: admission needs an empty FWA queue, and an unexposed vault rebases unpaid.
This executor exercises genuine new refunds and a standalone full-holder checkpoint.
No execution flag supplies owner authority; obtain approval of the exact prepared hash first.
"""
import argparse
import ast
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import shlex
import subprocess
import tempfile
import time
from types import SimpleNamespace

from eth_utils import keccak, to_checksum_address
import policy
import keeper as keeper_client
import tx as txm

ROOT = Path(__file__).resolve().parent.parent
PLAN = ROOT / 'docs/receipts/efficient-journal-local-plan.json'
FORK_RPC = 'https://mainnet.gateway.tenderly.co'
RPC = 'http://127.0.0.1:8559'
FORK_BLOCK = 26418539
MAX_GAS = 16777216
MAX_CODE = 24576
E = 10**18
COUNTS = [1, 2, 3, 7, 15, 16, 17, 31, 32, 33, 63, 64, 65, 127, 128]
CANDIDATE_COUNTS = [1, 16, 32, 64, 128]
QUOTE_RANGES = dict(journal=(22000,30000),journal_tail=(85000,160000),pack=(285000,325000))
ACTORS = {n: to_checksum_address(keccak(text='pack-vault-rehearsal-'+n)[-20:])
          for n in ('deployer', 'holder', 'holder2', 'keeper', 'kicker', 'owner')}
FUNDING = dict(deployer=E//10, holder=42*E//10, holder2=12*E//10,
               keeper=E//5, kicker=15*E//10, owner=11*E//10)
PARAMS = '(uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint64,uint128,uint128)'
SOURCE_PATHS = ('src/PackVault.sol', 'src/VaultLib.sol', 'src/KeeperPolicy.sol',
                'src/interfaces/External.sol', 'script/Deploy.s.sol', 'script/DeployCore.sol',
                'script/deploy.sh', 'test/fork/ForkKeeperPolicy.t.sol', 'keeper/policy.py', 'keeper/tx.py',
                'keeper/keeper.py', 'keeper/index.py', 'foundry.toml',
                'lib/solady/src/utils/FixedPointMathLib.sol','lib/solady/src/utils/ReentrancyGuard.sol','lib/solady/src/utils/SafeTransferLib.sol',
                'keeper/efficient_journal_rehearsal.py')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def raw(*args):
    result = subprocess.run(list(map(str, args)), cwd=ROOT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stdout}\n{result.stderr}')
    return result.stdout.strip()


def num(value):
    return int(str(value).split()[0], 0)


def array(values):
    return '['+','.join(map(str, values))+']'


def artifact_templates():
    result={}
    for path in ('out/PackVault.sol/PackVault.json','out/VaultLib.sol/VaultLib.json','out/KeeperPolicy.sol/KeeperPolicyV1.json','out/ForkKeeperPolicy.t.sol/PolicyGreedy.json'):
        p=ROOT/path
        if not p.exists():continue
        a=json.loads(p.read_text());creation=a['bytecode'];runtime=a['deployedBytecode']
        parts=dict(abi=a['abi'],creation=creation['object'],runtime=runtime['object'],
                   creation_links=creation.get('linkReferences',{}),runtime_links=runtime.get('linkReferences',{}),
                   immutable_ranges=sorted((i['start'],i['length']) for refs in runtime.get('immutableReferences',{}).values() for i in refs))
        result[path]=hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()
    return result


def quote_family():
    result={};all_values={}
    for path in ('src/VaultLib.sol','keeper/policy.py'):
        source=(ROOT/path).read_text();replacements=[];values={}
        if path.endswith('.sol'):
            for key,name in (('journal','Q_JOURNAL'),('journal_tail','Q_REQUIRED_TAIL'),('pack','Q_PACK')):
                matches=list(re.finditer(r'\b'+name+r'\s*=\s*([0-9_]+)\s*;',source))
                if len(matches)!=1:raise RuntimeError('ambiguous allowed quote constant '+name)
                m=matches[0];values[key]=int(m.group(1).replace('_',''));replacements.append((m.start(1),m.end(1),'<'+key+'>'))
        else:
            tree=ast.parse(source);call=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='Q' for t in n.targets))
            offsets=[];total=0
            for line in source.splitlines(keepends=True):offsets.append(total);total+=len(line)
            for key in QUOTE_RANGES:
                value=next(k.value for k in call.keywords if k.arg==key)
                if not isinstance(value,ast.Constant) or not isinstance(value.value,int):raise RuntimeError('nonliteral allowed policy quote')
                values[key]=value.value;replacements.append((offsets[value.lineno-1]+value.col_offset,offsets[value.end_lineno-1]+value.end_col_offset,'<'+key+'>'))
        for a,b,token in sorted(replacements,reverse=True):source=source[:a]+token+source[b:]
        result[path]=hashlib.sha256(source.encode()).hexdigest();all_values[path]=values
    if all_values['src/VaultLib.sol']!=all_values['keeper/policy.py']:raise RuntimeError('Solidity/Python allowed quotes differ')
    for key,value in all_values['src/VaultLib.sol'].items():
        lo,hi=QUOTE_RANGES[key]
        if not lo<=value<=hi:raise RuntimeError('quote outside bounded candidate family: '+key)
    return dict(normalized_source_sha256=result,values=all_values['src/VaultLib.sol'])


def prepare():
    values = json.loads((ROOT/'deploy/mainnet.json').read_text())
    values.update(owner=ACTORS['owner'], tvlCapWei=10*E, distributionBps=5000)
    return dict(name='efficient-journal-refunds-and-q360-full-holder', status='PREPARED; NOT APPROVED',
        authority='New explicit owner approval required for this exact plan hash. Prior77transaction batch is complete and grants no authority here.',
        endpoint=RPC, preserve_existing_endpoint='http://127.0.0.1:8557', fork_rpc=FORK_RPC,
        fork_block=FORK_BLOCK, expected_fork_hash='0x6bd9b2b1b4f8a69f234bdaf92fe78650113485f168e8a134890ef75f7bfae0e2', chain_id=1, actors=ACTORS, initial_funding_by_role_wei=FUNDING,
        initial_funding_total_wei=sum(FUNDING.values()), topups=0,
        maximum_broadcast_transactions=540, repair_allowance_transactions_included=20,
        maximum_aggregate_external_transaction_value_wei=32*E,
        maximum_simultaneous_acquisition_input_wei=15*E//10,expected_selection_timeout_blocks=30,maximum_deadline_mined_empty_blocks=(19+9)*31,
        per_transaction_gas_limit=MAX_GAS, runtime_code_limit=MAX_CODE,
        candidate_family=quote_family(),candidate_quote_ranges=QUOTE_RANGES,one_candidate_only=True,
        phase_profiles=dict(baseline=dict(positions=40,deposit_wei=4*E,counts=COUNTS,distribution_prices=[200000000,500000000],full_holder=True,restock_inventory_paths=True),candidate=dict(positions=1,deposit_wei=8*E//10,counts=CANDIDATE_COUNTS,distribution_prices=[500000000],full_holder=False,restock_inventory_paths=False)),
        candidate_rule='ONE separately frozen reviewed quote-only candidate after baseline bills/focused checks. Only Lib/Python literal journal22000..30000, journal_tail85000..160000, optional pack285000..325000; exact mirrors. Q_PACK decrease requires all6 baseline inventory/fee receipts, no automatic selection. Other production/client/config/dependency files unchanged. Existing test-policy source may change only with exactly identical PolicyGreedy artifact.',
        values=values, source_sha256={p:digest(ROOT/p) for p in SOURCE_PATHS},artifact_templates_sha256=artifact_templates(),
        tool_versions={name:raw(name,'--version') for name in ('forge','cast','anvil')},ordinary_keeper_defaults=dict(fail_rate_bps=0,min_return_bps=0,max_loss_wei=0,maximum_index_passes_per_case=16),
        required_source_api='sync(uint256[],uint256,uint256); matched active fee witness; autonomous128journal, independent16own/terminal/prune; no caller cursor/prefix overrides',
        source_freeze_note='Reprepare after final source/compiled artifacts are warm. Approve only that exact hash; this script refuses changed files.',
        fee_contexts=[dict(basefee_wei=150000000,effective_price_wei=200000000),
                      dict(basefee_wei=450000000,effective_price_wei=500000000),
                      dict(basefee_wei=1950000000,effective_price_wei=2000000000,scope='essential full-holder checkpoint only')],
        phase_limits=dict(baseline=321,candidate=199,total_planned_max=520,included_repair_max=20,hard_max=540),
        repair_rule='Stop on mismatch. Preserve all receipts, node, nonces and cumulative counters. Up to20repairs inside540 require root reconciliation and remain same targets/signers/funding/bounded quote family; no blind restart/reset/topup or second candidate.',
        phases=[
          'Start a fresh exclusively owned Anvil at 8559, accounts 0, Tenderly fork 26418539, normal code/gas limits. Before any funding assert all six actors have code 0x, nonce 0 and balance 0. Fund each once at the exact allocation; preserve 8557 untouched.',
          'Baseline: normal script/deploy.sh linked deployment, mainnet values except 10 ETH test TVL/distribution 5000/fresh owner. Deposit 4 ETH+live charge and price it. Optional 6 actual stock cases:1 new-mint pack,1 leftover pack,2 packs with 4 old + 10 fresh Shapes, at 0.2/0.5 gwei. Economic unreachability means no transaction and forbids lowering Q_PACK. Restore stock branch, then construct 40 genuine Active three-Shape positions.',
          'Each phase creates 128 genuine FWA requests once, chunks<=16 and concurrent input<=1.5 ETH. Assert actual 30 block deadlines; mine only to those deadlines at 12 seconds/block; processAcquisitions(16), withdraw actual refunds and prove terminal statuses3/4.',
          'Capture natural prefix snapshots, no cursor or protocol-state overrides. Baseline counts1,2,3,7,15,16,17,31,32,33,63,64,65,127,128; candidate counts1,16,32,64,128. Measure descending snapshots.',
          'At counts 1 and 32 with distribution enabled but no holder flows: actual no-gain offer must be 0 and ordinary keeper must omit sync; no transaction. One actual 1 ETH owner transfer per prefix creates a documented qualifying gain. Measure distribution-only tails under V1 and 1000 bps+PolicyGreedy. Baseline both 0.2/0.5 gwei, candidate 0.5 gwei. Revert gain before holder cases. These transfers are fixture gains, never recurring funding or mint revenue.',
          'Queue a real half-redemption once per natural prefix, before pricing. Existing unencumbered cash funds journal; request-pool ETH stays protected. At next eligible blackout/drained FWA queue measure autonomous sync([],matchedWitness,0) under V1 and actual PolicyGreedy+1000bps, at 0.2/0.5 gwei. Routine classification must pay despite locked shares and zero essential budget.',
          'Use ordinary keeper CLI without --send for real policy.plan first calldata/witness. Use production TxManager.preflight, shared profitability_gate, default fail_rate 0/min_return 0/max_loss 0 and billed-ratio model, then exact 80 percent minPay signed preflight. Record accepted/declined economics; authorized operator minPay 0 measurement does not establish normal keeper willingness.',
          'Baseline full holder: restore pre-request state, queue half-redemption and execute a genuine partial checkpoint. Assert >1 ETH redemption reserve and remaining locked shares. One actual 1 ETH owner gain plus second-holder 1 ETH deposit enable simultaneous remainder redemption, gain distribution and new deposit pricing. Obtain 3 standalone Q360 checkpoint receipts at 0.2/0.5/essential 2 gwei, actual claims, all protected/native getters and live custody/principal checks. Do not repeat unchanged Q360 full-holder in candidate phase.',
          'Archive receipts/getters/counters before restoring each entry snapshot. Verify all six balances/nonces/code, head, automine and empty pool; preserve node 8559. Baseline ends here for root bill review and focused tests; never automatically select or deploy candidate quotes.',
          'Candidate is ONE fresh normal deployment with 1 position/.8 ETH. Reuse exact baseline PID/entry snapshot, actors and persistent cumulative counters; never fund again. Only mirrored literal Q_JOURNAL 22k..30k, Q_REQUIRED_TAIL 85k..160k and conditionally Q_PACK 285k..325k may differ. All other production/client/config/dependency inputs stay frozen. Require separately reviewed exact candidate source/artifact descriptor before executing this phase.'
        ],
        successful_foreign_route=dict(status='BLOCKED for exposed paid production-vault measurement; no workaround authorized',
          candidate_fork=26099368, next_sequence=49187,last_issued=50072,
          actual_unsettled=886,actual_pending_vrf=61,already_authentic_cached=825,
          first128_historical_final_status=2,
          evidence='Read-only publicTenderly historical getters plus recorded AcquisitionRequested/RandomnessCached/AcquisitionProcessed database chronology.',
          actual_fwa_runtime_sha256='20d0ec8fcea735357da6487d821e678a93232f4e867161682e21fadd36c2ba8e',
          same_runtime_at_candidate_and_standard_fork=True,
          verified_source_provenance='/Users/dd/CascadeProjects/punk-or-bust/refs/fwa-v2/provenance.json (Sourcify runtime/creation match; compiler template includes immutable placeholders, so raw artifact-byte equality is not claimed)',
          reason='unsettled increments on request and decrements only in_finishAcquisition; cachedReady remains unsettled. PackVault.list rejects nonzero unsettled; unexposed sync/admission/checkpoint rebase unpaid. Deploy-after-request cannot acquire a genuine book exposure before processing the queued prefix.',
          forbidden=['fake book membership or protocol approvals/state/balance','persist old FWA/Shapes/Packs acrossforks','set blockhash or supply fabricated successful VRF output','impersonate coordinator and call rawFulfill directly','weaken production admission merely to admit the test'],
          alternatives=[
            'Keep paid successful-foreign billed receipt gap explicit; measure real refunds/new job boundaries and standalone Q360 holder now.',
            'Separate capped public canary with actual live VRF fulfillment, requiring new public-chain authority and real-funds limits.',
            'Separately authorized real-coordinator test-key/configuration experiment, requiring extra named administrative actors and valid cryptographic proofs; changed external configuration means it does not validate current production key/timing.'
          ]),
        things_that_do_not_make_sense=[
          'A real cached128-successful backlog exists, but a fresh production vault cannot acquire exposure while that queue is outstanding; claiming its unpaid rebase as paid journal calibration would test the wrong branch.',
          'Full-holder donation1ETH is a one-off gain fixture. It must not be called minted revenue, recurring operating income or a funding solution.',
          'Actual estimates and25percent signed limits answer gas feasibility; billed receipts and fixed pay answer keeper profit. These are separate checks.'
        ])


class LocalBatch:
    def __init__(self, plan, work, candidate=None, baseline=None):
        self.plan, self.work = plan, work
        self.phase='candidate' if candidate else 'baseline'
        self.profile=plan['phase_profiles'][self.phase]
        self.phase_freeze=candidate or plan
        self.baseline=baseline
        self.global_path=Path(baseline['global_ledger']) if baseline else work/'global-ledger.json'
        self.pid = None
        self.vault = None
        self.greedy_policy = None
        self.actions = []
        self.broadcasts = self.external_value = 0
        if baseline:
            global_state=json.loads(self.global_path.read_text())
            if global_state['phase']!='baseline_complete':raise RuntimeError('baseline not complete or candidate already started')
            self.broadcasts=global_state['broadcasts'];self.external_value=global_state['external_value_wei']
        self.state = dict(status='starting',base_revision=raw('git','rev-parse','HEAD'),started_at_unix=time.time(),plan_sha256=digest(PLAN),actions=self.actions,
                          broadcasts=self.broadcasts,external_value_wei=self.external_value,phase=self.phase,global_ledger=str(self.global_path),
                          phase_source_sha256=self.phase_freeze['source_sha256'],phase_artifact_templates_sha256=self.phase_freeze['artifact_templates_sha256'])
        if baseline:
            self.state.update(pid=baseline['pid'],fork_hash=baseline['fork_hash'],funded=baseline['funded'],entry_head=baseline['entry_head'],entry_actors=baseline['entry_actors'],baseline_results_sha256=digest(Path(baseline['_path'])))

    def cast(self, *args):
        return raw('cast', *args, '--rpc-url', RPC)

    def rpc(self, method, *params):
        return json.loads(self.cast('rpc', method, *[json.dumps(p) if not isinstance(p,str) else p for p in params]))

    def save(self):
        self.state.update(broadcasts=self.broadcasts,external_value_wei=self.external_value,elapsed_wall_seconds=time.time()-self.state['started_at_unix'])
        self.global_path.write_text(json.dumps(dict(phase=self.state.get('global_phase',self.phase+'_running'),broadcasts=self.broadcasts,external_value_wei=self.external_value,pid=self.pid),indent=2)+'\n')
        (self.work/'results.json').write_text(json.dumps(self.state,indent=2)+'\n')

    def freeze(self):
        for path, expected in self.phase_freeze['source_sha256'].items():
            if digest(ROOT/path) != expected: raise RuntimeError('source changed: '+path)
        if artifact_templates()!=self.phase_freeze['artifact_templates_sha256']:raise RuntimeError('compiled artifact templates changed')

    def guard(self):
        self.freeze()
        owners = raw('lsof','-nP','-tiTCP:8559','-sTCP:LISTEN').splitlines()
        if set(owners) != {str(self.pid)}: raise RuntimeError('endpoint ownership changed')
        if num(self.rpc('eth_chainId')) != 1 or 'anvil' not in self.rpc('web3_clientVersion').lower():
            raise RuntimeError('unexpected node/chain')
        fork = self.rpc('anvil_nodeInfo')['forkConfig']
        if num(fork['forkBlockNumber']) != FORK_BLOCK or fork['forkUrl'].rstrip('/') != FORK_RPC:
            raise RuntimeError('unexpected fork boundary')
        if self.rpc('eth_getBlockByNumber',hex(FORK_BLOCK),False)['hash'] != self.state['fork_hash'] or self.state['fork_hash'] != self.plan['expected_fork_hash']:
            raise RuntimeError('fork hash changed')

    def inclusion(self):
        parent = self.rpc('eth_getBlockByNumber','latest',False)
        pending = self.rpc('eth_getBlockByNumber','pending',False)
        base = txm.next_base_fee(parent)
        if num(pending['number']) != num(parent['number'])+1 or pending['parentHash'] != parent['hash'] or num(pending['baseFeePerGas']) != base:
            raise RuntimeError('pending inclusion context changed')
        executed = num(self.rpc('eth_call',dict(data='0x485f5260205ff3',gas=hex(100000),
                    maxFeePerGas=hex(2*base+50000000),maxPriorityFeePerGas=hex(50000000),**{'from':'0x'+'00'*20}),'pending'))
        if executed != base: raise RuntimeError('executed BASEFEE differs from next header')
        return base, ['--gas-price',str(2*base+50000000),'--priority-gas-price','50000000']

    def fee(self, price):
        self.guard()
        base = price-50000000
        parent = base*8//7
        if parent-parent//8 != base: raise RuntimeError('unrepresentable deterministic fee parent')
        self.rpc('anvil_setNextBlockBaseFeePerGas',hex(parent));self.rpc('evm_mine')
        if self.inclusion()[0] != base: raise RuntimeError('fee setup failed')

    def call(self,to,sig,*args,pending=False):
        extra = ['--block','pending',*self.inclusion()[1]] if pending else []
        return self.cast('call',to,sig,*args,*extra)

    def value(self,sig,*args,to=None,pending=False):
        return num(self.call(to or self.vault,sig,*args,pending=pending))

    def reserve(self,n,value):
        if self.broadcasts+n > 540 or self.external_value+value > 32*E:
            raise RuntimeError('aggregate transaction/value approval would be exceeded')
        self.broadcasts += n;self.external_value += value;self.save()

    def send(self,role,to,sig=None,args=(),value=0,label=None,measure=False,ordinary=True):
        self.guard();sender=ACTORS[role]
        if self.cast('code',sender) != '0x' or self.cast('code',to) == '0x':
            raise RuntimeError('sender or target code changed')
        base, fees=self.inclusion();nonce=num(self.cast('nonce',sender))
        calldata=raw('cast','calldata',sig,*args) if sig else '0x'
        common=[to,*([sig,*args] if sig else []),'--from',sender,'--value',str(value),*fees]
        estimate=num(self.cast('estimate',*common,'--block','pending'))
        limit=(estimate*5+3)//4
        if limit>MAX_GAS:raise RuntimeError('exact estimate plus25percent exceeds EIP7825')
        sender_before=num(self.cast('balance',sender))
        if sender_before<value+limit*(2*base+50000000):
            raise RuntimeError('named actor lacks approved initial funding; no topup')
        offer=None;ordinary_cost=None;signed_keeper_estimate=None
        if measure:
            result=self.cast('call',*common,'--block','pending')
            offer=num(result)
            operation=sig.split('(')[0]
            ratio=keeper_client.billed_ratio(None,operation)
            ordinary_cost,ordinary_need,ordinary_accepted=keeper_client.profitability_gate(estimate,base+50000000,offer,0,0,0,ratio)
            signed_args=(*args[:-1],offer*8//10)
            signed_common=[to,sig,*signed_args,'--from',sender,'--value',str(value),*fees]
            dispatch=self.ordinary_dispatch(sig,args) if ordinary else dict(required=False,reason='controlled operator inventory/setup fixture, not ordinary batch-size selection')
            tm=txm.TxManager(RPC,str(self.work/('preflight-'+str(len(self.actions))+'.json')),sender,[])
            try:
                checked,reason,expected=tm.preflight(to,[sig,*args],fees)
                signed_keeper_estimate,signed_reason,signed_expected=tm.preflight(to,[sig,*signed_args],fees)
            finally:tm._lockf.close()
            if checked is None or signed_keeper_estimate is None:
                raise RuntimeError('ordinary keeper exact preflight rejected: '+str((reason,signed_reason)))
            if checked!=estimate:raise RuntimeError('ordinary keeper estimate differs from exact operator estimate')
        self.reserve(1,value)
        receipt=json.loads(self.cast('send',*common,'--nonce',str(nonce),'--unlocked','--gas-limit',str(limit),'--json'))
        sender_after=num(self.cast('balance',sender));actual_cost=num(receipt['gasUsed'])*num(receipt['effectiveGasPrice'])
        row=dict(sender_native_before_wei=sender_before,sender_native_after_wei=sender_after,native_received_during_call_wei=sender_after-sender_before+value+actual_cost,actual_cost_wei=actual_cost,label=label or sig,sender=sender,to=to,function=sig or 'receive()',arguments=list(args),calldata=calldata,value_wei=value,
                 estimate=estimate,gas_limit=limit,pending_basefee_wei=base,ordinary_keeper_offer_wei=offer,
                 ordinary_keeper_dispatch=dispatch if measure else None,ordinary_keeper_shared_gate_accepted=ordinary_accepted if measure else None,ordinary_keeper_shared_gate_need_wei=ordinary_need if measure else None,ordinary_keeper_default_ratio_cost_wei=ordinary_cost,ordinary_keeper_default_ratio_net_wei=offer-ordinary_cost if offer is not None else None,
                 ordinary_keeper_conservative_estimate_net_wei=offer-estimate*(base+50000000) if offer is not None else None,
                 ordinary_keeper_signed_minPay=offer*8//10 if offer is not None else None,ordinary_keeper_exact_signed_estimate=signed_keeper_estimate,
                 operator_measurement_minPay=0 if measure else None,receipt=receipt)
        self.actions.append(row);self.save()
        if num(receipt['status'])!=1 or num(self.cast('nonce',sender))!=nonce+1:
            raise RuntimeError('receipt/nonce mismatch; preserve and stop')
        if measure:
            block=self.rpc('eth_getBlockByHash',receipt['blockHash'],True)
            if len(block['transactions'])!=1 or block['transactions'][0]['hash']!=receipt['transactionHash']:raise RuntimeError('receipt block is not isolated')
            if num(block['baseFeePerGas']) != base or num(receipt['effectiveGasPrice'])!=base+50000000:
                raise RuntimeError('receipt fee context differs from authenticated preflight')
            paid=sum(int(l['data'],16) for l in receipt['logs'] if l.get('topics') and l['topics'][0].lower()==txm.KEEPER_PAID and l['address'].lower()==self.vault.lower())
            row.update(billed_gas=num(receipt['gasUsed']),keeper_paid_wei=paid,actual_cost_wei=num(receipt['gasUsed'])*num(receipt['effectiveGasPrice']),transaction=block['transactions'][0])
            if paid != offer:raise RuntimeError('fixed keeper offer changed at inclusion')
            if row['native_received_during_call_wei']!=paid:raise RuntimeError('actual caller native inflow differs from KeeperPaid')
            self.save()
            print(json.dumps({k:row[k] for k in ('label','estimate','billed_gas','keeper_paid_wei','actual_cost_wei')}),flush=True)
        return row

    def ordinary_dispatch(self,sig,args,absent=False):
        case=str(len(self.actions))
        command=['python3','keeper/keeper.py',self.vault,'--rpc',RPC,'--from',ACTORS['keeper'],
                 '--state',str(self.work/('keeper-dry-'+case+'.json')),
                 '--index',str(self.work/('keeper-dry-'+case+'.sqlite')),
                 '--max-steps','1','--max-loss-wei','0','--fail-rate-bps','0','--min-return-bps','0']
        attempts=[]
        for _ in range(16):
            result=subprocess.run(command,cwd=ROOT,text=True,capture_output=True)
            out=result.stdout+result.stderr;attempts.append(dict(exit_status=result.returncode,output=out))
            lines=[line for line in out.splitlines() if line.startswith('cast send '+self.vault+' ')]
            if absent and not result.returncode and not any(marker in out for marker in ('event index at block','return/selection replay at block')):
                parsed=[shlex.split(line)[3:] for line in lines]
                if any(parts and parts[0].split('(')[0]=='sync' for parts in parsed):raise RuntimeError('ordinary keeper chose sync for no-gain zero-pay tail')
                record=dict(command=command,attempts=attempts,sync_absent=True,all_planned=parsed)
                self.state.setdefault('ordinary_dispatches',[]).append(record);self.save();return record
            if lines:
                selected=shlex.split(lines[0])[3:]
                actual=raw('cast','calldata',*selected)
                expected=raw('cast','calldata',sig,*args)
                record=dict(command=command,attempts=attempts,selected=selected,selected_calldata=actual,expected_calldata=expected,matches=actual==expected)
                self.state.setdefault('ordinary_dispatches',[]).append(record);self.save()
                if not record['matches']:raise RuntimeError('ordinary policy.plan chose different first work: '+str(selected))
                return record
            if result.returncode or not any(marker in out for marker in ('INDEX_CATCHUP','event index at block','return/selection replay at block')):
                break
        self.state.setdefault('ordinary_dispatches',[]).append(dict(command=command,attempts=attempts,matches=False));self.save()
        raise RuntimeError('ordinary keeper did not dispatch expected work after bounded index catchup')

    def deploy_greedy(self):
        self.guard();artifact=json.loads((ROOT/'out/ForkKeeperPolicy.t.sol/PolicyGreedy.json').read_text())
        creation=artifact['bytecode']['object'];runtime=artifact['deployedBytecode']['object']
        if not creation.startswith('0x'):creation='0x'+creation
        if not runtime.startswith('0x'):runtime='0x'+runtime
        sender=ACTORS['deployer'];base,fees=self.inclusion();nonce=num(self.cast('nonce',sender))
        estimate=num(raw('cast','estimate','--from',sender,*fees,'--block','pending','--rpc-url',RPC,'--create',creation))
        limit=(estimate*5+3)//4
        if limit>MAX_GAS:raise RuntimeError('test-policy creation exceeds normal gas bounds')
        self.reserve(1,0)
        receipt=json.loads(raw('cast','send','--from',sender,'--unlocked','--nonce',str(nonce),'--gas-limit',str(limit),*fees,'--json','--rpc-url',RPC,'--create',creation))
        if num(receipt['status'])!=1 or num(self.cast('nonce',sender))!=nonce+1:raise RuntimeError('test-policy creation failed')
        self.greedy_policy=receipt['contractAddress'];actual=self.cast('code',self.greedy_policy)
        if actual.lower()!=runtime.lower() or (len(actual)-2)//2>MAX_CODE:raise RuntimeError('test-policy runtime/artifact mismatch')
        self.actions.append(dict(label='existing owner-replaceable PolicyGreedy test role CREATE',estimate=estimate,gas_limit=limit,receipt=receipt,address=self.greedy_policy,runtime_sha256=hashlib.sha256(bytes.fromhex(actual[2:])).hexdigest()))
        self.state['test_policy_greedy']=self.greedy_policy;self.save()

    def snapshot(self):return self.rpc('evm_snapshot')
    def restore(self,snap):
        self.guard()
        if not self.rpc('evm_revert',snap):raise RuntimeError('snapshot restoration failed')
        return self.snapshot()

    def warp(self,offset):
        self.guard();now=num(self.rpc('eth_getBlockByNumber','latest',False)['timestamp'])
        nxt=now-now%43200+offset
        if nxt<=now:nxt+=43200
        self.rpc('evm_setNextBlockTimestamp',str(nxt));self.rpc('evm_mine')

    def getters(self,full=False):
        scalar=['totalShares','lastNav','pendingDepositTotal','redemptionReserve','lockedShares','distributionReserve','claimableTotal','processingPool','acquisitionCursor','pendingReceipts','reservedCount','idlePackCount','looseShapeCount','openListingCount','idleEth','freeEth','highWaterMark']
        result={k:self.value(k+'()(uint256)') for k in scalar}
        result['balance']=num(self.cast('balance',self.vault))
        result['protected_total']=sum(result[k] for k in ('pendingDepositTotal','redemptionReserve','distributionReserve','claimableTotal','processingPool'))
        if result['balance']<result['protected_total']:raise RuntimeError('actual ETH below protected liabilities')
        result['free_wei']=result['balance']-result['protected_total']
        if result['freeEth']!=result['free_wei']:raise RuntimeError('public free ETH does not match protected bucket arithmetic')
        result['holders']={role:dict(balance=num(self.cast('balance',ACTORS[role])),shares=self.value('shareBalance(address)(uint256)',ACTORS[role]),claimable=self.value('claimableEth(address)(uint256)',ACTORS[role])) for role in ('holder','holder2','keeper')}
        result['totals']=self.call(self.vault,'totals()(uint256,uint256,uint256,uint256,uint256,uint256)')
        result['budget']=[num(v) for v in self.call(self.vault,'budget()(uint256,uint256)').splitlines()]
        if full:
            fwa=self.plan['values']['fwa'];packs=self.plan['values']['packs']
            result['fwa_fee_credit_wei']=self.value('feeCredit(address)(uint256)',self.vault,to=fwa)
            rewards=self.call(fwa,'rewards()(address)');token=self.call(fwa,'token()(address)')
            result['fwa_token_balance']=self.value('balanceOf(address)(uint256)',self.vault,to=token)
            result['fwa_token_credit']=self.value('tokenCredit(address)(uint256)',self.vault,to=rewards)
            result['positions']=[]
            for i in range(result['openListingCount']):
                id_=self.value('openListingAt(uint256)(uint256)',i)
                position=[num(v) for v in self.call(self.vault,'position(uint256)(uint256,uint256,uint256,uint256,uint64,uint8)',id_).splitlines()]
                listing=self.call(fwa,'listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)',id_).splitlines()
                pack_value=self.value('valueOf(uint256)(uint256)',position[0],to=packs)
                custody=self.call(packs,'ownerOf(uint256)(address)',position[0])
                if listing[1].lower()!=self.vault.lower() or num(listing[-1])!=1 or custody.lower()!=fwa.lower():raise RuntimeError('independent live Active listing custody mismatch')
                if pack_value!=position[1] or num(listing[5])!=position[2]:raise RuntimeError('independent pack/backing principal mismatch')
                result['positions'].append(dict(id=id_,book=position,live_listing=listing,actual_pack_value=pack_value,actual_pack_owner=custody,pending_fee_wei=self.value('pendingFees(uint256)(uint256)',id_,to=fwa)))
            if len(result['positions'])!=self.profile['positions'] or sum(p['actual_pack_value'] for p in result['positions'])!=self.profile['positions']*3*10**16:raise RuntimeError('absolute actual pack principal fixture changed')
            result['accounted_nav_wei']=self.value('accountedNav(uint256)(uint256)',self.witness())
        return result

    def params(self):
        return [num(x.strip()) for x in self.call(self.vault,'getParams()('+PARAMS+')').strip('()').split(',')]

    def markup(self,bps):
        p=self.params();p[3]=bps
        self.send('owner',self.vault,'setParams('+PARAMS+')',( '('+','.join(map(str,p))+')',),label='isolated markup branch '+str(bps))

    def quote(self,count,build=False):
        edge=self.call(self.vault,'edge(uint256)(uint256,uint256,bool)',3,pending=True).splitlines()
        k,target=num(edge[0]),num(edge[1])
        if edge[2]!='true':raise RuntimeError('real live backing economics reject this fixture')
        p=self.params();base,_=self.inclusion();s=SimpleNamespace(k=k,base_fee=base,max_tip=p[9],gas_ceiling=p[7],markup_bps=p[3],work_fee=p[10])
        fee=self.value('ownerSettlementFeeBps()(uint256)',to=self.plan['values']['fwa']);discount=self.value('settlementDiscountBps()(uint256)',to=self.plan['values']['fwa'])
        up=lambda a,b:(a+b-1)//b
        minimum=max(up(3*10**16*10000,9500),up(3*10**16*10000,10000-fee),up(3*10**16*10000,discount),up(3*10**16*E,k-fee*10**14))
        cycle=policy.quote(s,policy.CYCLE_GAS,2)
        buildcost=policy.quote(s,policy.Q['pack']+policy.Q['mint']*3//10+policy.Q['listed'],2)+self.value('mintFee()(uint256)',to=self.plan['values']['shapes'])*3//10
        minimum=max(minimum,up((cycle+(buildcost if build else 1))*E,k-E))
        packs=self.plan['values']['packs'];maximum=2**256-1
        if self.call(self.plan['values']['fwa'],'oracleExemptCollections(address)(bool)',packs)!='true':
            oracle=self.call(self.plan['values']['fwa'],'floorOracle()(address)')
            ask=num(self.call(oracle,'getFloorRange(address)(uint256,uint256,uint48,uint48)',packs).splitlines()[1]);premium=self.value('oracleCeilingPremiumBps()(uint256)',to=self.plan['values']['fwa'])
            maximum=ask*(10000+premium)//10000*(10000-p[1])//10000
        proposals=policy.propose_backings(target,self.value('reservedCount()(uint256)'),1 if build else count,
                lambda b:bool(self.value('idForBacking(uint256)(uint256)',b)),minimum,maximum)
        if build:proposals*=count
        if len(proposals)!=count:raise RuntimeError('complete economically admissible proposals unavailable')
        return array(proposals)

    def start(self):
        with socket.socket() as s:s.bind(('127.0.0.1',8559))
        command=['anvil','--host','127.0.0.1','--port','8559','--accounts','0','--silent','--fork-url',FORK_RPC,'--fork-block-number',str(FORK_BLOCK),'--fork-retry-backoff','5000','--retries','30','--base-fee','150000000','--code-size-limit',str(MAX_CODE),'--gas-limit',str(MAX_GAS),'--enable-tx-gas-limit']
        log=open(self.work/'anvil.log','w');proc=subprocess.Popen(command,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);self.pid=proc.pid
        for _ in range(150):
            if proc.poll() is not None:raise RuntimeError('owned node exited')
            try:
                header=self.rpc('eth_getBlockByNumber',hex(FORK_BLOCK),False)
                if header:break
            except (RuntimeError,json.JSONDecodeError):pass
            time.sleep(.2)
        else:raise RuntimeError('owned node startup timed out')
        self.state.update(pid=self.pid,node_command=command,fork_hash=header['hash']);self.guard()
        if self.value('selectionTimeoutBlocks()(uint256)',to=self.plan['values']['fwa'])!=30:raise RuntimeError('fork selection deadline differs from approved30blocks')
        if self.rpc('anvil_getAutomine') is not True or self.rpc('txpool_status')!={'pending':'0x0','queued':'0x0'}:raise RuntimeError('fresh node automine/pool mismatch')
        before={role:dict(address=a,code=self.cast('code',a),nonce=num(self.cast('nonce',a)),balance=num(self.cast('balance',a))) for role,a in ACTORS.items()}
        if any(r['code']!='0x' or r['nonce'] or r['balance'] for r in before.values()):raise RuntimeError('actor not clean before funding')
        self.state['actors_clean_before_funding']=before;self.state['funded']={};self.save()
        for role,a in ACTORS.items():
            self.rpc('anvil_impersonateAccount',a);self.rpc('anvil_setBalance',a,hex(FUNDING[role]))
            if num(self.cast('balance',a))!=FUNDING[role]:raise RuntimeError('one-time funding readback mismatch')
            self.state['funded'][role]=FUNDING[role];self.save()
        log.close()

    def deploy(self):
        self.guard();self.reserve(3,self.plan['values']['seedWei'])
        path=ROOT/'deploy/rehearse-efficient-journal.json'
        if path.exists():raise RuntimeError('temporary deployment values already exist')
        path.write_text(json.dumps(self.plan['values'],indent=2)+'\n')
        try:
            env={**os.environ,'RPC_URL':RPC,'I_AM_THE_OWNER':'yes','FORGE_WALLET_ARGS':'--unlocked --sender '+ACTORS['deployer'],'FOUNDRY_GAS_LIMIT':str(MAX_GAS)}
            env.pop('FOUNDRY_CODE_SIZE_LIMIT',None)
            result=subprocess.run(['script/deploy.sh',str(path.relative_to(ROOT)),'--broadcast'],cwd=ROOT,env=env,text=True,capture_output=True)
            self.state['deployment_output']=result.stdout+result.stderr;self.save()
            if result.returncode:raise RuntimeError('normal production deployment failed; preserve receipts before any retry')
        finally:path.unlink()
        run=json.loads((ROOT/'broadcast/Deploy.s.sol/1/run-latest.json').read_text());self.state['deployment']=run
        if len(run['transactions'])>3:raise RuntimeError('more than reserved3deployments')
        self.broadcasts-=3-len(run['transactions'])
        for t in run['transactions']:
            rec=self.rpc('eth_getTransactionReceipt',t['hash'])
            if not rec or num(rec['status'])!=1 or num(rec['gasUsed'])>MAX_GAS:raise RuntimeError('deployment receipt failed')
            if t.get('contractAddress'):
                if (len(self.cast('code',t['contractAddress']))-2)//2>MAX_CODE:raise RuntimeError('deployed code exceeds EIP170')
        self.state['deployed_runtimes']=[]
        for reference in run.get('libraries',[]):
            source,name,address=reference.rsplit(':',2)
            code=bytes.fromhex(self.cast('code',address)[2:])
            artifact=json.loads((ROOT/'out'/Path(source).name/(name+'.json')).read_text())['deployedBytecode']
            compiled=bytearray.fromhex(artifact['object'].removeprefix('0x'));actual=bytearray(code)
            for refs in artifact.get('immutableReferences',{}).values():
                for offset in refs:
                    start,length=offset['start'],offset['length'];actual[start:start+length]=compiled[start:start+length]=bytes(length)
            if actual!=compiled or len(code)>MAX_CODE:raise RuntimeError('linked library differs from frozen artifact')
            self.state['deployed_runtimes'].append(dict(name=name,address=address,runtime_bytes=len(code),runtime_sha256=hashlib.sha256(code).hexdigest(),artifact_match=True))
        self.vault=next(t['contractAddress'] for t in run['transactions'] if t.get('contractName')=='PackVault')
        if self.call(self.vault,'owner()(address)').lower()!=ACTORS['owner'].lower():raise RuntimeError('deployment owner mismatch')
        self.state['vault']=self.vault
        for t in run['transactions']:
            if t.get('contractAddress'):
                code=bytes.fromhex(self.cast('code',t['contractAddress'])[2:])
                self.state['deployed_runtimes'].append(dict(name=t.get('contractName'),address=t['contractAddress'],runtime_bytes=len(code),runtime_sha256=hashlib.sha256(code).hexdigest(),receipt=self.rpc('eth_getTransactionReceipt',t['hash'])))
        self.save();self.freeze()

    def refund_chunk(self,count):
        self.warp(60);first=self.value('lastIssuedSequence()(uint64)',to=self.plan['values']['fwa'])+1;escrow=0;deadline=0
        for i in range(count):
            price=num(self.call(self.plan['values']['fwa'],'quoteAcquisitionPrice()(uint256,uint256,uint256)',pending=True).splitlines()[2]);escrow+=price
            if escrow>15*E//10:raise RuntimeError('approved simultaneous acquisition input exceeded')
            sent=self.send('kicker',self.plan['values']['fwa'],'acquire(address,uint256,uint256,uint256,uint256)',(ACTORS['kicker'],1,0,0,10000),price)
            request=self.value('requestIdAtSequence(uint64)(uint256)',first+i,to=self.plan['values']['fwa'])
            meta=self.call(self.plan['values']['fwa'],'acquisitionMeta(uint256)(uint64,uint64,uint64,uint16,uint16,uint256)',request).splitlines();deadline=max(deadline,num(meta[1]))
            if num(meta[1])!=num(sent['receipt']['blockNumber'])+30:raise RuntimeError('actual snapshotted deadline differs from approved context')
            self.state.setdefault('foreign_requests',[]).append(dict(sequence=first+i,request_id=request,word_deadline_block=num(meta[1]),input_wei=price));self.save()
        now=num(self.cast('block-number'));needed=max(0,deadline+1-now)
        if needed>31:raise RuntimeError('actual request deadline exceeds approved30block context')
        self.state['deadline_mined_blocks']=self.state.get('deadline_mined_blocks',0)+needed
        if self.state['deadline_mined_blocks']>(19 if self.phase=='baseline' else 9)*31:raise RuntimeError('approved empty deadline-mining resource bound exceeded')
        if needed:self.rpc('anvil_mine',hex(needed),hex(12))
        self.send('kicker',self.plan['values']['fwa'],'processAcquisitions(uint256)',(16,))
        for i in range(count):
            request=self.value('requestIdAtSequence(uint64)(uint256)',first+i,to=self.plan['values']['fwa'])
            status=num(self.call(self.plan['values']['fwa'],'acquisitions(uint256)(address,uint256,uint256,uint256,uint8)',request).splitlines()[-1])
            if status not in (3,4):raise RuntimeError('real request not terminal refund/expiry')
        self.send('kicker',self.plan['values']['fwa'],'withdrawAcquisitionRefund()')
        if self.value('unsettledAcquisitionCount()(uint256)',to=self.plan['values']['fwa']):raise RuntimeError('queue not drained')

    def queue_half(self):
        self.fee(200000000)
        half=self.value('shareBalance(address)(uint256)',ACTORS['holder'])//2
        charge=self.value('requestCharge()(uint256)',pending=True)+(half*self.value('lastNav()(uint256)')//self.value('totalShares()(uint256)'))*self.value('unwindCharge()(uint256)',pending=True)//66300000000000000
        self.send('holder',self.vault,'requestRedeem(uint256)',(half,),charge,label='genuine half-redemption queued for checkpoint')
        if not self.value('lockedShares()(uint256)'):raise RuntimeError('real queued redemption absent')
        if self.getters()['free_wei']<=0:raise RuntimeError('journal has no unencumbered native cash')

    def stock_cases(self):
        fresh=self.snapshot();self.state['stock_cases']=[]
        paths=[('one new primary mint',1,0,7),('one from leftovers',1,7,4),('two with four old plus new ten',2,4,8)]
        for label,count,loose_before,loose_after in paths:
            origin=self.snapshot()
            for price in (500000000,200000000):
                origin=self.restore(origin);self.fee(price)
                if self.value('looseShapeCount()(uint256)')!=loose_before:raise RuntimeError('real inventory-path precondition not reached')
                try:proposals=self.quote(count,True)
                except RuntimeError as exc:
                    if str(exc) not in ('real live backing economics reject this fixture','complete economically admissible proposals unavailable'):raise
                    self.state['stock_cases'].append(dict(path=label,price_wei=price,status='economic admission unavailable; no transaction',reason=str(exc)));self.save()
                    if price==200000000:raise RuntimeError('required setup inventory path unavailable at0.2gwei')
                    continue
                before=self.getters()
                row=self.send('keeper',self.vault,'restock(uint256,uint256[],uint256)',(3,proposals,0),label=f'stock/{label}/price{price}',measure=True,ordinary=False)
                after=self.getters();row.update(inventory_before=before,inventory_after=after,path=label,price_wei=price,status='billed')
                if after['looseShapeCount']!=loose_after:raise RuntimeError('real inventory-path result differs')
                self.state['stock_cases'].append(row);self.save()
        self.restore(fresh)

    def matrix(self,snap,count,witness,mode,prices):
        origin=self.restore(snap)
        for markup in (0,1000):
            origin=self.restore(origin)
            if markup:
                self.markup(markup)
                self.send('owner',self.vault,'setPolicy(address)',(self.greedy_policy,),label='maximum envelope uses genuine owner-replaceable policy')
            branch=self.snapshot()
            for price in prices:
                branch=self.restore(branch);self.warp(42360);self.fee(price)
                before=self.getters()
                row=self.send('keeper',self.vault,'sync(uint256[],uint256,uint256)',('[]',witness,0),label=f'{mode} journal{count}/markup{markup}/price{price}',measure=True)
                after=self.getters();row.update(before=before,after=after,records=count,markup=markup,tail_mode=mode)
                if after['acquisitionCursor']-before['acquisitionCursor']!=count:raise RuntimeError('autonomous journal did not process exact natural prefix')
                if mode=='holder' and not after['lockedShares']:raise RuntimeError('pending holder regime lost')
                if mode=='distribution' and (before['lockedShares'] or before['pendingDepositTotal']):raise RuntimeError('distribution-only fixture has holder flows')
                if before['budget'][1] or after['budget'][1] or before['processingPool']!=after['processingPool']:raise RuntimeError('routine classification/protected pool changed')
                if row['keeper_paid_wei']<=0:raise RuntimeError('required journal job not funded')
                self.save()
        return self.restore(origin)

    def distribution_cases(self,snap,count,witness):
        origin=self.restore(snap)
        for price in self.profile['distribution_prices']:
            origin=self.restore(origin);self.warp(42360);self.fee(price)
            state=self.getters()
            if state['lockedShares'] or state['pendingDepositTotal'] or not self.params()[2]:raise RuntimeError('no-flow distribution flag fixture not reached')
            offer=num(self.call(self.vault,'sync(uint256[],uint256,uint256)', '[]',witness,0,pending=True))
            dispatch=self.ordinary_dispatch('sync(uint256[],uint256,uint256)',('[]',witness,0),absent=True)
            if offer!=0:raise RuntimeError('distribution flag without a real qualifying gain paid the tail')
            self.state.setdefault('distribution_no_gain',[]).append(dict(records=count,price_wei=price,offer_wei=offer,keeper_dispatch=dispatch,getters=state,broadcast=False));self.save()
        origin=self.restore(origin)
        self.send('owner',self.vault,value=E,label='one-off actual 1 ETH qualifying distribution-gain fixture')
        gain=self.snapshot();self.matrix(gain,count,witness,'distribution',self.profile['distribution_prices'])
        return self.restore(origin)

    def attach_candidate(self):
        self.pid=self.baseline['pid'];self.guard()
        actual={r:dict(balance=num(self.cast('balance',a)),nonce=num(self.cast('nonce',a)),code=self.cast('code',a)) for r,a in ACTORS.items()}
        if actual!=self.baseline['entry_actors'] or self.rpc('eth_getBlockByNumber','latest',False)['hash']!=self.baseline['entry_head']['hash']:
            raise RuntimeError('candidate must reuse exact restored entry, not new funding or reset')
        for address in ACTORS.values():self.rpc('anvil_impersonateAccount',address)
        self.state['candidate_freeze']=self.phase_freeze;self.save()

    def run(self):
        if self.phase=='baseline':self.start()
        else:self.attach_candidate()
        entry=self.snapshot()
        self.state['entry_head']=self.rpc('eth_getBlockByNumber','latest',False)
        self.state['entry_actors']={r:dict(balance=num(self.cast('balance',a)),nonce=num(self.cast('nonce',a)),code=self.cast('code',a)) for r,a in ACTORS.items()};self.save()
        self.deploy();self.deploy_greedy();self.fee(200000000)
        self.send('holder',self.vault,'deposit()',value=self.profile['deposit_wei']+self.value('requestCharge()(uint256)',pending=True))
        self.warp(42360);self.fee(200000000)
        self.send('keeper',self.vault,'checkpoint(uint256,uint256)',(0,0),label='ordinary first holder pricing',measure=True)
        self.warp(60)
        if self.profile['restock_inventory_paths']:self.stock_cases()
        remaining=self.profile['positions']
        while remaining:
            n=min(10,remaining);self.fee(200000000)
            self.send('keeper',self.vault,'restock(uint256,uint256[],uint256)',(3,self.quote(n,True),0),label='controlled setup restock'+str(n),measure=True,ordinary=False)
            left=n
            while left:
                listed=min(8,left);self.fee(200000000)
                self.send('keeper',self.vault,'list(uint256[],uint256)',(self.quote(listed),0),label='controlled setup listing'+str(listed),measure=True,ordinary=False);left-=listed
            remaining-=n
        if self.value('openListingCount()(uint256)')!=self.profile['positions']:raise RuntimeError('real Active position target not reached')
        base=self.snapshot();begin=self.value('acquisitionCursor()(uint64)');witness=self.witness();snaps={};done=0
        self.state['before_foreign_requests']=self.getters(full=True);self.save()
        for count in self.profile['counts']:
            while done<count:
                chunk=min(16,count-done);self.refund_chunk(chunk);done+=chunk
            if self.value('acquisitionCursor()(uint64)')!=begin or self.value('nextSequenceToProcess()(uint64)',to=self.plan['values']['fwa'])!=begin+count:
                raise RuntimeError('natural external prefix or untouched vault cursor differs')
            snaps[count]=self.snapshot()
        for count in reversed(self.profile['counts']):
            origin=self.restore(snaps[count])
            if count in (1,32):origin=self.distribution_cases(origin,count,witness)
            self.queue_half();holder=self.snapshot()
            self.matrix(holder,count,witness,'holder',(200000000,500000000))
        if self.profile['full_holder']:
            self.restore(base);self.queue_half();self.warp(42360);self.fee(200000000)
            self.send('keeper',self.vault,'checkpoint(uint256,uint256)',(self.witness(),0),label='controlled genuine partial-holder setup',measure=True,ordinary=False)
            if not self.value('lockedShares()(uint256)') or self.value('redemptionReserve()(uint256)')<=E:raise RuntimeError('genuine first partial holder fill absent')
            self.state['partial_holder_getters']=self.getters(full=True);self.save()
            self.warp(60);self.send('owner',self.vault,value=E,label='one-off actual 1 ETH full-holder gain fixture')
            full=self.snapshot()
            for price in (200000000,500000000,2000000000):
                full=self.restore(full);self.fee(price)
                self.send('holder2',self.vault,'deposit()',value=E+self.value('requestCharge()(uint256)',pending=True))
                self.warp(42360);self.fee(price)
                before=self.getters(full=True)
                row=self.send('keeper',self.vault,'checkpoint(uint256,uint256)',(self.witness(),0),label=f'ordinary standalone full-holder checkpoint/price{price}',measure=True)
                after=self.getters(full=True);row.update(before=before,after=after)
                if after['lockedShares'] or after['pendingDepositTotal'] or not after['distributionReserve'] or not after['holders']['holder2']['shares']:raise RuntimeError('full holder paths not all reached')
                if after['redemptionReserve']<=before['redemptionReserve']:raise RuntimeError('remaining redemption not filled')
                self.state.setdefault('full_holder_results',[]).append(row);self.save()
                self.send('holder',self.vault,'claim()');self.state.setdefault('post_claim_getters',[]).append(self.getters(full=True));self.save()
        self.state['status']='measurements_complete';self.save();self.restore(entry)
        restored={r:dict(balance=num(self.cast('balance',a)),nonce=num(self.cast('nonce',a)),code=self.cast('code',a)) for r,a in ACTORS.items()}
        if restored!=self.state['entry_actors'] or self.rpc('eth_getBlockByNumber','latest',False)['hash']!=self.state['entry_head']['hash']:raise RuntimeError('entry restoration mismatch')
        if self.rpc('txpool_status')!={'pending':'0x0','queued':'0x0'} or self.rpc('anvil_getAutomine') is not True:raise RuntimeError('postflight node state mismatch')
        self.state.update(status='passed',global_phase=self.phase+'_complete',entry_restored=True,restored_actors=restored,node_preserved=True);self.save()

    def witness(self):
        count=self.value('openListingCount()(uint256)')
        if not count:return 0
        ids=[self.value('openListingAt(uint256)(uint256)',i) for i in range(count)]
        return min(ids,key=lambda i:num(self.call(self.plan['values']['fwa'],'listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)',i).splitlines()[7]))


def load_baseline(path,approved_hash):
    baseline=json.loads(Path(path).read_text())
    if baseline.get('phase')!='baseline' or baseline.get('status')!='passed' or not baseline.get('entry_restored'):
        raise RuntimeError('candidate needs completed, restored baseline evidence')
    if baseline['plan_sha256']!=approved_hash or digest(PLAN)!=approved_hash:
        raise RuntimeError('candidate does not inherit the exact approved plan')
    global_state=json.loads(Path(baseline['global_ledger']).read_text())
    if global_state['phase']!='baseline_complete' or global_state['broadcasts']!=baseline['broadcasts'] or global_state['external_value_wei']!=baseline['external_value_wei']:
        raise RuntimeError('global ledger changed or candidate already began')
    if baseline['funded']!=FUNDING:raise RuntimeError('initial funding manifest differs')
    if baseline['broadcasts']>540 or baseline['external_value_wei']>32*E:raise RuntimeError('baseline exceeded inherited approval bounds')
    baseline['_path']=str(Path(path).resolve())
    return baseline


def candidate_freeze(plan,baseline):
    family=quote_family()
    if family['normalized_source_sha256']!=plan['candidate_family']['normalized_source_sha256']:
        raise RuntimeError('candidate changes more than the named quote literals')
    current_sources={p:digest(ROOT/p) for p in SOURCE_PATHS}
    for path,expected in plan['source_sha256'].items():
        if path in ('src/VaultLib.sol','keeper/policy.py','test/fork/ForkKeeperPolicy.t.sol'):continue
        if current_sources[path]!=expected:raise RuntimeError('candidate changes forbidden input '+path)
    artifacts=artifact_templates()
    greedy='out/ForkKeeperPolicy.t.sol/PolicyGreedy.json'
    if artifacts[greedy]!=plan['artifact_templates_sha256'][greedy]:raise RuntimeError('candidate changes the named test-policy runtime')
    if family['values']['pack']!=plan['candidate_family']['values']['pack']:
        stock=baseline.get('stock_cases',[])
        if len(stock)!=6 or any(row.get('status')!='billed' for row in stock):
            raise RuntimeError('Q_PACK change lacks all six actual inventory/fee receipts')
    if any(raw(tool,'--version')!=version for tool,version in plan['tool_versions'].items()):
        raise RuntimeError('candidate toolchain differs from approved baseline')
    return dict(approved_plan_sha256=digest(PLAN),baseline_results_sha256=digest(Path(baseline['_path'])),
                source_sha256=current_sources,artifact_templates_sha256=artifacts,candidate_family=family,
                rule='Only the named literal quote family changed; production/keeper logic, ABI, Params, storage, gas limits, fees and funding remain frozen. Root review and focused checks required before executing this descriptor.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    group=parser.add_mutually_exclusive_group()
    group.add_argument('--prepare',action='store_true')
    group.add_argument('--prepare-candidate',action='store_true')
    group.add_argument('--execute-approved-local-batch',action='store_true')
    group.add_argument('--execute-approved-candidate',action='store_true')
    parser.add_argument('--approved-plan-sha256')
    parser.add_argument('--baseline-results')
    parser.add_argument('--candidate-freeze')
    parser.add_argument('--candidate-freeze-sha256')
    args=parser.parse_args()
    if args.prepare:
        prepared=prepare()
        if PLAN.exists():
            previous=json.loads(PLAN.read_text())
            if 'historical_ready_proof' in previous:prepared['historical_ready_proof']=previous['historical_ready_proof']
        PLAN.write_text(json.dumps(prepared,indent=2)+'\n');print('prepared '+str(PLAN)+' sha256='+digest(PLAN));return
    if not (args.execute_approved_local_batch or args.execute_approved_candidate or args.prepare_candidate):
        print(json.dumps(prepare(),indent=2));return
    if not args.approved_plan_sha256 or digest(PLAN)!=args.approved_plan_sha256:
        raise RuntimeError('exact plan hash must match the separately owner-approved bounded batch')
    plan=json.loads(PLAN.read_text());baseline=None;candidate=None
    if args.prepare_candidate or args.execute_approved_candidate:
        if not args.baseline_results:raise RuntimeError('baseline results are required')
        baseline=load_baseline(args.baseline_results,args.approved_plan_sha256)
        candidate=candidate_freeze(plan,baseline)
        if args.prepare_candidate:
            path=Path(baseline['_path']).parent/'candidate-freeze.json'
            if path.exists() and json.loads(path.read_text())!=candidate:
                raise RuntimeError('another candidate descriptor already exists; preserve and reconcile before replacement')
            path.write_text(json.dumps(candidate,indent=2)+'\n')
            print('candidate descriptor '+str(path)+' sha256='+digest(path));return
        if not args.candidate_freeze or not args.candidate_freeze_sha256 or digest(args.candidate_freeze)!=args.candidate_freeze_sha256:
            raise RuntimeError('reviewed exact candidate descriptor hash required')
        if json.loads(Path(args.candidate_freeze).read_text())!=candidate:
            raise RuntimeError('candidate source/artifact freeze differs from reviewed descriptor')
    # No compatibility fallback, no artifact/profile/runtime-limit override.
    abi=json.loads((ROOT/'out/PackVault.sol/PackVault.json').read_text())['abi']
    sync=[a for a in abi if a.get('type')=='function' and a.get('name')=='sync']
    if len(sync)!=1 or [i['type'] for i in sync[0]['inputs']]!=['uint256[]','uint256','uint256']:
        raise RuntimeError('freeze/build the agreed autonomous sync API before approving execution')
    for path in ('out/PackVault.sol/PackVault.json','out/VaultLib.sol/VaultLib.json','out/KeeperPolicy.sol/KeeperPolicyV1.json','out/ForkKeeperPolicy.t.sol/PolicyGreedy.json'):
        runtime=json.loads((ROOT/path).read_text())['deployedBytecode']['object'].removeprefix('0x')
        if len(runtime)//2>MAX_CODE:raise RuntimeError('frozen runtime exceeds normal EIP170 limit before deployment')
    work=Path(tempfile.mkdtemp(prefix='efficient-journal-candidate-' if candidate else 'efficient-journal-baseline-'))
    batch=LocalBatch(plan,work,candidate,baseline)
    print('local batch evidence directory '+str(work),flush=True)
    try:batch.run()
    except BaseException as exc:
        batch.state.update(status='failed',global_phase=batch.phase+'_failed',failure=str(exc),node_preserved=True);batch.save();raise


if __name__=='__main__':main()
