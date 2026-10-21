#!/bin/sh
# Heartbeat watchdog, run every 60s by netro-hbcheck.timer. Install as /usr/local/bin/netro-hbcheck.
# Restarts the bot if bot.heartbeat is older than 120s (a frozen poll loop), so a freeze is fixed within about 2 minutes.
HB=/home/YOUR_USER/netrovert-agents/tools/copytrade/tg_bot/bot.heartbeat
now=$(date +%s); hb=$(cut -d. -f1 "$HB" 2>/dev/null); hb=${hb:-0}
[ $((now - hb)) -gt 120 ] && systemctl restart netro-signal.service
exit 0
