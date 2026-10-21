"""Follow alerts (owner only): every 90 min read the FIRST page (20 newest) of followers of ~20 big X accounts via
twitterapi.io, keep a seen-set per account, and flag brand-new project accounts. Budget: 60 credits ($0.0006) per call,
~20 calls/run, 16 runs/day -> ~$5.8/month. Hard cap: no calls once estimated spend this month >= cap_usd ($17).
Config (owner-editable): follows_config.json. State: follows_state.json. Key: env TWITTERAPI_IO_KEY (never logged)."""
import json, os, re, threading, time, traceback, random
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import requests
import gate

HERE = gate.HERE
CFG = os.path.join(HERE, "follows_config.json"); STATE_P = os.path.join(HERE, "follows_state.json")
API = "https://api.twitterapi.io/twitter/user/followers"
LOCK = threading.RLock(); S = requests.Session(); S.headers["User-Agent"] = "netro-signal/1.0"
DEFAULT = {"every_s": 5400, "page_size": 20, "cap_usd": 17.0, "call_gap_s": 6, "max_age_days": 90, "max_followers": 5000,
           "min_score": 3, "strong_min_accounts": 3,
           "accounts": ["solana", "base", "HyperliquidX", "RobinhoodApp", "ethereum", "arbitrum", "inkonchain", "JupiterExchange",
                        "phantom", "coinbase", "toly", "rajgokal", "jessepollak", "VitalikButerin", "chameleon_jeff",
                        "brian_armstrong", "Pumpfun", "mert", "MeteoraAG", "helius"]}
KW = re.compile(r"\b(building|built on|protocol|testnet|mainnet|launch(ing|ed)?|dex|l2|layer ?2|app|defi|perps?|swap|"
                r"airdrop|token|onchain|on-chain|rollup|chain|network|labs|finance|fi|vault|yield|nft|agent|ai agent|"
                r"infra|sdk|api|wallet|liquidity|stablecoin|points|waitlist|beta|devnet|coming soon|dapp|exchange|lending)\b", re.I)
ECO = re.compile(r"(on|built on|powered by|backed by)\s+@?(solana|base|hyperliquid\w*|hyperevm|ethereum|arbitrum|ink\w*|robinhood\w*)|"
                 r"@(solana|base|hyperliquidx|arbitrum|inkonchain|jupiterexchange)\b", re.I)
PERSONAL = re.compile(r"\b(he/him|she/her|they/them|husband|wife|dad|mom|father|mother|views (are )?my own|my opinions|"
                      r"i'?m a|i am a|student|enthusiast|trader|investor|degen|nfa|dyor|lover|fan of)\b", re.I)


def cfg():
    c = gate.load(CFG, None)
    if not c: c = dict(DEFAULT); gate.atomic_dump(c, CFG, indent=2)
    return {**DEFAULT, **c}


def save_cfg(c): gate.atomic_dump(c, CFG, indent=2)
def state(): return gate.load(STATE_P, {"seen": {}, "recent": {}, "month": "", "credits": 0, "calls": 0, "flags": [], "last_run": None})
def save_state(s): gate.atomic_dump(s, STATE_P)
def month(): return time.strftime("%Y-%m")
def usd(credits): return credits / 100000.0


def call_credits(n):
    """twitterapi.io followers tiers: 20-99 -> 3/follower, 100-199 -> 2, 200 -> 1; minimum 60 credits per call."""
    per = 1 if n >= 200 else 2 if n >= 100 else 3
    return max(60, n * per)


def fetch(handle, page_size):
    key = os.environ.get("TWITTERAPI_IO_KEY")
    if not key: return None, "no key"
    try:
        r = S.get(API, params={"userName": handle, "pageSize": page_size}, headers={"X-API-Key": key}, timeout=(5, 25))
        j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code != 200 or j.get("status") == "error": return None, f"http {r.status_code} {str(j.get('msg') or '')[:80]}"
        return j.get("followers") or [], None
    except Exception as e:
        return None, type(e).__name__


