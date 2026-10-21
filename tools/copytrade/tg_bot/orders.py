"""Practice limit orders and DCA (fake money only). Orders live in each practice user's file under "orders".
A background checker fills them at live DexScreener prices with the usual 3% fake fee."""
import os, re, threading, time, traceback, uuid
import gate, practice as P

EXPIRE_S = 7 * 86400


def _resolve(u, k):
    """Token address from an address or a symbol you hold."""
    t = P.find_pos(u, k)
    return t or k


def _every(s):
    m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(m|min|h|hr|d)?", s.lower())
    if not m: return None
    n = float(m.group(1)); unit = m.group(2) or "h"
    return int(n * {"m": 60, "min": 60, "h": 3600, "hr": 3600, "d": 86400}[unit])


def _dur(sec):
    return f"{sec // 86400}d" if sec % 86400 == 0 else f"{sec // 3600}h" if sec % 3600 == 0 else f"{sec // 60} min"


def limit(cid, args):
    u = P.get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000."
    if len(args) < 3: return ("How to set a practice limit buy: /limit <token> <amount> <price or -20%>\n"
                              "Example: /limit <address> 50 -20%  (buys $50 if it drops 20% from now)")
    tok = _resolve(u, args[0])
    try: usd = float(args[1].lstrip("$")); assert usd > 0
    except Exception: return "The amount should be a number, like 50."
    q = P.price(tok)
    if not q: return P.no_price_msg(tok) if hasattr(P, "no_price_msg") else "😕 I couldn't find a live price for that token."
    tgt = args[2]
    try:
        if tgt.endswith("%"):
            pct = float(tgt.rstrip("%")); pct = -abs(pct); target = q[0] * (1 + pct / 100)
        else: target = float(tgt.lstrip("$"))
        assert target > 0
    except Exception: return "The price should be like 0.0012 or -20%."
    if target >= q[0]: return f"${q[1]} is already at {P.px_fmt(q[0])}, which is at or below your target. Just use /buy."
    if usd > u["cash"] + 1e-9: return f"Not enough fake cash. You have {P.money(u['cash'])}."
    with P.LOCK:
        u = P.get(cid); o = {"id": uuid.uuid4().hex[:6], "kind": "limit", "token": tok, "chain": q[2], "symbol": q[1], "usd": usd,
                             "target": target, "created": time.time(), "expires": time.time() + EXPIRE_S}
        u.setdefault("orders", []).append(o); P.put(u)
    return (f"⏳ Practice limit buy set: {P.money(usd)} of ${q[1]} if it drops to {P.px_fmt(target)} "
            f"(now {P.px_fmt(q[0])}, {(target / q[0] - 1) * 100:+.0f}%).\nI check every 5 minutes. It expires in 7 days. /orders to see it.")


def dca(cid, args):
    u = P.get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000."
    if len(args) < 4: return ("How to buy in pieces: /dca <token> <total> <pieces> <every>\n"
                              "Example: /dca <address> 100 4 1h  (buys $25 now, then every hour)")
    tok = _resolve(u, args[0])
    try: total = float(args[1].lstrip("$")); n = int(args[2]); assert total > 0 and 2 <= n <= 50
    except Exception: return "Total should be a number and pieces 2 to 50, like /dca <token> 100 4 1h"
    ev = _every(args[3])
    if not ev or ev < 300: return "Every should be 5m or more, like 30m, 1h or 1d."
    if (n - 1) * ev > EXPIRE_S: return "That plan runs longer than 7 days. Use fewer pieces or a shorter gap."
    if total > u["cash"] + 1e-9: return f"Not enough fake cash. You have {P.money(u['cash'])}."
    q = P.price(tok)
    if not q: return "😕 I couldn't find a live price for that token. Check the address?"
    with P.LOCK:
        u = P.get(cid); o = {"id": uuid.uuid4().hex[:6], "kind": "dca", "token": tok, "chain": q[2], "symbol": q[1], "usd": total / n,
                             "pieces": n, "done": 0, "every": ev, "next": time.time(), "created": time.time(), "expires": time.time() + EXPIRE_S}
        u.setdefault("orders", []).append(o); P.put(u)
    return (f"🧩 Practice DCA set: {P.money(total)} of ${q[1]} in {n} pieces of {P.money(total / n)}, every {_dur(ev)}.\n"
            "The first piece goes in at the next check (within 5 minutes). /orders to see it.")


