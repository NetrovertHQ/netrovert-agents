---
name: community-foul-language-watch
description: >-
  Use when setting up or running the community foul-language watch: flag abusive
  messages in Discord or Telegram, count weekly strikes, warn, and remove repeat
  offenders only after the owner approves.
---
# Foul-language watch

## Setup
- Agree the rules with the owner: a word list (start with a common English profanity and slur list and add their local slang or languages), the strike limit (default: warning at 4 strikes in a rolling 7 days, removal at 5), and whether the bot posts the warning in the group or only alerts the owner.
- Check the permissions. Discord needs Send Messages, Kick Members and Moderate Members (for timeouts), and the bot's role must sit above members' roles. Telegram needs the bot as admin with **Ban users**.
- Write `foul_watch.py` in the work folder. It checks only new messages since its last run (saved cursor), matches with code (whole words, case-insensitive, simple leetspeak like @ for a and 1 for i, skipping quoted reports in mod channels), and appends hits to `data/strikes.jsonl` (platform, member id/name, channel, message link or id, matched word, timestamp). For Telegram, read from the collector's saved messages, or have the watch run the collector first.
- Create a routine that runs it hourly during the owner's waking hours, plus the twice-daily Telegram collection. It stays completely silent when there are no hits.

## Each run
1. Run the script. If there are no new hits, end silently.
2. For each new hit, alert the owner in this chat: who, where, the message (mask the slur partly), and their strike count this week.
3. At the warning limit: post the agreed warning in the channel (Discord) or reply to the message (Telegram), only if the owner opted in. Otherwise include it as a suggestion in the alert.
4. At the removal limit, never remove anyone on your own. Send the owner a yes/no question: remove [member] from [group]? Include their recent strikes as evidence. Only after a clear yes, kick on Discord (`DELETE /guilds/{id}/members/{user}`) or ban and then unban on Telegram (`banChatMember` then `unbanChatMember`, so they're removed but can rejoin later). Log it. A no or no answer means do nothing, and mark the member as reviewed so you don't ask again for the same strikes.
5. Strikes older than 7 days stop counting. False positives the owner points out get added to an allowlist.
