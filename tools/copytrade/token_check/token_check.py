#!/usr/bin/env python3
"""Multi-chain token safety checker (rug filter). Free, no-key sources only:
DexScreener (all chains), Rugcheck (Solana), GoPlus (EVM).
Usage: python token_check.py <address> [--chain CHAIN] [--json] [--config PATH]
Exit code: 0 PASS, 1 WARN, 2 KILL, 3 error."""
import argparse, json, os, re, sys, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "token_check/1.0", "Accept": "application/json"}
DS = "https://api.dexscreener.com"
RC = "https://api.rugcheck.xyz/v1/tokens"
GP = "https://api.gopluslabs.io/api/v1/token_security"
B58 = re.compile(r"^[1-9A-HJ-NP-Za-km-z]{32,44}$")
EVM = re.compile(r"^0x[0-9a-fA-F]{40}$")


class SourceError(Exception):
    pass


def get_json(url, cfg):
    h = cfg["http"]; last = None
    for i in range(h["retries"]):
        try:
            r = requests.get(url, headers=UA, timeout=h["timeout_s"])
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}"
                time.sleep(h["backoff_s"] * (i + 1)); continue
            if r.status_code != 200:
                raise SourceError(f"HTTP {r.status_code}")
            return r.json()
        except (requests.RequestException, ValueError) as e:
            last = type(e).__name__
            time.sleep(h["backoff_s"] * (i + 1))
    raise SourceError(last or "failed")


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ---------------- sources ----------------
def dexscreener_pairs(chain, addr, cfg):
    # token-pairs/v1 returns every pair (up to 30); tokens/v1 returns only one per token
    try:
        d = get_json(f"{DS}/token-pairs/v1/{chain}/{addr}", cfg)
        d = d if isinstance(d, list) else (d.get("pairs") or [])
        if d: return d
    except SourceError:
        pass
    d = get_json(f"{DS}/tokens/v1/{chain}/{addr}", cfg)
    return d if isinstance(d, list) else (d.get("pairs") or [])


def detect_chain(addr, cfg):
    if EVM.match(addr):
        d = get_json(f"{DS}/latest/dex/tokens/{addr}", cfg)
        pairs = [p for p in (d.get("pairs") or [])
                 if (p.get("baseToken") or {}).get("address", "").lower() == addr.lower()] or (d.get("pairs") or [])
        if not pairs:
            raise SourceError("no DexScreener pairs found for this 0x address; pass --chain")
        best = max(pairs, key=lambda p: (p.get("liquidity") or {}).get("usd") or 0)
        return best["chainId"]
    if B58.match(addr):
        return "solana"
    raise SourceError("unrecognised address format; pass --chain")


def market(chain, addr, cfg):
    pairs = dexscreener_pairs(chain, addr, cfg)
    mine = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == addr.lower()]
    quote_side = not mine
    pairs = mine or pairs
    if not pairs:
        return None
    p = max(pairs, key=lambda x: (x.get("liquidity") or {}).get("usd") or 0)
    tx = p.get("txns") or {}; h1 = tx.get("h1") or {}; h24 = tx.get("h24") or {}
    born = p.get("pairCreatedAt")
    tok = p.get("quoteToken") if quote_side else p.get("baseToken")
    return {
        "symbol": (tok or {}).get("symbol"), "name": (tok or {}).get("name"),
        "dex": p.get("dexId"), "pair": p.get("pairAddress"), "url": p.get("url"),
        "price_usd": f(p.get("priceUsd")) if not quote_side else None,
        "liq_usd": (p.get("liquidity") or {}).get("usd"),
        "fdv": p.get("fdv"), "mcap": p.get("marketCap"),
        "vol_1h": (p.get("volume") or {}).get("h1"), "vol_24h": (p.get("volume") or {}).get("h24"),
        "buys_1h": h1.get("buys"), "sells_1h": h1.get("sells"),
        "buys_24h": h24.get("buys"), "sells_24h": h24.get("sells"),
        "age_min": round((time.time() * 1000 - born) / 60000) if born else None,
        "has_profile": bool(p.get("info")), "pairs_count": len(pairs),
        "total_liq_usd": round(sum((x.get("liquidity") or {}).get("usd") or 0 for x in pairs), 2),
        "info": p.get("info") or {},
        "token_is_quote": quote_side,
    }


