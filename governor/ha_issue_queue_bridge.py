#!/usr/bin/env python3
"""Publish the live LifeOS control plane and GitHub queue to Home Assistant.

The bridge preserves the previous ``LifeOS Issue Queue`` MQTT device so the
existing Home Assistant pages can be adapted in place.  In addition to the
per-issue priority controls it publishes a single authoritative control-state
sensor describing whether LifeOS is working, idle, blocked, stalled or
degraded.
"""
from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

REPO = os.environ.get("LIFEOS_BACKLOG_GITHUB_REPO", "joshant20-ops/lifeos-platform")
GOV = os.environ.get("LIFEOS_BACKLOG_GOVERNOR", "http://127.0.0.1:8790").rstrip("/")
MQTT_HOST = os.environ.get("LIFEOS_MQTT_HOST", "127.0.0.1")
REFRESH = max(10, int(os.environ.get("LIFEOS_ISSUE_QUEUE_REFRESH", "30")))
STALL_SECONDS = max(300, int(os.environ.get("LIFEOS_CONTROL_STALL_SECONDS", "2700")))
BACKLOG_STATE = Path(os.environ.get("LIFEOS_BACKLOG_STATE_FILE", "/var/lib/lifeos-backlog-runner/state.json"))
BRIDGE_STATE = Path(os.environ.get("LIFEOS_ISSUE_QUEUE_STATE", "/var/lib/lifeos-ha-issue-queue/state.json"))
HIGH_LABEL = "lifeos-high-priority"
DISCOVERY_ROOT = "homeassistant"
BASE = "lifeos/issue_queue"
STOP = threading.Event()
PROTECTED_UNITS = (
    "lifeos-control-job-submit.socket",
    "lifeos-root-broker.socket",
    "lifeos-autonomous-agent.service",
    "lifeos-engineer.service",
    "lifeos-ha-issue-queue-bridge.service",
)
ROADMAP_STAGE = 9
ROADMAP_STAGES = 12


def run(*args, check=True, timeout=90):
    cp = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if check and cp.returncode:
        raise RuntimeError(f"{' '.join(args)} rc={cp.returncode}: {(cp.stderr or '').strip()[:800]}")
    return cp


def gh(*args, check=True):
    return run("gh", *args, check=check)


def mqtt_pub(topic, payload, retain=True):
    args = ["mosquitto_pub", "-h", MQTT_HOST, "-t", topic, "-m", payload]
    if retain:
        args.append("-r")
    run(*args, timeout=20)


def governor(path="/jobs"):
    with urllib.request.urlopen(GOV + path, timeout=5) as response:
        return json.load(response)


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def save_bridge_state(value):
    BRIDGE_STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = BRIDGE_STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, BRIDGE_STATE)


def labels(issue):
    return {str(x.get("name", "")).lower() for x in issue.get("labels", [])}


def native_priority(issue):
    title = str(issue.get("title") or "")
    ls = labels(issue)
    for n in range(10):
        if re.match(rf"^P{n}\b", title, re.I) or f"priority:p{n}" in ls or f"p{n}" in ls:
            return n
    return 9


def get_open_issues():
    raw = gh("api", f"repos/{REPO}/issues?state=open&per_page=100", "--paginate").stdout or "[]"
    value = json.loads(raw)
    return [x for x in value if "pull_request" not in x]


def get_jobs():
    value = governor("/jobs")
    if isinstance(value, dict):
        return value.get("jobs", value.get("items", []))
    return value


def issue_status(number, durable, active, jobs_by_id):
    if active and int(active.get("issue", -1)) == number:
        job = jobs_by_id.get(str(active.get("job_id")))
        if job:
            return str(job.get("status") or "RUNNING").upper(), str(job.get("stage") or "unknown"), str(job.get("stage_detail") or "")
        return "RUNNING", "unknown", ""
    entry = durable.get("issues", {}).get(str(number), {})
    work = str(entry.get("work_state") or "").upper()
    retry_after = entry.get("retry_after")
    if retry_after and int(retry_after) > int(time.time()):
        return "COOLDOWN", "waiting", str(entry.get("barrier") or "")
    if work in {"BLOCKED", "WAITING_HUMAN", "WAITING_DEPENDENCY", "FAIL", "ERROR"}:
        return "BLOCKED", "blocked", str(entry.get("barrier") or "")
    return "READY", "eligible", ""


