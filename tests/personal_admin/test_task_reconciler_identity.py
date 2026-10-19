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


def test_done_state_is_not_regressed_by_later_classification_noise():
    assert reconciler.effective_status({"status": "DONE"}, "OPEN") == "DONE"
    assert reconciler.effective_status({"status": "WAITING"}, "DONE") == "DONE"


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


def test_no_reference_similar_topic_messages_remain_separate():
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
            "body": "private body must not be published",
        },
    ])
    assert projected == [{"observed_at": 100, "title": "Claim update", "status": "WAITING"}]
    assert "message_id" not in str(projected)
    assert "private body" not in str(projected)
