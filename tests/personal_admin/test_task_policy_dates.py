"""Insurance renewal dates must come from verified policy evidence."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "homelab/live/home/joshan/automation"))
import lifeos_task_reconciler as reconciler


def test_policy_reference_number_is_extracted_as_stable_identity():
    refs = reconciler.case_reference_ids({
        "subject": "Policy number: AB-12345678",
        "body": "",
    })
    assert refs == {"AB12345678"}


def test_policy_renewal_date_requires_explicit_label():
    assert reconciler.policy_renewal_dates(
        "Policy renewal date: 22 March 2027. Document issued 10 October 2026."
    ) == {"2027-03-22"}
    assert reconciler.policy_renewal_dates(
        "Document issued 10 October 2026. Insurance premium: £600."
    ) == set()


def test_verified_policy_document_overrides_email_derived_overdue_date(monkeypatch):
    task = {
        "title": "Car insurance renewal reminder",
        "topic": "car insurance",
        "due_date": "2026-10-13",
        "email_message_id": "<renewal@example.test>",
        "source_message_ids": ["<renewal@example.test>"],
        "case_reference_ids": ["POLICY123456"],
        "paperless_evidence": [{"document_id": 81, "title": "Motor policy schedule"}],
    }
    monkeypatch.setattr(reconciler, "_paperless_document", lambda _id: {
        "id": 81,
        "title": "Motor policy schedule",
        "content": (
            "Message-ID: <renewal@example.test>\n"
            "Policy renewal date: 22 March 2027."
        ),
    })

    assert reconciler.reconcile_insurance_policy_due_date(task)
    assert task["due_date"] == "2027-03-22"
    assert task["due_date_source"] == "paperless_policy"


def test_missing_or_ambiguous_policy_date_clears_unverified_email_date(monkeypatch):
    task = {
        "title": "Car insurance renewal reminder",
        "topic": "car insurance",
        "due_date": "2026-10-13",
        "email_message_id": "<renewal@example.test>",
        "source_message_ids": ["<renewal@example.test>"],
        "paperless_evidence": [{"document_id": 82, "title": "Policy schedule"}],
    }
    monkeypatch.setattr(reconciler, "_paperless_document", lambda _id: {
        "id": 82,
        "title": "Policy schedule",
        "content": (
            "Message-ID: <renewal@example.test>\n"
            "Renewal date: 22 March 2027. Policy expires on 25 March 2027."
        ),
    })

    assert reconciler.reconcile_insurance_policy_due_date(task)
    assert task["due_date"] is None
    assert task["due_date_source"] == "unverified_insurance_policy"
