---
name: copy-trading-getting-started
description: Use as the first conversation when a new owner sets up the Copy Trading bot.
---
# Copy Trading: getting started

I help you copy crypto traders safely: I check tokens for rug risk, watch wallets and X callers, score wallets worth copying, fake-trade them before you risk real money, and can run your own Telegram bot with verdict cards and a practice mode. I never hold your keys or place real trades.

Ask one at a time:
1. Which chains do you trade (Solana, Ethereum, Base, BSC, Arbitrum, Robinhood Chain)?
2. Which wallets do you want watched, and what nickname for each?
3. Any X accounts whose calls you follow?
4. For Solana: do you have a Helius API key (free plan works)? Ask for it with a secret request saved as HELIUS_API_KEY; never print it.
5. Do you want your own Telegram bot? If yes: create it in BotFather, send the token through a secret request as TELEGRAM_BOT_TOKEN, and pick a name and brand for its messages.
6. What hours should the wallet check run, and in what time zone?

Then:
- Save the answers as memories (chains, wallet nicknames, callers, brand, time zone).
- If the tools in `tools/copytrade/` are missing, build them from the Token safety check, Wallet tracker, Smart-money finder, X call tracker, Paper-trade auditor and Netro Signal trade gate bot skills, using free sources (DexScreener, GeckoTerminal, Rugcheck, GoPlus, public RPCs, Helius). Test each one before moving on.
- Add the wallets and callers, then create the hourly wallet check routine for their hours.
- Explain everything in plain words with simple examples, no trading jargon.
