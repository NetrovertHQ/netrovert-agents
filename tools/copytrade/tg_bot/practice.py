"""Practice mode for Netro Signal: fake money only, open to anyone. Never touches real funds or keys.
Per-user data: practice/users/<chat_id>.json. Prices: DexScreener (free). Gate: token_check (Rugcheck/GoPlus/DexScreener, no Helius)."""
import json, os, threading, time, uuid
from datetime import datetime
import requests
import gate

DIR = os.path.join(gate.HERE, "practice", "users"); os.makedirs(DIR, exist_ok=True)
LOCK = threading.RLock(); S = requests.Session(); S.headers["User-Agent"] = "netro-signal/1.0"
INTRO = ("🎮 You've got $1,000 of fake money to practice with.\n"
         "It's not real: nothing is bought on-chain and no wallet is connected.\n"
         "Prices are live and each trade costs a 3% fake fee, just like the real thing.")


def path(cid): return os.path.join(DIR, f"{cid}.json")
def get(cid): return gate.load(path(cid), None)
def put(u):
    with LOCK: json.dump(u, open(path(u["chat_id"]), "w"), indent=1)
def fee(): return gate.cfg().get("practice_fee_pct", 3) / 100
def money(x): return f"-${abs(x):,.2f}" if x < 0 else f"${x:,.2f}"
def now(): return datetime.now(gate.LAGOS).strftime("%d %b %H:%M WAT")


