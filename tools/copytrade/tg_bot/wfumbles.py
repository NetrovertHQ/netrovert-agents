"""Real-wallet fumbles: read-only public data. Solana swaps via Helius (credit-capped), peaks via GeckoTerminal candles."""
import os, re, sys, threading, time, json
from collections import defaultdict, deque
import gate, cache, practice

sys.path.insert(0, os.path.join(gate.ROOT, "wallet_tracker"))
import wallet_tracker as WT

SOL_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
RESULTS = cache.TTL(1800, miss_ttl=0)
USAGE = os.path.join(gate.HERE, "wallet_scan_usage.json"); ULOCK = threading.Lock()
SCANS = defaultdict(deque)


def c(k, d): return gate.cfg().get(k, d)
def short(a): return f"{a[:4]}…{a[-4:]}"
def is_addr(s): return bool(SOL_RE.match(s or ""))


def _day(): return time.strftime("%Y-%m-%d", time.gmtime())


def credits_today():
    u = gate.load(USAGE, {}); return u.get(_day(), 0)


def _add_credits(n):
    with ULOCK:
        u = gate.load(USAGE, {}); d = _day(); u = {k: v for k, v in u.items() if k >= time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))}
        u[d] = u.get(d, 0) + n; gate.atomic_dump(u, USAGE); return u[d]


def user_limited(chat, owner=False):
    if owner: return False
    q = SCANS[chat]; t = time.time()
    while q and t - q[0] > 3600: q.popleft()
    if len(q) >= c("wallet_scan_per_hour", 5): return True
    q.append(t); return False


def _swaps(addr):
    since = int(time.time()) - c("wallet_scan_days", 30) * 86400; maxp = c("wallet_scan_max_pages", 3)
    swaps, tok, c0 = [], None, WT.HELIUS_CREDITS["credits"]
    try:
        for _ in range(maxp):
            res = WT.helius_page(addr, {"blockTime": {"gte": since}}, "desc", 100, tok)
            for t in res["data"]: swaps += WT.sol_parse_tx(t, addr, t["transaction"]["signatures"][0])
            tok = res.get("paginationToken")
            if not tok: break
    finally:
        used = WT.HELIUS_CREDITS["credits"] - c0; tot = _add_credits(used)
        print(time.strftime("%Y-%m-%d %H:%M:%S"), f"wallet fumbles: helius ~{used} credits for {addr}, today ~{tot}", flush=True)
    return swaps


def _scan(addr):
    sells = [s for s in _swaps(addr) if s["side"] == "SELL" and s.get("amount") and s.get("time")]
    for s in sells: s["usd"] = WT.trade_usd(s)
    sells = [s for s in sells if s["usd"]]
    toks = []
    for s in sorted(sells, key=lambda s: -s["time"]):
        if s["token"] not in toks: toks.append(s["token"])
    toks = set(toks[:c("wallet_scan_max_tokens", 20)])
    out = []; t0 = time.time(); skipped = 0
    for s in sells:
        if s["token"] not in toks: continue
        if time.time() - t0 > c("wallet_scan_max_secs", 120): skipped += 1; continue
        pk, src, mk = practice.peak_after(s["token"], "solana", s["time"], True)
        px = s["usd"] / s["amount"]
        if src != "peak" or not practice.fumble_ok(px, pk, mk): continue
        q = practice.price(s["token"], "solana")
        out.append({"symbol": (q[1] if q else s["token"][:6]), "sold": px, "peak": pk, "missed": s["amount"] * (pk - px), "x": pk / px, "src": src})
    out.sort(key=lambda f: -f["missed"])
    return {"addr": addr, "total": sum(f["missed"] for f in out), "count": len(out), "checked": len(sells) - skipped, "top": out[:3]}


def scan(chat, addr, owner=False):
    """(result dict, error text)."""
    if not is_addr(addr): return None, "That doesn't look like a Solana wallet address. Send it like /fumbles <address>."
    if not os.environ.get("HELIUS_API_KEY"): return None, "Wallet scans are switched off right now. Try again later."
    hit = RESULTS.d.get(addr)
    if hit and hit[0] > time.time(): return hit[1], None
    if user_limited(chat, owner): return None, f"You've hit {c('wallet_scan_per_hour', 5)} wallet scans this hour. Give it a bit and try again."
    if credits_today() >= c("wallet_scan_daily_credits", 1500): return None, "Wallet scans are maxed out for today. Try again tomorrow!"
    try: return RESULTS.get(addr, lambda: _scan(addr)), None
    except Exception as e:
        return None, "😕 I couldn't read that wallet right now. Try again in a few minutes."
