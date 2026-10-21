"""Shared in-process TTL cache with single-flight: if 20 users ask for the same token at once, the fetch runs once
and everyone gets that result. Thread-safe. Used for DexScreener prices (~45s) and safety checks (~10 min)."""
import threading, time

_LOCK = threading.Lock()


class TTL:
    def __init__(self, ttl, miss_ttl=None, maxsize=5000):
        self.ttl, self.miss_ttl, self.max = ttl, miss_ttl if miss_ttl is not None else min(ttl, 10), maxsize
        self.d = {}; self.inflight = {}; self.hits = self.misses = 0

    def get(self, key, fn, ok=lambda v: v is not None):
        now = time.time()
        with _LOCK:
            e = self.d.get(key)
            if e and e[0] > now: self.hits += 1; return e[1]
            ev = self.inflight.get(key)
            if ev is None: ev = self.inflight[key] = threading.Event(); owner = True
            else: owner = False
        if not owner:
            ev.wait(180)
            with _LOCK:
                e = self.d.get(key)
                if e: self.hits += 1; return e[1]
            return fn()  # the first fetch failed hard; try ourselves
        try:
            v = fn(); self.misses += 1
            with _LOCK:
                if len(self.d) >= self.max:
                    for k in sorted(self.d, key=lambda k: self.d[k][0])[: self.max // 10]: self.d.pop(k, None)
                self.d[key] = (time.time() + (self.ttl if ok(v) else self.miss_ttl), v)
            return v
        finally:
            with _LOCK: self.inflight.pop(key, None)
            ev.set()


PAIRS = TTL(45, miss_ttl=10)       # DexScreener pairs per token
CHECKS = TTL(600, miss_ttl=0)      # token_check results per (token, chain, narrative); errors aren't cached


# ---- Per-host concurrency limit + 429 backoff for every requests call made in this process ----
# Launch scan, order checker, price lookups and user commands share these, so bursts can't pile onto one API.
# (token_check runs as a subprocess with its own retry/backoff; gate.TC_SLOTS caps how many run at once.)
import requests, urllib.parse
HOST_LIMITS = {"api.dexscreener.com": 4, "api.geckoterminal.com": 2, "api.rugcheck.xyz": 2, "api.etherscan.io": 2,
               "api.gopluslabs.io": 3, "api.telegram.org": 0}  # 0 = no limit (long polling + sends)
_SEMS = {}; _orig_request = requests.Session.request


def _sem(host):
    n = HOST_LIMITS.get(host, 6) if "helius" not in host else 2
    if not n: return None
    with _LOCK:
        if host not in _SEMS: _SEMS[host] = threading.BoundedSemaphore(n)
        return _SEMS[host]


def _limited_request(self, method, url, *a, **kw):
    kw.setdefault("timeout", 20)  # nothing in this process may block forever on the network
    sem = _sem(urllib.parse.urlsplit(url).hostname or "")
    if sem is None: return _orig_request(self, method, url, *a, **kw)
    for i in range(3):
        if not sem.acquire(timeout=60): raise requests.Timeout("host busy")
        try: r = _orig_request(self, method, url, *a, **kw)
        finally: sem.release()
        if r.status_code != 429 or i == 2: return r
        try: wait = min(float(r.headers.get("Retry-After") or 0), 10)
        except ValueError: wait = 0
        time.sleep(wait or 1.5 * (i + 1))
    return r


if not getattr(requests.Session.request, "_netro", False):
    _limited_request._netro = True; requests.Session.request = _limited_request
