"""Practice mode for Netro Signal: fake money only, open to anyone. Never touches real funds or keys.
Per-user data: practice/users/<chat_id>.json. Prices: DexScreener (free). Gate: token_check (Rugcheck/GoPlus/DexScreener, no Helius)."""
import json, os, threading, time, uuid
from datetime import datetime
import requests
import gate, cache

DIR = os.path.join(gate.HERE, "practice", "users"); os.makedirs(DIR, exist_ok=True)
LOCK = threading.RLock(); S = requests.Session(); S.headers["User-Agent"] = "netro-signal/1.0"
INTRO = ("🎮 You've got $1,000 of fake money to practice with.\n"
         "It's not real: nothing is bought on-chain and no wallet is connected.\n"
         "Prices are live and each trade costs a 3% fake fee, just like the real thing.")


def path(cid): return os.path.join(DIR, f"{cid}.json")
def get(cid): return gate.load(path(cid), None)
def put(u):
    with LOCK: gate.atomic_dump(u, path(u["chat_id"]), indent=1)
def fee(): return gate.cfg().get("practice_fee_pct", 3) / 100
def money(x): return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"
def now(): return datetime.now(gate.LAGOS).strftime("%d %b %H:%M WAT")


def _pairs(token):
    try: return S.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=15).json().get("pairs") or []
    except Exception: return None


def price(token, chain=None):
    """Best-liquidity DexScreener pair: (price_usd, symbol, chain) or None."""
    ps = cache.PAIRS.get(token.lower(), lambda: _pairs(token))
    if ps is None: return None
    ps = [p for p in ps if p.get("priceUsd") and p["baseToken"]["address"].lower() == token.lower() and (not chain or p["chainId"] == chain)]
    if not ps: return None
    p = max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return float(p["priceUsd"]), p["baseToken"]["symbol"], p["chainId"]


def no_price_msg(token, chain=None):
    """Explain why there's no price: unknown token vs a token with no live trading pool."""
    try: ps = S.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=15).json().get("pairs") or []
    except Exception: ps = []
    sym = None
    for p in ps:
        for side in ("baseToken", "quoteToken"):
            if (p.get(side) or {}).get("address", "").lower() == token.lower(): sym = p[side].get("symbol")
    if sym:
        return (f"😕 ${gate.esc(sym)} has no live trading pool right now (no money in it and no trades), so there's no real price to practice with. "
                "Try a token that's actively trading.")
    return "😕 I couldn't find that token on any exchange. Double-check the address, or add the chain after the amount, like: /buy <address> 20 sol"


def px_fmt(x):
    return f"${x:,.2f}" if x >= 1 else f"${x:.4f}" if x >= 0.01 else f"${x:.3g}"


def need(cid):
    u = get(cid)
    return u if u else None


def start(cid, name=""):
    u = get(cid)
    if u: return (f"🎮 You're already set up with {money(u['cash'])} in fake cash. /portfolio shows your bag, /fumbles shows what you sold too early, /reset starts over.",
                  None, [("😭 Fumbled trades", "pf:")])
    c = gate.cfg(); u = {"chat_id": cid, "name": name, "start": c.get("practice_start_usd", 1000), "cash": c.get("practice_start_usd", 1000),
                         "positions": {}, "history": [], "stoploss_pct": None, "copy": None, "copygate": True, "pending": {}, "created": now()}
    put(u)
    try: import refs; refs.joined(cid)
    except Exception: pass
    return INTRO + "\n\nTry it: /buy <token address> 50"


