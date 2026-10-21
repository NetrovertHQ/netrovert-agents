#!/bin/sh
systemctl is-active -q netro-signal || exit 0
hb=$(cut -d. -f1 /home/YOUR_USER/netrovert-agents/tools/copytrade/tg_bot/bot.heartbeat 2>/dev/null); hb=${hb:-0}
[ $(($(date +%s)-hb)) -gt 120 ] && { logger "netro-signal heartbeat stale, restarting"; systemctl restart netro-signal; }
exit 0
