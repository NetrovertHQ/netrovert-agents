#!/usr/bin/env python3
"""X call tracker: log token calls from X accounts and grade them against price action."""
import argparse, glob, json, os, re, shutil, statistics as stt, subprocess, sys, time
from datetime import datetime, timezone, timedelta
import requests
HERE = os.path.dirname(os.path.abspath(__file__)); CFG = json.load(open(os.path.join(HERE, "config.json")))
LAGOS = timezone(timedelta(hours=1), "WAT")
CALLERS, CALLS, STATE = (os.path.join(HERE, f) for f in ("callers.json", "calls.json", "state.json"))
INBOX = os.path.join(HERE, "inbox"); S = requests.Session(); S.headers["User-Agent"] = "x-calls/1.0"
SOL_RE = re.compile(r"(?<![A-Za-z0-9/])([1-9A-HJ-NP-Za-km-z]{32,44})(?![A-Za-z0-9])")
EVM_RE = re.compile(r"\b(0x[0-9a-fA-F]{40})\b")
TICK_RE = re.compile(r"(?<![\w$])\$([A-Za-z][A-Za-z0-9]{1,11})\b")
LINK_RE = re.compile(r"(?:dexscreener\.com/([a-z0-9]+)/|pump\.fun/(?:coin/)?|gmgn\.ai/([a-z]+)/token/|birdeye\.so/token/)([1-9A-HJ-NP-Za-km-z]{32,44}|0x[0-9a-fA-F]{40})")
def log(*a): print(*a, file=sys.stderr)
def load(p, d):
    try: return json.load(open(p))
    except FileNotFoundError: return d
def save(p, o):
    json.dump(o, open(p + ".tmp", "w"), indent=2); os.replace(p + ".tmp", p)
def ts(iso): return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())
def wat(t): return datetime.fromtimestamp(t, LAGOS).strftime("%Y-%m-%d %H:%M WAT")


def get(url, params=None, tries=4):
    d = 2
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30, headers={"Accept": "application/json"})
            if r.status_code == 429 or r.status_code >= 500: raise IOError(r.status_code)
            if r.status_code == 404: return None
            r.raise_for_status(); return r.json()
        except (IOError, requests.RequestException, ValueError) as e:
            if i == tries - 1: raise IOError(f"{url}: {e}")
            time.sleep(d); d *= 2


# ---------------- resolution ----------------
_DS = {}
def ds_token(addr):
    """Best pair for a token address on any chain (DexScreener)."""
    if addr not in _DS:
        j = get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}") or {}
        pairs = [p for p in j.get("pairs") or [] if p["baseToken"]["address"].lower() == addr.lower()]
        pairs.sort(key=lambda p: -((p.get("liquidity") or {}).get("usd") or 0))
        _DS[addr] = pairs[0] if pairs else None
    return _DS[addr]


def ds_ticker(sym):
    j = get("https://api.dexscreener.com/latest/dex/search", {"q": sym}) or {}
    by = {}
    for p in j.get("pairs") or []:
        if p["baseToken"]["symbol"].upper() != sym.upper(): continue
        k = (p["chainId"], p["baseToken"]["address"]); l = (p.get("liquidity") or {}).get("usd") or 0
        by[k] = max(by.get(k, 0), l)
    if not by: return None, "no match"
    ranked = sorted(by.items(), key=lambda x: -x[1]); tot = sum(by.values()) or 1
    (chain, addr), liq = ranked[0]
    if liq < CFG["ticker_min_liquidity_usd"]: return None, f"top match liquidity ${liq:,.0f} too low"
    if liq / tot < CFG["ticker_dominance"]: return None, f"ambiguous: {len(by)} tokens named ${sym}"
    return (chain, addr), "ticker resolved"


def extract(text):
    """-> list of (kind, value, chain_hint)"""
    out, seen = [], set()
    for m in LINK_RE.finditer(text):
        a = m.group(3); c = m.group(1) or m.group(2)
        if a not in seen: seen.add(a); out.append(("link", a, {"sol": "solana", "eth": "ethereum"}.get(c, c)))
    for a in EVM_RE.findall(text):
        if a not in seen: seen.add(a); out.append(("ca", a, None))
    for a in SOL_RE.findall(text):
        if a not in seen and not a.startswith("http") and re.search(r"\d", a) and re.search(r"[a-z]", a) and re.search(r"[A-Z]", a):
            seen.add(a); out.append(("ca", a, "solana"))
    for t in TICK_RE.findall(text):
        if t.upper() not in CFG["ignore_tickers"] and t.upper() not in seen: seen.add(t.upper()); out.append(("ticker", t.upper(), None))
    return out


