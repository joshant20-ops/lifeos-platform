from datetime import datetime
import sys
sys.path.insert(0, '/home/joshan/automation/pa')
#!/usr/bin/env python3
from pathlib import Path
import json, time, os

BASE = Path("/home/joshan/automation")
QUEUE_DIR = BASE / "queues"
LOG_DIR = BASE / "logs"

PA_QUEUE = QUEUE_DIR / "pa_job_queue.jsonl"
PA_FLAG = QUEUE_DIR / "pa_jobs_pending.flag"
AUDIT_LOG = LOG_DIR / "pa_audit_results.jsonl"
PA_SUMMARY = BASE / "state/pa_latest_summary.json"
OPEN_LOOPS = BASE / "state/open_loops.json"

def load_jobs():
    jobs = []
    if not PA_QUEUE.exists():
        return jobs
    for line in PA_QUEUE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            jobs.append(json.loads(line))
        except Exception:
            jobs.append({
                "job_id": f"corrupt_{int(time.time())}",
                "status": "error",
                "result": "Corrupt queue line could not be parsed",
                "raw": line
            })
    return jobs

def save_jobs(jobs):
    with PA_QUEUE.open("w", encoding="utf-8") as f:
        for job in jobs:
            f.write(json.dumps(job) + "\n")


def load_open_loops():
    if not OPEN_LOOPS.exists():
        return {"updated_time": int(time.time()), "loops": []}
    try:
        return json.loads(OPEN_LOOPS.read_text(encoding="utf-8"))
    except Exception:
        return {"updated_time": int(time.time()), "loops": []}

def save_open_loops(data):
    data["updated_time"] = int(time.time())
    OPEN_LOOPS.parent.mkdir(parents=True, exist_ok=True)
    OPEN_LOOPS.write_text(json.dumps(data, indent=2), encoding="utf-8")

def upsert_open_loop(job):
    payload = job.get("payload", {})
    loop_type = payload.get("loop_type", "unknown")
    summary = payload.get("summary", "No summary")
    source = payload.get("source", job.get("source", "unknown"))

    data = load_open_loops()
    loops = data.setdefault("loops", [])

    loop_id = payload.get("loop_id") or f"{loop_type}_{abs(hash(summary)) % 100000000}"

    existing = None
    for loop in loops:
        if loop.get("loop_id") == loop_id:
            existing = loop
            break

    now = int(time.time())

    if existing is None:
        loops.append({
            "loop_id": loop_id,
            "loop_type": loop_type,
            "status": payload.get("status", "open"),
            "created_time": now,
            "last_update_time": now,
            "summary": summary,
            "source": source,
            "next_expected_event": payload.get("next_expected_event", ""),
            "priority": payload.get("priority", job.get("priority", "normal")),
            "closure_conditions": payload.get("closure_conditions", []),
            "human_confirmation_required": payload.get("human_confirmation_required", False),
            "history": [{
                "time": now,
                "event": "created",
                "source_job_id": job.get("job_id")
            }]
        })
        save_open_loops(data)
        return f"PASS: created open loop {loop_id}"

    new_status = payload.get("status", existing.get("status", "open"))

    existing["last_update_time"] = now
    if new_status == "delivered" and payload.get("human_confirmation_required", False):
        new_status = "waiting_confirmation"
        existing["next_expected_event"] = payload.get("next_expected_event", "user_confirms_received")
    existing["status"] = new_status
    if summary != "No summary":
        existing["summary"] = summary
    existing["next_expected_event"] = payload.get("next_expected_event", existing.get("next_expected_event", ""))

    if new_status in ["closed", "complete", "refunded", "renewed", "confirmed", "cancelled"]:
        existing["closed_time"] = now
        existing["closure_reason"] = payload.get("closure_reason", new_status)
        existing["human_confirmation_required"] = False
        existing["next_expected_event"] = ""
    else:
        existing.pop("closed_time", None)
        existing.pop("closure_reason", None)

    existing.setdefault("history", []).append({
        "time": now,
        "event": f"status_set_to_{new_status}",
        "source_job_id": job.get("job_id"),
        "note": payload.get("note", "")
    })

    save_open_loops(data)
    return f"PASS: updated lifecycle loop {loop_id} to {new_status}"


def audit_qa_job(job):
    payload = job.get("payload", {})
    question = payload.get("question", "")
    answer = payload.get("answer", "")

    if not question:
        return "FAIL: missing question"
    if not answer or answer == "Thinking...":
        return "FAIL: missing answer"
    if "i don't know" in answer.lower():
        return "REVIEW: answer is unknown / incomplete"

    return "PASS: answer present and suitable for simple local Q&A"