def price(token, chain=None):
    """Best-liquidity DexScreener pair: (price_usd, symbol, chain) or None."""
    try:
        ps = S.get(f"https://api.dexscreener.com/latest/dex/tokens/{token}", timeout=15).json().get("pairs") or []
    except Exception: return None
    ps = [p for p in ps if p.get("priceUsd") and p["baseToken"]["address"].lower() == token.lower() and (not chain or p["chainId"] == chain)]
    if not ps: return None
    p = max(ps, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
    return float(p["priceUsd"]), p["baseToken"]["symbol"], p["chainId"]


def px_fmt(x):
    return f"${x:,.2f}" if x >= 1 else f"${x:.4f}" if x >= 0.01 else f"${x:.3g}"


def need(cid):
    u = get(cid)
    return u if u else None


def start(cid, name=""):
    u = get(cid)
    if u: return f"🎮 You're already set up with {money(u['cash'])} in fake cash. /portfolio shows your bag, /reset starts over."
    c = gate.cfg(); u = {"chat_id": cid, "name": name, "start": c.get("practice_start_usd", 1000), "cash": c.get("practice_start_usd", 1000),
                         "positions": {}, "history": [], "stoploss_pct": None, "copy": None, "copygate": True, "pending": {}, "created": now()}
    put(u); return INTRO + "\n\nTry it: /buy <token address> 50"


def _buy(u, token, usd, px, sym, chain, why):
    if usd > u["cash"] + 1e-9: return None, f"Not enough fake cash. You have {money(u['cash'])}."
    if len(u["positions"]) >= gate.cfg().get("practice_max_positions", 30) and token not in u["positions"]: return None, "You've got a lot of positions open. Sell a few first."
    fill = px * (1 + fee()); qty = usd / fill
    p = u["positions"].setdefault(token, {"symbol": sym, "chain": chain, "qty": 0, "cost": 0, "opened": now(), "via": why})
    p["qty"] += qty; p["cost"] += usd; u["cash"] -= usd
    u["history"].append({"t": now(), "side": "BUY", "token": token, "symbol": sym, "usd": round(usd, 2), "px": fill, "via": why})
    return p, None


def _sell(u, token, pct, px, why):
    p = u["positions"][token]; frac = min(max(pct, 0), 100) / 100
    qty = p["qty"] * frac; got = qty * px * (1 - fee()); cost = p["cost"] * frac; pl = got - cost
    p["qty"] -= qty; p["cost"] -= cost; u["cash"] += got
    u["history"].append({"t": now(), "side": "SELL", "token": token, "symbol": p["symbol"], "usd": round(got, 2), "pl": round(pl, 2), "px": px * (1 - fee()), "via": why})
    if frac >= 0.999: del u["positions"][token]
    return got, pl


def buy_request(cid, args):
    """Step 1: show the gate card and a Confirm button. Returns (text, buttons, callback_buttons)."""
    u = get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000.", None, None
    if len(args) < 2: return "How to buy: /buy <token address> <amount>\nExample: /buy DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263 50", None, None
    token = args[0]
    try: usd = float(args[1].lstrip("$"))
    except ValueError: return "The amount should be a number, like 50.", None, None
    if usd <= 0: return "The amount needs to be more than $0.", None, None
    if usd > u["cash"] + 1e-9: return f"Not enough fake cash. You have {money(u['cash'])}.", None, None
    chain = args[2].lower() if len(args) > 2 else None
    q = price(token, chain)
    if not q: return "😕 I couldn't find a live price for that token. Check the address?", None, None
    g = gate.gate(token, q[2], narrative=False)
    pid = uuid.uuid4().hex[:8]
    with LOCK:
        u = get(cid); u["pending"] = {pid: {"token": token, "usd": usd, "chain": q[2], "ts": time.time()}}; put(u)
    txt = gate.card_text(g, "🎮 <b>Practice buy</b>: here's our check first", footer=False, size_line=False)
    txt = gate.Html(txt + f"\n\n<b>Fake buy:</b> {money(usd)} of ${gate.esc(q[1])} at {px_fmt(q[0])} + 3% fee.\nTap confirm within 5 min.\n\n<i>🎮 Practice mode · fake money only</i>")
    return txt, g["buttons"], [("✅ Confirm fake buy", f"pb:{pid}"), ("✖️ Cancel", f"px:{pid}")]


def confirm(cid, data):
    kind, pid = data.split(":", 1)
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
    return f"{'📈' if pl >= 0 else '📉'} Sold {pct:g}% of ${sym} for {money(got)} (fee included). That's {'+' if pl >= 0 else ''}{money(pl)} on it.\n💵 Fake cash: {money(u['cash'])}"


def find_pos(u, k):
    for t, p in u["positions"].items():
        if t.lower() == k.lower() or p["symbol"].lower() == k.lower(): return t
    return None


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
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        tot, lines, stopped = value(u)
    pl = tot - u["start"]
    L = ["💼 Your practice portfolio", f"Worth {money(tot)} · {pl/u['start']*100:+.1f}% since you started", f"💵 Cash {money(u['cash'])}", ""]
    L += lines or ["Nothing open yet. Try /buy."]
    if stopped: L.append("🛑 Stop-loss sold: " + ", ".join(stopped))
    if u.get("copy"): L += ["", f"🤖 Copying {u['copy']['wallet']} with {money(u['copy']['usd'])} a trade"]
    L += ["", f"Prices as of {now()} · fake money only"]
    return "\n".join(L)


def history(cid):
    u = get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000."
    h = u["history"][-15:]
    if not h: return "No practice trades yet. Try /buy!"
    return "🧾 Your last practice trades\n" + "\n".join(
        f"• {x['t'].replace(' WAT','')}: {'bought' if x['side']=='BUY' else 'sold'} ${x['symbol']} {money(x['usd'])}" + (f" ({'+' if x['pl']>=0 else ''}{money(x['pl'])})" if "pl" in x else "") + (" · copied" if x.get("via","").startswith("copy") else " · stop-loss" if x.get("via")=="stop-loss" else "") for x in reversed(h))


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
    return [w for w in gate.load(gate.WALLETS, []) if not gate.is_test(w["label"])]


def copy(cid, args):
    with LOCK:
        u = get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        ws = copy_targets()
        if not args: return "🤖 How to copy: /copy <nickname> [amount per trade]\nYou can copy: " + ", ".join(w["label"] for w in ws)
        usd = gate.cfg().get("practice_copy_default_usd", 25)
        if len(args) > 1:
            try: usd = float(args[-1].lstrip("$")); args = args[:-1]
            except ValueError: pass
        nick = " ".join(args); w = next((w for w in ws if w["label"].lower() == nick.lower()), None)
        if not w: return "🤔 I don't know that wallet. You can copy: " + ", ".join(x["label"] for x in ws)
        u["copy"] = {"wallet": w["label"], "address": w["address"], "usd": usd, "since": now()}; put(u)
    return (f"🤖 You're now copying {w['label']} with {money(usd)} of fake money a trade. When they sell, you sell.\n"
            f"We check hourly, so you might be up to an hour behind them.\n"
            f"🛡 Risky tokens are {'skipped' if u.get('copygate', True) else 'copied too'} (/copygate to change). /uncopy to stop.")


def uncopy(cid):
    with LOCK:
        u = get(cid)
        if not u or not u.get("copy"): return "You're not copying anyone right now."
        w = u["copy"]["wallet"]; u["copy"] = None; put(u)
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


def copy_fills(scan, gate_cache):
    """Called by push: mirror buys/sells of copied wallets. Returns {chat_id: [messages]}. gate_cache: token->gate result."""
    out = {}
    for f in os.listdir(DIR):
        with LOCK:
            u = gate.load(os.path.join(DIR, f), None)
            if not u or not u.get("copy"): continue
            cp = u["copy"]; done = set(u.get("copied", [])); msgs = []
            for s in scan.get("swaps", []):
                if s.get("wallet", "").lower() != cp["address"].lower(): continue
                key = f"{s['tx']}:{s['token']}:{s['side']}"
                if key in done: continue
                done.add(key)
                if s["side"] == "BUY":
                    if s["token"] in u["positions"]: continue  # one copy per token
                    g = gate_cache.get(s["token"])
                    if u.get("copygate", True) and g and g["token_check"]["verdict"] in ("KILL", None):
                        msgs.append(f"⏭️ {cp['wallet']} bought ${s.get('symbol') or '?'}, but it failed our safety check, so we skipped it."); continue
                    q = price(s["token"], s["chain"])
                    if not q: msgs.append(f"⏭️ Couldn't copy ${s.get('symbol') or '?'}: no live price."); continue
                    usd = min(cp["usd"], u["cash"])
                    if usd < 1: msgs.append(f"⏭️ Out of fake cash, so we couldn't copy ${q[1]}."); continue
                    _, err = _buy(u, s["token"], usd, q[0], q[1], q[2], f"copy:{cp['wallet']}")
                    msgs.append(err or f"🤖 {cp['wallet']} bought ${q[1]}, so you did too: {money(usd)} at {px_fmt(q[0]*(1+fee()))}.\n💵 Fake cash left: {money(u['cash'])}")
                elif s["side"] == "SELL" and s["token"] in u["positions"] and u["positions"][s["token"]].get("via", "").startswith("copy"):
                    q = price(s["token"], s["chain"])
                    if not q: msgs.append(f"⚠️ {cp['wallet']} sold ${s.get('symbol') or '?'} but there's no live price. Sell it yourself with /sell."); continue
                    sym = u["positions"][s["token"]]["symbol"]; got, pl = _sell(u, s["token"], 100, q[0], f"copy:{cp['wallet']}")
                    msgs.append(f"🤖 {cp['wallet']} sold ${sym}, so you did too: {money(got)} back ({'+' if pl>=0 else ''}{money(pl)}).\n💵 Fake cash: {money(u['cash'])}")
            if u.get("stoploss_pct"):
                _, _, stopped = value(u)
                if stopped: msgs.append("🛑 Stop-loss sold: " + ", ".join(stopped))
            u["copied"] = sorted(done)[-2000:]; put(u)
            if msgs: out[u["chat_id"]] = msgs
    return out
