#!/usr/bin/env python3
"""Netro Signal: Telegram trade-gate bot. Never holds keys, signs or trades.
Owner-only tools + practice mode (fake money) for anyone.

python3 bot.py run                          # long polling
python3 bot.py push --scan-file <file>      # owner cards for new non-test BUYs + practice copy-trade fills
python3 bot.py set-commands                 # (run also does this) set the Telegram command menus
Token: env TELEGRAM_BOT_TOKEN (never printed or logged).
"""
import argparse, json, os, sys, time, traceback, threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
import requests
import gate, tools, practice

NAME = "Netro Signal"; HERE = gate.HERE; SEEN = os.path.join(HERE, "pushed.json")
OWNER_CMDS = [
    ("check", "🔎 Should I buy this token?", True), ("safety", "🛡 Full safety check of a token", True),
    ("watch", "👀 Follow a wallet: /watch address nickname", False), ("unwatch", "🙈 Stop following a wallet", False),
    ("wallets", "📒 Wallets you follow and how they're doing", False), ("scan", "📡 Check your wallets for new buys now", True),
    ("score", "🧮 How good is this wallet?", True), ("smartmoney", "🧠 Best wallets we've found", False),
    ("callers", "📣 X accounts we track", False), ("addcaller", "➕ Track an X account's calls", False),
    ("calls", "📊 How X callers' picks did", False), ("paper", "📝 Results of our fake test trades", False),
    ("papertrade", "🧪 Start a fake $100 test trade", True), ("fomo", "🏁 Fomo leaderboard summary", False),
    ("loss", "🩹 Log a real loss today (reminder only)", False), ("settings", "⚙️ Your limits and sizes", False)]
PUBLIC_CMDS = [
    ("practice", "🎮 Get $1,000 of fake money to practice", False), ("buy", "🛒 Fake buy: /buy token amount", True),
    ("sell", "💸 Fake sell: /sell token [percent]", True), ("portfolio", "💼 Your practice portfolio", True),
    ("history", "🧾 Your practice trades", False), ("reset", "🔄 Start practice over", False),
    ("stoploss", "🛑 Auto-sell if down X%", False), ("copy", "🤖 Auto-copy a wallet with fake money", False),
    ("uncopy", "✋ Stop copying", False), ("copygate", "🛡 Skip risky tokens when copying", False),
    ("leaderboard", "🏆 Top practice players", False), ("help", "❓ What Netro Signal can do", False)]
LONG = {c for c, _, l in OWNER_CMDS + PUBLIC_CMDS if l}
RATE = defaultdict(deque); POOL = ThreadPoolExecutor(max_workers=8); BUSY = {}


def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t: sys.exit("TELEGRAM_BOT_TOKEN is not set. Put the bot token in that env var and run again.")
    return t


class TG:
    def __init__(self, tok): self.base = "https://api.telegram.org/bot" + tok + "/"; self.s = requests.Session()

    def call(self, method, p=None, timeout=30):
        try:
            d = requests.post(self.base + method, json=p or {}, timeout=timeout).json()
            if not d.get("ok"): log(f"telegram {method} error: {d.get('error_code')} {d.get('description')}")
            return d
        except Exception as e:  # never log the URL: it holds the token
            log(f"telegram {method} failed: {type(e).__name__}"); return {}

    def send(self, chat, text, btns=None, cb=None):
        if not isinstance(text, gate.Html): text = gate.esc(text)
        p = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        kb = [[{"text": t, "callback_data": d} for t, d in cb]] if cb else []
        kb += [[{"text": t, "url": u}] for t, u in (btns or [])]
        if kb: p["reply_markup"] = {"inline_keyboard": kb}
        return self.call("sendMessage", p)


DESCRIPTION = ("Netro Signal checks a token before you copy a trade and tells you: looks good, careful, or skip.\n"
               "Practice mode gives you $1,000 of fake money to try it with zero risk.\n"
               "Built by Netrovert. We never touch your funds.")
SHORT_DESCRIPTION = "Should you copy that trade? Netro Signal checks the token first. Practice with $1k fake. By Netrovert"


