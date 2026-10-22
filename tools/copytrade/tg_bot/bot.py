import re
import threading
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
import gate, tools, practice, refs, card, launches, orders, follows

NAME = "Netro Signal"; HERE = gate.HERE; SEEN = os.path.join(HERE, "pushed.json")
OWNER_CMDS = [
    ("stats", "📊 Who is using the bot", True), ("check", "🔎 Should I buy this token?", True), ("safety", "🛡 Full safety check of a token", True),
    ("watch", "👀 Follow a wallet: /watch address nickname", False), ("unwatch", "🙈 Stop following a wallet", False),
    ("wallets", "📒 Wallets you follow and how they're doing", False), ("scan", "📡 Check your wallets for new buys now", True),
    ("score", "🧮 How good is this wallet?", True), ("smartmoney", "🧠 Best wallets we've found", False),
    ("callers", "📣 X accounts we track", False), ("addcaller", "➕ Track an X account's calls", False),
    ("calls", "📊 How X callers' picks did", False), ("paper", "📝 Results of our fake test trades", False),
    ("papertrade", "🧪 Start a fake $100 test trade", True), ("fomo", "🏁 Fomo leaderboard summary", False),
    ("loss", "🩹 Log a real loss today (reminder only)", False), ("settings", "⚙️ Your limits and sizes", False),
    ("publicname", "🏷 Rename a wallet for practice users: /publicname nickname new label", False)]
PUBLIC_CMDS = [
    ("practice", "🎮 Get $1,000 of fake money to practice", False), ("buy", "🛒 Fake buy: /buy token amount", True),
    ("sell", "💸 Fake sell: /sell token [percent]", True), ("portfolio", "💼 Your practice portfolio", True),
    ("history", "📜 Your practice trades", False), ("pnl", "🧾 Your practice PnL card", True), ("fumbles", "😭 Sold too early? /fumbles, or /fumbles <wallet> for a real Solana wallet", True), ("reset", "🔄 Start practice over", False),
    ("stoploss", "🛑 Auto-sell if down X%", False), ("copy", "🤖 Auto-copy a wallet with fake money", False),
    ("uncopy", "✋ Stop copying", False), ("copygate", "🛡 Skip risky tokens when copying", False),
    ("limit", "🎯 Practice limit buy: /limit token amount -20%", True), ("dca", "🧩 Practice buy in pieces: /dca token total pieces every", True),
    ("orders", "📋 Your practice orders", False), ("cancel", "✖️ Cancel a practice order", False),
    ("launches", "🚀 Alerts for new tokens that pass our check", False),
    ("follows", "🐦 Get alerts when new projects follow big crypto accounts", False),
    ("leaderboard", "🏆 Top practice players", False), ("invite", "👥 Invite friends and earn points", False),
    ("referrals", "🎖 Top inviters", False), ("help", "❓ What Netro Signal can do", False)]
LONG = {c for c, _, l in OWNER_CMDS + PUBLIC_CMDS if l}
RATE = defaultdict(deque); BUSY = {}
# Two lanes so cheap replies never queue behind slow safety checks:
#   FAST: /start, /help, /practice, menus, buttons, portfolio... (mostly local files + cached prices)
#   HEAVY: commands that run a full safety check or scoring (20-60s). At most one heavy job per user at a time.
FAST = ThreadPoolExecutor(max_workers=16, thread_name_prefix="fast"); HEAVY = ThreadPoolExecutor(max_workers=6, thread_name_prefix="heavy")
POOL = FAST  # old name, kept for anything else that imports it
HEAVY_CMDS = {"fumbles", "check", "safety", "score", "scan", "papertrade", "buy", "smartmoney", "fomo", "calls", "callers", "paper", "report"}
HEAVY_RUNNING = set(); HEAVY_LOCK = threading.Lock()


def log(*a): print(time.strftime("%Y-%m-%d %H:%M:%S"), *a, flush=True)


def token():
    t = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not t: sys.exit("TELEGRAM_BOT_TOKEN is not set. Put the bot token in that env var and run again.")
    return t