def write_summary(result, jobs):
    PA_SUMMARY.parent.mkdir(parents=True, exist_ok=True)
    status_counts = {}
    for j in jobs:
        status = j.get("status", "missing")
        status_counts[status] = status_counts.get(status, 0) + 1

    summary = {
        "updated_time": int(time.time()),
        "worker": "pa",
        "ok": result.get("ok", False),
        "processed": result.get("processed", 0),
        "reason": result.get("reason", ""),
        "still_pending": result.get("still_pending", False),
        "status_counts": status_counts,
        "pending_count": status_counts.get("pending", 0),
        "complete_count": status_counts.get("complete", 0),
        "error_count": status_counts.get("error", 0),
        "total_jobs": len(jobs),
        "flag": PA_FLAG.read_text(encoding="utf-8").strip() if PA_FLAG.exists() else "missing"
    }
    PA_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary

def write_summary(result, jobs):
    PA_SUMMARY.parent.mkdir(parents=True, exist_ok=True)

    status_counts = {}
    for j in jobs:
        status = j.get("status", "missing")
        status_counts[status] = status_counts.get(status, 0) + 1

    summary = {
        "updated_time": int(time.time()),
        "worker": "pa",
        "ok": result.get("ok", False),
        "processed": result.get("processed", 0),
        "reason": result.get("reason", ""),
        "still_pending": result.get("still_pending", False),
        "status_counts": status_counts,
        "pending_count": status_counts.get("pending", 0),
        "complete_count": status_counts.get("complete", 0),
        "error_count": status_counts.get("error", 0),
        "total_jobs": len(jobs),
        "flag": PA_FLAG.read_text(encoding="utf-8").strip() if PA_FLAG.exists() else "missing"
    }

    PA_SUMMARY.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# ---------------------------------------------------------------------------
# LIFEOS SOURCE-NATIVE LIFECYCLE REVIEW NOTES
# ---------------------------------------------------------------------------
# Purpose:
#   This function lets PA review an unsure/low-confidence lifecycle item that
#   Steward has routed into the canonical PA queue.
#
# Why this exists:
#   Steward is allowed to extract and route source-native evidence, but should
#   not guess when evidence is unclear. Instead, Steward sends unsure items to PA.
#
# Safety model:
#   - PA may review local redacted/source evidence.
#   - PA may create/maintain open loops for unresolved items.
#   - PA must NOT write accepted facts here.
#   - PA must NOT mutate Paperless here.
#   - PA must NOT close lifecycle items unless evidence is source-backed.
#   - Watchman remains required before any promoted 100-confidence closure can
#     affect live lifecycle state.
#
# Feedback model:
#   Steward feedback is advisory. Exact-source feedback has the highest priority.
#   Same job-class averages and global baselines are only suggestions. They must
#   never override the current source evidence.
#
# Future expansion point:
#   This local deterministic review can later delegate to the Z97/LLM PA worker
#   using payload.request_text, but the output contract should remain:
#   decision + confidence + reason + required_rework + no writeback.
# ---------------------------------------------------------------------------
def pa_review_source_item(job):
    payload = job.get("payload", {}) or {}
    item = payload.get("source_item", {}) or {}

    title = str(item.get("title") or payload.get("title") or "").lower()
    sample = str(item.get("redacted_phrase_sample") or "").lower()
    hits = item.get("phrase_hits") or []
    current_state = payload.get("current_state") or item.get("event_state") or item.get("state")

    combined = " ".join([title, sample, " ".join(map(str, hits))]).lower()

    closure_terms = [
        "refund processed",
        "refund has been processed",
        "refund issued",
        "refund completed",
        "refund complete",
        "refunded",
        "return completed",
        "return complete",
        "we have received your return",
        "credited",
    ]

    pending_terms = [
        "refund pending",
        "refund requested",
        "return requested",
        "return label",
        "awaiting refund",
        "refund will be processed",
        "processing your refund",
    ]

    refund_terms = [
        "refund",
        "return",
        "returned",
        "credit",
        "exchange",
        "replacement",
    ]

    closure_hits = [t for t in closure_terms if t in combined]
    pending_hits = [t for t in pending_terms if t in combined]
    refund_hits = [t for t in refund_terms if t in combined]

    if closure_hits:
        decision = "closed"
        score = 100
        reason = "Same local source evidence contains a clear closure phrase."
        required_rework = None
    elif pending_hits:
        decision = "waiting"
        score = 100
        reason = "Same local source evidence contains a pending/waiting refund or return phrase."
        required_rework = None
    elif refund_hits:
        decision = "needs_more_evidence"
        score = 85
        reason = "Refund/return terms exist, but no source-backed pending or closure phrase was found."
        required_rework = "Steward should provide stronger source evidence: exact redacted phrase, source document ID, and whether this is a return start, refund pending, or closure."
    else:
        decision = "not_relevant"
        score = 100
        reason = "Provided local source evidence does not contain enough refund/return lifecycle signal."
        required_rework = None

    return {
        "ok": True,
        "status": "reviewed",
        "job_type": job.get("job_type"),
        "decision": decision,
        "auditor_confidence_score": score,
        "reason": reason,
        "required_rework": required_rework,
        "evidence_used": {
            "title": item.get("title") or payload.get("title"),
            "current_state": current_state,
            "phrase_hits": hits,
            "redacted_phrase_sample": item.get("redacted_phrase_sample"),
            "paperless_doc_id": item.get("paperless_doc_id") or item.get("source_doc_id"),
            "job_classification": payload.get("job_classification") or item.get("job_classification") or item.get("event_type"),
        },
        "privacy_ok": True,
        "writeback_performed": False,
        "paperless_writeback_performed": False,
        "watchman_required": score == 100 and decision in {"closed", "actionable"},
        "writes_facts": False,
    }


