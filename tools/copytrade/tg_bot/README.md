# Netro Signal: your Telegram trade gate (tool #6)

Netro Signal (@netrosignal_bot) checks a token and the wallet that bought it, then answers **BUY**, **CAREFUL** or **SKIP**, with 2-3 reasons in plain words and a max size. It **never holds keys, never signs, never trades**. The buttons only open Jupiter, Phantom or DexScreener. You press buy in your own wallet.

## Start / stop
```
./start.sh      # runs "python3 bot.py run" in the background with nohup, logs to bot.log, pid in bot.pid
./stop.sh
```
It needs `TELEGRAM_BOT_TOKEN` in the environment. Without it, it exits with a clear message. The token is never printed or logged.

**Owner lock:** the first person to send `/start` becomes the owner, and their chat id is saved in `config.json` (`owner_chat_id`). Everyone else is ignored. To reset the owner, set it back to `null`.

## Owner commands (only you)
- `/check <token> [chain]`: BUY/CAREFUL/SKIP card with buttons and the story (narrative) grade
- `/safety <token> [chain]`: every safety check, pass/fail, in words
- `/watch <address> <nickname> [chain]`, `/unwatch <nickname>`, `/wallets` (test-* hidden)
- `/scan`: scan watched wallets now. It saves to `paper_trade/last_scan.json`, sends cards for new buys and practice copy fills. Once per 10 min.
- `/score <wallet> [chain]`: smart_money score in words (10 per day; Solana uses Helius credits)
- `/smartmoney`: top scored wallets. `/fomo`: Fomo leaderboard summary
- `/callers`, `/addcaller <handle>`, `/calls`: X callers and their latest saved report
- `/paper [nickname]`: fake-trade results against the 40-trade bar. `/papertrade <token> [chain]`: open a fake $100 trade
- `/loss <usd>`: log a real loss (daily-limit warning only). `/settings`, `/help`

## Practice mode (anyone, fake money)
`/practice` (fake $1,000), `/buy <token> <usd> [chain]` (shows the gate card, then a Confirm button; live DexScreener price + 3% fee), `/sell <token> [percent]`, `/portfolio`, `/history`, `/reset`, `/stoploss <percent>|off`, `/copy <nickname> [usd]`, `/uncopy`, `/copygate on|off`, `/leaderboard`.
- Data: `practice/users/<chat_id>.json`. No keys, no wallets, nothing on-chain. Free sources only (DexScreener, Rugcheck, GoPlus); no Helius.
- Copy trades are filled by `bot.py push` (hourly) or the owner's `/scan`. Fills use the price at that time, not the wallet's fill price. KILL tokens are skipped unless `/copygate off`. The wallet's sells are mirrored.
- Non-owners: about 30 commands per hour. Menus: everyone sees the practice commands; the owner's chat sees everything.
- The leaderboard values open positions at cost (no live price calls for every user).

## Alerts
`python3 bot.py push --scan-file ../paper_trade/last_scan.json` sends one card for each new BUY from a non-test wallet (one per wallet+token per run, at most `push_max_cards`). Ones it already sent are remembered in `pushed.json`, so the hourly routine can call it after every scan.

## How the verdict is decided (gate.py, also importable: `gate.gate(token, chain, wallet)`)
- **SKIP**: token check says KILL, there's no pool with money in it, or the wallet sold within 60 s of buying at a 30%+ loss (or the sell couldn't be priced at all, which can mean a honeypot).
- **CAREFUL**: token check gave a warning, or the wallet is losing on paper, or it has fewer than 15 paper trades.
- **BUY**: token check passed and the wallet's paper record is fine.
- Max size: $50 for BUY, $25 for CAREFUL, $0 for SKIP.
- Daily loss limit ($100): a warning only, shown on cards once your logged losses reach 70% of it. Nothing is blocked.

All of these numbers are in `config.json`. CLI: `python3 gate.py <token> [--chain C] [--wallet NICK] [--json]` (exit 0 BUY, 1 CAREFUL, 2 SKIP).

