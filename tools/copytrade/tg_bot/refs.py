"""Referrals: invite links, points balance (spendable later). Data: referrals.json + seen_users.json (atomic writes)."""
import glob, hashlib, hmac, os, secrets, threading, time
from urllib.parse import quote
import gate

REFS = os.path.join(gate.HERE, "referrals.json"); SEEN = os.path.join(gate.HERE, "seen_users.json")
LOCK = threading.RLock(); SEND = None  # bot sets SEND = tg.send
BOT = "netrosignal_bot"
_seen = None


def _cfg(k, d): return gate.cfg().get(k, d)


def _salt():
    c = gate.cfg()
    if not c.get("ref_salt"): c["ref_salt"] = secrets.token_hex(8); gate.save_cfg(c)
    return c["ref_salt"]


def code(cid):
    h = hmac.new(_salt().encode(), str(cid).encode(), hashlib.sha256).digest()
    n = int.from_bytes(h[:6], "big"); a = "23456789abcdefghjkmnpqrstuvwxyz"; s = ""
    for _ in range(7): n, r = divmod(n, len(a)); s += a[r]
    return s


def link(cid): return f"https://t.me/{BOT}?start=ref_{code(cid)}"
def _load(): return gate.load(REFS, {"users": {}, "codes": {}, "referred": {}})
def _save(d): gate.atomic_dump(d, REFS, indent=1)


def _seed():
    ids = set()
    for f in glob.glob(os.path.join(gate.HERE, "practice", "users", "*.json")): ids.add(os.path.basename(f)[:-5])
    for f in ("launch_subs.json", "follows_subs.json", "state.json"):
        v = gate.load(os.path.join(gate.HERE, f), {})
        if f != "state.json" and isinstance(v, dict): ids |= {str(k) for k in v}
    o = gate.cfg().get("owner_chat_id")
    if o: ids.add(str(o))
    return ids


def touch(cid):
    """Mark a chat as seen. True if the bot has never seen it before."""
    global _seen
    with LOCK:
        if _seen is None:
            s = gate.load(SEEN, None)
            _seen = set(s) if s is not None else _seed()
            if s is None: gate.atomic_dump(sorted(_seen), SEEN)
        k = str(cid)
        if k in _seen: return False
        _seen.add(k); gate.atomic_dump(sorted(_seen), SEEN); return True


def _user(d, cid, name=None):
    u = d["users"].setdefault(str(cid), {"code": code(cid), "points": 0, "earned": 0, "invited": 0, "name": name or ""})
    d["codes"][u["code"]] = str(cid)
    if name: u["name"] = name
    return u


def attach(new_cid, payload, name):
    """/start ref_<code> from a brand-new chat: remember who invited them (points come later)."""
    c = payload[4:] if payload.startswith("ref_") else ""
    with LOCK:
        d = _load(); ref = d["codes"].get(c)
        if not ref or ref == str(new_cid) or str(new_cid) in d["referred"]: return False
        d["referred"][str(new_cid)] = {"by": ref, "name": (name or "someone")[:32], "t": int(time.time()), "joined": False, "traded": False}
        _save(d); return True


def _award(new_cid, step):
    pts = _cfg("ref_points_signup", 10) if step == "joined" else _cfg("ref_points_first_trade", 1)
    with LOCK:
        d = _load(); r = d["referred"].get(str(new_cid))
        if not r or r[step] or (step == "traded" and not r["joined"]): return
        r[step] = True; u = _user(d, r["by"])
        u["points"] += pts; u["earned"] += pts
        if step == "joined": u["invited"] += 1
        _save(d); ref, nm, bal = r["by"], r["name"], u["points"]
    gate_log(f"referral: {step} +{pts} pts to a referrer")
    msg = (f"🎉 {nm} just joined Netro Signal through your link. +{pts} points, you've got {bal} now." if step == "joined"
           else f"📈 {nm} made their first practice trade. +{pts} point, you're at {bal}.")
    if SEND:
        try: SEND(int(ref), msg)
        except Exception: pass


def joined(cid): _award(cid, "joined")
def traded(cid): _award(cid, "traded")
def gate_log(s): print(time.strftime("%Y-%m-%d %H:%M:%S"), s, flush=True)


def invite(cid, name=""):
    with LOCK:
        d = _load(); u = _user(d, cid, name); _save(d)
    l = link(cid)
    pitch = "I'm practicing crypto copy-trading on Netro Signal with $1,000 of fake money. Real prices, zero risk. Try it:"
    share = f"https://t.me/share/url?url={quote(l)}&text={quote(pitch)}"
    txt = (f"👥 Invite friends to Netro Signal\n\nYour link:\n{l}\n\n"
           f"Joined through you: {u['invited']}\nPoints: {u['points']}\n\n"
           f"You get {_cfg('ref_points_signup', 10)} points when someone new opens practice mode from your link, "
           f"and {_cfg('ref_points_first_trade', 1)} more when they make their first trade. Points will be good for something soon 👀")
    return txt, [("📤 Share your link", share)]


def leaderboard():
    d = _load(); top = sorted((u for u in d["users"].values() if u["earned"] > 0), key=lambda u: -u["earned"])[:10]
    if not top: return "🏆 No referrals yet. Be the first: /invite"
    return "🏆 Top inviters\n\n" + "\n".join(f"{i}. {u.get('name') or 'anon'}: {u['earned']} pts ({u['invited']} joined)" for i, u in enumerate(top, 1)) + "\n\nGet your link with /invite"


def stats():
    d = _load(); r = d["referred"].values()
    return f"Referrals: {sum(x['joined'] for x in r)} joined ({len(d['referred'])} clicked a link), {sum(x['traded'] for x in r)} traded"
