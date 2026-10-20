---
name: community-unanswered-questions
description: >-
  Use when checking Discord, Telegram or X group chats for member questions
  nobody answered, so the owner can reply or pin an answer. Runs daily or as
  part of the weekly pulse.
---
# Unanswered questions

This works across Discord, Telegram and X group chats, using the same saved message files as the weekly pulse. Do the matching with code and only read the short candidate list.

1. Refresh the data for the window: the last 24 hours for a daily check, or 7 days inside the weekly pulse. Run the collectors (Discord script, Telegram collector, and the X group script with keys refetched first).
2. Find questions with code. A question contains '?' or starts with how/what/when/where/why/who/is/are/can/does/anyone/pls, and is over 15 characters. Skip bots, the owner's own messages and pure banter (very short or emoji-only messages).
3. Mark a question answered if any of these is true:
   - someone else replied to it directly (a reply or thread)
   - another member posted within 10 minutes and that message shares a key word with the question or mentions the asker
   - the asker said thanks or got it afterwards
   Otherwise it's unanswered. Leave out questions less than 2 hours old in the daily check.
4. Read only the unanswered list and keep the useful ones: real help or info requests (how-to, safety, payouts, access, opportunities). Drop rhetorical and joke questions. Group repeats from different members together, because those are FAQ candidates.
5. Send the owner a short list with platform, group or channel, asker, a short quote of the question, when it was asked, and a message link or id where the platform has one. Suggest a one-line answer only when it's a factual question you can verify. Flag any question asked 3+ times as worth a pinned FAQ.
6. Save the list to `reports/unanswered_DATE.md` and the ids already reported to `data/unanswered_seen.json`, so the same question isn't flagged twice.
7. If nothing new is unanswered, stay silent on a scheduled run.
8. Never reply in the community yourself. The owner answers, or asks you to draft a reply for them to post.