## Buttons
- Solana: Jupiter `jup.ag/swap/SOL-<mint>`, Phantom (Phantom's documented `phantom.app/ul/browse/<url>` link opens Jupiter in Phantom's browser), DexScreener.
- Robinhood Chain and other EVM chains: DexScreener plus a swap link for the DEX of the main pool (from DexScreener's `dexId`: uniswap, pancakeswap, aerodrome, sushiswap). With any other DEX, you get DexScreener only. The Uniswap link uses `chain=robinhood` and has not been tested on a phone. If it opens on the wrong chain, use DexScreener's own buy button.

Token check runs with `--no-narrative` here, for speed.

**Chains:** HyperEVM (aliases hyperevm/hype/hyper/hl/hyperliquid) and Ink get full safety checks through token_check's on-chain fallback. HyperSwap tokens also get a "Swap on Hyperswap" button.

## Shipped from user feedback in one night

Built between the night of Oct 20 and the morning of Oct 21, 2026, after [@phantom_zxx](https://x.com/phantom_zxx) publicly asked for sniping, MEV protection, limit orders and DCA, and better speed under traffic.

1. **New-launch alerts** (key-free) every 3 minutes across Solana, Robinhood Chain, HyperEVM and Base, from DexScreener, GeckoTerminal and pump.fun. Each token gets a safety check, then a one-tap buy link or a practice snipe. Opt in with `/launches` (`launches.py`).
2. **MEV protection** through Jupiter Ultra deep links for swap, limit and DCA.
3. **Practice limit orders and DCA** (`/limit`, `/dca`, `/orders`, `/cancel`) that fill at live prices (`orders.py`).
4. **Speed**: fast and heavy worker lanes, a "Checking…" reply first, a single-flight cache (`cache.py`), and one heavy job per user. With 50 concurrent users, `/start` went from about 21s to 0.2s.
5. **Hardening**: no network calls while holding locks, per-host rate limits with 429 backoff, atomic writes and log rotation. A 100-user stress test gave p95 0.10s with zero errors.
6. **Supervisor**: an outside supervisor (`supervise.sh`, `supervise_start.sh`, `autostart.sh`) watches a heartbeat, restarts a frozen bot within about 2 minutes, and starts it again after a reboot.
7. **Contract checks**: Etherscan v2 verified-source and proxy checks on Ethereum, Base, Arbitrum, BNB, Polygon and HyperEVM (`token_check/etherscan.py`, `token_check/onchain.py`).
8. **UX**: reply with a number or tap $20/$50/$100/$250 to complete `/buy`, plus a health check across 9 chains.
9. **In progress**: follow alerts for new projects followed by about 20 big ecosystem X accounts (`follows.py`, needs `TWITTERAPI_IO_KEY`; copy `follows_config.example.json` to `follows_config.json` and add the accounts).

## /fumbles

`/fumbles` looks at your last 40 practice sells and checks how high each token went after you sold (GeckoTerminal price history, free and keyless; falls back to the live price). It totals what holding would have paid and sends a card with your top 3 "sold too early" trades, or a clean-exits card if none went higher. Practice money only. Idea credit: [@Akcrypts](https://x.com/Akcrypts) on X.

## Deploy

Always-on VPS setup lives in [`../deploy/`](../deploy/). Replace `YOUR_USER` and the paths with your own.

- `netro-signal.service`: systemd unit with `Restart=always`, reading secrets from an `EnvironmentFile` that stays on the server (never in the repo).
- `netro-hbcheck.timer` + `netro-hbcheck.service` + `netro-hbcheck.sh` (install as `/usr/local/bin/netro-hbcheck`): every 60s, restart the bot if `bot.heartbeat` is older than 120s, so a frozen bot is back within about 2 minutes.
- `backup_state.sh`: nightly backup (run it from cron) of the bot's local state into `~/backups`, keeping 7 days. Backups stay on the server.

## Setup

Copy config.example.json to config.json and set your own values. The example numbers are generic placeholders, not tuned settings.
