import re
"""Owner-only tool wrappers for Netro Signal. Each returns (text, buttons_or_None). Read-only toward funds: no keys, no trades."""
import glob, json, os, subprocess, sys, time
from datetime import datetime
import gate

ROOT = gate.ROOT; STATE = os.path.join(gate.HERE, "state.json")
PY = sys.executable
WT = os.path.join(ROOT, "wallet_tracker", "wallet_tracker.py"); SM = os.path.join(ROOT, "smart_money", "smart_money.py")
XC = os.path.join(ROOT, "x_calls", "x_calls.py"); PT = os.path.join(ROOT, "paper_trade", "paper_trade.py")


def sh(script, *args, timeout=300):
    r = subprocess.run([PY, script, *args], capture_output=True, text=True, timeout=timeout, cwd=os.path.dirname(script))
    return r.returncode, r.stdout, r.stderr


def st(): return gate.load(STATE, {})
def st_save(s): gate.atomic_dump(s, STATE, indent=1)
def ago(sec): return f"{int(sec//60)} min" if sec >= 60 else f"{int(sec)} s"


# ---------- token ----------
def check(args):
    if not args: return "How to use: /check <token address> [chain]", None
    tok, ch, _ = gate.split_args(args)
    if not tok: return "How to use: /check <token address> [chain, e.g. sol, rh, eth, base, ink]", None
    g = gate.gate(tok, ch)
    return gate.card_text(g), g["buttons"]


def safety(args):
    if not args: return "How to use: /safety <token address> [chain]", None
    tok, ch, _ = gate.split_args(args)
    if not tok: return "How to use: /safety <token address> [chain, e.g. sol, rh, eth, base, ink]", None
    args = [tok]; tc = gate.token_check(tok, ch)
    if not tc.get("verdict"): return "😕 I couldn't find that token. Check the address and chain.", None
    E = gate.esc; m = tc.get("market") or {}
    head = {"PASS": "🟢 <b>Passed</b>", "WARN": "🟡 <b>Some worries</b>", "KILL": "🔴 <b>Failed</b>"}[tc["verdict"]]
    L = [f"🛡 Safety check for <b>${E((tc.get('symbol') or '?').lstrip('$'))}</b>", f"on {E(gate.chain_name(tc.get('chain')))} · <code>{E(args[0])}</code>", "",
         f"{head} · score {tc.get('score')}/100"]
    if m: L.append(f"{gate.usd_short(m.get('liq_usd'))} in the pool · {gate.usd_short(m.get('vol_24h'))} traded today · {age(m.get('age_min'))} old")
    fails = [c for c in tc.get("checks", []) if c.get("status") == "fail"]; unk = [c for c in tc.get("checks", []) if c.get("status") == "unknown"]
    oks = [c for c in tc.get("checks", []) if c.get("status") == "pass"]
    if fails:
        L += ["", "<b>Problems</b>"] + [f"{'⛔' if c.get('severity') == 'kill' else '⚠️'} {E(gate.FRIENDLY.get(c['check'], c['check'].replace('_', ' ')))}" for c in fails]
    if unk:
        L += ["", "<b>Couldn't check</b>"] + [f"❔ not sure: {E(GOOD.get(c['check'], c['check'].replace('_', ' ')))}" for c in unk]
    if oks:
        names = [GOOD.get(c["check"], c["check"].replace("_", " ")) for c in oks]
        L += ["", f"<b>Looks fine</b> ({len(oks)} checks passed)", "✅ " + E(", ".join(names[:6])) + (" and more" if len(names) > 6 else "")]
    n = gate.narr_words(tc)
    if n: L += ["", f"📖 {E(n)}"]
    L += ["", "⛔ = deal-breaker   ⚠️ = be careful", "", gate.FOOTER]
    return gate.Html("\n".join(L)), [("📊 DexScreener", m.get("url") or f"https://dexscreener.com/{tc.get('chain')}/{args[0]}")]


GOOD = {"rugged": "not rugged", "mint_authority": "no new tokens can be printed", "freeze_authority": "your tokens can't be frozen",
        "danger_flags": "no danger flags", "risk_score": "low risk rating", "honeypot": "you can sell", "sell_tax": "no big sell tax",
        "buy_tax": "no big buy tax", "owner_can_mint": "owner can't print tokens", "proxy": "contract can't be swapped",
        "blacklist": "no wallet blocking", "owner_powers": "owner has no special powers", "open_source": "code is public",
        "lp_lock": "pool is locked", "lp_unlocked_tiny": "pool is big or locked", "top10_holders": "supply is spread out",
        "dev_wallet": "creator's bag is small", "insiders": "no insider wallets", "liquidity": "enough money in the pool",
        "ticket_share": "your buy won't move the price much", "pair_age": "not brand new", "sells_exist": "people are selling fine",
        "volume": "people are trading it", "fdv_liquidity": "price looks sane next to the pool", "profile": "has website/socials"}


