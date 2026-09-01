#!/usr/bin/env python3
"""Publish the live LifeOS GitHub queue to Home Assistant over MQTT.

The bridge also accepts a single manual scheduling override per issue:
ON adds the durable GitHub label ``lifeos-high-priority`` and OFF removes it.
The backlog dispatcher treats labelled issues as a priority pool while still
using its normal ranking among all labelled issues.
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
BACKLOG_STATE = Path(os.environ.get("LIFEOS_BACKLOG_STATE_FILE", "/var/lib/lifeos-backlog-runner/state.json"))
BRIDGE_STATE = Path(os.environ.get("LIFEOS_ISSUE_QUEUE_STATE", "/var/lib/lifeos-ha-issue-queue/state.json"))
HIGH_LABEL = "lifeos-high-priority"
DISCOVERY_ROOT = "homeassistant"
BASE = "lifeos/issue_queue"
STOP = threading.Event()


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


def ensure_label():
    gh("label", "create", HIGH_LABEL, "--repo", REPO, "--description", "Manual LifeOS high-priority scheduling pool", "--color", "B60205", "--force")


def set_high_priority(number, enabled):
    if enabled:
        gh("issue", "edit", str(number), "--repo", REPO, "--add-label", HIGH_LABEL)
    else:
        cp = gh("issue", "edit", str(number), "--repo", REPO, "--remove-label", HIGH_LABEL, check=False)
        # Removing an absent label is harmless; other failures are not.
        if cp.returncode and "not found" not in (cp.stderr or "").lower():
            raise RuntimeError((cp.stderr or "label removal failed").strip())


def switch_discovery(number, title):
    uid = f"lifeos_issue_{number}_high_priority_v1"
    return {
        "name": f"#{number} High priority",
        "unique_id": uid,
        "state_topic": f"{BASE}/{number}/high_priority/state",
        "command_topic": f"{BASE}/{number}/high_priority/set",
        "payload_on": "ON",
        "payload_off": "OFF",
        "state_on": "ON",
        "state_off": "OFF",
        "icon": "mdi:priority-high",
        "device": {
            "identifiers": ["lifeos_issue_queue"],
            "name": "LifeOS Issue Queue",
            "manufacturer": "LifeOS",
            "model": "GitHub Backlog",
        },
    }


def publish_discovery():
    summary = {
        "name": "LifeOS Open Jobs",
        "unique_id": "lifeos_open_jobs_v1",
        "state_topic": f"{BASE}/state",
        "value_template": "{{ value_json.count }}",
        "json_attributes_topic": f"{BASE}/state",
        "unit_of_measurement": "jobs",
        "icon": "mdi:format-list-checks",
        "availability_topic": f"{BASE}/availability",
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": {
            "identifiers": ["lifeos_issue_queue"],
            "name": "LifeOS Issue Queue",
            "manufacturer": "LifeOS",
            "model": "GitHub Backlog",
        },
    }
    mqtt_pub(f"{DISCOVERY_ROOT}/sensor/lifeos_issue_queue/open_jobs/config", json.dumps(summary, separators=(",", ":")))


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
        p = native_priority(issue)
        rows.append({
            "number": number,
            "priority": p,
            "high_priority": high,
            "title": str(issue.get("title") or ""),
            "status": status,
            "stage": stage,
            "detail": detail[:500],
            "url": str(issue.get("html_url") or f"https://github.com/{REPO}/issues/{number}"),
            "created_at": str(issue.get("created_at") or ""),
        })
        topic = f"{DISCOVERY_ROOT}/switch/lifeos_issue_queue/issue_{number}_high_priority/config"
        mqtt_pub(topic, json.dumps(switch_discovery(number, issue.get("title", "")), separators=(",", ":")))
        mqtt_pub(f"{BASE}/{number}/high_priority/state", "ON" if high else "OFF")

    # Remove discovery for issues that have been closed/completed since the last refresh.
    for number in sorted(previous_numbers - current_numbers):
        mqtt_pub(f"{DISCOVERY_ROOT}/switch/lifeos_issue_queue/issue_{number}_high_priority/config", "")
        mqtt_pub(f"{BASE}/{number}/high_priority/state", "")

    rows.sort(key=lambda r: (0 if r["high_priority"] else 1, r["priority"], r["created_at"], r["number"]))
    payload = {
        "count": len(rows),
        "high_priority_count": sum(1 for r in rows if r["high_priority"]),
        "issues": rows,
        "generated_at": int(time.time()),
    }
    mqtt_pub(f"{BASE}/state", json.dumps(payload, separators=(",", ":")))
    mqtt_pub(f"{BASE}/availability", "online")
    save_bridge_state({"issues": sorted(current_numbers)})
    return payload


def command_loop():
    pattern = re.compile(rf"^{re.escape(BASE)}/(\d+)/high_priority/set$")
    while not STOP.is_set():
        proc = subprocess.Popen(
            ["mosquitto_sub", "-h", MQTT_HOST, "-v", "-t", f"{BASE}/+/high_priority/set"],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            while not STOP.is_set() and proc.poll() is None:
                line = proc.stdout.readline() if proc.stdout else ""
                if not line:
                    time.sleep(0.2); continue
                topic, _, payload = line.strip().partition(" ")
                match = pattern.match(topic)
                if not match or payload not in {"ON", "OFF"}:
                    continue
                number = int(match.group(1))
                try:
                    set_high_priority(number, payload == "ON")
                    refresh()
                except Exception as exc:
                    print(f"COMMAND=FAIL ISSUE={number} ERROR={type(exc).__name__}:{exc}", flush=True)
        finally:
            proc.terminate()
            try: proc.wait(timeout=3)
            except subprocess.TimeoutExpired: proc.kill()
        if not STOP.is_set(): time.sleep(2)


def shutdown(*_):
    STOP.set()


def main():
    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)
    ensure_label()
    publish_discovery()
    thread = threading.Thread(target=command_loop, name="mqtt-command-listener", daemon=True)
    thread.start()
    while not STOP.is_set():
        try:
            payload = refresh()
            print(f"QUEUE_REFRESH=PASS COUNT={payload['count']} HIGH={payload['high_priority_count']}", flush=True)
        except Exception as exc:
            print(f"QUEUE_REFRESH=FAIL TYPE={type(exc).__name__} REASON={exc}", flush=True)
        STOP.wait(REFRESH)
    try: mqtt_pub(f"{BASE}/availability", "offline")
    except Exception: pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