def created(u):
    v = u.get("created_at") or u.get("createdAt")
    if not v: return None
    try: return parsedate_to_datetime(v) if not v[:4].isdigit() else datetime.fromisoformat(v.replace("Z", "+00:00"))
    except Exception:
        try: return datetime.strptime(v, "%a %b %d %H:%M:%S %z %Y")
        except Exception: return None


def age_days(u):
    d = created(u)
    return None if d is None else (datetime.now(timezone.utc) - d).total_seconds() / 86400


def score(u, c):
    """Score from the data already returned (no extra calls). Returns (score, reasons) or (None, why) if gated out."""
    age = age_days(u); fol = u.get("followers_count") or 0
    if age is None or age > c["max_age_days"]: return None, "old"
    if fol >= c["max_followers"]: return None, "big"
    if u.get("protected"): return None, "protected"
    bio = (u.get("description") or "") + " " + (u.get("name") or "")
    site = u.get("url") or ""
    s, why = 0, []
    s += 2 if age <= 30 else 1; why.append(f"{int(age)}d old")
    k = set(m.group(0).lower() for m in KW.finditer(bio))
    if k: s += min(3, len(k)); why.append("bio: " + ", ".join(sorted(k)[:4]))
    if ECO.search(bio): s += 2; why.append("names an ecosystem")
    if site: s += 1; why.append("has a website")
    if PERSONAL.search(bio): s -= 3; why.append("looks personal")
    if not bio.strip() or len(bio.strip()) < 8: s -= 1
    return s, why


def _age_words(d):
    if d is None: return "unknown age"
    d = int(d)
    return "created today" if d < 1 else f"{d} day{'s' if d != 1 else ''} old"


def card(u, accounts, strong, sc):
    h = u.get("userName") or u.get("screen_name") or "?"
    bio = (u.get("description") or "").strip().replace("\n", " ")
    L = [("🔥 <b>Strong signal: new account following several big names</b>" if strong else "👀 <b>Possible new project</b>"),
         f"<b>{gate.esc(u.get('name') or h)}</b> (@{gate.esc(h)}) just followed "
         + ", ".join("@" + gate.esc(a) for a in accounts) + ".",
         f"Account is {_age_words(age_days(u))}, has {(u.get('followers_count') or 0):,} followers and {(u.get('statuses_count') or 0):,} posts.",
         f"Bio: {gate.esc(bio[:280]) or '(empty)'}"]
    if u.get("url"): L.append(f"Site: {gate.esc(u['url'])}")
    L += [f"Score {sc}.", "", "<i>Netro Signal by Netrovert · early heads-up, not advice. Check before you trust anything new.</i>"]
    return gate.Html("\n".join(L)), [("Open on X", f"https://x.com/{h}")]


