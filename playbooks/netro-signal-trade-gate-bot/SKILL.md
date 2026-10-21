---
name: Netro Signal trade gate bot
description: >-
  Use when running, fixing, extending or explaining the owner's Telegram
  trade-gate bot (verdict cards, owner tools, practice mode with fake money).
---
# Netro Signal (Telegram trade gate)

## What it is, in plain words
A Telegram bot that looks at any token and says BUY, CAREFUL or SKIP with short reasons and a max size, then gives one-tap buttons (Swap on Jupiter/Phantom on Solana, Uniswap on Robinhood Chain, DexScreener). The Swap button is the real-money path: it opens the person's own wallet and they confirm there. The bot never holds keys and never places real trades. Messages are Netrovert-branded ("Netro Signal by Netrovert").

- BUY: passes the safety check and the copied wallet isn't losing badly on paper (max size: `size_cap_buy_usd` in config).
- CAREFUL: warning signs or thin/losing paper record (max size: `size_cap_careful_usd`).
- SKIP: failed safety check, no pool, or the wallet dumped seconds after buying.

## Who can use what
- Owner (first /start, chat id saved in config): every tool: /check, /safety, /watch, /unwatch, /wallets, /scan (cooldown `scan_cooldown_s`), /score (daily cap `score_per_day`), /smartmoney, /callers, /addcaller, /calls, /paper, /papertrade, /fomo, /loss, /settings, /publicname.
- Everyone else: practice mode only, rate-limited by `public_rate_per_hour`: /practice (fake $1,000), /buy and /sell at live prices with a safety card, Confirm fake buy button and the real Swap button, /portfolio, /history (numbered), /reset, /stoploss, /copy <number> and /uncopy, /copygate, /leaderboard, /pnl.
- Chain can be typed short and in any order: sol, rh/hood, eth, base, bnb/bsc, arb, poly, ink (gate.ALIAS / split_args). Ink safety data is partial, so Ink tokens usually come out CAREFUL.

## Public wallet labels
Public users never see the owner's wallet nicknames. Each watched wallet has a public label in config.json `public_labels` keyed by address (e.g. Robinhood whale #1, Solana trader #1/#2) with a description built from real hold time, trade rate and paper record. `/copy N` uses the number. Owner renames with `/publicname <nickname> <label>`. Test-* wallets are hidden.

## PnL cards
`card.py` draws 1200x675 practice PnL images (trade and portfolio) labelled PRACTICE · NOT REAL MONEY, with the Gojo fox mascot from tg_bot/assets/: band.png for profit above +2%, sass.png for loss below -2%, sleep.png for flat (FLAT_PCT). Sent with `/pnl`, `/pnl SYMBOL` or `/pnl N`, and through the 🧾 Share PnL card button after sells and push closes.

## Running it
Folder `tools/copytrade/tg_bot/` (python3). Token is env TELEGRAM_BOT_TOKEN; never print it.
- Start/stop: `./start.sh`, `./stop.sh` (logs in bot.log). After a box restart, run start.sh again; the hourly wallet check also restarts it if it's down.
- Each Telegram call uses its own requests.post (a shared Session froze the reply workers after getUpdates timeouts). Replies run in a worker pool, and a watchdog restarts the bot if a reply is stuck too long.
- Alerts and practice copy fills: `python3 bot.py push --scan-file ../paper_trade/last_scan.json`, called by the hourly wallet check after its scan. Never run a separate scan for it.
- Gate on its own: `python3 gate.py <token> [--chain C] [--wallet NICK]`.
- BotFather: join groups disabled. Description, short description and command menus are set through the API; don't overwrite them in BotFather. The profile photo is still to be set (the owner's logo).

## Known limits
Practice copy fills use the price at push time (up to an hour late). Slow commands: /score takes minutes, /safety up to a minute when Rugcheck is slow; if Rugcheck is down, results show as WARN, never PASS.
