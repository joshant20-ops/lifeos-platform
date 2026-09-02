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
MANUAL_HIGH_PRIORITY_LABEL = "lifeos-high-priority"


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


def empty_state(): return {"version": 4, "active": None, "issues": {}, "attempts": []}


def _clean_id(value):
    value = re.sub(r"[^a-zA-Z0-9_.-]+", "-", str(value or "").strip()).strip("-")
    if not value or len(value) > 80: raise ValueError("plan identifiers must be 1-80 safe characters")
    return value


def validate_plan(raw, issue_number):
    """Validate the builder-produced plan before it becomes scheduler authority."""
    if not isinstance(raw, dict) or not isinstance(raw.get("milestones"), list) or not raw["milestones"]:
        raise ValueError("plan requires at least one milestone")
    plan = {"schema_version": 1, "issue": int(issue_number), "revision": int(raw.get("revision", 1)),
            "state": "IN_PROGRESS", "created_at": iso(now()), "milestones": []}
    seen = set()
    for mi, source_m in enumerate(raw["milestones"], 1):
        mid = _clean_id(source_m.get("id") or f"m{mi}")
        if mid in seen: raise ValueError(f"duplicate id: {mid}")
        seen.add(mid); targets = source_m.get("targets")
        if not isinstance(targets, list) or not targets: raise ValueError(f"milestone {mid} has no targets")
        milestone = {"id": mid, "title": str(source_m.get("title") or mid)[:240],
            "mandatory": bool(source_m.get("mandatory", True)), "state": "PLANNED",
            "verification": str(source_m.get("verification") or "mandatory targets pass")[:2000], "targets": []}
        for ti, source_t in enumerate(targets, 1):
            tid = _clean_id(source_t.get("id") or f"{mid}.t{ti}")
            if tid in seen: raise ValueError(f"duplicate id: {tid}")
            seen.add(tid); acceptance = source_t.get("acceptance_criteria")
            if not isinstance(acceptance, list) or not acceptance or not all(str(x).strip() for x in acceptance):
                raise ValueError(f"target {tid} requires acceptance criteria")
            milestone["targets"].append({"id": tid, "title": str(source_t.get("title") or tid)[:240],
                "state": "PLANNED", "mandatory": bool(source_t.get("mandatory", True)),
                "depends_on": [_clean_id(x) for x in source_t.get("depends_on", [])],
                "acceptance_criteria": [str(x)[:1000] for x in acceptance],
                "runtime_verification_required": bool(source_t.get("runtime_verification_required", False)),
                "attempts": 0, "recovery_attempts": 0, "lineage_depth": 0,
                "parent_target_id": None, "blocker_class": None, "evidence": []})
        plan["milestones"].append(milestone)
    ids = {t["id"] for m in plan["milestones"] for t in m["targets"]}
    for target in plan_targets(plan):
        if set(target["depends_on"]) - ids or target["id"] in target["depends_on"]:
            raise ValueError(f"invalid dependencies for {target['id']}")
    return plan


def plan_targets(plan): return [t for m in plan.get("milestones", []) for t in m.get("targets", [])]


def next_target(plan):
    targets = plan_targets(plan); passed = {t["id"] for t in targets if t["state"] == "PASS"}
    # Continue safe independent work before spending another job on diagnosis.
    ready = (t for t in targets if t["state"] in {"PLANNED", "READY"}
             and set(t["depends_on"]) <= passed)
    return next(ready, None) or next((t for t in targets if t["state"] in {"FAILED", "BLOCKED"}
                                     and int(t.get("recovery_attempts", 0)) < 3
                                     and set(t["depends_on"]) <= passed), None)