def help_text(owner):
    L = ["<b>Netro Signal</b> checks tokens and wallets so you don't copy a rug.",
         "You always buy in your own wallet. We never touch your funds.", ""]
    if owner: L += ["<b>Your tools</b>"] + [f"/{c}: {gate.esc(d.split(' ', 1)[1])}" for c, d, _ in OWNER_CMDS] + [""]
    L += ["<b>Practice mode</b> (fake money)"] + [f"/{c}: {gate.esc(d.split(' ', 1)[1])}" for c, d, _ in PUBLIC_CMDS]
    return gate.Html("\n".join(L))


def welcome(owner, name):
    n = gate.esc(name or "there")
    if owner:
        return gate.Html(f"👋 Hey {n}, welcome to <b>Netro Signal</b>. This bot is yours now.\n\n"
            "Send /check with any token and I'll tell you: 🟢 looks good, 🟡 careful, or 🔴 skip, with the reasons and a safe size.\n"
            "I'll also ping you when the wallets you follow buy something.\n\n"
            "Everything else is in the menu or /help. Other people only get practice mode.\n\n" + gate.FOOTER)
    return gate.Html(f"👋 Hey {n}, welcome to <b>Netro Signal</b> by Netrovert.\n\n"
        "Want to learn copy-trading without risking a cent? Send /practice and you get <b>$1,000 of fake money</b>. "
        "Buy at real prices, copy real wallets, and see how you'd do.\n\n"
        "Nothing here is real money and no wallet is ever connected.\n\n/help shows everything.")


def set_profile(tg):
    """BotFather-equivalent settings available in the Bot API. Idempotent."""
    r = {}
    cur = tg.call("getMyName").get("result", {}).get("name")
    r["name"] = "already set" if cur == NAME else tg.call("setMyName", {"name": NAME}).get("ok")
    r["description"] = tg.call("setMyDescription", {"description": DESCRIPTION}).get("ok")
    r["short_description"] = tg.call("setMyShortDescription", {"short_description": SHORT_DESCRIPTION}).get("ok")
    r["menu_button"] = tg.call("setChatMenuButton", {"menu_button": {"type": "commands"}}).get("ok")
    log("profile: " + ", ".join(f"{k}={v}" for k, v in r.items())); return r


def set_commands(tg, owner):
    pub = [{"command": c, "description": d[:256]} for c, d, _ in PUBLIC_CMDS]
    tg.call("setMyCommands", {"commands": pub, "scope": {"type": "default"}})
    if owner:
        allc = [{"command": c, "description": d[:256]} for c, d, _ in OWNER_CMDS] + pub
        tg.call("setMyCommands", {"commands": allc, "scope": {"type": "chat", "chat_id": owner}})
    log("command menus set" + (" (owner too)" if owner else ""))


def limited(chat):
    q = RATE[chat]; t = time.time()
    while q and t - q[0] > 3600: q.popleft()
    if len(q) >= gate.cfg().get("public_rate_per_hour", 30): return True
    q.append(t); return False


