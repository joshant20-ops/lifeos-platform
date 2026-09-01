#!/usr/bin/env bash
set -Eeuo pipefail

REPO=/home/joshan/lifeos-platform
WORKER=/usr/local/libexec/lifeos-backlog-runner
STATE_DIR=/var/lib/lifeos-backlog-runner
DISPATCH_TOKEN=/etc/lifeos/backlog-dispatcher.token
SERVICE=/etc/systemd/system/lifeos-backlog-runner.service
TIMER=/etc/systemd/system/lifeos-backlog-runner.timer
GOVERNOR=http://127.0.0.1:8790
GITHUB_REPO=joshant20-ops/lifeos-platform

fail() { printf 'RESULT=FAIL\nREASON=%s\n' "$1" >&2; exit 1; }
[[ $(id -u) -eq 0 ]] || fail must_run_via_sudo
[[ $(hostname) == Docker ]] || fail must_run_on_pi5_Docker
[[ -d "$REPO/.git" ]] || fail canonical_repo_missing
command -v python3 >/dev/null || fail python3_missing
[[ -f "$REPO/governor/backlog_runner.py" ]] || fail backlog_runner_source_missing

# The dispatcher needs authenticated GitHub Issues API access for reading,
# commenting, closing and creating issues. Git-over-SSH authentication alone
# cannot provide those API operations, so bootstrap the official GitHub CLI as
# the smallest mature OTS client rather than embedding a custom token client.
if ! command -v gh >/dev/null 2>&1; then
    command -v apt-get >/dev/null || fail apt_get_missing_for_gh_install
    printf 'GITHUB_CLI=INSTALLING\n'
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y gh
fi
command -v gh >/dev/null || fail gh_install_failed

# Reuse an existing joshan GitHub CLI session. Activation remains non-interactive;
# an absent user-owned GitHub session is reported as a fail-closed prerequisite.
if ! runuser -u joshan -- gh auth status --hostname github.com >/dev/null 2>&1; then
    fail gh_auth_unavailable_for_joshan
fi
runuser -u joshan -- gh auth status --hostname github.com >/dev/null 2>&1 || fail gh_auth_unavailable_for_joshan
runuser -u joshan -- gh api "repos/$GITHUB_REPO" >/dev/null 2>&1 || fail gh_repo_api_unavailable
curl -fsS --max-time 5 "$GOVERNOR/health" >/dev/null || fail governor_unhealthy

install -d -m 0755 /usr/local/libexec
install -d -o joshan -g joshan -m 0750 "$STATE_DIR"
install -d -m 0755 /etc/lifeos
if [[ ! -s "$DISPATCH_TOKEN" ]]; then
    umask 077
    python3 -c 'import secrets; print(secrets.token_urlsafe(48))' >"$DISPATCH_TOKEN"
fi
chown root:root "$DISPATCH_TOKEN"
chmod 0600 "$DISPATCH_TOKEN"

cat >"$WORKER" <<'PY'
#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO_FULL = os.environ.get("LIFEOS_BACKLOG_GITHUB_REPO", "joshant20-ops/lifeos-platform")
GOV = os.environ.get("LIFEOS_BACKLOG_GOVERNOR", "http://127.0.0.1:8790").rstrip("/")
STATE_DIR = Path(os.environ.get("LIFEOS_BACKLOG_STATE", "/var/lib/lifeos-backlog-runner"))
STATE = STATE_DIR / "state.json"
CENTRAL_ISSUE = int(os.environ.get("LIFEOS_BACKLOG_CENTRAL_ISSUE", "24"))
MAX_ISSUE_BODY = 14000


def log(msg):
    print(msg, flush=True)


def gh(*args, check=True):
    cp = subprocess.run(["gh", *args], text=True, capture_output=True, timeout=90)
    if check and cp.returncode:
        raise RuntimeError(f"gh {' '.join(args)} rc={cp.returncode}: {(cp.stderr or '').strip()[:500]}")
    return cp


def api(path, method="GET", body=None):
    url = f"{GOV}{path}"
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    if method == "POST" and isinstance(body, dict) and "dispatch_builder" in body:
        credential_dir = os.environ.get("CREDENTIALS_DIRECTORY", "")
        token = (Path(credential_dir) / "backlog-dispatcher.token").read_text().strip()
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=45) as r:
        return json.load(r)


def load_state():
    try:
        return json.loads(STATE.read_text())
    except Exception:
        return {}


