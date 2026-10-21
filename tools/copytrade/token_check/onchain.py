"""Our own EVM safety checks for chains GoPlus doesn't cover (HyperEVM, Ink). Free, keyless sources only:
public RPC (eth_call + state override, eth_getLogs), Sourcify (verified source/ABI), Blockscout (Ink: holders, creator, ABI).
Returns a dict shaped like token_check.goplus() so the same PASS/WARN/KILL rules apply. Anything we can't measure is None (= unknown).
Honeypot test: sim/HoneypotSim.sol is injected with an eth_call state override (nothing is sent or signed), buys ~$25 of
the token through its deepest wrapped-native pool, transfers 1% to a fresh address, sells the rest, and reports taxes."""
import json, os, time
import requests
import etherscan

HERE = os.path.dirname(os.path.abspath(__file__))
_SIM_BIN = os.path.join(HERE, "sim", "HoneypotSim.bin-runtime")  # build from sim/HoneypotSim.sol (see README); not in the repo
SIM_CODE = ("0x" + open(_SIM_BIN).read().strip()) if os.path.exists(_SIM_BIN) else None
SIM = "0x" + "0" * 34 + "5151AA"
DEAD = {"0x" + "0" * 36 + "dead", "0x" + "0" * 40}  # burn addresses
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
IMPL_SLOT = "0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc"
BEACON_SLOT = "0xa3f0ad74e5423aebfd80d3ef4346578335a9a72aeaee59ff6cb3582b35133d50"
SEL = {"owner": "8da5cb5b", "getOwner": "893d20e8", "totalSupply": "18160ddd", "balanceOf": "70a08231", "decimals": "313ce567",
       "token0": "0dfe1681", "getReserves": "0902f1ac", "slot0": "3850c7bd", "globalState": "e76c01e4", "run": "d56ae1d3",
       "DEFAULT_ADMIN_ROLE": "a217fddf"}
# bytecode selector scan, used only when source isn't verified (PUSH4 <selector>)
RISK_SELECTORS = {"mint": ["40c10f19", "a0712d68", "449a52f8"],
                  "blacklist": ["f9f92be4", "44337ea1", "153b0d1e", "455a4396", "fe575a87", "9c0db5f3", "d34628cc"],
                  "pause": ["8456cb59"], "fees": ["69fe0e2d", "c647b20e", "0b78f9c0", "0cc835a3", "8b4cee08", "6db79437", "2e5bb6ff"],
                  "upgrade": ["3659cfe6", "4f1ef286"]}
NAME_RULES = {"mint": ("mint", "issue"), "blacklist": ("blacklist", "blocklist", "denylist", "bot", "sniper", "exclude from trading"),
              "pause": ("pause", "freeze", "enabletrading", "settrading", "lock"), "fees": ("fee", "tax"), "upgrade": ("upgrade",),
              "balance": ("setbalance", "burnfrom", "rebase", "reflect")}


class OnchainError(Exception):
    pass


def _hx(n): return hex(int(n))
def _a(x): return "0" * 24 + x.lower().replace("0x", "")
def _u(x): return format(int(x), "064x")
def _words(h): h = h[2:] if h.startswith("0x") else h; return [int(h[i:i + 64], 16) for i in range(0, len(h), 64) if len(h[i:i + 64]) == 64]