def rugcheck(addr, cfg):
    d = get_json(f"{RC}/{addr}/report", cfg)
    token = d.get("token") or {}; known = d.get("knownAccounts") or {}

    def is_pool(h):
        tag = known.get(h.get("owner")) or known.get(h.get("address")) or {}
        return str(tag.get("type", "")).upper() in ("AMM", "LOCKER")
    holders = [h for h in (d.get("topHolders") or []) if not is_pool(h)]
    mk = sorted(d.get("markets") or [], key=lambda m: ((m.get("lp") or {}).get("baseUSD") or 0)
                + ((m.get("lp") or {}).get("quoteUSD") or 0), reverse=True)
    lp = (mk[0].get("lp") or {}) if mk else {}
    supply = token.get("supply") or 0
    risks = d.get("risks") or []
    return {
        "symbol": (d.get("tokenMeta") or {}).get("symbol"),
        "rugged": bool(d.get("rugged")),
        "risk_score": d.get("score_normalised"),
        "danger": [x.get("name") for x in risks if x.get("level") == "danger"],
        "warn": [x.get("name") for x in risks if x.get("level") == "warn"],
        "mint_authority": token.get("mintAuthority", d.get("mintAuthority")),
        "freeze_authority": token.get("freezeAuthority", d.get("freezeAuthority")),
        "lp_locked_pct": lp.get("lpLockedPct", d.get("lpLockedPct")) if mk else None,
        "top10_pct": round(sum(h.get("pct") or 0 for h in holders[:10]), 2) if holders else None,
        "dev_pct": round((d.get("creatorBalance") or 0) / supply * 100, 2) if supply else None,
        "insiders": sum(1 for h in holders if h.get("insider")),
        "graph_insiders": d.get("graphInsidersDetected") or 0,
        "holders": d.get("totalHolders"),
    }


def goplus(chain, addr, cfg):
    cid = cfg["goplus_chain_ids"].get(chain)
    if not cid:
        raise SourceError(f"GoPlus has no chain id mapped for '{chain}'")
    d = get_json(f"{GP}/{cid}?contract_addresses={addr}", cfg)
    if d.get("code") not in (1, 3):  # 3 = partial data
        raise SourceError(f"GoPlus code {d.get('code')}: {d.get('message')}")
    res = (d.get("result") or {}).get(addr.lower())
    if not res:
        raise SourceError("GoPlus returned no data for this token")
    b = lambda k: None if res.get(k) in (None, "") else res.get(k) == "1"
    pools = {(x.get("pair") or "").lower() for x in res.get("dex") or []} | \
            {(x.get("pool_manager") or "").lower() for x in res.get("dex") or []} | \
            set(cfg.get("exclude_holders", {}).get("all", []))
    holders = [h for h in (res.get("holders") or []) if (h.get("address") or "").lower() not in pools]
    lp_h = res.get("lp_holders") or []
    burn = {"0x" + "0" * 36 + "dead", "0x" + "0" * 40}  # burn addresses
    lp_locked = sum((f(h.get("percent")) or 0) for h in lp_h
                    if h.get("is_locked") == 1 or (h.get("address") or "").lower() in burn) * 100 if lp_h else None
    owner = (res.get("owner_address") or "").lower()
    renounced = (owner in burn) if res.get("owner_address") is not None else None
    return {
        "_partial": d.get("code") == 3,
        "symbol": res.get("token_symbol"),
        "honeypot": b("is_honeypot"), "cannot_sell_all": b("cannot_sell_all"), "cannot_buy": b("cannot_buy"),
        "buy_tax": None if f(res.get("buy_tax")) is None else f(res.get("buy_tax")) * 100,
        "sell_tax": None if f(res.get("sell_tax")) is None else f(res.get("sell_tax")) * 100,
        "mintable": b("is_mintable"), "proxy": b("is_proxy"), "blacklist": b("is_blacklisted"),
        "open_source": b("is_open_source"), "owner_renounced": renounced,
        "owner_powers": [k for k in ("hidden_owner", "can_take_back_ownership", "owner_change_balance",
                                     "selfdestruct", "transfer_pausable", "slippage_modifiable") if res.get(k) == "1"],
        "top10_pct": round(sum((f(h.get("percent")) or 0) for h in holders[:10]
                               if not h.get("is_locked")) * 100, 2) if holders else None,
        "dev_pct": f(res.get("creator_percent")) * 100 if f(res.get("creator_percent")) is not None else None,
        "lp_locked_pct": round(lp_locked, 2) if lp_locked is not None else None,
        "in_cex": (res.get("is_in_cex") or {}).get("listed") == "1",
        "holders": res.get("holder_count"),
    }


