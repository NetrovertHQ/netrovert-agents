#!/usr/bin/env python3
"""gate.py: trade gate. Plain-words verdict BUY / CAREFUL / SKIP for one token + source wallet.
Never holds keys, never signs, never trades. It only reads the other tools' output.

python3 gate.py <token> [--chain solana] [--wallet "E/acc guy"] [--scan-file ../paper_trade/last_scan.json] [--json]
"""
import argparse, html, json, os, subprocess, sys, threading, time
TC_SLOTS = threading.BoundedSemaphore(5)  # at most 5 token_check subprocesses at once (heavy lane 6 + launch pool 3 share these)
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
CFG_PATH = os.path.join(HERE, "config.json")
TC = os.path.join(ROOT, "token_check", "token_check.py")
WALLETS = os.path.join(ROOT, "wallet_tracker", "wallets.json")
TRADES = os.path.join(ROOT, "paper_trade", "trades.json")
SCAN = os.path.join(ROOT, "paper_trade", "last_scan.json")
LOSSES = os.path.join(HERE, "losses.json")
LAGOS = timezone(timedelta(hours=1))
EVM_DEX_SWAP = {  # dexId from DexScreener -> swap URL template (just links, user confirms in own wallet)
    "uniswap": "https://app.uniswap.org/swap?chain={chain}&outputCurrency={token}",
    "pancakeswap": "https://pancakeswap.finance/swap?chain={chain}&outputCurrency={token}",
    "aerodrome": "https://aerodrome.finance/swap?to={token}",
    "sushiswap": "https://www.sushi.com/swap?token1={token}",
    "hyperswap": "https://app.hyperswap.exchange/trade?inputCurrency=HYPE&outputCurrency={token}",  # HyperEVM main DEX
}

EVM_DEX_SWAP["velodrome"] = "https://velodrome.finance/swap?to={token}"
CHAIN_SWAP = {"ethereum": "uniswap", "base": "uniswap", "arbitrum": "uniswap", "polygon": "uniswap", "bsc": "pancakeswap",
              "hyperevm": "hyperswap", "ink": "velodrome"}  # fallback swap link per chain


def atomic_dump(o, p, **kw):
    """Write JSON via a per-thread temp file + os.replace, so readers never see half a file."""
    tmp = f"{p}.{os.getpid()}.{threading.get_ident()}.tmp"
    with open(tmp, "w") as fh: json.dump(o, fh, **kw)
    os.replace(tmp, p)


def load(p, d):
    try: return json.load(open(p))
    except Exception: return d


def cfg(): return load(CFG_PATH, {})
def save_cfg(c): atomic_dump(c, CFG_PATH, indent=2)
def is_test(label): return (label or "").lower().startswith("test")


def find_wallet(name_or_addr):
    if not name_or_addr: return None
    k = name_or_addr.lower()
    for w in load(WALLETS, []):
        if w["label"].lower() == k or w["address"].lower() == k: return w
    return None


# ---- public labels: non-owners never see the owner's nicknames ----
PUB_KIND = {"robinhood": "whale"}  # chain -> word; everything else is "trader"
SCORES = os.path.join(ROOT, "smart_money", "results", "scores.json")


def _hold_words(s):
    if s is None: return None
    if s < 600: return f"fast flipper, holds about {max(1, round(s / 60))} min"
    if s < 3600 * 3: return f"short trades, holds about {round(s / 60)} min"
    if s < 86400 * 2: return f"swing trader, holds about {round(s / 3600)}h"
    return f"patient holder, holds about {round(s / 86400)} days"


def public_desc(w):
    """Short plain description from data we already have (smart_money score + paper-trade record). No made-up stats."""
    parts = []
    sc = next((v for v in load(SCORES, {}).values() if (v.get("address") or "").lower() == w["address"].lower()), None)
    if sc:
        h = _hold_words(sc.get("median_hold_s"))
        if h: parts.append(h)
        if sc.get("trades_per_day"): parts.append(f"about {sc['trades_per_day']:.0f} trades a day")
    r = wallet_record(w["label"])
    if r["trades"]: parts.append(f"our fake copies: {r['wins']} of {r['trades']} won, {'+' if r['pnl_usd'] >= 0 else '-'}${abs(r['pnl_usd']):,.0f}")
    return ", ".join(parts) or "new, not much data yet"


