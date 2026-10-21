---
name: Bot uptime and health check
description: >-
  Use when a long-running bot (e.g. a Telegram bot on the box) stops replying,
  freezes, gets slow under traffic, or the owner asks to check that all of its
  features work.
---
# Keep a long-running bot alive and healthy

## When it stops replying
1. Check quickly: is the process running (`pgrep -af bot.py`), when was its log last written, and are there watchdog, Traceback or error lines? A long gap in the log with no lines at all means the whole process was frozen or the machine was paused, not a single stuck request.
2. Get it answering first (restart it), then tell the owner honestly how long it was down and that users may need to resend.
3. Optional: `py-spy dump --pid <pid>` shows where every thread is waiting.

## Freeze-proofing (do once per bot)
- Every network call has a timeout. Telegram long-poll: getUpdates timeout ~25s with HTTP timeout (5, 35).
- The poll loop only fetches updates; replies, button acknowledgements and sends run in worker pools. Each thread keeps its own HTTP session, never one session shared by every thread.
- Two lanes: a fast pool for cheap commands and buttons, and a small heavy pool for slow checks. One heavy job per user at a time. Slow commands reply 'Checking…' at once, then edit that message with the result.
- A shared cache with single-flight (one lookup per key, everyone else waits for it): prices ~45s, safety results ~10 min. Don't cache errors, and cap the cache size.
- Background loops (scanners, order checkers) get their own small pools, are staggered so they don't fire together, and share per-host rate limits with 429 backoff.
- JSON state files: atomic write (temp file + rename) under a lock. Rotate the log file.
- An in-process watchdog is not enough: if the whole process freezes, so does the watchdog. Add an OUTSIDE supervisor script, started detached with nohup/setsid, that every ~20s restarts the bot with SIGKILL plus a fresh start if it's not running or its heartbeat file (written every poll) is older than 120s. The start script writes a heartbeat before launching so the supervisor doesn't kill a bot that is still starting.
- Secrets for restarts: only with the owner's OK, keep them in a chmod 600 env file outside the workspace (never in templates, backups or git) that the start scripts source. Never print values; check with `[ -n "$VAR" ]`.
- Auto-start after a reboot: use @reboot cron or the init system if there is one; otherwise use a guarded, silent, idempotent snippet in ~/.bashrc and ~/.profile that starts the supervisor if it isn't running.
- Test it: `kill -STOP <pid>` and confirm the supervisor brings it back within ~2 min; kill both and confirm a fresh shell brings them back.

## Full feature health check
Run in-process with a temp non-owner chat id and stubbed sends (never message real strangers), then clean up:
- Process, polling, heartbeat, watchdog and supervisor alive; log errors and slow entries since the last check.
- Menus and help for both owner and public scopes; owner-only commands are refused for others straight away.
- Every core command and button path, with short aliases and arguments in any order; deep-link URLs return 200.
- Background threads ran recently and state files are fresh; scheduled routines ran in their window.
- Privacy: private nicknames or owner data never appear in public output.
- Stress: ~50-100 fake users mixing cheap and heavy commands while background jobs run; cheap-command p95 under ~1-3s, heartbeat gaps under 30s, stable thread count and memory.
- Save paid API credits: skip or limit calls that cost credits.

Fix bugs with small targeted edits (back up first), restart through the supervisor path, re-verify, then report a short pass/fail list by area, what was fixed and what is still partly working.
