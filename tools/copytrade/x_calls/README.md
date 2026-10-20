# x_calls — grade X accounts' token calls against real price action

```
python3 x_calls.py add <handle> [--user-id N] [--wallet ADDR [--wallet-chain solana]] [--tag kol]
python3 x_calls.py list            # handle, user id, since_id, wallet
python3 x_calls.py ingest          # parse inbox/*.json → calls.json (moves files to inbox/processed/)
python3 x_calls.py grade           # GeckoTerminal OHLCV outcomes for every call not yet final; self-buy check
python3 x_calls.py report [handle] # leaderboard (also saved to results/leaderboard_<time>.md) or one caller's calls
```

## Routine procedure (the X reads happen on the agent side)
X budget: 30 reads/min and 1,000/day, shared with other bots; at most 25 posts per call.
1. `python3 x_calls.py list`. For each caller, take `user_id` and `since_id` (`-` = first run).
   - If `user_id` is missing, resolve up to 100 handles in one `x.get_users_by_usernames` call and re-add them with `--user-id`.
2. For each caller, call `x.get_users_posts` with:
   - `id=<user_id>`, `max_results=25`, `exclude=retweets`
   - `post.fields=created_at,public_metrics,entities,author_id`
   - `since_id=<since_id>` when known
   Write the raw JSON to `inbox/<handle>_<YYYYmmdd_HHMM>.json` and add a top-level `"_handle": "<handle>"`. Skip callers with no new posts (`meta.result_count==0`).
   Search results can also be dropped in the inbox (with `expansions=author_id`). Their authors become callers automatically.
3. Run `python3 x_calls.py ingest`, then `grade`, then `report`.
4. Run `grade` again later: calls stay `PENDING` until 24 h have passed, and 7-day numbers fill in as time passes.

Each run costs 1 X call per caller, plus 1 if any user ids are missing.

## Parsing
- **A call** is any of these in the post text or expanded URLs:
  - A dexscreener, pump.fun, gmgn or birdeye token link.
  - An EVM `0x…` address.
  - A Solana base58 string of 32-44 chars with mixed case and a digit.
  - A `$TICKER`.
- Addresses are kept only if DexScreener knows the token. Its best-liquidity pair gives the chain and pool.
- **Tickers** are resolved with DexScreener search only when one token named that holds at least 90% of matching liquidity and at least $10k. Otherwise the call is `unresolved` with the reason. Majors in `ignore_tickers` are skipped.
- A token whose pair was created more than 1 h after the post is `unresolved` (probably a same-name coin).
- **token_check** runs (`--no-narrative`) on each new resolved call.

## Grading (GeckoTerminal, free, about 30 req/min; 3 s spacing)
- Data: hourly OHLCV for the pool from the call to +7 d.
- Price at call: the close of the last candle before the post.
- FDV at call: current FDV × (price at call / current price).
- Measured: return at +1 h / +24 h / +7 d, peak multiple in the first 24 h and 7 d (candle highs), and the 7-day low.
- Labels:
  - `WIN`: 24 h peak ≥ 2x, or +24 h ≥ +50%.
  - `LOSS`: +24 h ≤ −50%, or a KILL token that dropped ≥ 80%.
  - `FLAT`: otherwise.
  - `PENDING`: under 24 h old and not yet a 2x.
- Thresholds are in `config.json`.
- **Self-buy check:** for callers with a Solana `wallet`, one Helius call (≈10 credits) reads the wallet's swaps ±72 h around the call. Flags: "bought before posting", "bought before posting, sold into followers", "bought after posting" or "no buy seen".
- **Per caller:** calls (graded), hit rate, median 24 h return, average 7-day peak, KILL %, unresolved count, flags. Flags: dumped on followers, front-runs own calls, mostly KILL tokens, small sample.

## Limits
- Hourly candles blur the price at call (±1 h) and the 1 h return.
- Very new pools may have no candles yet (`ungradable`).
- GeckoTerminal sometimes returns 429. Failed calls are retried on the next `grade`.
- Ticker-only calls are often ambiguous on Solana, which is why the `unresolved` counts are high.

## Setup

Copy config.example.json to config.json and set your own values. The example numbers are generic placeholders, not tuned settings.
