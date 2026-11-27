"""One off-chain representation of the account-owned Solidity configuration."""
import re

PARAM_FIELDS = [
    ('minEdgeBps', 'uint16'), ('distributionBps', 'uint16'),
    ('keeperShareBps', 'uint16'), ('upliftBoundBps', 'uint16'),
    ('packUnitsMask', 'uint64'), ('gasCeilingWei', 'uint64'), ('essentialCeilingWei', 'uint64'),
    ('maxTipWei', 'uint64'), ('workFeeWei', 'uint64'), ('routineCapWei', 'uint64'),
    ('routineRatePerDayWei', 'uint64'),
    ('reserveWei', 'uint128'), ('tvlCapWei', 'uint128'), ('backingRatioBps', 'uint32'),
    ('acceptedMintFeeWei', 'uint64'),
    ('minDepositWei', 'uint64'), ('minDistributionWei', 'uint64'),
]
GAS_FIELDS = ('checkpoint allocationEntry allocationRead build buildPack buildShape list listed sync requiredTail '
              'distributionProof journal scan selected synced pruned unlist unlisted '
              'harvested credit fund overhead').split()
GAS_T = '(' + ','.join(['uint32'] * len(GAS_FIELDS)) + ')'
PARAMS_T = '(' + ','.join([t for _, t in PARAM_FIELDS] + [GAS_T]) + ')'
PARAMS_ORDER = [k for k, _ in PARAM_FIELDS]
GAS_DEFAULTS = dict(zip(GAS_FIELDS, (
    500_000, 6_000, 30_000, 360_000, 300_000, 130_000, 280_000, 825_000,
    125_000, 120_000, 80_000, 22_000, 30_000, 180_000, 120_000, 45_000,
    340_000, 285_000,
    80_000, 40_000, 40_000, 100_000)))
GAS_KEYS = dict(zip(GAS_FIELDS, (
    'checkpoint', 'allocation_entry', 'allocation_read', 'build', 'build_pack', 'build_shape',
    'list', 'listed', 'sync', 'journal_tail', 'distribution_proof', 'journal', 'scan', 'selected',
    'synced', 'pruned', 'unlist', 'unlisted',
    'harvested', 'sync_credit', 'sync_funding', 'overhead')))


def params_values(values):
    result = []
    for key, kind in PARAM_FIELDS:
        value = int(values[key])
        if not 0 <= value < 1 << int(kind[4:]):
            raise ValueError(f'{key} does not fit {kind}')
        result.append(value)
    gas = tuple(int(values['gasSchedule'][key]) for key in GAS_FIELDS)
    if any(not 0 <= n < 1 << 32 for n in gas):
        raise ValueError('gas schedule does not fit uint32')
    return tuple(result) + (gas,)


def tuple_arg(values):
    p = params_values(values)
    return '(' + ','.join(map(str, p[:-1])) + ',(' + ','.join(map(str, p[-1])) + '))'


def decode_params(raw):
    clean = re.sub(r'\s*\[[^\]]*\]', '', raw)
    numbers = [int(n) for n in re.findall(r'\d+', clean)]
    if len(numbers) != len(PARAM_FIELDS) + len(GAS_FIELDS):
        raise ValueError('unexpected account Params result')
    return dict(zip(PARAMS_ORDER, numbers[:len(PARAM_FIELDS)])) | {
        'gasSchedule': dict(zip(GAS_FIELDS, numbers[len(PARAM_FIELDS):]))}


def gas_schedule(values):
    return {GAS_KEYS[key]: int(value) for key, value in values['gasSchedule'].items()}


def configuration_hash(values, live_mint_fee, listing_paused=False, winding_down=False):
    from eth_abi import encode
    from eth_utils import keccak
    return '0x' + keccak(encode([PARAMS_T, 'uint256', 'bool', 'bool'], [params_values(values), live_mint_fee, listing_paused, winding_down])).hex()


def factory_configuration_hash(values, live_mint_fee, implementation):
    """PackManagerFactory.configHashFor: the creation's settings bound to the implementation it clones."""
    from eth_abi import encode
    from eth_utils import keccak
    return '0x' + keccak(encode([PARAMS_T, 'uint256', 'bool', 'bool', 'address'],
                                [params_values(values), live_mint_fee, False, False, implementation])).hex()


def guarded_call(sig, args, read):
    """Bind legacy rehearsal call sites to the current ABI at the execution boundary."""
    name = sig.split('(')[0]
    args = list(args)
    if name == 'create' and 'bytes32' not in sig:
        args.append(read(f'configHashFor({PARAMS_T})(bytes32)', args[-1]))
    elif name in {'setParams', 'acceptMintFee', 'build', 'list', 'sync', 'unlist', 'liquidate', 'renew',
                  'checkpoint', 'deposit', 'requestRedeem', 'fundCheckpoint', 'syncCheckpoint'} and 'bytes32' not in sig:
        args.append(read('configurationHash()(bytes32)'))
    else:
        return sig, args
    return sig[:-1] + (',' if sig[-2] != '(' else '') + 'bytes32)', args