class RPC:
    def __init__(self, ccfg, timeout=25):
        self.urls = ccfg["rpcs"]; self.archive = ccfg.get("archive_rpcs") or self.urls; self.max_range = ccfg.get("logs_max_range", 1000)
        self.logs_urls = ccfg.get("logs_rpcs") or self.urls; self.t = timeout; self.calls = 0

    def call(self, method, params, urls=None, raw=False):
        last = None
        for u in urls or self.urls:
            for i in range(2):
                try:
                    self.calls += 1
                    j = requests.post(u, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=self.t).json()
                    if "error" in j:
                        msg = str(j["error"].get("message", ""))
                        if raw and ("revert" in msg.lower() or j["error"].get("code") == 3): return None
                        last = msg[:120]
                        if "rate" in msg.lower() or "limit" in msg.lower(): time.sleep(1 + i); continue
                        break
                    return j.get("result")
                except (requests.RequestException, ValueError) as e:
                    last = type(e).__name__; time.sleep(1)
        raise OnchainError(f"{method}: {last}")

    def eth_call(self, to, data, block="latest", override=None, frm=None, urls=None, gas=None):
        tx = {"to": to, "data": "0x" + data.replace("0x", "")}
        if frm: tx["from"] = frm
        if gas: tx["gas"] = gas
        p = [tx, block] + ([override] if override else [])
        try: return self.call("eth_call", p, urls=urls, raw=True)
        except OnchainError: return None


def http_json(url, timeout=20):
    try:
        r = requests.get(url, timeout=timeout, headers={"User-Agent": "token_check/1.0"})
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


# ---------------- contract metadata ----------------
def sourcify(chain_id, addr):
    d = http_json(f"https://sourcify.dev/server/v2/contract/{chain_id}/{addr}?fields=abi,proxyResolution")
    if not d or not d.get("match"): return None
    pr = d.get("proxyResolution") or {}
    return {"abi": d.get("abi") or [], "proxy_type": pr.get("proxyType") if pr.get("isProxy") else None,
            "impls": [i.get("address") for i in pr.get("implementations") or [] if i.get("address")]}


def blockscout_contract(bs, addr):
    d = http_json(f"{bs}/api/v2/smart-contracts/{addr}")
    a = http_json(f"{bs}/api/v2/addresses/{addr}") or {}
    out = {"creator": (a.get("creator_address_hash") or "").lower() or None, "creation_tx": a.get("creation_transaction_hash"),
           "proxy_type": a.get("proxy_type"), "impls": [i.get("address_hash") or i.get("address") for i in a.get("implementations") or []]}
    if d and d.get("abi") and (d.get("is_verified") or a.get("is_verified")): out["abi"] = d["abi"]
    elif a.get("is_verified") is False: out["abi"] = None
    return out


def fn_names(abi):
    return [(f.get("name") or "") for f in abi or [] if f.get("type") == "function" and f.get("stateMutability") not in ("view", "pure")]


def classify(names):
    low = [n.lower() for n in names]; hit = {}
    for k, keys in NAME_RULES.items():
        hit[k] = sorted({n for n, l in zip(names, low) if any(x.replace(" ", "") in l for x in keys)
                         and not l.startswith("_") and l not in ("approve", "transfer", "transferfrom")
                         and not (k == "pause" and l in ("unlock",)) and not (k == "mint" and "permit" in l)})
    return hit


def selector_scan(code):
    c = code.lower()
    return {k: [s for s in v if "63" + s in c] for k, v in RISK_SELECTORS.items()}


# ---------------- holders ----------------
def find_creation_block(rpc, addr, head):
    lo, hi = 0, head
    if (rpc.call("eth_getCode", [addr, _hx(hi)], urls=rpc.archive) or "0x") == "0x": return None
    if (rpc.call("eth_getCode", [addr, _hx(1)], urls=rpc.archive) or "0x") != "0x": return None  # non-archive answer, can't trust
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if (rpc.call("eth_getCode", [addr, _hx(mid)], urls=rpc.archive) or "0x") != "0x": hi = mid
        else: lo = mid
    return hi


def transfer_logs(rpc, addr, frm, to, max_chunks):
    """All Transfer logs of a token from block frm to to. None if it would take more than max_chunks calls."""
    step = rpc.max_range; n = (to - frm) // step + 1
    if n > max_chunks: return None
    logs = []
    for b in range(frm, to + 1, step):
        r = rpc.call("eth_getLogs", [{"address": addr, "topics": [TRANSFER], "fromBlock": _hx(b), "toBlock": _hx(min(to, b + step - 1))}], urls=rpc.logs_urls)
        logs += r or []
    return logs