def apply_recovery(plan, failed, recovery, job_id):
    """Apply a bounded builder diagnosis while retaining every durable PASS."""
    if failed.get("state") not in {"FAILED", "BLOCKED"}: raise ValueError("recovery target is not failed or blocked")
    attempts = int(failed.get("recovery_attempts", 0)) + 1
    failed["recovery_attempts"] = attempts
    action = str(recovery.get("action", "")).lower()
    blocker_class = _clean_id(recovery.get("blocker_class") or "unknown")
    failed["blocker_class"] = blocker_class
    summary = str(recovery.get("diagnosis") or "no diagnosis supplied")[:2000]
    failed["evidence"].append({"job_id": job_id, "finished_at": iso(now()),
        "state": "DIAGNOSED", "summary": summary, "blocker_class": blocker_class})
    if action == "waiting_human":
        failed["state"] = "WAITING_HUMAN"; return
    if action == "retry":
        if attempts >= 3: failed["state"] = "BLOCKED"
        else: failed["state"] = "READY"
        return
    if action not in {"remediate", "subdivide"}: raise ValueError("unsupported recovery action")
    depth = int(failed.get("lineage_depth", 0)) + 1
    additions = recovery.get("targets")
    if depth > 3 or attempts > 3: failed["state"] = "BLOCKED"; return
    if not isinstance(additions, list) or not 1 <= len(additions) <= 5:
        raise ValueError("recovery requires 1-5 replacement targets")
    milestone = next((m for m in plan["milestones"] if failed in m["targets"]), None)
    if not milestone: raise ValueError("failed target has no milestone")
    existing = {t["id"] for t in plan_targets(plan)}; replacements = []
    for source in additions:
        tid = _clean_id(source.get("id"))
        acceptance = source.get("acceptance_criteria")
        if tid in existing or not isinstance(acceptance, list) or not acceptance or not all(str(x).strip() for x in acceptance):
            raise ValueError("recovery targets require unique ids and acceptance criteria")
        dependencies = [_clean_id(x) for x in source.get("depends_on", failed["depends_on"])]
        replacement = {"id": tid, "title": str(source.get("title") or tid)[:240], "state": "PLANNED",
            "mandatory": bool(failed.get("mandatory", True)), "depends_on": dependencies,
            "acceptance_criteria": [str(x)[:1000] for x in acceptance],
            "runtime_verification_required": bool(source.get("runtime_verification_required", False)),
            "attempts": 0, "recovery_attempts": 0, "lineage_depth": depth,
            "parent_target_id": failed["id"], "blocker_class": None, "evidence": []}
        replacements.append(replacement); existing.add(tid)
    allowed = {t["id"] for t in plan_targets(plan)} | {t["id"] for t in replacements}
    if any(set(t["depends_on"]) - allowed or t["id"] in t["depends_on"] for t in replacements):
        raise ValueError("recovery target dependencies are invalid")
    terminal_ids = [t["id"] for t in replacements
                    if not any(t["id"] in other["depends_on"] for other in replacements)]
    for target in plan_targets(plan):
        if target is not failed and failed["id"] in target["depends_on"]:
            target["depends_on"] = [x for x in target["depends_on"] if x != failed["id"]] + terminal_ids
    offset = milestone["targets"].index(failed)
    milestone["targets"][offset:offset] = replacements
    failed["state"] = "SUPERSEDED"


def refresh_plan(plan):
    for milestone in plan["milestones"]:
        required = [t for t in milestone["targets"] if t["mandatory"] and t["state"] != "SUPERSEDED"]
        milestone["state"] = "PASS" if required and all(t["state"] == "PASS" for t in required) else "IN_PROGRESS"
    mandatory = [m for m in plan["milestones"] if m["mandatory"]]
    plan["state"] = "PASS" if mandatory and all(m["state"] == "PASS" for m in mandatory) else "IN_PROGRESS"
    return plan


def progress(plan):
    targets = [t for t in plan_targets(plan) if t["state"] != "SUPERSEDED"]; current = next_target(plan)
    return {"completed_targets": sum(t["state"] == "PASS" for t in targets), "total_targets": len(targets),
            "current_target": current["id"] if current else None, "state": plan.get("state", "IN_PROGRESS")}


def decode_field(evidence, name):
    raw = field(evidence, name)
    if not raw: raise ValueError(f"missing {name}")
    return json.loads(base64.b64decode(raw, validate=True).decode())


