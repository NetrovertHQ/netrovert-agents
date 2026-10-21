#!/usr/bin/env bash
cd "$(dirname "$0")"; [ -f bot.pid ] && kill "$(cat bot.pid)" && rm bot.pid && echo stopped