def holders_from_logs(rpc, addr, logs, total, exclude, k=10):
    bal = {}
    for l in logs:
        if len(l["topics"]) != 3 or l["data"] in ("0x", ""): continue
        f, t, v = "0x" + l["topics"][1][-40:], "0x" + l["topics"][2][-40:], int(l["data"][:66], 16)
        bal[f] = bal.get(f, 0) - v; bal[t] = bal.get(t, 0) + v
    cands = sorted((a for a in bal if a not in exclude and a not in DEAD), key=lambda a: -bal[a])[:k + 15]
    real = []
    for a in cands:  # confirm with balanceOf: logs can miss rebases/reflections
        r = rpc.eth_call(addr, SEL["balanceOf"] + _a(a))
        if r and r != "0x": real.append((a, int(r, 16)))
    real.sort(key=lambda x: -x[1])
    return [(a, v / total * 100) for a, v in real[:k]], len(bal)


def blockscout_holders(bs, addr, k=50):
    d = http_json(f"{bs}/api/v2/tokens/{addr}/holders")
    t = http_json(f"{bs}/api/v2/tokens/{addr}") or {}
    if not d or "items" not in d: return None, None
    return [((i["address"]["hash"]).lower(), int(i["value"]), i["address"].get("is_contract"), i["address"].get("name")) for i in d["items"][:k]], t.get("holders_count") or t.get("holders")


# ---------------- honeypot simulation ----------------
def pool_kind(rpc, pool):
    if len(pool) != 42: return None  # Uniswap v4 pool ids aren't contracts
    for s in ("slot0", "globalState"):  # check CL first: some CL pools (e.g. nest) also answer getReserves
        r = rpc.eth_call(pool, SEL[s])
        if r and len(r) > 2: return "v3"
    r = rpc.eth_call(pool, SEL["getReserves"])
    if r and len(r) >= 2 + 64 * 2: return "v2"
    return None


def simulate(rpc, pool, kind, wnative, token, amount_wei):
    data = SEL["run"] + _a(pool) + _u(1 if kind == "v2" else 0) + _a(wnative) + _a(token) + _u(amount_wei)
    if not SIM_CODE: return None  # sim not built: honeypot stays unknown
    ov = {SIM: {"code": SIM_CODE, "balance": _hx(amount_wei * 2)}}
    r = rpc.eth_call(SIM, data, override=ov, frm="0x" + "0" * 36 + "c0de", gas=_hx(30_000_000))
    if not r or r == "0x": return None
    w = _words(r)
    return dict(zip(["stage", "buy_out", "buy_got", "probe_sent", "probe_got", "sell_sent", "pool_got", "sell_got"], w)) if len(w) >= 8 else None


def honeypot(rpc, pairs, wnative, token, ticket_usd):
    """Try the deepest wrapped-native pools. Returns (result dict or None, note)."""
    cands = []
    for p in sorted(pairs, key=lambda p: -((p.get("liquidity") or {}).get("usd") or 0)):
        q = (p.get("quoteToken") or {}).get("address", "").lower(); b = (p.get("baseToken") or {}).get("address", "").lower()
        if wnative.lower() not in (q, b) or token.lower() not in (q, b): continue
        pn, pu = float(p.get("priceNative") or 0), float(p.get("priceUsd") or 0)
        native_usd = pu / pn if pn and pu and q == wnative.lower() else None
        cands.append((p, native_usd))
    if not cands: return None, "no pool against the wrapped native token to test with"
    native_usd = next((n for _, n in cands if n), None)
    notes = []; last = None
    for p, _ in cands[:3]:
        kind = pool_kind(rpc, p["pairAddress"])
        if not kind: notes.append(f"{p.get('dexId')} pool type not supported"); continue
        qliq = (p.get("liquidity") or {}).get("quote") if (p.get("quoteToken") or {}).get("address", "").lower() == wnative.lower() else (p.get("liquidity") or {}).get("base")
        amt = ticket_usd / native_usd if native_usd else 0.01
        if qliq: amt = min(amt, float(qliq) * 0.005)
        amt_wei = max(int(amt * 1e18), 10 ** 12)
        r = simulate(rpc, p["pairAddress"], kind, wnative, token, amt_wei)
        if r is None or r["stage"] == 2:  # wrong guess of pool type? try the other swap style once
            alt = "v3" if kind == "v2" else "v2"; r2 = simulate(rpc, p["pairAddress"], alt, wnative, token, amt_wei)
            if r2 and r2["stage"] != 2: r, kind = r2, alt
        if r is None: notes.append(f"{p.get('dexId')} {kind} simulation reverted"); continue
        r.update(pool=p["pairAddress"], dex=p.get("dexId"), kind=kind, amount_in=amt_wei)
        if r["stage"] in (1, 2) and len(notes) < 2: notes.append(f"{p.get('dexId')} buy reverted"); last = r; continue
        return r, ""
    return last, "; ".join(notes)