def age(mins):
    if not mins: return "?"
    h = mins / 60
    return f"{int(mins)} min" if h < 1 else f"{h:.0f}h" if h < 48 else f"{h/24:.0f} days"


# ---------- wallets ----------
def watch(args):
    if len(args) < 2: return "How to use: /watch <address> <nickname> [chain]", None
    addr = args[0]; chain = None
    if len(args) > 2 and args[-1].lower() in ("solana", "ethereum", "base", "bsc", "arbitrum", "robinhood"): chain = args[-1].lower(); nick = " ".join(args[1:-1])
    else: nick = " ".join(args[1:])
    if addr.startswith("0x") and not chain: return "For a 0x address, add the chain too, like: /watch 0x… Nick robinhood", None
    rc, out, err = sh(WT, "add", addr, "--label", nick, *(["--chain", chain] if chain else []), timeout=120)
    return (f"👀 Following {nick}. I'll ping you on their next buy (the first scan just sets a starting point)." if rc == 0 else f"😕 Couldn't add it: {(err or out).strip()[-200:]}"), None


def unwatch(args):
    if not args: return "How to use: /unwatch <nickname>", None
    nick = " ".join(args); rc, out, err = sh(WT, "remove", nick, timeout=60)
    return (f"🙈 Stopped following {nick}." if rc == 0 else f"😕 Couldn't remove it: {(err or out).strip()[-200:]}"), None


def wallets(args=None):
    L = ["📒 Wallets you follow"]
    for w in gate.load(gate.WALLETS, []):
        if gate.is_test(w["label"]): continue
        r = gate.wallet_record(w["label"])
        tag = {"ok": "looks fine", "failing": "losing on paper", "thin": "not enough data"}[r["status"]]
        L.append(f"• {w['label']} ({w['chain']}): {r['words']}. {tag}" + (f", {r['open']} still open" if r["open"] else ""))
    return "\n".join(L), None


def scan(args=None, force=False):
    """Returns (text, None, scan_path or None)."""
    s = st(); c = gate.cfg(); last = s.get("last_manual_scan", 0); wait = c.get("scan_cooldown_s", 600) - (time.time() - last)
    if wait > 0 and not force: return f"⏱ I scanned {ago(time.time()-last)} ago. Try again in {ago(wait)}.", None, None
    s["last_manual_scan"] = time.time(); st_save(s)
    rc, out, err = sh(WT, "scan", "--json", timeout=600)
    if rc not in (0,) and not out.strip(): return f"😕 The scan failed: {err.strip()[-200:]}", None, None
    d = json.loads(out) if out.strip() else {"swaps": []}
    d.setdefault("scanned_at", datetime.now(gate.LAGOS).isoformat())
    json.dump(d, open(gate.SCAN, "w"), indent=2)
    sw = d.get("swaps", []); real = [x for x in sw if not gate.is_test(x.get("label"))]
    buys = sum(x["side"] == "BUY" for x in real)
    return f"📡 Scan done: {buys} new buys from your wallets" + (" (cards coming)." if buys else ". Nothing new."), None, gate.SCAN


# ---------- smart money ----------
def score(args):
    if not args: return "How to use: /score <wallet address> [chain]", None
    if not re.fullmatch(r"0x[0-9a-fA-F]{40}|[1-9A-HJ-NP-Za-km-z]{32,44}", args[0]):
        return "That doesn't look like a wallet address. Paste the full address, like /score 7xKX…(32-44 letters) or 0x…", None
    c = gate.cfg(); s = st(); day = datetime.now(gate.LAGOS).strftime("%Y-%m-%d"); used = s.get("score_used", {}).get(day, 0)
    if used >= c.get("score_per_day", 10): return f"⏱ That's {used} scores today, the daily max. It resets at midnight WAT.", None
    s["score_used"] = {day: used + 1}; st_save(s)
    rc, out, err = sh(SM, "score", args[0], *(["--chain", gate.norm_chain(args[1])] if len(args) > 1 else []), "--json", timeout=300)
    try: r = json.loads(out)
    except Exception: return "😕 Scoring failed: " + ((err or out).strip().splitlines() or ["no output"])[-1][-160:], None
    return score_words(r), None


