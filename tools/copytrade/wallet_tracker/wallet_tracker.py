#!/usr/bin/env python3
"""Multi-chain wallet tracker: watches wallets for token swaps and runs token_check on new buys."""
import argparse, json, os, re, subprocess, sys, time
from datetime import datetime, timezone, timedelta
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LAGOS = timezone(timedelta(hours=1), "WAT")
TRANSFER = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
EVM_CHAINS = ["ethereum", "base", "bsc", "arbitrum", "robinhood"]
ALIASES = {"sol": "solana", "eth": "ethereum", "bnb": "bsc", "arb": "arbitrum", "rh": "robinhood", "robinhoodchain": "robinhood"}
S = requests.Session(); S.headers["User-Agent"] = "wallet-tracker/1.0"


def log(*a):
    print(*a, file=sys.stderr)


def load(path, default):
    try:
        with open(path) as f: return json.load(f)
    except FileNotFoundError: return default


def save(path, obj):
    tmp = path + ".tmp"
    with open(tmp, "w") as f: json.dump(obj, f, indent=2)
    os.replace(tmp, path)


CFG = load(os.path.join(HERE, "config.json"), {})
WALLETS = os.path.join(HERE, "wallets.json")
STATE = os.path.join(HERE, "state")


def state_path(w): return os.path.join(STATE, f"{w['chain']}_{w['address']}.json")


def fmt_time(ts): return datetime.fromtimestamp(ts, LAGOS).strftime("%Y-%m-%d %H:%M WAT") if ts else "?"


# ---------------- HTTP helpers ----------------
def post_json(url, payload, tries=5):
    delay = 1.0
    for i in range(tries):
        try:
            r = S.post(url, json=payload, timeout=30)
            if r.status_code == 429 or r.status_code >= 500:
                raise IOError(f"HTTP {r.status_code}")
            j = r.json()
            err = j.get("error") if isinstance(j, dict) else None
            if err and ("rate" in str(err).lower() or "too many" in str(err).lower() or err.get("code") in (429, -32005, -32029)):
                raise IOError(str(err))
            return j
        except (IOError, requests.RequestException, ValueError) as e:
            if i == tries - 1: raise IOError(f"{url}: {e}")
            time.sleep(delay); delay *= 2


def get_json(url, params=None, tries=4):
    delay = 1.0
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30, headers={"Accept": "application/json"})
            if r.status_code == 429 or r.status_code >= 500: raise IOError(f"HTTP {r.status_code}")
            r.raise_for_status(); return r.json()
        except (IOError, requests.RequestException, ValueError) as e:
            if i == tries - 1: raise IOError(f"{url}: {e}")
            time.sleep(delay); delay *= 2