def _buy(u, token, usd, px, sym, chain, why):
    sym = (sym or "?").lstrip("$") or sym  # some DexScreener symbols already start with $; we add our own
    if usd > u["cash"] + 1e-9: return None, f"Not enough fake cash. You have {money(u['cash'])}."
    if len(u["positions"]) >= gate.cfg().get("practice_max_positions", 30) and token not in u["positions"]: return None, "You've got a lot of positions open. Sell a few first."
    fill = px * (1 + fee()); qty = usd / fill
    p = u["positions"].setdefault(token, {"symbol": sym, "chain": chain, "qty": 0, "cost": 0, "opened": now(), "ts": time.time(), "via": why})
    p["qty"] += qty; p["cost"] += usd; u["cash"] -= usd
    u["history"].append({"t": now(), "side": "BUY", "token": token, "symbol": sym, "usd": round(usd, 2), "px": fill, "via": why})
    if len(u["history"]) == 1:
        try: import refs; threading.Thread(target=refs.traded, args=(u["chat_id"],), daemon=True).start()
        except Exception: pass
    return p, None


def _sell(u, token, pct, px, why):
    p = u["positions"][token]; frac = min(max(pct, 0), 100) / 100
    entry = p["cost"] / p["qty"] if p["qty"] else px
    qty = p["qty"] * frac; got = qty * px * (1 - fee()); cost = p["cost"] * frac; pl = got - cost
    p["qty"] -= qty; p["cost"] -= cost; u["cash"] += got
    u["history"].append({"t": now(), "side": "SELL", "token": token, "symbol": p["symbol"], "usd": round(got, 2), "pl": round(pl, 2), "px": px * (1 - fee()), "via": why,
                         "entry_px": entry, "chain": p.get("chain"), "opened": p.get("opened"), "opened_ts": p.get("ts"), "ts": time.time(),
                         "pct": round(pl / cost * 100, 2) if cost else 0})
    if frac >= 0.999: del u["positions"][token]
    return got, pl


def buy_request(cid, args):
    """Step 1: show the gate card and a Confirm button. Returns (text, buttons, callback_buttons)."""
    u = get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000.", None, None
    if len(args) == 1: return "How much fake money do you want to put in? Just reply with a number, like 50.", None, None
    if len(args) < 2: return "How to buy: /buy <token address> <amount>\nExample: /buy DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 50", None, None
    token = args[0]
    try: usd = float(args[1].lstrip("$"))
    except ValueError: return "The amount should be a number, like 50.", None, None
    if usd <= 0: return "The amount needs to be more than $0.", None, None
    if usd > u["cash"] + 1e-9: return f"Not enough fake cash. You have {money(u['cash'])}.", None, None
    chain = gate.norm_chain(args[2]) if len(args) > 2 else None
    q = price(token, chain)
    if not q: return no_price_msg(token, chain), None, None
    g = gate.gate(token, q[2], narrative=False)
    pid = uuid.uuid4().hex[:8]
    with LOCK:
        u = get(cid); u["pending"] = {pid: {"token": token, "usd": usd, "chain": q[2], "ts": time.time()}}; put(u)
    txt = gate.card_text(g, "🎮 <b>Practice buy</b>: here's our check first", footer=False, size_line=False)
    txt = gate.Html(txt + f"\n\n<b>Fake buy:</b> {money(usd)} of ${gate.esc(q[1])} at {px_fmt(q[0])} + 3% fee.\nTap confirm within 5 min.\n\n<i>🎮 Practice mode · fake money only</i>")
    return txt, g["buttons"], [("✅ Confirm fake buy", f"pb:{pid}"), ("✖️ Cancel", f"px:{pid}")]


def confirm(cid, data):
    kind, pid = data.split(":", 1)
    p0 = ((get(cid) or {}).get("pending") or {}).get(pid)
    if p0 and kind == "pb": warm([(p0["token"], p0["chain"])])
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first."
        p = u.get("pending", {}).pop(pid, None); put(u)
        if not p: return "⌛ That button already expired. Send /buy again."
        if kind == "px": return "👍 Cancelled. Nothing bought."
        if time.time() - p["ts"] > 300: return "⌛ That price is over 5 minutes old. Send /buy again for a fresh one."
        q = price(p["token"], p["chain"])
        if not q: return "😕 The price vanished, so nothing was bought. Try again."
        pos, err = _buy(u, p["token"], p["usd"], q[0], q[1], q[2], "manual")
        if err: return err
        put(u)
    return f"✅ Bought {money(p['usd'])} of ${q[1]} at {px_fmt(q[0]*(1+fee()))} (fee included).\n💵 Fake cash left: {money(u['cash'])}"