def score_words(r, name=None):
    pnl = r.get("realized_pnl_usd") or 0
    L = [f"Wallet {name or r.get('label') or r['address'][:6]+'…'+r['address'][-4:]} ({r.get('chain')}), last {r.get('days', 30)} days:",
         f"• {'Made' if pnl >= 0 else 'Lost'} ${abs(pnl):,.0f} on trades it closed; won {r.get('win_rate_pct', 0):.0f}% of {r.get('closed_positions', 0)} of them",
         f"• About {r.get('trades_per_day', 0):.0f} trades a day, usually holds {hold(r.get('median_hold_s'))}, typical buy ${r.get('median_buy_usd') or 0:,.0f}",
         f"• {r.get('kill_pct_sampled', 0)}% of its biggest buys fail the token check",
         f"• Easy to copy: {r.get('copyability', 0)}/100"]
    if r.get("flags"): L.append("• Watch out: " + "; ".join(r["flags"]))
    return "\n".join(L)


def hold(s):
    if not s: return "?"
    return f"{s/3600:.0f}h" if s >= 3600 else f"{s/60:.0f} min" if s >= 60 else f"{s:.0f}s"


def smartmoney(args=None):
    db = sorted(gate.load(os.path.join(ROOT, "smart_money", "results", "scores.json"), {}).values(), key=lambda r: -r.get("rank_score", 0))[:8]
    if not db: return "No smart-money scores saved yet.", None
    L = ["Top scored wallets (best first):"]
    for i, r in enumerate(db, 1):
        name = r.get("label") or r["address"][:6] + "…" + r["address"][-4:]
        L.append(f"{i}. {name}: {'made' if r.get('realized_pnl_usd',0)>=0 else 'lost'} ${abs(r.get('realized_pnl_usd',0)):,.0f}, wins {r.get('win_rate_pct',0):.0f}%, copy-ease {r.get('copyability',0)}/100, {r.get('kill_pct_sampled',0)}% risky buys"
                 + (f". ⚠️ {r['flags'][0].split(':')[0]}" if r.get("flags") else ""))
    return "\n".join(L), None


def fomo(args=None):
    p = os.path.join(ROOT, "smart_money", "results", "fomo_leaderboard.md")
    if not os.path.exists(p): return "No Fomo leaderboard saved yet.", None
    rows = [r for r in ([x for x in l.split("|")[1:-1]] for l in open(p) if l.startswith("|") and not l.startswith("|---") and "Handle" not in l) if len(r) >= 8]
    boards = {}
    for r in rows: boards.setdefault(r[0].strip(), []).append(r)
    resolved = [r for r in rows if "not resolved" not in r[4]]
    L = [f"Fomo leaderboard (saved 20 Oct): {len(rows)} traders across {', '.join(boards)} boards."]
    for b, rs in boards.items(): L.append(f"• {b} top 5: " + ", ".join(x[2].strip() for x in rs[:5]))
    L.append(f"• Wallets found: {len({x[2] for x in resolved})} of {len({x[2] for x in rows})} traders" + (" (" + ", ".join(dict.fromkeys(f"{x[2].strip()}: {x[5].strip()}" for x in resolved)) + ")" if resolved else ""))
    L.append("Fomo hides wallets unless you log in, so most of these can't be scored or copied yet.")
    return "\n".join(L), None


# ---------- x callers ----------
def callers(args=None):
    cs = gate.load(os.path.join(ROOT, "x_calls", "callers.json"), [])
    return f"Tracking {len(cs)} X callers:\n" + "\n".join(f"• @{c['handle']}" + (" (wallet known)" if c.get("wallet") else "") for c in cs), None


def addcaller(args):
    if not args: return "How to use: /addcaller <X handle>", None
    rc, out, err = sh(XC, "add", args[0].lstrip("@"), timeout=60)
    return (f"Added @{args[0].lstrip('@')}. Their posts get read on the next X routine run." if rc == 0 else f"Couldn't add: {(err or out).strip()[-200:]}"), None


