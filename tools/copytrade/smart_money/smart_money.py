#!/usr/bin/env python3
"""Smart-money finder: discover and score wallets by realized PnL, win rate and copyability."""
import argparse, json, os, statistics as stt, subprocess, sys, time, re
import requests
from datetime import datetime
HERE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(HERE, "config.json")))
WT_DIR = os.path.normpath(os.path.join(HERE, CFG["wallet_tracker_dir"]))
sys.path.insert(0, WT_DIR)
import wallet_tracker as WT  # reuse parsers, Helius client, price helpers
RES = os.path.join(HERE, "results")
def log(*a): print(*a, file=sys.stderr)


# ---------------- data ----------------
def sol_swaps(addr, days, max_pages=None):
    """Wallet's own swaps over `days` via Helius (needs HELIUS_API_KEY); falls back to public RPC (shallow)."""
    since = int(time.time()) - days * 86400; swaps, token, pages, ntx = [], None, 0, 0
    maxp = max_pages or CFG["helius"]["max_pages_score"]; truncated = False
    if os.environ.get("HELIUS_API_KEY"):
        while pages < maxp:
            res = WT.helius_page(addr, {"blockTime": {"gte": since}}, "desc", CFG["helius"]["page_size"], token); pages += 1
            for t in res["data"]:
                ntx += 1; swaps += WT.sol_parse_tx(t, addr, t["transaction"]["signatures"][0])
            token = res.get("paginationToken")
            if not token: break
        else: truncated = True
    else:
        log("HELIUS_API_KEY not set: public RPC, last ~180 txs only")
        swaps, _ = WT.sol_fetch({"address": addr, "label": addr[:6], "chain": "solana"}, {}, 10 ** 6); truncated = True
    for s in swaps: s["usd"] = WT.trade_usd(s)
    return sorted(swaps, key=lambda s: s["time"] or 0), {"pages": pages, "txs_seen": ntx, "truncated": truncated}


def evm_swaps(addr, chain, days):
    w = {"address": addr.lower(), "chain": chain, "label": addr[:6]}
    swaps, _ = WT.evm_fetch(w, {}, 200)
    since = time.time() - days * 86400; swaps = [s for s in swaps if (s["time"] or 0) >= since]
    px = WT.dex_prices(WT.CFG["evm"][chain]["dex"], [s["token"] for s in swaps])
    for s in swaps:
        p = px.get(s["token"]); s["usd"] = s["amount"] * p["price"] if p and p["price"] else None  # current price only
    return swaps, {"truncated": True, "note": "EVM USD = current DexScreener price"}


def pair_info(dex, tokens):
    out = {}
    for i in range(0, len(tokens), 30):
        try: pairs = WT.get_json(f"https://api.dexscreener.com/tokens/v1/{dex}/{','.join(tokens[i:i+30])}")
        except IOError: continue
        for p in pairs or []:
            a = p["baseToken"]["address"]; c = (p.get("pairCreatedAt") or 0) / 1000
            if a not in out or (c and c < out[a]["created"]): out[a] = {"created": c or out.get(a, {}).get("created", 0), "symbol": p["baseToken"]["symbol"]}
    return out


def token_verdict(tok, dex):
    r = WT.run_token_check(tok, dex); return r.get("verdict")


