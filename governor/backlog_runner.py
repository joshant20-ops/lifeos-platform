#!/usr/bin/env python3
"""Persistent, single-flight GitHub backlog dispatcher for LifeOS."""
from __future__ import annotations

import base64
import datetime as dt
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

REPO_FULL = os.environ.get("LIFEOS_BACKLOG_GITHUB_REPO", "joshant20-ops/lifeos-platform")
GOV = os.environ.get("LIFEOS_BACKLOG_GOVERNOR", "http://127.0.0.1:8790").rstrip("/")
STATE_DIR = Path(os.environ.get("LIFEOS_BACKLOG_STATE", "/var/lib/lifeos-backlog-runner"))
STATE = STATE_DIR / "state.json"
CENTRAL_ISSUE = int(os.environ.get("LIFEOS_BACKLOG_CENTRAL_ISSUE", "24"))
RETRY_SECONDS = max(86400, int(os.environ.get("LIFEOS_BACKLOG_RETRY_SECONDS", "86400")))
ISSUE_6_JOBS = ("000ed1030609", "bdb436220936", "2ed8008ab644", "b38c21b43b66", "eb616e077179", "482ade0c9757")
TERMINAL = {"PASS", "FAIL", "BLOCKED", "CANCELLED", "ERROR", "COMPLETED"}
INCOMPLETE = {"BLOCKED", "WAITING_HUMAN", "WAITING_DEPENDENCY", "RETRY", "FAIL", "ERROR"}


def now(): return int(time.time())
def iso(ts): return dt.datetime.fromtimestamp(int(ts), dt.timezone.utc).isoformat().replace("+00:00", "Z")
def log(message): print(message, flush=True)


def gh(*args, check=True):
    cp = subprocess.run(["gh", *args], text=True, capture_output=True, timeout=90)
    if check and cp.returncode:
        raise RuntimeError(f"gh {' '.join(args)} rc={cp.returncode}: {(cp.stderr or '').strip()[:500]}")
    return cp


def api(path, method="GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{GOV}{path}", data=data, method=method)
    if data is not None: req.add_header("Content-Type", "application/json")
    if method == "POST" and isinstance(body, dict) and "dispatch_builder" in body:
        token = (Path(os.environ.get("CREDENTIALS_DIRECTORY", "")) / "backlog-dispatcher.token").read_text().strip()
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=45) as response:
        return json.load(response)


def empty_state(): return {"version": 2, "active": None, "issues": {}, "attempts": []}


def load_state():
    try: value = json.loads(STATE.read_text())
    except (OSError, ValueError): value = empty_state()
    # Migrate the old single-active-record format without losing the in-flight job.
    if "version" not in value:
        active = value if value.get("issue") and value.get("job_id") else None
        value = empty_state(); value["active"] = active
    value.setdefault("issues", {}); value.setdefault("attempts", []); value.setdefault("active", None)
    migrate_issue_6(value)
    return value


def migrate_issue_6(state, timestamp=None):
    entry = state["issues"].get("6")
    if entry: return
    stamp = int(timestamp or now())
    state["issues"]["6"] = {
        "retry_count": len(ISSUE_6_JOBS), "retry_after": stamp + RETRY_SECONDS,
        "work_state": "BLOCKED", "issue_validity": "BLOCKED",
        "barrier": "repeated blocked attempts migrated: " + ",".join(ISSUE_6_JOBS),
        "next_autonomous_action": "revalidate after cooldown or concrete barrier-clear evidence",
        "last_job_id": ISSUE_6_JOBS[-1], "attempted_at": stamp,
    }


def save_state(value):
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, STATE)


def labels(issue): return {str(x.get("name", "")).lower() for x in issue.get("labels", [])}
def private_issue(issue): return bool(labels(issue) & {"risk:local-only", "privacy:local-only", "local-only", "private", "private-data", "financial-private", "paperless-private"})


def priority(issue):
    title, ls = issue.get("title", ""), labels(issue)
    rank = next((n for n in range(6) if re.match(rf"^P{n}\b", title, re.I) or f"priority:p{n}" in ls or f"p{n}" in ls), 6) * 100
    if "lifeos-engineer-ready" in ls: rank -= 25
    return rank, issue.get("created_at", ""), int(issue["number"])


def get_open_issues():
    data = json.loads(gh("api", f"repos/{REPO_FULL}/issues?state=open&per_page=100", "--paginate").stdout or "[]")
    return [item for item in data if "pull_request" not in item]


def active_governor_jobs():
    jobs = api("/jobs")
    if isinstance(jobs, dict): jobs = jobs.get("jobs", jobs.get("items", []))
    return [j for j in jobs if str(j.get("status", "")).upper() in {"QUEUED", "RUNNING"}]


def field(text, name):
    values = re.findall(rf"(?m)^{re.escape(name)}\s*=\s*(.*?)\s*$", text)
    return values[-1].strip() if values else ""