def apply_plan_result(entry, active, job):
    """Checkpoint planning/target output without discarding prior PASS targets."""
    evidence = final_evidence(job)
    if active.get("phase") == "planning":
        entry["plan"] = validate_plan(decode_field(evidence, "PLAN_JSON_B64"), active["issue"])
        entry["work_state"] = "IN_PROGRESS"; entry["retry_after"] = None
        return progress(entry["plan"])
    plan = entry["plan"]
    target = next((t for t in plan_targets(plan) if t["id"] == active.get("target_id")), None)
    if not target: raise ValueError("active target is absent from persisted plan")
    if active.get("phase") == "recovery":
        apply_recovery(plan, target, decode_field(evidence, "RECOVERY_PLAN_JSON_B64"), active["job_id"])
        refresh_plan(plan); entry["work_state"] = plan["state"]
        entry["barrier"] = target.get("blocker_class") or "none"
        entry["retry_after"] = None if next_target(plan) else entry.get("retry_after")
        return progress(plan)
    reported = (field(evidence, "TARGET_STATE") or "FAILED").upper()
    if reported == "PASS" and target["runtime_verification_required"] and field(evidence, "TARGET_RUNTIME_VERIFIED").upper() != "PASS":
        reported = "FAILED"
    target["state"] = reported if reported in {"PASS", "BLOCKED", "WAITING_HUMAN"} else "FAILED"
    target["evidence"].append({"job_id": active["job_id"], "finished_at": iso(now()),
        "state": target["state"], "summary": (field(evidence, "TARGET_EVIDENCE") or "not reported")[:2000]})
    refresh_plan(plan); entry["work_state"] = plan["state"]
    entry["barrier"] = field(evidence, "BARRIER") or "none"
    entry["retry_after"] = None if next_target(plan) else entry.get("retry_after")
    return progress(plan)


def load_state():
    try: value = json.loads(STATE.read_text())
    except (OSError, ValueError): value = empty_state()
    if "version" not in value:
        active = value if value.get("issue") and value.get("job_id") else None
        value = empty_state(); value["active"] = active
    value.setdefault("issues", {}); value.setdefault("attempts", []); value.setdefault("active", None); value["version"] = 4
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
    manual_tier = 0 if MANUAL_HIGH_PRIORITY_LABEL in ls else 1
    rank = next((n for n in range(6) if re.match(rf"^P{n}\b", title, re.I) or f"priority:p{n}" in ls or f"p{n}" in ls), 6) * 100
    if "lifeos-engineer-ready" in ls: rank -= 25
    # Manual high-priority is a tier only. Within that tier LifeOS still uses
    # the normal autonomous priority/dependency ordering.
    return manual_tier, rank, issue.get("created_at", ""), int(issue["number"])


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
    number = int(active["issue"]); entry = state["issues"].setdefault(str(number), {})
    try: plan_progress = apply_plan_result(entry, active, job)
    except Exception as exc:
        log(f"PLAN_CHECKPOINT=FAIL {type(exc).__name__}: {exc}"); return True
    record = terminal_record(job, active, entry)
    # A successful child job is not objective completion. The persisted gates decide that.
    record["work_state"] = entry.get("plan", {}).get("state", "IN_PROGRESS")
    discovered = add_discovered_issues(final_evidence(job), number, open_issues)
    retry = iso(record["retry_after"]) if record["retry_after"] else "none"
    checkpoint = ("### LifeOS autonomous backlog checkpoint\n"
        f"- Checked: current issue validity and requested engineering outcome.\n- Why: terminal processing for dispatched backlog work.\n"
        f"- Changed/result: `{record['result']}`; commits: `{record['commits']}`\n- LifeOS job: `{record['job_id']}`; record: `governor/job_records/{record['job_id']}.json`\n"
        f"- Tests: {record['tests']}\n- Deployment/runtime verification: {record['runtime_verification']}\n"
        f"- Completion: `{record['final_status']}` / `{record['work_state']}`; validity: `{record['issue_validity']}`\n"
        f"- Plan progress: `{plan_progress['completed_targets']}/{plan_progress['total_targets']}` targets; next: `{plan_progress['current_target'] or 'none'}`\n"
        f"- Exact barrier: {record['barrier']}\n- Next autonomous action: {record['next_autonomous_action']}\n"
        f"- Retry after: `{retry}`; retry count: `{record['retry_count']}`\n- Discovered issues created or linked: {len(discovered)}\n\nRaw logs, secrets, and private content are omitted.")
    try:
        issue_comment(number, checkpoint)
        if record["work_state"] == "PASS" and record["issue_validity"] in {"VALID", "ALREADY_COMPLETE", "SUPERSEDED"}: issue_close(number, f"LifeOS job `{record['job_id']}` completed all mandatory milestone gates for this issue.")
    except Exception as exc:
        log(f"ISSUE_UPDATE=FAIL {type(exc).__name__}: {exc}"); return True
    state["attempts"].append(record); state["attempts"] = state["attempts"][-500:]
    entry.update({k: record[k] for k in ("retry_count", "issue_validity", "barrier", "next_autonomous_action", "job_id", "attempted_at") if k in record})
    entry["retry_after"] = None if next_target(entry["plan"]) else record["retry_after"]
    state["active"] = None; save_state(state)
    log(f"FINISHED_JOB={record['job_id']} ISSUE=#{number} RETRY_AFTER={retry}")
    return False


