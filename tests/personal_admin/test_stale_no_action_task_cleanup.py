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




def test_stale_cleanup_accepts_source_retained_only_in_timeline():
    source_id = "<gemini@example.test>"
    tasks = {
        "legacy-gemini-task": {
            "id": "legacy-gemini-task",
            "source_message_ids": [],
            "timeline_events": [{"message_id": source_id}],
        }
    }
    assert reconciler.task_source_message_ids(tasks["legacy-gemini-task"]) == [source_id]
    assert reconciler.discard_single_source_no_action_task(
        tasks,
        {"message_id": source_id},
    )
    assert tasks == {}


def test_exact_source_lookup_fetches_only_unprocessed_single_source_tasks(monkeypatch):
    import email

    message_id = "<gemini@example.test>"
    raw = (
        b"From: Google AI Studio <ai-studio@example.test>\\r\\n"
        b"Subject: Gemini 3.5 Flash deprecation\\r\\n"
        b"Date: Sat, 10 Oct 2026 15:05:15 +0000\\r\\n"
        b"Message-ID: <gemini@example.test>\\r\\n"
        b"Content-Type: text/plain; charset=utf-8\\r\\n\\r\\n"
        b"No action required."
    )

    class FakeIMAP:
        def __init__(self, *args, **kwargs):
            self.selected = []
        def login(self, *_args):
            return "OK", []
        def select(self, mailbox, readonly=True):
            self.selected.append(mailbox)
            return ("OK", []) if mailbox == "[Gmail]/All Mail" else ("NO", [])
        def uid(self, command, *args):
            if command == "search":
                return "OK", [b"77"]
            if command == "fetch":
                return "OK", [(b"77 (RFC822)", raw)]
            raise AssertionError(command)
        def logout(self):
            return "BYE", []

    monkeypatch.setattr(reconciler.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(reconciler, "secret", lambda *_args: "credential")
    tasks = [
        {"email_message_id": message_id, "source_message_ids": [message_id]},
        {"email_message_id": "<already@example.test>", "source_message_ids": ["<already@example.test>"]},
        {"email_message_id": "<multi@example.test>", "source_message_ids": ["<multi@example.test>", "<second@example.test>"]},
    ]
    found = reconciler.fetch_existing_task_source_emails(
        tasks,
        already_fetched={"<already@example.test>"},
    )
    assert set(found) == {message_id}
    assert found[message_id]["message_id"] == message_id
    assert reconciler.has_explicit_no_action_required(found[message_id])


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
