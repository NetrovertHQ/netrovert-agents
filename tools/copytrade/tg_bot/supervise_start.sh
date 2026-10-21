#!/usr/bin/env bash
# Start the supervisor detached (survives the calling shell). Run from a shell that has the bot's env vars.
cd "$(dirname "$0")"
if [ -f supervise.pid ] && kill -0 "$(cat supervise.pid)" 2>/dev/null; then echo "supervisor already running (pid $(cat supervise.pid))"; exit 0; fi
setsid nohup ./supervise.sh > /dev/null 2>&1 < /dev/null &
sleep 1; echo "supervisor started (pid $(cat supervise.pid))"