# ---------------- checks ----------------
def run(addr, chain, cfg):
    T = cfg["thresholds"]; results = []; sources = {}
    def add(name, status, reason):  # status: pass / fail / unknown / info
        results.append({"check": name, "status": status, "reason": reason})

    m = sec = None
    try:
        m = market(chain, addr, cfg); sources["dexscreener"] = "ok" if m else "no pairs"
    except SourceError as e:
        sources["dexscreener"] = f"failed: {e}"
    if chain == "solana":
        try:
            sec = rugcheck(addr, cfg); sources["rugcheck"] = "ok"
        except SourceError as e:
            sources["rugcheck"] = f"failed: {e}"
    else:
        try:
            sec = goplus(chain, addr, cfg); sources["goplus"] = "ok" + (" (partial)" if sec.pop("_partial", False) else "")
        except SourceError as e:
            sources["goplus"] = f"failed: {e}"
    U = lambda src: f"{src} unavailable"
    secname = "Rugcheck" if chain == "solana" else "GoPlus"

    if chain == "solana":
        if not sec:
            for c in ("rugged", "mint_authority", "freeze_authority", "danger_flags", "risk_score"):
                add(c, "unknown", U(secname))
        else:
            add("rugged", "fail" if sec["rugged"] else "pass", "Rugcheck marks it rugged" if sec["rugged"] else "not flagged as rugged")
            add("mint_authority", "fail" if sec["mint_authority"] else "pass",
                "mint authority still live: dev can print supply" if sec["mint_authority"] else "mint authority revoked")
            add("freeze_authority", "fail" if sec["freeze_authority"] else "pass",
                "freeze authority live: dev can freeze your tokens" if sec["freeze_authority"] else "freeze authority revoked")
            add("danger_flags", "fail" if sec["danger"] else "pass",
                "danger risks: " + ", ".join(sec["danger"]) if sec["danger"] else
                "no danger-level risks" + (f" (warn: {', '.join(sec['warn'])})" if sec["warn"] else ""))
            rs = sec["risk_score"]
            add("risk_score", "unknown" if rs is None else ("fail" if rs > T["max_risk_score"] else "pass"),
                "no risk score" if rs is None else f"Rugcheck risk {rs}/100 (max {T['max_risk_score']})")
    else:
        if not sec:
            for c in ("honeypot", "sell_tax", "buy_tax", "owner_can_mint", "proxy", "blacklist", "owner_powers", "open_source"):
                add(c, "unknown", U(secname))
        else:
            hp = sec["honeypot"]; csa = sec["cannot_sell_all"]
            add("honeypot", "unknown" if hp is None else ("fail" if hp or csa or sec["cannot_buy"] else "pass"),
                "GoPlus gave no honeypot result" if hp is None else
                ("honeypot / cannot sell flagged" if hp or csa else ("cannot buy" if sec["cannot_buy"] else "buy and sell simulate OK")))
            for nm, key, lim in (("sell_tax", "sell_tax", T["max_sell_tax_pct"]), ("buy_tax", "buy_tax", T["max_buy_tax_pct"])):
                v = sec[key]
                if v is None: add(nm, "unknown", f"{nm.replace('_', ' ')} not reported")
                else:
                    st = "fail" if v > lim else ("warn" if v > T["warn_tax_pct"] else "pass")
                    add(nm, st, f"{nm.replace('_', ' ')} {v:.1f}% (max {lim}%)")
            mt = sec["mintable"]
            if mt is None: add("owner_can_mint", "unknown", "mintability not reported")
            elif mt and not sec["owner_renounced"]: add("owner_can_mint", "fail", "contract is mintable and owner is not renounced")
            else: add("owner_can_mint", "pass", "not mintable" if not mt else "mint function exists but ownership renounced")
            add("proxy", "unknown" if sec["proxy"] is None else ("fail" if sec["proxy"] else "pass"),
                "proxy not reported" if sec["proxy"] is None else
                ("upgradeable proxy: logic can be swapped" if sec["proxy"] else "not a proxy"))
            add("blacklist", "unknown" if sec["blacklist"] is None else ("fail" if sec["blacklist"] else "pass"),
                "blacklist not reported" if sec["blacklist"] is None else
                ("contract has a blacklist function" if sec["blacklist"] else "no blacklist"))
            pw = sec["owner_powers"]
            if sec["owner_renounced"] is None and not pw:
                add("owner_powers", "unknown", "owner not reported")
            else: add("owner_powers", "fail" if pw and not sec["owner_renounced"] else "pass",
                ("owner powers: " + ", ".join(pw)) if pw and not sec["owner_renounced"] else
                ("ownership renounced" if sec["owner_renounced"] else "no dangerous owner powers"))
            os_ = sec["open_source"]
            add("open_source", "unknown" if os_ is None else ("pass" if os_ else "fail"),
                "not reported" if os_ is None else ("source verified" if os_ else "contract source not verified"))

    # holders / LP / dev (both chains)
    if not sec:
        for c in ("lp_lock", "top10_holders", "dev_wallet") + (("insiders",) if chain == "solana" else ()):
            add(c, "unknown", U(secname))
    else:
        lpp = sec["lp_locked_pct"]; liq = (m or {}).get("liq_usd")
        if lpp is None: add("lp_lock", "unknown", "LP lock not reported")
        else: add("lp_lock", "fail" if lpp < T["min_lp_locked_pct"] else "pass",
                  f"biggest pool LP {lpp:.1f}% locked/burned (min {T['min_lp_locked_pct']}%)")
        if lpp is not None and liq is not None:
            bad = lpp < T["min_lp_locked_pct"] and liq < T["tiny_liquidity_usd"]
            add("lp_unlocked_tiny", "fail" if bad else "pass",
                f"LP unlocked AND liquidity only ${liq:,.0f} (< ${T['tiny_liquidity_usd']:,})" if bad else "not (unlocked LP + tiny pool)")
        else:
            add("lp_unlocked_tiny", "unknown", "need both LP lock and liquidity")
        t10 = sec["top10_pct"]
        age = (m or {}).get("age_min"); liq_e = (m or {}).get("total_liq_usd")
        est = age is not None and age >= T["new_pair_hours"] * 60 and \
              liq_e is not None and liq_e >= T["established_min_liquidity_usd"]
        lim = T["max_top10_pct"] if est else T["max_top10_pct_new"]
        tier = "established pair, WARN" if est else "new/thin/unknown-age pair, KILL"
        add("top10_holders", "unknown" if t10 is None else ("fail" if t10 > lim else "pass"),
            "top holders not reported" if t10 is None else f"top 10 holders own {t10:.1f}% (max {lim}% for {tier}; total liq ${(liq_e or 0):,.0f}; pools/lockers excluded)")
        if est: results[-1]["severity_override"] = "warn"
        dv = sec["dev_pct"]
        add("dev_wallet", "unknown" if dv is None else ("fail" if dv > T["max_dev_pct"] else "pass"),
            "creator balance not reported" if dv is None else f"creator holds {dv:.2f}% (max {T['max_dev_pct']}%)")
        if chain == "solana":
            ins = sec["insiders"]
            add("insiders", "fail" if ins > T["max_insiders"] else "pass",
                f"{ins} insider-flagged top holders (max {T['max_insiders']}); insider-graph wallets: {sec['graph_insiders']}")

    # market checks
    mk = ("liquidity", "ticket_share", "pair_age", "sells_exist", "volume", "fdv_liquidity", "profile")
    if not m:
        for c in mk: add(c, "unknown" if sources.get("dexscreener", "").startswith("failed") else "fail",
                         U("DexScreener") if sources.get("dexscreener", "").startswith("failed") else "no DEX pool found")
    else:
        liq = m["liq_usd"]
        if liq is None: add("liquidity", "unknown", "no liquidity figure"); add("ticket_share", "unknown", "no liquidity figure")
        else:
            add("liquidity", "fail" if liq < T["min_liquidity_usd"] else "pass", f"deepest pool ${liq:,.0f} (min ${T['min_liquidity_usd']:,})")
            sh = cfg["ticket_usd"] / liq if liq else 1
            add("ticket_share", "fail" if sh > T["max_ticket_share"] else "pass",
                f"${cfg['ticket_usd']} ticket = {sh*100:.3f}% of pool (max {T['max_ticket_share']*100:.1f}%)")
        a = m["age_min"]
        if a is None: add("pair_age", "unknown", "pair age unknown")
        else:
            human = f"{a} min" if a < 120 else (f"{a/60:.1f} h" if a < 2880 else f"{a/1440:.0f} days")
            too_old = T["max_age_hours"] is not None and a > T["max_age_hours"] * 60
            add("pair_age", "fail" if a < T["min_age_min"] or too_old else "pass",
                f"pair age {human} (min {T['min_age_min']} min" + (f", max {T['max_age_hours']} h)" if T["max_age_hours"] else ")"))
        b, s = m["buys_1h"], m["sells_1h"]
        if b is None or s is None: add("sells_exist", "unknown", "no 1h txn counts")
        else: add("sells_exist", "fail" if b >= T["honeypot_min_buys_1h"] and s == 0 else "pass",
                  f"1h: {b} buys / {s} sells" + (" -> honeypot shape" if b >= T["honeypot_min_buys_1h"] and s == 0 else ""))
        v = m["vol_24h"]
        add("volume", "unknown" if v is None else ("fail" if v < T["min_volume_24h_usd"] else "pass"),
            "no volume" if v is None else f"24h volume ${v:,.0f} (min ${T['min_volume_24h_usd']:,})")
        if m["fdv"] and liq:
            r = m["fdv"] / liq
            add("fdv_liquidity", "fail" if r > T["max_fdv_liq_ratio"] else "pass", f"FDV ${m['fdv']:,.0f} = {r:.0f}x liquidity (max {T['max_fdv_liq_ratio']}x)")
        else: add("fdv_liquidity", "unknown", "FDV or liquidity missing")
        add("profile", "pass" if m["has_profile"] else "fail",
            "DexScreener profile/socials present" if m["has_profile"] else "no DexScreener profile/socials")

    narrative = None
    if cfg.get("_narrative_on"):
        narrative = narrative_section(addr, chain, cfg)
    # scoring & verdict
    C = cfg["checks"]; score = 100.0; kills, warns, unknowns = [], [], []
    for r in results:
        c = dict(C.get(r["check"], {"severity": "warn", "weight": 5}))
        c["severity"] = r.pop("severity_override", c["severity"]); r["severity"] = c["severity"]
        if r["status"] == "fail":
            score -= c["weight"]
            (kills if c["severity"] == "kill" else warns).append(r)
        elif r["status"] == "warn":
            score -= c["weight"] / 2; warns.append(r)
        elif r["status"] == "unknown":
            score -= c["weight"] / 2; unknowns.append(r)
    nadj = 0
    if narrative and narrative.get("grade") in cfg["narrative"]["score_effect"]:
        nadj = cfg["narrative"]["score_effect"][narrative["grade"]]; narrative["score_effect"] = nadj
    score = max(0, min(100, round(score + nadj)))
    if kills: verdict = "KILL"
    elif warns or (unknowns and cfg["verdict"]["unknown_is_warn"]) or score < cfg["verdict"]["pass_min_score"]: verdict = "WARN"
    else: verdict = "PASS"
    if verdict == "PASS" and narrative and narrative.get("grade") == "CONTRADICTED":
        verdict = "WARN"  # narrative never KILLs alone, but a contradicted story is never a clean PASS
    if kills: summary = "; ".join(k["reason"] for k in kills[:3])
    elif warns or unknowns: summary = "; ".join(x["reason"] for x in (warns + unknowns)[:3])
    else: summary = "all checks passed"
    return {"address": addr, "chain": chain, "symbol": (m or {}).get("symbol") or (sec or {}).get("symbol"),
            "verdict": verdict, "score": score, "summary": summary,
            "kills": [k["check"] for k in kills], "warnings": [w["check"] for w in warns],
            "unknown": [u["check"] for u in unknowns], "checks": results, "sources": sources,
            "market": m, "security": sec, "narrative": narrative, "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}


def narrative_section(addr, chain, cfg):
    sys.path.insert(0, HERE)
    import narrative as N
    path = cfg.get("_narrative_file") or os.path.join(HERE, cfg["narrative"]["dir"], f"{addr}.json")
    meta = N.gather(addr, chain)
    out = {"name": meta.get("name"), "symbol": meta.get("symbol"), "description": meta.get("description"),
           "source_posts": meta.get("source_posts"), "pair_created_utc": meta.get("pair_created_utc"),
           "grade": "PENDING", "reason": f"no grade file yet: run the procedure in README, save {os.path.relpath(path, HERE)}",
           "queries": N.queries(meta)}
    if os.path.exists(path):
        g = json.load(open(path))
        if g.get("grade") in N.GRADES:
            out.update({k: g.get(k) for k in ("grade", "catalyst", "subject", "reason", "sources", "timeline", "checked_at")})
            out.pop("queries", None); out["grade_file"] = os.path.relpath(path, HERE)
    return out


def render(r):
    icon = {"pass": "OK  ", "fail": "FAIL", "warn": "WARN", "unknown": "??  ", "info": "info"}
    out = [f"{r['symbol'] or '?'} on {r['chain']}  {r['address']}",
           f"VERDICT: {r['verdict']}   score {r['score']}/100   -- {r['summary']}", ""]
    for c in r["checks"]:
        tag = "" if c["status"] == "pass" else (" [hard]" if c["severity"] == "kill" and c["status"] == "fail" else "")
        out.append(f"  {icon[c['status']]} {c['check']:<17} {c['reason']}{tag}")
    n = r.get("narrative")
    if n:
        out += ["", f"NARRATIVE: {n['grade']}  ({n.get('catalyst') or 'catalyst not graded yet'})"
                + (f"  score {n['score_effect']:+d}" if n.get("score_effect") else ""),
                f"  {n.get('reason')}"]
        for src in (n.get("sources") or [])[:6]:
            out.append(f"  - {src.get('url')}  {src.get('note', '')}")
        if n["grade"] == "PENDING":
            out.append("  queries: " + "; ".join(n["queries"]["x_search_posts_all"][:3]))
    out.append(""); out.append("sources: " + ", ".join(f"{k}={v}" for k, v in r["sources"].items()))
    if r.get("market") and r["market"].get("url"): out.append("pool: " + r["market"]["url"])
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="Multi-chain token rug filter")
    ap.add_argument("address"); ap.add_argument("--chain", help="solana|ethereum|base|bsc|arbitrum|... (auto if omitted)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--narrative", dest="narrative", action="store_true", default=None, help="add narrative section (default on for solana)")
    ap.add_argument("--no-narrative", dest="narrative", action="store_false")
    ap.add_argument("--narrative-file", help="grade JSON to apply (default narratives/<address>.json)"); ap.add_argument("--config", default=os.path.join(HERE, "config.json"))
    a = ap.parse_args()
    cfg = json.load(open(a.config)); addr = a.address.strip()
    try:
        chain = (a.chain or detect_chain(addr, cfg)).lower()
        if EVM.match(addr): addr = addr.lower() if chain != "solana" else addr
        cfg["_narrative_on"] = a.narrative if a.narrative is not None else (chain == "solana")
        cfg["_narrative_file"] = a.narrative_file
        r = run(addr, chain, cfg)
    except SourceError as e:
        err = {"address": addr, "verdict": "UNKNOWN", "score": None, "error": str(e)}
        print(json.dumps(err) if a.json else f"error: {e}"); sys.exit(3)
    print(json.dumps(r, indent=2, default=str) if a.json else render(r))
    sys.exit({"PASS": 0, "WARN": 1, "KILL": 2}[r["verdict"]])


if __name__ == "__main__":
    main()
