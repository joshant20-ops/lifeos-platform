#!/usr/bin/env python3
"""Fail-closed publication boundary for the long-lived Governor.

The Governor may stage exact publication candidates under its mutable state, but
it never mutates the canonical checkout or pushes Git itself. A short-lived Pi5
publisher owned by the execution workflow consumes these requests.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import pathlib
import re
import time
import uuid

SCHEMA = 1
WAIT_SECONDS = int(os.environ.get("LIFEOS_PUBLICATION_WAIT_SECONDS", "300"))
POLL_SECONDS = 0.25


def _dirs(core):
    root = pathlib.Path(core.ROOT) / "publication_queue"
    paths = {
        "root": root,
        "requests": root / "requests",
        "payloads": root / "payloads",
        "results": root / "results",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True, mode=0o750)
    return paths


def _atomic_write(path: pathlib.Path, data: bytes, mode: int = 0o600):
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with open(tmp, "xb") as handle:
        os.fchmod(handle.fileno(), mode)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _submit(core, *, operation: str, job: dict, payload: bytes, expected_base: str, iteration: int | None = None, rel: str | None = None):
    job_id = str(job.get("id") or "")
    if not core.JOB_ID_PATTERN.fullmatch(job_id):
        return {"status": "REJECTED", "reason": "invalid_job_id"}
    if operation not in {"patch", "runtime"}:
        return {"status": "REJECTED", "reason": "invalid_operation"}
    if not re.fullmatch(r"[0-9a-f]{40,64}", str(expected_base or "")):
        return {"status": "REJECTED", "reason": "invalid_expected_base"}

    paths = _dirs(core)
    request_id = f"{job_id}-{operation}-{uuid.uuid4().hex[:12]}"
    payload_name = request_id + ".bin"
    result_name = request_id + ".json"
    request_name = request_id + ".json"
    digest = hashlib.sha256(payload).hexdigest()
    request = {
        "schema_version": SCHEMA,
        "request_id": request_id,
        "operation": operation,
        "job_id": job_id,
        "iteration": int(iteration or 0),
        "expected_base": expected_base,
        "payload_file": payload_name,
        "payload_sha256": digest,
        "payload_bytes": len(payload),
        "runtime_path": rel,
        "created_at": int(time.time()),
    }
    _atomic_write(paths["payloads"] / payload_name, payload)
    _atomic_write(
        paths["requests"] / request_name,
        (json.dumps(request, sort_keys=True, separators=(",", ":")) + "\n").encode(),
    )

    result_path = paths["results"] / result_name
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        if result_path.is_file() and not result_path.is_symlink():
            try:
                result = json.loads(result_path.read_text(encoding="utf-8"))
            except Exception:
                return {"status": "REJECTED", "reason": "invalid_publisher_result"}
            for path in (
                paths["requests"] / request_name,
                paths["payloads"] / payload_name,
                result_path,
            ):
                path.unlink(missing_ok=True)
            return result if isinstance(result, dict) else {"status": "REJECTED", "reason": "invalid_publisher_result"}
        time.sleep(POLL_SECONDS)
    return {"status": "REJECTED", "reason": "publisher_unavailable_or_timeout"}


def install(core):
    """Replace legacy direct-Git publication with the staged runner boundary."""

    def apply_and_publish_patch(job, iteration, handoff):
        payload = handoff.get("patch_b64")
        if not payload:
            return "PI5_PATCH=none\n"
        if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local":
            return "PI5_PATCH=blocked_for_cloud_authored_private_job\n"
        try:
            patch = base64.b64decode(payload, validate=True)
        except Exception as exc:
            return f"PI5_PATCH=invalid_base64 error={type(exc).__name__}\n"
        if len(patch) > core.MAX_PATCH_BYTES:
            return f"PI5_PATCH=rejected size={len(patch)} limit={core.MAX_PATCH_BYTES}\n"
        expected_base = str(handoff.get("base") or "")
        if not re.fullmatch(r"[0-9a-f]{40,64}", expected_base):
            try:
                expected_base = core.git("rev-parse", "HEAD").stdout.strip()
            except Exception:
                return "PI5_PATCH=RETRY error=canonical_head_unavailable\n"
        result = _submit(
            core,
            operation="patch",
            job=job,
            payload=patch,
            expected_base=expected_base,
            iteration=iteration,
        )
        if result.get("status") != "PASS":
            return f"PI5_PATCH=RETRY error={result.get('reason','publisher_rejected')}\n"
        files = result.get("files") or []
        return (
            "PI5_PATCH=APPLIED\n"
            f"PI5_COMMIT={result.get('commit','UNAVAILABLE')}\n"
            f"PI5_FILES={','.join(str(x) for x in files[:50])}\n"
            "PI5_PUSH=PASS\n"
        )

    def publish_runtime_artifact(job, handoff):
        if not core.JOB_ID_PATTERN.fullmatch(str(job.get("id", ""))):
            return False, core._artifact_evidence(
                f"{core.RUNTIME_PREFIX}[rejected].sh", None, None, False, "invalid_job_id"
            )
        rel = handoff.get("run_script")
        payload = handoff.get("runtime_b64")
        expected = f"{core.RUNTIME_PREFIX}{job['id']}.sh"
        if not rel and not payload:
            return False, "RUNTIME_ACTION=none_declared\n"
        if rel != expected:
            return False, core._artifact_evidence(expected, None, None, False, "rejected_path")
        if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local":
            return False, core._artifact_evidence(expected, None, None, False, "cloud_authored_private_job")
        try:
            script = base64.b64decode(payload or "", validate=True)
            if len(script) > core.MAX_RUNTIME_BYTES:
                raise ValueError("size_limit")
            text = script.decode("utf-8", errors="strict")
            if not text.startswith("#!/usr/bin/env bash"):
                raise ValueError("invalid_shebang")
        except Exception as exc:
            return False, core._artifact_evidence(expected, None, None, False, f"invalid_payload_{type(exc).__name__}")
        digest = hashlib.sha256(script).hexdigest()
        already, evidence = core.verify_runtime_artifact(job["id"], digest)
        if already:
            return True, evidence
        try:
            expected_base = core.git("rev-parse", "HEAD").stdout.strip()
        except Exception:
            return False, core._artifact_evidence(expected, digest, None, False, "canonical_head_unavailable")
        result = _submit(
            core,
            operation="runtime",
            job=job,
            payload=script,
            expected_base=expected_base,
            rel=expected,
        )
        if result.get("status") != "PASS":
            return False, core._artifact_evidence(
                expected, digest, None, False, str(result.get("reason") or "publisher_rejected")
            )
        return core.verify_runtime_artifact(job["id"], digest)

    core.apply_and_publish_patch = apply_and_publish_patch
    core.publish_runtime_artifact = publish_runtime_artifact
    return core