def public_wallets(save=True):
    """Non-test watched wallets with public labels, in a stable order. Labels live in config public_labels[address]."""
    c = cfg(); pl = c.setdefault("public_labels", {}); changed = False
    ws = [w for w in load(WALLETS, []) if not is_test(w["label"])]
    for w in ws:
        e = pl.get(w["address"])
        if not e:
            base = f"{chain_name(w['chain']).replace(' Chain', '')} {PUB_KIND.get(w['chain'], 'trader')}"
            n = 1 + sum(1 for x in pl.values() if x.get("base") == base)
            e = pl[w["address"]] = {"label": f"{base} #{n}", "base": base, "desc": public_desc(w), "auto_desc": True}; changed = True
        elif e.get("auto_desc", True):
            d = public_desc(w)
            if d != e.get("desc"): e["desc"] = d; changed = True
    if changed and save: save_cfg(c)
    out = []
    for i, w in enumerate(sorted(ws, key=lambda w: w["added"]), 1):
        e = pl[w["address"]]; out.append({"n": i, "address": w["address"], "chain": w["chain"], "label": e["label"], "desc": e["desc"]})
    return out


def public_name(addr):
    """Public label for an address (never the nickname). Falls back to a short address."""
    if not addr: return "that wallet"
    e = cfg().get("public_labels", {}).get(addr) or next((v for k, v in cfg().get("public_labels", {}).items() if k.lower() == addr.lower()), None)
    return e["label"] if e else f"wallet {short_addr(addr)}"


def token_check(token, chain=None, narrative=True):
    """Cached ~10 min per token and shared by all users (cache.CHECKS); errors aren't cached."""
    import cache
    chain = norm_chain(chain)
    return cache.CHECKS.get((token.lower(), chain, bool(narrative)), lambda: _token_check(token, chain, narrative),
                            ok=lambda d: d.get("exit_code") in (0, 1, 2) and bool(d.get("verdict")))


def _token_check(token, chain=None, narrative=True):
    cmd = [sys.executable, TC, token, "--json"] + ([] if narrative else ["--no-narrative"]) + (["--chain", chain] if chain else [])
    try:
        with TC_SLOTS: r = subprocess.run(cmd, capture_output=True, text=True, timeout=cfg().get("token_check_timeout_s", 120))
        d = json.loads(r.stdout) if r.stdout.strip() else {}
        d["exit_code"] = r.returncode
        return d
    except Exception as e:
        return {"exit_code": 3, "error": str(e)[:200]}


def wallet_record(label):
    """Paper-trade record for one wallet (gate-ON trades: KILL tokens left out, same as the report headline)."""
    c = cfg(); ts = [t for t in load(TRADES, []) if t.get("source") == f"wallet:{label}" and not t.get("gated_out")]
    cl = [t for t in ts if t.get("status") == "closed"]
    n = len(cl); wins = sum(t.get("pnl_usd", 0) > 0 for t in cl); pnl = sum(t.get("pnl_usd", 0) for t in cl)
    rec = {"label": label, "trades": n, "open": len(ts) - n, "wins": wins, "win_rate": wins / n if n else 0, "pnl_usd": round(pnl, 2)}
    if n < c.get("thin_data_trades", 15): rec["status"] = "thin"
    elif pnl < 0 or rec["win_rate"] < c.get("failing_win_rate", 0.33): rec["status"] = "failing"
    else: rec["status"] = "ok"
    rec["words"] = record_words(rec)
    return rec


def record_words(r):
    if not r["trades"]: return "no paper trades yet"
    s = f"{r['wins']} wins out of {r['trades']} paper trades ({r['win_rate']*100:.0f}%), "
    s += f"{'made' if r['pnl_usd'] >= 0 else 'lost'} ${abs(r['pnl_usd']):,.0f} total on $100 fake bets"
    return s


def instant_dump(token, wallet_addr, scan_file=None):
    """Did this wallet buy and then sell within seconds at a big loss (or with no price at all) in the scan?"""
    c = cfg(); d = load(scan_file or SCAN, {}); sw = [s for s in d.get("swaps", []) if s.get("token", "").lower() == token.lower()
                                                     and (not wallet_addr or s.get("wallet", "").lower() == wallet_addr.lower())]
    buys = [s for s in sw if s["side"] == "BUY"]; sells = [s for s in sw if s["side"] == "SELL"]
    for b in buys:
        for s in sells:
            dt = s["time"] - b["time"]
            if 0 <= dt <= c.get("instant_dump_seconds", 60):
                bu, su = b.get("usd"), s.get("usd")
                if bu and su:
                    loss = (bu - su) / bu * 100
                    if loss >= c.get("instant_dump_loss_pct", 30):
                        return f"The wallet sold {dt}s after buying, at a {loss:.0f}% loss. Classic dump"
                else:
                    return f"The wallet sold {dt}s after buying and we couldn't price the sell. Looks like a dump or honeypot"
    return None


