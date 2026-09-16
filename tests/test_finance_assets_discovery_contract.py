import hashlib
import json
import re
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "governor/contracts/finance-assets-read-model.schema.json"
FIXTURE_PATH = (
    ROOT
    / "governor/contracts/examples/finance-assets-read-model.synthetic.json"
)
POLICY_PATH = ROOT / "governor/privacy-domain-policy.json"
DOC_PATH = ROOT / "docs/architecture/wave-c-finance-assets-discovery.md"


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def walk_keys(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from walk_keys(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_keys(item)


def uk_tax_year(day):
    start = day.year if day >= date(day.year, 4, 6) else day.year - 1
    return f"{start:04d}-{(start + 1) % 100:02d}"


def source_fingerprint(record):
    source = record["source"]
    transaction = record["transaction"]
    material = "|".join(
        (
            source["system"],
            source["source_record_id"],
            transaction["booked_on"],
            transaction["currency"],
            str(transaction["amount_minor"]),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def test_schema_and_fixture_are_strict_local_read_only_contracts():
    schema = load(SCHEMA_PATH)
    fixture = load(FIXTURE_PATH)

    assert schema["$schema"].endswith("draft/2020-12/schema")
    assert schema["additionalProperties"] is False
    assert schema["properties"]["privacy"] == {"const": "local-only"}
    assert schema["properties"]["mode"] == {"const": "read-only"}
    assert schema["$defs"]["record"]["additionalProperties"] is False
    assert fixture["privacy"] == "local-only"
    assert fixture["mode"] == "read-only"
    assert fixture["records"]

    assert set(fixture) == set(schema["required"])
    record_schema = schema["$defs"]["record"]
    record = fixture["records"][0]
    assert set(record) == set(record_schema["required"])
    for section in (
        "source",
        "transaction",
        "classification",
        "reconciliation",
        "mutation_control",
        "provenance",
    ):
        section_schema = record_schema["properties"][section]
        assert section_schema["additionalProperties"] is False
        assert set(record[section]) == set(section_schema["required"])

    evidence_schema = record_schema["properties"]["evidence"]["items"]
    assert evidence_schema["additionalProperties"] is False
    assert set(record["evidence"][0]) == set(evidence_schema["required"])


def test_finance_domain_remains_fail_closed_without_cloud_fallback():
    policy = load(POLICY_PATH)
    finance = policy["domains"]["finance-assets"]

    assert policy["fail_closed"] is True
    assert finance["privacy"] == "local-only"
    assert finance["cloud_fallback"] is False
    assert "transactions" in finance["sources"]
    assert "tax-records" in finance["sources"]


def test_synthetic_fixture_contains_no_private_payload_or_secret_fields():
    fixture = load(FIXTURE_PATH)
    forbidden = {
        "account_number",
        "sort_code",
        "iban",
        "credential",
        "credentials",
        "token",
        "secret",
        "document_body",
        "email_body",
        "raw_payload",
        "transaction_description",
        "counterparty_name",
    }

    keys = {key.lower() for key in walk_keys(fixture)}
    assert keys.isdisjoint(forbidden)
    encoded = json.dumps(fixture).lower()
    assert "synthetic" in encoded
    assert not re.search(r"\b\d{2}-\d{2}-\d{2}\b", encoded)


def test_import_fingerprint_is_deterministic_and_idempotent():
    record = load(FIXTURE_PATH)["records"][0]
    first = source_fingerprint(record)
    second = source_fingerprint(json.loads(json.dumps(record)))

    assert first == second == record["source"]["fingerprint"]
    assert len({first, second}) == 1


def test_uk_tax_year_boundary_and_fixture_label():
    assert uk_tax_year(date(2026, 4, 5)) == "2025-26"
    assert uk_tax_year(date(2026, 4, 6)) == "2026-27"
    assert uk_tax_year(date(2027, 4, 5)) == "2026-27"
    assert uk_tax_year(date(2027, 4, 6)) == "2027-28"

    record = load(FIXTURE_PATH)["records"][0]
    booked_on = date.fromisoformat(record["transaction"]["booked_on"])
    assert record["transaction"]["tax_year"] == uk_tax_year(booked_on)


def test_reconciliation_requires_exact_amount_currency_and_evidence_reference():
    record = load(FIXTURE_PATH)["records"][0]
    transaction = record["transaction"]
    reconciliation = record["reconciliation"]

    assert reconciliation["state"] == "matched"
    assert reconciliation["rule"] == "exact-amount-currency"
    assert reconciliation["matched_amount_minor"] == transaction["amount_minor"]
    assert reconciliation["matched_currency"] == transaction["currency"]
    assert reconciliation["ledger_record_id"].startswith("synthetic-")
    assert len(record["evidence"]) == 1
    assert record["evidence"][0]["verified"] is True
    assert record["evidence"][0]["paperless_document_id"] > 0


def test_discovery_contract_cannot_authorise_ledger_or_hmrc_mutation():
    schema = load(SCHEMA_PATH)
    record = load(FIXTURE_PATH)["records"][0]
    mutation_schema = schema["$defs"]["record"]["properties"]["mutation_control"]
    classification_schema = schema["$defs"]["record"]["properties"]["classification"]

    assert mutation_schema["properties"]["permitted"] == {"const": False}
    assert mutation_schema["properties"]["approval_reference"] == {"type": "null"}
    assert mutation_schema["properties"]["ledger_write_performed"] == {"const": False}
    assert mutation_schema["properties"]["hmrc_submission_performed"] == {"const": False}
    assert classification_schema["properties"]["ai_advisory_only"] == {"const": True}
    assert classification_schema["properties"]["authority_write_performed"] == {"const": False}
    assert record["mutation_control"] == {
        "permitted": False,
        "approval_reference": None,
        "ledger_write_performed": False,
        "hmrc_submission_performed": False,
    }
    assert record["classification"]["origin"] == "local-ai-proposal"
    assert record["classification"]["ai_advisory_only"] is True
    assert record["classification"]["authority_write_performed"] is False


def test_architecture_preserves_ots_paperless_and_home_assistant_boundaries():
    text = DOC_PATH.read_text(encoding="utf-8")

    assert "authoritative ledger" in text
    assert "Paperless" in text
    assert "Home Assistant cannot grant that approval" in text
    assert "does not implement an accounting engine" in text
    assert "no AI write" in text