def eligible(issue, state, timestamp=None):
    number = int(issue["number"]); ls = labels(issue)
    if number == CENTRAL_ISSUE or ls & {"lifeos-engineer-ignore", "do-not-automate"}: return False
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
    entry = state["issues"].setdefault(str(number), {}); plan = entry.get("plan")
    target = next_target(plan) if plan else None
    if not plan:
        phase = "planning"
        instruction = """Revalidate current repository/runtime relevance first. Decide whether a single target or dynamic decomposition is appropriate. Return PLAN_JSON_B64 containing a base64 JSON object with milestones[]. Each milestone requires id, title, mandatory, verification, and targets[]. Each target requires id, title, mandatory, depends_on, acceptance_criteria (non-empty list), and runtime_verification_required. Do not implement the objective in this job."""
    elif target and target["state"] == "FAILED":
        phase = "recovery"
        prior = target.get("evidence", [])[-1].get("summary", "not reported") if target.get("evidence") else "not reported"
        instruction = f"""Diagnose only failed target {target['id']}: {target['title']}\nPrior evidence: {prior}\nReturn RECOVERY_PLAN_JSON_B64 containing a base64 JSON object with action retry, remediate, subdivide, or waiting_human; blocker_class; diagnosis; and, for remediate/subdivide, 1-5 small replacement targets using the normal target fields. Do not implement work in this diagnosis job. Recovery is bounded to three attempts and lineage depth three; never split work to evade governance or approval boundaries."""
    elif target:
        phase = "target"; criteria = "\n".join(f"- {x}" for x in target["acceptance_criteria"])
        instruction = f"""Execute only target {target['id']}: {target['title']}\nAcceptance criteria:\n{criteria}\nDo not expand scope to the whole parent objective. Emit TARGET_STATE=PASS|FAILED|BLOCKED|WAITING_HUMAN and TARGET_EVIDENCE=<concise evidence>."""
    else: raise RuntimeError("plan has no eligible target")
    prompt = f"""Process GitHub issue #{number} in {REPO_FULL}: {issue.get('title','')}\nPlanning phase: {phase}\n\n{privacy_note}\n\n{instruction}\n\nPARENT ISSUE CONTEXT (context only):\n{body}\n\nEvery final iteration MUST emit:\nISSUE_VALIDITY=VALID|ALREADY_COMPLETE|SUPERSEDED|BLOCKED\nLIFEOS_WORK_STATE=PASS|BLOCKED|WAITING_HUMAN|WAITING_DEPENDENCY|SUPERSEDED\nBARRIER=<exact barrier or none>\nNEXT_AUTONOMOUS_ACTION=<next action>\nDISCOVERED_ISSUES_JSON_B64=<base64 JSON list or none>\n"""
    job = api("/jobs?async=1", "POST", {"request": prompt, "dispatch_builder": "local" if is_private else "normal"})
    job_id = str(job.get("id") or "")
    if not job_id: raise RuntimeError("governor returned no job id")
    if target and phase == "target": target["state"] = "IN_PROGRESS"; target["attempts"] += 1
    state["active"] = {"issue": number, "job_id": job_id, "started": now(), "phase": phase,
                       "target_id": target["id"] if target else None}; save_state(state)
    issue_comment(number, f"### LifeOS autonomous backlog start\n- Selected after a complete open-issue refresh and priority/dependency eligibility pass.\n- LifeOS job: `{job_id}`\n- Route: `{'local-only' if is_private else 'normal'}`\n- State: `IN_PROGRESS`")
    log(f"SUBMITTED_JOB={job_id} ISSUE=#{number}")


def main():
    state = load_state(); save_state(state)
    issues = get_open_issues()
    if state.get("active") and finish_active(state, issues): return 0
    issues = get_open_issues()
    if active_governor_jobs(): log("DISPATCH=WAIT governor_has_active_job"); return 0
    issue = choose_issue(issues, state)
    if not issue: log("DISPATCH=IDLE no_eligible_open_issues"); return 0
    log(f"PRIORITY_RECHECK=PASS selected=#{issue['number']}"); submit_issue(issue, state); return 0


if __name__ == "__main__":
    try: raise SystemExit(main())
    except Exception as exc:
        log(f"RESULT=FAIL TYPE={type(exc).__name__} REASON={str(exc)[:1000]}"); raise