def todays_loss():
    today = datetime.now(LAGOS).strftime("%Y-%m-%d")
    return sum(x["usd"] for x in load(LOSSES, []) if x.get("day") == today)


def log_loss(usd):
    L = load(LOSSES, []); L.append({"day": datetime.now(LAGOS).strftime("%Y-%m-%d"), "usd": float(usd), "ts": int(time.time())})
    atomic_dump(L, LOSSES, indent=1); return todays_loss()


FRIENDLY = {  # failed check -> plain words
    "rugged": "It's already been rugged",
    "mint_authority": "The creator can still print more tokens",
    "freeze_authority": "The creator can freeze your tokens so you can't sell",
    "danger_flags": "Rugcheck flags it as dangerous",
    "risk_score": "Rugcheck rates it as risky",
    "honeypot": "It looks like a honeypot: you may not be able to sell",
    "sell_tax": "There's a big tax when you sell",
    "buy_tax": "There's a tax when you buy",
    "owner_can_mint": "The owner can print more tokens",
    "proxy": "The contract can be changed later",
    "blacklist": "The owner can block wallets from selling",
    "owner_powers": "The owner still has special powers over the token",
    "open_source": "The code isn't public, so nobody can check it",
    "lp_lock": "The sellers' pool isn't locked, so the creator could pull the money out",
    "lp_unlocked_tiny": "The pool is small and unlocked, so it's easy to rug",
    "top10_holders": "A few wallets hold most of the supply",
    "dev_wallet": "The creator still holds a big bag",
    "insiders": "Insider wallets hold a lot",
    "liquidity": "There's very little money in the pool",
    "ticket_share": "Your buy would move the price a lot",
    "pair_age": "It's brand new, launched minutes ago",
    "sells_exist": "Almost nobody is selling, which can mean people can't sell",
    "volume": "Hardly anyone is trading it",
    "fdv_liquidity": "The price looks inflated next to the money in the pool",
    "profile": "No website or socials listed",
}
UNKNOWN_SRC = {"solana": "Rugcheck", "evm": "GoPlus"}


def usd_short(x):
    x = float(x or 0)
    for d, s in ((1e9, "B"), (1e6, "M"), (1e3, "k")):
        if abs(x) >= d: v = x / d; return f"${v:.1f}{s}".replace(".0" + s, s) if v < 100 else f"${v:.0f}{s}"
    return f"${x:,.0f}"


def tc_reasons(tc, limit=2):
    """Plain-words reasons: deal-breakers first, then warnings, then the market line."""
    out = []; m = tc.get("market") or {}; checks = tc.get("checks") or []
    fails = [c for c in checks if c.get("status") == "fail"]
    fails.sort(key=lambda c: (c.get("severity") != "kill",))
    if any(c.get("check") == "lp_unlocked_tiny" for c in fails): fails = [c for c in fails if c.get("check") != "lp_lock"]
    for c in fails:
        t = FRIENDLY.get(c.get("check"))
        if t and t not in out and c.get("check") != "profile": out.append(t)
    unk = [c for c in checks if c.get("status") == "unknown"]
    if unk and len(unk) >= 3: out.append("Some safety data didn't load, so treat this as unchecked")
    elif unk and any(c["check"] in ("owner_powers",) for c in unk): out.append("We couldn't tell whether the owner gave up control")
    out = out[:limit]
    if m.get("liq_usd"): out.append(f"{usd_short(m['liq_usd'])} in the pool · {usd_short(m.get('vol_24h'))} traded today")
    if not fails and not unk: out.insert(0, "Passed every safety check")
    return out


def narr_words(tc):
    n = tc.get("narrative")
    if not n: return None
    g = n.get("grade") or "PENDING"
    if g == "PENDING": return None
    words = {"CONFIRMED": "The story behind it checks out", "UNCONFIRMED": "The story behind it isn't confirmed yet",
             "FALSE": "The story behind it is fake"}.get(g, f"Story: {g.lower()}")
    cat = n.get("catalyst")
    return words + (f": {cat}" if cat else "")


