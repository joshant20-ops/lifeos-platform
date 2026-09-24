#!/usr/bin/env python3
import base64
import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import re
import socket
import statistics
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import uuid
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

_JOB_RECORDS_SPEC = importlib.util.spec_from_file_location(
    "lifeos_job_records", pathlib.Path(__file__).with_name("job_records.py")
)
_JOB_RECORDS = importlib.util.module_from_spec(_JOB_RECORDS_SPEC)
_JOB_RECORDS_SPEC.loader.exec_module(_JOB_RECORDS)
publish_record = _JOB_RECORDS.publish_record

_TARGET_IDENTITY_SPEC = importlib.util.spec_from_file_location(
    "lifeos_target_identity", pathlib.Path(__file__).with_name("target_identity.py")
)
_TARGET_IDENTITY = importlib.util.module_from_spec(_TARGET_IDENTITY_SPEC)
_TARGET_IDENTITY_SPEC.loader.exec_module(_TARGET_IDENTITY)
load_target_id = _TARGET_IDENTITY.load_target_id

_AI_BROKER_PATH = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")) / "governor" / "ai_broker.py"
if not _AI_BROKER_PATH.is_file():
    _AI_BROKER_PATH = pathlib.Path(__file__).resolve().with_name("ai_broker.py")
_AI_BROKER_SPEC = importlib.util.spec_from_file_location("lifeos_agent_ai_broker", _AI_BROKER_PATH)
_AI_BROKER = importlib.util.module_from_spec(_AI_BROKER_SPEC)
_AI_BROKER_SPEC.loader.exec_module(_AI_BROKER)

ROOT = pathlib.Path(os.environ.get("LIFEOS_AGENT_STATE", "/var/lib/lifeos-agent"))
ROOT.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("LIFEOS_AGENT_PORT", "8790"))
MAX_ITERATIONS = int(os.environ.get("LIFEOS_AGENT_MAX_ITERATIONS", "3"))
BUILDER = os.environ.get("LIFEOS_AGENT_BUILDER", "/usr/local/libexec/lifeos-cloud-builder")
LOCAL_BUILDER = os.environ.get("LIFEOS_AGENT_LOCAL_BUILDER", "")
ENGINEER_HOST = os.environ.get("LIFEOS_ENGINEER_HOST", "192.168.0.204")
ENGINEER_SSH_PORT = int(os.environ.get("LIFEOS_ENGINEER_SSH_PORT", "22"))
ENGINEER_WAKE_TIMEOUT = int(os.environ.get("LIFEOS_ENGINEER_WAKE_TIMEOUT", "120"))
BUILDER_TIMEOUT_SECONDS = int(os.environ.get("LIFEOS_BUILDER_TIMEOUT_SECONDS", "300"))
DISPATCH_TOKEN_FILE = os.environ.get("LIFEOS_BACKLOG_DISPATCH_TOKEN_FILE", "")
VERIFIER_URL = os.environ.get("LIFEOS_LOCAL_VERIFIER_URL", "http://192.168.0.201:11434/api/generate")
VERIFIER_MODEL = os.environ.get("LIFEOS_LOCAL_VERIFIER_MODEL", "qwen2.5-coder:7b-instruct")
PLATFORM_REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/lifeos-platform")).resolve()
PRIVACY_DOMAIN_POLICY_PATH = pathlib.Path(
    os.environ.get(
        "LIFEOS_PRIVACY_DOMAIN_POLICY",
        str(pathlib.Path(__file__).with_name("privacy-domain-policy.json")),
    )
)
UI_PATH = PLATFORM_REPO / "governor" / "agent_ui.html"
RUNTIME_ROOT = pathlib.Path(os.environ.get("LIFEOS_RUNTIME_ARTIFACT_ROOT", str(ROOT / "runtime_jobs"))).resolve()
RUNTIME_PREFIX = "runtime_jobs/"
JOB_ID_PATTERN = re.compile(r"\A[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}\Z")
MAX_PATCH_BYTES = 1048576
MAX_RUNTIME_BYTES = 65536
REPEATED_FAILURE_LIMIT = int(os.environ.get("LIFEOS_REPEATED_FAILURE_LIMIT", "3"))
STUCK_JOB_MULTIPLIER = float(os.environ.get("LIFEOS_STUCK_JOB_MULTIPLIER", "3.0"))
STUCK_JOB_MIN_SECONDS = int(os.environ.get("LIFEOS_STUCK_JOB_MIN_SECONDS", "300"))
EXECUTION_LOCK = threading.Lock()
ACTIVE_JOB_LOCK = threading.Lock()
ACTIVE_JOB_ID = None
DISPATCH_BUILDER_CLASSES = frozenset({"normal", "local"})
RETIRED_CONTINUATION_FIELDS = frozenset({
    "continuation_enabled", "continuation_depth", "continuation_reason", "continuation_request",
})
CANONICAL_ASSERTION_KINDS = frozenset({"tracked_text_contains", "tracked_path_absent"})
DEPLOYMENT_OPERATIONS = frozenset({
    "deploy-engineer-runtime", "deploy-autonomous-agent",
})

INCOMPLETE_CONTRACT_STATES = frozenset({
    "PENDING", "NOT_STARTED", "NOT_IMPLEMENTED", "NOT_VERIFIED",
    "NOT_ATTEMPTED", "UNKNOWN", "INCOMPLETE",
})


def submit_control_job(manifest_json, script_bytes):
    """Submit only an exact manifest and script to the local fixed-purpose bridge."""
    if not isinstance(manifest_json, str) or not isinstance(script_bytes, (bytes, bytearray)):
        return {"status": "REJECTED", "reason": "manifest_json and script bytes required"}
    if len(manifest_json.encode()) > 32768 or len(script_bytes) > 262144:
        return {"status": "REJECTED", "reason": "control-job package exceeds size limit"}
    request = {
        "operation": "submit-control-job",
        "manifest": manifest_json,
        "script_base64": base64.b64encode(bytes(script_bytes)).decode("ascii"),
    }
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(15)
            client.connect("/run/lifeos-control-job-submit.sock")
            client.sendall(json.dumps(request, separators=(",", ":")).encode())
            client.shutdown(socket.SHUT_WR)
            response = b""
            while len(response) <= 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        result = json.loads(response)
        return result if isinstance(result, dict) else {"status": "REJECTED", "reason": "invalid bridge response"}
    except Exception as exc:
        return {"status": "REJECTED", "reason": f"submission bridge unavailable: {type(exc).__name__}"}