def sell(cid, args):
    u0 = get(cid); t0 = find_pos(u0, args[0]) if u0 and args else None
    if t0: price(t0, u0["positions"][t0]["chain"])  # warm the 45s price cache outside the global lock
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        if not args: return "How to sell: /sell <token or symbol> [percent]\nExample: /sell BONK 50"
        tok = find_pos(u, args[0])
        if not tok: return "You don't hold that one. /portfolio shows what you have."
        try: pct = float(args[1].rstrip("%")) if len(args) > 1 else 100
        except ValueError: return "The percent should be a number, like 50."
        q = price(tok, u["positions"][tok]["chain"])
        if not q: return "😕 I can't get a live price right now. Try again in a bit."
        sym = u["positions"][tok]["symbol"]; got, pl = _sell(u, tok, pct, q[0], "manual"); put(u)
    txt = f"{'📈' if pl >= 0 else '📉'} Sold {pct:g}% of ${sym} for {money(got)} (fee included). That's {'+' if pl >= 0 else ''}{money(pl)} on it.\n💵 Fake cash: {money(u['cash'])}"
    return txt, None, [share_btn(len(u["history"]) - 1)]


def find_pos(u, k):
    for t, p in u["positions"].items():
        if t.lower() == k.lower() or p["symbol"].lstrip("$").lower() == k.lstrip("$").lower(): return t
    return None


_WARM = __import__("concurrent.futures").futures.ThreadPoolExecutor(max_workers=4, thread_name_prefix="warm")


def warm(pairs):
    """Fetch prices (token, chain) into the 45s cache in parallel, OUTSIDE the global LOCK, so later
    price() calls under the lock are cache hits instead of network calls that would block every user."""
    pairs = list(dict.fromkeys(pairs))[:40]
    try:
        if pairs: list(_WARM.map(lambda k: price(*k), pairs, timeout=40)) if len(pairs) > 1 else price(*pairs[0])
    except Exception: pass  # warming is best effort


def warm_user(cid):
    u = get(cid)
    if u: warm([(t, p.get("chain")) for t, p in u.get("positions", {}).items()])


def value(u, apply_stops=True):
    """Live value. Applies the user's stop-loss if set. Returns (total, lines, stopped)."""
    lines, stopped, tot = [], [], u["cash"]
    for t in list(u["positions"]):
        p = u["positions"][t]; q = price(t, p["chain"])
        if not q: lines.append(f"• ${p['symbol']}: paid {money(p['cost'])}, no live price right now"); tot += p["cost"]; continue
        v = p["qty"] * q[0] * (1 - fee()); pl = v - p["cost"]; pct = pl / p["cost"] * 100 if p["cost"] else 0
        if apply_stops and u.get("stoploss_pct") and pct <= -u["stoploss_pct"]:
            got, rpl = _sell(u, t, 100, q[0], "stop-loss"); stopped.append(f"{p['symbol']} ({money(rpl)})"); tot += got; continue
        tot += v; lines.append(f"{'🟢' if pct >= 0 else '🔴'} ${p['symbol']}: {money(v)} ({pct:+.1f}%)" + (" · copied" if p.get("via", "").startswith("copy") else ""))
    if stopped: put(u)
    return tot, lines, stopped