def buttons(token, chain, tc):
    m = tc.get("market") or {}; ds = m.get("url") or f"https://dexscreener.com/{chain}/{token}"
    if chain == "solana":  # Jupiter URLs checked 2026-10-20: /swap, /limit and /recurring (DCA) all load for SOL-<mint>
        jup = f"https://jup.ag/swap/SOL-{token}"
        phantom = f"https://phantom.app/ul/browse/{quote(jup, safe='')}?ref={quote('https://jup.ag', safe='')}"
        return [("Swap on Jupiter", jup), ("Set limit order", f"https://jup.ag/limit/SOL-{token}"),
                ("Buy in pieces (DCA)", f"https://jup.ag/recurring/SOL-{token}"), ("Open in Phantom", phantom), ("DexScreener", ds)]
    b = [("DexScreener", ds)]; dex = (m.get("dex") or "").lower(); tpl = EVM_DEX_SWAP.get(dex)
    if not tpl and chain in CHAIN_SWAP: dex = CHAIN_SWAP[chain]; tpl = EVM_DEX_SWAP[dex]  # top pool on a DEX we have no link for
    if tpl: b.insert(0, (f"Swap on {dex.capitalize()}", tpl.format(chain=chain, token=token)))
    return b


def gate(token, chain=None, wallet=None, scan_file=None, tc=None, narrative=True):
    chain = norm_chain(chain)
    c = cfg(); w = find_wallet(wallet) if isinstance(wallet, str) else wallet
    chain = chain or (w["chain"] if w else None)
    tc = tc or token_check(token, chain, narrative); chain = tc.get("chain") or chain or "solana"
    v = tc.get("verdict"); m = tc.get("market") or {}
    reasons, verdict = [], None
    rec = wallet_record(w["label"]) if w else None
    dump = instant_dump(token, w["address"] if w else None, scan_file)
    if tc.get("exit_code") == 3 or not v:
        verdict = "SKIP"; reasons.append("We couldn't find this token. Check the address and chain")
    elif v == "KILL":
        verdict = "SKIP"; reasons += [r for r in tc_reasons(tc, 2) if "traded today" not in r] or ["It failed a deal-breaker safety check"]
    elif not m.get("liq_usd"):
        verdict = "SKIP"; reasons.append("There's no pool with money in it, so you couldn't sell")
    if dump:
        verdict = "SKIP"; reasons.insert(0, dump)
    if not verdict:
        bad = rec and rec["status"] in ("failing", "thin")
        verdict = "CAREFUL" if (v == "WARN" or bad) else "BUY"
        reasons += tc_reasons(tc, 1 if rec else 2)
    if rec:
        reasons.append({"ok": f"{rec['label']} is doing well on our fake trades ({rec['wins']} of {rec['trades']} won)",
                        "failing": f"{rec['label']} is losing on our fake trades ({rec['wins']} of {rec['trades']} won)",
                        "thin": f"We haven't seen enough of {rec['label']}'s trades to trust them yet"}[rec["status"]])
    cap = {"BUY": c.get("size_cap_buy_usd", 50), "CAREFUL": c.get("size_cap_careful_usd", 25)}.get(verdict, 0)
    lim = c.get("daily_loss_limit_usd"); lost = todays_loss(); warn = None
    if lim and lost >= lim: warn = f"You're down {usd_short(lost)} today, past your {usd_short(lim)} limit. Maybe call it a day."
    elif lim and lost >= 0.7 * lim: warn = f"You're down {usd_short(lost)} today (your limit is {usd_short(lim)})."
    return {"verdict": verdict, "token": token, "chain": chain, "symbol": tc.get("symbol") or m.get("symbol") or "?",
            "contract": ((tc.get("security") or {}).get("contract_name"), (tc.get("security") or {}).get("open_source")),
            "wallet": w["label"] if w else None, "reasons": [r for r in reasons if r][:3], "size_cap_usd": cap, "loss_warning": warn,
            "token_check": {"verdict": v, "score": tc.get("score")}, "narrative": narr_words(tc), "price_usd": m.get("price_usd"), "buttons": buttons(token, chain, tc)}