def cycle(send=None, owner=None, accounts=None, log=print):
    c = cfg(); accounts = accounts or c["accounts"]
    with LOCK:
        st = state()
        if st.get("month") != month(): st.update(month=month(), credits=0, calls=0)
    now = time.time(); stats = {"accounts": 0, "seeded": 0, "new": 0, "flagged": 0, "errors": 0, "credits": 0}
    new_by_user = {}  # uid -> (user, [watched accounts])
    for i, a in enumerate(accounts):
        if usd(st["credits"] + call_credits(c["page_size"])) > c["cap_usd"]:
            log(f"follows: monthly cap ${c['cap_usd']} reached, skipping remaining calls"); stats["capped"] = True; break
        if i: time.sleep(c["call_gap_s"])
        fl, err = fetch(a, c["page_size"])
        if fl is None:
            stats["errors"] += 1; log(f"follows: @{a} error {err}")
            if err == "no key": break
            continue
        cr = call_credits(len(fl)); st["credits"] += cr; st["calls"] += 1; stats["credits"] += cr; stats["accounts"] += 1
        key = a.lower(); seen = st["seen"].get(key)
        ids = [str(u.get("id")) for u in fl if u.get("id")]
        if seen is None: stats["seeded"] += 1
        else:
            ss = set(seen)
            for u in fl:
                uid = str(u.get("id"))
                if uid and uid not in ss:
                    stats["new"] += 1; new_by_user.setdefault(uid, [u, []])[1].append(a)
        st["seen"][key] = (ids + [x for x in (seen or []) if x not in ids])[:400]
        with LOCK: save_state(st)  # persist after every call so a crash never double-counts credits
    # 24h cross-account memory and flagging
    rec = {k: [e for e in v if now - e[1] < 86400] for k, v in st.get("recent", {}).items()}
    rec = {k: v for k, v in rec.items() if v}
    for uid, (u, accs) in new_by_user.items():
        sc, why = score(u, c)
        if sc is None: continue
        r = rec.setdefault(uid, [])
        for a in accs:
            if a not in [e[0] for e in r]: r.append([a, now])
        allaccs = [e[0] for e in r]
        strong = len(allaccs) >= c["strong_min_accounts"]
        if sc < c["min_score"] and not strong: continue
        stats["flagged"] += 1
        h = u.get("userName") or u.get("screen_name")
        st["flags"] = ([{"t": now, "handle": h, "score": sc, "strong": strong, "accounts": allaccs,
                         "followers": u.get("followers_count"), "age_d": round(age_days(u) or 0)}] + st.get("flags", []))[:50]
        if send:
            txt, btn = card(u, allaccs, strong, sc)
            fanout(send, owner, txt, btn, log)
    st["recent"] = rec; st["last_run"] = now; st["last_stats"] = stats
    with LOCK: save_state(st)
    return stats


# ---------------- subscribers + fan-out (no API calls per user; one shared card per flag) ----------------
SUBS_P = os.path.join(HERE, "follows_subs.json"); SUB_LOCK = threading.Lock()
import queue, collections
Q = queue.Queue(maxsize=20000); SENT = collections.defaultdict(collections.deque); PER_HOUR = 6; PER_SEC = 25
_sender = [None]


def subs(): return gate.load(SUBS_P, {})


def set_sub(chat, on):
    with SUB_LOCK:
        d = subs(); k = str(chat)
        if on: d[k] = {"on": True, "since": time.time()}
        else: d.pop(k, None)
        gate.atomic_dump(d, SUBS_P)


def is_on(chat, owner=False): return owner or str(chat) in subs()


def _send_loop(send, log):
    while True:
        chat, txt, btn = Q.get()
        try:
            dq = SENT[chat]; now = time.time()
            while dq and now - dq[0] > 3600: dq.popleft()
            if len(dq) >= PER_HOUR: continue
            dq.append(now); send(chat, txt, btn, None)
        except Exception: log("follows: send error")
        finally: time.sleep(1.0 / PER_SEC)


def fanout(send, owner, txt, btn, log=print):
    if _sender[0] is None or not _sender[0].is_alive():
        _sender[0] = threading.Thread(target=_send_loop, args=(send, log), daemon=True, name="follows-send"); _sender[0].start()
    chats = ([owner] if owner else []) + [int(k) if k.lstrip("-").isdigit() else k for k in subs() if str(k) != str(owner)]
    for ch in chats:
        try: Q.put_nowait((ch, txt, btn))
        except queue.Full: log("follows: send queue full"); break
    return len(chats)


def loop(send, log):
    time.sleep(200 + random.uniform(0, 20))  # staggered after launches (20s) and orders (110s)
    while True:
        t0 = time.time(); c = cfg()
        try:
            st = cycle(send, gate.cfg().get("owner_chat_id"), log=log)
            s = state()
            log("follows: " + ", ".join(f"{k}={v}" for k, v in st.items())
                + f", run_usd=${usd(st['credits']):.4f}, month_usd=${usd(s['credits']):.3f}")
        except Exception:
            log("follows error: " + traceback.format_exc().strip().splitlines()[-1])
        time.sleep(max(300, c["every_s"] - (time.time() - t0)) + random.uniform(0, 30))


def start(send, log):
    if not os.environ.get("TWITTERAPI_IO_KEY"): log("follows: TWITTERAPI_IO_KEY not set, follow alerts off"); return None
    th = threading.Thread(target=loop, args=(send, log), daemon=True, name="follows"); th.start(); return th


