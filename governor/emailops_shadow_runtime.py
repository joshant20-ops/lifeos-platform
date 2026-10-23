#!/usr/bin/env python3
"""Private Pi-only shadow sample. Only fixed codes and counters go to Actions."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from governor import ai_broker
from governor.emailops_adapter import EmailOpsError, PROFILE, ShadowClient, confirm_junk_native, write_private_json

STATE = Path("/opt/stacks/homeassistant/config/www/lifeos_tasks.json")
USER_STATE = Path("/opt/stacks/homeassistant/config/lifeos-pa-state/user_state.json")


def snapshots():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None for p in (STATE, USER_STATE)}


def local_ollama_host():
    from urllib.parse import urlsplit
    import ipaddress
    host = ai_broker.OLLAMA_URL.rsplit("/api/", 1)[0]
    parsed = urlsplit(host)
    name = parsed.hostname or ""
    local = name == "localhost" or name.endswith(".lan")
    try:
        local = local or ipaddress.ip_address(name).is_private
    except ValueError:
        pass
    if not local or parsed.scheme not in {"http", "https"} or parsed.username or parsed.password:
        raise EmailOpsError("local_ai_route_invalid")
    # ai.lan is the stable name of the gateway on this same Pi. Use its
    # loopback listener so upstream's HTTP transport guard stays intact.
    if (name == "ai.lan" and parsed.scheme == "http" and parsed.port == 18114
            and parsed.path in {"", "/"} and not parsed.query and not parsed.fragment):
        return "http://127.0.0.1:18114"
    return host


def unlock_keyring(credentials):
    password = (credentials / "emailops-keyring-password").read_text().rstrip("\r\n")
    result = subprocess.run(
        ["/usr/bin/gnome-keyring-daemon", "--unlock", "--components=secrets"],
        input=password, capture_output=True, text=True, timeout=30, check=False,
    )
    if result.returncode != 0:
        raise EmailOpsError("keyring_unlock_failed")


def add_imap_account(client, address, credentials, sync_from):
    # Systemd may expose its protected credential with group-read permissions.
    # Keep EmailOps' private-file requirement: use an ephemeral service-owned
    # 0600 handoff in the private /run directory, then unlink on every outcome.
    runtime = Path(os.environ["XDG_RUNTIME_DIR"])
    info = runtime.lstat()
    if (runtime.is_symlink() or not runtime.is_dir() or info.st_uid != os.geteuid()
            or info.st_mode & 0o077):
        raise EmailOpsError("credential_handoff_directory_not_private")
    with (credentials / "gmail-imap-password").open("rb") as source:
        password = source.read(4097)
    if not password or len(password) > 4096:
        raise EmailOpsError("credential_handoff_length_invalid")
    with tempfile.NamedTemporaryFile(prefix="emailops-password-", dir=runtime) as handoff:
        handoff.write(password)
        handoff.flush()
        return client._call(
            "accounts", "add", "imap", "--host", "imap.gmail.com", "--email", address,
            "--smtp-host", "smtp.gmail.com", "--password-file", handoff.name,
            "--sync-from", sync_from,
        )


def main():
    stage = "runtime_preflight"
    try:
        if platform.node() != "Docker" or os.geteuid() == 0:
            raise EmailOpsError("wrong_runtime")
        PROFILE.mkdir(mode=0o700, parents=True, exist_ok=True)
        if PROFILE.is_symlink() or PROFILE.stat().st_mode & 0o077:
            raise EmailOpsError("profile_not_private")
        os.environ["XDG_DATA_HOME"] = str(PROFILE / "xdg")
        os.environ["XDG_CONFIG_HOME"] = str(PROFILE / "config")
        os.environ["OLLAMA_HOST"] = local_ollama_host()
        credentials = Path(os.environ["CREDENTIALS_DIRECTORY"])
        before = snapshots()
        stage = "keyring"
        unlock_keyring(credentials)
        if sys.argv[1:] == ["--confirm-junk"]:
            stage = "confirmed_junk"
            request = json.loads((PROFILE / "junk-request.json").read_text())
            if request.get("schema") != "lifeos_emailops_junk_v1":
                raise EmailOpsError("junk_request_invalid")
            confirm_junk_native(request["source_message_ids"])
            write_private_json(PROFILE / "junk-result.json", {
                "request_id": request["request_id"], "verified": True,
            })
            print("EMAILOPS_JUNK=VERIFIED")
            return 0
        if sys.argv[1:]:
            raise EmailOpsError("runtime_arguments_invalid")
        stage = "local_ai_configuration"
        client = ShadowClient()
        client._call("config", "local-ai", "--provider", "ollama", "--model", ai_broker.OLLAMA_MODEL)
        stage = "account_bootstrap"
        address = (credentials / "gmail-imap-user").read_text().strip()
        stage = "account_list"
        accounts = client.accounts()
        matches = [a for a in accounts if a.get("email", "").casefold() == address.casefold()]
        if not matches:
            stage = "account_add"
            sync_from = (datetime.now(timezone.utc) - timedelta(days=30)).date().isoformat()
            added = add_imap_account(client, address, credentials, sync_from)
            matches = [added]
        if len(matches) != 1 or matches[0].get("provider") != "imap":
            raise EmailOpsError("isolated_account_mismatch")
        client.account = matches[0]["id"]
        stage = "doctor"
        doctor = client.doctor()
        if doctor.get("ok") is not True or doctor.get("provider") != "ollama":
            raise EmailOpsError("doctor_not_ready")
        stage = "bounded_sync"
        synced = client._call("sync", timeout=300)
        if synced != {"synced": client.account}:
            raise EmailOpsError("sync_account_proof_invalid")
        rows = client.emails(200)
        current = json.loads(STATE.read_text())
        known = {}
        for task in current.get("tasks", []):
            ids = set(task.get("source_message_ids") or [])
            if task.get("email_message_id"):
                ids.add(task["email_message_id"])
            for value in ids:
                known.setdefault(value, []).append(task["id"])
        # Prefer exact source matches to current tasks, then sample other mail.
        rows.sort(key=lambda row: row.get("messageId") not in known)
        results, seen = [], set()
        stage = "shadow_analysis"
        started = time.monotonic()
        for row in rows:
            source = row.get("messageId")
            if not source or source in seen or row.get("mailbox") in {"spam", "trash"}:
                continue
            seen.add(source)
            result = client.analyze(row["id"])
            if result["source_message_ids"] != [source]:
                raise EmailOpsError("analysis_source_mismatch")
            result["matched_task_ids"] = known.get(source, [])
            results.append(result)
            if len(results) == 3:
                break
        if not results:
            raise EmailOpsError("no_shadow_sample")
        stage = "authoritative_state_check"
        if snapshots() != before:
            raise EmailOpsError("authoritative_state_changed_during_shadow")
        write_private_json(PROFILE / "shadow-report.json", {
            "schema": "lifeos_emailops_comparison_v1", "mode": "shadow", "generated_at": int(time.time()),
            "results": results, "elapsed_seconds": round(time.monotonic() - started, 2),
            "acceptance": "PENDING_LIFECYCLE_CORPUS_AND_USER_REVIEW",
        })
        print("EMAILOPS_MAILBOX_WRITES=DISABLED")
        print("EMAILOPS_SAMPLED=" + str(len(results)))
        print("EMAILOPS_EXACT_SOURCE_MATCHES=" + str(sum(bool(x["matched_task_ids"]) for x in results)))
        print("EMAILOPS_PROPOSALS=" + str(sum(len(x["proposals"]) for x in results)))
        print("EMAILOPS_AUTHORITATIVE_STATE=UNCHANGED")
        print("EMAILOPS_PROMOTION=HELD_LIFECYCLE_CORPUS_AND_USER_REVIEW")
        print("EMAILOPS_SHADOW=PASS")
        return 0
    except Exception as error:
        # Errors from the native CLI/keyring/model may contain private content.
        reason = str(error) if isinstance(error, EmailOpsError) else type(error).__name__.lower()
        print("EMAILOPS_SHADOW=FAIL")
        print("EMAILOPS_STAGE=" + stage)
        print("EMAILOPS_REASON=" + reason)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