def issue_plan_progress(number, durable):
    plan = durable.get("issues", {}).get(str(number), {}).get("plan") or {}
    milestones = plan.get("milestones") or []
    targets = [target for milestone in milestones for target in milestone.get("targets", [])
               if target.get("state") != "SUPERSEDED"]
    current = next((target for target in targets if target.get("state") == "IN_PROGRESS"), None)
    if current is None:
        passed = {target.get("id") for target in targets if target.get("state") == "PASS"}
        current = next((target for target in targets if target.get("state") in {"PLANNED", "READY", "FAILED"}
                        and set(target.get("depends_on", [])) <= passed), None)
    current_milestone = next((milestone for milestone in milestones
                              if current in milestone.get("targets", [])), None)
    return {
        "plan_state": plan.get("state"),
        "completed_targets": sum(target.get("state") == "PASS" for target in targets),
        "total_targets": len(targets),
        "current_milestone": current_milestone.get("id") if current_milestone else None,
        "current_target": current.get("id") if current else None,
        "blocker": next((target.get("evidence", [{}])[-1].get("summary") for target in targets
                         if target.get("state") in {"BLOCKED", "WAITING_HUMAN"} and target.get("evidence")), None),
    }


def systemd_state(unit):
    active = run("systemctl", "is-active", unit, check=False, timeout=10).stdout.strip() or "unknown"
    enabled = run("systemctl", "is-enabled", unit, check=False, timeout=10).stdout.strip() or "unknown"
    return {"active": active, "enabled": enabled}


def runner_health():
    cp = run("systemctl", "list-units", "--all", "--type=service", "--no-legend", "actions.runner.*lifeos-pi5.service", check=False, timeout=10)
    line = next((x for x in cp.stdout.splitlines() if "lifeos-pi5.service" in x), "")
    return {"state": "PASS" if " active running " in f" {line} " else "FAIL", "unit": line.split()[0] if line else None}


def semaphore_health():
    cp = run("docker", "port", "lifeos-semaphore-shadow-semaphore-1", "3000/tcp", check=False, timeout=10)
    endpoint = next((x.strip() for x in cp.stdout.splitlines() if x.strip()), "")
    if not endpoint:
        return {"state": "FAIL", "endpoint": None}
    # Docker may render IPv6 as [::]:port; prefer the explicitly published LAN endpoint.
    if endpoint.startswith("["):
        endpoint = next((x.strip() for x in cp.stdout.splitlines() if x.strip() and not x.strip().startswith("[")), endpoint)
    url = f"http://{endpoint}/api/ping"
    try:
        with urllib.request.urlopen(url, timeout=4) as response:
            ok = 200 <= response.status < 300
    except Exception:
        ok = False
    return {"state": "PASS" if ok else "FAIL", "endpoint": endpoint}


def latest_automation():
    cp = gh("run", "list", "--repo", REPO, "--workflow", "lifeos-pi-auto-smoke.yml", "--limit", "1",
            "--json", "status,conclusion,createdAt,updatedAt,databaseId,headSha,url", check=False)
    if cp.returncode:
        return {"state": "UNKNOWN"}
    try:
        rows = json.loads(cp.stdout or "[]")
        row = rows[0] if rows else {}
    except ValueError:
        row = {}
    conclusion = str(row.get("conclusion") or "").lower()
    status = str(row.get("status") or "").lower()
    state = "RUNNING" if status in {"queued", "in_progress"} else ("PASS" if conclusion == "success" else "FAIL" if conclusion else "UNKNOWN")
    return {"state": state, **row}


def _epoch(value):
    if not value:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp())
    except (TypeError, ValueError):
        return 0


