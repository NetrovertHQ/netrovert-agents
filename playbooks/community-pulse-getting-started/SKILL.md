---
name: community-pulse-getting-started
description: >-
  Use as the first conversation when a new owner sets up the Community Pulse
  bot, to connect their Discord, Telegram and X group chats and turn on the
  weekly pulse, unanswered-question alerts and foul-language watch.
---
# Community Pulse: getting started

Start with one line: I write a weekly pulse of your community chats (top questions, most active members, who's gone quiet), flag questions nobody answered, and can watch for foul language. Then ask one thing at a time and check each step works before moving on. Give click-by-click instructions, since most owners have never used a bot API.

## 1. Which platforms
Ask which community chats they run: a Discord server, a Telegram group, X group chats, or a mix. Set them up one at a time, starting with Discord if they have it. Save the community name and platforms to memory.

## 2. Discord
Give these steps:
1. Open https://discord.com/developers/applications, click **New Application**, and name it.
2. On the **Bot** tab, turn on **Message Content Intent** and **Server Members Intent**. Click **Reset Token**, then **Copy**.
   - If **Save Changes** won't work, the cause is almost always **Public Bot** being off while an install link exists. Fix it by turning Public Bot back on (harmless, since nobody can add the bot without the link), or by going to the **Installation** tab, setting Install Link to None, and saving.
3. Go to **OAuth2**, then **URL Generator**. Pick scope `bot` and permissions **View Channels** and **Read Message History**. For moderation, also pick **Send Messages**, **Kick Members** and **Moderate Members**. Open the generated link and add the bot to their server.
4. Collect the token with a secret-request as `DISCORD_BOT_TOKEN`. If the save button fails, accept a pasted token, store it in a chmod 600 `.env` in the work folder, and suggest they reset the token later.

To verify, call `GET https://discord.com/api/v10/users/@me/guilds` with header `Authorization: Bot <token>` and check the server is listed. Then try reading a few messages from every text channel. If some channels return 403, read each channel's `permission_overwrites` and the guild roles yourself. Usually @everyone is denied and one member role (such as a 'verified' role) is allowed. Tell the owner the exact role name, and ask them to right-click the bot, choose **Roles** and tick it. Don't make them set per-channel overrides. Staff-only channels can stay private unless they want them included.

Write `discord_pulse.py` in the work folder (default `/workspace/community-pulse`). It fetches 35 days of messages from every readable text and announcement channel, active and archived threads, and forum posts. It paginates with `before` and waits out 429 `retry_after`. It saves the raw messages to `data/discord_DATE.json`. With code, it computes:
- per-channel and per-member counts for this week vs last week, excluding bots
- gone-quiet members (5+ messages in days 8-35, none in the last 7)
- question-like messages, each with a replied flag

## 3. Telegram
1. Message @BotFather, send `/newbot`, and copy the token.
2. Send `/setprivacy`, pick the bot, and choose **Disable**. Otherwise the bot only sees commands.
3. Add the bot to the group, as an admin to be safe. If it was added before privacy was disabled, remove it and add it again.
4. Collect the token with a secret-request as `TELEGRAM_BOT_TOKEN`.

To verify, check that `getMe` shows `can_read_all_group_messages: true`. Ask them to send a test message, then check that `getUpdates` shows the group. If there are no updates at all, the bot isn't really in the group. Check the exact bot username, and that they added it to the group chat rather than the announcement channel.

The Bot API only keeps updates for 24 hours, and the bot can't see older history. Write `tg_collect.py`, which pulls `getUpdates` with a saved offset and appends group messages (id, chat, ts, user id/username/name, is_bot, text or caption, reply_to) to `data/telegram/DATE.jsonl`. Create a silent routine that runs it twice a day, every day, weekends included because of the 24-hour limit. It should only speak up after 2 failures in a row.

For history, ask for a one-time Telegram Desktop export. They open the group, tap ⋮, choose **Export chat history**, untick media, choose JSON, and pick the last 1-3 months. Import `result.json` into the same jsonl format. Don't try a user-account (MTProto) login, because most bot computers only allow web traffic.

## 4. X group chats
X group chats are end-to-end encrypted. Reading them needs the X plugin connected as the owner plus the owner's X Chat PIN. The bot reads as the owner, so it only sees groups they're in.
1. Install or connect the X plugin and Read its X guide skill. Follow its X Chat section, which uses the local xchat-lite helper.
2. Collect the Chat PIN with a secret-request, never in plain chat. If they've forgotten it, they can reset it in X under **Settings**, **Privacy and safety**, **Encrypted messages**.
3. Before unlocking, always refetch the owner's public keys and use the newest key version. A 'Keys not registered' error almost always means an old key version is being used, not that the PIN is wrong. Ask once whether to keep the chat key on this computer so the PIN isn't needed every week.
4. List group conversations. Most group names are encrypted, so decrypt them and ask which groups to track. Save each group's conversation id to memory.
5. Write `x_group_pulse.py`. Busy groups can produce hundreds of events a day, so page backwards only until the window start (7 days for the weekly pulse, plus 4 earlier weeks the first time for the gone-quiet baseline). Save decrypted messages to `data/x/GROUP_DATE.json` with chmod 600, and compute the same per-member counts, gone-quiet list and questions with a replied flag as for Discord. Read only. Never send, react, mark read or accept requests.

## 5. Turn things on
- Ask what day and time they want the pulse, suggesting Monday morning in their timezone. Create the weekly routine that runs the collectors and follows the **community-pulse-weekly** skill.
- Offer the **community-unanswered-questions** skill as a daily check (suggest evenings), so questions get answered the same day instead of waiting for Monday.
- Ask if they want the foul-language watch. If yes, follow the **community-foul-language-watch** setup. Agree the strike limit (suggest a warning at 4 and removal at 5 per week) and any extra words or languages to add, and confirm the bot has the moderation permissions above.
- Finish by running the pulse once so they see a real report. If a platform is quiet, say so plainly.
