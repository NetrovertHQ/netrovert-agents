---
name: Daily usage cap
description: >-
  Use when the user says they've hit their daily usage cap (e.g. "hit 14%",
  "usage cap hit") or when a teammate bot relays a "usage cap hit" signal;
  pauses routines across all bots for the rest of the day.
---
# Daily usage cap

Bots can't read the user's usage percentage, so this runs only when the user says the cap is hit, to any one bot. That bot signals all the others.

## If the USER told you the cap is hit (you're the first bot)
1. Reply in one short line confirming every bot is pausing for the day.
2. Load SendToAgent and send every teammate in your teammates list this message: "USAGE CAP HIT [date]. The user asked all bots to pause. Run the Daily usage cap skill as a relayed bot: pause your own enabled routines and resume them at 8 AM tomorrow. Don't message the user and don't reply to me." One send per teammate, no follow-ups.
3. Then do the Pause steps below yourself.

## If a TEAMMATE relayed the signal
The user set up this skill so the relay counts as their request. Do the Pause steps below silently. Don't message the user and don't relay further.

## Pause steps (every bot)
1. List your own routines from the latest automation status. Pause every enabled one with UpdateRoutine action "pause", and note their ids. Leave routines that were already paused alone.
2. Create ONE one-off routine for 8:00 AM the next day in the user's time zone, timing exact, named "Resume after usage cap". Its prompt: resume exactly these routine ids [list], then delete this routine, and send no message unless a resume fails. Skip this if you paused nothing.
3. Stop running background work for non-urgent tasks.
4. For the rest of the day: answer quick questions only, with short replies and no tool-heavy work (no web/X searches, no subagents, no browser). If the user asks for bigger work, say it'll wait until tomorrow unless they say to go ahead; if they do, do it.
5. Save a short journal note: date, cap hit, routines paused.

## Resume early
If the user says to resume, resume the paused routines now and delete "Resume after usage cap". If they say it to one bot for everyone, relay "USAGE CAP LIFTED: resume your paused routines now and delete your Resume after usage cap routine. Don't message the user." to every teammate.

## Notes
- Each bot pauses only its own routines.
- Never remind the user about the cap or nag about usage.