def save_state(value):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, STATE)


def issue_comment(number, text):
    gh("issue", "comment", str(number), "--repo", REPO_FULL, "--body", text)


def issue_close(number, reason):
    gh("issue", "close", str(number), "--repo", REPO_FULL, "--comment", reason)


def labels(issue):
    return {str(x.get("name", "")).lower() for x in issue.get("labels", [])}


def private_issue(issue):
    ls = labels(issue)
    return bool(ls & {
        "risk:local-only", "privacy:local-only", "local-only", "private",
        "private-data", "financial-private", "paperless-private"
    })


def priority(issue):
    title = issue.get("title", "")
    ls = labels(issue)
    for n in range(0, 6):
        if re.match(rf"^P{n}\b", title, re.I) or f"priority:p{n}" in ls or f"p{n}" in ls:
            base = n * 100
            break
    else:
        base = 600
    if "lifeos-engineer-ready" in ls:
        base -= 25
    if "blocked" in ls or "waiting-human" in ls or "waiting-dependency" in ls:
        base += 500
    return (base, issue.get("created_at", ""), int(issue["number"]))


def get_open_issues():
    cp = gh("api", f"repos/{REPO_FULL}/issues?state=open&per_page=100", "--paginate")
    data = json.loads(cp.stdout or "[]")
    issues = [x for x in data if "pull_request" not in x]
    return issues


def active_governor_jobs():
    jobs = api("/jobs")
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", jobs.get("items", []))
    return [j for j in jobs if str(j.get("status", "")).upper() in {"QUEUED", "RUNNING"}]


def final_evidence(job):
    return "\n".join(str(i.get("evidence", "")) for i in job.get("iterations", []))


def field(text, name):
    vals = re.findall(rf"(?m)^{re.escape(name)}\s*=\s*(.*?)\s*$", text)
    return vals[-1].strip() if vals else ""


def add_discovered_issues(evidence, parent):
    raw = field(evidence, "DISCOVERED_ISSUES_JSON_B64")
    if not raw or raw.lower() in {"none", "null"}:
        return []
    try:
        items = json.loads(base64.b64decode(raw, validate=True).decode())
    except Exception as exc:
        log(f"DISCOVERED_ISSUES_PARSE=FAIL {type(exc).__name__}")
        return []
    created = []
    for item in items[:10]:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        title = str(item["title"])[:240]
        body = str(item.get("body") or "Discovered during autonomous backlog processing.")[:12000]
        privacy = str(item.get("privacy") or "normal").lower()
        label = "risk:local-only" if privacy == "local-only" else "risk:normal"
        cp = gh("issue", "create", "--repo", REPO_FULL, "--title", title,
                "--body", body + f"\n\nDiscovered while processing #{parent}.",
                "--label", "lifeos-engineer-ready", "--label", label, check=False)
        if cp.returncode == 0:
            created.append((cp.stdout or "").strip())
    return created


def finish_active(st):
    job_id = st.get("job_id")
    issue_no = st.get("issue")
    if not job_id or not issue_no:
        return False
    try:
        job = api(f"/jobs/{job_id}")
    except Exception as exc:
        log(f"ACTIVE_LOOKUP=RETRY {type(exc).__name__}")
        return True
    status = str(job.get("status", "")).upper()
    if status in {"QUEUED", "RUNNING"}:
        log(f"ACTIVE_JOB={job_id} ISSUE=#{issue_no} STATUS={status} STAGE={job.get('stage','?')}")
        return True

    evidence = final_evidence(job)
    work_state = field(evidence, "LIFEOS_WORK_STATE") or ("PASS" if status == "PASS" else "BLOCKED")
    validity = field(evidence, "ISSUE_VALIDITY") or "UNKNOWN"
    next_action = field(evidence, "NEXT_AUTONOMOUS_ACTION") or field(evidence, "NEXT_RUNTIME_CHECK") or "re-prioritise backlog"
    barrier = field(evidence, "BARRIER") or str(job.get("blocked_reason") or job.get("stage_detail") or "none")
    record = f"governor/job_records/{job_id}.json"
    created = add_discovered_issues(evidence, int(issue_no))
    comment = (
        "### LifeOS autonomous backlog checkpoint\n"
        f"- `LIFEOS_WORK_STATE={work_state}`\n"
        f"- `ISSUE_VALIDITY={validity}`\n"
        f"- LifeOS job: `{job_id}` (`{status}`)\n"
        f"- Machine record: `{record}`\n"
        f"- Barrier: {barrier[:1200]}\n"
        f"- `NEXT_AUTONOMOUS_ACTION={next_action[:1200]}`\n"
        f"- Newly discovered issues created: {len(created)}\n\n"
        "Large raw logs and secrets are intentionally omitted."
    )
    try:
        issue_comment(int(issue_no), comment)
        if status == "PASS" and work_state.upper() == "PASS" and validity.upper() in {"VALID", "ALREADY_COMPLETE", "SUPERSEDED"}:
            issue_close(int(issue_no), f"LifeOS autonomous job `{job_id}` completed this issue with `{validity}` / PASS.")
    except Exception as exc:
        log(f"ISSUE_UPDATE=FAIL {type(exc).__name__}: {exc}")
        return True
    save_state({})
    log(f"FINISHED_JOB={job_id} ISSUE=#{issue_no} STATUS={status} WORK_STATE={work_state}")
    return False