# ---------------- scoring ----------------
def score_wallet(addr, chain="solana", days=None, check=True):
    days = days or CFG["days"]; t0 = time.time(); c0 = WT.HELIUS_CREDITS["credits"]
    swaps, meta = sol_swaps(addr, days) if chain == "solana" else evm_swaps(addr, chain, days)
    dex = "solana" if chain == "solana" else WT.CFG["evm"][chain]["dex"]
    pos = {}
    for s in swaps:
        p = pos.setdefault(s["token"], {"bq": 0, "bu": 0, "sq": 0, "su": 0, "first_buy": None, "first_sell": None, "buys": [], "unpriced": 0})
        if s["usd"] is None: p["unpriced"] += 1
        if s["side"] == "BUY":
            p["bq"] += s["amount"]; p["bu"] += s["usd"] or 0; p["buys"].append(s)
            p["first_buy"] = p["first_buy"] or s["time"]
        else:
            p["sq"] += s["amount"]; p["su"] += s["usd"] or 0
            if p["first_buy"] and not p["first_sell"]: p["first_sell"] = s["time"]
    closed = []
    for tok, p in pos.items():
        if p["bq"] <= 0 or p["sq"] <= 0: continue  # need a buy inside the window and a sell
        frac = min(1.0, p["sq"] / p["bq"]); pnl = p["su"] - p["bu"] * frac
        closed.append({"token": tok, "pnl": pnl, "cost": p["bu"] * frac, "hold_s": (p["first_sell"] - p["first_buy"]) if p["first_sell"] else None})
    buys = [s for s in swaps if s["side"] == "BUY"]
    span_d = max(1 / 24, ((swaps[-1]["time"] - swaps[0]["time"]) / 86400) if len(swaps) > 1 else 1)
    holds = [c["hold_s"] for c in closed if c["hold_s"] is not None]
    sizes = [s["usd"] for s in buys if s["usd"]]
    slots = {}
    for s in buys: slots.setdefault((s["tx"][:0], s["time"]), []).append(s)
    same_sec = sum(len(v) for v in slots.values() if len(v) > 1)
    info = pair_info(dex, list({s["token"] for s in buys})[:90])
    early = [s["time"] - info[s["token"]]["created"] for s in buys if s["token"] in info and info[s["token"]]["created"] and s["time"]]
    pre_pair = sum(1 for e in early if e < -60)
    snipes = sum(1 for e in early if -60 <= e <= CFG["bot"]["sniper_s_after_pair"])
    # token_check on a sample of distinct tokens bought (biggest buys first)
    kill = None; sampled = []
    if check and buys:
        big = sorted({s["token"]: s["usd"] or 0 for s in buys}.items(), key=lambda x: -x[1])[:CFG["token_check_sample"]]
        verdicts = [token_verdict(t, dex) for t, _ in big]; sampled = list(zip([t for t, _ in big], verdicts))
        valid = [v for v in verdicts if v in ("PASS", "WARN", "KILL")]
        kill = round(100 * sum(v == "KILL" for v in valid) / len(valid)) if valid else None
    r = {"address": addr, "chain": chain, "days": days, "scored_at": datetime.now(WT.LAGOS).isoformat(timespec="seconds"),
         "swaps": len(swaps), "buys": len(buys), "tokens_traded": len(pos), "closed_positions": len(closed),
         "realized_pnl_usd": round(sum(c["pnl"] for c in closed), 2),
         "win_rate_pct": round(100 * sum(c["pnl"] > 0 for c in closed) / len(closed), 1) if closed else None,
         "trades_per_day": round(len(swaps) / span_d, 1), "active_span_days": round(span_d, 2),
         "median_hold_s": round(stt.median(holds)) if holds else None, "avg_hold_s": round(stt.mean(holds)) if holds else None,
         "median_buy_usd": round(stt.median(sizes), 2) if sizes else None,
         "buy_size_cv": round(stt.pstdev(sizes) / stt.mean(sizes), 2) if len(sizes) > 2 else None,
         "median_entry_s_after_pair": round(stt.median(early)) if early else None,
         "pct_buys_sniped": round(100 * snipes / len(early)) if early else None, "pre_pair_buys": pre_pair,
         "same_second_buys_pct": round(100 * same_sec / len(buys)) if buys else 0,
         "kill_pct_sampled": kill, "token_check_sample": sampled, "data": meta}
    r["flags"] = flags(r); r["copyability"] = copyability(r); r["rank_score"] = rank_score(r)
    r["helius_credits"] = WT.HELIUS_CREDITS["credits"] - c0; r["secs"] = round(time.time() - t0, 1)
    return r


def flags(r):
    b = CFG["bot"]; f = []
    if r["trades_per_day"] > b["max_trades_per_day"]: f.append(f"bot-like volume ({r['trades_per_day']}/day)")
    if r["median_hold_s"] is not None and r["median_hold_s"] < b["min_median_hold_s"]: f.append(f"scalper/bot hold ({r['median_hold_s']}s median)")
    if (r["pct_buys_sniped"] or 0) >= 30: f.append(f"sniper ({r['pct_buys_sniped']}% of buys within {b['sniper_s_after_pair']}s of pair)")
    if r["same_second_buys_pct"] >= b["same_slot_buys_pct"]: f.append(f"bundled same-second buys ({r['same_second_buys_pct']}%)")
    if r["pre_pair_buys"]: f.append(f"pre-pair entries: {r['pre_pair_buys']} buys before the earliest DexScreener pair (bonding curve or insider; check creator funding)")
    if (r["kill_pct_sampled"] or 0) >= 50: f.append(f"rug-chaser ({r['kill_pct_sampled']}% of sampled buys KILL)")
    if r["closed_positions"] < 5: f.append("small sample (<5 closed positions)")
    if r["data"].get("truncated"): f.append("history truncated by page cap")
    return f


