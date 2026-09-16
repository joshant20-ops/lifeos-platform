import json
from datetime import date
from pathlib import Path

from governor.finance_assets_readonly import (
    EvidenceReference,
    FinanceReadModel,
    FreeAgentReadAdapter,
    GetOnlyJsonTransport,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "governor/contracts/examples/freeagent-bank-transactions.synthetic.json"


class FixtureTransport:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get(self, path, query=None):
        self.calls.append((path, query))
        return self.payload


def adapter():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return FreeAgentReadAdapter(FixtureTransport(payload), "https://example.invalid/account/1")


def test_transport_only_exposes_get_and_rejects_non_https():
    try:
        GetOnlyJsonTransport("http://accounting.invalid", "synthetic-token")
    except ValueError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("non-HTTPS accounting endpoint was accepted")
    transport = GetOnlyJsonTransport("https://accounting.invalid", "synthetic-token")
    assert hasattr(transport, "get")
    for method in ("post", "put", "patch", "delete"):
        assert not hasattr(transport, method)


def test_freeagent_adapter_normalises_without_retaining_private_description():
    subject = adapter()
    records = list(subject.iter_transactions())
    assert [record.amount_minor for record in records] == [140000, -12550]
    assert [record.kind for record in records] == ["income", "expense"]
    assert records[0].property_ref.startswith("property:")
    assert all(not hasattr(record, "description") for record in records)
    assert records[0].record_id != records[1].record_id
    assert records[0].fingerprint == records[0].fingerprint
    assert subject.transport.calls == [
        (
            "/v2/bank_transactions",
            {
                "bank_account": "https://example.invalid/account/1",
                "page": "1",
                "per_page": "100",
            },
        )
    ]


def test_local_projection_is_idempotent_and_conflicts_fail_closed(tmp_path):
    records = list(adapter().iter_transactions())
    model = FinanceReadModel(tmp_path / "finance.sqlite3")
    assert model.ingest(records) == {"seen": 2, "inserted": 2, "unchanged": 0, "conflicts": 0}
    assert model.ingest(records) == {"seen": 2, "inserted": 0, "unchanged": 2, "conflicts": 0}

    changed = records[0].__class__(
        **{**records[0].__dict__, "amount_minor": records[0].amount_minor + 1}
    )
    assert model.ingest([changed]) == {"seen": 1, "inserted": 0, "unchanged": 0, "conflicts": 1}


def test_exact_evidence_link_is_idempotent_and_ambiguous_matches_are_not_linked(tmp_path):
    model = FinanceReadModel(tmp_path / "finance.sqlite3")
    model.ingest(adapter().iter_transactions())
    reference = EvidenceReference(
        42, "a" * 64, "invoice", -12550, "GBP", date(2026, 5, 3)
    )
    assert model.link_exact_evidence([reference]) == 1
    assert model.link_exact_evidence([reference]) == 0
    ambiguous = EvidenceReference(
        43, "b" * 64, "receipt", 999, "GBP", date(2026, 5, 3)
    )
    assert model.link_exact_evidence([ambiguous]) == 0


def test_report_is_local_read_only_and_arithmetically_reconciled(tmp_path):
    model = FinanceReadModel(tmp_path / "finance.sqlite3")
    result = model.ingest(adapter().iter_transactions())
    report = model.report(date(2026, 4, 6), date(2027, 4, 5))
    assert result["seen"] == report["record_count"]
    assert report == {
        "privacy": "local-only",
        "mode": "read-only",
        "period": {"start": "2026-04-06", "end": "2027-04-05"},
        "property_ref": None,
        "record_count": 2,
        "income_minor": 140000,
        "expense_minor": 12550,
        "net_minor": 127450,
        "uncategorised_count": 1,
        "without_evidence_count": 2,
    }


def test_reconciliation_summary_and_property_report_are_deterministic(tmp_path):
    records = list(adapter().iter_transactions())
    model = FinanceReadModel(tmp_path / "finance.sqlite3")
    model.ingest(records)
    assert model.reconciliation_summary() == {
        "privacy": "local-only",
        "mode": "read-only",
        "imported_record_count": 2,
        "imported_totals_minor": {"GBP": 127450},
        "matched_evidence_count": 0,
        "unmatched_evidence_count": 2,
    }
    report = model.report(date(2026, 4, 6), date(2027, 4, 5), records[0].property_ref)
    assert report["record_count"] == 2
    assert report["property_ref"] == records[0].property_ref


def test_bounded_import_reconciles_source_and_projection_totals(tmp_path):
    model = FinanceReadModel(tmp_path / "finance.sqlite3")
    assert model.ingest_reconciled(adapter().iter_transactions()) == {
        "privacy": "local-only",
        "mode": "read-only",
        "source_record_count": 2,
        "source_totals_minor": {"GBP": 127450},
        "imported_record_count": 2,
        "imported_totals_minor": {"GBP": 127450},
        "conflict_count": 0,
        "status": "PASS",
    }


def test_no_ai_or_authoritative_mutation_path_exists():
    text = (ROOT / "governor/finance_assets_readonly.py").read_text(encoding="utf-8")
    assert 'method="GET"' in text
    assert 'method="POST"' not in text
    assert "ollama" not in text.lower()
    assert "ai_broker" not in text