def request_bounded_deployment(job_id, intent):
    """Map an exact declarative intent to a fixed broker operation."""
    if intent not in DEPLOYMENT_OPERATIONS:
        return {"status": "REJECTED", "reason": "deployment operation not allowlisted"}
    try:
        request = {"operation": intent, "job_id": str(job_id), "target": load_target_id()}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(180)
            client.connect("/run/lifeos-root-broker.sock")
            client.sendall((json.dumps(request, sort_keys=True) + "\n").encode())
            client.shutdown(socket.SHUT_WR)
            response = b""
            while len(response) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    break
                response += chunk
        payload = json.loads(response.decode())
        if not isinstance(payload, dict):
            raise ValueError("broker response was not an object")
        return payload
    except Exception as exc:
        return {"status": "REJECTED", "reason": f"root broker unavailable: {type(exc).__name__}"}


def request_engineer_runtime_deployment(job_id):
    """Compatibility interface for existing Engineer jobs."""
    return request_bounded_deployment(job_id, "deploy-engineer-runtime")

PRIVATE_PATTERNS = (
    r"\bpaperless\b",
    r"\bprivate (?:data|documents?|files?|records?|information)\b",
    r"\bpersonal (?:data|documents?|files?|records?|information)\b",
    r"\bmedical (?:data|records?|documents?|information)\b",
    r"\bhealth (?:data|records?|documents?|information)\b",
    r"\bpassport(?:s)?\b",
    r"\bbank (?:accounts?|statements?|details|records?|documents?)\b",
    r"\bfinancial (?:statements?|records?|data|documents?)\b",
    r"\bpersonal (?:invoice|invoices|email|emails|mailbox|inbox)\b",
    r"\b(?:email|emails|mailbox|inbox)\b.{0,40}\b(?:private|personal|messages?|content)\b",
)

def now():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def _parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%dT%H:%M:%S%z")
    except Exception:
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None


def job_path(job_id):
    return ROOT / f"{job_id}.json"


def save(job):
    tmp = job_path(job["id"]).with_suffix(".tmp")
    tmp.write_text(json.dumps(job, indent=2, sort_keys=True))
    os.replace(tmp, job_path(job["id"]))


def load(job_id):
    return json.loads(job_path(job_id).read_text())