def portfolio(cid):
    warm_user(cid)
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        tot, lines, stopped = value(u)
    pl = tot - u["start"]
    L = ["💼 Your practice portfolio", f"Worth {money(tot)} · {pl/u['start']*100:+.1f}% since you started", f"💵 Cash {money(u['cash'])}", ""]
    L += lines or ["Nothing open yet. Try /buy."]
    if stopped: L.append("🛑 Stop-loss sold: " + ", ".join(stopped))
    if u.get("copy"): L += ["", f"🤖 Copying {gate.public_name(u['copy']['address'])} with {money(u['copy']['usd'])} a trade"]
    L += ["", f"Prices as of {now()} · fake money only", "/pnl gets you a card to share, /pnl SYMBOL for one trade."]
    return "\n".join(L)


def history(cid):
    u = get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000."
    h = u["history"][-15:]
    if not h: return "No practice trades yet. Try /buy!"
    return "🧾 Your last practice trades\n" + "\n".join(
        f"{i}. {x['t'].replace(' WAT','')}: {'bought' if x['side']=='BUY' else 'sold'} ${x['symbol']} {money(x['usd'])}" + (f" ({'+' if x['pl']>=0 else ''}{money(x['pl'])})" if "pl" in x else "") + (" · copied" if x.get("via","").startswith("copy") else " · stop-loss" if x.get("via")=="stop-loss" else "") for i, x in enumerate(reversed(h), 1)) + "\n\n/pnl 1 makes a card for trade 1, /pnl alone for your whole run."


def reset(cid, name=""):
    with LOCK:
        if os.path.exists(path(cid)): os.remove(path(cid))
    return "🔄 Fresh start!\n\n" + start(cid, name)


def stoploss(cid, args):
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        if not args: return f"🛑 Stop-loss is {'off' if not u.get('stoploss_pct') else 'at -'+format(u['stoploss_pct'],'g')+'%'}. Set it with /stoploss 30, or /stoploss off."
        if args[0].lower() == "off": u["stoploss_pct"] = None
        else:
            try: v = float(args[0].rstrip("%")); assert 1 <= v <= 99
            except Exception: return "Pick a number from 1 to 99, like /stoploss 30."
            u["stoploss_pct"] = v
        put(u)
    sl = u["stoploss_pct"]
    return "🛑 Stop-loss is off." if not sl else f"🛑 Done. Anything down {sl:g}% gets sold for you (checked hourly and on /portfolio)."


def copy_targets():
    """Public view of copyable wallets: n, address, chain, label (public), desc. Never the owner's nickname."""
    return gate.public_wallets()


def target_list(ws):
    return "\n".join(f"{w['n']}. {w['label']}: {w['desc']}" for w in ws)


def migrate(u):
    """Old state stored the owner's nickname. Re-key to the address and the public label. Returns True if changed."""
    nick = {w["label"]: w["address"] for w in gate.load(gate.WALLETS, [])}; ch = False
    cp = u.get("copy")
    if cp and cp.get("address") and cp.get("wallet") != gate.public_name(cp["address"]):
        cp["wallet"] = gate.public_name(cp["address"]); ch = True
    for x in list(u.get("positions", {}).values()) + u.get("history", []):
        v = x.get("via", "")
        if v.startswith("copy:") and v[5:] in nick: x["via"] = "copy:" + nick[v[5:]]; ch = True
    return ch


def migrate_all():
    n = 0
    for f in os.listdir(DIR):
        with LOCK:
            u = gate.load(os.path.join(DIR, f), None)
            if u and migrate(u): put(u); n += 1
    return n


def copy(cid, args):
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        ws = copy_targets()
        if not args: return "🤖 How to copy: /copy <number> [amount per trade], e.g. /copy 1 25\n\nYou can copy:\n" + target_list(ws)
        usd = gate.cfg().get("practice_copy_default_usd", 25)
        if len(args) > 1:
            try: usd = float(args[-1].lstrip("$")); args = args[:-1]
            except ValueError: pass
        k = " ".join(args).strip().lower().lstrip("#")
        w = next((w for w in ws if str(w["n"]) == k or w["label"].lower() == k or w["label"].lower().replace(" #", " ") == k or w["address"].lower() == k), None)
        if not w: return "🤔 I don't know that one. Pick a number:\n" + target_list(ws)
        u["copy"] = {"wallet": w["label"], "address": w["address"], "usd": usd, "since": now()}; put(u)
    return (f"🤖 You're now copying {w['label']} with {money(usd)} of fake money a trade. When they sell, you sell.\n"
            f"We check hourly, so you might be up to an hour behind them.\n"
            f"🛡 Risky tokens are {'skipped' if u.get('copygate', True) else 'copied too'} (/copygate to change). /uncopy to stop.")


