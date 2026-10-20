# smart_money — find copyable, verifiably profitable wallets

```
python3 smart_money.py discover [--chain solana] [--days 7] [--limit 10] [--no-check]
python3 smart_money.py score <wallet> [--chain solana|ethereum|base|bsc|arbitrum|robinhood] [--days 30] [--label X] [--json]
python3 smart_money.py top [--limit 20] [--min-copyability 50]
python3 smart_money.py promote <wallet> --label X [--chain C]   # runs wallet_tracker add
```
Results go to `results/scores.json` (one entry per wallet, latest score) and `results/discover_<time>.json`. Settings are in `config.json`. The tool reuses `../wallet_tracker` for the swap parser, the Helius client and prices. It needs `HELIUS_API_KEY` for Solana. The key is never printed.

## Data sources (checked live on 20 Oct 2026)
- **Works:**
  - Helius `getTransactionsForAddress`, with filters `status=succeeded`, `tokenAccounts=balanceChanged`, `tokenTransfer.direction=out`. "out" cut spam from 98% to 0-17% of each page and still catches buys (SOL is wrapped and sent out).
  - DexScreener: boosts, profiles, community takeovers, tokens/v1 (pair creation time and prices).
  - kolexplorer.com and kolscan.io leaderboards (HTML).
  - Coinbase 1-minute SOL-USD candles (USD at fill).
  - token_check.
- **pump.fun (keyless, used by discover):**
  - `frontend-api-v3.pump.fun/coins?sort=market_cap&order=DESC&limit=50`: graduated coins under 7 days old, kept only if DexScreener shows at least $40k liquidity (pump.fun market caps can be wash-inflated).
  - `frontend-api-v3.pump.fun/coins/top-holders/<mint>`: wallets flagged isDev/isSniper/isBundler are dropped, and entry [0] (the pool) is skipped.
  - `swap-api.pump.fun/v2/coins/<mint>/trades?limit=100&cursor=…`: 3 pages; the top net sellers become candidates.
  - It rate-limits hard: use plain requests with 1 s spacing and back off on 429.
  - `king-of-the-hill` and `advanced-api-v2` returned 404 and 530.
- **fomo.family:** the app calls `prod-api.fomo.family/v2/leaderboard/{24h|7d|30d}`, but it returns HTTP 431 `unauthorized` without a login. The code tries it and skips it cleanly.
- **Blocked or needs a key:** GMGN (Cloudflare), Birdeye top traders (401 without a key). Cielo was not tried.

## Metrics (per wallet, last `days`=30)
- Realized PnL: per token, sells minus cost × (sold qty / bought qty). Only tokens both bought and sold inside the window count. USD is at fill.
- Also: win rate over closed positions, swaps and swaps/day, median and average hold (first buy → first sell), median buy size and its spread.
- `kill_pct_sampled`: token_check run on the 6 biggest tokens bought.
- Entry timing: median seconds from the earliest DexScreener pair creation to the buy.
- Flags:
  - Bot volume: more than 150 swaps/day.
  - Scalper: median hold under 60 s.
  - Sniper: 30% or more of buys within 10 s of the pair.
  - Same-second bundled buys.
  - Pre-pair entries: usually a pump.fun bonding-curve buy; could be an insider.
  - Rug-chaser: 50% or more KILL.
  - Small sample or truncated history.
- **copyability** (0-100): penalties for short holds, high trade rate, sniping, bundling, erratic sizing, and mostly pre-pair entries.
- **rank_score** = (log-PnL + 0.4 × win rate) × sample factor × copyability × (1 − 0.5 × KILL share).

## Discovery
1. Find runner tokens: Solana tokens in DexScreener boosts, profiles and takeovers with a pair younger than 7 days and liquidity of at least $40k. Ranked by FDV; top 8.
2. Take the first 100 successful txs on each mint (Helius, asc). The first 6 buying signers per token become candidates.
3. Add a sample from the leaderboards.
4. Score up to 24 wallets.

## Cost and limits
- Helius: 10 credits per call of ≤100 txs.
- `score`: up to 10 pages, about 50-100 credits.
- `discover`: about 1,700 credits with the defaults (24 wallets).
- Very active wallets hit the page cap, so they get scored on less than the full 30 days ("history truncated").
- **Not checked yet:** funding by the token creator. Rugcheck creator vs the wallet's first funder would be the next step.
- EVM `score` uses wallet_tracker's sources (deep on Ethereum, shallow elsewhere) with *current* DexScreener prices. EVM `discover` is not built.
