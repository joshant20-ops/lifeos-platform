"""Stale one-source tasks can be removed from verified email OCR."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "homelab/live/home/joshan/automation"))
import lifeos_task_reconciler as reconciler


def test_uid_search_uses_uid_syntax_without_charset_placeholder():
    from unittest.mock import Mock

    client = Mock()
    client.uid.return_value = ("OK", [b"77"])
    query = '"<gemini@example.test>"'
    assert reconciler._uid_search(client, "HEADER", "Message-ID", query) == ("OK", [b"77"])
    client.uid.assert_called_once_with("search", "HEADER", "Message-ID", query)


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
            "source_message_ids": [source_id, "<legacy-provenance@example.test>"],
            "timeline_events": [{"message_id": source_id}],
        }
    }
    assert reconciler.task_source_message_ids(tasks["legacy-gemini-task"]) == [source_id]
    assert reconciler.task_cleanup_source_message_id(tasks["legacy-gemini-task"]) == source_id
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
                assert args and args[0] is not None, "UID SEARCH must not include a charset placeholder"
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



def test_exact_source_lookup_uses_bounded_date_fallback_when_id_search_misses(monkeypatch):
    message_id = "<dated-gemini@example.test>"
    crlf = bytes([13, 10])
    raw = crlf.join([
        b"From: Google AI Studio <ai-studio@example.test>",
        b"Subject: Gemini deprecation",
        b"Date: Sat, 10 Oct 2026 15:05:15 +0000",
        b"Message-ID: <dated-gemini@example.test>",
        b"Content-Type: text/plain; charset=utf-8",
        b"",
        b"No action required.",
    ])

    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            self.searches = 0
        def login(self, *_args):
            return "OK", []
        def select(self, *_args, **_kwargs):
            return "OK", []
        def uid(self, command, *args):
            if command == "search":
                assert args and args[0] is not None, "UID SEARCH must not include a charset placeholder"
                self.searches += 1
                if self.searches < 3:
                    return "OK", [b""]
                assert args[0] == "SINCE"
                assert args[2] == "BEFORE"
                return "OK", [b"77"]
            if command == "fetch":
                return "OK", [(b"77 (RFC822)", raw)]
            raise AssertionError(command)
        def logout(self):
            return "BYE", []

    monkeypatch.setattr(reconciler.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(reconciler, "secret", lambda *_args: "credential")
    task = {
        "email_message_id": message_id,
        "source_message_ids": [message_id],
        "timeline_events": [{
            "message_id": message_id,
            "date": "Sat, 10 Oct 2026 15:05:15 +0000",
        }],
    }
    found = reconciler.fetch_existing_task_source_emails([task])
    assert set(found) == {message_id}
    assert reconciler.has_explicit_no_action_required(found[message_id])
    assert reconciler._SOURCE_LOOKUP_DIAGNOSTICS["tasks_seen"] == 1
    assert reconciler._SOURCE_LOOKUP_DIAGNOSTICS["tasks_with_source_ids"] == 1
    assert reconciler._SOURCE_LOOKUP_DIAGNOSTICS["timeline_fallback_tasks"] == 1


def test_stale_primary_no_action_email_can_remove_legacy_extra_source_ids():
    message_id = "<gemini@example.test>"
    tasks = {
        "legacy-gemini-task": {
            "id": "legacy-gemini-task",
            "email_message_id": message_id,
            "source_message_ids": [message_id, "<legacy-provenance@example.test>"],
            "timeline_events": [{"message_id": message_id}],
        }
    }
    assert reconciler.discard_single_source_no_action_task(
        tasks,
        {"message_id": message_id},
    )
    assert tasks == {}


def test_stale_cleanup_keeps_task_with_another_timeline_event():
    message_id = "<gemini@example.test>"
    other_id = "<actionable-followup@example.test>"
    tasks = {
        "legacy-gemini-task": {
            "id": "legacy-gemini-task",
            "email_message_id": message_id,
            "source_message_ids": [message_id, other_id],
            "timeline_events": [
                {"message_id": message_id},
                {"message_id": other_id},
            ],
        }
    }
    assert not reconciler.discard_single_source_no_action_task(
        tasks,
        {"message_id": message_id},
    )
    assert "legacy-gemini-task" in tasks


def test_stale_source_lookup_inspects_primary_when_legacy_ids_are_extra(monkeypatch):
    import email

    message_id = "<gemini@example.test>"
    crlf = bytes([13, 10])
    raw = crlf.join([
        b"From: Google AI Studio <ai-studio@example.test>",
        b"Subject: Gemini deprecation",
        b"Date: Sat, 10 Oct 2026 15:05:15 +0000",
        b"Message-ID: <gemini@example.test>",
        b"Content-Type: text/plain; charset=utf-8",
        b"",
        b"No action required.",
    ])

    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            self.searches = 0
        def login(self, *_args):
            return "OK", []
        def select(self, *_args, **_kwargs):
            return "OK", []
        def uid(self, command, *args):
            if command == "search":
                assert args and args[0] is not None, "UID SEARCH must not include a charset placeholder"
                self.searches += 1
                if self.searches < 3:
                    return "OK", [b""]
                return "OK", [b"77"]
            if command == "fetch":
                return "OK", [(b"77 (RFC822)", raw)]
            raise AssertionError(command)
        def logout(self):
            return "BYE", []

    monkeypatch.setattr(reconciler.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(reconciler, "secret", lambda *_args: "credential")
    task = {
        "email_message_id": message_id,
        "source_message_ids": [message_id, "<legacy-provenance@example.test>"],
        "timeline_events": [{
            "message_id": message_id,
            "date": "Sat, 10 Oct 2026 15:05:15 +0000",
        }],
    }
    found = reconciler.fetch_existing_task_source_emails([task])
    assert set(found) == {message_id}
    assert reconciler.has_explicit_no_action_required(found[message_id])


def test_stale_source_lookup_uses_sole_timeline_id_without_primary(monkeypatch):
    message_id = "<gemini@example.test>"
    crlf = bytes([13, 10])
    raw = crlf.join([
        b"From: Google AI Studio <ai-studio@example.test>",
        b"Subject: Gemini deprecation",
        b"Date: Sat, 10 Oct 2026 15:05:15 +0000",
        b"Message-ID: <gemini@example.test>",
        b"Content-Type: text/plain; charset=utf-8",
        b"",
        b"No action required.",
    ])

    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            self.searches = 0
        def login(self, *_args):
            return "OK", []
        def select(self, *_args, **_kwargs):
            return "OK", []
        def uid(self, command, *args):
            if command == "search":
                assert args and args[0] is not None, "UID SEARCH must not include a charset placeholder"
                self.searches += 1
                if self.searches < 3:
                    return "OK", [b""]
                return "OK", [b"77"]
            if command == "fetch":
                return "OK", [(b"77 (RFC822)", raw)]
            raise AssertionError(command)
        def logout(self):
            return "BYE", []

    monkeypatch.setattr(reconciler.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(reconciler, "secret", lambda *_args: "credential")
    task = {
        "source_message_ids": [message_id, "<legacy-provenance@example.test>"],
        "timeline_events": [{
            "message_id": message_id,
            "date": "Sat, 10 Oct 2026 15:05:15 +0000",
        }],
    }
    assert reconciler.task_cleanup_source_message_id(task) == message_id
    found = reconciler.fetch_existing_task_source_emails([task])
    assert set(found) == {message_id}
    assert reconciler.has_explicit_no_action_required(found[message_id])
    tasks = {"legacy-gemini-task": task}
    assert reconciler.discard_single_source_no_action_task(tasks, found[message_id])
    assert tasks == {}


def test_stale_source_lookup_uses_fresh_authenticated_inbox_session(monkeypatch):
    message_id = "<gemini@example.test>"
    crlf = bytes([13, 10])
    raw = crlf.join([
        b"From: Google AI Studio <ai-studio@example.test>",
        b"Subject: Gemini 3.5 Flash deprecation",
        b"Date: Sat, 10 Oct 2026 15:05:15 +0000",
        b"Message-ID: <gemini@example.test>",
        b"Content-Type: text/plain; charset=utf-8",
        b"",
        b"No action required.",
    ])
    sessions = []

    class FakeIMAP:
        def __init__(self, *_args, **_kwargs):
            self.logged_in = False
            self.selected = []
            sessions.append(self)
        def login(self, *_args):
            self.logged_in = True
            return "OK", []
        def select(self, mailbox, readonly=True):
            assert self.logged_in
            self.selected.append(mailbox)
            return ("OK", []) if mailbox == "INBOX" else ("NO", [])
        def uid(self, command, *args):
            assert self.logged_in and self.selected == ["INBOX"]
            if command == "search":
                assert args == ("HEADER", "Message-ID", '"<gemini@example.test>"')
                return "OK", [b"77"]
            if command == "fetch":
                return "OK", [(b"77 (RFC822)", raw)]
            raise AssertionError(command)
        def logout(self):
            self.logged_in = False
            return "BYE", []

    monkeypatch.setattr(reconciler.imaplib, "IMAP4_SSL", FakeIMAP)
    monkeypatch.setattr(reconciler, "secret", lambda *_args: "credential")
    found = reconciler.fetch_existing_task_source_emails(
        [{"email_message_id": message_id, "source_message_ids": [message_id]}]
    )
    assert len(sessions) == 1
    assert sessions[0].selected == ["INBOX"]
    assert not sessions[0].logged_in
    assert found[message_id]["message_id"] == message_id
    assert reconciler.has_explicit_no_action_required(found[message_id])