def uncopy(cid):
    with LOCK:
        u = get(cid)
        if not u or not u.get("copy"): return "You're not copying anyone right now."
        w = gate.public_name(u["copy"]["address"]); u["copy"] = None; put(u)
    return f"✋ Stopped copying {w}. Anything you already hold stays; /sell when you like."


def copygate(cid, args):
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        if not args or args[0].lower() not in ("on", "off"): return f"🛡 Safety filter is {'on' if u.get('copygate', True) else 'off'}. Use /copygate on or /copygate off."
        u["copygate"] = args[0].lower() == "on"; put(u)
    return "🛡 On: copies skip tokens that fail our safety check." if u["copygate"] else "⚠️ Off: every buy gets copied, even risky ones."


def leaderboard(cid=None):
    rows = []
    for f in os.listdir(DIR):
        u = gate.load(os.path.join(DIR, f), None)
        if not u: continue
        tot = u["cash"] + sum(p["cost"] for p in u["positions"].values())  # cost basis: no price calls for everyone
        rows.append(((tot - u["start"]) / u["start"] * 100, u.get("name") or "anon", u["chat_id"] == cid, len(u["history"])))
    if not rows: return "🏆 No players yet. Be the first: /practice"
    rows.sort(reverse=True)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    return "🏆 Practice leaderboard\n" + "\n".join(
        f"{medal.get(i, str(i)+'.')} {n}{' (you)' if me else ''}: {r:+.1f}% · {t} trades" for i, (r, n, me, t) in enumerate(rows[:10], 1)) + "\n\nOpen positions count at what was paid."


def copy_fills(scan, gate_cache, closes=None):
    """Called by push: mirror buys/sells of copied wallets. Returns {chat_id: [messages]}. gate_cache: token->gate result.
    closes (optional dict) gets {chat_id: history index of the last close} so push can add a Share PnL card button."""
    out = {}; closes = {} if closes is None else closes
    try: warm([(s["token"], s["chain"]) for s in scan.get("swaps", [])])
    except Exception: pass
    for f in os.listdir(DIR):
        with LOCK:
            u = gate.load(os.path.join(DIR, f), None)
            if not u or not u.get("copy"): continue
            migrate(u); cp = u["copy"]; who = gate.public_name(cp["address"]); done = set(u.get("copied", [])); msgs = []
            for s in scan.get("swaps", []):
                if s.get("wallet", "").lower() != cp["address"].lower(): continue
                key = f"{s['tx']}:{s['token']}:{s['side']}"
                if key in done: continue
                done.add(key)
                if s["side"] == "BUY":
                    if s["token"] in u["positions"]: continue  # one copy per token
                    g = gate_cache.get(s["token"])
                    if u.get("copygate", True) and g and g["token_check"]["verdict"] in ("KILL", None):
                        msgs.append(f"⏭️ {who} bought ${s.get('symbol') or '?'}, but it failed our safety check, so we skipped it."); continue
                    q = price(s["token"], s["chain"])
                    if not q: msgs.append(f"⏭️ Couldn't copy ${s.get('symbol') or '?'}: no live price."); continue
                    usd = min(cp["usd"], u["cash"])
                    if usd < 1: msgs.append(f"⏭️ Out of fake cash, so we couldn't copy ${q[1]}."); continue
                    _, err = _buy(u, s["token"], usd, q[0], q[1], q[2], f"copy:{cp['address']}")
                    msgs.append(err or f"🤖 {who} bought ${q[1]}, so you did too: {money(usd)} at {px_fmt(q[0]*(1+fee()))}.\n💵 Fake cash left: {money(u['cash'])}")
                elif s["side"] == "SELL" and s["token"] in u["positions"] and u["positions"][s["token"]].get("via", "").startswith("copy"):
                    q = price(s["token"], s["chain"])
                    if not q: msgs.append(f"⚠️ {who} sold ${s.get('symbol') or '?'} but there's no live price. Sell it yourself with /sell."); continue
                    sym = u["positions"][s["token"]]["symbol"]; got, pl = _sell(u, s["token"], 100, q[0], f"copy:{cp['address']}")
                    msgs.append(f"🤖 {who} sold ${sym}, so you did too: {money(got)} back ({'+' if pl>=0 else ''}{money(pl)}).\n💵 Fake cash: {money(u['cash'])}")
            if u.get("stoploss_pct"):
                _, _, stopped = value(u)
                if stopped: msgs.append("🛑 Stop-loss sold: " + ", ".join(stopped))
            u["copied"] = sorted(done)[-2000:]; put(u)
            sells = [i for i, x in enumerate(u["history"]) if x["side"] == "SELL"]
            if msgs and sells and u["history"][sells[-1]].get("ts", 0) > time.time() - 600 and any("sold" in m for m in msgs): closes[u["chat_id"]] = sells[-1]
            if msgs: out[u["chat_id"]] = msgs
    return out


