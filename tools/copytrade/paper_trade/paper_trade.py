#!/usr/bin/env python3
"""paper_trade — paper-trade auditor for copy-trading signals. SIMULATION ONLY: no keys, no orders, ever.

python3 paper_trade.py open <token> --source wallet:<nick>|xcall:<handle>|manual [--chain solana] [--signal-id ID]
python3 paper_trade.py ingest [--scan-file scan.json] [--no-xcalls]
python3 paper_trade.py update
python3 paper_trade.py report [--book live|backtest|all]
python3 paper_trade.py backtest [--wallets "E/acc guy,Nullmask winner"] [--days 30] [--reuse]
"""
import argparse, json, os, subprocess, sys, time, shutil
from datetime import datetime, timezone, timedelta
import requests

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
CFG = json.load(open(os.path.join(HERE, "config.json")))
TRADES = os.path.join(HERE, "trades.json"); RES = os.path.join(HERE, "results"); CACHE = os.path.join(HERE, "cache")
TC = os.path.join(ROOT, "token_check", "token_check.py"); WT = os.path.join(ROOT, "wallet_tracker", "wallet_tracker.py")
XC = os.path.join(ROOT, "x_calls", "calls.json")
LAGOS = timezone(timedelta(hours=1)); S = requests.Session(); S.headers["User-Agent"] = "paper_trade/1.0"
GT_NET = {"solana": "solana", "ethereum": "eth", "base": "base", "bsc": "bsc", "arbitrum": "arbitrum", "robinhood": "robinhood",
          "hyperevm": "hyperevm", "ink": "ink"}  # GeckoTerminal network ids (verified 2026-10-20)
DS_CHAIN = {"robinhood": "robinhood"}


def log(*a): print(*a, file=sys.stderr)
def load(p, d):
    try: return json.load(open(p))
    except (OSError, ValueError): return d
def save(p, o):
    tmp = p + ".tmp"; json.dump(o, open(tmp, "w"), indent=2); os.replace(tmp, p)
def wat(ts): return datetime.fromtimestamp(ts, LAGOS).strftime("%Y-%m-%d %H:%M WAT") if ts else "-"


def get(url, params=None, tries=4):
    for i in range(tries):
        try:
            r = S.get(url, params=params, timeout=30)
            if r.status_code == 429 or r.status_code >= 500: time.sleep(5 * (i + 1)); continue
            if r.status_code != 200: return None
            return r.json()
        except (requests.RequestException, ValueError): time.sleep(2 * (i + 1))
    return None


# ---------- prices ----------
def best_pairs(chain, tokens):
    """token -> best-liquidity DexScreener pair (pool, price, symbol)."""
    out = {}
    for i in range(0, len(tokens), 30):
        j = get(f"https://api.dexscreener.com/tokens/v1/{DS_CHAIN.get(chain, chain)}/" + ",".join(tokens[i:i + 30])) or []
        for p in j if isinstance(j, list) else []:
            t = p["baseToken"]["address"]; low = {x.lower(): x for x in tokens}
            if t not in tokens and t.lower() in low: t = low[t.lower()]
            if t not in tokens: continue
            liq = (p.get("liquidity") or {}).get("usd") or 0
            if t not in out or liq > out[t]["liq"]:
                out[t] = {"pool": p["pairAddress"], "price": float(p.get("priceUsd") or 0) or None, "symbol": p["baseToken"].get("symbol"), "liq": liq}
    return out


_GT = [0.0]
def candles(chain, pool, frm, to=None, tf="hour", agg=1):
    """hourly OHLCV [ts,o,h,l,c,v] ascending, frm..to (GeckoTerminal, cached per pool)."""
    to = to or int(time.time()); cp = os.path.join(CACHE, f"gt_{chain}_{pool}" + ("" if tf == "hour" else f"_{tf}{agg}") + ".json"); step_s = {"hour": 3600, "minute": 60}[tf] * agg; c = load(cp, None)
    if c and c["from"] <= frm and c["to"] >= min(to, int(time.time()) - step_s):
        return [x for x in c["ohlcv"] if frm <= x[0] <= to]
    rows, before = {}, to + step_s
    while before > frm:
        wait = CFG["gecko_spacing_s"] - (time.time() - _GT[0])
        if wait > 0: time.sleep(wait)
        _GT[0] = time.time()
        j = get(f"https://api.geckoterminal.com/api/v2/networks/{GT_NET.get(chain, chain)}/pools/{pool}/ohlcv/{tf}",
                {"aggregate": agg, "before_timestamp": before, "limit": 1000, "currency": "usd", "token": "base"})
        lst = ((j or {}).get("data") or {}).get("attributes", {}).get("ohlcv_list") or []
        if not lst: break
        for x in lst: rows[int(x[0])] = [int(x[0])] + [float(v) for v in x[1:6]]
        mn = min(int(x[0]) for x in lst)
        if mn >= before or len(lst) < 1000: break
        before = mn
    ohl = sorted(rows.values()); save(cp, {"from": frm, "to": to, "ohlcv": ohl})
    return [x for x in ohl if frm <= x[0] <= to]


