#!/bin/sh
# Read-only evidence collector. It reports metadata, never file contents.
set -eu

output=${1:-/tmp/lifeos-engineer-cleanup-audit.txt}
case "$output" in
  /tmp/*) ;;
  *) echo "refusing output outside /tmp" >&2; exit 2 ;;
esac

{
  echo "generated=$(date -Iseconds)"
  echo "host=$(hostname)"
  echo "## filesystem"
  df -h /home /var 2>/dev/null || df -h /
  echo "## protected paths (metadata only)"
  for path in \
    /home/joshan/.codex/auth.json /home/joshan/.config/gh /home/joshan/.ssh \
    /home/joshan/.openhands /home/joshan/.ollama /usr/share/ollama \
    /home/joshan/workspace/lifeos-platform
  do
    if [ -e "$path" ]; then stat -c '%F %a %U:%G %s %n' "$path"; else echo "ABSENT $path"; fi
  done
  echo "## proposed backup candidates (metadata only)"
  find /home/joshan/automation/backups -maxdepth 1 -mindepth 1 \
    \( -name 'openhands_*' -o -name 'z97_*' -o -name 'llm_bridge*' \) \
    -printf '%y %TY-%Tm-%TdT%TH:%TM:%TS %s %p\n' 2>/dev/null || true
  echo "## ollama models (read only)"
  if command -v ollama >/dev/null 2>&1; then ollama list 2>&1 || true; else echo "ollama CLI absent"; fi
  echo "## package candidates (simulation only)"
  if command -v apt-get >/dev/null 2>&1; then apt-get -s autoremove 2>&1 || true; else echo "apt-get absent"; fi
  echo "## docker usage (read only; no prune)"
  if command -v docker >/dev/null 2>&1; then docker system df 2>&1 || true; else echo "docker CLI absent"; fi
  echo "## journal usage (read only; no vacuum)"
  if command -v journalctl >/dev/null 2>&1; then journalctl --disk-usage 2>&1 || true; else echo "journalctl absent"; fi
} > "$output"

chmod 600 "$output"
echo "$output"
