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


def test_quote_offer_is_not_a_policy_renewal():
    quote={"subject":"Your car insurance renewal quote","body":"Your quote expires on 20 November 2026."}
    assert reconciler.insurance_quote_only(quote)
    assert not reconciler.insurance_quote_only({"subject":"Your renewal quote","body":"Your current policy expires on 20 November 2026. Please review the renewal."})
    assert not reconciler.insurance_quote_only({"subject":"Insurance quote correction","body":"Please provide your correct address."})


def test_quote_document_cannot_supply_policy_due_date(monkeypatch):
    task={"title":"Car insurance renewal","email_message_id":"<quote@example.test>",
          "source_message_ids":["<quote@example.test>"],"paperless_evidence":[{"document_id":83}]}
    monkeypatch.setattr(reconciler,"_paperless_document",lambda _id: {
        "id":83,"title":"Your insurance quote","content":"Message-ID: <quote@example.test>\nExpiry date: 20 November 2026."})
    reconciler.reconcile_insurance_policy_due_date(task)
    assert task["due_date"] is None
    assert task["due_date_source"]=="unverified_insurance_policy"


def test_multi_message_quote_hold_requires_every_source_and_preserves_notes():
    task={"title":"Car insurance renewal","source_message_ids":["<a@example.test>","<b@example.test>"],
          "timeline_events":[],"comments":["keep this note"]}
    quote={"subject":"Car insurance quote","body":"Your quotation is ready."}
    assert not reconciler.hold_quote_only_obligation(task,{"<a@example.test>":quote})
    assert reconciler.hold_quote_only_obligation(task,{"<a@example.test>":quote,"<b@example.test>":quote})
    assert task["comments"]==["keep this note"]
    assert len(task["source_message_ids"])==2
    task["due_date_source"]="paperless_policy"
    assert not reconciler.hold_quote_only_obligation(task,{"<a@example.test>":quote,"<b@example.test>":quote})