# ---------- token_check ----------
def token_check(token, chain):
    cp = os.path.join(CACHE, "token_check.json"); c = load(cp, {}); k = f"{chain}:{token}"
    if k in c and time.time() - c[k]["checked_at"] < 6 * 3600: return c[k]
    try:
        r = subprocess.run([sys.executable, TC, token, "--chain", chain, "--json", "--no-narrative"], capture_output=True, text=True, timeout=CFG["token_check_timeout_s"])
        j = json.loads(r.stdout); res = {"verdict": j.get("verdict"), "score": j.get("score"), "summary": (j.get("summary") or "")[:200]}
    except Exception as e:
        res = {"verdict": "ERROR", "score": None, "summary": str(e)[:120]}
    res["checked_at"] = int(time.time()); c[k] = res; save(cp, c); return res


# ---------- positions ----------
def cost_frac(chain):
    rt = CFG["round_trip_cost_pct"]; return rt.get(chain, rt["default"]) / 100.0


def new_position(book, source, token, chain, entry_px, entry_ts, signal_id, tc, symbol=None, pool=None, extra=None):
    gated = CFG["gate"] and tc.get("verdict") == "KILL"
    p = {"id": signal_id, "book": book, "source": source, "token": token, "symbol": symbol, "chain": chain, "pool": pool,
         "entry_ts": entry_ts, "entry_wat": wat(entry_ts), "entry_px": entry_px, "notional": CFG["notional_usd"],
         "cost_pct": cost_frac(chain) * 100, "sl_px": entry_px * (1 + CFG["stop_loss_pct"] / 100.0),
         "tp": [{"px": entry_px * (1 + t["pct"] / 100.0), "frac": t["sell_frac"], "pct": t["pct"], "hit": None} for t in CFG["take_profit_ladder"]],
         "max_hold_ts": entry_ts + CFG["max_hold_hours"] * 3600, "token_check": {k: tc.get(k) for k in ("verdict", "score", "summary")},
         "gated_out": gated, "status": "open", "fills": [], "exit_ts": None, "r": None, "pnl_usd": None, "last_candle": None}
    if extra: p.update(extra)
    return p


def close_part(p, frac, px, ts, why):
    p["fills"].append({"frac": frac, "px": px, "ts": ts, "wat": wat(ts), "why": why})


def remaining(p): return 1.0 - sum(f["frac"] for f in p["fills"])


def finalize(p):
    """R = net PnL / risk, risk = notional * |SL|. Costs: half the round trip on entry, half on exit."""
    half = p["cost_pct"] / 200.0; eff_in = p["entry_px"] * (1 + half)
    gross = sum(f["frac"] * f["px"] * (1 - half) for f in p["fills"])
    pnl = p["notional"] * (gross / eff_in - 1)
    p["pnl_usd"] = round(pnl, 2); p["r"] = round(pnl / (p["notional"] * abs(CFG["stop_loss_pct"]) / 100.0), 3)
    p["exit_ts"] = max(f["ts"] for f in p["fills"]); p["exit_wat"] = wat(p["exit_ts"])
    p["exit_reason"] = "+".join(dict.fromkeys(f["why"] for f in p["fills"])); p["status"] = "closed"
    p["hold_h"] = round((p["exit_ts"] - p["entry_ts"]) / 3600, 1)


