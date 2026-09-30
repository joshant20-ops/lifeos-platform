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
