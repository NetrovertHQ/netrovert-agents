---
name: Fomo leaderboard wallets
description: >-
  Use when pulling top traders and their wallets from the Fomo (fomo.family)
  leaderboard to feed smart-money scoring.
---
# Fomo leaderboard wallets

Read-only harvesting of Fomo top traders as copy-trade candidates. Never trade, deposit, follow, copy-trade, or export keys.

## Access
- Fomo's leaderboard and profile APIs (prod-api.fomo.family) and profile pages need a login; public curl returns `unauthorized` and empty shells.
- Fomo login is Apple or Google only. Google blocks the box browser, so use Sign in with Apple via request_box_help (user types the password on Apple's page; may need an iPhone approval). A Fomo account made with Apple shows an Apple private-relay email; that's normal.
- If the OAuth callback says "code expired or invalid", retry once quickly. If Apple says "failed to verify identity", allow one careful retry max, then fall back.
- Fallback: the user sends app screenshots (boards) and copies wallet addresses from profiles.
- Tell the user not to fund the account or tap Export keys.

## Steps
1. computerUse (read only): on the Leaderboard, record top 20 for 24h, 7d, 30d and all-time: rank, handle, PnL.
2. Dedupe handles; mark those on 2+ boards as priority.
3. Open each priority profile (then others, cap ~40) and copy full wallet addresses with chain. Never guess or rebuild truncated addresses.
4. Save to `tools/copytrade/smart_money/results/fomo_leaderboard.md`.
5. Score wallets with the Smart-money finder skill (`smart_money.py score`), watching the data-credit budget (~50-100 credits per wallet); rank priority ones first.
6. Report a short top list with bot/sniper flags. Promote nothing to the wallet tracker without the user's OK.
