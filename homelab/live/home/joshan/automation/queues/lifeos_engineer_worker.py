#!/usr/bin/env python3
from pathlib import Path
import json, time

BASE = Path("/home/joshan/automation")
QUEUE_DIR = BASE / "queues"
LOG_DIR = BASE / "logs"

ENG_QUEUE = QUEUE_DIR / "engineer_job_queue.jsonl"
ENG_FLAG = QUEUE_DIR / "engineer_jobs_pending.flag"
ENG_LOG = LOG_DIR / "engineer_worker_results.jsonl"

def load_jobs():
    jobs = []
    if not ENG_QUEUE.exists():
        return jobs

    for line in ENG_QUEUE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            jobs.append(json.loads(line))
        except Exception:
            jobs.append({
                "job_id": f"corrupt_{int(time.time())}",
                "status": "error",
                "result": "Corrupt engineer queue line could not be parsed",
                "raw": line
            })

    return jobs

def save_jobs(jobs):
    with ENG_QUEUE.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")

def inspect_job(job):
    payload = job.get("payload", {})
    job_type = job.get("job_type", "")

    if job_type == "service_check":
        service = payload.get("service", "")
        if not service:
            return "REVIEW: service_check missing service name"
        return f"PASS: engineer received service_check for {service}; no repair executed"

    if job_type == "failure_review":
        failure = payload.get("failure", "")
        if not failure:
            return "REVIEW: failure_review missing failure details"
        return "PASS: engineer received failure review; proposal-only mode"

    return f"REVIEW: unknown engineer job type {job_type}"

def run_once():
    if not ENG_FLAG.exists() or ENG_FLAG.read_text(encoding="utf-8").strip() != "1":
        return {"ok": True, "processed": 0, "reason": "no_pending_flag"}

    jobs = load_jobs()
    processed = 0

    for job in jobs:
        if job.get("status") != "pending":
            continue

        result = inspect_job(job)

        job["status"] = "complete"
        job["result"] = result
        job["completed_time"] = int(time.time())
        processed += 1

        with ENG_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "result_time": int(time.time()),
                "job_id": job.get("job_id"),
                "job_type": job.get("job_type"),
                "result": result,
                "payload": job.get("payload", {}),
                "execution_performed": False,
                "watchman_required_for_execution": True
            }) + "\n")

    save_jobs(jobs)

    still_pending = any(j.get("status") == "pending" for j in jobs)
    ENG_FLAG.write_text("1\n" if still_pending else "0\n", encoding="utf-8")

    return {"ok": True, "processed": processed, "still_pending": still_pending}

if __name__ == "__main__":
    print(json.dumps(run_once(), indent=2))
