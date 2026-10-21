#!/bin/sh
cd /home/YOUR_USER/netrovert-agents/tools/copytrade/tg_bot && tar czf /home/YOUR_USER/backups/state-$(date +%F).tgz *.json practice 2>/dev/null
find /home/YOUR_USER/backups -name "state-*.tgz" -mtime +7 -delete