def copyability(r):
    c = CFG["copyability"]; s = 100
    h = r["median_hold_s"]
    if h is None: s -= 30
    elif h < 30: s -= 60
    elif h < c["good_median_hold_s"]: s -= 30 * (1 - h / c["good_median_hold_s"]) + 15
    tpd = r["trades_per_day"]
    if tpd > c["max_good_trades_per_day"]: s -= min(40, (tpd - c["max_good_trades_per_day"]) / 5)
    s -= min(30, (r["pct_buys_sniped"] or 0) * 0.6); s -= min(20, r["same_second_buys_pct"] * 0.4)
    if r["buy_size_cv"] and r["buy_size_cv"] > 1.5: s -= 10
    if r["buys"] and r["pre_pair_buys"] / r["buys"] > 0.2: s -= 15
    return max(0, round(s))


def rank_score(r):
    import math
    pnl = r["realized_pnl_usd"]; wr = r["win_rate_pct"] or 0
    p = math.copysign(math.log10(1 + abs(pnl)), pnl) * 10   # ~40 for $10k
    sample = min(1.0, r["closed_positions"] / 15)
    kill = (r["kill_pct_sampled"] or 0) / 100
    return round((p + wr * 0.4) * sample * (r["copyability"] / 100) * (1 - 0.5 * kill), 1)


def save_result(r):
    path = os.path.join(RES, "scores.json"); db = WT.load(path, {})
    db[f"{r['chain']}:{r['address']}"] = r; WT.save(path, db)


def fmt(r, label=""):
    hold = lambda x: "?" if x is None else (f"{x}s" if x < 120 else f"{x/60:.0f}m" if x < 7200 else f"{x/3600:.1f}h")
    return (f"{label or r['address'][:8]+'…'} [{r['chain']}] PnL ${r['realized_pnl_usd']:,.0f} | win {r['win_rate_pct']}% of {r['closed_positions']} closed | "
            f"{r['swaps']} swaps ({r['trades_per_day']}/day) | median hold {hold(r['median_hold_s'])} | median buy ${r['median_buy_usd']} | "
            f"KILL {r['kill_pct_sampled']}% | entry {hold(r['median_entry_s_after_pair'])} after pair | copyability {r['copyability']} | rank {r['rank_score']}"
            + (f"\n    flags: {'; '.join(r['flags'])}" if r["flags"] else ""))


# ---------------- discovery ----------------
def leaderboard_wallets():
    out = {}
    for name, url, rx in [("kolexplorer", "https://kolexplorer.com/", r'data-address="([1-9A-HJ-NP-Za-km-z]{32,44})"'),
                          ("kolscan", "https://kolscan.io/leaderboard", r'/account/([1-9A-HJ-NP-Za-km-z]{32,44})')]:
        try:
            html = WT.S.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}).text
            for a in dict.fromkeys(re.findall(rx, html)): out.setdefault(a, name)
            log(f"{name}: {sum(1 for v in out.values() if v == name)} wallets")
        except Exception as e: log(f"{name} failed: {e}")
    return out


def runner_tokens(chain, days):
    d = CFG["discover"]; seen = {}
    for ep in ["/token-boosts/top/v1", "/token-boosts/latest/v1", "/token-profiles/latest/v1", "/community-takeovers/latest/v1"]:
        try:
            for t in WT.get_json("https://api.dexscreener.com" + ep) or []:
                if t.get("chainId") == chain: seen[t["tokenAddress"]] = 1
        except IOError: pass
    toks = list(seen); good = []
    for i in range(0, len(toks), 30):
        try: pairs = WT.get_json(f"https://api.dexscreener.com/tokens/v1/{chain}/{','.join(toks[i:i+30])}")
        except IOError: continue
        best = {}
        for p in pairs or []:
            a = p["baseToken"]["address"]
            if a not in best or (p.get("liquidity") or {}).get("usd", 0) > (best[a].get("liquidity") or {}).get("usd", 0): best[a] = p
        for a, p in best.items():
            age_d = (time.time() - (p.get("pairCreatedAt") or 0) / 1000) / 86400
            ch = (p.get("priceChange") or {}).get("h24") or 0; liq = (p.get("liquidity") or {}).get("usd") or 0
            fdv = p.get("fdv") or 0
            if age_d <= min(days, d["max_pair_age_days"]) and liq >= d["min_liquidity_usd"] and (ch >= d["min_price_change_h24_pct"] or fdv >= 20 * liq * 0 + 1e6):
                good.append({"token": a, "symbol": p["baseToken"]["symbol"], "change_h24": ch, "liq": liq, "fdv": fdv, "age_d": round(age_d, 2), "created": p["pairCreatedAt"] / 1000})
    good.sort(key=lambda g: -(g["fdv"] / max(g["liq"], 1) * 0 + g["fdv"]))
    return good[: d["max_tokens"]]


