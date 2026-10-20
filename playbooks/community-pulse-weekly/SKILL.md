---
name: community-pulse-weekly
description: >-
  Use when writing the weekly community pulse from saved Discord, Telegram or X
  group chat messages: volume, most active members, who's gone quiet, top
  questions, unanswered ones and suggested actions.
---
# Weekly community pulse

The usage budget matters, so do all counting with code and read only the extracted questions and summaries, never the raw dumps.

1. Refresh the data. Run the Telegram collector, then `discord_pulse.py`, then `x_group_pulse.py` for each tracked X group (all in the work folder). For X, refetch public keys before unlocking and page back only 7 days, plus 4 earlier weeks the first time for the gone-quiet baseline.
2. For each platform or group, compute with code:
   - total messages, active members out of total members, and the owner's own count
   - spike days, with what drove them
   - the top 10 most active members with message counts, plus their last-7-day counts
   - gone quiet: members with 5+ messages in the prior 4 weeks and none this week, sorted by previous volume, plus regulars whose activity dropped sharply
   - question-like messages (containing '?' or starting with how/what/when/where/why/who/is/are/can/does, over 15 characters), each with whether it got a direct reply, a nearby reply within 10 minutes, or nothing
3. Read only the questions file. Group the questions into 4-6 themes, each with 1-3 short real examples. Then run the **community-unanswered-questions** skill on the same week to pick the notable unanswered ones.
4. Save the full report to `reports/pulse_DATE.md`.
5. Send the owner the pulse in exactly this layout, one block per platform or group. Write one opening sentence with the group name, member count and the dates covered, then these bullets:
   - **Volume:** messages from N active members, with any spike days and what drove them.
   - **Most active:** the top 7 names with counts, noting anyone whose posts all came this week.
   - **Gone quiet:** the biggest drop-off first (their count and the last date they posted), then regulars who have slowed down a lot.
   - **Top questions:** the 4-6 themes, each with a short real example in quotes or brackets.
   - **Answers:** how many questions got no reply out of the total, plus 2-3 examples of unanswered ones.
   After the bullets, add one line of suggestions (who to check in with, what to pin as an FAQ or safety note, and what recurring post would help), followed by the path to the full report.
   Write in plain English with no hype. If a platform had no activity, give it one line instead of a block.
6. Never message community members yourself. Suggestions go to the owner.