def final_evidence(job): return "\n".join(str(i.get("evidence", "")) for i in job.get("iterations", []))
def issue_comment(number, text): gh("issue", "comment", str(number), "--repo", REPO_FULL, "--body", text)
def issue_close(number, reason): gh("issue", "close", str(number), "--repo", REPO_FULL, "--comment", reason)


def add_discovered_issues(evidence, parent, open_issues):
    raw = field(evidence, "DISCOVERED_ISSUES_JSON_B64")
    if not raw or raw.lower() in {"none", "null"}: return []
    try: items = json.loads(base64.b64decode(raw, validate=True).decode())
    except Exception as exc:
        log(f"DISCOVERED_ISSUES_PARSE=FAIL {type(exc).__name__}"); return []
    by_title = {re.sub(r"\s+", " ", i.get("title", "").strip().casefold()): i for i in open_issues}
    changed = []
    for item in items[:10]:
        if not isinstance(item, dict) or not item.get("title"): continue
        title = str(item["title"])[:240]; key = re.sub(r"\s+", " ", title.strip().casefold())
        if key in by_title:
            changed.append(f"#{by_title[key]['number']} (existing)"); continue
        body = str(item.get("body") or "Discovered during autonomous backlog processing.")[:12000]
        label = "risk:local-only" if str(item.get("privacy", "normal")).lower() == "local-only" else "risk:normal"
        cp = gh("issue", "create", "--repo", REPO_FULL, "--title", title, "--body", body + f"\n\nDiscovered while processing #{parent}.\nCentral build list: #{CENTRAL_ISSUE}.", "--label", "lifeos-engineer-ready", "--label", label, check=False)
        if cp.returncode == 0: changed.append((cp.stdout or "").strip())
    return changed


def terminal_record(job, active, previous, timestamp=None):
    stamp = int(timestamp or now()); status = str(job.get("status", "")).upper(); evidence = final_evidence(job)
    work = (field(evidence, "LIFEOS_WORK_STATE") or ("PASS" if status == "PASS" else "BLOCKED")).upper()
    validity = (field(evidence, "ISSUE_VALIDITY") or "UNKNOWN").upper()
    barrier = field(evidence, "BARRIER") or str(job.get("blocked_reason") or job.get("stage_detail") or "none")
    action = field(evidence, "NEXT_AUTONOMOUS_ACTION") or field(evidence, "NEXT_RUNTIME_CHECK") or "re-prioritise backlog"
    incomplete = work in INCOMPLETE or status in {"FAIL", "BLOCKED", "ERROR", "CANCELLED"}
    retries = int((previous or {}).get("retry_count", 0)) + (1 if incomplete else 0)
    retry_after = stamp + RETRY_SECONDS if incomplete else None
    return {"issue": int(active["issue"]), "job_id": active["job_id"], "attempted_at": int(active.get("started", stamp)), "finished_at": stamp, "final_status": status, "issue_validity": validity, "work_state": work, "barrier": barrier[:1200], "retry_count": retries, "retry_after": retry_after, "next_autonomous_action": action[:1200], "result": field(evidence, "RESULT") or status, "tests": field(evidence, "TESTS") or "not reported", "commits": field(evidence, "CANONICAL_COMMIT") or field(evidence, "COMMITS") or "not reported", "runtime_verification": field(evidence, "LIVE_DEPLOYMENT") or "not reported"}


def finish_active(state, open_issues):
    active = state.get("active")
    if not active: return False
    try: job = api(f"/jobs/{active['job_id']}")
    except Exception as exc:
        log(f"ACTIVE_LOOKUP=RETRY {type(exc).__name__}"); return True
    status = str(job.get("status", "")).upper()
    if status not in TERMINAL:
        log(f"ACTIVE_JOB={active['job_id']} ISSUE=#{active['issue']} STATUS={status} STAGE={job.get('stage','?')}"); return True
    number = int(active["issue"]); record = terminal_record(job, active, state["issues"].get(str(number)))
    discovered = add_discovered_issues(final_evidence(job), number, open_issues)
    retry = iso(record["retry_after"]) if record["retry_after"] else "none"
    checkpoint = ("### LifeOS autonomous backlog checkpoint\n"
        f"- Checked: current issue validity and requested engineering outcome.\n- Why: terminal processing for dispatched backlog work.\n"
        f"- Changed/result: `{record['result']}`; commits: `{record['commits']}`\n- LifeOS job: `{record['job_id']}`; record: `governor/job_records/{record['job_id']}.json`\n"
        f"- Tests: {record['tests']}\n- Deployment/runtime verification: {record['runtime_verification']}\n"
        f"- Completion: `{record['final_status']}` / `{record['work_state']}`; validity: `{record['issue_validity']}`\n"
        f"- Exact barrier: {record['barrier']}\n- Next autonomous action: {record['next_autonomous_action']}\n"
        f"- Retry after: `{retry}`; retry count: `{record['retry_count']}`\n- Discovered issues created or linked: {len(discovered)}\n\nRaw logs, secrets, and private content are omitted.")
    try:
        issue_comment(number, checkpoint)
        if record["work_state"] == "PASS" and record["issue_validity"] in {"VALID", "ALREADY_COMPLETE", "SUPERSEDED"}: issue_close(number, f"LifeOS job `{record['job_id']}` completed this issue.")
    except Exception as exc:
        log(f"ISSUE_UPDATE=FAIL {type(exc).__name__}: {exc}"); return True
    state["attempts"].append(record); state["attempts"] = state["attempts"][-500:]
    state["issues"][str(number)] = {k: record[k] for k in ("retry_count", "retry_after", "work_state", "issue_validity", "barrier", "next_autonomous_action", "job_id", "attempted_at") if k in record}
    state["active"] = None; save_state(state)
    log(f"FINISHED_JOB={record['job_id']} ISSUE=#{number} RETRY_AFTER={retry}")
    return False


