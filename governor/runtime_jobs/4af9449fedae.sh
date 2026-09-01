#!/usr/bin/env bash
set -Eeuo pipefail

readonly JOB_ID=4af9449fedae
readonly ENGINEER_HOST="${LIFEOS_ENGINEER_SSH:-Engineer}"
readonly ENGINEER_REPO="${LIFEOS_ENGINEER_REPO:-/home/joshan/workspace/lifeos-platform}"
readonly CONNECT_TIMEOUT_SECONDS=15
readonly AUDIT_TIMEOUT_SECONDS=300

fail() {
  printf 'AUDIT_STATUS=FAIL reason=%s\n' "${1:-unknown_failure}" >&2
  printf 'RESULT=FAIL job=%s\n' "$JOB_ID" >&2
  exit "${2:-1}"
}

command -v timeout >/dev/null || fail timeout_command_missing 20
command -v ssh >/dev/null || fail ssh_command_missing 21
[[ "$(hostname)" == Docker ]] || fail must_run_on_pi5_Docker 22

printf 'AUDIT_STATUS=START target=Engineer scope=git_tracked_source\n'
# Read-only remote audit. Only classifications and repository-relative code
# paths are returned. Source text, diffs, environment values, documents,
# credentials, and untracked files never leave the Engineer VM.
if ! timeout --signal=TERM --kill-after=10s "${AUDIT_TIMEOUT_SECONDS}s" \
  ssh -T -o BatchMode=yes -o ConnectTimeout="$CONNECT_TIMEOUT_SECONDS" \
  "$ENGINEER_HOST" python3 - "$ENGINEER_REPO" <<'PY'
import collections
import datetime as dt
import hashlib
import pathlib
import re
import subprocess
import sys

root = pathlib.Path(sys.argv[1]).resolve()
if not (root / ".git").exists():
    raise SystemExit("AUDIT_STATUS=FAIL reason=engineer_repo_missing")

def git(*args):
    return subprocess.run(
        ["git", "-C", str(root), *args], check=True, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=120,
    ).stdout

suffixes = {
    ".py", ".sh", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
    ".java", ".rb", ".php", ".lua", ".yaml", ".yml", ".json",
    ".toml", ".ini", ".service", ".timer", ".sql", ".html", ".css",
}
excluded = {
    ".git", "node_modules", "vendor", "dist", "build", "__pycache__",
    "paperless", "documents", "document", "media", "secrets", ".secrets",
    "credentials", ".env",
}
tracked = []
for rel in git("ls-files", "-z").split("\0"):
    path = pathlib.PurePosixPath(rel)
    full = root / rel
    if (rel and not any(p.lower() in excluded for p in path.parts)
            and full.is_file() and full.suffix.lower() in suffixes
            and full.stat().st_size <= 1_000_000):
        tracked.append(rel)
if not tracked:
    raise SystemExit("AUDIT_STATUS=FAIL reason=no_tracked_source_files")

contents, exact_hashes, normalized_hashes = {}, collections.defaultdict(list), collections.defaultdict(list)
for rel in tracked:
    raw = (root / rel).read_bytes()
    text = raw.decode("utf-8", "replace")
    contents[rel] = text
    exact_hashes[hashlib.sha256(raw).hexdigest()].append(rel)
    # A review signal for copied code that differs only in blank lines/comments.
    logical = "\n".join(
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith(("#", "//"))
    )
    if len(logical) >= 120:
        normalized_hashes[hashlib.sha256(logical.encode()).hexdigest()].append(rel)

last_seen, stamp = {}, None
for line in git("log", "--format=@@%ct", "--name-only", "--").splitlines():
    if line.startswith("@@"):
        stamp = int(line[2:])
    elif line in contents and stamp is not None and line not in last_seen:
        last_seen[line] = stamp

def groups(mapping):
    return sorted((sorted(v) for v in mapping.values() if len(v) > 1), key=lambda x: x[0])

exact_groups = groups(exact_hashes)
near_groups = [g for g in groups(normalized_hashes) if g not in exact_groups]
exact_members = {p for g in exact_groups for p in g}
near_members = {p for g in near_groups for p in g}
now = int(dt.datetime.now(dt.timezone.utc).timestamp())
legacy_re = re.compile(r"(^|[/_.-])(old|legacy|deprecated|backup|bak|copy|unused)([/_.-]|$)", re.I)

def purpose(rel):
    low = rel.lower()
    name = pathlib.PurePosixPath(low).name
    if low.startswith("tests/") or "/tests/" in low or name.startswith("test_"):
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