def command(args, chat=None, owner=True):
    c = cfg(); args = list(args or [])
    if args and args[0].lower() in ("on", "off"):
        if owner: return "You always get follow alerts as the owner."
        set_sub(chat, args[0].lower() == "on")
        return ("✅ Follow alerts on. I'll message you when a brand-new project account follows big crypto accounts. /follows off to stop."
                if args[0].lower() == "on" else "🔕 Follow alerts off.")
    if not owner:
        if args and args[0].lower() in ("add", "remove", "rm"): return "🔒 Only the owner can change which accounts are watched."
        return public_status(chat)
    if args and args[0].lower() in ("add", "remove", "rm") and len(args) > 1:
        h = args[1].lstrip("@").strip()
        if not re.fullmatch(r"\w{1,15}", h): return "That doesn't look like an X handle."
        low = [a.lower() for a in c["accounts"]]
        if args[0].lower() == "add":
            if h.lower() in low: return f"Already watching @{h}."
            c["accounts"].append(h); save_cfg(c)
            return f"Now watching @{h}. The first run only learns its current followers, alerts start after that."
        if h.lower() not in low: return f"I wasn't watching @{h}."
        c["accounts"] = [a for a in c["accounts"] if a.lower() != h.lower()]; save_cfg(c)
        return f"Stopped watching @{h}."
    s = state(); cr = s["credits"] if s.get("month") == month() else 0
    per_run = len(c["accounts"]) * call_credits(c["page_size"]); runs = 86400 * 30 / c["every_s"]
    L = ["<b>Follow alerts</b>",
         f"Watching {len(c['accounts'])} accounts: " + ", ".join("@" + gate.esc(a) for a in c["accounts"]),
         f"Every {c['every_s'] // 60} min, newest {c['page_size']} followers each.",
         f"Last run: {time.strftime('%Y-%m-%d %H:%M', time.localtime(s['last_run'])) if s.get('last_run') else 'not yet'}"
         + (f" ({s['last_stats'].get('new', 0)} new, {s['last_stats'].get('flagged', 0)} flagged)" if s.get("last_stats") else ""),
         f"Spent this month: ${usd(cr):.3f} of ${c['cap_usd']:.0f} cap ({s.get('calls', 0)} calls). About ${usd(per_run):.4f} per run, ~${usd(per_run) * runs:.2f}/month.",
         "", "<b>Recent flags</b>"]
    fl = s.get("flags", [])[:8]
    L += [f"{'🔥' if f['strong'] else '•'} @{gate.esc(f['handle'])}: {f['age_d']}d old, {f['followers']} followers, followed "
          + ", ".join("@" + gate.esc(a) for a in f["accounts"]) for f in fl] or ["None yet."]
    L += ["", "/follows add @handle · /follows remove @handle"]
    return gate.Html("\n".join(L))


def public_status(chat):
    c = cfg(); s = state(); on = is_on(chat)
    L = ["<b>Follow alerts</b>", f"You're {'subscribed ✅' if on else 'not subscribed'}. " + ("/follows off to stop." if on else "/follows on to get alerts."),
         "I check who's newly following big crypto accounts (" + ", ".join("@" + gate.esc(a) for a in c["accounts"][:8]) + " and more) "
         f"every {c['every_s'] // 60} min, and flag brand-new project accounts.",
         f"Last check: {time.strftime('%Y-%m-%d %H:%M', time.localtime(s['last_run'])) if s.get('last_run') else 'not yet'}", "", "<b>Recent flags</b>"]
    L += [f"{'🔥' if f['strong'] else '•'} @{gate.esc(f['handle'])}: {f['age_d']}d old, {f['followers']} followers, followed "
          + ", ".join("@" + gate.esc(a) for a in f["accounts"]) for f in s.get("flags", [])[:8]] or ["None yet."]
    L += ["", "<i>Netro Signal by Netrovert · early heads-up, not advice.</i>"]
    return gate.Html("\n".join(L))