def control_state(rows, durable, jobs):
    now = int(time.time())
    active = durable.get("active") or None
    jobs_by_id = {str(j.get("id")): j for j in jobs if j.get("id")}
    active_job = jobs_by_id.get(str(active.get("job_id"))) if active else None
    protected = {unit: systemd_state(unit) for unit in PROTECTED_UNITS}
    runner = runner_health()
    semaphore = semaphore_health()
    automation = latest_automation()
    degraded = [unit for unit, value in protected.items() if value["active"] != "active"]
    if runner["state"] != "PASS":
        degraded.append("github-runner")
    if semaphore["state"] != "PASS":
        degraded.append("semaphore")

    blocked = [r for r in rows if r["status"] == "BLOCKED"]
    eligible = [r for r in rows if r["status"] == "READY"]
    current = None
    if active:
        current = next((r for r in rows if r["number"] == int(active.get("issue", -1))), None)
    if current is None and blocked:
        current = blocked[0]
    if current is None and eligible:
        current = eligible[0]

    completed = [j for j in jobs if str(j.get("status") or "").upper() in {"PASS", "FAIL", "ERROR", "REJECTED"}]
    completed.sort(key=lambda j: _epoch(j.get("completed_at") or j.get("stage_changed_at")), reverse=True)
    last_job = completed[0] if completed else None
    progress_times = [_epoch((last_job or {}).get("completed_at") or (last_job or {}).get("stage_changed_at")), _epoch(automation.get("updatedAt"))]
    last_progress = max(progress_times or [0])
    stalled_for = max(0, now - last_progress) if last_progress else None

    blocker = ""
    next_action = ""
    if current:
        blocker = str(current.get("blocker") or current.get("detail") or "")
        next_action = str(current.get("current_target") or current.get("stage") or "")

    if degraded:
        state = "DEGRADED"
        blocker = "unhealthy control-plane component: " + ", ".join(degraded)
    elif active:
        state = "WORKING"
    elif blocked:
        state = "BLOCKED"
    elif eligible and (last_progress == 0 or now - last_progress >= STALL_SECONDS):
        state = "STALLED"
        blocker = blocker or f"{len(eligible)} eligible issue(s) but no active execution"
        next_action = next_action or "dispatch next eligible issue through Semaphore"
    else:
        state = "IDLE"

    return {
        "state": state,
        "generated_at": now,
        "current_issue": current.get("number") if current else None,
        "current_title": current.get("title") if current else None,
        "current_job": active.get("job_id") if active else None,
        "current_job_status": str((active_job or {}).get("status") or "") or None,
        "current_stage": str((active_job or {}).get("stage") or (current or {}).get("stage") or "") or None,
        "stage_detail": str((active_job or {}).get("stage_detail") or (current or {}).get("detail") or "")[:500] or None,
        "blocker": blocker[:500] or None,
        "next_action": next_action[:300] or None,
        "eligible_count": len(eligible),
        "blocked_count": len(blocked),
        "open_issue_count": len(rows),
        "last_completed_job": (last_job or {}).get("id"),
        "last_completed_status": (last_job or {}).get("status"),
        "last_progress_at": last_progress or None,
        "stalled_for_seconds": stalled_for,
        "stall_threshold_seconds": STALL_SECONDS,
        "github_runner": runner,
        "semaphore": semaphore,
        "automation": automation,
        "protected_units": protected,
        "roadmap_stage": ROADMAP_STAGE,
        "roadmap_stages": ROADMAP_STAGES,
        "roadmap_progress_percent": round(100 * ROADMAP_STAGE / ROADMAP_STAGES),
        "roadmap_label": "Safe automated deployment and remediation",
    }


def ensure_label():
    gh("label", "create", HIGH_LABEL, "--repo", REPO, "--description", "Manual LifeOS high-priority scheduling pool", "--color", "B60205", "--force")


def set_high_priority(number, enabled):
    if enabled:
        gh("issue", "edit", str(number), "--repo", REPO, "--add-label", HIGH_LABEL)
    else:
        cp = gh("issue", "edit", str(number), "--repo", REPO, "--remove-label", HIGH_LABEL, check=False)
        if cp.returncode and "not found" not in (cp.stderr or "").lower():
            raise RuntimeError((cp.stderr or "label removal failed").strip())


def device():
    return {"identifiers": ["lifeos_issue_queue"], "name": "LifeOS Issue Queue", "manufacturer": "LifeOS", "model": "GitHub Backlog / Control Plane"}


def switch_discovery(number, title):
    return {
        "name": f"#{number} High priority", "unique_id": f"lifeos_issue_{number}_high_priority_v1",
        "state_topic": f"{BASE}/{number}/high_priority/state", "command_topic": f"{BASE}/{number}/high_priority/set",
        "payload_on": "ON", "payload_off": "OFF", "state_on": "ON", "state_off": "OFF", "icon": "mdi:priority-high", "device": device(),
    }


def publish_discovery():
    summary = {
        "name": "LifeOS Open Jobs", "unique_id": "lifeos_open_jobs_v1", "state_topic": f"{BASE}/state",
        "value_template": "{{ value_json.count }}", "json_attributes_topic": f"{BASE}/state", "unit_of_measurement": "jobs",
        "icon": "mdi:format-list-checks", "availability_topic": f"{BASE}/availability", "payload_available": "online",
        "payload_not_available": "offline", "device": device(),
    }
    control = {
        "name": "LifeOS Control State", "unique_id": "lifeos_control_state_v1", "state_topic": f"{BASE}/control",
        "value_template": "{{ value_json.state }}", "json_attributes_topic": f"{BASE}/control", "icon": "mdi:state-machine",
        "availability_topic": f"{BASE}/availability", "payload_available": "online", "payload_not_available": "offline", "device": device(),
    }
    stalled = {
        "name": "LifeOS Stalled", "unique_id": "lifeos_stalled_v1", "state_topic": f"{BASE}/control",
        "value_template": "{{ 'ON' if value_json.state == 'STALLED' else 'OFF' }}", "payload_on": "ON", "payload_off": "OFF",
        "device_class": "problem", "availability_topic": f"{BASE}/availability", "payload_available": "online",
        "payload_not_available": "offline", "device": device(),
    }
    mqtt_pub(f"{DISCOVERY_ROOT}/sensor/lifeos_issue_queue/open_jobs/config", json.dumps(summary, separators=(",", ":")))
    mqtt_pub(f"{DISCOVERY_ROOT}/sensor/lifeos_issue_queue/control_state/config", json.dumps(control, separators=(",", ":")))
    mqtt_pub(f"{DISCOVERY_ROOT}/binary_sensor/lifeos_issue_queue/stalled/config", json.dumps(stalled, separators=(",", ":")))