def dispatch(cmd, args, chat, name, is_owner):
    """Returns list of (text, url_buttons, callback_buttons). Pure: no Telegram I/O, so it can be tested directly."""
    P = practice
    pub = {"practice": lambda: P.start(chat, name), "buy": lambda: P.buy_request(chat, args), "sell": lambda: P.sell(chat, args),
           "portfolio": lambda: P.portfolio(chat), "history": lambda: P.history(chat), "reset": lambda: P.reset(chat, name),
           "stoploss": lambda: P.stoploss(chat, args), "copy": lambda: P.copy(chat, args), "uncopy": lambda: P.uncopy(chat),
           "copygate": lambda: P.copygate(chat, args), "leaderboard": lambda: P.leaderboard(chat),
           "help": lambda: help_text(is_owner), "start": lambda: welcome(is_owner, name)}
    own = {"check": lambda: tools.check(args), "safety": lambda: tools.safety(args), "watch": lambda: tools.watch(args),
           "unwatch": lambda: tools.unwatch(args), "wallets": lambda: tools.wallets(), "score": lambda: tools.score(args),
           "smartmoney": lambda: tools.smartmoney(), "callers": lambda: tools.callers(), "addcaller": lambda: tools.addcaller(args),
           "calls": lambda: tools.calls(), "paper": lambda: tools.paper(args), "papertrade": lambda: tools.papertrade(args),
           "fomo": lambda: tools.fomo(), "settings": lambda: tools.settings(), "report": lambda: tools.paper([]),
           "loss": lambda: loss(args)}
    if cmd == "scan" and is_owner:
        txt, _, f = tools.scan(args)
        out = [(txt, None, None)]
        if f: out += push_cards(gate.load(f, {}), f, owner_chat=chat)
        return out
    if cmd in own and is_owner: r = own[cmd]()
    elif cmd in pub: r = pub[cmd]()
    elif cmd in own: return [("🔒 That one's only for the owner. You can play with fake money in /practice though!", None, None)]
    else: return [("🤔 I don't know that one. /help has the list.", None, None)]
    if isinstance(r, str): return [(r, None, None)]  # plain text gets escaped at send; gate.Html passes through
    if len(r) == 2: return [(r[0], r[1], None)]
    return [r]


def loss(args):
    try: tot = gate.log_loss(float(args[0].lstrip("$")))
    except Exception: return "Usage: /loss 20", None
    return f"Logged. Today's losses: ${tot:,.0f} of your ${gate.cfg().get('daily_loss_limit_usd')} limit (just a reminder; nothing is blocked).", None


def handle_message(tg, msg):
    c = gate.cfg(); chat = msg.get("chat", {}).get("id"); text = (msg.get("text") or "").strip()
    if not text.startswith("/") or msg.get("chat", {}).get("type") != "private": return
    cmd, *args = text.split(); cmd = cmd[1:].split("@")[0].lower()
    name = (msg.get("from") or {}).get("first_name") or "anon"
    if c.get("owner_chat_id") is None and cmd == "start":
        c["owner_chat_id"] = chat; gate.save_cfg(c); log("owner set"); set_commands(tg, chat)
        return tg.send(chat, welcome(True, name))
    is_owner = chat == c.get("owner_chat_id")
    if not is_owner and limited(chat): return
    log(f"command /{cmd} from {'owner' if is_owner else 'user'}")
    if cmd in LONG: tg.send(chat, "⏳ On it, one moment…")
    def job():
        BUSY[id(job)] = time.time()
        try:
            for t, b, cb in dispatch(cmd, args, chat, name, is_owner): tg.send(chat, t, b, cb)
        except Exception:
            log(f"handler /{cmd} error: " + traceback.format_exc().strip().splitlines()[-1]); tg.send(chat, "😕 Something went wrong on my side. Please try again in a minute.")
        finally: BUSY.pop(id(job), None)
    POOL.submit(job)


def handle_callback(tg, cq):
    chat = cq.get("message", {}).get("chat", {}).get("id"); data = cq.get("data") or ""
    tg.call("answerCallbackQuery", {"callback_query_id": cq["id"]})
    if not chat or not data[:3] in ("pb:", "px:"): return
    if chat != gate.cfg().get("owner_chat_id") and limited(chat): return
    def job():
        BUSY[id(job)] = time.time()
        try: tg.send(chat, practice.confirm(chat, data))
        except Exception: log("callback error: " + traceback.format_exc().strip().splitlines()[-1])
    POOL.submit(job)


def run():
    tg = TG(token()); me = tg.call("getMe", timeout=15)
    if not me.get("ok"): sys.exit("getMe failed: check the token.")
    log(f"{NAME} running as @{me['result'].get('username')}, polling"); set_commands(tg, gate.cfg().get("owner_chat_id")); set_profile(tg)
    off = None
    while True:
        try:
            d = tg.call("getUpdates", {"offset": off, "timeout": 50, "allowed_updates": ["message", "callback_query"]}, timeout=60)
            for u in d.get("result", []):
                off = u["update_id"] + 1
                try:
                    if "message" in u: handle_message(tg, u["message"])
                    elif "callback_query" in u: handle_callback(tg, u["callback_query"])
                except Exception: log("update error: " + traceback.format_exc().strip().splitlines()[-1])
            if not d.get("ok"): time.sleep(5)
            if BUSY and time.time() - min(BUSY.values()) > 600:
                log("watchdog: a reply was stuck over 10 min, restarting"); os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            log("poll loop error: " + traceback.format_exc().strip().splitlines()[-1]); time.sleep(5)


