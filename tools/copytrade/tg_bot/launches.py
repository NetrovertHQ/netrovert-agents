"""Launch alerts ("sniping" without keys): find brand-new tokens on free sources, run our safety check, and tell
subscribers about the ones that pass the basics. Nobody's money moves: the card only has links to swap in your own wallet
and a Practice snipe button for fake money.
Sources (free): DexScreener latest token profiles + boosts, GeckoTerminal new pools, pump.fun graduations (unofficial, best effort)."""
import random
import json, os, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, wait
import requests
import gate

HERE = gate.HERE
SUBS = os.path.join(HERE, "launch_subs.json"); SEEN = os.path.join(HERE, "launch_seen.json"); CACHE = os.path.join(HERE, "launch_cache.json")
SHORT = {"sol": "solana", "rh": "robinhood", "hype": "hyperevm", "base": "base"}
LONG = {v: k for k, v in SHORT.items()}
GT_NET = {"solana": "solana", "robinhood": "robinhood", "hyperevm": "hyperevm", "base": "base"}
S = requests.Session(); S.headers["User-Agent"] = "netro-signal/1.0"
LOCK = threading.RLock(); STATE = {"last_cycle": None, "last_stats": None}


def cfg():
    c = gate.cfg()
    return {"every_s": c.get("launch_every_s", 180), "max_checks": c.get("launch_max_checks", 15), "min_liq": c.get("launch_min_liq_usd", 30000),
            "max_age_min": c.get("launch_max_age_min", 60), "per_hour": c.get("launch_max_per_hour", 6)}