def refresh():
    issues = get_open_issues()
    durable = load_json(BACKLOG_STATE, {"active": None, "issues": {}})
    active = durable.get("active") or None
    jobs = get_jobs()
    jobs_by_id = {str(j.get("id")): j for j in jobs if j.get("id")}
    previous = load_json(BRIDGE_STATE, {"issues": []})
    previous_numbers = {int(x) for x in previous.get("issues", [])}

    rows = []
    current_numbers = set()
    for issue in issues:
        number = int(issue["number"])
        current_numbers.add(number)
        ls = labels(issue)
        high = HIGH_LABEL in ls
        status, stage, detail = issue_status(number, durable, active, jobs_by_id)
        rows.append({
            "number": number, "priority": native_priority(issue), "high_priority": high,
            "title": str(issue.get("title") or ""), "status": status, "stage": stage, "detail": detail[:500],
            "url": str(issue.get("html_url") or f"https://github.com/{REPO}/issues/{number}"), "created_at": str(issue.get("created_at") or ""),
            **issue_plan_progress(number, durable),
        })
        mqtt_pub(f"{DISCOVERY_ROOT}/switch/lifeos_issue_queue/issue_{number}_high_priority/config", json.dumps(switch_discovery(number, issue.get("title", "")), separators=(",", ":")))
        mqtt_pub(f"{BASE}/{number}/high_priority/state", "ON" if high else "OFF")

    for number in sorted(previous_numbers - current_numbers):
        mqtt_pub(f"{DISCOVERY_ROOT}/switch/lifeos_issue_queue/issue_{number}_high_priority/config", "")
        mqtt_pub(f"{BASE}/{number}/high_priority/state", "")

    rows.sort(key=lambda r: (0 if r["high_priority"] else 1, r["priority"], r["created_at"], r["number"]))
    payload = {"count": len(rows), "high_priority_count": sum(1 for r in rows if r["high_priority"]), "issues": rows, "generated_at": int(time.time())}
    control = control_state(rows, durable, jobs)
    mqtt_pub(f"{BASE}/state", json.dumps(payload, separators=(",", ":")))
    mqtt_pub(f"{BASE}/control", json.dumps(control, separators=(",", ":")))
    mqtt_pub(f"{BASE}/availability", "online")
    save_bridge_state({"issues": sorted(current_numbers), "control": control})
    return payload, control


def command_loop():
    pattern = re.compile(rf"^{re.escape(BASE)}/(\d+)/high_priority/set$")
    while not STOP.is_set():
        proc = subprocess.Popen(["mosquitto_sub", "-h", MQTT_HOST, "-v", "-t", f"{BASE}/+/high_priority/set"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            while not STOP.is_set() and proc.poll() is None:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    time.sleep(0.2); continue
                topic, _, payload = line.strip().partition(" ")
                match = pattern.match(topic)
                if not match or payload not in {"ON", "OFF"}: continue
                number = int(match.group(1))
                try:
                    set_high_priority(number, payload == "ON"); refresh()
                except Exception as exc:
                    print(f"COMMAND=FAIL ISSUE={number} ERROR={type(exc).__name__}:{exc}", flush=True)
        finally:
            proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill()
        if not STOP.is_set(): time.sleep(2)


def shutdown(*_): STOP.set()


def main():
    signal.signal(signal.SIGTERM, shutdown); signal.signal(signal.SIGINT, shutdown)
    ensure_label(); publish_discovery()
    threading.Thread(target=command_loop, name="mqtt-command-listener", daemon=True).start()
    while not STOP.is_set():
        try:
            payload, control = refresh()
            print(f"QUEUE_REFRESH=PASS COUNT={payload['count']} HIGH={payload['high_priority_count']} CONTROL_STATE={control['state']} BLOCKED={control['blocked_count']} ELIGIBLE={control['eligible_count']}", flush=True)
        except Exception as exc:
            print(f"QUEUE_REFRESH=FAIL TYPE={type(exc).__name__} REASON={exc}", flush=True)
        STOP.wait(REFRESH)
    try: mqtt_pub(f"{BASE}/availability", "offline")
    except Exception: pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