def run_once():
    jobs = load_jobs()

    if not PA_FLAG.exists() or PA_FLAG.read_text(encoding="utf-8").strip() != "1":
        result = {"ok": True, "processed": 0, "reason": "no_pending_flag"}
        write_summary(result, jobs)
        return result

    processed = 0

    for job in jobs:
        if job.get("status") != "pending":
            continue

        if job.get("job_type") == "qa_audit":
            result_text = audit_qa_job(job)
        elif job.get("job_type") == "deciding_review":
            payload = job.get("payload", {})
            result = {
                "ok": True,
                "status": "review_required",
                "job_type": "deciding_review",
                "summary": "Deciding review queued for PA/Z97 reasoning. Local Pi5 worker does not decide conflicts.",
                "entity": payload.get("entity"),
                "decision": "requires_z97_pa_review",
                "confidence": "not_decided",
                "recommendations": [
                    "Route to Z97 PA worker using payload.request_text contract.",
                    "Do not write accepted facts.",
                    "Return proposal only for Watchman/Steward review."
                ],
                "watchman_required": True,
                "writes_facts": False,
            }
            result_text = result
            job["status"] = "pending_z97"
            job.setdefault("routing_history", []).append({
                "time": datetime.now().isoformat(timespec="seconds"),
                "worker": "lifeos_pa_audit_worker",
                "event": "deciding_review_requires_z97_pa"
            })
            changed = True

        elif job.get("job_type") == "lifecycle_tracking":
            payload = job.get("payload", {}) or {}
            # SOURCE-NATIVE REVIEW BRANCH
            # Steward sends unclear lifecycle evidence here instead of guessing.
            # This keeps noisy extraction out of accepted facts while still
            # giving PA a chance to reason, request rework, or create an open loop.
            if payload.get("loop_type") == "steward_unsure_lifecycle_review" and payload.get("source_item"):
                review = pa_review_source_item(job)
                result_text = review
                if review.get("decision") in {"needs_more_evidence", "waiting"}:
                    # Keep unresolved items visible as open loops.
                    # Reason:
                    #   A PA review result of "waiting" or "needs_more_evidence"
                    #   is not a completed lifecycle decision. It should remain
                    #   trackable on the PA/dashboard side until better source
                    #   evidence arrives or a human confirms resolution.
                    upsert_open_loop(job)
            else:
                result_text = upsert_open_loop(job)
        else:
            result_text = f"REVIEW: unknown PA job type {job.get('job_type')}"

        job["status"] = "complete"
        if "result_text" not in locals():
            result_text = {
                "ok": False,
                "status": "review_required",
                "summary": "PA worker reached result assignment without setting result_text.",
                "job_type": job.get("job_type"),
                "watchman_required": True,
                "writes_facts": False
            }
        job["result"] = result_text
        job["completed_time"] = int(time.time())
        processed += 1

        with AUDIT_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "audit_time": int(time.time()),
                "job_id": job.get("job_id"),
                "job_type": job.get("job_type"),
                "result": result_text,
                "payload": job.get("payload", {})
            }) + "\n")

    save_jobs(jobs)

    still_pending = any(j.get("status") == "pending" for j in jobs)
    PA_FLAG.write_text("1\n" if still_pending else "0\n", encoding="utf-8")

    result = {"ok": True, "processed": processed, "still_pending": still_pending}
    write_summary(result, jobs)
    return result

if __name__ == "__main__":
    print(json.dumps(run_once(), indent=2))