def step(p, c, sell_ts=None, cs_len=3600):
    """apply one hourly candle [ts,o,h,l,c,v]; conservative: SL before TP inside one candle. sell_ts = wallet sell inside this candle."""
    ts, o, h, l, cl = c[0], c[1], c[2], c[3], c[4]
    if l <= p["sl_px"]:
        close_part(p, remaining(p), min(p["sl_px"], o), ts, "SL"); return True   # gap through SL fills at open
    for t in p["tp"]:
        if not t["hit"] and h >= t["px"]:
            t["hit"] = ts; close_part(p, min(t["frac"], remaining(p)), max(t["px"], o), ts, f"TP{t['pct']}")
    if remaining(p) <= 1e-9: return True
    if sell_ts is not None:
        close_part(p, remaining(p), cl, ts, "mirror_sell"); return True
    if ts + cs_len >= p["max_hold_ts"]:
        close_part(p, remaining(p), cl, ts + cs_len, "max_hold"); return True
    return False


def simulate(p, cs, sell_times=(), L=3600):
    """walk candles strictly after the entry candle."""
    start = p["entry_ts"] - p["entry_ts"] % L + L
    sells = sorted(t for t in sell_times if t > p["entry_ts"]) if CFG["mirror_wallet_sells"] else []
    if sells and sells[0] < start:   # wallet sold inside the entry candle: exit at that candle's close (= entry px, so costs only)
        close_part(p, 1.0, p["entry_px"], sells[0], "mirror_sell_same_candle"); finalize(p); return
    for c in cs:
        if c[0] < start: continue
        if c[0] >= p["max_hold_ts"] + L: break
        st = next((s for s in sells if c[0] <= s < c[0] + L), None)
        if sells and sells[0] < c[0] and st is None and remaining(p) > 0:   # sell fell in a candle-less gap
            close_part(p, remaining(p), c[1], c[0], "mirror_sell"); break
        p["last_candle"] = c[0]
        if step(p, c, st, L): break
    if remaining(p) <= 1e-9: finalize(p)
    elif time.time() >= p["max_hold_ts"] + 3600 and p["last_candle"]:
        last = [c for c in cs if c[0] <= p["max_hold_ts"]]   # dead pool (no candles): exit at last close
        if last: close_part(p, remaining(p), last[-1][4], p["max_hold_ts"], "max_hold_stale"); finalize(p)


# ---------- commands ----------
def cmd_open(a, trades=None):
    own = trades is None; trades = load(TRADES, []) if own else trades
    chain = a.chain or ("solana" if not a.token.startswith("0x") else None)
    if not chain: sys.exit("0x token: pass --chain")
    sid = a.signal_id or f"{a.source}:{a.token}:{int(time.time())}"
    if any(t["id"] == sid for t in trades): log(f"dup signal {sid}"); return None
    if CFG["one_position_per_token_per_source"] and any(t["status"] == "open" and t["token"] == a.token and t["source"] == a.source and t["book"] == "live" for t in trades):
        log(f"already holding {a.token} from {a.source}"); return None
    bp = best_pairs(chain, [a.token]).get(a.token)
    if not bp or not bp["price"]: log(f"no price for {a.token}"); return None
    tc = token_check(a.token, chain)
    p = new_position("live", a.source, a.token, chain, bp["price"], int(time.time()), sid, tc, bp["symbol"], bp["pool"], getattr(a, "extra", None))
    trades.append(p)
    if own: save(TRADES, trades)
    print(f"OPEN {p['source']} {p['symbol']} @ ${p['entry_px']:.8g}  token_check {tc['verdict']} {tc['score']}" + ("  [gated out: KILL, tracked as shadow]" if p["gated_out"] else ""))
    return p


