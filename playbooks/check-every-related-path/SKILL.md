---
name: Check every related path
description: >-
  Use when verifying a bot, feature, or UX fix (health checks, after shipping,
  or after user feedback): never skip a related menu, command, or button path
  just to keep the run lean.
---
# Check every related path

Owner rule: always do things the proper way. A “lean” check that skips a related surface is a miss, especially when someone already got burned there.

## When this applies
- Full or partial health checks
- After shipping a UX or behavior change
- After user feedback about one screen, command, or button

## Do this
1. List every user-facing way to reach the same thing (slash command, Menu button, inline buttons, aliases, owner vs public).
2. Exercise **each** path with the same fixture (same user / same bag / same token). Compare text, buttons, and refusals side by side.
3. If feedback named a mismatch (e.g. Menu vs `/portfolio`), that pair is mandatory on the next verify. Do not mark the area PASS with a WARN that you skipped it.
4. Prefer one thorough pass over two lean passes that leave a gap.
5. Saving API credits or time is fine for *unrelated* areas; never for paths that share the bug class you just fixed or that the user just reported.

## Do not
- Skip a path because “code review says it calls the same function” without running it
- Call “lean” a reason to leave WARN on the exact place users complained about
- Tell the owner something is unified until both surfaces were checked in the same run

## Report
Say which paths you actually ran. If one failed or was blocked, say FAIL or blocked, not WARN-for-skipped.