# ---------------- Solana ----------------
class SolRPC:
    def __init__(self):
        self.c = CFG["solana"]; self.rpcs = self.c["rpcs"]

    def call(self, method, params):
        last = None
        for url in self.rpcs:
            try:
                j = post_json(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                time.sleep(self.c.get("sleep_s", 0.35))
                if "error" in j: last = j["error"]; continue
                return j["result"]
            except IOError as e: last = e
        raise IOError(f"solana {method}: {last}")


def sol_parse_tx(tx, wallet, sig):
    if not tx or tx["meta"].get("err"): return []
    meta = tx["meta"]; quotes = CFG["solana"]["quote_mints"]
    # only txs the wallet signed: copy-trade bots reference famous wallets in thousands of txs they did not sign
    if not any(isinstance(k, dict) and k.get("signer") and k.get("pubkey") == wallet for k in tx["transaction"]["message"]["accountKeys"]):
        return []
    delta, nft = {}, set()
    for side, sign in (("preTokenBalances", -1), ("postTokenBalances", 1)):
        for b in meta.get(side) or []:
            if b.get("owner") != wallet: continue
            if b["uiTokenAmount"].get("decimals") == 0: nft.add(b["mint"])
            amt = float(b["uiTokenAmount"].get("uiAmountString") or 0)
            delta[b["mint"]] = delta.get(b["mint"], 0) + sign * amt
    keys = [k["pubkey"] if isinstance(k, dict) else k for k in tx["transaction"]["message"]["accountKeys"]]
    sol = 0.0
    if wallet in keys:
        i = keys.index(wallet)
        sol = (meta["postBalances"][i] - meta["preBalances"][i]) / 1e9
        if i == 0: sol += meta.get("fee", 0) / 1e9  # ignore the network fee
    wsol = "So" + "1" * 40 + "2"  # wrapped SOL mint
    delta[wsol] = delta.get(wsol, 0) + sol
    # ignore dust: rent/fee-sized SOL moves and NFTs / 0-decimal tokens
    delta = {m: d for m, d in delta.items() if abs(d) > (CFG["solana"].get("min_sol_leg", 0.005) if m == wsol else 1e-9) and m not in nft}
    base = {m: d for m, d in delta.items() if m not in quotes}
    out = []
    for m, d in base.items():
        opp = [(quotes.get(x, x), abs(v)) for x, v in delta.items() if x != m and (v > 0) != (d > 0)]
        if not opp: continue  # one-way move = transfer, not a swap
        oq = [o for o in opp if o[0] in quotes.values()]
        out.append({"side": "BUY" if d > 0 else "SELL", "token": m, "amount": abs(d), "paid": (oq or opp)[0],
                    "tx": sig, "time": tx.get("blockTime"), "link": f"https://solscan.io/tx/{sig}"})
    return out


def sol_fetch(w, st, backfill):
    rpc = SolRPC(); addr = w["address"]; maxtx = CFG["solana"]["max_tx_per_scan"]
    if not st.get("last_sig") and not backfill:
        sigs = rpc.call("getSignaturesForAddress", [addr, {"limit": 1}])
        return [], {"last_sig": sigs[0]["signature"] if sigs else None, "last_slot": sigs[0]["slot"] if sigs else None, "baselined": int(time.time())}
    params = {"limit": 1000}; pages = 0
    if st.get("last_sig") and not backfill: params["until"] = st["last_sig"]
    swaps, newest, newest_slot, before, seen = [], None, None, None, 0
    while True:
        p = dict(params)
        if before: p["before"] = before
        sigs = rpc.call("getSignaturesForAddress", [addr, p])
        if not sigs: break
        if not newest: newest, newest_slot = sigs[0]["signature"], sigs[0].get("slot")
        pages += 1
        for s in sigs:
            if s.get("err"): continue  # failed txs (bots spam these) are skipped without a fetch
            seen += 1
            tx = rpc.call("getTransaction", [s["signature"], {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 1}])
            swaps += sol_parse_tx(tx, addr, s["signature"])
            if backfill and len({x["tx"] for x in swaps}) >= backfill: break
            if seen >= maxtx * (3 if backfill else 1): break
        if backfill and len({x["tx"] for x in swaps}) >= backfill: break
        if seen >= maxtx * (3 if backfill else 1) or len(sigs) < p["limit"] or pages >= CFG["solana"].get("max_sig_pages", 20):
            if seen >= maxtx and not backfill: log(f"[{w['label']}] capped at {maxtx} txs this scan")
            break
        before = sigs[-1]["signature"]
    if backfill:
        keep = []; txs = []
        for s in swaps:
            if s["tx"] not in txs:
                if len(txs) >= backfill: continue
                txs.append(s["tx"])
            keep.append(s)
        swaps = keep
    return swaps, {"last_sig": newest or st.get("last_sig"), "last_slot": newest_slot or st.get("last_slot"), "source": "rpc"}



# ---------------- Solana via Helius (optional, HELIUS_API_KEY) ----------------
HELIUS_CREDITS = {"calls": 0, "credits": 0}


def helius_call(method, params):
    key = os.environ.get("HELIUS_API_KEY")
    url = CFG["solana"].get("helius_rpc", "https://mainnet.helius-rpc.com/") + "?api-key=" + key
    try:
        r = S.post(url, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, timeout=60)
        if r.status_code == 429 or r.status_code >= 500: raise IOError(f"HTTP {r.status_code}")
        j = r.json()
    except (IOError, requests.RequestException, ValueError) as e:
        raise IOError(f"helius {method}: {type(e).__name__} {str(e).split('api-key')[0][:120]}")  # never leak the key
    if "error" in j: raise IOError(f"helius {method}: {j['error'].get('message')}")
    HELIUS_CREDITS["calls"] += 1
    n = len(j["result"].get("data", [])) if isinstance(j.get("result"), dict) else 0
    HELIUS_CREDITS["credits"] += max(10, -(-n // 100) * 10) if method == "getTransactionsForAddress" else 1
    return j["result"]


def helius_page(addr, filters, order, limit, token=None):
    cfg = {"transactionDetails": "full", "encoding": "jsonParsed", "maxSupportedTransactionVersion": 1,
           "sortOrder": order, "limit": limit,
           # succeeded only + wallet's own token-account transfers: drops failed/spam bot txs at the source
           "filters": dict({"status": "succeeded", "tokenAccounts": "balanceChanged", "tokenTransfer": {"direction": CFG["solana"].get("helius_direction", "out")}}, **filters)}
    # amount floor (raw units) drops address-poisoning dust transfers that otherwise flood real wallets
    if token: cfg["paginationToken"] = token
    return helius_call("getTransactionsForAddress", [addr, cfg])


def helius_fetch(w, st, backfill):
    addr = w["address"]; hc = CFG["solana"]; lim = hc.get("helius_page_size", 100); maxp = hc.get("helius_max_pages", 5)
    def sig(t): return t["transaction"]["signatures"][0]
    if not st.get("last_slot") and st.get("last_sig") and not backfill:  # migrate RPC-era state
        t = helius_call("getTransaction", [st["last_sig"], {"maxSupportedTransactionVersion": 1}])
        st["last_slot"] = t["slot"] if t else None
    if not st.get("last_slot") and not backfill:
        d = helius_page(addr, {}, "desc", 1)["data"]
        return [], {"last_sig": sig(d[0]) if d else None, "last_slot": d[0]["slot"] if d else None, "baselined": int(time.time()), "source": "helius"}
    swaps, newest, token = [], None, None
    for _ in range(maxp):
        if backfill: res = helius_page(addr, {}, "desc", lim, token)
        else: res = helius_page(addr, {"slot": {"gte": st["last_slot"]}}, "asc", lim, token)
        for t in res["data"]:
            if not backfill and sig(t) == st.get("last_sig"): continue
            if not backfill or not newest or t["slot"] >= newest[1]: newest = newest if (backfill and newest) else (sig(t), t["slot"])
            swaps += sol_parse_tx(t, addr, sig(t))
            if backfill and len({x["tx"] for x in swaps}) >= backfill: break
        token = res.get("paginationToken")
        if not token or (backfill and len({x["tx"] for x in swaps}) >= backfill): break
    else:
        log(f"[{w['label']}] helius page cap ({maxp}) reached")
    if backfill:
        txs = []
        for x in swaps:
            if x["tx"] not in txs: txs.append(x["tx"])
        swaps = [x for x in swaps if x["tx"] in txs[:backfill]]
        top = helius_page(addr, {}, "desc", 1)["data"]  # baseline = newest tx
        newest = (sig(top[0]), top[0]["slot"]) if top else newest
    elif res["data"]:
        last = res["data"][-1]; newest = (sig(last), last["slot"])
    return swaps, {"last_sig": newest[0] if newest else st.get("last_sig"), "last_slot": newest[1] if newest else st.get("last_slot"), "source": "helius"}


def sol_fetch_any(w, st, backfill):
    if os.environ.get("HELIUS_API_KEY"):
        try: return helius_fetch(w, dict(st), backfill)
        except Exception as e: log(f"[{w['label']}] Helius failed ({str(e)[:150]}); falling back to public RPC")
    return sol_fetch(w, st, backfill)


# ---------------- price at time of trade ----------------
_SOLPX = {}


def sol_usd_at(ts):
    m = int(ts) // 60 * 60
    if m not in _SOLPX:
        try:
            j = get_json("https://api.coinbase.com/api/v3/brokerage/market/products/SOL-USD/candles",
                         {"start": m - 60, "end": m + 60, "granularity": "ONE_MINUTE"})
            c = sorted(j["candles"], key=lambda c: abs(int(c["start"]) - m))
            _SOLPX[m] = float(c[0]["close"]) if c else None
        except Exception: _SOLPX[m] = None
    return _SOLPX[m]


def trade_usd(s):
    """USD from the swap's quote leg at fill time (USD stables 1:1, SOL via Coinbase 1m candle)."""
    if not s.get("paid") or not s.get("time"): return None
    sym, amt = s["paid"]
    if sym in ("USDC", "USDT", "USD1"): return amt
    if sym == "SOL":
        px = sol_usd_at(s["time"]); return amt * px if px else None
    return None


# ---------------- EVM ----------------
def topic(addr): return "0x" + "0" * 24 + addr[2:].lower()


class EvmRPC:
    def __init__(self, chain):
        self.c = CFG["evm"][chain]; self.chain = chain

    def call(self, method, params, need_range=None):
        last = None
        for r in self.c["rpcs"]:
            if need_range is not None and r["max_range"] and need_range > r["max_range"]: continue
            if need_range is not None and r["max_range"] == 0: continue
            try:
                j = post_json(r["url"], {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
                if "error" in j: last = j["error"]; continue
                return j["result"]
            except IOError as e: last = e
        raise IOError(f"{self.chain} {method}: {last}")

    def chunk(self):
        rs = [r["max_range"] for r in self.c["rpcs"] if r["max_range"]]
        return max(rs) if rs else 100

    def head(self): return int(self.call("eth_blockNumber", []), 16)

    def logs(self, wallet, frm, to):
        out = []
        for t in ([TRANSFER, topic(wallet)], [TRANSFER, None, topic(wallet)]):
            out += self.call("eth_getLogs", [{"fromBlock": hex(frm), "toBlock": hex(to), "topics": t}], need_range=to - frm + 1)
        return out


DEC_CACHE, SYM_CACHE = {}, {}


def evm_decimals(rpc, token):
    k = (rpc.chain, token)
    if k not in DEC_CACHE:
        try: DEC_CACHE[k] = int(rpc.call("eth_call", [{"to": token, "data": "0x313ce567"}, "latest"]), 16)
        except Exception: DEC_CACHE[k] = 18
    return DEC_CACHE[k]


def evm_build_swaps(rpc, wallet, transfers):
    """transfers: list of dicts {tx, token, from, to, raw, block, time}"""
    wallet = wallet.lower(); quotes = {k.lower(): v for k, v in rpc.c["quotes"].items()}
    by_tx = {}
    for t in transfers: by_tx.setdefault(t["tx"], []).append(t)
    out = []
    for h, ts in by_tx.items():
        tx = rpc.call("eth_getTransactionByHash", [h]) or {}
        if (tx.get("from") or "").lower() != wallet: continue  # only txs the wallet signed (skips airdrops/spam)
        delta = {}
        for t in ts:
            amt = t["raw"] / 10 ** (t.get("decimals") if t.get("decimals") is not None else evm_decimals(rpc, t["token"]))
            if t["to"] == wallet: delta[t["token"]] = delta.get(t["token"], 0) + amt
            if t["from"] == wallet: delta[t["token"]] = delta.get(t["token"], 0) - amt
        native_out = int(tx.get("value") or "0x0", 16) / 1e18
        base = {m: d for m, d in delta.items() if m not in quotes and abs(d) > 0}
        qleg = [(quotes[m], abs(d)) for m, d in delta.items() if m in quotes and abs(d) > 0]
        if native_out > 0: qleg.append((rpc.c["native"], native_out))
        tstamp = ts[0].get("time")
        if tstamp is None:
            try: tstamp = int(rpc.call("eth_getBlockByNumber", [hex(ts[0]["block"]), False])["timestamp"], 16)
            except Exception: tstamp = None
        for m, d in base.items():
            opp = qleg + [(x, v) for x, v in base.items() if x != m and (v > 0) != (d > 0)]
            # sells usually receive native via router unwrap (not visible as a transfer) -> allow SELL without visible quote leg
            if not opp and d > 0: continue
            out.append({"side": "BUY" if d > 0 else "SELL", "token": m, "amount": abs(d), "paid": qleg[0] if qleg else None,
                        "tx": h, "time": tstamp, "block": ts[0]["block"], "link": rpc.c["explorer_tx"] + h,
                        "symbol_hint": ts[0].get("symbol") if ts[0]["token"] == m else None})
    out.sort(key=lambda s: s["block"])
    return out


def logs_to_transfers(logs):
    tr = []
    for l in logs:
        if len(l["topics"]) != 3 or l["data"] in ("0x", ""): continue  # ERC-721 has 4 topics
        tr.append({"tx": l["transactionHash"], "token": l["address"].lower(), "from": "0x" + l["topics"][1][-40:].lower(),
                   "to": "0x" + l["topics"][2][-40:].lower(), "raw": int(l["data"][:66], 16), "block": int(l["blockNumber"], 16)})
    # de-dup (wallet->wallet self transfers would be fetched twice)
    seen, out = set(), []
    for t in tr:
        k = (t["tx"], t["token"], t["from"], t["to"], t["raw"])
        if k not in seen: seen.add(k); out.append(t)
    return out


def etherscan_transfers(chain, wallet, startblock, limit):
    key = os.environ.get("ETHERSCAN_API_KEY")
    if not key: return None
    j = get_json("https://api.etherscan.io/v2/api", {"chainid": CFG["evm"][chain]["chain_id"], "module": "account", "action": "tokentx",
                 "address": wallet, "startblock": startblock, "endblock": 99999999, "page": 1, "offset": limit, "sort": "desc", "apikey": key})
    if j.get("status") != "1":
        if "No transactions" in str(j.get("message")): return []
        log(f"etherscan {chain}: {j.get('result') or j.get('message')} -> falling back"); return None
    return [{"tx": t["hash"], "token": t["contractAddress"].lower(), "from": t["from"].lower(), "to": t["to"].lower(),
             "raw": int(t["value"]), "decimals": int(t["tokenDecimal"] or 18), "symbol": t["tokenSymbol"],
             "block": int(t["blockNumber"]), "time": int(t["timeStamp"])} for t in j["result"]]


def blockscout_transfers(chain, wallet, startblock, limit):
    bs = CFG["evm"][chain].get("blockscout")
    if not bs: return None
    out, params = [], {"type": "ERC-20"}
    for _ in range(10):
        try: j = get_json(f"{bs}/api/v2/addresses/{wallet}/token-transfers", params)
        except IOError as e: log(f"blockscout {chain}: {e} -> falling back"); return None
        for it in j.get("items", []):
            if it["block_number"] < startblock: return out
            tok = it["token"]; tot = it.get("total") or {}
            if tot.get("value") is None: continue
            ts = int(datetime.fromisoformat(it["timestamp"].replace("Z", "+00:00")).timestamp())
            out.append({"tx": it["transaction_hash"], "token": tok["address_hash"].lower() if "address_hash" in tok else tok["address"].lower(),
                        "from": it["from"]["hash"].lower(), "to": it["to"]["hash"].lower(), "raw": int(tot["value"]),
                        "decimals": int(tot.get("decimals") or tok.get("decimals") or 18), "symbol": tok.get("symbol"),
                        "block": it["block_number"], "time": ts})
        if len({t["tx"] for t in out}) >= limit or not j.get("next_page_params"): break
        params = dict({"type": "ERC-20"}, **j["next_page_params"])
    return out


BACKFILL_DAYS = [0]


def _evm_block_ts(rpc, b):
    return int(rpc.call("eth_getBlockByNumber", [hex(b), False])["timestamp"], 16)


def evm_fetch(w, st, backfill):
    chain, addr = w["chain"], w["address"].lower(); rpc = EvmRPC(chain); head = rpc.head()
    if not st.get("last_block") and not backfill:
        return [], {"last_block": head, "baselined": int(time.time())}
    start = (st.get("last_block") or 0) + 1 if not backfill else 0
    # indexed sources first (fast, deep history), RPC logs as the keyless fallback
    for src in (etherscan_transfers, blockscout_transfers):
        tr = src(chain, addr, start, 200 if backfill else 1000)
        if tr is not None:
            if backfill:
                txs = []
                for t in tr:  # desc order
                    if t["tx"] not in txs: txs.append(t["tx"])
                swaps = []
                # build swaps progressively until N found
                for i in range(0, len(txs), 10):
                    sel = set(txs[: i + 10])
                    swaps = evm_build_swaps(rpc, addr, [t for t in tr if t["tx"] in sel])
                    if len({s["tx"] for s in swaps}) >= backfill: break
                keep = sorted({s["tx"]: s["block"] for s in swaps}.items(), key=lambda x: -x[1])[:backfill]
                swaps = [s for s in swaps if s["tx"] in dict(keep)]
            else:
                swaps = evm_build_swaps(rpc, addr, [t for t in tr if t["block"] > (st.get("last_block") or 0)])
            return swaps, {"last_block": head, "source": src.__name__.split("_")[0]}
    step = rpc.chunk(); trs = []
    if backfill:
        to = head
        since_ts = (time.time() - BACKFILL_DAYS[0] * 86400) if BACKFILL_DAYS[0] else None; n = 0
        for _ in range(CFG.get("evm_backfill_max_chunks", 300) if not since_ts else 10**6):
            frm = max(0, to - step + 1)
            trs = logs_to_transfers(rpc.logs(addr, frm, to)) + trs
            # count candidate txs cheaply; build swaps (tx/decimals lookups) once at the end, not per chunk
            if len({t["tx"] for t in trs}) >= backfill: break
            if since_ts and frm > 0 and _evm_block_ts(rpc, frm) < since_ts: break
            to = frm - 1
        swaps = evm_build_swaps(rpc, addr, trs) if trs else []
        keep = set([t for t, _ in sorted({s["tx"]: s["block"] for s in swaps}.items(), key=lambda x: -x[1])[:backfill]])
        return [s for s in swaps if s["tx"] in keep], {"last_block": head, "source": "rpc"}
    frm = start; maxc = CFG.get("evm_max_blocks_per_scan_chunks", 60)
    if (head - frm) // step + 1 > maxc:
        log(f"[{w['label']}] {head - frm} blocks behind; scanning only the latest {maxc * step}")
        frm = head - maxc * step + 1
    while frm <= head:
        to = min(head, frm + step - 1)
        trs += logs_to_transfers(rpc.logs(addr, frm, to)); frm = to + 1
    return evm_build_swaps(rpc, addr, trs), {"last_block": head, "source": "rpc"}


# ---------------- enrichment ----------------
def dex_prices(chain, tokens):
    out = {}
    tokens = list(dict.fromkeys(tokens))
    for i in range(0, len(tokens), 30):
        try: pairs = get_json(f"{CFG['dexscreener_base']}/tokens/v1/{chain}/{','.join(tokens[i:i + 30])}")
        except IOError: continue
        for p in pairs or []:
            ba = p["baseToken"]["address"]; key = next((t for t in tokens if t.lower() == ba.lower()), None)
            if not key: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if key not in out or liq > out[key]["liq"]:
                out[key] = {"price": float(p.get("priceUsd") or 0), "symbol": p["baseToken"].get("symbol"), "liq": liq}
    return out


def run_token_check(token, chain):
    tc = CFG["token_check"]; path = os.path.normpath(os.path.join(HERE, tc["path"]))
    try:
        p = subprocess.run(["python3", path, token, "--chain", chain, "--json"] + tc.get("extra_args", []),
                           capture_output=True, text=True, timeout=tc.get("timeout_s", 120))
        r = json.loads(p.stdout)
        reasons = [x for x in (r.get("summary") or "").split("; ") if x]
        return {"verdict": r.get("verdict"), "score": r.get("score"), "reasons": reasons[:3],
                "kills": r.get("kills", []), "warnings": r.get("warnings", []), "exit_code": p.returncode, "symbol": r.get("symbol")}
    except Exception as e:
        return {"verdict": "ERROR", "score": None, "reasons": [str(e)[:200]], "exit_code": 3}


def fmt_amt(x):
    if x >= 1e9: return f"{x / 1e9:.2f}B"
    if x >= 1e6: return f"{x / 1e6:.2f}M"
    if x >= 1e3: return f"{x / 1e3:.2f}K"
    return f"{x:.4g}"


def alert_line(w, s):
    usd = (f"${s['usd']:,.0f} at fill" if s.get("usd_source") == "trade" else f"~${s['usd']:,.0f} now") if s.get("usd") is not None else "~$? (no price)"
    paid = f" for {fmt_amt(s['paid'][1])} {s['paid'][0]}" if s.get("paid") else ""
    verb = "bought" if s["side"] == "BUY" else "sold"
    line = (f"[{w['chain']}] {w['label']} {verb} {fmt_amt(s['amount'])} {s.get('symbol') or '?'} ({usd}){paid} "
            f"at {fmt_time(s['time'])} | token {s['token']} | {s['link']}")
    tc = s.get("token_check")
    if tc:
        line += f"\n    token_check: {tc['verdict']} (score {tc['score']})"
        if tc.get("reasons"): line += " - " + "; ".join(tc["reasons"])
    return line


def scan(args):
    wallets = load(WALLETS, [])
    if args.address: wallets = [w for w in wallets if w["address"] == args.address or w.get("label") == args.address]
    results, errors, tc_cache = [], [], {}
    for w in wallets:
        sp = state_path(w); st = load(sp, {})
        try:
            swaps, new_st = (sol_fetch_any if w["chain"] == "solana" else evm_fetch)(w, st, args.backfill)
        except Exception as e:
            errors.append({"wallet": w["label"], "chain": w["chain"], "error": str(e)[:300]}); continue
        st.update({k: v for k, v in new_st.items() if v is not None}); st["last_scan"] = int(time.time()); save(sp, st)
        if not swaps: continue
        dex = "solana" if w["chain"] == "solana" else CFG["evm"][w["chain"]]["dex"]
        prices = dex_prices(dex, [s["token"] for s in swaps])
        for s in swaps:
            p = prices.get(s["token"])
            s["symbol"] = (p or {}).get("symbol") or s.pop("symbol_hint", None)
            s.pop("symbol_hint", None)
            tu = trade_usd(s) if w["chain"] == "solana" else None
            if tu is not None: s["usd"], s["usd_source"] = round(tu, 2), "trade"
            else:
                s["usd"] = round(s["amount"] * p["price"], 2) if p and p["price"] else None
                s["usd_source"] = "dexscreener_now" if s["usd"] is not None else None
            if s["usd"] is not None and s["usd"] < CFG.get("min_usd_alert", 0): continue
            if s["side"] == "BUY" and not args.no_check:
                k = (dex, s["token"])
                if k not in tc_cache: tc_cache[k] = run_token_check(s["token"], dex)
                s["token_check"] = tc_cache[k]
                if not s["symbol"]: s["symbol"] = tc_cache[k].get("symbol")
            s["time_wat"] = fmt_time(s["time"])
            results.append({"wallet": w["address"], "label": w["label"], "chain": w["chain"], **s})
    results.sort(key=lambda r: r.get("time") or 0)
    if args.json:
        if results or errors:
            print(json.dumps({"scanned_at": datetime.now(LAGOS).isoformat(), "swaps": results, "errors": errors}, indent=2))
    else:
        for r in results: print(alert_line({"chain": r["chain"], "label": r["label"]}, r))
        for e in errors: log(f"ERROR [{e['chain']}] {e['wallet']}: {e['error']}")
    if HELIUS_CREDITS["calls"]: log(f"helius: {HELIUS_CREDITS['calls']} calls, ~{HELIUS_CREDITS['credits']} credits") if args.verbose else None
    return 3 if errors and not results else 0


def norm_chain(c, addr):
    if c: c = ALIASES.get(c.lower(), c.lower())
    elif addr.startswith("0x"): sys.exit("EVM address: pass --chain ethereum|base|bsc|arbitrum|robinhood")
    else: c = "solana"
    if c != "solana" and c not in EVM_CHAINS: sys.exit(f"unsupported chain {c}")
    if c == "solana" and not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", addr): sys.exit("not a Solana address")
    if c != "solana" and not re.fullmatch(r"0x[0-9a-fA-F]{40}", addr): sys.exit("not an EVM address")
    return c


def main():
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add"); a.add_argument("address"); a.add_argument("--chain"); a.add_argument("--label")
    r = sub.add_parser("remove"); r.add_argument("address", help="address or label")
    sub.add_parser("list")
    s = sub.add_parser("scan"); s.add_argument("address", nargs="?", help="only this address/label")
    s.add_argument("--json", action="store_true"); s.add_argument("--backfill", type=int, default=0, metavar="N")
    s.add_argument("--backfill-days", type=float, default=0, help="EVM backfill: walk back this many days (N still caps the swap count)")
    s.add_argument("--no-check", action="store_true", help="skip token_check on buys")
    s.add_argument("--verbose", action="store_true", help="print source/credit stats to stderr")
    args = ap.parse_args(); os.makedirs(STATE, exist_ok=True)
    BACKFILL_DAYS[0] = getattr(args, "backfill_days", 0) or 0
    wallets = load(WALLETS, [])
    if args.cmd == "add":
        c = norm_chain(args.chain, args.address)
        addr = args.address.lower() if c != "solana" else args.address
        if any(w["address"] == addr and w["chain"] == c for w in wallets): sys.exit("already tracked")
        wallets.append({"address": addr, "chain": c, "label": args.label or addr[:6], "added": datetime.now(LAGOS).isoformat(timespec="seconds")})
        save(WALLETS, wallets); print(f"added {addr} on {c} as {args.label or addr[:6]} (first scan sets the baseline)")
    elif args.cmd == "remove":
        keep = [w for w in wallets if args.address not in (w["address"], w["label"], w["address"].lower())]
        for w in wallets:
            if w not in keep and os.path.exists(state_path(w)): os.remove(state_path(w))
        if len(keep) == len(wallets): sys.exit("not found")
        save(WALLETS, keep); print(f"removed {len(wallets) - len(keep)} wallet(s)")
    elif args.cmd == "list":
        for w in wallets:
            st = load(state_path(w), {})
            last = st.get("last_sig") or st.get("last_block") or "no baseline yet"
            print(f"{w['label']:<14} {w['chain']:<10} {w['address']}  last-seen: {last}  last scan: {fmt_time(st.get('last_scan'))}")
        if not wallets: print("watchlist is empty")
    else:
        sys.exit(scan(args))


if __name__ == "__main__":
    main()