def list_jobs(limit=None):
    jobs = []
    paths = sorted(ROOT.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if limit is not None:
        paths = paths[:limit]
    for path in paths:
        try:
            jobs.append(json.loads(path.read_text()))
        except Exception:
            continue
    return jobs


def set_stage(job, stage, detail=None):
    job["stage"] = stage
    job["stage_changed_at"] = now()
    if detail:
        job["stage_detail"] = str(detail)[:1000]
    else:
        job.pop("stage_detail", None)
    save(job)


def finish_job(job, stage, detail=None):
    """Persist terminal runtime state and attempt its sanitised Git record."""
    set_stage(job, stage, detail)
    job["record_publication"] = publish_record(PLATFORM_REPO, job)
    save(job)
    return job


def completed_job_durations(jobs=None):
    durations = []
    for job in jobs if jobs is not None else list_jobs():
        if str(job.get("status") or "").upper() != "PASS":
            continue
        start = _parse_time(job.get("started_at") or job.get("created_at"))
        end = _parse_time(job.get("completed_at"))
        if start and end and end >= start:
            durations.append((end - start).total_seconds())
    return durations


def stuck_jobs(jobs=None, at=None):
    jobs = list(jobs if jobs is not None else list_jobs())
    at = at or datetime.now().astimezone()
    history = completed_job_durations(jobs)
    historical_limit = 0.0
    if history:
        historical_limit = max(
            statistics.median(history) * STUCK_JOB_MULTIPLIER,
            max(history) * 1.5,
        )
    threshold = max(float(STUCK_JOB_MIN_SECONDS), historical_limit)
    result = []
    for job in jobs:
        status = str(job.get("status") or "").upper()
        if status not in ("RUNNING", "QUEUED", "PENDING", "STAGING"):
            continue
        changed = _parse_time(job.get("stage_changed_at") or job.get("started_at") or job.get("created_at"))
        if not changed:
            continue
        age = max(0.0, (at - changed).total_seconds())
        if age <= threshold:
            continue
        item = {k: job.get(k) for k in (
            "id", "status", "stage", "stage_changed_at", "created_at", "started_at",
            "request", "repeated_failure_count",
        ) if k in job}
        item["stage_age_seconds"] = int(age)
        item["stuck_threshold_seconds"] = int(threshold)
        source = "persisted successful-job duration history" if historical_limit else "minimum deterministic threshold"
        item["stuck_reason"] = (
            f"stage has not advanced for {int(age)}s, exceeding conservative threshold "
            f"{int(threshold)}s from {source}"
        )
        result.append(item)
    return result


def _privacy_domain_policy():
    """Load the runtime privacy policy; any policy failure must fail closed."""
    try:
        policy = json.loads(PRIVACY_DOMAIN_POLICY_PATH.read_text())
        if policy.get("schema_version") != 1 or policy.get("fail_closed") is not True:
            return None
        if not isinstance(policy.get("domains"), dict):
            return None
        return policy
    except Exception:
        return None


def _privacy_term_matches(lower, term):
    normalized = re.escape(str(term).strip().lower())
    normalized = normalized.replace(r"\ ", r"[\s_-]+").replace(r"\-", r"[\s_-]+")
    return bool(normalized and re.search(rf"(?<!\w){normalized}(?!\w)", lower))


def classify_privacy(text, domain=None):
    lower = str(text or "").lower()
    if any(re.search(pattern, lower) for pattern in PRIVATE_PATTERNS):
        return "local-only"
    policy = _privacy_domain_policy()
    if policy is None:
        return "local-only"
    domains = policy["domains"]
    if domain:
        key = re.sub(r"[\s_]+", "-", str(domain).strip().lower())
        rule = domains.get(key)
        if not isinstance(rule, dict):
            return "local-only"
        return "local-only" if rule.get("privacy") == "local-only" else str(policy.get("default") or "normal")
    for rule in domains.values():
        if not isinstance(rule, dict) or rule.get("privacy") != "local-only":
            continue
        if any(_privacy_term_matches(lower, term) for term in rule.get("request_terms", ())):
            return "local-only"
    return str(policy.get("default") or "normal")


def _dispatcher_token():
    path = DISPATCH_TOKEN_FILE
    if not path:
        credentials = os.environ.get("CREDENTIALS_DIRECTORY", "")
        if credentials:
            path = str(pathlib.Path(credentials) / "backlog-dispatcher.token")
    if not path:
        return ""
    try:
        return pathlib.Path(path).read_text().strip()
    except OSError:
        return ""


def _ai_broker_token():
    path = os.environ.get(
        "LIFEOS_AI_BROKER_TOKEN_FILE",
        str(pathlib.Path.home() / ".config/lifeos/ai-broker.token"),
    )
    try:
        return pathlib.Path(path).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _authenticated_ai_broker(headers):
    expected = _ai_broker_token()
    supplied = str(headers.get("Authorization", ""))
    return bool(
        expected
        and supplied.startswith("Bearer ")
        and hmac.compare_digest(supplied[7:].encode(), expected.encode())
    )


def authenticated_dispatch_route(headers, body):
    """Validate the backlog dispatcher's bounded, authenticated route assertion."""
    if "dispatch_builder" not in body:
        return None, None
    route = body.get("dispatch_builder")
    if not isinstance(route, str) or route not in DISPATCH_BUILDER_CLASSES:
        return None, "invalid_dispatch_builder"
    expected = _dispatcher_token()
    supplied = str(headers.get("Authorization", ""))
    if not expected or not supplied.startswith("Bearer "):
        return None, "dispatcher_capability_required"
    if not hmac.compare_digest(supplied[7:].encode(), expected.encode()):
        return None, "dispatcher_capability_required"
    return route, None


def extract_mandatory_final_fields(request):
    """Return reusable KEY= final-contract fields explicitly declared by a job."""
    fields = []
    in_contract = False
    for raw_line in str(request or "").splitlines():
        line = raw_line.strip()
        lowered = line.lower()
        if ("final status must explicitly report" in lowered
                or "final output contract" in lowered):
            in_contract = True
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=.*", line)
        if in_contract and match and match.group(1) not in fields:
            fields.append(match.group(1))
    return fields


def _contract_value(evidence, field):
    values = re.findall(rf"(?m)^{re.escape(field)}\s*=\s*(.*?)\s*$", str(evidence or ""))
    return values[-1] if values else None


def milestone_decision(job, iteration_verdict, evidence):
    """Separate an independent iteration verdict from milestone completion."""
    verdict = str((iteration_verdict or {}).get("verdict") or "RETRY").upper()
    if verdict not in {"PASS", "RETRY", "BLOCKED"}:
        verdict = "RETRY"
    result = {
        "iteration_result": verdict,
        "milestone_result": verdict,
        "reason": str((iteration_verdict or {}).get("reason") or ""),
        "next_instruction": str((iteration_verdict or {}).get("next_instruction") or ""),
    }
    if verdict == "BLOCKED":
        # BLOCKED is terminal only when the verifier supplies a concrete
        # external/user-only boundary. Generic or self-referential blocker
        # prose is actionable engineering uncertainty and must be retried.
        reason = result["reason"].strip()
        lower_reason = reason.lower()
        external_markers = (
            "credential", "hardware", "physical", "policy",
            "authorization", "authorisation", "consent",
        )
        # A terminal BLOCKED result must identify the actual external boundary.
        # Model prose that merely says a user-only blocker exists, or describes
        # missing engineering/evidence output, is retryable work.
        actionable_markers = (
            "engineering", "deployment", "implementation", "current gap",
            "further engineering", "further deployment", "missing evidence",
            "not yet satisfied", "not satisfied", "requires repair",
        )
        generic = (
            not reason
            or "without providing a structured reason" in lower_reason
            or "genuine user-only blocker" in lower_reason
            or "user-only blocker exists" in lower_reason
            or "cannot resolve itself" in lower_reason
            or any(marker in lower_reason for marker in actionable_markers)
            or not any(marker in lower_reason for marker in external_markers)
        )
        if generic:
            result["milestone_result"] = "RETRY"
            result["reason"] = "BLOCKED verdict lacked a concrete evidenced external boundary"
            result["next_instruction"] = (
                "Continue autonomously: repair actionable engineering gaps or provide "
                "specific evidence of the exact external/user-only boundary."
            )
        return result
    if verdict != "PASS":
        return result
    fields = list(job.get("mandatory_final_fields") or [])
    incomplete = []
    for field in fields:
        value = _contract_value(evidence, field)
        normalized = re.sub(r"[\s-]+", "_", str(value or "").strip().upper())
        if value is None or normalized in INCOMPLETE_CONTRACT_STATES:
            incomplete.append(field)
    if incomplete:
        result["milestone_result"] = "RETRY"
        result["reason"] = "mandatory milestone contract is incomplete: " + ", ".join(incomplete)
        result["next_instruction"] = (
            "Continue with the next useful phase and provide completed evidence for: "
            + ", ".join(incomplete)
        )
    return result


def _parse_json_object(value):
    """Extract one valid JSON object from strict, fenced, or prefaced model output."""
    text = str(value or "").strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise json.JSONDecodeError("model did not return a JSON object", text, 0)


def local_verify(job, iteration, evidence):
    prompt = f"""You are the independent LOCAL verifier for LifeOS.
Decide whether the user's original goal is actually complete from supplied BUILD, PUBLICATION, AND RUNTIME evidence.
Return JSON only with keys: verdict, reason, next_instruction.
verdict must be PASS, RETRY, or BLOCKED.

Rules:
- PASS only when evidence demonstrates the requested outcome works.
- RETRY when there is any actionable engineering, deployment, configuration, testing, or repair step the autonomous system can attempt itself.
- BLOCKED is reserved for a genuinely external blocker the autonomous system cannot resolve itself, such as missing user-only credentials, unavailable required hardware, a required physical action, or a safety/privacy policy prohibition.
- Unrelated pre-existing repository failures are not a blocker for a scoped job.
- A builder saying BLOCKED does not force BLOCKED if the issue is internally actionable.
- Do not ask the user to run diagnostics the automation can run itself.
- Do not assume success merely because a process exited zero.
- If evidence shows the same deterministic failure as a prior iteration, change the plan materially rather than repeating the same action.

User goal: {job['request']}
Privacy class: {job['privacy']}
Iteration: {iteration}
Evidence:\n{evidence[-18000:]}
"""
    result = _AI_BROKER.generate(prompt, privacy="local-only", task_class="normal", force_provider="ollama")
    raw = result.get("text", "{}")
    try:
        return _parse_json_object(raw)
    except json.JSONDecodeError:
        return {"verdict": "RETRY", "reason": "verifier returned invalid JSON", "next_instruction": "Repeat focused local verification and return valid JSON."}


def validate_canonical_assertions(value):
    """Validate bounded, data-only assertions supplied by a trusted controller."""
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > 8:
        raise ValueError("invalid_canonical_assertions")
    assertions = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("invalid_canonical_assertion")
        assertion_id = str(item.get("id") or "")
        kind = str(item.get("kind") or "")
        expected = item.get("value")
        required_keys = (
            {"id", "kind", "path", "value"}
            if kind == "tracked_text_contains"
            else {"id", "kind", "value"}
        )
        if set(item) != required_keys:
            raise ValueError("invalid_canonical_assertion")
        if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", assertion_id) or assertion_id in seen:
            raise ValueError("invalid_canonical_assertion_id")
        if kind not in CANONICAL_ASSERTION_KINDS:
            raise ValueError("invalid_canonical_assertion_kind")
        if not isinstance(expected, str) or not expected or len(expected) > 512 or "\n" in expected:
            raise ValueError("invalid_canonical_assertion_value")
        if kind == "tracked_text_contains":
            path = item.get("path")
            if (
                not isinstance(path, str)
                or not path
                or len(path) > 256
                or path.startswith("/")
                or "\\" in path
                or any(part in {"", ".", ".."} for part in path.split("/"))
            ):
                raise ValueError("invalid_canonical_assertion_path")
        seen.add(assertion_id)
        assertion = {"id": assertion_id, "kind": kind, "value": expected}
        if kind == "tracked_text_contains":
            assertion["path"] = path
        assertions.append(assertion)
    return assertions


def verify_canonical_assertions(job):
    """Independently verify declared outcomes against the clean canonical checkout."""
    assertions = list(job.get("canonical_assertions") or [])
    if not assertions:
        return None, "CANONICAL_ASSERTIONS=none\n"
    try:
        head = git("rev-parse", "HEAD").stdout.strip()
        origin_main = git("rev-parse", "origin/main").stdout.strip()
        dirty = bool(git("status", "--porcelain", check=False).stdout.strip())
    except Exception as exc:
        return False, f"CANONICAL_ASSERTIONS=FAIL reason=repository_unavailable_{type(exc).__name__}\n"
    lines = [
        f"CANONICAL_HEAD={head}",
        f"CANONICAL_ORIGIN_MAIN={origin_main}",
        f"CANONICAL_CLEAN={'PASS' if not dirty else 'FAIL'}",
        f"CANONICAL_ALIGNED={'PASS' if head == origin_main else 'FAIL'}",
    ]
    passed = not dirty and head == origin_main
    for assertion in assertions:
        if assertion["kind"] == "tracked_text_contains":
            result = subprocess.run(
                [
                    "git", "grep", "-F", "-q", "--", assertion["value"],
                    f"HEAD:{assertion['path']}",
                ],
                cwd=PLATFORM_REPO,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            item_passed = result.returncode == 0
        else:
            result = subprocess.run(
                ["git", "cat-file", "-e", f"HEAD:{assertion['value']}"],
                cwd=PLATFORM_REPO,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
            item_passed = result.returncode != 0
        passed = passed and item_passed
        lines.append(
            "CANONICAL_ASSERTION_"
            + assertion["id"].upper().replace("-", "_")
            + f"={'PASS' if item_passed else 'FAIL'} kind={assertion['kind']}"
        )
    lines.append(f"CANONICAL_ASSERTIONS={'PASS' if passed else 'FAIL'}")
    return passed, "\n".join(lines) + "\n"


def independent_verify(job, iteration, evidence, canonical_result):
    """Use deterministic canonical assertions when declared, else local AI review."""
    if canonical_result is True:
        return {
            "verdict": "PASS",
            "reason": "declared canonical assertions passed independent deterministic verification",
            "next_instruction": "",
        }
    if canonical_result is False:
        return {
            "verdict": "RETRY",
            "reason": "declared canonical assertions are not satisfied in the clean aligned canonical checkout",
            "next_instruction": "Continue governed engineering until the declared canonical assertions pass.",
        }
    return local_verify(job, iteration, evidence)


def _marker(text, name):
    m = re.findall(rf"(?m)^{re.escape(name)}=(.*)$", text)
    return m[-1].strip() if m else None


def parse_handoff(raw):
    deployment_operation = _marker(raw, "DEPLOYMENT_OPERATION")
    if deployment_operation not in DEPLOYMENT_OPERATIONS:
        deployment_operation = None
    handoff = {
        "base": _marker(raw, "HANDOFF_BASE"),
        "patch_b64": _marker(raw, "HANDOFF_PATCH_B64"),
        "runtime_b64": _marker(raw, "HANDOFF_RUNTIME_B64"),
        "run_script": _marker(raw, "RUN_SCRIPT"),
        "deployment_operation": deployment_operation,
    }
    sanitized = re.sub(r"(?m)^HANDOFF_(?:PATCH|RUNTIME)_B64=.*$", "HANDOFF_PAYLOAD=[redacted from verifier evidence]", raw)
    sanitized = re.sub(
        r"(?m)^RUNTIME_ARTIFACT_(?:PATH|SHA256|COMMIT|PUBLISHED)=.*$",
        "UNTRUSTED_BUILDER_PUBLICATION_CLAIM=[removed]",
        sanitized,
    )
    return handoff, sanitized


def failure_signature(evidence, verdict):
    lines = []
    patterns = (
        r"(?m)^RUNTIME_RC=.*$",
        r"(?m)^RESULT=FAIL.*$",
        r"(?m)^REASON=.*$",
        r"(?m)^DEPLOYMENT_FAILURE=.*$",
        r"(?m)^PRIVILEGED_BOOTSTRAP_REQUIRED.*$",
        r"(?m)^PI5_PATCH=RETRY.*$",
        r"(?m)^HANDOFF_ERROR=.*$",
    )
    for pattern in patterns:
        matches = re.findall(pattern, evidence)
        if matches:
            lines.append(matches[-1])
    reason = str((verdict or {}).get("reason") or "").strip()
    if reason:
        lines.append("VERIFIER_REASON=" + reason[:1000])
    if not lines:
        return None
    normalized = "\n".join(lines)
    normalized = re.sub(r"\b[a-f0-9]{12,64}\b", "<id>", normalized, flags=re.I)
    normalized = re.sub(r"\b\d{4}-\d{2}-\d{2}T[^\s]+", "<time>", normalized)
    normalized = re.sub(r"line=\d+", "line=<n>", normalized)
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def update_failure_history(job, signature):
    if not signature:
        job["repeated_failure_count"] = 0
        job.pop("last_failure_signature", None)
        return 0
    if job.get("last_failure_signature") == signature:
        count = int(job.get("repeated_failure_count") or 1) + 1
    else:
        count = 1
    job["last_failure_signature"] = signature
    job["repeated_failure_count"] = count
    return count


def _prepare_engineer_builder_host():
    """Acquire Tower compute and wait for the automatically booted Engineer VM."""
    _AI_BROKER._publish_lease("active")
    try:
        _AI_BROKER._wake_local_ai()
        deadline = time.monotonic() + ENGINEER_WAKE_TIMEOUT
        last_error = "not attempted"
        while time.monotonic() < deadline:
            _AI_BROKER._publish_lease("active")
            try:
                with socket.create_connection((ENGINEER_HOST, ENGINEER_SSH_PORT), timeout=3):
                    return
            except OSError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                time.sleep(3)
        raise RuntimeError(
            f"Engineer VM did not become SSH-ready at {ENGINEER_HOST}:{ENGINEER_SSH_PORT} "
            f"after Tower wake ({last_error})"
        )
    except Exception:
        _AI_BROKER._publish_lease("released", required=False)
        raise


def run_builder(job, iteration, verifier_feedback=None):
    route, builder = builder_route(job)
    if not builder:
        return 78, "BUILDER_ROUTE=local\nLOCAL_BUILDER=UNAVAILABLE\n", {
            "_builder_route": route,
        }
    env = os.environ.copy()
    env["LIFEOS_JOB_ID"] = job["id"]
    env["LIFEOS_JOB_PRIVACY"] = job["privacy"]
    args = [builder, job["request"], str(iteration)]
    if verifier_feedback:
        args.append(verifier_feedback)
    tower_lease = route == "normal"
    if tower_lease:
        _prepare_engineer_builder_host()
    try:
        try:
            cp = subprocess.run(args, text=True, capture_output=True, timeout=BUILDER_TIMEOUT_SECONDS, env=env)
        except subprocess.TimeoutExpired as exc:
            # A bounded builder timeout is an actionable engineering result, not
            # an uncaught worker exception that leaves the Governor job RUNNING.
            stdout = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = exc.stderr.decode(errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            raw = stdout + "\n" + stderr
            handoff, evidence = parse_handoff(raw)
            handoff["_builder_route"] = route
            evidence += f"\nHANDOFF_ERROR=builder_timeout_{BUILDER_TIMEOUT_SECONDS}s\nRESULT=RETRY\nREASON=builder_timeout\n"
            return 124, f"BUILDER_ROUTE={route}\n" + evidence, handoff
    finally:
        if tower_lease:
            _AI_BROKER._publish_lease("released", required=False)
    raw = (cp.stdout or "") + "\n" + (cp.stderr or "")
    handoff, evidence = parse_handoff(raw)
    handoff["_builder_route"] = route
    return cp.returncode, f"BUILDER_ROUTE={route}\n" + evidence, handoff


def builder_route(job):
    """Select a capable builder without weakening the job's privacy class."""
    if job.get("privacy") == "local-only":
        route = "local"
    else:
        route = job.get("dispatch_builder") or "normal"
    if route == "normal":
        return "normal", BUILDER
    if LOCAL_BUILDER and pathlib.Path(LOCAL_BUILDER).is_file() and os.access(LOCAL_BUILDER, os.X_OK):
        return "local", LOCAL_BUILDER
    return "local", None


def git(*args, check=True, timeout=120):
    return subprocess.run(["git", *args], cwd=PLATFORM_REPO, text=True, capture_output=True, check=check, timeout=timeout)


def repo_context():
    result = {"status": "ok"}
    try:
        result["head"] = git("rev-parse", "HEAD").stdout.strip()
        result["branch"] = git("symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip() or "detached"
        result["dirty"] = bool(git("status", "--porcelain", check=False).stdout.strip())
        result["origin_main"] = git("rev-parse", "origin/main", check=False).stdout.strip()
    except Exception as exc:
        return {"status": "unavailable", "detail": type(exc).__name__}
    running = [j for j in list_jobs(20) if j.get("status") in ("QUEUED", "RUNNING")]
    result["active_jobs"] = [
        {k: j.get(k) for k in ("id", "status", "stage", "stage_changed_at", "created_at", "started_at", "request")}
        for j in running[:5]
    ]
    result["stuck_jobs"] = stuck_jobs(list_jobs(100))
    return result


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
    if len(patch) > MAX_PATCH_BYTES:
        return f"PI5_PATCH=rejected size={len(patch)} limit={MAX_PATCH_BYTES}\n"
    status = git("status", "--porcelain").stdout.strip()
    if status:
        return "PI5_PATCH=retry canonical_checkout_dirty\n" + status[-4000:] + "\n"
    try:
        git("fetch", "origin", "main")
        head = git("rev-parse", "HEAD").stdout.strip()
        origin_main = git("rev-parse", "origin/main").stdout.strip()
        if head != origin_main:
            return f"PI5_PATCH=retry canonical_not_at_origin_main head={head} origin_main={origin_main}\n"
        patch_file = ROOT / f"{job['id']}-{iteration}.patch"
        patch_file.write_bytes(patch)
        subprocess.run(["git", "apply", "--check", str(patch_file)], cwd=PLATFORM_REPO, check=True, text=True, capture_output=True, timeout=30)
        subprocess.run(["git", "apply", str(patch_file)], cwd=PLATFORM_REPO, check=True, text=True, capture_output=True, timeout=30)
        patch_file.unlink(missing_ok=True)
        git("add", "-A")
        git("diff", "--cached", "--check")
        staged = git("diff", "--cached", "--name-only").stdout.splitlines()
        if not staged:
            return "PI5_PATCH=no_effect\n"
        commit = git("commit", "-m", f"agent: job {job['id']} iteration {iteration}", timeout=60).stdout
        sha = git("rev-parse", "HEAD").stdout.strip()
        push = git("push", "origin", "HEAD:main", timeout=180)
        return "PI5_PATCH=APPLIED\nPI5_COMMIT=" + sha + "\nPI5_FILES=" + ",".join(staged[:50]) + "\nPI5_PUSH=PASS\n" + commit[-2000:] + push.stdout[-1000:] + push.stderr[-1000:] + "\n"
    except subprocess.CalledProcessError as exc:
        detail = ((exc.stdout or "") + "\n" + (exc.stderr or ""))[-5000:]
        return f"PI5_PATCH=RETRY error=command_failed rc={exc.returncode}\n{detail}\n"
    except Exception as exc:
        return f"PI5_PATCH=RETRY error={type(exc).__name__}:{exc}\n"


def _runtime_candidate_path(job_id):
    candidate_dir = ROOT / "artifact_candidates"
    candidate_dir.mkdir(mode=0o750, parents=True, exist_ok=True)
    return candidate_dir / f"{job_id}.sh"


def _artifact_evidence(rel, digest, commit, published, reason=None):
    lines = [
        f"RUNTIME_ARTIFACT_PATH={rel}",
        f"RUNTIME_ARTIFACT_SHA256={digest or 'UNAVAILABLE'}",
        f"RUNTIME_ARTIFACT_COMMIT={commit or 'UNAVAILABLE'}",
        f"RUNTIME_ARTIFACT_PUBLISHED={'PASS' if published else 'FAIL'}",
    ]
    if reason:
        lines.extend((f"RUNTIME_ARTIFACT_REASON={reason}", "HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED"))
    return "\n".join(lines) + "\n"


def suppress_unpublished_runtime_instructions(evidence):
    """Remove executable human instructions when their artifact was not published."""
    filtered = []
    for line in evidence.splitlines():
        if line.startswith(("HUMAN_ACTION_REQUIRED=", "NEXT_RUNTIME_CHECK=")):
            filtered.append("HUMAN_ACTION_REQUIRED_ARTIFACT_NOT_PUBLISHED")
            continue
        line = re.sub(
            r"sudo\s+\S*governor/runtime_jobs/[A-Za-z0-9._/-]+\.sh",
            "[unpublished runtime command suppressed]",
            line,
        )
        filtered.append(line)
    return "\n".join(filtered) + ("\n" if evidence.endswith("\n") else "")


def verify_runtime_artifact(job_id, expected_sha256=None):
    """Prove a bounded runtime artifact exists outside the canonical Git checkout."""
    if not JOB_ID_PATTERN.fullmatch(str(job_id)):
        return False, _artifact_evidence(f"{RUNTIME_PREFIX}[rejected].sh", None, None, False, "invalid_job_id")
    rel = f"{RUNTIME_PREFIX}{job_id}.sh"
    target = RUNTIME_ROOT / f"{job_id}.sh"
    try:
        target.resolve().relative_to(RUNTIME_ROOT)
        if target.is_symlink() or not target.is_file():
            return False, _artifact_evidence(rel, None, None, False, "runtime_file_missing_or_unsafe")
        if not os.access(target, os.X_OK):
            return False, _artifact_evidence(rel, None, None, False, "runtime_file_not_executable")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        if expected_sha256 is not None and not hmac.compare_digest(digest, str(expected_sha256)):
            return False, _artifact_evidence(rel, digest, None, False, "sha256_mismatch")
        return True, _artifact_evidence(rel, digest, "RUNTIME_LOCAL", True)
    except Exception as exc:
        return False, _artifact_evidence(rel, None, None, False, f"verification_error_{type(exc).__name__}")

def publish_runtime_artifact(job, handoff):
    """Persist a candidate, then publish and prove it before it may be referenced."""
    if not JOB_ID_PATTERN.fullmatch(str(job.get("id", ""))):
        return False, _artifact_evidence(
            f"{RUNTIME_PREFIX}[rejected].sh", None, None, False, "invalid_job_id"
        )
    rel = handoff.get("run_script")
    payload = handoff.get("runtime_b64")
    expected = f"{RUNTIME_PREFIX}{job['id']}.sh"
    if not rel and not payload:
        return False, "RUNTIME_ACTION=none_declared\n"
    if rel != expected:
        return False, _artifact_evidence(expected, None, None, False, "rejected_path")
    if job["privacy"] == "local-only" and handoff.get("_builder_route") != "local":
        return False, _artifact_evidence(expected, None, None, False, "cloud_authored_private_job")
    try:
        script = base64.b64decode(payload or "", validate=True)
        if len(script) > MAX_RUNTIME_BYTES:
            raise ValueError("size_limit")
        text = script.decode("utf-8", errors="strict")
        if not text.startswith("#!/usr/bin/env bash"):
            raise ValueError("invalid_shebang")
    except Exception as exc:
        return False, _artifact_evidence(expected, None, None, False, f"invalid_payload_{type(exc).__name__}")
    candidate = _runtime_candidate_path(job["id"])
    candidate.write_bytes(script)
    candidate.chmod(0o700)
    digest = hashlib.sha256(script).hexdigest()
    already, evidence = verify_runtime_artifact(job["id"], digest)
    if already:
        return True, evidence
    try:
        RUNTIME_ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
        target = RUNTIME_ROOT / f"{job['id']}.sh"
        if target.is_symlink():
            return False, _artifact_evidence(expected, digest, None, False, "symlink_rejected")
        temporary = target.with_name(f".{target.name}.{job['id']}.tmp")
        temporary.write_bytes(script)
        temporary.chmod(0o700)
        os.replace(temporary, target)
        return verify_runtime_artifact(job["id"], digest)
    except Exception as exc:
        return False, _artifact_evidence(expected, digest, None, False, f"publication_error_{type(exc).__name__}")


def run_pi5_runtime(job, handoff):
    rel = handoff.get("run_script")
    payload = handoff.get("runtime_b64")
    if not rel and not payload:
        return "RUNTIME_ACTION=none_declared\n"
    published, publication = publish_runtime_artifact(job, handoff)
    if not published:
        return publication
    target = RUNTIME_ROOT / f"{job['id']}.sh"
    cp = subprocess.run(
        ["/usr/bin/timeout", "240s", str(target)],
        cwd=PLATFORM_REPO,
        text=True,
        capture_output=True,
        timeout=270,
        env={**os.environ, "LIFEOS_JOB_ID": job["id"], "LIFEOS_JOB_REQUEST": job["request"]},
    )
    out = (cp.stdout or "") + "\n" + (cp.stderr or "")
    return publication + f"RUNTIME_SCRIPT={rel}\nRUNTIME_RC={cp.returncode}\nPI5_RUNTIME_EVIDENCE:\n{out[-16000:]}\n"


def retain_runtime_publication(job, runtime_evidence):
    """Persist only validator-produced publication facts across later boundaries."""
    if "RUNTIME_ARTIFACT_PUBLISHED=PASS" in runtime_evidence:
        verified, publication = verify_runtime_artifact(job["id"])
    elif job.get("runtime_artifact"):
        expected = job["runtime_artifact"].get("sha256")
        verified, publication = verify_runtime_artifact(job["id"], expected)
        runtime_evidence = publication + runtime_evidence
    else:
        return runtime_evidence
    if not verified:
        job.pop("runtime_artifact", None)
        return runtime_evidence if publication in runtime_evidence else publication + runtime_evidence
    facts = {
        "path": _marker(publication, "RUNTIME_ARTIFACT_PATH"),
        "sha256": _marker(publication, "RUNTIME_ARTIFACT_SHA256"),
        "commit": _marker(publication, "RUNTIME_ARTIFACT_COMMIT"),
        "published": "PASS",
    }
    job["runtime_artifact"] = facts
    if "RUNTIME_ARTIFACT_PUBLISHED=PASS" not in runtime_evidence:
        runtime_evidence = publication + runtime_evidence
    return runtime_evidence


def _execute_job_locked(job):
    """Run bounded governed OTS sessions until independent acceptance is terminal."""
    job = load(job["id"])
    job["status"] = "RUNNING"
    job["started_at"] = now()
    job["engineering_loop"] = "ots-owned"
    max_iterations = int(os.environ.get("LIFEOS_ACCEPTANCE_RETRY_LIMIT", "3"))
    verifier_feedback = None

    for iteration in range(1, max_iterations + 1):
        set_stage(job, "builder", f"OTS agent iteration {iteration} owns plan/edit/test/debug")
        rec = {"iteration": iteration, "started_at": now(), "owner": "ots-agent"}
        try:
            rc, build_evidence, handoff = run_builder(job, iteration, verifier_feedback)
            rec["builder_rc"] = rc
        except Exception as exc:
            build_evidence = f"builder exception: {type(exc).__name__}: {exc}"
            handoff = {}
            rec["builder_rc"] = 255

        set_stage(job, "publication", "Governor bounded publication gate")
        publication = apply_and_publish_patch(job, iteration, handoff)
        set_stage(job, "runtime", "Governor bounded runtime/evidence gate")
        runtime = retain_runtime_publication(job, run_pi5_runtime(job, handoff))
        if "RUNTIME_ARTIFACT_PUBLISHED=FAIL" in runtime:
            build_evidence = suppress_unpublished_runtime_instructions(build_evidence)
        canonical_result, canonical_evidence = verify_canonical_assertions(job)
        evidence = (
            f"ENGINEERING_LOOP=ots-owned\\nBUILD_EVIDENCE:\\n{build_evidence[-12000:]}\\n\\n"
            f"PUBLICATION_EVIDENCE:\\n{publication[-7000:]}\\n\\n{runtime}\\n"
            f"INDEPENDENT_CANONICAL_EVIDENCE:\\n{canonical_evidence}"
        )
        rec["evidence"] = evidence[-26000:]

        set_stage(job, "verifier", "independent local acceptance gate")
        try:
            verdict = independent_verify(job, iteration, rec["evidence"], canonical_result)
        except Exception as exc:
            verdict = {
                "verdict": "RETRY",
                "reason": f"local verifier unavailable: {type(exc).__name__}",
                "next_instruction": "Retry independent verification after local verifier recovery.",
            }
        rec["verification"] = verdict
        decision = milestone_decision(job, verdict, rec["evidence"])
        rec["iteration_result"] = decision["iteration_result"]
        rec["milestone_result"] = decision["milestone_result"]
        rec["finished_at"] = now()
        signature = failure_signature(rec["evidence"], verdict)
        if signature:
            rec["failure_signature"] = signature
        job.setdefault("iterations", []).append(rec)

        if decision["milestone_result"] == "PASS":
            deployment_operation = handoff.get("deployment_operation")
            if bool(job.get("deploy_engineer_runtime")):
                deployment_operation = "deploy-engineer-runtime"
            if deployment_operation:
                set_stage(job, "deployment", "Governor approved bounded deployment gate")
                if deployment_operation == "deploy-engineer-runtime":
                    job["deployment"] = request_engineer_runtime_deployment(job["id"])
                else:
                    job["deployment"] = request_bounded_deployment(job["id"], deployment_operation)
                if job["deployment"].get("status") != "PASS":
                    job["status"] = "BLOCKED"
                    job["blocked_reason"] = "bounded runtime deployment was not approved or failed"
                    job["completed_at"] = now()
                    return finish_job(job, "blocked", job["blocked_reason"])
            job["status"] = "PASS"
            job["completed_at"] = now()
            return finish_job(job, "complete", "independent acceptance gate passed OTS result")

        reason = str(decision.get("reason") or "").strip()
        if decision["milestone_result"] == "BLOCKED":
            job["status"] = "BLOCKED"
            job["blocked_reason"] = reason or "concrete external boundary reported"
            job["completed_at"] = now()
            return finish_job(job, "blocked", job["blocked_reason"])

        verifier_feedback = str(decision.get("next_instruction") or reason or "Continue toward independently verifiable acceptance.")
        job["next_instruction"] = verifier_feedback
        if iteration < max_iterations:
            save(job)
            continue

        job["status"] = "FAILED"
        job["blocked_reason"] = reason or "bounded acceptance retries exhausted"
        job["completed_at"] = now()
        return finish_job(job, "acceptance_failed", job["blocked_reason"])


def execute_job(job):
    global ACTIVE_JOB_ID
    with EXECUTION_LOCK:
        with ACTIVE_JOB_LOCK:
            ACTIVE_JOB_ID = job["id"]
        try:
            _execute_job_locked(job)
        finally:
            with ACTIVE_JOB_LOCK:
                ACTIVE_JOB_ID = None


def new_job(request, retry_of=None, deploy_engineer_runtime=False, dispatch_builder=None,
            privacy_domain=None, canonical_assertions=None):
    normalized_domain = None
    if privacy_domain:
        normalized_domain = re.sub(r"[\s_]+", "-", str(privacy_domain).strip().lower())
    classified_privacy = classify_privacy(request, domain=normalized_domain)
    privacy = (
        "local-only"
        if dispatch_builder == "local" or classified_privacy == "local-only"
        else "normal"
    )
    job = {
        "id": uuid.uuid4().hex[:12],
        "created_at": now(),
        "request": request.strip(),
        "privacy": privacy,
        "status": "QUEUED",
        "stage": "queued",
        "stage_changed_at": now(),
        "iterations": [],
        "repeated_failure_count": 0,
        "deploy_engineer_runtime": bool(deploy_engineer_runtime),
        "mandatory_final_fields": extract_mandatory_final_fields(request),
        "canonical_assertions": validate_canonical_assertions(canonical_assertions),
    }
    if normalized_domain:
        job["privacy_domain"] = normalized_domain
    if retry_of:
        job["retry_of"] = retry_of
    if dispatch_builder in DISPATCH_BUILDER_CLASSES:
        job["dispatch_builder"] = dispatch_builder
    save(job)
    return job


def create_job(request, async_mode=False, retry_of=None, **job_options):
    # Do not create an unbounded in-memory thread queue behind the single
    # execution lock.  A caller can retry once the active governed job ends.
    if async_mode:
        with ACTIVE_JOB_LOCK:
            active = ACTIVE_JOB_ID
        if active:
            return {"status": "BUSY", "active_job_id": active}
    job = new_job(request, retry_of=retry_of, **job_options)
    if async_mode:
        threading.Thread(target=execute_job, args=(job,), daemon=True, name=f"job-{job['id']}").start()
        return job
    execute_job(job)
    return load(job["id"])


class Handler(BaseHTTPRequestHandler):
    def send_bytes(self, code, data, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, code, payload):
        self.send_bytes(code, json.dumps(payload, sort_keys=True).encode(), "application/json")

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/ui"):
            try:
                self.send_bytes(200, UI_PATH.read_bytes(), "text/html; charset=utf-8")
            except Exception as exc:
                self.send_json(503, {"error": "ui_unavailable", "detail": type(exc).__name__})
            return
        if path == "/health":
            self.send_json(200, {
                "service": "lifeos-autonomous-agent",
                "status": "ok",
                "max_iterations": MAX_ITERATIONS,
                "repeated_failure_limit": REPEATED_FAILURE_LIMIT,
                "stuck_job_multiplier": STUCK_JOB_MULTIPLIER,
                "engineering_session_owner": "openhands",
                "governor_continuation": "retired",
                "runtime_controller": "pi5",
                "git_controller": "pi5",
                "privacy_domain_policy": str(PRIVACY_DOMAIN_POLICY_PATH),
                "ui": "/",
            })
            return
        if path == "/context":
            self.send_json(200, repo_context())
            return
        if path == "/jobs":
            jobs = list_jobs()
            keys = (
                "id", "created_at", "started_at", "completed_at", "request", "privacy", "privacy_domain", "status",
                "stage", "stage_changed_at", "stage_detail", "retry_of", "repeated_failure_count",
                "dispatch_builder",
            )
            self.send_json(200, {"jobs": [{k: j.get(k) for k in keys if k in j} for j in jobs]})
            return
        if path == "/jobs/stuck":
            self.send_json(200, {"stuck_jobs": stuck_jobs()})
            return
        if path.startswith("/jobs/"):
            job_id = path.split("/", 2)[2]
            try:
                self.send_json(200, load(job_id))
            except Exception:
                self.send_json(404, {"error": "not_found"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == "/v1/chat/completions":
            if not _authenticated_ai_broker(self.headers):
                self.send_json(403, {"error": "ai_broker_capability_required"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                body = json.loads(self.rfile.read(length) or b"{}")
                messages = body.get("messages") or []
                tools = body.get("tools") or []
                tool_choice = body.get("tool_choice")
                if not messages:
                    raise ValueError("messages_required")
                if tools:
                    effective_privacy = "normal"
                    result = _AI_BROKER.chat(
                        messages,
                        tools=tools,
                        tool_choice=tool_choice,
                        privacy=effective_privacy,
                        task_class="normal",
                    )
                    message = result["message"]
                    finish_reason = result["finish_reason"]
                else:
                    effective_privacy = "local-only"
                    prompt = "\n".join(
                        f"{str(item.get('role') or 'user').upper()}: {str(item.get('content') or '')}"
                        for item in messages if isinstance(item, dict)
                    ).strip()
                    if not prompt:
                        raise ValueError("messages_required")
                    result = _AI_BROKER.generate(prompt, privacy="local-only", task_class="normal")
                    message = {"role": "assistant", "content": result["text"]}
                    finish_reason = "stop"
                self.send_json(200, {
                    "id": "chatcmpl-" + uuid.uuid4().hex,
                    "object": "chat.completion",
                    "created": int(time.time()),
                    "model": result["model"],
                    "lifeos_provider": result["provider"],
                    "lifeos_privacy": effective_privacy,
                    "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
                })
            except Exception as exc:
                self.send_json(502, {"error": "ai_broker_failed", "detail": str(exc)[:500]})
            return
        if path.startswith("/jobs/") and path.endswith("/retry"):
            job_id = path.split("/")[2]
            try:
                old = load(job_id)
            except Exception:
                self.send_json(404, {"error": "not_found"})
                return
            job = create_job(
                old["request"], async_mode=True, retry_of=job_id,
                dispatch_builder=old.get("dispatch_builder"),
                privacy_domain=old.get("privacy_domain"),
                canonical_assertions=old.get("canonical_assertions"),
            )
            self.send_json(409 if job.get("status") == "BUSY" else 202, job)
            return
        if path != "/jobs":
            self.send_json(404, {"error": "not_found"})
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            request = str(body.get("request", "")).strip()
        except Exception:
            body = {}
            request = ""
        if not request:
            self.send_json(400, {"error": "request_required"})
            return
        dispatch_builder, dispatch_error = authenticated_dispatch_route(self.headers, body)
        if dispatch_error:
            code = 400 if dispatch_error == "invalid_dispatch_builder" else 403
            self.send_json(code, {"error": dispatch_error})
            return
        async_mode = urllib.parse.parse_qs(parsed.query).get("async", ["0"])[0].lower() in ("1", "true", "yes")
        retired_fields = sorted(RETIRED_CONTINUATION_FIELDS.intersection(body))
        if retired_fields:
            self.send_json(410, {
                "error": "governor_continuation_retired",
                "canonical_owner": "openhands",
                "fields": retired_fields,
            })
            return
        job_options = {
            "deploy_engineer_runtime": bool(body.get("deploy_engineer_runtime", False)),
            "dispatch_builder": dispatch_builder,
            "privacy_domain": body.get("privacy_domain"),
            "canonical_assertions": body.get("canonical_assertions"),
        }
        try:
            job = create_job(request, async_mode=async_mode, **job_options)
        except ValueError as exc:
            self.send_json(400, {"error": str(exc)})
            return
        if job.get("status") == "BUSY":
            self.send_json(409, job)
        else:
            self.send_json(202 if async_mode else 200, job)

    def log_message(self, fmt, *args):
        print("agent", self.address_string(), fmt % args, flush=True)


if __name__ == "__main__":
    print(f"lifeos-autonomous-agent listening on 0.0.0.0:{PORT}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