ICON = {"BUY": "🟢", "CAREFUL": "🟡", "SKIP": "🔴"}
WORD = {"BUY": "Looks good:", "CAREFUL": "Careful with", "SKIP": "Skip"}
CHAIN = {"solana": "Solana", "robinhood": "Robinhood Chain", "ethereum": "Ethereum", "base": "Base", "bsc": "BNB Chain",
         "arbitrum": "Arbitrum", "polygon": "Polygon", "ink": "Ink", "hyperevm": "HyperEVM"}
ALIAS = {"sol": "solana", "solana": "solana", "rh": "robinhood", "hood": "robinhood", "robinhood": "robinhood",
         "eth": "ethereum", "ethereum": "ethereum", "mainnet": "ethereum", "base": "base", "bsc": "bsc", "bnb": "bsc",
         "arb": "arbitrum", "arbitrum": "arbitrum", "poly": "polygon", "matic": "polygon", "polygon": "polygon", "ink": "ink",
         "hyperevm": "hyperevm", "hype": "hyperevm", "hyper": "hyperevm", "hl": "hyperevm", "hyperliquid": "hyperevm"}


def norm_chain(c):
    if not c: return None
    c = c.strip().lower()
    return ALIAS.get(c, c)


def split_args(args):
    """Token + chain from args in any order: '/check SOL <addr>' or '/check <addr> rh'."""
    chain = next((norm_chain(a) for a in args if a.lower() in ALIAS), None)
    rest = [a for a in args if a.lower() not in ALIAS]
    return (rest[0] if rest else None), chain, rest


FOOTER = "<i>Netro Signal by Netrovert · you buy in your own wallet, we never touch your funds</i>"


class Html(str):
    """Text that is already Telegram HTML (everything else gets escaped before sending)."""


def esc(x): return html.escape(str(x), quote=False)
def short_addr(a): return a if len(a) <= 12 else f"{a[:4]}…{a[-4:]}" if not a.startswith("0x") else f"{a[:6]}…{a[-4:]}"
def chain_name(c): return CHAIN.get(c, (c or "?").capitalize())


# Per Jupiter docs (docs.jup.ag, Ultra mode / Risks): Ultra, the default on jup.ag, sends swaps privately (Beam), which
# "significantly reduces" MEV risk but can't remove it. Keep the wording that honest.
MEV_LINE = "🛡 Jupiter's default Ultra mode sends your swap privately, which makes it much harder for front-running bots (not impossible)."


def card_text(g, header=None, footer=True, size_line=True):
    """Telegram HTML card."""
    sym = g["symbol"].lstrip("$")
    L = []
    if header: L += [header, ""]
    L.append(f"{ICON[g['verdict']]} <b>{WORD[g['verdict']]} ${esc(sym)}</b>")
    L.append(f"on {esc(chain_name(g['chain']))} · {esc(short_addr(g['token']))}")
    L.append(f"<code>{esc(g['token'])}</code>")
    L += ["", "<b>Why:</b>"] + [f"• {esc(r)}" for r in g["reasons"]]
    cn, os_ = g.get("contract") or (None, None)
    if cn and os_: L.append(f"• Code is public: verified as {esc(cn)}")
    if g.get("narrative"): L.append(f"• {esc(g['narrative'])}")
    if size_line:
        L.append("")
        L.append(f"<b>If you buy:</b> keep it under ${g['size_cap_usd']}." if g["size_cap_usd"] else "<b>Our call:</b> don't buy this one.")
    if g["loss_warning"]: L.append(f"⚠️ {esc(g['loss_warning'])}")
    if g.get("chain") == "solana" and g.get("verdict") != "SKIP": L.append(esc(MEV_LINE))
    if footer: L += ["", footer if isinstance(footer, str) else FOOTER]
    return Html("\n".join(L))


def strip_html(t): return html.unescape(__import__("re").sub(r"<[^>]+>", "", t))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("token"); ap.add_argument("--chain"); ap.add_argument("--wallet"); ap.add_argument("--scan-file"); ap.add_argument("--json", action="store_true")
    a = ap.parse_args(); g = gate(a.token, a.chain, a.wallet, a.scan_file)
    print(json.dumps(g, indent=2) if a.json else strip_html(card_text(g)) + "\n" + "\n".join(f"[{t}] {u}" for t, u in g["buttons"]))
    sys.exit({"BUY": 0, "CAREFUL": 1, "SKIP": 2}[g["verdict"]])


if __name__ == "__main__": main()