def _get(url, timeout=12):
    try:
        r = S.get(url, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except Exception: return None


def _save(p, o):
    tmp = p + ".tmp"; json.dump(o, open(tmp, "w")); os.replace(tmp, p)


# ---------------- subscriptions ----------------
def subs():
    return gate.load(SUBS, {})


def sub_of(chat):
    s = subs().get(str(chat)); owner = gate.cfg().get("owner_chat_id")
    if s is None: s = {"on": chat == owner, "chains": list(SHORT.values()), "per_hour": cfg()["per_hour"], "sent": []}
    return s


def put_sub(chat, s):
    with LOCK:
        a = subs(); a[str(chat)] = s; _save(SUBS, a)


def command(chat, args):
    s = sub_of(chat); names = ", ".join(LONG.get(c, c) for c in s["chains"])
    if not args:
        return (f"🚀 Launch alerts are {'on' if s['on'] else 'off'} for you ({names}, up to {s['per_hour']} an hour).\n\n"
                "I look for brand-new tokens every few minutes, run our safety check, and only tell you about ones that aren't a clear rug, "
                f"have at least ${cfg()['min_liq']:,} in the pool and are under an hour old.\n\n"
                "/launches on or /launches off\n/launches chains sol rh hype base (pick any)\n/launches max 3 (alerts per hour)")
    a = args[0].lower()
    if a in ("on", "off"):
        s["on"] = a == "on"; put_sub(chat, s)
        return ("🚀 Launch alerts on. You'll get new tokens on " + names + ". New tokens are very risky, so start with /practice money.") if s["on"] else "🔕 Launch alerts off."
    if a == "chains":
        ch = [SHORT.get(x.lower(), gate.norm_chain(x)) for x in args[1:]]
        bad = [x for x, c in zip(args[1:], ch) if c not in LONG]
        if not ch or bad: return "Pick from: sol, rh, hype, base. Like /launches chains sol base"
        s["chains"] = list(dict.fromkeys(ch)); put_sub(chat, s)
        return "👍 Launch alerts will cover " + ", ".join(LONG[c] for c in s["chains"]) + "." + ("" if s["on"] else " Turn them on with /launches on")
    if a == "max":
        try: n = int(args[1]); assert 1 <= n <= 20
        except Exception: return "Pick a number from 1 to 20, like /launches max 3"
        s["per_hour"] = n; put_sub(chat, s); return f"👍 At most {n} launch alerts an hour."
    return "Try /launches on, /launches off, /launches chains sol base, or /launches max 3"


# ---------------- finding launches ----------------
def candidates():
    """{(chain, token)} from all free sources, chains we cover only."""
    out = set()
    for url in ("https://api.dexscreener.com/token-profiles/latest/v1", "https://api.dexscreener.com/token-boosts/latest/v1"):
        for x in _get(url) or []:
            if x.get("chainId") in GT_NET and x.get("tokenAddress"): out.add((x["chainId"], x["tokenAddress"]))
    for chain, net in GT_NET.items():
        j = _get(f"https://api.geckoterminal.com/api/v2/networks/{net}/new_pools?page=1") or {}
        quotes = {"solana": {"So" + "1" * 40 + "2"}}.get(chain, set())
        for p in j.get("data") or []:
            try: base = p["relationships"]["base_token"]["data"]["id"].split("_", 1)[1]
            except Exception: continue
            if base not in quotes: out.add((chain, base))
        time.sleep(2.2)  # GeckoTerminal free tier is ~30 calls/min
    pf = _get("https://frontend-api-v3.pump.fun/coins?sort=last_trade_timestamp&limit=50&complete=true&order=DESC") or []
    pf = pf if isinstance(pf, list) else pf.get("coins", [])
    for c in pf:
        if c.get("mint") and c.get("created_timestamp", 0) / 1000 > time.time() - 6 * 3600: out.add(("solana", c["mint"]))
    return out


def market(chain, tokens):
    """DexScreener best pair per token: {token: (liq_usd, age_min, symbol)}."""
    out = {}; tokens = list(tokens)
    for i in range(0, len(tokens), 30):
        for p in _get(f"https://api.dexscreener.com/tokens/v1/{chain}/" + ",".join(tokens[i:i + 30])) or []:
            t = next((x for x in tokens if x.lower() == (p.get("baseToken") or {}).get("address", "").lower()), None)
            if not t: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0; born = p.get("pairCreatedAt")
            if t not in out or liq > out[t][0]:
                out[t] = (liq, (time.time() * 1000 - born) / 60000 if born else None, (p.get("baseToken") or {}).get("symbol"))
    return out


def check(chain, token):
    tc = gate.token_check(token, chain, narrative=False)
    return tc, gate.gate(token, chain, tc=tc, narrative=False)


def taxes(tc):
    s = tc.get("security") or {}
    b, sl = s.get("buy_tax"), s.get("sell_tax")
    if tc.get("chain") == "solana": return None  # Solana tokens don't have buy/sell taxes like EVM ones
    if b is None and sl is None: return "Taxes: not reported yet, so check before you buy"
    f = lambda x: "?" if x is None else f"{x:.0f}%"
    return f"Taxes: buy {f(b)} · sell {f(sl)}"


def age_words(m):
    return f"{max(1, round(m))} min old" if m is not None else "age unknown"


def card(chain, token, tc, g, liq, age):
    sym = gate.esc((g.get("symbol") or "?").lstrip("$"))
    L = [f"🚀 <b>New launch: ${sym}</b> on {gate.esc(gate.chain_name(chain))}",
         f"{age_words(age)} · {gate.usd_short(liq)} in the pool",
         f"<code>{gate.esc(token)}</code>", "",
         f"{gate.ICON[g['verdict']]} <b>{'Looks clean so far' if g['verdict'] == 'BUY' else 'Careful'}</b>"]
    L += [f"• {gate.esc(r)}" for r in g["reasons"][:3]]
    tx = taxes(tc)
    if tx: L.append(f"• {tx}")
    L += ["", f"<b>Max size:</b> ${g['size_cap_usd']}. Brand-new tokens can still go to zero fast."]
    if chain == "solana": L.append(gate.MEV_LINE)
    L += ["", "<i>Netro Signal by Netrovert · you buy in your own wallet, we never touch your funds</i>"]
    cb = [("🎮 Practice snipe ($50)", f"ls:{LONG.get(chain, chain)}:{token}")]
    return gate.Html("\n".join(L)), g["buttons"], cb


def cycle(send=None, dry=False):
    """One scan. send(chat, text, buttons, callbacks). Returns stats."""
    c = cfg(); st = {"candidates": 0, "fresh": 0, "checked": 0, "alertable": 0, "sent": 0, "errors": 0}
    seen = gate.load(SEEN, {}); cache = gate.load(CACHE, {}); now = time.time()
    seen = {k: v for k, v in seen.items() if now - v < 3 * 86400}; cache = {k: v for k, v in cache.items() if now - v["t"] < 3600}
    cands = {(ch, t) for ch, t in candidates() if f"{ch}:{t.lower()}" not in seen}; st["candidates"] = len(cands)
    fresh = []
    by_chain = {}
    for ch, t in cands: by_chain.setdefault(ch, []).append(t)
    for ch, ts in by_chain.items():
        m = market(ch, ts)
        for t in ts:
            liq, age, sym = m.get(t, (0, None, None))
            key = f"{ch}:{t.lower()}"
            if age is not None and age > c["max_age_min"]: seen[key] = now; continue  # too old: never alert
            if liq >= c["min_liq"] and age is not None: fresh.append((ch, t, liq, age))
    fresh.sort(key=lambda x: -x[2]); st["fresh"] = len(fresh)
    results = []
    todo = [x for x in fresh if f"{x[0]}:{x[1].lower()}" not in cache][:c["max_checks"]]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(check, ch, t): (ch, t, liq, age) for ch, t, liq, age in todo}
        done, _ = wait(futs, timeout=300)
        for f in done:
            ch, t, liq, age = futs[f]
            try: tc, g = f.result()
            except Exception: st["errors"] += 1; continue
            st["checked"] += 1
            cache[f"{ch}:{t.lower()}"] = {"t": now, "verdict": g["verdict"], "symbol": g.get("symbol"), "cap": g.get("size_cap_usd")}
            seen[f"{ch}:{t.lower()}"] = now
            if tc.get("verdict") == "KILL" or g["verdict"] == "SKIP": continue
            results.append((ch, t, tc, g, liq, age))
    st["alertable"] = len(results); cards = []
    for ch, t, tc, g, liq, age in results:
        txt, btn, cb = card(ch, t, tc, g, liq, age); cards.append((ch, txt, btn, cb))
    if not dry and send and cards:
        a = subs(); owner = gate.cfg().get("owner_chat_id")
        chats = set(int(k) for k in a) | ({owner} if owner else set())
        for chat in chats:
            s = sub_of(chat)
            if not s["on"]: continue
            s["sent"] = [x for x in s.get("sent", []) if now - x < 3600]
            for ch, txt, btn, cb in cards:
                if ch not in s["chains"] or len(s["sent"]) >= s["per_hour"]: continue
                try: send(chat, txt, btn, cb); s["sent"].append(now); st["sent"] += 1
                except Exception: st["errors"] += 1
            put_sub(chat, s)
    _save(SEEN, seen); _save(CACHE, cache)
    st["cards"] = cards
    return st


def loop(send, log):
    time.sleep(20)  # orders start at 110s, so the two scans start ~90s apart
    while True:
        t0 = time.time()
        try:
            st = cycle(send); STATE["last_cycle"] = time.time(); STATE["last_stats"] = {k: v for k, v in st.items() if k != "cards"}
            log("launches: " + ", ".join(f"{k}={v}" for k, v in STATE["last_stats"].items()))
        except Exception:
            log("launches error: " + traceback.format_exc().strip().splitlines()[-1])
        time.sleep(max(30, cfg()["every_s"] - (time.time() - t0)) + random.uniform(0, 10))  # jitter so we don't lock-step with orders


def start(send, log):
    th = threading.Thread(target=loop, args=(send, log), daemon=True, name="launches"); th.start(); return th


def saved_verdict(chain, token):
    """Verdict the launch scan stored when the alert went out (kept 1h), or None."""
    return gate.load(CACHE, {}).get(f"{chain}:{token.lower()}")