# ---- PnL cards ----
def share_btn(idx): return ("🧾 Share PnL card", f"pc:h{idx}")


def _ts_from(s):
    try: return datetime.strptime(f"{datetime.now(gate.LAGOS).year} {s.replace(' WAT', '')}", "%Y %d %b %H:%M").replace(tzinfo=gate.LAGOS).timestamp()
    except Exception: return None


def _closed(x):
    o = x.get("opened_ts") or (_ts_from(x["opened"]) if x.get("opened") else None)
    end = x.get("ts") or _ts_from(x["t"])
    cost = x["usd"] - x["pl"]
    return {"symbol": x["symbol"], "chain": x.get("chain"), "entry": x.get("entry_px") or x["px"], "exit": x["px"], "pl": x["pl"],
            "pct": x.get("pct", x["pl"] / cost * 100 if cost else 0), "hold_sec": end - o if o and end else None, "open": False, "when": x["t"], "source": _source(x.get("via"))}


def _open(t, p):
    q = price(t, p["chain"])
    if not q: return None
    v = p["qty"] * q[0] * (1 - fee()); pl = v - p["cost"]
    o = p.get("ts") or _ts_from(p.get("opened", ""))
    return {"symbol": p["symbol"], "chain": p["chain"], "entry": p["cost"] / p["qty"], "exit": q[0], "pl": pl,
            "pct": pl / p["cost"] * 100 if p["cost"] else 0, "hold_sec": time.time() - o if o else None, "open": True, "when": "", "source": _source(p.get("via"))}


def _source(via):
    """Public source line for a card: never the nickname."""
    via = via or ""
    if via.startswith("copy:"): return "Copied " + gate.public_name(via[5:]) if not via[5:] in {w["label"] for w in gate.load(gate.WALLETS, [])} else "Copied a wallet"
    return "Stop-loss sale" if via == "stop-loss" else None


def portfolio_stats(cid):
    warm_user(cid)
    with LOCK:
        u = get(cid)
        if not u: return None
        tot, lines, _ = value(u)
    sells = [x for x in u["history"] if x["side"] == "SELL"]
    best = max(sells, key=lambda x: x["pl"], default=None)
    return {"name": u.get("name"), "balance": tot, "start": u["start"], "pl": tot - u["start"], "pct": (tot - u["start"]) / u["start"] * 100,
            "wins": sum(x["pl"] > 0 for x in sells), "losses": sum(x["pl"] <= 0 for x in sells),
            "best": {"symbol": best["symbol"], "pl": best["pl"]} if best and best["pl"] > 0 else None, "open_count": len(u["positions"])}


