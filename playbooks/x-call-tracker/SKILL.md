---
name: X call tracker
description: >-
  Use when tracking or grading crypto token calls posted by X accounts, adding
  callers, or ranking which callers are worth following.
---
# X call tracker

Tool: `tools/copytrade/x_calls/x_calls.py` (README.md has the full procedure). X reads are agent-side through the built-in public X tools; keep usage frugal (shared daily limit).

## Steps
1. Add callers: `python3 x_calls.py add <handle> [--wallet <addr>]`; `list` shows them.
2. Fetch each caller's new posts since the saved since_id with the X tools and save the raw JSON into `x_calls/inbox/` as the README describes.
3. `python3 x_calls.py ingest` to extract calls (contract addresses, cashtags, DEX links) and run the token safety check on each.
4. `python3 x_calls.py grade` to update outcomes (+1h, +24h, +7d, peak multiple) for calls old enough.
5. `python3 x_calls.py report [handle]` for the leaderboard: calls, hit rate, median 24h return, avg peak, KILL %, and front-running flags when a caller's wallet is known.

## Notes
- Ticker-only calls stay unresolved unless one token clearly dominates; don't guess.
- Small samples aren't a track record; say so.
- Engagement-farming shill accounts are common; judge by graded results, not followers.