def choose_issue():
    issues = get_open_issues()
    candidates = []
    for i in issues:
        if int(i["number"]) == CENTRAL_ISSUE:
            continue
        ls = labels(i)
        if "lifeos-engineer-ignore" in ls or "do-not-automate" in ls:
            continue
        candidates.append(i)
    candidates.sort(key=priority)
    return candidates[0] if candidates else None


def submit_issue(issue):
    number = int(issue["number"])
    is_private = private_issue(issue)
    privacy_note = (
        "This issue is classified local-only. Do not use cloud services or transmit issue/private contents outside the LAN. "
        if is_private else
        "This is ordinary engineering work. Cloud Codex is permitted, but do not access or transmit unrelated private documents, financial records, credentials, or household-private data. "
    )
    body = str(issue.get("body") or "")[:MAX_ISSUE_BODY]
    prompt = f"""Process GitHub issue #{number} in {REPO_FULL}: {issue.get('title','')}

{privacy_note}

FIRST: independently confirm whether the issue is still valid against current canonical source, live state where safely readable, prior issue comments, and existing run records. Do not assume the issue is still current.

THEN: if valid and safely actionable, diagnose the root cause and complete as much of the correction as possible. Iterate on ordinary software/config/test failures rather than treating them as permanent blockers. Use mature OTS solutions in preference to custom code when they materially improve reliability, maintenance, power use, or security.

If you hit a genuine human/physical/credential/privilege/dependency boundary, stop that issue at the boundary after completing all safe preparatory work. Preserve evidence and do not weaken policy.

If you discover additional distinct defects or build requirements, report them for creation as new GitHub issues.

ISSUE BODY (authoritative but may be stale):
{body}

Every final iteration MUST emit these exact fields:
ISSUE_VALIDITY=VALID|ALREADY_COMPLETE|SUPERSEDED|BLOCKED
LIFEOS_WORK_STATE=PASS|BLOCKED|WAITING_HUMAN|WAITING_DEPENDENCY|SUPERSEDED
BARRIER=<none or concise exact barrier>
NEXT_AUTONOMOUS_ACTION=<next safe action>
DISCOVERED_ISSUES_JSON_B64=<base64 JSON list of objects with title, body, privacy; or none>

Also ensure the normal redacted governor/job_records/<job_id>.json mechanism captures the run. Do not close or modify GitHub issues directly; the local backlog dispatcher will write the authoritative issue checkpoint after the run.
"""
    payload = {"request": prompt, "dispatch_builder": "local" if is_private else "normal"}
    job = api("/jobs", "POST", payload)
    job_id = str(job.get("id") or "")
    if not job_id:
        raise RuntimeError("governor returned no job id")
    issue_comment(number, (
        "### LifeOS autonomous backlog start\n"
        "- `LIFEOS_WORK_STATE=IN_PROGRESS`\n"
        f"- Selected after fresh backlog re-prioritisation.\n"
        f"- LifeOS job: `{job_id}`\n"
        f"- Privacy route: `{'local-only' if is_private else 'normal'}`\n"
        "- First action is to revalidate that this issue is still current before changing anything."
    ))
    save_state({"issue": number, "job_id": job_id, "started": int(time.time())})
    log(f"SUBMITTED_JOB={job_id} ISSUE=#{number} PRIVACY={'local-only' if is_private else 'normal'}")


