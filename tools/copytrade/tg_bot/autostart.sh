#!/usr/bin/env bash
# Quiet, idempotent auto-start for the Netro Signal supervisor (called from ~/.bashrc, ~/.profile and the desktop autostart).
D="$(cd "$(dirname "$0")" && pwd)"
[ -x "$D/supervise_start.sh" ] || exit 0
[ -f "$D/supervise.pid" ] && kill -0 "$(cat "$D/supervise.pid" 2>/dev/null)" 2>/dev/null && exit 0
pgrep -f "$D/supervise.sh|\./supervise.sh" >/dev/null 2>&1 && exit 0
[ -f "$HOME/.netro_signal.env" ] && . "$HOME/.netro_signal.env"
( cd "$D" && setsid nohup ./supervise_start.sh >/dev/null 2>&1 </dev/null & ) >/dev/null 2>&1
exit 0
