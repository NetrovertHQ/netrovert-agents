#!/usr/bin/env bash
# Outside supervisor for Netro Signal. Restarts bot.py if it's not running or bot.heartbeat is older than 120s
# (SIGKILL, then a fresh start.sh). Inherits env (TELEGRAM_BOT_TOKEN, ETHERSCAN_API_KEY, ...) from the shell that starts it.
# Start: ./supervise_start.sh   Log: supervise.log (never prints secrets).
cd "$(dirname "$0")"
[ -f "$HOME/.netro_signal.env" ] && . "$HOME/.netro_signal.env"
echo $$ > supervise.pid
log() { echo "$(date '+%F %T') supervisor: $*" >> supervise.log; }
log "started (pid $$)"
while true; do
  pid=$(cat bot.pid 2>/dev/null); now=$(date +%s)
  hb=$(cut -d. -f1 bot.heartbeat 2>/dev/null); hb=${hb:-0}
  reason=""
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then reason="not running"
  elif [ $((now - hb)) -gt 120 ]; then reason="heartbeat $((now - hb))s old"; fi
  if [ -n "$reason" ]; then
    log "restarting bot ($reason)"; echo "$(date '+%F %T') supervisor: restarting ($reason)" >> bot.log
    [ -n "$pid" ] && kill -9 "$pid" 2>/dev/null; pkill -9 -f "python3 bot.py run" 2>/dev/null; rm -f bot.pid
    sleep 1; date +%s > bot.heartbeat; ./start.sh >> supervise.log 2>&1
  fi
  # rotate bot.log at 5 MB (bot appends, so copy + truncate is safe); keep one old copy
  if [ "$(stat -c %s bot.log 2>/dev/null || echo 0)" -gt 5000000 ]; then cp bot.log bot.log.1 && : > bot.log; log "rotated bot.log"; fi
  if [ "$(stat -c %s supervise.log 2>/dev/null || echo 0)" -gt 1000000 ]; then tail -n 200 supervise.log > supervise.log.tmp && mv supervise.log.tmp supervise.log; fi
  sleep 20
done
