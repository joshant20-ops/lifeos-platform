"""Thin JSON CLI adapter. Shadow proposals never publish or mutate LifeOS tasks."""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

CLI = Path("/opt/lifeos/emailops-shadow/bin/emailops-cli")
PROFILE = Path("/home/joshan/.local/share/lifeos/emailops-shadow")
POLICY = Path("/home/joshan/lifeos-platform/config/emailops-upstream.json")
MANIFEST = Path("/opt/lifeos/emailops-shadow/manifest.json")


class EmailOpsError(RuntimeError):
    """Only fixed error codes may leave the private processing boundary."""


def envelope(stdout, returncode=0):
    try:
        data = json.loads(stdout)
    except (ValueError, TypeError):
        # Some upstream sync diagnostics precede the final pretty JSON object.
        # Accept only a complete object at column zero ending at EOF; never
        # emit the ignored prefix or search arbitrary embedded mail JSON.
        start = stdout.rfind("\n{") if isinstance(stdout, str) else -1
        if start < 0:
            raise EmailOpsError("cli_invalid_json") from None
        try:
            data = json.loads(stdout[start + 1:])
        except (ValueError, TypeError):
            raise EmailOpsError("cli_invalid_json") from None
    if not isinstance(data, dict) or data.get("ok") is not True or returncode != 0:
        # Upstream errors can include subjects, addresses, and provider responses.
        reason = {2: "cli_invalid_input", 3: "cli_not_found", 4: "cli_auth", 5: "cli_network",
                  6: "cli_ai", 130: "cli_cancelled"}.get(returncode, "cli_failed")
        error = data.get("error")
        code = error.get("code") if isinstance(error, dict) else None
        if code in {"auth", "keyring", "database", "http", "sync", "io", "invalid_input", "not_found"}:
            reason = "cli_" + code
        if code == "invalid_input":
            params = error.get("params")
            detail = params.get("detail") if isinstance(params, dict) else None
            message = detail if isinstance(detail, str) else error.get("message")
            fixed = {
                "password file unavailable": "cli_password_file_unavailable",
                "password file must be a regular file": "cli_password_file_type",
                "password file must be private": "cli_password_file_permissions",
                "password file unreadable": "cli_password_file_unreadable",
                "password file has invalid length": "cli_password_file_length",
            }
            if isinstance(message, str):
                reason = fixed.get(message, reason)
                if "is not a valid email address." in message:
                    reason = "cli_account_address_invalid"
                elif message.startswith("An email address is required."):
                    reason = "cli_account_address_missing"
                elif message.startswith("Account ") and message.endswith(" is already connected"):
                    reason = "cli_account_already_connected"
        raise EmailOpsError(reason)
    if data.get("error") is not None or "data" not in data:
        raise EmailOpsError("cli_invalid_envelope")
    return data["data"]


def source_identity(source):
    if not isinstance(source, dict):
        raise EmailOpsError("source_identity_missing")
    message_id = source.get("messageId")
    if not isinstance(message_id, str) or not re.fullmatch(r"<[^<>\s\x00-\x1f]{1,298}>", message_id):
        raise EmailOpsError("source_identity_invalid")
    if not all(isinstance(source.get(k), str) and source[k] for k in ("id", "accountId", "threadId")):
        raise EmailOpsError("source_identity_missing")
    return message_id


def require_acceptance():
    """Activated only after corpus and user acceptance; no IMAP code lives here."""
    try:
        policy = json.loads(POLICY.read_text())
        manifest = json.loads(MANIFEST.read_text())
    except (OSError, ValueError):
        raise EmailOpsError("emailops_acceptance_required") from None
    acceptance = policy.get("acceptance") or {}
    if (policy.get("mode") != "active" or policy.get("mailbox_writes") is not True
            or acceptance.get("corpus") is not True or acceptance.get("user") is not True
            or manifest.get("source_commit") != policy.get("commit")
            or manifest.get("patch_sha256") != policy.get("patch_sha256")):
        raise EmailOpsError("emailops_acceptance_required")
    return policy


