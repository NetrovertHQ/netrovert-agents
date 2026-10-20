---
name: Wallet tracker
description: >-
  Use when watching crypto wallets (Solana, Ethereum, Base, BSC, Arbitrum,
  Robinhood Chain) for new buys and sells, adding or removing watched wallets,
  or alerting on their trades with a safety verdict.
---
# Wallet tracker

Tool: `tools/copytrade/wallet_tracker/wallet_tracker.py` (see README.md). Solana uses Helius when `HELIUS_API_KEY` is set (never print it), else public RPC; EVM chains use free public RPC/Blockscout.

## Steps
1. Manage the list: `python3 wallet_tracker.py add <addr> --chain <chain> --label <nickname>`, `remove <addr|label>`, `list`. A new wallet's first scan only sets a baseline; use `scan <label> --backfill N` to see its last N trades.
2. Check for trades: `python3 wallet_tracker.py scan --json`. No output means nothing new: stay silent.
3. For each new trade, report wallet nickname, BUY/SELL, token, USD value (say if it's at fill or current price), time in the user's zone, and for buys the token safety check verdict, score and main reason.
4. Flag patterns: a wallet buying the same token repeatedly, or several wallets buying the same token.

## Notes
- Run the Token safety check skill's rules for verdicts; never present a trade as advice.
- Very bot-heavy wallets need Helius; without it say their trades may be missed.
- Keep cadence modest (Helius ~10 credits per wallet per scan).
