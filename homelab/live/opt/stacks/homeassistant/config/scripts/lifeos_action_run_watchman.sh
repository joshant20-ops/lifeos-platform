#!/usr/bin/env bash
set -e

echo "[LifeOS] Manual Watchman trigger"

python3 /home/joshan/automation/proposal_applier.py >> /home/joshan/automation/logs/manual_watchman_trigger.log 2>&1

echo "[LifeOS] Done"