def confirm_junk_native(message_ids, runner=subprocess.run):
    require_acceptance()
    client = ShadowClient(runner=runner)
    accounts = client.accounts()
    if len(accounts) != 1:
        raise EmailOpsError("isolated_account_mismatch")
    client.account = accounts[0]["id"]
    # Refresh provider IDs after a previous partial move/restart before resolving
    # the confirmed source set. This download does not mutate provider mail.
    client._call("sync", timeout=300)
    rows = client.emails(200) + client._call("emails", "--mailbox", "spam", "--limit", "200")
    selected = []
    # Resolve every source before the first mailbox mutation. A fuzzy subject or
    # sender match must never select a message for a destructive action.
    for message_id in sorted(set(message_ids)):
        matches = {r["id"]: r for r in rows if r.get("messageId") == message_id
                   and r.get("accountId") == client.account}
        if len(matches) != 1:
            raise EmailOpsError("source_lookup_not_unique")
        selected.append(next(iter(matches)))
    if not 1 <= len(selected) <= 20:
        raise EmailOpsError("source_email_set_invalid")
    for email_id in selected:
        argv = [str(CLI), "--json", "--quiet", "--data-dir", str(PROFILE / "data"),
                "--account", client.account, "report-junk", email_id, "--confirm"]
        try:
            result = runner(argv, capture_output=True, text=True, timeout=180, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise EmailOpsError("emailops_junk_unverified") from None
        proof = envelope(result.stdout, result.returncode)
        if not isinstance(proof, dict) or proof.get("filed") is not True or proof.get("verified") is not True:
            raise EmailOpsError("emailops_junk_unverified")


def confirm_junk(message_ids, runner=subprocess.run):
    """The root reconciler delegates mailbox work to the isolated user service."""
    import pwd
    require_acceptance()
    request_id = os.urandom(16).hex()
    request = PROFILE / "junk-request.json"
    write_private_json(request, {
        "schema": "lifeos_emailops_junk_v1", "request_id": request_id,
        "source_message_ids": sorted(set(message_ids)),
    })
    owner = pwd.getpwnam("joshan")
    os.chown(request, owner.pw_uid, owner.pw_gid)
    try:
        result = runner(["/usr/bin/systemctl", "start", "lifeos-emailops-junk.service"],
                        capture_output=True, text=True, timeout=600, check=False)
        proof = json.loads((PROFILE / "junk-result.json").read_text())
    except (OSError, ValueError, subprocess.TimeoutExpired):
        raise EmailOpsError("emailops_junk_unverified") from None
    if result.returncode or proof.get("request_id") != request_id or proof.get("verified") is not True:
        raise EmailOpsError("emailops_junk_unverified")


def normalize_analysis(data):
    """Preserve source identity and reported dates; never infer completion."""
    if not isinstance(data, dict) or data.get("schema") != "emailops_analysis_v1":
        raise EmailOpsError("analysis_schema_invalid")
    source = data.get("source")
    message_id = source_identity(source)
    extraction = data.get("extraction")
    if not isinstance(extraction, dict) or not isinstance(extraction.get("tasks"), list):
        raise EmailOpsError("analysis_payload_invalid")
    if len(extraction["tasks"]) > 20:
        raise EmailOpsError("analysis_task_limit")
    proposals = []
    for task in extraction["tasks"]:
        if not isinstance(task, dict) or not isinstance(task.get("title"), str) or not task["title"].strip():
            raise EmailOpsError("analysis_task_invalid")
        due = task.get("due_at_iso", task.get("dueAtIso"))
        if due is not None:
            try:
                # Dates remain sourced values. A malformed model date is held.
                due = datetime.fromisoformat(due.replace("Z", "+00:00")).date().isoformat()
            except (ValueError, TypeError, AttributeError):
                raise EmailOpsError("analysis_due_date_invalid") from None
        priority = str(task.get("priority") or "normal").lower()
        proposals.append({
            "title": task["title"].strip()[:300],
            "detail": str(task.get("detail") or "")[:4000],
            "severity": {"urgent": "high", "high": "high", "low": "low"}.get(priority, "normal"),
            "due_date": due,
            "source_message_ids": [message_id],
        })
    return {
        "schema": "lifeos_emailops_shadow_v1",
        "mode": "shadow",
        "source_message_ids": [message_id],
        "emailops_email_id": source["id"],
        "emailops_account_id": source["accountId"],
        "emailops_thread_id": source["threadId"],
        "summary": extraction.get("thread_summary", extraction.get("threadSummary")),
        "proposals": proposals,
        # The pinned upstream payload has no lifecycle/completion field.
        "lifecycle": "UNKNOWN",
        "promotion_ready": False,
    }


class ShadowClient:
    """Only a fixed set of non-mutating mailbox operations are exposed here."""

    def __init__(self, account=None, runner=subprocess.run):
        self.account = account
        self.runner = runner

    def _call(self, command, *args, timeout=180):
        if command not in {"doctor", "accounts", "emails", "analyze", "sync", "config"}:
            raise EmailOpsError("shadow_command_blocked")
        if command == "config" and tuple(args[:1]) != ("local-ai",):
            raise EmailOpsError("shadow_command_blocked")
        argv = [str(CLI), "--json", "--quiet", "--data-dir", str(PROFILE / "data")]
        if self.account:
            argv += ["--account", self.account]
        argv += [command, *map(str, args)]
        try:
            result = self.runner(argv, capture_output=True, text=True, timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise EmailOpsError("cli_unavailable") from None
        return envelope(result.stdout, result.returncode)

    def doctor(self):
        return self._call("doctor")

    def accounts(self):
        return self._call("accounts")

    def emails(self, limit=200):
        if not isinstance(limit, int) or not 1 <= limit <= 200:
            raise EmailOpsError("sample_limit_invalid")
        return self._call("emails", "--limit", limit)

    def analyze(self, email_id):
        return normalize_analysis(self._call("analyze", email_id))


def write_private_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