def push_cards(scan, scan_file, owner_chat=None, sender=None):
    """Owner verdict cards for new non-test BUYs + practice copy fills. Returns owner messages; practice msgs go via sender."""
    c = gate.cfg(); seen = set(gate.load(SEEN, [])); done = set(); out = []; cache = {}
    for s in scan.get("swaps", []):
        if s.get("side") != "BUY" or gate.is_test(s.get("label")): continue
        key = f"{s['tx']}:{s['token']}"; tk = (s["wallet"], s["token"])
        if key in seen or tk in done: seen.add(key); continue
        seen.add(key); done.add(tk)
        g = cache.get(s["token"]) or gate.gate(s["token"], s["chain"], s["label"], scan_file); cache[s["token"]] = g
        if len(out) >= c.get("push_max_cards", 10): continue
        out.append((gate.card_text(g, alert_header(scan, s)), g["buttons"], None))
    json.dump(sorted(seen), open(SEEN, "w"))
    for s in scan.get("swaps", []):  # gate verdicts for copy fills, incl. tokens already carded earlier
        if s["side"] == "BUY" and not gate.is_test(s.get("label")) and s["token"] not in cache:
            if any((practice.get(int(f[:-5])) or {}).get("copy", {}) and practice.get(int(f[:-5]))["copy"]["address"].lower() == s["wallet"].lower() for f in os.listdir(practice.DIR)):
                cache[s["token"]] = gate.gate(s["token"], s["chain"], s["label"], scan_file, narrative=False)
    fills = practice.copy_fills(scan, cache)
    if sender:
        for chat, msgs in fills.items(): sender(chat, "\n\n".join(msgs))
    log(f"push: {len(out)} owner cards, copy fills for {len(fills)} users")
    return out if sender else out + [("[practice] " + "\n".join(m), None, None) for _, m in fills.items()]


def alert_header(scan, s):
    same = [x for x in scan.get("swaps", []) if x["side"] == "BUY" and x["wallet"] == s["wallet"] and x["token"] == s["token"]]
    usd = sum(x.get("usd") or 0 for x in same); n = len(same); span = max(x["time"] for x in same) - min(x["time"] for x in same)
    sym = gate.esc((s.get("symbol") or "?").lstrip("$"))
    amt = f"{gate.usd_short(usd)} of " if usd else ""
    when = "" if n == 1 else f" ({n} buys in {max(1, round(span/60))} min)" if span >= 60 else f" ({n} buys in {span}s)"
    t = s.get("time_wat", "").split(" ")[1] if " " in s.get("time_wat", "") else ""
    return f"👀 <b>{gate.esc(s['label'])}</b> just bought {amt}${sym}{when}" + (f" · {t} WAT" if t else "")


def push(scan_file):
    tg = TG(token()); owner = gate.cfg().get("owner_chat_id")
    cards = push_cards(gate.load(scan_file, {}), scan_file, sender=lambda ch, t: tg.send(ch, gate.Html(gate.esc(t) + "\n\n<i>🎮 Practice mode · fake money only</i>")))
    if owner:
        for t, b, cb in cards: tg.send(owner, t, b, cb)
    elif cards: log("no owner yet: owner cards not sent")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run"); sub.add_parser("set-commands"); p = sub.add_parser("push"); p.add_argument("--scan-file", default=gate.SCAN)
    a = ap.parse_args()
    if a.cmd == "run": run()
    elif a.cmd == "push": push(a.scan_file)
    else: tg = TG(token()); set_commands(tg, gate.cfg().get("owner_chat_id")); set_profile(tg)


if __name__ == "__main__": main()