def trade_data(cid, key):
    """key: symbol/address, a number from /history (1 = newest), or 'h<index>' from a button. Returns (data, error)."""
    u = get(cid)
    if not u: return None, "🎮 Send /practice first to get your fake $1,000."
    h = u["history"]
    if key.startswith("h") and key[1:].isdigit():
        i = int(key[1:])
        if i >= len(h) or h[i]["side"] != "SELL": return None, "⌛ I can't find that trade anymore."
        return _closed(h[i]), None
    if key.isdigit():
        n = int(key); rh = list(reversed(h[-15:]))
        if not 1 <= n <= len(rh):
            opens = list(u["positions"].items())
            return None, f"There's no trade {n} in your /history." if not opens else f"Pick a number from /history (1 to {len(rh)}), or a symbol like /pnl {opens[0][1]['symbol']}."
        x = rh[n - 1]
        if x["side"] == "SELL": return _closed(x), None
        key = x["token"]  # a buy: show the position if still open, else the sell that closed it
        if key not in u["positions"]:
            idx = len(h) - n
            later = [y for y in h[idx + 1:] if y["side"] == "SELL" and y["token"] == key]
            return (_closed(later[0]), None) if later else (None, "I can't find how that one ended.")
    t = find_pos(u, key)
    if t:
        d = _open(t, u["positions"][t])
        return (d, None) if d else (None, "😕 I can't get a live price right now. Try again in a bit.")
    last = [x for x in h if x["side"] == "SELL" and (x["symbol"].lower() == key.lower() or x["token"].lower() == key.lower())]
    if last: return _closed(last[-1]), None
    return None, "I can't find that one. Try /pnl with a number from /history, or a symbol you've traded."


def snipe(cid, token, chain):
    """Practice snipe from a launch card: no new safety check (the launch scan already did it), just a fresh price and fill."""
    import launches
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
    q = price(token, chain)
    if not q: return no_price_msg(token, chain)
    v = launches.saved_verdict(q[2], token) or {}
    with LOCK:
        u = get(cid)
        pos, err = _buy(u, token, 50.0, q[0], q[1], q[2], "snipe")
        if err: return err
        put(u)
    note = {"BUY": "🟢 It looked clean when we flagged it.", "CAREFUL": "🟡 We flagged it as careful, so keep it small."}.get(v.get("verdict"), "")
    return gate.Html(f"✅ Sniped {money(50)} of ${gate.esc(q[1])} at {px_fmt(q[0]*(1+fee()))} (fee included).\n"
                     f"💵 Fake cash left: {money(u['cash'])}" + (f"\n{note}" if note else "") + "\n\n<i>🎮 Practice mode · fake money only</i>")


