#!/usr/bin/env python3
"""Local rehearsal of the proposed canary with the production deploy script and the production
keeper (keeper/keeper.py, unmodified), on an anvil fork pinned just before a real FWA buyback.

Start the fork first (local only; never a public network). Block 26,418,539 is after FWA admitted
packs and quoted them, one block before a searcher paid FWA's accrued protocol fees into its V2
buyback; the rehearsal makes that permissionless payout and buyback itself, after the vault lists:
  anvil --fork-url https://mainnet.gateway.tenderly.co --fork-block-number 26418539 \
    --port 8547 --base-fee 150000000
Then: python3 keeper/rehearse_canary.py   (writes sim/out/canary-rehearsal.json)

Values: deploy/canary.example.json exactly (guardian and admin placeholders impersonated).
Other parties act only through their real entry points: the buyback is the real transaction
FWA's own permissionless buyback() spending real protocol fees, the oracle owner moves the ask, anyone kicks, holders deposit and redeem.
Not reachable here: acquisitions selecting vault listings (their VRF proofs bind the original
request block hash, which a local chain cannot reproduce); those run in test/fork/ForkSelection.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RPC = "http://127.0.0.1:8547"
VALUES = json.loads((ROOT / "deploy/canary.example.json").read_text())
FWA = VALUES["fwa"]
PACKS = VALUES["packs"]
QUOTER = "0x52f0e24d1c21c8a0cb1e5a5dd6198556bd9e1203"  # Uniswap v4 Quoter, mainnet
# Actors: fresh addresses (keccak of a label). Never anvil's dev accounts: those are real mainnet
# addresses, and dev account #2 carries an EIP-7702 delegation that diverts ETH it receives.
DEPLOYER = "0xe0980b9f7F5fB4a98813552894f4E980836cDa7c"  # keccak("pack-vault-rehearsal-deployer")
HOLDER = "0xDd4B0D7470953fb19b97fa130A15Af59537Bc523"
HOLDER2 = "0xb9A3188644D5A55A98C68B056A2685Cd6C915725"
KEEPER = "0x6B401c3364dFb17fe7D54237fC04aba3f7739dd0"
KICKER = "0x2C42b18832Cef2Eb8C8C0f83250700176694E341"  # "anyone": kicks, processes FWA's queue
E = 10**18
log = []


def sh(*args, check=True):
    r = subprocess.run([str(a) for a in args], capture_output=True, text=True, cwd=ROOT)
    if check and r.returncode:
        sys.exit(f"failed: {' '.join(map(str, args))}\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def cast(*a):
    return sh("cast", *a, "--rpc-url", RPC)


def call(to, sig, *a):
    return cast("call", to, sig, *a).split(" ")[0]


def ids(sig="openListings()(uint256[])"):
    out = cast("call", VAULT, sig).strip("[]")
    return [int(x.strip().split(" ")[0]) for x in out.split(",") if x.strip()]


def num(v):
    v = v.split(" ")[0]
    return int(v, 0) if v.startswith("0x") else int(v)


def send(frm, to, sig, *a, value=None, expect=True):
    extra = ["--value", str(value)] if value is not None else []
    r = subprocess.run(["cast", "send", to, sig, *map(str, a), *extra, "--from", frm, "--unlocked",
                        "--rpc-url", RPC, "--json"], capture_output=True, text=True)
    ok = r.returncode == 0 and json.loads(r.stdout).get("status") == "0x1"
    if ok != expect:
        sys.exit(f"{sig} from {frm}: expected {'success' if expect else 'revert'}\n{r.stdout}{r.stderr}")
    return ok


def impersonate(addr):
    cast("rpc", "anvil_impersonateAccount", addr)
    cast("rpc", "anvil_setBalance", addr, hex(10 * E))


def warp_to(offset):  # seconds into FWA's 12 h interval: 42,360 = 11:46 (blackout), 60 = open
    now = num(cast("block", "latest", "--field", "timestamp"))
    nxt = now - now % 43200 + offset
    if nxt <= now:
        nxt += 43200
    cast("rpc", "evm_setNextBlockTimestamp", str(nxt))
    cast("rpc", "evm_mine")


def keeper(*extra):
    out = sh("python3", "keeper/keeper.py", VAULT, "--send", "--from", KEEPER, "--rpc", RPC, *extra, check=False)
    print("  " + out.replace("\n", "\n  "))
    return out


def state(tag):
    s = dict(tag=tag, balance=num(cast("balance", VAULT)), lastNav=num(call(VAULT, "lastNav()(uint256)")),
             totalShares=num(call(VAULT, "totalShares()(uint256)")),
             open=len(ids()), idle=len(ids("idlePacks()(uint256[])")),
             loose=num(call(VAULT, "looseShapeCount()(uint256)")),
             tokens=num(call(TOKEN, "balanceOf(address)(uint256)", VAULT)),
             keeper=num(cast("balance", KEEPER)), holder=num(cast("balance", HOLDER)))
    log.append(s)
    print(f"[{tag}] balance {s['balance'] / E:.6f} open {s['open']} idle {s['idle']} loose {s['loose']} "
          f"tokens {s['tokens']} lastNav {s['lastNav'] / E:.6f}")
    return s


def main():
    global VAULT, TOKEN
    if num(cast("chain-id")) != 1:
        sys.exit("expects a local mainnet fork")
    sh("forge", "build", "--force")
    for a in (DEPLOYER, HOLDER, HOLDER2, KEEPER, KICKER):
        if cast("code", a) != "0x" or num(cast("nonce", a)) != 0:
            sys.exit(f"actor {a} is not a clean address on this chain")
        impersonate(a)
    r = subprocess.run(["forge", "script", "script/Deploy.s.sol", "--rpc-url", RPC, "--broadcast", "--unlocked",
                        "--sender", DEPLOYER], capture_output=True, text=True, cwd=ROOT,
                       env={**__import__("os").environ, "DEPLOY_VALUES": "deploy/canary.example.json"})
    if r.returncode:
        sys.exit(r.stdout + r.stderr)
    run = json.loads((ROOT / "broadcast/Deploy.s.sol/1/run-latest.json").read_text())
    VAULT = next(t["contractAddress"] for t in run["transactions"] if t.get("contractName") == "PackVault")
    TOKEN = call(FWA, "token()(address)")
    print("vault", VAULT)
    keeper_start = num(cast("balance", KEEPER))
    holder_start = num(cast("balance", HOLDER))
    s0 = state("deployed")

    # 1. Deposits: the TVL cap is enforced on lastNav + escrow (lastNav is 0 before pricing).
    send(HOLDER, VAULT, "deposit()", value=VALUES["tvlCapWei"] - VALUES["seedWei"])
    send(HOLDER2, VAULT, "deposit()", value=2 * 10**16, expect=False)
    deposited = VALUES["tvlCapWei"] - VALUES["seedWei"]
    warp_to(42360)
    keeper()
    state("priced")

    # 2. Inventory and listing: the keeper alone, until nothing more fits. The fork carries a
    #    real request whose word never arrives here, so FWA stages these listings.
    warp_to(60)
    keeper()
    built = state("deployed capital")
    staged0 = sum(1 for i in ids() if num(cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", i).split("\n")[-1]) == 5)
    print(f"  FWA staged {staged0} of {built['open']} listings (its queue was busy)")
    if num(call(FWA, "unsettledAcquisitionCount()(uint256)")):
        # FWA's own processor expires a stale request after its word deadline (anyone may call).
        for _ in range(8):
            cast("rpc", "anvil_mine", hex(1000))
        send(KICKER, FWA, "processAcquisitions(uint256)", 50)
    if staged0:
        keeper()  # the keeper activates the vault's staged listings, paid per listing activated
    staged1 = sum(1 for i in ids() if num(cast("call", FWA, "listings(uint256)(address,address,address,uint256,uint256,uint256,uint256,uint256,uint256,uint64,uint8)", i).split("\n")[-1]) == 5)
    print(f"  staged after the keeper's activation: {staged1}")

    # 3. Token rewards through FWA's real permissionless path: anyone pays out FWA's accrued
    #    protocol fees (a slice funds the buyback contract) and anyone runs the buyback, which
    #    buys FWA tokens and routes the depositor share to active listings by sqrt(backing).
    rewards = call(FWA, "rewards()(address)")
    bb = call(rewards, "buyback()(address)")
    if num(call(FWA, "accruedOwnerFees()(uint256)")):
        send(KICKER, FWA, "payoutFees()")
    bb_eth = num(cast("balance", bb))
    print(f"  buyback contract holds {bb_eth / E:.6f} ETH")
    send(KICKER, bb, "buyback()")
    listed = ids()
    pending = sum(num(call(rewards, "pendingDepositorTokens(uint256)(uint256)", i)) for i in listed)
    print(f"  real buyback accrued {pending} token wei to {len(listed)} listings")
    out_noref = keeper()

    # 4. The admin sets a reference floor from a live quote (parameter delay applies).
    pk = cast("call", TOKEN, "poolKey()((address,address,uint24,int24,address))")
    q = cast("call", QUOTER, "quoteExactInputSingle(((address,address,uint24,int24,address),bool,uint128,bytes))(uint256,uint256)",
             f"({pk},false,{10**18},0x)")
    ref = num(q.splitlines()[0]) if q else 0
    raw = cast("call", VAULT, "getParams()((uint16,uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint96,uint128,uint128,uint128,uint128,uint128))")
    fields = [f.split(" ")[0] for f in raw.strip("()").split(", ")]
    fields[-1] = str(ref)
    tup = "(" + ",".join(fields) + ")"
    impersonate(VALUES["admin"])
    send(VALUES["admin"], VAULT, "proposeParams((uint16,uint16,uint16,uint16,uint16,uint16,uint16,uint64,uint64,uint64,uint96,uint128,uint128,uint128,uint128,uint128))", tup)
    cast("rpc", "evm_increaseTime", str(VALUES["paramDelay"] + 60))
    cast("rpc", "evm_mine")
    send(KICKER, VAULT, "applyParams()")
    print(f"  reference floor set from a live quote: {ref} wei per 1e18 tokens")

    # 5. Keeper decides on its own: dust rewards are not worth the vault's gas pay.
    out_dust = keeper()
    # 6. The operator chooses to subsidize: the same production keeper sells, unpaid.
    before_eth = num(cast("balance", VAULT))
    kb = num(cast("balance", KEEPER))
    out_sub = keeper("--subsidize-tokens")
    sold = state("after token sale")
    token_eth = sold["balance"] - before_eth
    token_keeper_cost = kb - sold["keeper"]

    # 7. Settlement-like transition: the oracle owner lowers the ask; anyone kicks in the blackout;
    #    the keeper resolves and relists at the new cap.
    oracle = call(FWA, "floorOracle()(address)")
    owner = call(oracle, "owner()(address)")
    impersonate(owner)
    send(owner, oracle, "setFloor(address,uint256)", PACKS, 3 * 10**16)
    warp_to(42360)
    impersonate(KICKER)
    send(KICKER, FWA, "kickListing(uint256)", listed[0])
    warp_to(60)
    keeper()
    state("after kick, sync, relist")

    # 8. Partial withdrawal, with the keeper interrupted after one call and restarted.
    shares = num(call(VAULT, "shareBalance(address)(uint256)", HOLDER))
    send(HOLDER, VAULT, "requestRedeem(uint256)", shares // 2)
    keeper("--max-steps", "1")  # interrupted
    keeper()  # restarted from chain state alone
    warp_to(42360)
    keeper()
    send(HOLDER, VAULT, "claim()")
    state("partial withdrawal")

    # 9. Full withdrawal, then wind-down.
    warp_to(60)
    shares = num(call(VAULT, "shareBalance(address)(uint256)", HOLDER))
    send(HOLDER, VAULT, "requestRedeem(uint256)", shares)
    impersonate(VALUES["guardian"])
    send(VALUES["guardian"], VAULT, "startWindDown()")
    keeper()
    warp_to(42360)
    keeper()
    send(HOLDER, VAULT, "claim()", expect=True)
    end = state("wound down")

    paid_logs = json.loads(sh("cast", "logs", "--rpc-url", RPC, "--json", "--address", VAULT,
                              "KeeperPaid(address indexed,uint256)") or "[]")
    pay = sum(int(l["data"], 16) for l in paid_logs)
    claim_logs = json.loads(sh("cast", "logs", "--rpc-url", RPC, "--json", "--address", VAULT,
                               "Claimed(address indexed,uint256)") or "[]")
    claims = sum(int(l["data"], 16) for l in claim_logs)
    conv = json.loads(sh("cast", "logs", "--rpc-url", RPC, "--json", "--address", VAULT,
                         "Converted(uint256,uint256)") or "[]")
    token_out = sum(int(l["data"][66:], 16) for l in conv)
    restocks = json.loads(sh("cast", "logs", "--rpc-url", RPC, "--json", "--address", VAULT,
                             "Restocked(uint256,uint256)") or "[]")
    loose, mints = 0, 0
    for l in restocks:
        n, u = int(l["data"][2:66], 16), int(l["data"][66:], 16)
        need = n * u
        m = -(-(need - loose) // 10) if need > loose else 0
        mints += m
        loose += 10 * m - need
    mint_fees = mints * 10**15
    ins = s0["balance"] + deposited + token_out
    outs = claims + pay + mint_fees + end["balance"]
    report = dict(
        values=VALUES, positions_built=built["open"] + built["idle"], positions_listed=built["open"],
        capital_idle_after_build=built["balance"], deposited=deposited, claimed=claims,
        holder_result=claims - deposited, keeper_pay=pay, keeper_net=end["keeper"] - keeper_start,
        keeper_gas_spent=pay - (end["keeper"] - keeper_start), mints=mints, mint_fees=mint_fees,
        staged_before_activation=staged0, staged_after_activation=staged1,
        token_pending=pending, token_eth=token_out, token_sale_keeper_cost=token_keeper_cost,
        end_balance=end["balance"], end_lastNav=end["lastNav"], ledger_in=ins, ledger_out=outs,
        ledger_gap=ins - outs, waits=dict(no_ref=out_noref, dust=out_dust, subsidized=out_sub), log=log)
    (ROOT / "sim/out/canary-rehearsal.json").write_text(json.dumps(report, indent=1, default=str))
    print(json.dumps({k: v for k, v in report.items() if k not in ("log", "waits", "values")}, indent=1))
    if ins != outs:
        sys.exit(f"ledger does not close: in {ins} out {outs}")
    print("ledger closes to the wei: seed + deposits + token ETH = claims + keeper pay + mint fees + balance")
    del token_eth, holder_start


if __name__ == "__main__":
    main()
