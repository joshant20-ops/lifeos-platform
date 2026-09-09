#!/usr/bin/env python3
import json
import subprocess
import sys
import time
import uuid
from pathlib import Path
from datetime import datetime, timezone

BASE = Path("/home/joshan/automation")
LOGS = BASE / "logs"
OUTBOX = BASE / "z97_job_outbox"
RESULTS = BASE / "z97_job_results"
CONFIG_PATH = BASE / "z97_job_bridge_config.json"

for p in [LOGS, OUTBOX, RESULTS]:
    p.mkdir(parents=True, exist_ok=True)

def now():
    return datetime.now(timezone.utc).isoformat()

def run(cmd, timeout=120):
    return subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)

def load_config():
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def _extract_json(text):
    raw = str(text or "").strip()
    try:
        return json.loads(raw)
    except Exception:
        pass

    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
        try:
            return json.loads(raw)
        except Exception:
            pass

    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            return json.loads(raw[start:end + 1])
        except Exception:
            pass

    return raw


def submit_pa_local(text, model=None, wait=True):
    repo = Path("/home/joshan/lifeos-platform")
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))

    from governor import ai_broker

    job_id = "job_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]
    chosen_model = model or ai_broker.OLLAMA_MODEL

    job = {
        "job_id": job_id,
        "created_utc": now(),
        "source": "pi5",
        "job_type": "pa",
        "model": chosen_model,
        "route": "local_ai_broker",
        "summary": text[:180],
        "payload": {"request_text": text},
        "safety": {
            "writeback_enabled": False,
            "execution_allowed": False,
            "watchman_required_for_execution": True
        }
    }

    local_job = OUTBOX / f"{job_id}.json"
    local_job.write_text(json.dumps(job, indent=2), encoding="utf-8")

    try:
        raw = ai_broker._ollama(text, chosen_model)
        response = _extract_json(raw)

        result = {
            "ok": True,
            "job_id": job_id,
            "job_type": "pa",
            "route": "local_ai_broker",
            "model": chosen_model,
            "response": response,
            "raw_response": raw if not isinstance(response, dict) else None
        }

        local_result = RESULTS / f"{job_id}.result.json"
        local_result.write_text(json.dumps(result, indent=2), encoding="utf-8")

        latest = LOGS / "z97_job_last_result.json"
        latest.write_text(json.dumps(result, indent=2), encoding="utf-8")

        return result

    except Exception as e:
        return {
            "ok": False,
            "stage": "local_ai_broker",
            "job_id": job_id,
            "route": "local_ai_broker",
            "error": type(e).__name__
        }


def submit(job_type, text, model=None, wait=True):
    # Personal Administration is normal local-AI work.
    # It must not depend on the Engineer VM being online.
    if job_type == "pa":
        return submit_pa_local(text, model=model, wait=wait)

    cfg = load_config()
    host = cfg["z97_host"]
    # LifeOS fix: Z97 SSH must use joshan, not root
    if host == "192.168.0.204":
        host = "joshan@192.168.0.204"
    elif host.endswith("@192.168.0.204") is False and "192.168.0.204" in host:
        host = "joshan@192.168.0.204"
    zbase = cfg["z97_base"]

    job_id = "job_" + datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:8]

    if model is None:
        model = cfg.get("default_pa_model", "llama3:latest") if job_type == "pa" else cfg.get("default_engineer_model", "llama3:latest")

    job = {
        "job_id": job_id,
        "created_utc": now(),
        "source": "pi5",
        "job_type": job_type,
        "model": model,
        "summary": text[:180],
        "payload": {
            "request_text": text
        },
        "safety": {
            "writeback_enabled": False,
            "execution_allowed": False,
            "watchman_required_for_execution": True
        }
    }

    local_job = OUTBOX / f"{job_id}.json"
    local_job.write_text(json.dumps(job, indent=2), encoding="utf-8")

    remote_job = f"{zbase}/inbox/{job_id}.json"
    scp = run(["scp", str(local_job), f"{host}:{remote_job}"], timeout=60)
    if scp.returncode != 0:
        return {
            "ok": False,
            "stage": "scp_to_z97",
            "job_id": job_id,
            "stderr": scp.stderr,
            "stdout": scp.stdout
        }

    if job_type == "pa":
        worker_script = "run_pa_once.sh"
    elif job_type == "engineer":
        worker_script = "run_engineer_once.sh"
    elif job_type == "rw":
        worker_script = "run_rw_once.sh"
    else:
        worker_script = "run_auditor_once.sh"
    ssh = run(["ssh", host, f"{zbase}/workers/{worker_script}"], timeout=900)
    if ssh.returncode != 0:
        return {
            "ok": False,
            "stage": "z97_worker",
            "job_id": job_id,
            "stderr": ssh.stderr,
            "stdout": ssh.stdout
        }

    if not wait:
        return {"ok": True, "job_id": job_id, "submitted": True, "waited": False}

    remote_result = f"{zbase}/results/{job_id}.result.json"
    local_result = RESULTS / f"{job_id}.result.json"

    fetch = run(["scp", f"{host}:{remote_result}", str(local_result)], timeout=60)
    if fetch.returncode != 0:
        return {
            "ok": False,
            "stage": "fetch_result",
            "job_id": job_id,
            "stderr": fetch.stderr,
            "stdout": fetch.stdout
        }

    result = json.loads(local_result.read_text(encoding="utf-8"))
    latest = LOGS / "z97_job_last_result.json"
    latest.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return result

def main():
    if len(sys.argv) < 3:
        print("Usage: z97_job_submitter.py pa|engineer|auditor|rw 'request text'", file=sys.stderr)
        sys.exit(2)

    job_type = sys.argv[1]
    text = " ".join(sys.argv[2:]).strip()

    if job_type not in {"pa", "engineer", "auditor", "rw"}:
        print("job_type must be: pa, engineer, auditor, or rw", file=sys.stderr)
        sys.exit(2)

    result = submit(job_type, text)
    print(json.dumps(result, indent=2))

    if not result.get("ok"):
        sys.exit(1)

if __name__ == "__main__":
    main()