def cmd_ingest(a):
    trades = load(TRADES, []); now = time.time(); maxage = CFG["ingest_max_signal_age_hours"] * 3600
    if a.scan_file: scan = load(a.scan_file, {})
    else:
        r = subprocess.run([sys.executable, WT, "scan", "--json"], capture_output=True, text=True, timeout=1800, cwd=os.path.dirname(WT))
        scan = json.loads(r.stdout) if r.stdout.strip() else {}
    for s in scan.get("swaps", []):
        if s["label"].startswith("test-"): continue
        src = f"wallet:{s['label']}"
        if s["side"] == "SELL":
            for p in trades:
                if p["book"] == "live" and p["status"] == "open" and p["source"] == src and p["token"] == s["token"] and CFG["mirror_wallet_sells"]:
                    bp = best_pairs(p["chain"], [p["token"]]).get(p["token"])
                    if bp and bp["price"]: close_part(p, remaining(p), bp["price"], int(now), "mirror_sell"); finalize(p); print(f"CLOSE mirror sell {p['symbol']} R={p['r']}")
            continue
        if now - (s.get("time") or now) > maxage: continue
        ns = argparse.Namespace(token=s["token"], chain=s["chain"], source=src, signal_id=f"wallet:{s['tx']}:{s['token']}",
                                extra={"signal_ts": s.get("time"), "wallet_fill_usd": s.get("usd")})
        cmd_open(ns, trades)
    if CFG["ingest_xcall_sources"] and not a.no_xcalls:
        for c in load(XC, []):
            if not c.get("token") or c.get("status") == "unresolved" or now - c["time"] > maxage: continue
            ns = argparse.Namespace(token=c["token"], chain=c["chain"], source=f"xcall:{c['caller']}", signal_id=f"xcall:{c['post_id']}:{c['token']}",
                                    extra={"signal_ts": c["time"], "post": c.get("url")})
            cmd_open(ns, trades)
    save(TRADES, trades)


def cmd_update(a):
    trades = load(TRADES, []); n = 0
    for p in trades:
        if p["status"] != "open" or p["book"] != "live": continue
        cs = candles(p["chain"], p["pool"], p["entry_ts"] - 3600, int(time.time()))
        q = json.loads(json.dumps(p)); q["fills"], q["last_candle"] = [], None
        for t in q["tp"]: t["hit"] = None
        simulate(q, cs)
        if q["status"] == "closed" or q["fills"]: p.update(q); n += q["status"] == "closed"
    save(TRADES, trades); print(f"updated; {n} closed this run, {sum(t['status'] == 'open' for t in trades)} open")


# ---------- stats / report ----------
def stats(ts):
    cl = sorted([t for t in ts if t["status"] == "closed"], key=lambda t: t["exit_ts"])
    n = len(cl)
    if not n: return {"n": 0, "open": sum(t["status"] == "open" for t in ts)}
    rs = [t["r"] for t in cl]; wins = sum(r > 0 for r in rs)
    eq = peak = CFG["starting_equity_usd"]; dd = 0.0
    for t in cl:
        eq += t["pnl_usd"]; peak = max(peak, eq); dd = max(dd, (peak - eq) / peak * 100)
    s = {"n": n, "open": sum(t["status"] == "open" for t in ts), "win_rate": wins / n, "exp_r": sum(rs) / n, "total_r": sum(rs),
         "max_dd": dd, "avg_hold": sum(t["hold_h"] for t in cl) / n, "pnl": sum(t["pnl_usd"] for t in cl)}
    b = CFG["bar"]
    if n < b["min_trades"]: s["verdict"] = "NOT ENOUGH TRADES"
    else: s["verdict"] = "PASS" if (s["win_rate"] >= b["min_win_rate"] and s["exp_r"] >= b["min_expectancy_r"] and dd <= b["max_drawdown_pct"]) else "FAIL"
    if n < b["min_trades"]:   # still say which way it is leaning
        s["lean"] = "on track" if (s["win_rate"] >= b["min_win_rate"] and s["exp_r"] >= b["min_expectancy_r"] and dd <= b["max_drawdown_pct"]) else "failing so far"
    return s


def row(name, s):
    if not s["n"]: return f"| {name} | 0 | - | - | - | - | - | {s['open']} | NOT ENOUGH TRADES |"
    v = s["verdict"] + (f" ({s['lean']})" if s.get("lean") else "")
    return f"| {name} | {s['n']} | {s['win_rate']*100:.0f}% | {s['exp_r']:+.2f} | {s['total_r']:+.1f} | {s['max_dd']:.1f}% | {s['avg_hold']:.1f}h | {s['open']} | {v} |"


HDR = "| source | trades | win rate | exp R | total R | max DD | avg hold | open | verdict |\n|---|---|---|---|---|---|---|---|---|"