def early_buyers(tok):
    """First successful txs touching the mint (oldest first); keep signers that bought it."""
    res = WT.helius_call("getTransactionsForAddress", [tok["token"], {"transactionDetails": "full", "encoding": "jsonParsed",
        "maxSupportedTransactionVersion": 1, "sortOrder": "asc", "limit": 100, "filters": {"status": "succeeded"}}])
    buyers = []
    for t in res["data"]:
        signers = [k["pubkey"] for k in t["transaction"]["message"]["accountKeys"] if k.get("signer")]
        if not signers: continue
        w = signers[0]
        for s in WT.sol_parse_tx(t, w, t["transaction"]["signatures"][0]):
            if s["side"] == "BUY" and s["token"] == tok["token"] and w not in buyers: buyers.append(w)
    return buyers


PF_UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}


def pf_get(url, params=None):
    for i in range(4):
        r = requests.get(url, params=params, headers=PF_UA, timeout=30)
        if r.status_code == 429: time.sleep(10 * (i + 1)); continue
        r.raise_for_status(); return r.json()
    raise IOError(f"pump.fun 429: {url}")


def pumpfun_wallets(days):
    """Top holders (minus dev/sniper/bundler flags) and top realized sellers of pump.fun coins that ran recently."""
    d = CFG["discover"]; out = {}
    coins = pf_get("https://frontend-api-v3.pump.fun/coins", {"offset": 0, "limit": 50, "sort": "market_cap", "order": "DESC", "includeNsfw": "false"})
    coins = [c for c in coins if c.get("complete") and (time.time() - c["created_timestamp"] / 1000) / 86400 <= days]
    # keep coins DexScreener confirms with real liquidity (pump.fun market caps can be wash-inflated)
    info = {}
    for i in range(0, len(coins), 30):
        for pr in WT.get_json("https://api.dexscreener.com/tokens/v1/solana/" + ",".join(c["mint"] for c in coins[i:i + 30])) or []:
            a = pr["baseToken"]["address"]; l = (pr.get("liquidity") or {}).get("usd") or 0
            info[a] = max(info.get(a, 0), l)
    coins = [c for c in coins if info.get(c["mint"], 0) >= d["min_liquidity_usd"]][: d.get("pumpfun_coins", 4)]
    log(f"pump.fun coins: {[(c['symbol'], round(info[c['mint']])) for c in coins]}")
    for c in coins:
        m = c["mint"]; time.sleep(1)
        try:
            th = pf_get(f"https://frontend-api-v3.pump.fun/coins/top-holders/{m}").get("topHolders", [])
            keep = [h["address"] for h in th if not (h.get("isDev") or h.get("isSniper") or h.get("isBundler"))]
            for a in keep[1: 1 + d.get("pumpfun_holders_per_coin", 3)]:  # [0] is usually the pool
                out.setdefault(a, []).append(f"pump.fun top holder of {c['symbol']}")
        except Exception as e: log(f"pump.fun holders {c['symbol']}: {e}")
        agg, cur = {}, None
        for _ in range(d.get("pumpfun_trade_pages", 3)):
            time.sleep(1)
            j = pf_get(f"https://swap-api.pump.fun/v2/coins/{m}/trades", dict({"limit": 100}, **({"cursor": cur} if cur else {})))
            for t in j.get("trades", []):
                u = agg.setdefault(t["userAddress"], [0.0, 0.0]); u[0 if t["type"] == "buy" else 1] += float(t.get("amountUsd") or 0)
            cur = (j.get("pagination") or {}).get("nextCursor")
            if not cur: break
        top = sorted(agg.items(), key=lambda x: -(x[1][1] - x[1][0]))[: d.get("pumpfun_traders_per_coin", 3)]
        for a, (b, sl) in top:
            if sl > b: out.setdefault(a, []).append(f"pump.fun top seller of {c['symbol']} (net ${sl - b:,.0f} recent)")
    return out


def fomo_wallets():
    """fomo.family leaderboard: prod-api.fomo.family/v2/leaderboard/<range> (found in the web bundle)."""
    try:
        r = WT.S.get("https://prod-api.fomo.family/v2/leaderboard/30d", headers=PF_UA, timeout=20)
        if r.status_code != 200 or "unauthorized" in r.text: log(f"fomo.family leaderboard: HTTP {r.status_code} {r.text[:60]} (needs login) - skipped"); return {}
        lb = r.json()["responseObject"]["leaderboard"]
        return {e["solanaAddress"]: ["fomo.family leaderboard"] for e in lb if e.get("solanaAddress")}
    except Exception as e: log(f"fomo.family: {e}"); return {}


