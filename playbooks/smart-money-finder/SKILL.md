---
name: Smart-money finder
description: >-
  Use when finding, scoring or ranking crypto wallets worth copying by real PnL,
  win rate and copyability, or deciding whether a given wallet is a good copy
  target.
---
# Smart-money finder

Tool: `tools/copytrade/smart_money/smart_money.py` (see README.md). Solana via Helius (`HELIUS_API_KEY`, never print it); candidates from tokens that ran, pump.fun, and public leaderboards.

## Steps
1. Score a wallet: `python3 smart_money.py score <wallet> [--chain] [--label]` for 30-day realized PnL, win rate, trades/day, hold time, buy size, share of buys the token safety check kills, early-buy and bot/sniper/insider flags, and a 0-100 copyability score.
2. Find new ones: `python3 smart_money.py discover [--days 7] [--limit 10]`, then `top [--min-copyability N]`.
3. Only add a wallet to the Wallet tracker with `promote <wallet> --label X` after the user agrees.

## Notes
- Profitable snipers and bots aren't copyable; rank by copyability, not PnL alone.
- A high KILL share means the wallet chases rugs; copy only with the safety filter on.
- Discover costs ~2k Helius credits per pass.