def describe(o):
    left = max(0, int((o["expires"] - time.time()) / 3600))
    if o["kind"] == "limit":
        return f"Limit buy {P.money(o['usd'])} of ${o['symbol']} at {P.px_fmt(o['target'])} · {left}h left"
    return f"DCA ${o['symbol']}: {o['done']}/{o['pieces']} pieces of {P.money(o['usd'])} every {_dur(o['every'])} · {left}h left"


def list_orders(cid):
    u = P.get(cid)
    if not u: return "🎮 Send /practice first to get your fake $1,000."
    os_ = u.get("orders") or []
    if not os_: return "No open practice orders. Try /limit or /dca."
    return "📋 Your practice orders\n" + "\n".join(f"{i}. {describe(o)}" for i, o in enumerate(os_, 1)) + "\n\n/cancel 1 to cancel one."


def cancel(cid, args):
    with P.LOCK:
        u = P.get(cid)
        if not u: return "🎮 Send /practice first to get your fake $1,000."
        os_ = u.get("orders") or []
        try: i = int(args[0]); assert 1 <= i <= len(os_)
        except Exception: return "Which one? /orders shows the numbers, then /cancel 1."
        o = os_.pop(i - 1); P.put(u)
    return f"✖️ Cancelled: {describe(o)}"


def check_all(send):
    """Fill due orders. send(chat, text, callbacks). Returns number of fills."""
    fills = 0; now = time.time(); px = {}
    for f in os.listdir(P.DIR):  # pass 1, no lock: fetch every price we'll need (network) up front
        try: u = P.get(int(f[:-5]))
        except ValueError: continue
        for o in (u or {}).get("orders") or []:
            k = (o["token"], o["chain"])
            if k not in px and (o["kind"] == "limit" or now >= o.get("next", 0)): px[k] = P.price(*k)
    for f in os.listdir(P.DIR):
        try: cid = int(f[:-5])
        except ValueError: continue
        with P.LOCK:
            u = P.get(cid)
            if not u or not u.get("orders"): continue
            msgs = []; keep = []; btn = None
            for o in u["orders"]:
                if now > o["expires"]:
                    msgs.append(f"⌛ Expired after 7 days: {describe(o)}"); continue
                due = o["kind"] == "dca" and now >= o["next"]
                if o["kind"] == "limit" or due:
                    k = (o["token"], o["chain"])
                    q = px.get(k)  # never hit the network while holding P.LOCK
                    if not q: keep.append(o); continue
                    if o["kind"] == "limit" and q[0] > o["target"]: keep.append(o); continue
                    usd = min(o["usd"], u["cash"])
                    if usd < 1:
                        msgs.append(f"⏭️ Out of fake cash, so this was cancelled: {describe(o)}"); continue
                    _, err = P._buy(u, o["token"], usd, q[0], q[1], q[2], o["kind"])
                    if err: msgs.append(f"⏭️ {err} Cancelled: {describe(o)}"); continue
                    fills += 1; btn = [("🧾 Share PnL card", f"pc:{o['token']}")] if len(o["token"]) <= 60 else None
                    if o["kind"] == "limit":
                        msgs.append(f"🎯 Your practice limit filled: bought {P.money(usd)} of ${q[1]} at {P.px_fmt(q[0] * (1 + P.fee()))} (fee included).\n💵 Fake cash left: {P.money(u['cash'])}")
                        continue
                    o["done"] += 1; o["next"] = now + o["every"]
                    msgs.append(f"🧩 DCA piece {o['done']}/{o['pieces']}: bought {P.money(usd)} of ${q[1]} at {P.px_fmt(q[0] * (1 + P.fee()))} (fee included).\n💵 Fake cash left: {P.money(u['cash'])}")
                    if o["done"] >= o["pieces"]: msgs.append(f"✅ DCA for ${q[1]} is done."); continue
                keep.append(o)
            if msgs or len(keep) != len(u["orders"]):
                u["orders"] = keep; P.put(u)
        if msgs:
            try: send(cid, "\n\n".join(msgs), btn)
            except Exception: pass
    return fills


def loop(send, log, every=300):
    time.sleep(110)  # offset from the launch scan (starts at 20s, every ~180s)
    while True:
        try:
            n = check_all(send)
            if n: log(f"orders: {n} practice fills")
        except Exception:
            log("orders error: " + traceback.format_exc().strip().splitlines()[-1])
        time.sleep(every)


def start(send, log):
    th = threading.Thread(target=loop, args=(send, log), daemon=True, name="orders"); th.start(); return th
