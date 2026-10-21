"""Etherscan v2 multichain API (free tier) for verified source / ABI / contract name / creator.
Key: env ETHERSCAN_API_KEY only (never logged). Missing key or unsupported chain -> None, callers fall back to Sourcify/explorers.
Free tier (checked 2026-10-20): getsourcecode works on 1, 8453, 42161, 56, 137, 999; getcontractcreation on 1, 42161, 137, 999
(Base/BNB need a paid plan); holder lists are Pro-only; Ink (57073) isn't on v2 at all.
Rate limit ~5/s: a cross-process file lock spaces calls >= 0.22s apart. Results are cached on disk (verified 24h, unverified 1h)."""
import fcntl, json, os, time
import requests

API = "https://api.etherscan.io/v2/api"
CHAIN_IDS = {"ethereum": 1, "base": 8453, "arbitrum": 42161, "bsc": 56, "polygon": 137, "hyperevm": 999}
CREATION_FREE = {1, 42161, 137, 999}
HERE = os.path.dirname(os.path.abspath(__file__)); CDIR = os.path.join(HERE, "cache", "etherscan"); os.makedirs(CDIR, exist_ok=True)
LOCKF = os.path.join(CDIR, ".ratelimit")


def key(): return os.environ.get("ETHERSCAN_API_KEY", "").strip() or None


def _wait_turn(gap=0.22):
    with open(LOCKF, "a+") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.seek(0); s = f.read().strip(); last = float(s) if s else 0
        d = gap - (time.time() - last)
        if d > 0: time.sleep(d)
        f.seek(0); f.truncate(); f.write(str(time.time())); fcntl.flock(f, fcntl.LOCK_UN)


def _call(cid, params, tries=3):
    k = key()
    if not k: return None
    for i in range(tries):
        _wait_turn()
        try: j = requests.get(API, params=dict(chainid=cid, apikey=k, **params), timeout=15).json()
        except (requests.RequestException, ValueError): time.sleep(1); continue
        r = j.get("result")
        if j.get("status") == "1": return r
        if isinstance(r, str) and "rate limit" in r.lower(): time.sleep(1 + i); continue
        return None  # not supported on free tier / not found
    return None


def _cached(name, ttl_fn, fn):
    p = os.path.join(CDIR, name + ".json")
    try:
        d = json.load(open(p))
        if time.time() < d["exp"]: return d["v"]
    except (OSError, ValueError, KeyError): pass
    v = fn()
    if v is not None:
        try: json.dump({"exp": time.time() + ttl_fn(v), "v": v}, open(p, "w"))
        except OSError: pass
    return v


def source(chain, addr):
    """{'verified', 'name', 'abi', 'proxy', 'impl', 'compiler'} or None if we can't ask."""
    cid = CHAIN_IDS.get(chain)
    if not cid or not key(): return None
    def fetch():
        r = _call(cid, {"module": "contract", "action": "getsourcecode", "address": addr})
        if not r or not isinstance(r, list): return None
        x = r[0]; verified = bool(x.get("SourceCode")) and x.get("ABI", "").startswith("[")
        abi = None
        if verified:
            try: abi = json.loads(x["ABI"])
            except ValueError: abi = None
        return {"verified": verified, "name": x.get("ContractName") or None, "abi": abi, "proxy": x.get("Proxy") == "1",
                "impl": (x.get("Implementation") or "").lower() or None, "compiler": x.get("CompilerVersion") or None}
    return _cached(f"src_{cid}_{addr.lower()}", lambda v: 86400 if v.get("verified") else 3600, fetch)


def creator(chain, addr):
    cid = CHAIN_IDS.get(chain)
    if cid not in CREATION_FREE or not key(): return None
    def fetch():
        r = _call(cid, {"module": "contract", "action": "getcontractcreation", "contractaddresses": addr})
        return {"creator": r[0].get("contractCreator", "").lower(), "tx": r[0].get("txHash")} if r and isinstance(r, list) else None
    return _cached(f"cre_{cid}_{addr.lower()}", lambda v: 30 * 86400, fetch)
