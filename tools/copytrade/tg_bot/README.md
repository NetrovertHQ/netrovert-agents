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