# ---------------- prices (GeckoTerminal) ----------------
_GT_T = [0.0]
def gt(path, params=None):
    w = CFG["gt_sleep_s"] - (time.time() - _GT_T[0])
    if w > 0: time.sleep(w)
    _GT_T[0] = time.time(); return get("https://api.geckoterminal.com/api/v2" + path, params)


def ohlcv(net, pool, frm, to, tf="hour"):
    """Candles [t,o,h,l,c,v] between frm..to (paged back from `to`)."""
    out, before = [], to
    while before > frm:
        j = gt(f"/networks/{net}/pools/{pool}/ohlcv/{tf}", {"aggregate": 1, "before_timestamp": before, "limit": 1000, "currency": "usd", "token": "base"})
        lst = ((j or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
        if not lst: break
        out += lst; oldest = min(c[0] for c in lst)
        if oldest >= before: break
        before = oldest
        if len(lst) < 1000: break
    return sorted({c[0]: c for c in out if frm <= c[0] <= to}.values())


def price_at(candles, t):
    prev = [c for c in candles if c[0] <= t]
    return (prev[-1][4] if prev else candles[0][1]) if candles else None


# ---------------- token_check ----------------
def token_check(addr, chain):
    p = os.path.normpath(os.path.join(HERE, CFG["token_check_path"]))
    try:
        r = subprocess.run(["python3", p, addr, "--chain", chain, "--json", "--no-narrative"], capture_output=True, text=True, timeout=150)
        j = json.loads(r.stdout); return {"verdict": j.get("verdict"), "score": j.get("score"), "summary": j.get("summary")}
    except Exception as e: return {"verdict": "ERROR", "score": None, "summary": str(e)[:150]}


# ---------------- commands ----------------
def cmd_add(a):
    c = load(CALLERS, []); h = a.handle.lstrip("@")
    if any(x["handle"].lower() == h.lower() for x in c): sys.exit("already added")
    c.append({"handle": h, "user_id": a.user_id, "wallet": a.wallet, "wallet_chain": a.wallet_chain if a.wallet else None, "tag": a.tag})
    save(CALLERS, c); print(f"added @{h}" + (" (user_id still needed: resolve with x get_users_by_username)" if not a.user_id else ""))


def cmd_list(a):
    st = load(STATE, {})
    for x in load(CALLERS, []):
        print(f"@{x['handle']:<18} id={x.get('user_id') or '?':<20} since_id={st.get(x['handle'], {}).get('since_id', '-'):<20} wallet={x.get('wallet') or '-'}")


def cmd_ingest(a):
    calls = load(CALLS, []); have = {(c["post_id"], c["token"]) for c in calls}; st = load(STATE, {})
    callers = {x["handle"].lower(): x for x in load(CALLERS, [])}; new = 0
    for f in sorted(glob.glob(os.path.join(INBOX, "*.json"))):
        j = load(f, {}); handle = j.get("_handle")
        users = {u["id"]: u["username"] for u in (j.get("includes") or {}).get("users", [])}
        for p in j.get("data") or []:
            h = handle or users.get(p.get("author_id"))
            if not h: continue
            if h.lower() not in callers: callers[h.lower()] = {"handle": h, "user_id": p.get("author_id")}
            s = st.setdefault(h, {}); s["since_id"] = str(max(int(s.get("since_id", 0)), int(p["id"])))
            text = p.get("note_tweet", {}).get("text") or p["text"]
            for e in (p.get("entities") or {}).get("urls") or []: text += " " + (e.get("expanded_url") or "")
            t_post = ts(p["created_at"])
            for kind, val, hint in extract(text):
                if kind == "ticker":
                    res, why = ds_ticker(val)
                    if not res:
                        if (p["id"], "$" + val) not in have:
                            calls.append({"caller": h, "post_id": p["id"], "url": f"https://x.com/{h}/status/{p['id']}", "time": t_post, "token": "$" + val,
                                          "status": "unresolved", "why": why, "text": text[:200]}); have.add((p["id"], "$" + val))
                        continue
                    chain, addr = res
                else:
                    pair = ds_token(val)
                    if not pair: continue  # not a token (wallet/tx/random base58)
                    chain, addr = pair["chainId"], pair["baseToken"]["address"]
                if (p["id"], addr) in have: continue
                pair = ds_token(addr)
                c = {"caller": h, "post_id": p["id"], "url": f"https://x.com/{h}/status/{p['id']}", "time": t_post, "time_wat": wat(t_post),
                     "kind": kind, "token": addr, "chain": chain, "symbol": pair["baseToken"]["symbol"] if pair else None,
                     "pool": pair["pairAddress"] if pair else None, "pair_created": (pair.get("pairCreatedAt") or 0) / 1000 if pair else None,
                     "status": "new", "text": text[:200], "likes": (p.get("public_metrics") or {}).get("like_count")}
                if c["pair_created"] and c["pair_created"] > t_post + 3600:
                    c["status"] = "unresolved"; c["why"] = "pair created after the post (different token with same name?)"
                else:
                    c["token_check"] = token_check(addr, chain)
                calls.append(c); have.add((p["id"], addr)); new += 1
        os.makedirs(os.path.join(INBOX, "processed"), exist_ok=True)
        shutil.move(f, os.path.join(INBOX, "processed", os.path.basename(f)))
    save(CALLS, calls); save(STATE, st); save(CALLERS, list(callers.values()))
    print(f"ingested {new} new calls; {len(calls)} total")


def grade_call(c):
    net = CFG["gt_networks"].get(c["chain"]); now = int(time.time()); t0 = c["time"]
    if not net or not c.get("pool"): c["status"] = "ungradable"; c["why"] = "no GeckoTerminal network/pool"; return
    end = min(now, t0 + 7 * 86400)
    cs = ohlcv(net, c["pool"], t0 - 3600, end)
    if not cs: c["status"] = "ungradable"; c["why"] = "no OHLCV"; return
    p0 = price_at(cs, t0); c["price_at_call"] = p0
    pair = ds_token(c["token"])
    if pair and pair.get("priceUsd") and pair.get("fdv"):
        c["fdv_at_call"] = round(pair["fdv"] * p0 / float(pair["priceUsd"]))  # supply x price at call
    def ret(h):
        if now < t0 + h * 3600: return None
        p = price_at(cs, t0 + h * 3600); return round((p / p0 - 1) * 100, 1) if p and p0 else None
    def peak(h):
        w = [x[2] for x in cs if t0 <= x[0] <= t0 + h * 3600]; return round(max(w) / p0, 2) if w and p0 else None
    c.update({"ret_1h": ret(1), "ret_24h": ret(24), "ret_7d": ret(168), "peak_24h": peak(24), "peak_7d": peak(168),
              "low_7d_pct": round((min([x[3] for x in cs if x[0] >= t0] or [p0]) / p0 - 1) * 100, 1) if p0 else None, "graded_at": now})
    killed = (c.get("token_check") or {}).get("verdict") == "KILL"
    if c["ret_24h"] is None and (c["peak_24h"] or 0) < CFG["win"]["peak_mult"]: c["status"] = "PENDING"
    elif (c["peak_24h"] or 0) >= CFG["win"]["peak_mult"] or (c["ret_24h"] or -999) >= CFG["win"]["ret24_pct"]: c["status"] = "WIN"
    elif (c["ret_24h"] is not None and c["ret_24h"] <= CFG["loss"]["ret24_pct"]) or (killed and (c["low_7d_pct"] or 0) <= CFG["loss"]["kill_drawdown_pct"]): c["status"] = "LOSS"
    else: c["status"] = "FLAT"


def self_buy(c, wallet):
    sys.path.insert(0, os.path.normpath(os.path.join(HERE, CFG["wallet_tracker_dir"])))
    import wallet_tracker as WT
    if not os.environ.get("HELIUS_API_KEY"): return None
    w = CFG["self_buy_window_h"] * 3600
    res = WT.helius_page(wallet, {"blockTime": {"gte": c["time"] - w, "lte": c["time"] + w}}, "asc", 100)
    sw = [s for t in res["data"] for s in WT.sol_parse_tx(t, wallet, t["transaction"]["signatures"][0]) if s["token"] == c["token"]]
    buys = [s["time"] for s in sw if s["side"] == "BUY"]; sells = [s["time"] for s in sw if s["side"] == "SELL"]
    r = {"first_buy_vs_post_min": round((min(buys) - c["time"]) / 60) if buys else None,
         "sold_within_24h_after_post": any(c["time"] <= x <= c["time"] + 86400 for x in sells), "helius_credits": WT.HELIUS_CREDITS["credits"]}
    r["flag"] = ("bought before posting, sold into followers" if buys and min(buys) < c["time"] and r["sold_within_24h_after_post"]
                 else "bought before posting" if buys and min(buys) < c["time"] else "bought after posting" if buys else "no buy seen ±72h")
    return r


def cmd_grade(a):
    calls = load(CALLS, []); callers = {x["handle"]: x for x in load(CALLERS, [])}; n = 0
    for c in calls:
        if c["status"] in ("unresolved", "ungradable"): continue
        if c.get("graded_at") and c["status"] in ("WIN", "LOSS", "FLAT") and c.get("ret_7d") is not None: continue
        try: grade_call(c); n += 1
        except Exception as e: log(f"grade {c['token']}: {e}")
        cw = callers.get(c["caller"], {})
        if cw.get("wallet") and cw.get("wallet_chain", "solana") == "solana" and c["chain"] == "solana" and "self_buy" not in c:
            try: c["self_buy"] = self_buy(c, cw["wallet"])
            except Exception as e: log(f"self-buy {c['caller']}: {e}")
        save(CALLS, calls)
    print(f"graded {n} calls")


def caller_stats(calls):
    g = [c for c in calls if c["status"] in ("WIN", "LOSS", "FLAT", "PENDING")]
    done = [c for c in g if c["status"] != "PENDING"]
    r24 = [c["ret_24h"] for c in g if c.get("ret_24h") is not None]; pk = [c["peak_7d"] for c in g if c.get("peak_7d")]
    tc = [c for c in g if c.get("token_check")]
    flags = []
    sb = [c["self_buy"]["flag"] for c in g if c.get("self_buy")]
    if any("sold into followers" in f for f in sb): flags.append("dumped on followers")
    elif any("before posting" in f for f in sb): flags.append("front-runs own calls")
    kill = round(100 * sum(c["token_check"]["verdict"] == "KILL" for c in tc) / len(tc)) if tc else None
    if kill is not None and kill >= 50: flags.append("mostly KILL tokens")
    if len(done) < 5: flags.append("small sample")
    return {"calls": len(g), "graded": len(done), "unresolved": sum(c["status"] == "unresolved" for c in calls),
            "hit_rate": round(100 * sum(c["status"] == "WIN" for c in done) / len(done)) if done else None,
            "median_24h": round(stt.median(r24), 1) if r24 else None, "avg_peak_7d": round(stt.mean(pk), 2) if pk else None,
            "kill_pct": kill, "flags": flags}


def cmd_report(a):
    calls = load(CALLS, []); by = {}
    for c in calls: by.setdefault(c["caller"], []).append(c)
    for x in load(CALLERS, []): by.setdefault(x["handle"], [])
    if a.handle:
        for c in sorted(by.get(a.handle.lstrip("@"), []), key=lambda c: c["time"]):
            tc = c.get("token_check") or {}
            print(f"{wat(c['time'])} {c['status']:<10} {c.get('symbol') or c['token']:<12} 1h {c.get('ret_1h')}% 24h {c.get('ret_24h')}% 7d {c.get('ret_7d')}% peak7d {c.get('peak_7d')}x "
                  f"| {tc.get('verdict', '-')} | {c['url']}" + (f" | self-buy: {c['self_buy']['flag']}" if c.get("self_buy") else "") + (f" | {c['why']}" if c.get("why") else ""))
        return
    rows = sorted(((h, caller_stats(cs)) for h, cs in by.items()), key=lambda x: (-(x[1]["hit_rate"] or -1), -(x[1]["median_24h"] or -999)))
    lines = ["| caller | calls (graded) | hit rate | median 24h | avg peak 7d | KILL % | unresolved | flags |", "|---|---|---|---|---|---|---|---|"]
    for h, s in rows:
        lines.append(f"| @{h} | {s['calls']} ({s['graded']}) | {s['hit_rate'] if s['hit_rate'] is not None else '-'}% | {s['median_24h']}% | {s['avg_peak_7d']}x | {s['kill_pct']}% | {s['unresolved']} | {', '.join(s['flags'])} |")
    out = "\n".join(lines); print(out)
    os.makedirs(os.path.join(HERE, "results"), exist_ok=True)
    open(os.path.join(HERE, "results", f"leaderboard_{datetime.now(LAGOS):%Y%m%d_%H%M}.md"), "w").write(out + "\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("add"); p.add_argument("handle"); p.add_argument("--wallet"); p.add_argument("--wallet-chain", default="solana")
    p.add_argument("--user-id"); p.add_argument("--tag")
    sub.add_parser("list"); sub.add_parser("ingest"); sub.add_parser("grade")
    r = sub.add_parser("report"); r.add_argument("handle", nargs="?")
    a = ap.parse_args(); {"add": cmd_add, "list": cmd_list, "ingest": cmd_ingest, "grade": cmd_grade, "report": cmd_report}[a.cmd](a)


if __name__ == "__main__":
    main()
