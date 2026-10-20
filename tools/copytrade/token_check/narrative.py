#!/usr/bin/env python3
"""Narrative helper. Gathers a token's story metadata (DexScreener profile + pair info, Rugcheck
metadata), extracts likely catalyst keywords, and builds the X / web search queries an agent should
run. The agent runs the searches (X tools are agent-side), then writes a grade JSON that
token_check.py can apply with --narrative-file.

  python narrative.py <address> [--chain solana] [--json]

Grade file format (narratives/<address>.json):
  {"grade": "CONFIRMED|UNCONFIRMED|CONTRADICTED|NONE", "catalyst": "...", "subject": "...",
   "reason": "...", "checked_at": "...", "sources": [{"url": "...", "note": "..."}],
   "timeline": [{"date": "...", "event": "..."}]}
"""
import argparse, json, os, re, sys, time
import requests

DS = "https://api.dexscreener.com"; RC = "https://api.rugcheck.xyz/v1/tokens"
UA = {"User-Agent": "token_check/1.0"}
GRADES = ("CONFIRMED", "UNCONFIRMED", "CONTRADICTED", "NONE")
STATUS_RE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]+)/status/(\d+)")
HANDLE_RE = re.compile(r"(?:x|twitter)\.com/([A-Za-z0-9_]+)/?(?:\?|$)")


def _get(url, timeout=15):
    try:
        r = requests.get(url, headers=UA, timeout=timeout)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def gather(addr, chain="solana"):
    meta = {"address": addr, "chain": chain, "name": None, "symbol": None, "description": None,
            "websites": [], "socials": [], "source_posts": [], "handles": [],
            "pair_created_utc": None, "sources": {}}
    pairs = _get(f"{DS}/tokens/v1/{chain}/{addr}")
    if isinstance(pairs, list) and pairs:
        meta["sources"]["dexscreener"] = "ok"
        mine = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == addr.lower()] or pairs
        born = [p["pairCreatedAt"] for p in mine if p.get("pairCreatedAt")]
        if born:
            meta["pair_created_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(min(born) / 1000))
        bt = mine[0].get("baseToken") or {}
        meta["name"], meta["symbol"] = bt.get("name"), bt.get("symbol")
        for p in mine:
            info = p.get("info") or {}
            for s in info.get("socials") or []:
                if s.get("url") and s not in meta["socials"]: meta["socials"].append(s)
            for w in info.get("websites") or []:
                if w.get("url") and w["url"] not in meta["websites"]: meta["websites"].append(w["url"])
    else:
        meta["sources"]["dexscreener"] = "failed/no pairs"
    prof = _get(f"{DS}/token-profiles/latest/v1")
    if isinstance(prof, list):
        for p in prof:
            if (p.get("tokenAddress") or "").lower() == addr.lower():
                meta["description"] = p.get("description")
                for l in p.get("links") or []:
                    if l.get("url") and l not in meta["socials"]: meta["socials"].append(l)
    if chain == "solana":
        rc = _get(f"{RC}/{addr}/report", 20)
        if rc:
            meta["sources"]["rugcheck"] = "ok"
            tm = rc.get("tokenMeta") or {}; fm = rc.get("fileMeta") or {}
            meta["name"] = meta["name"] or tm.get("name"); meta["symbol"] = meta["symbol"] or tm.get("symbol")
            meta["description"] = meta["description"] or fm.get("description")
            meta["metadata_uri"] = tm.get("uri"); meta["launchpad"] = rc.get("launchpad") or rc.get("deployPlatform")
            meta["creator"] = rc.get("creator")
        else:
            meta["sources"]["rugcheck"] = "failed"
    for s in meta["socials"]:
        u = s.get("url") or ""
        m = STATUS_RE.search(u)
        if m: meta["source_posts"].append({"handle": m.group(1), "post_id": m.group(2), "url": u})
        else:
            h = HANDLE_RE.search(u)
            if h: meta["handles"].append(h.group(1))
    return meta


def queries(meta):
    name = (meta.get("name") or "").replace(" Coin", "").strip() or meta.get("symbol") or ""
    sym = meta.get("symbol") or ""
    born = (meta.get("pair_created_utc") or "")[:10]
    q = {
        "x_get_posts_by_ids": [p["post_id"] for p in meta["source_posts"]],
        "x_get_users_by_username": sorted(set([p["handle"] for p in meta["source_posts"]] + meta["handles"])),
        "x_search_posts_all": [f'"{name}" -is:retweet', f'"${sym}" -is:retweet',
                               f'"{meta["address"]}"'] + ([f'"{name}" until:{born}'] if born else []),
        "x_search_news": sorted({name, f"{name} {sym}".strip()} if sym.lower() != name.lower() else {name}),
        "web_search": [f'"{name}" origin', f'"{name}" official announcement', f'"{name}" leak OR trailer OR announced'],
        "then": ["identify the claimed catalyst (game / film / celebrity / product / event) and its SUBJECT",
                 "find the subject's official/verified account and search from:<official> for the catalyst",
                 "check whether the source post is live, deleted or withheld (get_posts_by_ids error or "
                 "'withheld' field); a deleted or withheld leak gives UNCONFIRMED, not CONTRADICTED",
                 "compare dates: catalyst date vs pair_created_utc; a token created before the catalyst = front-run or insider",
                 "write narratives/<address>.json with grade + sources, then rerun token_check.py --narrative-file"],
    }
    return q


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); ap.add_argument("address"); ap.add_argument("--chain", default="solana")
    ap.add_argument("--json", action="store_true"); a = ap.parse_args()
    m = gather(a.address, a.chain); out = {"metadata": m, "queries": queries(m)}
    print(json.dumps(out, indent=2))