# ---------------- main entry ----------------
def security(chain, addr, pairs, cfg):
    cc = (cfg.get("onchain") or {}).get(chain)
    if not cc: raise OnchainError(f"no on-chain config for {chain}")
    rpc = RPC(cc); addr = addr.lower(); out = {"_sources": {}}; S = out["_sources"]
    code = rpc.call("eth_getCode", [addr, "latest"]) or "0x"
    if code == "0x": raise OnchainError("no contract at this address")
    head = int(rpc.call("eth_blockNumber", []), 16)
    dec_r = rpc.eth_call(addr, SEL["decimals"]); ts_r = rpc.eth_call(addr, SEL["totalSupply"])
    total = int(ts_r, 16) if ts_r and ts_r != "0x" else None

    # --- source / ABI / proxy ---
    meta = {}
    if cc.get("blockscout"):
        meta = blockscout_contract(cc["blockscout"], addr); S["blockscout"] = "ok" if meta else "failed"
    sf = sourcify(cc["chain_id"], addr); S["sourcify"] = "verified" if sf else "not verified / no data"
    es = etherscan.source(chain, addr)  # Etherscan v2 (HyperEVMScan) when a key is set; None otherwise
    if es is not None: S["etherscan"] = ("verified: " + (es.get("name") or "?")) if es["verified"] else "not verified"
    abi = (meta or {}).get("abi") or (sf or {}).get("abi") or ((es or {}).get("abi") if (es or {}).get("verified") else None)
    out["contract_name"] = (es or {}).get("name") if (es or {}).get("verified") else None
    impl_slot = rpc.call("eth_getStorageAt", [addr, IMPL_SLOT, "latest"]) or "0x0"
    beacon = rpc.call("eth_getStorageAt", [addr, BEACON_SLOT, "latest"]) or "0x0"
    is_clone = code.lower().startswith("0x363d3d373d3d3d363d73")
    ptype = (meta or {}).get("proxy_type") or (sf or {}).get("proxy_type")
    impls = [i for i in ((meta or {}).get("impls") or (sf or {}).get("impls") or []) if i]
    if int(impl_slot, 16): impls = impls or ["0x" + impl_slot[-40:]]
    if is_clone: impls = impls or ["0x" + code[22:62]]; ptype = "eip1167"
    upgradeable = bool(int(impl_slot, 16) or int(beacon, 16)) or (ptype not in (None, "eip1167", "unknown") and bool(ptype))
    impl_code = None
    if impls:
        ia = impls[0]; isf = sourcify(cc["chain_id"], ia)
        ies = etherscan.source(chain, ia)
        if (ies or {}).get("verified") and ies.get("name"): out["contract_name"] = ies["name"]
        iabi = (blockscout_contract(cc["blockscout"], ia).get("abi") if cc.get("blockscout") else None) or (isf or {}).get("abi") \
            or ((ies or {}).get("abi") if (ies or {}).get("verified") else None)
        if iabi: abi = (abi or []) + iabi
        if not iabi: abi = None if not (meta or {}).get("abi") and not sf and not (es or {}).get("verified") else abi
        impl_code = rpc.call("eth_getCode", [ia, "latest"])
    verified = bool(abi)
    out["open_source"] = verified
    out["proxy"] = upgradeable
    if verified:
        hit = classify(fn_names(abi)); S["powers_from"] = "verified ABI"
    else:
        hit = selector_scan((impl_code or "") + code); S["powers_from"] = "bytecode selectors (unverified, partial)"
    # --- owner ---
    owner = None; has_owner_fn = False
    for s in ("owner", "getOwner"):
        r = rpc.eth_call(addr, SEL[s])
        if r and len(r) >= 66: owner = "0x" + r[-40:]; has_owner_fn = True; break
    access_control = bool(rpc.eth_call(addr, SEL["DEFAULT_ADMIN_ROLE"]))
    if has_owner_fn: renounced = owner in DEAD
    elif access_control: renounced = None  # role-based admin: can't tell who holds roles cheaply
    elif verified or is_clone: renounced = True  # no owner and no roles: nobody to hold powers
    else: renounced = None
    out["owner_address"] = owner; out["owner_renounced"] = renounced
    out["mintable"] = bool(hit.get("mint")) if (verified or hit.get("mint")) else None
    out["blacklist"] = bool(hit.get("blacklist")) if (verified or hit.get("blacklist")) else None
    pw = []
    if hit.get("pause"): pw.append("transfer_pausable")
    if hit.get("fees"): pw.append("slippage_modifiable")
    if hit.get("balance"): pw.append("owner_change_balance")
    out["owner_powers"] = pw; out["power_functions"] = {k: v for k, v in hit.items() if v}
    if not verified and not pw: out["owner_powers_unknown"] = True

    # --- symbol / holders / dev ---
    pools = {(p.get("pairAddress") or "").lower() for p in pairs} | set((cfg.get("exclude_holders") or {}).get("all", [])) | set(cc.get("exclude_holders", []))
    creator = (meta or {}).get("creator") or ((etherscan.creator(chain, addr) or {}).get("creator") or None); top = None; hcount = None; lp_locked = None
    if cc.get("blockscout"):
        hl, hcount = blockscout_holders(cc["blockscout"], addr)
        if hl is not None and total:
            keep = [(a, v) for a, v, isc, name in hl if a not in pools and a not in DEAD and not (isc and name and ("pair" in name.lower() or "pool" in name.lower() or "locker" in name.lower()))]
            top = [(a, v / total * 100) for a, v in keep[:10]]; S["holders"] = "blockscout"
    if top is None and total:
        try:
            cb = find_creation_block(rpc, addr, head)
            logs = transfer_logs(rpc, addr, cb, head, cc.get("max_log_chunks", 40)) if cb else None
            if logs is not None:
                top, hcount = holders_from_logs(rpc, addr, logs, total, pools); S["holders"] = f"rebuilt from {len(logs)} transfer logs"
                if not creator and logs:
                    first = min(logs, key=lambda l: (int(l["blockNumber"], 16), int(l["logIndex"], 16)))
                    tx = rpc.call("eth_getTransactionByHash", [first["transactionHash"]]) or {}
                    creator = (tx.get("from") or "").lower() or None
            else: S["holders"] = "token too old/busy to rebuild holders from logs" if cb else "creation block not found (needs archive RPC)"
        except OnchainError as e: S["holders"] = f"failed: {e}"
    if not creator:  # deployer from the creation block (cheap: ~26 archive getCode calls + 1 block of logs)
        try:
            cb = locals().get("cb") or find_creation_block(rpc, addr, head)
            if cb:
                lg = rpc.call("eth_getLogs", [{"address": addr, "fromBlock": _hx(cb), "toBlock": _hx(cb)}], urls=rpc.logs_urls) or []
                if lg:
                    tx = rpc.call("eth_getTransactionByHash", [lg[0]["transactionHash"]]) or {}
                    creator = (tx.get("from") or "").lower() or None
        except OnchainError: pass
    out["top10_pct"] = round(sum(p for _, p in top), 2) if top else (0.0 if top == [] else None)
    out["holders"] = hcount
    if creator and total:
        r = rpc.eth_call(addr, SEL["balanceOf"] + _a(creator))
        out["dev_pct"] = int(r, 16) / total * 100 if r and r != "0x" else None
    else: out["dev_pct"] = None
    out["creator"] = creator

    # --- LP lock (V2 pools only: LP is an ERC-20; CL/V3 positions are NFTs) ---
    best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0) if pairs else None
    if best:
        kind = pool_kind(rpc, best["pairAddress"])
        if kind == "v2":
            pa = best["pairAddress"].lower(); lts = rpc.eth_call(pa, SEL["totalSupply"]); lt = int(lts, 16) if lts and lts != "0x" else 0
            lockers = {x.lower() for x in cc.get("lp_lockers", [])}
            if lt:
                locked = 0
                for a in DEAD | lockers:
                    r = rpc.eth_call(pa, SEL["balanceOf"] + _a(a)); locked += int(r, 16) if r and r != "0x" else 0
                if cc.get("blockscout"):
                    hl, _ = blockscout_holders(cc["blockscout"], pa)
                    for a, v, isc, name in hl or []:
                        if a not in DEAD and a not in lockers and name and "lock" in name.lower(): locked += v
                lp_locked = locked / lt * 100
            S["lp"] = f"{best.get('dexId')} v2 LP: burned + known lockers"
        else: S["lp"] = f"{best.get('dexId')} is a concentrated-liquidity pool (LP is NFTs), lock can't be read"
    out["lp_locked_pct"] = round(lp_locked, 2) if lp_locked is not None else None

    # --- honeypot ---
    hp, note = honeypot(rpc, pairs, cc["wrapped_native"], addr, cfg.get("ticket_usd", 25))
    out["sim"] = hp; S["honeypot_sim"] = (f"{hp['dex']} {hp['kind']} pool, stage {hp['stage']}" if hp else "not run") + (f" ({note})" if note else "")
    out["honeypot"] = out["cannot_sell_all"] = out["cannot_buy"] = None; out["buy_tax"] = out["sell_tax"] = None
    if hp and hp["stage"] not in (1, 2):
        st = hp["stage"]
        out["cannot_buy"] = st == 3
        out["buy_tax"] = round(max(0.0, (1 - hp["buy_got"] / hp["buy_out"]) * 100), 2) if hp["buy_out"] else None
        probe_tax = max(0.0, (1 - hp["probe_got"] / hp["probe_sent"]) * 100) if hp["probe_sent"] else 0.0
        if st == 0:
            pool_tax = max(0.0, (1 - hp["pool_got"] / hp["sell_sent"]) * 100) if hp["sell_sent"] and hp["pool_got"] else 0.0
            out["sell_tax"] = round(max(pool_tax, probe_tax), 2); out["honeypot"] = False; out["cannot_sell_all"] = False
            out["round_trip_loss_pct"] = round((1 - hp["sell_got"] / hp["amount_in"]) * 100, 2)
            if out["round_trip_loss_pct"] > cfg.get("thresholds", {}).get("max_round_trip_loss_pct", 40): out["honeypot"] = True
        elif st in (4, 5, 6, 7):
            out["honeypot"] = True; out["cannot_sell_all"] = True; out["sell_tax"] = 100.0 if st != 6 or not probe_tax else probe_tax
    elif hp and hp["stage"] == 2:
        out["cannot_buy"] = None  # buy reverts can be a pool quirk, not proof
    out["symbol"] = None; out["in_cex"] = False; out["rpc_calls"] = rpc.calls
    return out