def reference_count(rel):
    path = pathlib.PurePosixPath(rel)
    needles = {path.name}
    if len(path.stem) >= 5:
        needles.add(path.stem)
    return sum(other != rel and any(n in text for n in needles)
               for other, text in contents.items())

def frequency(count):
    if count >= 10: return "frequent (10+ static consumers)"
    if count >= 2: return "occasional (2-9 static consumers)"
    if count == 1: return "rare (1 static consumer)"
    return "unreferenced (0 static consumers)"

findings = []
for rel in sorted(tracked):
    refs = reference_count(rel)
    age = (now - last_seen.get(rel, now)) // 86400
    signals = []
    disposition = []
    if rel in exact_members:
        signals.append("exact duplicate")
        disposition.append("consolidate into one canonical file")
    if rel in near_members:
        signals.append("comment/whitespace-normalized duplicate")
        disposition.append("compare behavior, then extract shared implementation")
    if legacy_re.search(rel):
        signals.append("legacy/backup naming")
        disposition.append("confirm owner and remove or rename")
    if age >= 730 and refs <= 1:
        signals.append(f"old ({age} days) with low static use")
        disposition.append("characterize, deprecate, then remove if unused")
    if signals:
        findings.append((rel, purpose(rel), frequency(refs), "; ".join(signals), "; ".join(dict.fromkeys(disposition))))

safe_root = root.name.replace("|", "_").replace("`", "_")
print("# Engineer VM old and redundant code report")
print()
print(f"Generated: {dt.datetime.now(dt.timezone.utc).date().isoformat()} (UTC)  ")
print(f"Scope: Engineer checkout `{safe_root}`; {len(tracked)} Git-tracked source/config files scanned.  ")
print("Privacy: document, Paperless, media, secret, credential, generated, vendored, and untracked paths excluded; no source contents emitted.")
print()
print("## Method and limitations")
print()
print("All instances matching the declared rules are listed below: byte-identical files; files identical after removing blank/comment-only lines; legacy/backup names; and files at least 730 days old with no more than one static filename/stem consumer. Frequency is static reference frequency, not runtime telemetry. These are review candidates, not automatic deletion decisions.")
print()
print("## Complete findings inventory")
print()
print("| Path | Detection class | Purpose | Frequency | Evidence | Recommended disposition |")
print("|---|---|---|---|---|---|")
if findings:
    for rel, category, freq, evidence, action in findings:
        safe = rel.replace("|", "_").replace("`", "_")
        detection = ", ".join(x.split(" (")[0] for x in evidence.split("; "))
        print(f"| `{safe}` | {detection} | {category} | {freq} | {evidence} | {action} |")
else:
    print("| _None matched the declared rules_ | — | — | — | Full scan completed | Re-run quarterly |")
print()
print("## Duplicate groups")
print()
for label, duplicate_groups in (("Exact", exact_groups), ("Normalized", near_groups)):
    if duplicate_groups:
        for number, group in enumerate(duplicate_groups, 1):
            print(f"- {label} {number}: " + ", ".join(f"`{p}`" for p in group))
    else:
        print(f"- {label}: none")
print()
print("## Refactoring timeline")
print()
print("1. Week 1 — assign owners; validate runtime consumers for every candidate; record keep/consolidate/remove decisions; add characterization tests.")
print("2. Week 2 — consolidate exact and normalized duplicates behind canonical modules/scripts; update callers; run focused tests and deployment dry-runs.")
print("3. Week 3 — deprecate approved low-use legacy paths with compatibility shims where required; monitor services and scheduled jobs for seven days.")
print("4. Week 4 — remove approved dead code and expired shims; update runbooks; rerun this audit and compare the baseline.")
print()
print("## Expected outcomes")
print()
print(f"- Baseline: {len(findings)} candidate files, {len(exact_groups)} exact groups, {len(near_groups)} normalized groups.")
print("- Target: one maintained implementation per confirmed duplicate group, zero unowned legacy candidates, and no service/test regression.")
print("- Efficiency: smaller maintenance and test surface, fewer divergent fixes, and repeatable quarterly evidence.")
print("- Safety: no automatic deletion; each removal remains independently reviewable and reversible through the Pi5 canonical Git workflow.")
print()
print(f"AUDIT_EVIDENCE=PASS scanned={len(tracked)} findings={len(findings)} exact_groups={len(exact_groups)} normalized_groups={len(near_groups)}")
PY
then
  status=$?
  fail "engineer_audit_failed_or_timed_out_${status}" "$status"
fi

printf 'AUDIT_STATUS=PASS job=%s\n' "$JOB_ID"
printf 'RESULT=PASS job=%s\n' "$JOB_ID"