def cmd_report(a):
    trades = [t for t in load(TRADES, []) if a.book == "all" or t["book"] == a.book]
    taken = [t for t in trades if not t["gated_out"]] if CFG["gate"] else trades
    b = CFG["bar"]; L = [f"# Paper-trade report ({a.book} book) — {datetime.now(LAGOS).strftime('%Y-%m-%d %H:%M WAT')}", "",
        f"SIMULATION ONLY. ${CFG['notional_usd']}/trade, SL {CFG['stop_loss_pct']}% (=1R), TP ladder " + ", ".join(f"+{t['pct']}% x{t['sell_frac']}" for t in CFG['take_profit_ladder']) +
        f", max hold {CFG['max_hold_hours']}h, costs {CFG['round_trip_cost_pct']['solana']}% round trip (Solana). Equity curve starts at ${CFG['starting_equity_usd']}. Gate mode: **{'ON (KILL skipped)' if CFG['gate'] else 'OFF'}**.",
        f"Bar: ≥{b['min_trades']} trades, ≥{b['min_win_rate']*100:.0f}% win rate, ≥+{b['min_expectancy_r']}R expectancy, ≤{b['max_drawdown_pct']}% max DD.", "",
        "## Per source (current gate mode)", "", HDR]
    for src in sorted({t["source"] for t in taken}): L.append(row(src, stats([t for t in taken if t["source"] == src])))
    L.append(row("**OVERALL**", stats(taken)))
    L += ["", "## Gate on vs gate off", "", HDR]
    for src in sorted({t["source"] for t in trades}) + [None]:
        sub = [t for t in trades if src is None or t["source"] == src]; nm = src or "OVERALL"
        L.append(row(f"{nm} — gate OFF (all)", stats(sub)))
        L.append(row(f"{nm} — gate ON (no KILL)", stats([t for t in sub if t["token_check"]["verdict"] != "KILL"])))
        L.append(row(f"{nm} — KILL only", stats([t for t in sub if t["token_check"]["verdict"] == "KILL"])))
    cl = [t for t in trades if t["status"] == "closed"]
    reasons = {}
    for t in cl: reasons[t["exit_reason"]] = reasons.get(t["exit_reason"], 0) + 1
    L += ["", "Exit reasons: " + ", ".join(f"{k} {v}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])), ""]
    skipped = load(os.path.join(RES, "backtest_skipped.json"), {}) if a.book != "live" else {}
    if skipped: L += ["Backtest signals not simulated: " + ", ".join(f"{k} {v}" for k, v in skipped.items()), ""]
    L += ["## Closed trades", "", "| source | token | entry | exit | reason | tc | R |", "|---|---|---|---|---|---|---|"]
    for t in sorted(cl, key=lambda t: t["entry_ts"]):
        L.append(f"| {t['source']} | {t['symbol'] or t['token'][:6]} | {t['entry_wat']} | {t['exit_wat']} | {t['exit_reason']} | {t['token_check']['verdict']} {t['token_check']['score']} | {t['r']:+.2f} |")
    txt = "\n".join(L) + "\n"; os.makedirs(RES, exist_ok=True); open(os.path.join(RES, "report.md"), "w").write(txt); print(txt)


# ---------- backtest ----------
def cmd_backtest(a):
    wallets = [w.strip() for w in (a.wallets or ",".join(CFG["backtest_wallets"])).split(",")]
    days = a.days or CFG["backtest_days"]; since = int(time.time()) - days * 86400
    raw = os.path.join(CACHE, "backfill.json" if not a.wallets else "backfill_" + "_".join(x.replace("/", "") for x in wallets) + ".json")
    if a.reuse and os.path.exists(raw): swaps = load(raw, [])
    else:
        swaps = []
        stdir = os.path.join(os.path.dirname(WT), "state")
        for w in wallets:
            # --backfill moves the live baseline; back the state up and restore it so the hourly routine misses nothing
            wl = [x for x in load(os.path.join(os.path.dirname(WT), "wallets.json"), []) if x["label"] == w]
            if not wl: log(f"unknown wallet {w}"); continue
            sp = os.path.join(stdir, f"{wl[0]['chain']}_{wl[0]['address']}.json"); bk = sp + ".paperbak"
            if os.path.exists(sp): shutil.copy(sp, bk)
            try:
                r = subprocess.run([sys.executable, WT, "scan", w, "--json", "--backfill", str(CFG["backtest_backfill_n"] if wl[0]["chain"] == "solana" else CFG.get("backtest_backfill_n_evm", 150)), "--no-check", "--verbose"],
                                   capture_output=True, text=True, timeout=1800, cwd=os.path.dirname(WT))
            finally:
                if os.path.exists(bk): shutil.move(bk, sp)
            for line in r.stderr.splitlines(): log(f"[{w}] {line}")
            j = json.loads(r.stdout) if r.stdout.strip() else {}
            swaps += j.get("swaps", [])
        save(raw, swaps)
    trades = [t for t in load(TRADES, []) if not (t["book"] == "backtest" and t["source"] in {f"wallet:{w}" for w in wallets})]; bt = []; skipped = {}
    def skip(k): skipped[k] = skipped.get(k, 0) + 1
    for w in wallets:
        ws = sorted([s for s in swaps if s["label"] == w], key=lambda s: s["time"] or 0)
        if ws: log(f"[{w}] {len(ws)} swaps, oldest {wat(ws[0]['time'])}, newest {wat(ws[-1]['time'])}")
        buys = [s for s in ws if s["side"] == "BUY" and (s["time"] or 0) >= since]
        chain = ws[0]["chain"] if ws else "solana"; tf, agg = CFG.get("backtest_candles", {}).get(chain, ["hour", 1]); L = {"hour": 3600, "minute": 60}[tf] * agg
        if a.max_buys: buys = buys[-a.max_buys:]
        toks = sorted({s["token"] for s in buys}); bp = best_pairs(chain, toks) if toks else {}
        for s in buys:
            if s["token"] not in bp: skip("no DexScreener pool"); continue
            if any(p["source"] == f"wallet:{w}" and p["token"] == s["token"] and (p["status"] == "open" or (p["exit_ts"] or 0) > s["time"]) for p in bt):
                skip("already in position"); continue
            pool = bp[s["token"]]["pool"]
            cs = candles(chain, pool, s["time"] - L, min(int(time.time()), s["time"] + (CFG["max_hold_hours"] + 2) * 3600), tf, agg)
            ec = [c for c in cs if c[0] <= s["time"] < c[0] + L]
            if not ec: skip("no candle at buy (pre-pool / bonding curve or no OHLCV)"); continue
            tc = token_check(s["token"], chain)
            p = new_position("backtest", f"wallet:{w}", s["token"], chain, ec[0][4], s["time"], f"bt:{s['tx']}:{s['token']}", tc,
                             bp[s["token"]]["symbol"], pool, {"wallet_fill_usd": s.get("usd"), "wallet_fill_px": (s["usd"] / s["amount"]) if s.get("usd") and s.get("amount") else None})
            sells = [x["time"] for x in ws if x["side"] == "SELL" and x["token"] == s["token"]]
            p["candles"] = f"{tf}{agg}"; simulate(p, cs, sells, L); bt.append(p)
    save(TRADES, trades + bt); sk = load(os.path.join(RES, "backtest_skipped.json"), {}); sk.update({f"{",".join(wallets)}: {k}": v for k, v in skipped.items()}) if a.wallets else None; save(os.path.join(RES, "backtest_skipped.json"), sk if a.wallets else skipped)
    print(f"backtest: {len(bt)} positions ({sum(p['status']=='closed' for p in bt)} closed), skipped {skipped}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open"); o.add_argument("token"); o.add_argument("--chain"); o.add_argument("--source", default="manual"); o.add_argument("--signal-id")
    i = sub.add_parser("ingest"); i.add_argument("--scan-file"); i.add_argument("--no-xcalls", action="store_true")
    sub.add_parser("update")
    r = sub.add_parser("report"); r.add_argument("--book", default="all", choices=["live", "backtest", "all"])
    b = sub.add_parser("backtest"); b.add_argument("--wallets"); b.add_argument("--days", type=int); b.add_argument("--reuse", action="store_true"); b.add_argument("--max-buys", type=int)
    a = ap.parse_args(); os.makedirs(CACHE, exist_ok=True); os.makedirs(RES, exist_ok=True)
    if not os.path.exists(TRADES): save(TRADES, [])
    {"open": cmd_open, "ingest": cmd_ingest, "update": cmd_update, "report": cmd_report, "backtest": cmd_backtest}[a.cmd](a)


if __name__ == "__main__":
    main()
