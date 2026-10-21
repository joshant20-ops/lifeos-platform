"""Stale one-source tasks can be removed from verified email OCR."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "homelab/live/home/joshan/automation"))
import lifeos_task_reconciler as reconciler


def test_verified_sole_source_email_with_no_action_notice_is_detected(monkeypatch):
    task = {
        "email_message_id": "<gemini@example.test>",
        "source_message_ids": ["<gemini@example.test>"],
        "paperless_evidence": [{"document_id": 91, "title": "Gemini notice"}],
    }
    monkeypatch.setattr(reconciler, "_paperless_document", lambda _id: {
        "id": 91,
        "title": "Gemini notice",
        "content": "Message-ID: <gemini@example.test>\nNo action required.",
    })
    assert reconciler.verified_source_email_requires_no_action(task) == "<gemini@example.test>"


def test_unrelated_or_multi_source_ocr_cannot_remove_task(monkeypatch):
    task = {
        "email_message_id": "<gemini@example.test>",
        "source_message_ids": ["<gemini@example.test>", "<followup@example.test>"],
        "paperless_evidence": [{"document_id": 92, "title": "Unrelated"}],
    }
    monkeypatch.setattr(reconciler, "_paperless_document", lambda _id: {
        "id": 92,
        "title": "Unrelated",
        "content": "Message-ID: <other@example.test>\nNo action required.",
    })
    assert reconciler.verified_source_email_requires_no_action(task) == ""
