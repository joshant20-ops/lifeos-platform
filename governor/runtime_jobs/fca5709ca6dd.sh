#!/usr/bin/env bash
set -Eeuo pipefail

readonly JOB_ID="fca5709ca6dd"
readonly ENGINEER_HOST="${LIFEOS_ENGINEER_SSH:-Engineer}"
readonly ENGINEER_REPO="${LIFEOS_ENGINEER_REPO:-/home/joshan/workspace/lifeos-platform}"
readonly SSH_TIMEOUT_SECONDS=15
readonly AUDIT_TIMEOUT_SECONDS=300

fail() {
  printf 'AUDIT_STATUS=FAIL reason=%s\n' "$1" >&2
  printf 'RESULT=FAIL job=%s\n' "$JOB_ID" >&2
  exit "${2:-1}"
}

command -v timeout >/dev/null || fail timeout_command_missing 20
command -v ssh >/dev/null || fail ssh_command_missing 21
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker 22

printf 'AUDIT_STATUS=START target=Engineer scope=tracked_source_code\n'
# The remote program examines only Git-tracked source under the LifeOS checkout.
# It excludes document/Paperless paths and emits classifications and paths only;
# source contents, secrets, environment values, and Git patches are never output.
if ! timeout --signal=TERM --kill-after=10s "${AUDIT_TIMEOUT_SECONDS}s" \
  ssh -T -o BatchMode=yes -o ConnectTimeout="$SSH_TIMEOUT_SECONDS" \
  "$ENGINEER_HOST" python3 - "$ENGINEER_REPO" <<'PY'
import collections
import datetime as dt
import hashlib
import os
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1]).resolve()
if not (root / ".git").exists():
    raise SystemExit("AUDIT_STATUS=FAIL reason=engineer_repo_missing")

def git(*args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        timeout=120,
    ).stdout

source_suffixes = {
    ".py", ".sh", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java",
    ".rb", ".php", ".lua", ".yaml", ".yml", ".json", ".toml", ".ini",
    ".service", ".timer", ".sql", ".html", ".css",
}
excluded_parts = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__",
    "paperless", "documents", "document", "media", "secrets", ".secrets",
}
tracked = []
for rel in git("ls-files", "-z").split("\0"):
    if not rel:
        continue
    path = pathlib.PurePosixPath(rel)
    if any(part.lower() in excluded_parts for part in path.parts):
        continue
    full = root / rel
    if full.is_file() and full.suffix.lower() in source_suffixes and full.stat().st_size <= 1_000_000:
        tracked.append(rel)

if not tracked:
    raise SystemExit("AUDIT_STATUS=FAIL reason=no_tracked_source_files")

contents = {}
hashes = collections.defaultdict(list)
for rel in tracked:
    data = (root / rel).read_bytes()
    hashes[hashlib.sha256(data).hexdigest()].append(rel)
    contents[rel] = data.decode("utf-8", "replace")

# Establish the last commit timestamp for every path without network access.
last_seen = {}
stamp = None
for line in git("log", "--format=@@%ct", "--name-only", "--", *tracked).splitlines():
    if line.startswith("@@"):
        stamp = int(line[2:])
    elif line and stamp is not None and line in contents and line not in last_seen:
        last_seen[line] = stamp

now = int(dt.datetime.now(dt.timezone.utc).timestamp())
basenames = {rel: pathlib.PurePosixPath(rel).name for rel in tracked}

def purpose(rel):
    low = rel.lower()
    if low.startswith("tests/") or "/test" in low or pathlib.PurePosixPath(low).name.startswith("test_"):
        return "tests/verification"
    if "/runtime_jobs/" in low or "/scripts/" in low or low.endswith(".sh"):
        return "operations/automation"
    if "deploy" in low or low.endswith((".service", ".timer")):
        return "deployment/service"
    if low.endswith((".html", ".css", ".js", ".jsx", ".tsx")):
        return "user-interface"
    if low.endswith((".yaml", ".yml", ".json", ".toml", ".ini")):
        return "configuration"
    return "application/library"