def eligible(issue, state, timestamp=None):
    number = int(issue["number"]); ls = labels(issue)
    if number == CENTRAL_ISSUE or ls & {"lifeos-engineer-ignore", "do-not-automate"}: return False
    # Labels are live barrier evidence. A human/dependency-blocked issue cannot
    # become eligible merely because time elapsed; clearing the label is the
    # concrete evidence which permits reconsideration after its cooldown.
    if ls & {"blocked", "waiting-human", "waiting-dependency"}: return False
    entry = state["issues"].get(str(number), {})
    if entry.get("work_state") == "PASS": return False
    retry_after = entry.get("retry_after")
    return not retry_after or int(retry_after) <= int(timestamp or now())


def choose_issue(issues, state, timestamp=None):
    candidates = [i for i in issues if eligible(i, state, timestamp)]
    return sorted(candidates, key=priority)[0] if candidates else None


def submit_issue(issue, state):
    number = int(issue["number"]); is_private = private_issue(issue); body = str(issue.get("body") or "")[:14000]
    privacy_note = "This issue is local-only; never transmit its contents outside the LAN." if is_private else "This is ordinary engineering work; unrelated private data remains out of scope."
    prompt = f"""Process GitHub issue #{number} in {REPO_FULL}: {issue.get('title','')}\n\n{privacy_note}\n\nFirst revalidate current relevance and dependencies, then implement and test safe work.\n\nISSUE BODY:\n{body}\n\nEvery final iteration MUST emit:\nISSUE_VALIDITY=VALID|ALREADY_COMPLETE|SUPERSEDED|BLOCKED\nLIFEOS_WORK_STATE=PASS|BLOCKED|WAITING_HUMAN|WAITING_DEPENDENCY|SUPERSEDED\nBARRIER=<exact barrier or none>\nNEXT_AUTONOMOUS_ACTION=<next action>\nDISCOVERED_ISSUES_JSON_B64=<base64 JSON list or none>\n"""
    # Backlog dispatch is intentionally asynchronous. The dispatcher records the
    # returned job ID immediately and exits; the Governor owns the long-running
    # engineering execution. This prevents the oneshot runner's HTTP timeout from
    # being mistaken for a failed dispatch while the job continues successfully.
    job = api("/jobs?async=1", "POST", {"request": prompt, "dispatch_builder": "local" if is_private else "normal"})
    job_id = str(job.get("id") or "")
    if not job_id: raise RuntimeError("governor returned no job id")
    state["active"] = {"issue": number, "job_id": job_id, "started": now()}; save_state(state)
    issue_comment(number, f"### LifeOS autonomous backlog start\n- Selected after a complete open-issue refresh and priority/dependency eligibility pass.\n- LifeOS job: `{job_id}`\n- Route: `{'local-only' if is_private else 'normal'}`\n- State: `IN_PROGRESS`")
    log(f"SUBMITTED_JOB={job_id} ISSUE=#{number}")


def main():
    state = load_state(); save_state(state)
    issues = get_open_issues()  # refresh before terminal processing and reprioritisation
    if state.get("active") and finish_active(state, issues): return 0
    issues = get_open_issues()  # terminal changes/discoveries may have changed the backlog
    if active_governor_jobs(): log("DISPATCH=WAIT governor_has_active_job"); return 0
    issue = choose_issue(issues, state)
    if not issue: log("DISPATCH=IDLE no_eligible_open_issues"); return 0
    log(f"PRIORITY_RECHECK=PASS selected=#{issue['number']}"); submit_issue(issue, state); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        log(f"RESULT=FAIL TYPE={type(exc).__name__} REASON={str(exc)[:1000]}"); raise