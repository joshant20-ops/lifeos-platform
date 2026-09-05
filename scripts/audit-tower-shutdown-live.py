#!/usr/bin/env python3
import json, re, subprocess
from pathlib import Path

PATTERNS = re.compile(r"shut\s*down\s*tower|shutdown\s*tower|tower|z97|poweroff|shutdown|lifeos[_-]?wol|power[_-]?down", re.I)
SECRET = re.compile(r"(?i)(token|password|secret|api[_-]?key|authorization)\s*[:=]\s*[^\s,}]+")
IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
URL_CREDS = re.compile(r"(?i)(https?://)([^/@\s:]+):([^/@\s]+)@")

def run(*args):
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout

def redact(s):
    s = SECRET.sub(lambda m: m.group(1)+"=<redacted>", s)
    s = URL_CREDS.sub(r"\1<redacted>@", s)
    s = IP.sub("<ip>", s)
    return s

containers = run("docker","ps","--format","{{.Names}}").splitlines()
ha = next((x for x in containers if x in ("homeassistant","home-assistant")), None)
if not ha:
    raise SystemExit("HA_CONTAINER=NOT_FOUND")

cmd = ["docker","exec",ha,"sh","-lc",
       "find /config -maxdepth 3 -type f \\( -name '*.yaml' -o -name '*.yml' \\) -print0 | xargs -0 grep -nHiE 'shut[[:space:]]*down[[:space:]]*tower|shutdown[[:space:]]*tower|tower|z97|poweroff|shutdown|lifeos[-_]?wol|power[-_]?down' || true"]
out = run(*cmd)
lines = []
for line in out.splitlines():
    if PATTERNS.search(line):
        lines.append(redact(line)[:500])

# systemd/unit structural evidence only; no env dumps
units = run("systemctl","list-unit-files","--no-legend","--no-pager").splitlines()
relevant_units = [u.split()[0] for u in units if re.search(r"lifeos|wol|z97|power|shutdown", u, re.I)]

print("TOWER_SHUTDOWN_AUDIT=PASS")
print(f"HA_CONTAINER={ha}")
print(f"MATCH_COUNT={len(lines)}")
print("MATCHES_BEGIN")
for x in lines[:120]: print(x)
print("MATCHES_END")
print("RELEVANT_UNITS_BEGIN")
for x in relevant_units[:120]: print(x)
print("RELEVANT_UNITS_END")
print("SECRETS_REDACTED=YES")
print("MUTATION_PERFORMED=NO")
