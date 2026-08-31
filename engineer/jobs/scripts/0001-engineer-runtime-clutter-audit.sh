#!/usr/bin/env bash
set -euo pipefail
echo "===== ENGINEER RUNTIME / AUTOMATION CLUTTER AUDIT ====="
date -Is
echo
echo "===== IDENTITY ====="
hostname
id
echo
echo "===== RESOURCE SUMMARY ====="
free -h
df -h /
echo
echo "===== LISTENING PORTS ====="
ss -lntup 2>/dev/null || true
echo
echo "===== PYTHON PROCESSES ====="
ps -eo pid,ppid,user,etimes,%cpu,%mem,cmd | grep -E '[p]ython|[c]odex|[o]llama' || true
echo
echo "===== USER CRON ====="
crontab -l 2>/dev/null || true
echo
echo "===== USER SYSTEMD ====="
systemctl --user list-unit-files --no-pager 2>/dev/null || true
echo
echo "===== SYSTEM SERVICES RELEVANT TO ENGINEER ====="
systemctl list-unit-files --type=service --no-pager 2>/dev/null | grep -Ei 'lifeos|engineer|codex|ollama|python|docker' || true
echo
echo "===== SYSTEM TIMERS ====="
systemctl list-timers --all --no-pager 2>/dev/null || true
echo
echo "===== HOME TOP LEVEL ====="
find "$HOME" -maxdepth 1 -mindepth 1 -printf '%f\n' | sort
echo
echo "===== SELECTED DIRECTORY SIZES ====="
for d in "$HOME/automation" "$HOME/z97_jobs" "$HOME/engineer_sync" "$HOME/engineer" "$HOME/pa_ai_lifeos" "$HOME/paperless_ai_inbox" "$HOME/paperless_ai_outbox" "$HOME/workspace"; do
  [ -e "$d" ] && du -sh "$d" 2>/dev/null || true
done
echo
echo "===== AUTOMATION TREE ====="
find "$HOME/automation" -maxdepth 2 -type f -printf '%p\n' 2>/dev/null | sort | head -200 || true
echo
echo "===== Z97 JOBS ====="
find "$HOME/z97_jobs" -maxdepth 2 -type f -printf '%p\n' 2>/dev/null | sort | head -200 || true
echo
echo "===== ENGINEER SYNC ====="
find "$HOME/engineer_sync" -maxdepth 3 -type f -printf '%p\n' 2>/dev/null | sort | head -200 || true
echo
echo "===== PUBLIC PORT 38124 OWNER ====="
pid=$(ss -lntp 2>/dev/null | awk '/:38124 / {if (match($0,/pid=[0-9]+/)) {x=substr($0,RSTART+4,RLENGTH-4); print x; exit}}')
if [ -n "${pid:-}" ] && [ -r "/proc/$pid/cmdline" ]; then
  echo "PID=$pid"
  tr '\0' ' ' <"/proc/$pid/cmdline"; echo
  echo "CWD=$(readlink -f /proc/$pid/cwd 2>/dev/null || true)"
  echo "EXE=$(readlink -f /proc/$pid/exe 2>/dev/null || true)"
else
  echo "No readable process found on 38124"
fi
echo
echo "===== RESULT ====="
echo "RESULT=PASS"
echo "NEXT=classify_keep_remove_migrate"