# ---- Fumbled trades: how much more a closed trade would have made if held to the peak after the sale ----
OHLCV = cache.TTL(900, miss_ttl=120)
GT_NET = {"solana": "solana", "ethereum": "eth", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon_pos", "avalanche": "avax"}


QUOTES = {"So" + "1" * 40 + "2", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
          "0x42" + "0" * 37 + "6", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48"}
SIDES = cache.TTL(86400, miss_ttl=120)


def _pool(token, chain):
    """Best pool with the token as DexScreener base; prefer SOL/USDC/USDT (or WETH/USDC) quoted pools."""
    ps = cache.PAIRS.get(token.lower(), lambda: _pairs(token)) or []
    ps = [p for p in ps if p["baseToken"]["address"].lower() == token.lower() and (not chain or p["chainId"] == chain)]
    liq = lambda p: (p.get("liquidity") or {}).get("usd") or 0
    good = [p for p in ps if p["quoteToken"]["address"] in QUOTES or p["quoteToken"]["address"].lower() in QUOTES]
    good = [p for p in good if liq(p) >= 1000] or good
    return max(good or ps, key=liq) if (good or ps) else None


def _gt(url, params=None):
    """GeckoTerminal GET with a short backoff on 429 (free tier is ~30 calls/min)."""
    for i in range(2):
        r = S.get(url, params=params, timeout=15)
        if r.status_code != 429: return r
        time.sleep(4)
    return r


def _side(net, pool, token):
    """'base' or 'quote': which side of the GeckoTerminal pool is our token (GT and DexScreener can disagree)."""
    def f():
        try:
            r = _gt(f"https://api.geckoterminal.com/api/v2/networks/{net}/pools/{pool}")
            rel = r.json()["data"]["relationships"]
            for side in ("base", "quote"):
                if rel[f"{side}_token"]["data"]["id"].split("_", 1)[1].lower() == token.lower(): return side
        except Exception: return None
        return None
    return SIDES.get((net, pool, token.lower()), f)


def _candles(net, pool, tf, agg, side="base"):
    def f():
        try:
            r = _gt(f"https://api.geckoterminal.com/api/v2/networks/{net}/pools/{pool}/ohlcv/{tf}", {"aggregate": agg, "limit": 1000, "token": side})
            return r.json()["data"]["attributes"]["ohlcv_list"] if r.ok else None
        except Exception: return None
    return OHLCV.get((net, pool, tf, agg, side), f)


def peak_after(token, chain, ts, with_market=False):
    """(peak_usd, source[, market_close_at_ts]). Peak = highest CLOSE after ts on the token's own side of its pool,
    ignoring candles whose wick is >3x their close. Falls back to the live price (source 'now')."""
    p = _pool(token, chain); net = GT_NET.get((p or {}).get("chainId") or chain or "")
    if p and net and ts:
        side = _side(net, p["pairAddress"], token)
        if side:
            age = time.time() - ts
            tf, agg, step = ("minute", 15, 900) if age < 9 * 86400 else ("hour", 1, 3600) if age < 40 * 86400 else ("day", 1, 86400)
            cs = sorted(_candles(net, p["pairAddress"], tf, agg, side) or [], key=lambda c: c[0])
            after = [c for c in cs if c[0] >= ts - step and c[4]]
            if after:
                mk = after[0][4] if after[0][0] <= ts else None
                after = [c for c in after if c[0] + step > ts and c[0] >= ts - step]
                pk = max(c[4] for c in after)
                return (pk, "peak", mk) if with_market else (pk, "peak")
    q = price(token, chain)
    r = (q[0], "now") if q else (None, None)
    return r + (None,) if with_market else r


def fumble_ok(sold, peak, market):
    """Sanity checks: no >1000x peaks, and the sell price must be within 5x of the market close at sell time."""
    if not peak or peak <= sold or peak / sold > 1000: return False
    if market and (sold / market > 5 or market / sold > 5): return False
    return True


def fumbles(cid, top=3):
    u = get(cid)
    if not u: return None
    sells = [x for x in u["history"] if x["side"] == "SELL" and x.get("px") and x.get("usd")][-40:]
    pairs = {(x["token"], x.get("chain")) for x in sells}; warm(list(pairs))
    out = []
    for x in sells:
        ts = x.get("ts") or _ts_from(x["t"]); pk, src, mk = peak_after(x["token"], x.get("chain"), ts, True)
        if not pk or src != "peak": continue
        exit_raw = x["px"] / (1 - fee()); qty = x["usd"] / x["px"]
        missed = qty * pk * (1 - fee()) - x["usd"]
        if missed > 0.01 and fumble_ok(exit_raw, pk, mk):
            out.append({"symbol": x["symbol"], "sold": exit_raw, "peak": pk, "missed": missed, "x": pk / exit_raw, "src": src, "when": x["t"]})
    out.sort(key=lambda f: -f["missed"])
    return {"name": u.get("name"), "total": sum(f["missed"] for f in out), "count": len(out), "checked": len(sells), "top": out[:top]}
