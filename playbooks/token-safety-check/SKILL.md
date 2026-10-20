---
name: Token safety check
description: >-
  Use before alerting on, copying, or recommending any crypto token (Solana, EVM
  chains, Base, Robinhood Chain), to get a PASS/WARN/KILL rug-risk verdict,
  score, and narrative grade.
---
# Token safety check

Tool lives at `tools/copytrade/token_check/` (see its README.md). Free sources only: DexScreener, Rugcheck (Solana), GoPlus (EVM incl. Robinhood Chain id 4663).

## Steps
1. Run `python tools/copytrade/token_check/token_check.py <address> [--chain solana|ethereum|base|bsc|arbitrum|robinhood|...] --json`. Chain auto-detects if omitted. Exit codes: 0 PASS, 1 WARN, 2 KILL, 3 error.
2. Narrative (on by default for Solana, `--narrative` elsewhere): if the result shows PENDING, run `narrative.py` to get metadata and search queries, then search X (built-in x namespace: search_posts_all, get_posts_by_ids, search_news) and the web. Identify the catalyst, check official/verified confirmation, whether source posts are deleted, and timing vs token creation. Grade CONFIRMED / UNCONFIRMED / CONTRADICTED / NONE with source links, save to `narratives/<address>.json` per README, rerun step 1.
3. Report: verdict, score, the failed/warned checks in plain English, narrative grade with sources. A deleted leak = UNCONFIRMED, never FAKE. Narrative never kills on its own.

## Rules (all thresholds in config.json)
- Top-10 holders: established tokens (pair >=24h and >=$500k total liquidity across all pools) WARN above 40%; new/thin/unknown-age tokens KILL above 35%. Exchange wallets aren't labelled by the sources, so note that on big tokens.
- Hard kills: honeypot, live mint/freeze authority, sell tax >10%, deepest pool <$30k, Rugcheck danger risks, unlocked LP with <$100k liquidity, buys with zero sells.
- A failed data source is 'unknown', never a pass.
- Never present unverified profit claims as fact; this is risk screening, not financial advice.
