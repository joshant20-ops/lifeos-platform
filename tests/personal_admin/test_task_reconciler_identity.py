"""Deterministic identity and progression checks for the PA task read model."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "homelab/live/home/joshan/automation"))
import lifeos_task_reconciler as reconciler


def decision(topic, status="OPEN", counterparty="Acme"):
    return {
        "actionable": True, "title": topic, "status": status,
        "counterparty": counterparty, "topic": topic,
    }


def test_same_counterparty_separate_threads_keep_separate_identity():
    a = {"message_id": "<request-a@example.test>", "source_ref": "<request-a@example.test>"}
    b = {"message_id": "<request-b@example.test>", "source_ref": "<request-b@example.test>"}
    first = reconciler.resolve_task_id(decision("renewal"), a, {})
    second = reconciler.resolve_task_id(decision("renewal"), b, {})
    assert first != second


def test_reply_reference_reuses_existing_obligation_when_topic_text_changes():
    original = {"message_id": "<request@example.test>", "source_ref": "<request@example.test>"}
    first = decision("renewal")
    task_id = reconciler.resolve_task_id(first, original, {})
    tasks = {
        task_id: {
            "id": task_id,
            "identity_semantic": reconciler.key(first),
            "thread_root_id": original["message_id"],
            "source_message_ids": [original["message_id"]],
        }
    }
    reply = {
        "message_id": "<progress@example.test>",
        "in_reply_to": original["message_id"],
        "references": original["message_id"],
        "source_ref": "<progress@example.test>",
    }
    assert reconciler.resolve_task_id(decision("policy documents", "WAITING"), reply, tasks) == task_id


def test_replay_and_legacy_migration_are_idempotent():
    message = {"message_id": "<same@example.test>", "source_ref": "<same@example.test>"}
    item = decision("payment")
    task_id = reconciler.resolve_task_id(item, message, {})
    assert reconciler.resolve_task_id(item, message, {}) == task_id
    legacy={reconciler.key(item): {"id": reconciler.key(item),"email_message_id":message["message_id"]}}
    assert reconciler.resolve_task_id(item, message, legacy) == reconciler.key(item)
    unrelated={"message_id":"<other@example.test>","source_ref":"<other@example.test>"}
    assert reconciler.resolve_task_id(item, unrelated, legacy) != reconciler.key(item)


def test_order_and_tracking_references_are_normalized_across_company_emails():
    order=reconciler.case_reference_ids({"subject":"Order number: ORD-123456"})
    courier=reconciler.case_reference_ids({"subject":"Your parcel tracking number is ORD123456"})
    assert order=={"ORD123456"}
    assert courier==order

    order_message={"message_id":"<order@shop.test>","subject":"Order number ORD-123456"}
    delivery_message={"message_id":"<delivery@courier.test>","subject":"Tracking number ORD123456"}
    first=decision("purchase order",counterparty="Example Shop")
    second=decision("delivery update",status="WAITING",counterparty="Example Courier")
    task_id=reconciler.resolve_task_id(first,order_message,{})
    existing={task_id:{
        "id":task_id,"identity_semantic":reconciler.key(first),
        "thread_root_id":order_message["message_id"],
        "counterparty":"Example Shop","topic":"purchase order",
        "case_reference_ids":sorted(order),"source_message_ids":[order_message["message_id"]],
    }}
    assert reconciler.resolve_task_id(second,delivery_message,existing)==task_id


def test_done_state_is_not_regressed_by_later_classification_noise():
    assert reconciler.effective_status({"status": "DONE"}, "OPEN") == "DONE"
    assert reconciler.effective_status({"status": "WAITING"}, "DONE") == "DONE"


def test_paperless_candidates_require_exact_task_source_message_id():
    loaded=[]
    documents={
        11:{"id":11,"title":"Interview confirmation","content":"Subject: Interview Confirmation\nMessage-ID: <interview@example.test>"},
        12:{"id":12,"title":"Gemini update","content":"Subject: Welcome to Gemini\nMessage-ID: <gemini@example.test>"},
    }
    result=reconciler.verified_message_documents(
        [
            {"document_id":11,"title":"Interview confirmation"},
            {"document_id":12,"title":"Gemini update"},
            {"document_id":12,"title":"duplicate candidate"},
        ],
        ["<gemini@example.test>"],
        [],
        lambda document_id:(loaded.append(document_id) or documents.get(document_id)),
    )
    assert result==[{
        "document_id":12,"title":"Gemini update","created":"",
    }]
    assert loaded==[11,12]


def test_paperless_search_results_without_source_identity_are_not_links():
    result=reconciler.verified_message_documents(
        [{"document_id":21,"title":"Unrelated email with matching keywords"}],
        ["<task@example.test>"],
        [],
        lambda _document_id:{"title":"Unrelated email with matching keywords","content":"Subject: Interview confirmation"},
    )
    assert result==[]


def test_saved_document_candidates_are_reverified_after_email_was_already_processed(monkeypatch,tmp_path):
    import json

    monkeypatch.setattr(reconciler,"STATE",tmp_path/"tasks.json")
    reconciler.STATE.write_text(json.dumps({"tasks":[{
        "id":"gemini-migration-123456",
        "email_message_id":"<migration@example.test>",
        "source_message_ids":["<migration@example.test>"],
        "paperless_evidence":[
            {"document_id":41,"title":"Migration email"},
            {"document_id":42,"title":"Unrelated email"},
        ],
    }]}))
    documents={
        41:{"id":41,"title":"Migration email","content":"Message-ID: <migration@example.test>"},
        42:{"id":42,"title":"Unrelated email","content":"Message-ID: <other@example.test>"},
    }
    monkeypatch.setattr(reconciler,"_paperless_document",lambda document_id:documents.get(document_id))

    task=reconciler.load_previous()["gemini-migration-123456"]
    verified=reconciler.reverify_saved_task_paperless_evidence(task)

    assert [item["document_id"] for item in verified]==[41]


def test_cross_company_paperless_document_links_on_shared_order_reference():
    result=reconciler.verified_message_documents(
        [
            {"document_id":31,"title":"Courier delivery update"},
            {"document_id":32,"title":"Unrelated order email"},
        ],
        ["<shop-order@example.test>"],
        ["ORD123456"],
        lambda document_id:{
            31:{"title":"Courier delivery update","content":"Tracking number: ORD-123456. Sent by Example Courier."},
            32:{"title":"Unrelated order email","content":"Tracking details unavailable."},
        }.get(document_id),
    )
    assert result==[{"document_id":31,"title":"Courier delivery update","created":""}]


def test_out_of_order_observation_does_not_replace_newer_task_state():
    existing = {"observed_at": 200}
    assert not reconciler.observation_is_newer(existing, 100)
    assert reconciler.observation_is_newer(existing, 200)
    assert reconciler.observation_is_newer(existing, 300)


def test_attention_projection_uses_severity_and_due_urgency_without_source_content():
    from datetime import date
    now=1736899200
    attention=reconciler.derive_attention([
        {"id":"late-high","title":"Synthetic renewal","status":"OPEN","severity":"high","due_date":"2025-01-14","observed_at":now-20*86400,"source_message_ids":["<synthetic@example.test>"]},
        {"id":"waiting","title":"Synthetic reply","status":"WAITING","severity":"normal","observed_at":now},
        {"id":"done","title":"Synthetic done","status":"DONE","severity":"low","observed_at":now},
    ],now_ts=now,today=date(2025,1,15))
    assert attention["schema"]=="lifeos_attention_projection_v1"
    assert attention["needs_me"][0]["id"]=="late-high"
    assert attention["needs_me"][0]["priority_score"]==15
    assert attention["counts"]["overdue"]==1
    assert attention["counts"]["waiting_on_others"]==1
    assert attention["counts"]["recently_completed"]==1
    assert "Synthetic renewal" not in str(attention["counts"])

def test_briefing_is_bounded_and_uses_only_structured_projection():
    attention=reconciler.derive_attention([
        {"id":str(i),"title":"Synthetic task "+str(i),"status":"OPEN","due_date":"2025-01-16","severity":"normal","observed_at":1736899200}
        for i in range(8)
    ],now_ts=1736899200)
    briefing=reconciler.daily_briefing(attention)
    assert briefing["source"]=="lifeos_tasks_v3"
    assert briefing["confidence"]=="structured_state_only"
    assert len(briefing["items"])==5
    assert briefing["summary"].startswith("Needs you: 8;")


def test_exact_case_reference_groups_cross_thread_messages_and_preserves_timeline():
    original = {
        "message_id": "<case-open@example.test>",
        "source_ref": "<case-open@example.test>",
        "subject": "Case reference: UK-HB-42/AB12",
        "date": "Mon, 19 Oct 2026 09:00:00 +0100",
    }
    update = {
        "message_id": "<case-update@example.test>",
        "source_ref": "<case-update@example.test>",
        "subject": "Reference # UK_HB_42-AB12",
        "date": "Mon, 19 Oct 2026 10:00:00 +0100",
    }
    first = decision("renewal request")
    second = decision("documents received")
    task_id = reconciler.resolve_task_id(first, original, {})
    task = {
        "id": task_id,
        "identity_semantic": reconciler.key(first),
        "thread_root_id": original["message_id"],
        "counterparty": "Acme",
        "case_reference_ids": sorted(reconciler.case_reference_ids(original)),
        "source_message_ids": [],
        "timeline_events": [],
    }

    assert reconciler.case_reference_ids(original) == {"UKHB42AB12"}
    assert reconciler.case_reference_ids(update) == {"UKHB42AB12"}
    assert reconciler.resolve_task_id(second, update, {task_id: task}) == task_id

    reconciler.record_source_event(task, original, first, 100)
    reconciler.record_source_event(task, update, second, 200)
    reconciler.record_source_event(task, update, second, 200)
    assert task["source_message_ids"] == sorted([original["message_id"], update["message_id"]])
    assert [event["message_id"] for event in task["timeline_events"]] == [
        original["message_id"], update["message_id"],
    ]


def test_case_reference_does_not_group_different_matters_for_same_counterparty():
    first = {
        "message_id": "<case-a@example.test>",
        "subject": "Case reference: UK-10001",
    }
    second = {
        "message_id": "<case-b@example.test>",
        "subject": "Case reference: UK-20002",
    }
    item = decision("claim update")
    first_id = reconciler.resolve_task_id(item, first, {})
    existing = {
        first_id: {
            "id": first_id,
            "identity_semantic": reconciler.key(item),
            "thread_root_id": first["message_id"],
            "counterparty": "Acme",
            "case_reference_ids": sorted(reconciler.case_reference_ids(first)),
            "source_message_ids": [first["message_id"]],
        }
    }
    second_id = reconciler.resolve_task_id(item, second, existing)
    assert second_id != first_id


def test_same_counterparty_stable_topic_groups_across_threads():
    first = {
        "message_id": "<renewal-a@example.test>",
        "source_ref": "<renewal-a@example.test>",
    }
    second = {
        "message_id": "<renewal-b@example.test>",
        "source_ref": "<renewal-b@example.test>",
    }
    item = decision("renewal paperwork", counterparty="Acme")
    task_id = reconciler.resolve_task_id(item, first, {})
    existing = {
        task_id: {
            "id": task_id,
            "identity_semantic": reconciler.key(item),
            "thread_root_id": first["message_id"],
            "counterparty": "Acme",
            "topic": "renewal paperwork",
            "case_reference_ids": [],
            "source_message_ids": [first["message_id"]],
        }
    }
    assert reconciler.resolve_task_id(item, second, existing) == task_id


def test_ambiguous_or_conflicting_case_references_do_not_topic_merge():
    first_id = "acme-renewal-case-a"
    second_id = "acme-renewal-case-b"
    item = decision("renewal paperwork", counterparty="Acme")
    tasks = {
        first_id: {
            "id": first_id, "identity_semantic": reconciler.key(item),
            "thread_root_id": "<case-a@example.test>", "counterparty": "Acme",
            "topic": "renewal paperwork", "case_reference_ids": ["UK10001"],
            "source_message_ids": ["<case-a@example.test>"],
        },
        second_id: {
            "id": second_id, "identity_semantic": reconciler.key(item),
            "thread_root_id": "<case-b@example.test>", "counterparty": "Acme",
            "topic": "renewal paperwork", "case_reference_ids": ["UK20002"],
            "source_message_ids": ["<case-b@example.test>"],
        },
    }
    no_reference = {"message_id": "<new@example.test>", "source_ref": "<new@example.test>"}
    result = reconciler.resolve_task_id(item, no_reference, tasks)
    assert result not in {first_id, second_id}


def test_case_reference_groups_across_different_counterparty_labels():
    first = {"message_id": "<case-a@example.test>", "subject": "Case reference: UK-10001"}
    update = {"message_id": "<case-b@example.test>", "subject": "Reference # UK_10001"}
    first_decision = decision("claim update", counterparty="Acme Support")
    second_decision = decision("claim update", counterparty="Insurer Services")
    task_id = reconciler.resolve_task_id(first_decision, first, {})
    existing = {
        task_id: {
            "id": task_id,
            "identity_semantic": reconciler.key(first_decision),
            "thread_root_id": first["message_id"],
            "counterparty": "Acme Support",
            "topic": "claim update",
            "case_reference_ids": sorted(reconciler.case_reference_ids(first)),
            "source_message_ids": [first["message_id"]],
        }
    }
    assert reconciler.resolve_task_id(second_decision, update, existing) == task_id


def test_independent_roots_are_distinct_without_existing_matter_evidence():
    first = {"message_id": "<renewal-a@example.test>", "subject": "Renewal paperwork"}
    second = {"message_id": "<renewal-b@example.test>", "subject": "Renewal paperwork"}
    item = decision("renewal paperwork", counterparty="Acme")
    first_id = reconciler.resolve_task_id(item, first, {})
    second_id = reconciler.resolve_task_id(item, second, {})
    assert first_id != second_id


def test_attention_timeline_projection_exposes_only_bounded_summary_fields():
    from pathlib import Path
    import sys

    scripts = REPO / "homelab/live/opt/stacks/homeassistant/config/scripts"
    sys.path.insert(0, str(scripts))
    import lifeos_pa_task_attention_sensor as sensor

    projected = sensor.project_timeline_events([
        {
            "message_id": "<private@example.test>",
            "observed_at": 100,
            "title": "Claim update",
            "status": "WAITING",
            "event_kind": "information",
            "body": "private body must not be published",
        },
    ])
    assert projected == [{"observed_at": 100, "title": "Claim update", "status": "WAITING", "event_kind": "information"}]
    assert "message_id" not in str(projected)
    assert "private body" not in str(projected)





def test_failure_diagnostic_uses_only_fixed_stages_and_buckets():
    stages = {
        "startup", "state_load", "credential_load", "mailbox_connect",
        "mailbox_search", "mailbox_fetch", "classification", "paperless_lookup",
        "reconcile", "persist_publish", "complete",
    }
    for stage in stages:
        diagnostic = reconciler.safe_failure_diagnostic(
            RuntimeError("private message body and credential text"), stage
        )
        assert diagnostic == (
            f"TASK_RECONCILER_FAILURE_STAGE={stage}\n"
            "TASK_RECONCILER_FAILURE_BUCKET=OTHER"
        )
        assert "private message" not in diagnostic
        assert "credential text" not in diagnostic


def test_failure_exception_types_map_to_safe_buckets():
    import errno
    import http.client
    import imaplib
    import json
    import socket
    import ssl
    from urllib.error import HTTPError, URLError

    samples = [
        (ssl.SSLError("secret"), "TLS"),
        (imaplib.IMAP4.error("secret"), "IMAP"),
        (HTTPError("https://private.invalid", 500, "secret", {}, None), "HTTP"),
        (http.client.HTTPException("private protocol detail"), "HTTP"),
        (URLError("private host"), "NETWORK"),
        (json.JSONDecodeError("private content", "sensitive", 0), "JSON"),
        (socket.timeout("secret"), "NETWORK"),
        (socket.gaierror(-2, "private lookup"), "NETWORK"),
        (ConnectionError("private endpoint"), "NETWORK"),
        (OSError(errno.ECONNREFUSED, "private endpoint"), "NETWORK"),
        (PermissionError("private path"), "FILESYSTEM"),
        (OSError("private details"), "IO"),
        (ValueError("private email"), "DATA"),
    ]
    for exc, expected in samples:
        diagnostic = reconciler.safe_failure_diagnostic(exc, "mailbox_connect")
        assert diagnostic.endswith("TASK_RECONCILER_FAILURE_BUCKET=" + expected)
        assert str(exc) not in diagnostic


def test_failure_diagnostic_normalizes_unknown_stage_and_exception():
    class PrivateErrorName(Exception):
        pass

    diagnostic = reconciler.safe_failure_diagnostic(
        PrivateErrorName("secret"), "private-stage"
    )
    assert diagnostic == (
        "TASK_RECONCILER_FAILURE_STAGE=startup\n"
        "TASK_RECONCILER_FAILURE_BUCKET=OTHER"
    )
    assert "secret" not in diagnostic


def test_deploy_failure_diagnostics_filter_journal_to_fixed_markers():
    deploy = (REPO / "governor/scripts/deploy-pa-task-reconciler.sh").read_text()
    assert "grep -E '^TASK_RECONCILER_FAILURE_(STAGE|BUCKET)=[A-Za-z0-9_]+$'" in deploy
    assert "journalctl -u lifeos-task-reconciler.service -n 60 --no-pager;" not in deploy



def test_paperless_diagnostic_probe_is_bounded_body_free_and_allowlisted(tmp_path):
    import os
    import re
    import subprocess
    import sys

    deploy = (REPO / "governor/scripts/deploy-pa-task-reconciler.sh").read_text()
    function = re.search(r"(?ms)^paperless_runtime_diagnostic\(\) \{\n.*?^\}\n", deploy)
    assert function, "bounded Paperless diagnostic function missing"
    assert '/usr/bin/python3 "$REPO/governor/paperless_runtime_diagnostic.py"' in function.group(0)
    assert deploy.count("  paperless_runtime_diagnostic\n") == 2

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        "if [ \"$1\" = volume ] || [ \"$1\" = network ]; then printf '%s\\n' \"$3\"; "
        "elif [ \"$1\" = compose ]; then exit 0; "
        "elif [ \"$1\" = ps ]; then case \" $* \" in *' --quiet '*) printf '%s\\n' private-container-id;; "
        "*) printf '%s\\n' 'running|Up 4 minutes (healthy)';; esac; fi\n"
    )
    findmnt = bin_dir / "findmnt"
    findmnt.write_text("#!/bin/sh\nprintf '%s\\n' /mnt/synology\n")
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nprintf '%s\\n' 'PRIVATE RESPONSE BODY' >&2\nprintf '%s' 204\n")
    for command in (docker, findmnt, curl):
        command.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    helper = REPO / "governor/paperless_runtime_diagnostic.py"
    result = subprocess.run(
        [sys.executable, str(helper)],
        text=True, capture_output=True, timeout=15, env=env, check=True,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert fields["PAPERLESS_8010_PUBLISHED"] == "YES"
    assert fields["PAPERLESS_API_HTTP_STATUS"] == "204"
    assert fields["PAPERLESS_API_REACHABILITY"] == "REACHABLE"
    assert fields["PAPERLESS_REDIS_VOLUME"] == "PRESENT"
    assert fields["PAPERLESS_REVERSE_PROXY_NETWORK"] == "PRESENT"
    assert fields["PAPERLESS_CONTAINER_COUNT"] == "1"
    assert fields["PAPERLESS_CONTAINER_STATE_RUNNING"] == "1"
    assert fields["PAPERLESS_CONTAINER_HEALTH_HEALTHY"] == "1"
    assert all(key.startswith("PAPERLESS_") for key in fields)
    assert "private-container-id" not in result.stdout
    assert "PRIVATE RESPONSE BODY" not in result.stdout + result.stderr


def test_paperless_diagnostic_reports_fixed_unreachable_status(tmp_path):
    import os
    import subprocess
    import sys

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    docker = bin_dir / "docker"
    docker.write_text("#!/bin/sh\nexit 1\n")
    findmnt = bin_dir / "findmnt"
    findmnt.write_text("#!/bin/sh\nexit 1\n")
    curl = bin_dir / "curl"
    curl.write_text("#!/bin/sh\nprintf 'private transport detail' >&2\nexit 7\n")
    for command in (docker, findmnt, curl):
        command.chmod(0o755)
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"]}
    helper = REPO / "governor/paperless_runtime_diagnostic.py"
    result = subprocess.run(
        [sys.executable, str(helper)],
        text=True, capture_output=True, timeout=15, env=env, check=True,
    )
    fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
    assert fields["PAPERLESS_8010_PUBLISHED"] == "UNKNOWN"
    assert fields["PAPERLESS_API_HTTP_STATUS"] == "000"
    assert fields["PAPERLESS_API_REACHABILITY"] == "UNREACHABLE"
    assert fields["PAPERLESS_CONTAINER_SUMMARY"] == "UNKNOWN"
    assert "private transport detail" not in result.stdout + result.stderr


def test_informational_event_updates_only_an_existing_matter_and_is_idempotent(monkeypatch):
    task_id = "acme-claim-12345"
    task = {
        "id": task_id,
        "status": "WAITING",
        "due_date": "2026-11-01",
        "severity": "high",
        "counterparty": "Acme",
        "identity_semantic": "acme-claim",
        "user_comments": [{"text": "synthetic user note"}],
        "source_message_ids": ["<claim-open@example.test>"],
        "case_reference_ids": ["UKHB12345"],
        "timeline_events": [],
    }
    tasks = {task_id: task}
    message = {
        "message_id": "<claim-received@example.test>",
        "source_ref": "<claim-received@example.test>",
        "subject": "Claim reference UK-HB-12345 update",
    }
    decision = {
        "relevant": True,
        "actionable": False,
        "title": "Documents received",
        "status": "NONE",
        "counterparty": "Acme",
        "topic": "claim",
    }
    lookups=[]
    monkeypatch.setattr(
        reconciler,"paperless_linked_documents",
        lambda message_ids,reference_ids:(
            lookups.append((list(message_ids),list(reference_ids)))
            or ([{"document_id":42,"title":"Courier update","created":""}] if reference_ids else [])
        ),
    )

    resolved_id = reconciler.resolve_task_id(decision, message, tasks)
    assert resolved_id == task_id
    assert reconciler.reconcile_information_event(
        tasks, resolved_id, message, decision, 200
    )
    assert reconciler.reconcile_information_event(
        tasks, resolved_id, message, decision, 200
    )
    assert list(tasks) == [task_id]
    assert task["status"] == "WAITING"
    assert task["due_date"] == "2026-11-01"
    assert task["severity"] == "high"
    assert task["user_comments"] == [{"text": "synthetic user note"}]
    assert task["source_message_ids"] == [
        "<claim-open@example.test>",
        "<claim-received@example.test>",
    ]
    assert len(task["timeline_events"]) == 1
    assert task["timeline_events"][0]["event_kind"] == "information"
    assert len(lookups)==2
    assert "UKHB12345" in lookups[-1][1]
    assert task["paperless_evidence"]==[{"document_id":42,"title":"Courier update","created":""}]


def test_informational_event_without_a_matched_matter_creates_no_obligation():
    tasks = {}
    message = {"message_id": "<fyi@example.test>", "source_ref": "<fyi@example.test>"}
    decision = {
        "relevant": True,
        "actionable": False,
        "title": "General account update",
        "status": "NONE",
        "counterparty": "Acme",
        "topic": "general update",
    }
    task_id = reconciler.resolve_task_id(decision, message, tasks)
    assert not reconciler.reconcile_information_event(
        tasks, task_id, message, decision, 200
    )
    assert tasks == {}


def test_reconciler_classification_requests_native_local_json(monkeypatch):
    calls = []
    response = {
        "actionable": True,
        "title": "Synthetic renewal",
        "status": "OPEN",
        "due_date": None,
        "counterparty": "Acme",
        "topic": "renewal",
        "severity": "NORMAL",
        "evidence_query": "renewal",
        "reason": "synthetic test",
    }
    monkeypatch.setattr(
        reconciler.ai_broker,
        "_ollama",
        lambda prompt, model, **kwargs: calls.append(kwargs) or __import__("json").dumps(response),
    )
    result = reconciler.classify({"subject": "Synthetic renewal"})
    assert result["actionable"] is True
    assert calls == [{"response_format": reconciler.TASK_CLASSIFICATION_SCHEMA}]
    assert reconciler.TASK_CLASSIFICATION_SCHEMA["additionalProperties"] is False
    assert "actionable" in reconciler.TASK_CLASSIFICATION_SCHEMA["required"]


def test_inference_failure_category_redacts_upstream_body():
    error = reconciler.ai_broker.BrokerError(
        "provider HTTP 400: private model response and prompt data"
    )
    assert reconciler.safe_classification_error_category(error) == "UPSTREAM_HTTP_400"


def test_unknown_inference_failure_category_is_fixed():
    error = reconciler.ai_broker.BrokerError(
        "provider HTTP response contained sensitive details"
    )
    assert reconciler.safe_classification_error_category(error) == "BROKER_OTHER"


def test_pa_reconciler_deploy_fails_closed_on_nonzero_error_count():
    script = (REPO / "governor/scripts/deploy-pa-task-reconciler.sh").read_text()
    assert "TASK_CLASSIFICATION_ERROR_CATEGORIES=[A-Z0-9_,=]+" in script
    assert "TASK_RECONCILER_ERROR_GATE=FAIL" in script
    assert script.index("TASK_CLASSIFICATION_ERROR_CATEGORIES") < script.index(
        "TASK_RECONCILER_ERROR_GATE=FAIL"
    )