def references(rel):
    name = basenames[rel]
    stem = pathlib.PurePosixPath(name).stem
    needles = {name}
    if len(stem) >= 5:
        needles.add(stem)
    count = 0
    for other, text in contents.items():
        if other != rel and any(needle in text for needle in needles):
            count += 1
    return count

def frequency(n):
    if n >= 10: return "frequent (10+ referencing files)"
    if n >= 2: return "occasional (2-9 referencing files)"
    if n == 1: return "rare (1 referencing file)"
    return "unreferenced (0 referencing files)"

duplicates = [sorted(group) for group in hashes.values() if len(group) > 1]
findings = []
duplicate_members = {p for group in duplicates for p in group}
legacy_re = re.compile(r"(^|[/_.-])(old|legacy|deprecated|backup|bak|copy|unused)([/_.-]|$)", re.I)
for rel in sorted(tracked):
    refs = references(rel)
    age_days = (now - last_seen.get(rel, now)) // 86400
    reasons = []
    if rel in duplicate_members:
        reasons.append("exact duplicate")
    if legacy_re.search(rel):
        reasons.append("legacy/backup naming")
    if age_days >= 730 and refs <= 1:
        reasons.append(f"old ({age_days} days) with low use")
    if reasons:
        findings.append((rel, purpose(rel), frequency(refs), "; ".join(reasons), age_days))

print("# Engineer VM old and redundant code audit")
print()
print(f"Generated: {dt.datetime.now(dt.timezone.utc).date().isoformat()} (UTC)  ")
print(f"Scope: `{root}` — {len(tracked)} Git-tracked source/config files.  ")
print("Privacy boundary: Paperless, document, media, secret, generated, vendored, and untracked paths excluded; no file contents were emitted.")
print()
print("## Inventory and method")
print()
print("Exact redundancy is byte-identical SHA-256 content. Old code is at least 730 days since its last commit and has at most one filename/stem reference. Legacy naming is an additional review signal. Frequency is static reference frequency, not runtime telemetry; candidates require owner review before deletion.")
print()
print("## All identified instances")
print()
print("| Path | Purpose | Frequency | Evidence |")
print("|---|---|---|---|")
if findings:
    for rel, category, freq, reason, _ in findings:
        safe = rel.replace("|", "_").replace("`", "_")
        print(f"| `{safe}` | {category} | {freq} | {reason} |")
else:
    print("| _None detected by the stated rules_ | — | — | Re-run after code changes |")
print()
print("## Exact duplicate groups")
print()
if duplicates:
    for number, group in enumerate(duplicates, 1):
        print(f"- Group {number}: " + ", ".join(f"`{p}`" for p in group))
else:
    print("- None.")
print()
print("## Refactoring and removal plan")
print()
print("1. Week 1 — validate ownership and runtime consumers for every listed candidate; add missing characterization tests and record keep/remove decisions.")
print("2. Week 2 — consolidate exact duplicates behind one canonical module/script; update callers and deployment references, then run focused tests.")
print("3. Week 3 — deprecate low-use legacy candidates with compatibility shims where needed; observe service logs and scheduled-job health for seven days.")
print("4. Week 4 — remove approved dead code and shims, update operational documentation, and rerun this audit to establish the new baseline.")
print()
print("## Expected outcomes")
print()
print(f"- Review queue: {len(findings)} candidate files across {len(duplicates)} exact-duplicate groups.")
print("- One maintained implementation per duplicate group, fewer divergent fixes, a smaller test/deployment surface, and explicit ownership for retained legacy code.")
print("- No deletion is automatic; rollback remains a normal Git revert on the Pi5 canonical repository.")
print()
print(f"AUDIT_EVIDENCE=PASS scanned={len(tracked)} findings={len(findings)} duplicate_groups={len(duplicates)}")
PY
then
  status=$?
  fail "engineer_audit_failed_or_timed_out_${status}" "$status"
fi

printf 'AUDIT_STATUS=PASS job=%s\n' "$JOB_ID"
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