def calls(args=None):
    fs = sorted(f for f in glob.glob(os.path.join(ROOT, "x_calls", "results", "leaderboard_2*.md")))
    if not fs: return "No caller report saved yet.", None
    f = fs[-1]; t = datetime.fromtimestamp(os.path.getmtime(f), gate.LAGOS).strftime("%d %b %H:%M WAT")
    L = [f"X caller report (saved {t}). A 'hit' = 2x within 24h or +50% at 24h:"]
    for l in open(f):
        if not l.startswith("| @"): continue
        c = [x.strip() for x in l.split("|")[1:-1]]; n = c[1].split()[0]
        if n == "0": continue
        L.append(f"• {c[0]}: {c[1].replace('(', '(graded ').replace(')', ')')} calls, hit {c[2]}, 24h median {c[3].replace('None%', 'n/a')}, {c[5]} were risky tokens" + (f". {c[7]}" if c[7] else ""))
    empty = sum(1 for l in open(f) if l.startswith("| @") and l.split("|")[2].strip().startswith("0 "))
    if empty: L.append(f"{empty} callers have no calls graded yet.")
    return "\n".join(L), None


# ---------- paper ----------
def paper(args=None):
    sys.path.insert(0, os.path.join(ROOT, "paper_trade")); import paper_trade as P
    tr = gate.load(gate.TRADES, []); nick = " ".join(args) if args else None
    srcs = sorted({t["source"] for t in tr if not gate.is_test(t["source"].split(":", 1)[-1])})
    if nick: srcs = [s for s in srcs if s.split(":", 1)[-1].lower() == nick.lower()]
    if not srcs: return f"No paper trades for {nick}." if nick else "No paper trades yet.", None
    bar = P.CFG["bar"]
    L = [f"Paper trading ($100 fake bets). To pass, a source needs {bar['min_trades']}+ trades, {bar['min_win_rate']*100:.0f}%+ wins, real average profit and drops under {bar['max_drawdown_pct']}%."]
    for s in srcs:
        ts = [t for t in tr if t["source"] == s and not t.get("gated_out")]; x = P.stats(ts)
        name = s.split(":", 1)[-1]
        if not x["n"]: L.append(f"• {name}: no finished trades yet ({x['open']} open)"); continue
        v = {"PASS": "✅ passes", "FAIL": "❌ fails", "NOT ENOUGH TRADES": f"⏳ only {x['n']} of {bar['min_trades']} trades"}[x["verdict"]]
        lean = {"on track": ", on track so far", "failing so far": ", failing so far"}.get(x.get("lean"), "")
        L.append(f"• {name}: {x['n']} trades, {x['win_rate']*100:.0f}% wins, {'made' if x['pnl']>=0 else 'lost'} ${abs(x['pnl']):,.0f}, worst drop {x['max_dd']:.0f}%, {x['open']} open. {v}{lean}")
    k = [t for t in tr if t.get("gated_out") and t.get("status") == "closed"]
    if k and not nick: L.append(f"Tokens the safety check would have blocked: {len(k)} trades, lost ${-sum(t['pnl_usd'] for t in k):,.0f}. The check is helping.")
    return "\n".join(L), None


def papertrade(args):
    if not args: return "How to use: /papertrade <token address> [chain]", None
    rc, out, err = sh(PT, "open", args[0], "--source", "manual", *(["--chain", gate.norm_chain(args[1])] if len(args) > 1 else []), timeout=180)
    o = out.strip()
    if o.startswith("OPEN"): return f"Fake $100 trade opened: {o[5:]}\nIt gets tracked hourly (stop at -30%, take profit at +50% and +100%, max 3 days). See /paper manual.", None
    return f"😕 Didn't open it: {(err.strip().splitlines() or ['unknown reason'])[-1]}", None


def settings(args=None):
    c = gate.cfg()
    return ("Settings (edit tg_bot/config.json):\n"
            f"• Max size: ${c['size_cap_buy_usd']} on BUY, ${c['size_cap_careful_usd']} on CAREFUL\n"
            f"• Daily loss warning at ${c['daily_loss_limit_usd']} (just a reminder)\n"
            f"• Wallet with under {c['thin_data_trades']} paper trades = not enough data\n"
            f"• Instant dump = sold within {c['instant_dump_seconds']}s at {c['instant_dump_loss_pct']}%+ loss\n"
            f"• /scan once per {c['scan_cooldown_s']//60} min, /score {c['score_per_day']} per day\n"
            f"• Practice: ${c['practice_start_usd']:,} start, {c['practice_fee_pct']}% fees, other users max {c['public_rate_per_hour']} commands/hour"), None