def discover(args):
    if args.chain != "solana": sys.exit("discover is Solana-only for now (EVM early-buyer scans need an indexer; use `score` for EVM wallets)")
    if not os.environ.get("HELIUS_API_KEY"): sys.exit("discover needs HELIUS_API_KEY")
    d = CFG["discover"]; cands = {}
    toks = runner_tokens("solana", args.days); log(f"runner tokens: {[(t['symbol'], t['change_h24'], round(t['fdv'])) for t in toks]}")
    for t in toks:
        try:
            for w in early_buyers(t)[: d["early_buyers_per_token"]]: cands.setdefault(w, []).append(f"early buyer of {t['symbol']}")
        except Exception as e: log(f"early buyers {t['symbol']}: {e}")
    for src in (pumpfun_wallets(args.days), fomo_wallets()):
        for a, why in src.items(): cands.setdefault(a, []).extend(why)
    lb = leaderboard_wallets()
    for a, src in list(lb.items())[: d["leaderboard_sample"]]: cands.setdefault(a, []).append(f"{src} leaderboard")
    # skip wallets seen across many runners as pure routers/bots? keep, flags will tell
    ranked = []
    for i, (w, why) in enumerate(list(cands.items())[: d["max_wallets_to_score"]]):
        try:
            r = score_wallet(w, "solana", CFG["days"], check=not args.no_check); r["sources"] = why; save_result(r); ranked.append(r)
            log(f"[{i+1}] {fmt(r)}")
        except Exception as e: log(f"score {w}: {e}")
    ranked.sort(key=lambda r: -r["rank_score"])
    out = {"run_at": datetime.now(WT.LAGOS).isoformat(timespec="seconds"), "tokens": toks, "candidates": ranked[: args.limit],
           "helius_credits": WT.HELIUS_CREDITS["credits"]}
    WT.save(os.path.join(RES, f"discover_{datetime.now(WT.LAGOS):%Y%m%d_%H%M}.json"), out)
    for n, r in enumerate(ranked[: args.limit], 1): print(f"{n:>2}. {fmt(r, r['address'])}\n    via: {', '.join(r['sources'])}")
    log(f"helius credits this run: ~{WT.HELIUS_CREDITS['credits']}")


def main():
    ap = argparse.ArgumentParser(description=__doc__); sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("discover"); d.add_argument("--chain", default="solana"); d.add_argument("--days", type=int, default=7)
    d.add_argument("--limit", type=int, default=10); d.add_argument("--no-check", action="store_true")
    s = sub.add_parser("score"); s.add_argument("wallet"); s.add_argument("--chain", default=None); s.add_argument("--days", type=int)
    s.add_argument("--label", default=""); s.add_argument("--json", action="store_true"); s.add_argument("--no-check", action="store_true")
    t = sub.add_parser("top"); t.add_argument("--limit", type=int, default=20); t.add_argument("--min-copyability", type=int, default=0)
    p = sub.add_parser("promote"); p.add_argument("wallet"); p.add_argument("--label", required=True); p.add_argument("--chain")
    a = ap.parse_args(); os.makedirs(RES, exist_ok=True)
    if a.cmd == "discover": discover(a)
    elif a.cmd == "score":
        chain = a.chain or ("solana" if not a.wallet.startswith("0x") else sys.exit("pass --chain for 0x wallets"))
        r = score_wallet(a.wallet, chain, a.days, check=not a.no_check); r["label"] = a.label; save_result(r)
        print(json.dumps(r, indent=2) if a.json else fmt(r, a.label)); log(f"helius credits: ~{r['helius_credits']}")
    elif a.cmd == "top":
        db = sorted(WT.load(os.path.join(RES, "scores.json"), {}).values(), key=lambda r: -r["rank_score"])
        for n, r in enumerate([r for r in db if r["copyability"] >= a.min_copyability][: a.limit], 1): print(f"{n:>2}. {fmt(r, r.get('label') or r['address'])}")
    elif a.cmd == "promote":
        cmd = ["python3", os.path.join(WT_DIR, "wallet_tracker.py"), "add", a.wallet, "--label", a.label] + (["--chain", a.chain] if a.chain else [])
        sys.exit(subprocess.call(cmd))


if __name__ == "__main__":
    main()