class TG:
    def __init__(self, tok): self.base = "https://api.telegram.org/bot" + tok + "/"; self._tl = threading.local()

    @property
    def s(self):  # one keep-alive session per thread (requests.Session isn't guaranteed thread-safe)
        if not hasattr(self._tl, "s"): self._tl.s = requests.Session()
        return self._tl.s

    RETRY = {"sendMessage", "editMessageText", "sendPhoto", "answerCallbackQuery"}
    BACKOFF = (1, 3, 6)

    def _retrying(self, method, do):
        """do() -> requests.Response. Retries blips (connection/timeout/SSL, 5xx, 429) for outgoing calls up to 3 times
        on a fresh connection; other 4xx are final. A ReadTimeout retry can double-send if the first one landed (accepted)."""
        tries = len(self.BACKOFF) + 1 if method in self.RETRY else 1
        why = None
        for i in range(tries):
            if i:
                self._tl.s = requests.Session()  # fresh connection after a blip
            try:
                r = do()
                if r.status_code == 429 or r.status_code >= 500:
                    why = f"HTTP {r.status_code}"
                    if i + 1 < tries:
                        try: ra = float((r.json().get("parameters") or {}).get("retry_after") or 0)
                        except Exception: ra = 0
                        time.sleep(min(max(ra, self.BACKOFF[i]), 30)); continue
                d = r.json()
                if i and d.get("ok"): log(f"telegram {method} retried ok ({why})")
                if not d.get("ok"): log(f"telegram {method} error: {d.get('error_code')} {d.get('description')}")
                return d
            except (requests.ConnectionError, requests.Timeout) as e:  # SSLError is a ConnectionError
                why = type(e).__name__
                if i + 1 < tries: time.sleep(self.BACKOFF[i]); continue
            except Exception as e:
                why = type(e).__name__; break
        log(f"telegram {method} " + ("gave up" if tries > 1 else "failed") + f": {why}")  # never log the URL: it holds the token
        return {}

    def call(self, method, p=None, timeout=30):
        return self._retrying(method, lambda: self.s.post(self.base + method, json=p or {}, timeout=timeout))

    def send(self, chat, text, btns=None, cb=None):
        if not isinstance(text, gate.Html): text = gate.esc(text)
        p = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        kb = [[{"text": t, "callback_data": d} for t, d in cb]] if cb else []
        kb += [[{"text": t, "url": u}] for t, u in (btns or [])]
        if kb: p["reply_markup"] = {"inline_keyboard": kb}
        return self.call("sendMessage", p)

    def edit(self, chat, mid, text, btns=None, cb=None):
        """Replace a 'Checking…' message with the result; falls back to a new message if the edit fails."""
        if not mid: return self.send(chat, text, btns, cb)
        if not isinstance(text, gate.Html): text = gate.esc(text)
        p = {"chat_id": chat, "message_id": mid, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
        kb = [[{"text": t, "callback_data": d} for t, d in cb]] if cb else []
        kb += [[{"text": t, "url": u}] for t, u in (btns or [])]
        if kb: p["reply_markup"] = {"inline_keyboard": kb}
        d = self.call("editMessageText", p)
        return d if d.get("ok") else self.send(chat, text, btns, cb)

    def send_photo(self, chat, path, caption="", cb=None, timeout=60):
        """Multipart sendPhoto. caption is plain text unless gate.Html."""
        if not isinstance(caption, gate.Html): caption = gate.esc(caption)
        p = {"chat_id": chat, "caption": caption[:1024], "parse_mode": "HTML"}
        if cb: p["reply_markup"] = json.dumps({"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in cb]]})
        def do():
            with open(path, "rb") as f:
                return requests.post(self.base + "sendPhoto", data=p, files={"photo": ("pnl.png", f, "image/png")}, timeout=timeout)
        return self._retrying("sendPhoto", do)

    def out(self, chat, t, b=None, cb=None):
        """Send one dispatch item: text, or a Photo."""
        if isinstance(t, Photo):
            try: return self.send_photo(chat, t.path, t.caption, cb)
            finally:
                if t.temp:
                    try: os.remove(t.path)
                    except OSError: pass
        return self.send(chat, t, b, cb)


class Photo:
    """Dispatch marker: put in the text slot of a (text, buttons, callbacks) tuple to send an image instead."""
    def __init__(self, path, caption="", temp=True): self.path, self.caption, self.temp = path, caption, temp


DESCRIPTION = ("Netro Signal checks a token before you copy a trade and tells you: looks good, careful, or skip.\n"
               "Practice mode gives you $1,000 of fake money to try it with zero risk.\n"
               "Built by Netrovert. We never touch your funds.")
SHORT_DESCRIPTION = "Should you copy that trade? Netro Signal checks the token first. Practice with $1k fake. By Netrovert"


def help_text(owner):
    L = ["<b>Netro Signal</b> checks tokens and wallets so you don't copy a rug.",
         "You always buy in your own wallet. We never touch your funds.", ""]
    if owner: L += ["<b>Your tools</b>"] + [f"/{c}: {gate.esc(d.split(' ', 1)[1])}" for c, d, _ in OWNER_CMDS] + [""]
    L += ["<b>Practice mode</b> (fake money)"] + [f"/{c}: {gate.esc(d.split(' ', 1)[1])}" for c, d, _ in PUBLIC_CMDS if c != "launches"]
    L += ["", "<b>New launches</b> (real tokens, you buy in your own wallet)", "/launches: get alerts for brand-new tokens that pass our safety check (off until you turn it on)"]
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
           "copygate": lambda: P.copygate(chat, args), "leaderboard": lambda: P.leaderboard(chat), "pnl": lambda: pnl(chat, args), "fumbles": lambda: fumbles(chat, args, is_owner),
           "limit": lambda: orders.limit(chat, args), "dca": lambda: orders.dca(chat, args), "orders": lambda: orders.list_orders(chat),
           "cancel": lambda: orders.cancel(chat, args), "launches": lambda: launches.command(chat, args), "follows": lambda: follows.command(args, chat, is_owner),
           "help": lambda: help_text(is_owner), "start": lambda: (welcome(is_owner, name), None, [("👥 Invite friends", "rf:")]),
           "invite": lambda: refs.invite(chat, name), "referrals": lambda: refs.leaderboard()}
    own = {"stats": lambda: (owner_stats(), None), "check": lambda: tools.check(args), "safety": lambda: tools.safety(args), "watch": lambda: tools.watch(args),
           "unwatch": lambda: tools.unwatch(args), "wallets": lambda: tools.wallets(), "score": lambda: tools.score(args),
           "smartmoney": lambda: tools.smartmoney(), "callers": lambda: tools.callers(), "addcaller": lambda: tools.addcaller(args),
           "calls": lambda: tools.calls(), "paper": lambda: tools.paper(args), "papertrade": lambda: tools.papertrade(args),
           "fomo": lambda: tools.fomo(), "settings": lambda: tools.settings(), "report": lambda: tools.paper([]),
           "loss": lambda: loss(args), "publicname": lambda: publicname(args)}
    if cmd == "scan" and is_owner:
        txt, _, f = tools.scan(args)
        out = [(txt, None, None)]
        if f: out += push_cards(gate.load(f, {}), f, owner_chat=chat)
        return out
    if cmd in own and is_owner: r = own[cmd]()
    elif cmd in pub: r = pub[cmd]()
    elif cmd in own: return [("🔒 That one's only for the owner. You can play with fake money in /practice though!", None, None)]
    else: return [("🤔 I don't know that one. /help has the list.", None, None)]
    if isinstance(r, list): return r
    if isinstance(r, str): return [(r, None, None)]  # plain text gets escaped at send; gate.Html passes through
    if len(r) == 2: return [(r[0], r[1], None)]
    return [r]


def pnl(chat, args):
    """/pnl: portfolio card; /pnl <symbol | number from /history> = one trade's card."""
    if not args:
        st = practice.portfolio_stats(chat)
        if not st: return "🎮 Send /practice first to get your fake $1,000."
        cap = f"🧾 My Netro Signal practice run: {'+' if st['pl'] >= 0 else ''}{practice.money(st['pl'])} ({st['pct']:+.1f}%). Fake money, real prices."
        return [(Photo(card.portfolio_card(st), cap), None, None)]
    d, err = practice.trade_data(chat, args[0])
    if err: return err
    return [(Photo(card.trade_card(d), trade_caption(d)), None, None)]


def fumbles(chat, args=None, is_owner=False):
    if args: return wallet_fumbles(chat, args[0], is_owner)
    f = practice.fumbles(chat)
    if not f: return "🎮 Send /practice first to get your fake $1,000."
    if not f["checked"]: return "No closed trades yet, so nothing to fumble. Sell something and check back 😄"
    if not f["top"]:
        return [(Photo(card.fumble_card(f), f"✅ Checked your last {f['checked']} sells. None of them went higher after you got out. Clean exits!"), None, None)]
    lines = [f"😭 You left {practice.money(f['total'])} on the table across {f['count']} trade{'s' if f['count'] != 1 else ''}."]
    for r in f["top"]:
        lines.append(f"${r['symbol']}: sold at {card.px_fmt(r['sold'])}, it went to {card.px_fmt(r['peak'])}" + (" (price now)" if r["src"] == "now" else "")
                     + f". That's {practice.money(r['missed'])} missed.")
    lines.append("Practice mode, fake money. Peaks are the highest price since you sold.")
    return [(Photo(card.fumble_card(f), "\n".join(lines)[:1000]), None, None)]


def wallet_fumbles(chat, addr, is_owner=False):
    import wfumbles
    f, err = wfumbles.scan(chat, addr.strip(), is_owner)
    if err: return err
    who = wfumbles.short(f["addr"])
    if not f["checked"]: return f"🔎 I couldn't find any sells from {who} in the last 30 days. Nothing to fumble!"
    if not f["top"]:
        return [(Photo(card.fumble_card(f), f"✅ {who}: checked {f['checked']} sells from the last 30 days. Nothing went higher after they sold. Clean exits!"), None, None)]
    lines = [f"😭 {who} left {practice.money(f['total'])} on the table across {f['count']} sell{'s' if f['count'] != 1 else ''} in the last 30 days."]
    for r in f["top"]:
        lines.append(f"${r['symbol']}: sold at {card.px_fmt(r['sold'])}, it went to {card.px_fmt(r['peak'])}" + (" (price now)" if r["src"] == "now" else "")
                     + f". That's {practice.money(r['missed'])} missed.")
    lines.append("Peaks are the highest price since each sell. Public on-chain data only.")
    return [(Photo(card.fumble_card(f), "\n".join(lines)[:1000]), None, None)]


def trade_caption(d):
    return (f"🧾 ${d['symbol']}: {'+' if d['pl'] >= 0 else ''}{practice.money(d['pl'])} ({d['pct']:+.1f}%)"
            + (" so far" if d["open"] else "") + ". Practice trade on Netro Signal, fake money.")


def publicname(args):
    """Owner: /publicname <nickname or address> <new public label>. No args: list current public labels."""
    ws = gate.public_wallets(); nick = {w["address"]: w["label"] for w in gate.load(gate.WALLETS, [])}
    if not args:
        return "🏷 What practice users see:\n" + "\n".join(f"{p['n']}. {nick.get(p['address'], '?')} → {p['label']} ({p['desc']})" for p in ws) + \
               "\n\nRename: /publicname <nickname> <new label>"
    for i in range(len(args) - 1, 0, -1):
        w = gate.find_wallet(" ".join(args[:i]))
        if w: break
    else: return "🤔 I couldn't match a wallet nickname. Usage: /publicname <nickname> <public label>"
    if gate.is_test(w["label"]): return "Test wallets aren't shown to practice users."
    new = " ".join(args[i:]).strip()[:40]
    if any(nk.lower() in new.lower() for nk in nick.values() if len(nk) > 2): return "That label has a private nickname in it. Pick something else."
    c = gate.cfg(); e = c.setdefault("public_labels", {}).get(w["address"])
    if not e: return "That wallet has no public label yet. Try again in a sec."
    e["label"] = new; gate.save_cfg(c); practice.migrate_all()
    return f"🏷 Done. Practice users now see {w['label']} as “{new}”."


def loss(args):
    try: tot = gate.log_loss(float(args[0].lstrip("$")))
    except Exception: return "Usage: /loss 20", None
    return f"Logged. Today's losses: ${tot:,.0f} of your ${gate.cfg().get('daily_loss_limit_usd')} limit (just a reminder; nothing is blocked).", None


PENDING = {}  # chat -> {"cmd", "pre", "post", "exp"}: we asked for an amount; a bare number (or button) finishes it
AMOUNT_ASK = "How much fake money do you want to put in? Just reply with a number, like 50."
AMOUNT_BTNS = [("$20", "am:20"), ("$50", "am:50"), ("$100", "am:100"), ("$250", "am:250")]


def parse_amount(t):
    m = re.fullmatch(r"\$?\s*(\d+(?:[.,]\d+)?)\s*(?:\$|usd|dollars?)?", t.strip().lower())
    return m.group(1).replace(",", ".") if m else None


def needs_amount(cmd, args):
    """(pre, post) args around the missing amount, or None if nothing is missing."""
    if cmd == "buy" and len(args) == 1: return [args[0]], []
    if cmd == "limit" and len(args) == 2 and parse_amount(args[1]) is None: return [args[0]], [args[1]]  # /limit TOKEN -20%
    return None


def handle_message(tg, msg):
    c = gate.cfg(); chat = msg.get("chat", {}).get("id"); text = (msg.get("text") or "").strip()
    if msg.get("chat", {}).get("type") != "private": return
    pend = PENDING.pop(chat, None)
    if not text.startswith("/") and pend and pend["cmd"] == "fumbles" and pend["exp"] > time.time() and re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", text):
        text = "/fumbles " + text
    if not text.startswith("/"):
        amt = parse_amount(text) if pend and pend["exp"] > time.time() and pend["cmd"] != "fumbles" else None
        if not amt: return
        text = " ".join(["/" + pend["cmd"]] + pend["pre"] + [amt] + pend["post"])
    cmd, *args = text.split(); cmd = cmd[1:].split("@")[0].lower()
    try:
        fresh = refs.touch(chat)
        if fresh and cmd == "start" and args and args[0].startswith("ref_"):
            refs.attach(chat, args[0], (msg.get("from") or {}).get("first_name") or (msg.get("from") or {}).get("username"))
    except Exception: log("referral error: " + traceback.format_exc().strip().splitlines()[-1])
    miss = needs_amount(cmd, args)
    if miss and practice.get(chat):
        PENDING[chat] = {"cmd": cmd, "pre": miss[0], "post": miss[1], "exp": time.time() + 300}
        return FAST.submit(tg.send, chat, AMOUNT_ASK, None, AMOUNT_BTNS)
    name = (msg.get("from") or {}).get("first_name") or "anon"
    if c.get("owner_chat_id") is None and cmd == "start":
        c["owner_chat_id"] = chat; gate.save_cfg(c); log("owner set"); set_commands(tg, chat)
        return FAST.submit(tg.send, chat, welcome(True, name))
    is_owner = chat == c.get("owner_chat_id")
    if not is_owner and limited(chat): return
    log(f"command /{cmd} from {'owner' if is_owner else 'user'}")
    quick_no = not is_owner and cmd not in {c for c, _, _ in PUBLIC_CMDS} | {"start", "help"}  # owner-only/unknown: instant reply
    heavy = cmd in HEAVY_CMDS and not quick_no
    if heavy:
        with HEAVY_LOCK:
            if chat in HEAVY_RUNNING:
                FAST.submit(tg.send, chat, "⏳ I'm still working on your last one. I'll answer that first, then send this again."); return
            HEAVY_RUNNING.add(chat)
    def job():
        BUSY[id(job)] = time.time(); t0 = time.time(); mid = None
        try:
            if (heavy or cmd in LONG) and not quick_no:  # quick 'Checking…' now, then edit it with the result
                mid = (tg.send(chat, "🔎 Scanning wallet… this can take a minute." if cmd == "fumbles" and args else "⏳ Checking… one moment.") or {}).get("result", {}).get("message_id")
            out = dispatch(cmd, args, chat, name, is_owner)
            for i, (t, b, cb) in enumerate(out):
                if i == 0 and mid and not isinstance(t, Photo): tg.edit(chat, mid, t, b, cb)
                else: tg.out(chat, t, b, cb)
            if time.time() - t0 > 20: log(f"slow /{cmd}: {time.time() - t0:.0f}s")
        except Exception:
            log(f"handler /{cmd} error: " + traceback.format_exc().strip().splitlines()[-1])
            msg = "😕 Something went wrong on my side. Please try again in a minute."
            tg.edit(chat, mid, msg) if mid else tg.send(chat, msg)
        finally:
            BUSY.pop(id(job), None)
            if heavy:
                with HEAVY_LOCK: HEAVY_RUNNING.discard(chat)
    (HEAVY if heavy else FAST).submit(job)


def handle_callback(tg, cq):
    chat = cq.get("message", {}).get("chat", {}).get("id"); data = cq.get("data") or ""
    toast = {"callback_query_id": cq["id"]}
    if data.startswith("ls:"): toast["text"] = "Sniping $50…"
    FAST.submit(tg.call, "answerCallbackQuery", toast, 10)  # right away, off the polling thread
    if chat and data.startswith("am:"):  # amount button: finish the pending /buy or /limit like a typed number
        pend = PENDING.get(chat)
        if not pend or pend["exp"] < time.time():
            PENDING.pop(chat, None); FAST.submit(tg.send, chat, "⌛ That one expired. Send the command again."); return
        return handle_message(tg, {"chat": {"id": chat, "type": "private"}, "from": cq.get("from"), "text": data[3:]})
    if not chat or not data[:3] in ("pb:", "px:", "pc:", "ls:", "pf:", "rf:"): return
    if chat != gate.cfg().get("owner_chat_id") and limited(chat): return
    def job():
        BUSY[id(job)] = time.time()
        try:
            if data.startswith("ls:"):  # Practice snipe from a launch card: same flow as /buy <token> 50
                _, ch, tok = data.split(":", 2)
                mid = (tg.send(chat, "⏳ Buying…") or {}).get("result", {}).get("message_id")
                r = practice.snipe(chat, tok, launches.SHORT.get(ch, ch))  # no re-check: verdict came from the launch scan
                tg.edit(chat, mid, r) if mid else tg.send(chat, r)
            elif data.startswith("rf:"):
                t, bb = refs.invite(chat, (cq.get("from") or {}).get("first_name") or ""); tg.send(chat, t, bb)
            elif data.startswith("pf:"):
                PENDING[chat] = {"cmd": "fumbles", "pre": [], "post": [], "exp": time.time() + 300}
                tg.send(chat, "😭 Here are your practice fumbles. Want to see a real wallet's? Just send me its Solana address.")
                for t, bb, cb in (lambda r: [(r, None, None)] if isinstance(r, str) else r)(fumbles(chat)): tg.out(chat, t, bb, cb)
            elif data.startswith("pc:"):
                for t, b, cb in (lambda r: [(r, None, None)] if isinstance(r, str) else r)(pnl(chat, [data[3:]])): tg.out(chat, t, b, cb)
            else: tg.send(chat, practice.confirm(chat, data))
        except Exception: log("callback error: " + traceback.format_exc().strip().splitlines()[-1])
        finally: BUSY.pop(id(job), None)
    (HEAVY if data.startswith("pf:") else FAST).submit(job)


HERE_DIR = os.path.dirname(os.path.abspath(__file__))


def owner_stats():
    import glob, json as J
    now = time.time(); us = []
    for f in glob.glob(os.path.join(HERE_DIR, "practice", "users", "*.json")):
        try: u = J.load(open(f)); u["_m"] = os.path.getmtime(f); us.append(u)
        except Exception: pass
    act = lambda sec: sum(1 for u in us if now - u["_m"] < sec)
    trades = sum(len(u.get("history") or []) for u in us); opens = sum(len(u.get("positions") or {}) for u in us)
    copying = sum(1 for u in us if u.get("copy")); traded = sum(1 for u in us if u.get("history") or u.get("positions"))
    def worth(u): return (u.get("cash") or 0) + sum((p.get("cost") or p.get("usd") or 0) for p in (u.get("positions") or {}).values())
    top = sorted(us, key=worth, reverse=True)[:5]
    cmds = {"user": 0, "owner": 0}; cut = time.strftime("%Y-%m-%d %H:%M", time.localtime(now - 86400))
    try:
        for ln in open(os.path.join(HERE_DIR, "bot.log")):
            if ln[:16] >= cut and " command /" in ln: cmds["owner" if ln.rstrip().endswith("owner") else "user"] += 1
    except Exception: pass
    L = ["📊 <b>Netro Signal stats</b>", "", f"👥 Practice players: <b>{len(us)}</b>",
         f"Active in the last 24h: {act(86400)} · last 7 days: {act(7*86400)}",
         f"Made at least one fake trade: {traded}", f"Fake trades closed: {trades} · open now: {opens}",
         f"Copying a wallet: {copying}", refs.stats(), f"Commands from players in the last 24h: {cmds['user']} (you: {cmds['owner']})"]
    if top:
        L += ["", "🏆 <b>Top balances</b> (open trades at cost)"]
        L += [f"{i}. {gate.esc(u.get('name') or 'anon')}: ${worth(u):,.0f}" for i, u in enumerate(top, 1)]
    return gate.Html("\n".join(L))


LAST_POLL = [time.time()]
HEARTBEAT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot.heartbeat")


def _watchdog():
    while True:
        time.sleep(30)
        try:  # housekeeping so per-chat dicts can't grow forever
            t = time.time()
            for k in [k for k, v in list(PENDING.items()) if v["exp"] < t]: PENDING.pop(k, None)
            for k in [k for k, q in list(RATE.items()) if not q or t - q[-1] > 3600]: RATE.pop(k, None)
        except Exception: pass
        stuck_poll = time.time() - LAST_POLL[0] > 150
        stuck_job = BUSY and time.time() - min(BUSY.values()) > 600
        if stuck_poll or stuck_job:
            log(f"watchdog: {'polling' if stuck_poll else 'a reply'} stuck, restarting")
            os.execv(sys.executable, [sys.executable] + sys.argv)


def run():
    tg = TG(token()); me = tg.call("getMe", timeout=15); refs.SEND = tg.send
    if not me.get("ok"): sys.exit("getMe failed: check the token.")
    gate.public_wallets(); log(f"practice: migrated {practice.migrate_all()} users to public labels")
    log(f"{NAME} running as @{me['result'].get('username')}, polling"); set_commands(tg, gate.cfg().get("owner_chat_id")); set_profile(tg)
    off = None
    threading.Thread(target=_watchdog, daemon=True).start()
    # Background jobs run in their own daemon threads with their own timeouts; they never touch BUSY, so they can't trip the watchdog
    # or block polling. Every send goes through TG.call (30s timeout, errors logged).
    launches.start(lambda ch, t, btn, cb: tg.send(ch, t, btn, cb), log)
    orders.start(lambda ch, t, cb=None: tg.send(ch, gate.Html(gate.esc(t) + "\n\n<i>🎮 Practice mode · fake money only</i>"), None, cb), log)
    follows.start(lambda ch, t, btn, cb: tg.send(ch, t, btn, cb), log)  # follow alerts (owner + opted-in users), own thread, starts ~200s in
    while True:
        try:
            LAST_POLL[0] = time.time()
            try: open(HEARTBEAT, "w").write(str(time.time()))  # outside supervisor (supervise.sh) restarts us if this goes stale
            except OSError: pass
            d = tg.call("getUpdates", {"offset": off, "timeout": 25, "allowed_updates": ["message", "callback_query"]}, timeout=(5, 35))
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
    gate.atomic_dump(sorted(seen), SEEN)
    for s in scan.get("swaps", []):  # gate verdicts for copy fills, incl. tokens already carded earlier
        if s["side"] == "BUY" and not gate.is_test(s.get("label")) and s["token"] not in cache:
            if any((practice.get(int(f[:-5])) or {}).get("copy", {}) and practice.get(int(f[:-5]))["copy"]["address"].lower() == s["wallet"].lower() for f in os.listdir(practice.DIR)):
                cache[s["token"]] = gate.gate(s["token"], s["chain"], s["label"], scan_file, narrative=False)
    closes = {}; fills = practice.copy_fills(scan, cache, closes)
    if sender:
        for chat, msgs in fills.items(): sender(chat, "\n\n".join(msgs), [practice.share_btn(closes[chat])] if chat in closes else None)
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
    cards = push_cards(gate.load(scan_file, {}), scan_file, sender=lambda ch, t, cb=None: tg.send(ch, gate.Html(gate.esc(t) + "\n\n<i>🎮 Practice mode · fake money only</i>"), None, cb))
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
