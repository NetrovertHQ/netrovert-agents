---
name: Founder questions lead mining
description: >-
  Use when finding warm content or growth leads by mining questions people ask
  recently seed-funded startup founders on X, to produce content ideas and cold
  DMs with a real reason.
---
# Founder questions lead mining

Based on a method by @thatGTMdude. It turns founders' audience questions into content ideas and pitches that come with a real reason.

## Steps
1. **Pick a niche** (ask once if the user hasn't named one). Use one kind of customer, such as stablecoin or payments apps, AI agents, or consumer crypto.
2. **Find about 20 startups** that raised a seed round 3 to 9 months ago. Skip raises less than 3 months old, because the team is still heads-down. Use public funding news (web search, funding trackers, X announcements) and record the date, amount and source link for each.
3. **Narrow to 5** that sell to the same kind of customer. Skip any project already in the tracker or contacts files (run the shared-contacts skill).
4. **Find each founder's real X handle** from the company site or an official post. Never guess a handle.
5. **Read their recent posts with code, not the model.** About 50 is the lean default and 100 is the full version. Use public X reads (get_users_posts), save the raw output to a file, then filter it with a script for replies and quotes that contain questions aimed at them.
6. **Pull out every question** people asked them, then group the questions by theme and count how often each comes up.
7. **Write a short sheet per founder** in the workspace, covering the startup, raise, founder handle, top 3 to 5 question themes with example links, 3 content ideas that answer those questions, and one cold DM draft. Follow the cold-dm-sweet-spot skill: one human reason taken from their questions, the ask early, short lines, lowercase, and no unverified claims.
8. **Log each lead** in the tracker and contacts files and note which DM style was used. The user sends first DMs themselves.

## Budget rules
- Keep to about 250 X reads per run unless the user asks for the full version.
- Save long results to files and send the user only the 5 one-line summaries with the file path.
- Stop and report after 3 failures.
