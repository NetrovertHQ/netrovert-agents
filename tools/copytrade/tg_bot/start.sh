#!/usr/bin/env bash
# Start Netro Signal in the background. Needs TELEGRAM_BOT_TOKEN in env. Logs to bot.log (token never written).
cd "$(dirname "$0")"
[ -f "$HOME/.netro_signal.env" ] && . "$HOME/.netro_signal.env"  # private secrets file (600), needed after a reboot
[ -z "$TELEGRAM_BOT_TOKEN" ] && { echo "TELEGRAM_BOT_TOKEN is not set"; exit 1; }
if [ -f bot.pid ] && kill -0 "$(cat bot.pid)" 2>/dev/null; then echo "already running (pid $(cat bot.pid))"; exit 0; fi
date +%s > bot.heartbeat  # grace for the supervisor until the poll loop writes its own
nohup python3 bot.py run >> bot.log 2>&1 &
echo $! > bot.pid; echo "started pid $!, log: $(pwd)/bot.log"