def main():
    st = load_state()
    if st and finish_active(st):
        return 0
    active = active_governor_jobs()
    if active:
        log("DISPATCH=WAIT governor_has_active_job " + ",".join(str(j.get("id")) for j in active))
        return 0
    issue = choose_issue()
    if not issue:
        log("DISPATCH=IDLE no_open_issues")
        return 0
    log(f"PRIORITY_CHECK=PASS selected=#{issue['number']} title={issue.get('title','')[:120]}")
    submit_issue(issue)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"RESULT=FAIL TYPE={type(exc).__name__} REASON={str(exc)[:1000]}")
        raise
PY
# The heredoc above is retained as a rollback snapshot for older checkouts. The
# canonical, unit-tested source always wins for installation.
install -m 0755 "$REPO/governor/backlog_runner.py" "$WORKER"
chmod 0755 "$WORKER"
chown root:root "$WORKER"
python3 -m py_compile "$WORKER"

cat >"$SERVICE" <<EOF
[Unit]
Description=LifeOS autonomous GitHub backlog dispatcher
After=network-online.target lifeos-autonomous-agent.service
Wants=network-online.target

[Service]
Type=oneshot
User=joshan
Group=joshan
WorkingDirectory=$REPO
Environment=HOME=/home/joshan
Environment=LIFEOS_BACKLOG_GITHUB_REPO=$GITHUB_REPO
Environment=LIFEOS_BACKLOG_GOVERNOR=$GOVERNOR
Environment=LIFEOS_BACKLOG_STATE=$STATE_DIR
Environment=LIFEOS_BACKLOG_CENTRAL_ISSUE=24
ExecStart=$WORKER
TimeoutStartSec=300
Nice=5
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ReadWritePaths=$STATE_DIR $REPO
ProtectHome=read-only
LoadCredential=backlog-dispatcher.token:$DISPATCH_TOKEN
EOF

install -d -m 0755 /etc/systemd/system/lifeos-autonomous-agent.service.d
cat >/etc/systemd/system/lifeos-autonomous-agent.service.d/backlog-dispatcher.conf <<EOF
[Service]
LoadCredential=backlog-dispatcher.token:$DISPATCH_TOKEN
EOF

cat >"$TIMER" <<'EOF'
[Unit]
Description=Run LifeOS autonomous backlog dispatcher every 10 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=10min
AccuracySec=30s
Persistent=true
Unit=lifeos-backlog-runner.service

[Install]
WantedBy=timers.target
EOF

systemctl daemon-reload
systemctl restart lifeos-autonomous-agent.service
for _ in $(seq 1 15); do
    curl -fsS --max-time 3 "$GOVERNOR/health" >/dev/null 2>&1 && break
    sleep 1
done
curl -fsS --max-time 3 "$GOVERNOR/health" >/dev/null || fail governor_restart_unhealthy
systemctl enable --now lifeos-backlog-runner.timer
systemctl start lifeos-backlog-runner.service
sleep 3

printf '\n===== BACKLOG RUNNER STATUS =====\n'
systemctl --no-pager --full status lifeos-backlog-runner.service || true
printf '\n===== TIMER =====\n'
systemctl list-timers --all --no-pager lifeos-backlog-runner.timer || true
printf '\n===== STATE =====\n'
if [[ -s "$STATE_DIR/state.json" ]]; then cat "$STATE_DIR/state.json"; else echo '{}'; fi
printf '\n===== RECENT LOG =====\n'
journalctl -u lifeos-backlog-runner.service -n 40 --no-pager || true
printf '\n===== GOVERNOR ACTIVE JOBS =====\n'
curl -fsS --max-time 10 "$GOVERNOR/jobs" | python3 -c '
import json,sys
x=json.load(sys.stdin); x=x.get("jobs",x.get("items",[])) if isinstance(x,dict) else x
for j in x:
    if str(j.get("status","")).upper() in {"QUEUED","RUNNING"}:
        print(f"{j.get('id')} | {j.get('status')} | {j.get('stage')} | {j.get('privacy')}")
' || true

printf '\nRESULT=PASS\n'
printf 'BACKLOG_RUNNER=ACTIVE\n'
printf 'CADENCE=10min\n'
printf 'NEXT_RUNTIME_CHECK=systemctl status lifeos-backlog-runner.timer && journalctl -u lifeos-backlog-runner.service -n 50 --no-pager\n'
