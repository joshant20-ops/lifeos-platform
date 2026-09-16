"""Read-only Wave C ingestion and reporting primitives.

This module deliberately contains no POST/PUT/PATCH/DELETE transport.  It builds
a recoverable local projection of records owned by an accounting provider and
references evidence owned by Paperless.  Local AI may propose classification
elsewhere, but it cannot mutate either authority through this module.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol


ADAPTER_VERSION = "freeagent-readonly-v1"


def _stable_id(prefix: str, material: str) -> str:
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest[:32]}"


def uk_tax_year(day: date) -> str:
    start = day.year if day >= date(day.year, 4, 6) else day.year - 1
    return f"{start:04d}-{(start + 1) % 100:02d}"


@dataclass(frozen=True)
class SourceTransaction:
    source_system: str
    source_record_id: str
    account_ref: str
    booked_on: date
    amount_minor: int
    currency: str
    kind: str
    source_category_ref: str | None = None
    property_ref: str | None = None

    @property
    def fingerprint(self) -> str:
        material = "|".join(
            (
                self.source_system,
                self.source_record_id,
                self.booked_on.isoformat(),
                self.currency,
                str(self.amount_minor),
            )
        )
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    @property
    def record_id(self) -> str:
        return _stable_id(
            "finance",
            f"{self.source_system}|{self.source_record_id}",
        )


@dataclass(frozen=True)
class EvidenceReference:
    paperless_document_id: int
    sha256: str
    relation: str
    amount_minor: int
    currency: str
    booked_on: date
    verified: bool = True


class AccountingReadAdapter(Protocol):
    def iter_transactions(self) -> Iterable[SourceTransaction]: ...


class GetOnlyJsonTransport:
    """HTTP JSON transport that makes non-GET methods unrepresentable."""

    def __init__(self, base_url: str, bearer_token: str, timeout: int = 30):
        if not base_url.startswith("https://"):
            raise ValueError("accounting API must use HTTPS")
        self.base_url = base_url.rstrip("/")
        self._bearer_token = bearer_token
        self.timeout = timeout

    def get(self, path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
        if not path.startswith("/") or "//" in path:
            raise ValueError("path must be an absolute API path")
        url = f"{self.base_url}{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "Authorization": f"Bearer {self._bearer_token}",
                "Accept": "application/json",
                "User-Agent": "lifeos-finance-readonly/1",
            },
        )
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)


class FreeAgentReadAdapter:
    """Normalize FreeAgent bank transactions without retaining descriptions."""

    def __init__(self, transport: GetOnlyJsonTransport, account_url: str):
        self.transport = transport
        self.account_url = account_url

    def iter_transactions(self) -> Iterable[SourceTransaction]:
        page = 1
        while True:
            payload = self.transport.get(
                "/v2/bank_transactions",
                {
                    "bank_account": self.account_url,
                    "page": str(page),
                    "per_page": "100",
                },
            )
            rows = payload.get("bank_transactions", [])
            if not isinstance(rows, list):
                raise ValueError("invalid FreeAgent bank_transactions response")
            for row in rows:
                yield self._normalise(row)
            if len(rows) < 100:
                break
            page += 1

    def _normalise(self, row: dict[str, Any]) -> SourceTransaction:
        source_id = str(row.get("url", "")).rsplit("/", 1)[-1]
        if not source_id:
            raise ValueError("FreeAgent transaction has no stable URL identity")
        amount_minor = _decimal_to_minor(row["amount"])
        currency = str(row.get("currency", "GBP")).upper()
        if len(currency) != 3:
            raise ValueError("invalid currency")
        category = row.get("category")
        property_ref = row.get("property")
        return SourceTransaction(
            source_system="freeagent",
            source_record_id=source_id,
            account_ref=_stable_id("account", self.account_url),
            booked_on=date.fromisoformat(str(row["dated_on"])),
            amount_minor=amount_minor,
            currency=currency,
            kind="income" if amount_minor >= 0 else "expense",
            source_category_ref=_reference_id("category", category),
            property_ref=_reference_id("property", property_ref),
        )


def _reference_id(prefix: str, value: Any) -> str | None:
    if value in (None, ""):
        return None
    return _stable_id(prefix, str(value))


def _decimal_to_minor(value: Any) -> int:
    from decimal import Decimal, InvalidOperation, ROUND_HALF_EVEN

    try:
        amount = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    except InvalidOperation as exc:
        raise ValueError("invalid monetary amount") from exc
    return int(amount * 100)


class FinanceReadModel:
    """Recoverable local projection with idempotent conflict detection."""

    def __init__(self, database: str | Path):
        self.connection = sqlite3.connect(str(database))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS finance_records (
                record_id TEXT PRIMARY KEY,
                source_system TEXT NOT NULL,
                source_record_id TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                account_ref TEXT NOT NULL,
                property_ref TEXT,
                booked_on TEXT NOT NULL,
                amount_minor INTEGER NOT NULL,
                currency TEXT NOT NULL,
                kind TEXT NOT NULL,
                category_ref TEXT,
                evidence_json TEXT NOT NULL DEFAULT '[]',
                observed_at TEXT NOT NULL,
                UNIQUE(source_system, source_record_id)
            )
            """
        )
        self.connection.commit()

    def ingest(self, records: Iterable[SourceTransaction]) -> dict[str, int]:
        result = {"seen": 0, "inserted": 0, "unchanged": 0, "conflicts": 0}
        for record in records:
            result["seen"] += 1
            current = self.connection.execute(
                "SELECT fingerprint FROM finance_records WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            if current:
                if current["fingerprint"] != record.fingerprint:
                    result["conflicts"] += 1
                    continue
                result["unchanged"] += 1
                continue
            self.connection.execute(
                """INSERT INTO finance_records
                (record_id, source_system, source_record_id, fingerprint,
                 account_ref, property_ref, booked_on, amount_minor, currency,
                 kind, category_ref, observed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    record.record_id,
                    record.source_system,
                    record.source_record_id,
                    record.fingerprint,
                    record.account_ref,
                    record.property_ref,
                    record.booked_on.isoformat(),
                    record.amount_minor,
                    record.currency,
                    record.kind,
                    record.source_category_ref,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            result["inserted"] += 1
        self.connection.commit()
        return result

    def ingest_reconciled(self, records: Iterable[SourceTransaction]) -> dict[str, Any]:
        """Ingest a bounded provider page/batch and prove its local projection totals."""
        batch = list(records)
        source_totals: dict[str, int] = {}
        for record in batch:
            source_totals[record.currency] = (
                source_totals.get(record.currency, 0) + record.amount_minor
            )
        ingestion = self.ingest(batch)
        imported_totals: dict[str, int] = {}
        imported_count = 0
        for record in batch:
            row = self.connection.execute(
                "SELECT amount_minor, currency, fingerprint FROM finance_records "
                "WHERE record_id = ?",
                (record.record_id,),
            ).fetchone()
            if row is None or row["fingerprint"] != record.fingerprint:
                continue
            imported_count += 1
            imported_totals[row["currency"]] = (
                imported_totals.get(row["currency"], 0) + row["amount_minor"]
            )
        return {
            "privacy": "local-only",
            "mode": "read-only",
            "source_record_count": len(batch),
            "source_totals_minor": source_totals,
            "imported_record_count": imported_count,
            "imported_totals_minor": imported_totals,
            "conflict_count": ingestion["conflicts"],
            "status": (
                "PASS"
                if imported_count == len(batch)
                and imported_totals == source_totals
                and ingestion["conflicts"] == 0
                else "REVIEW_REQUIRED"
            ),
        }

    def reconciliation_summary(self) -> dict[str, Any]:
        rows = self.connection.execute(
            "SELECT amount_minor, currency, evidence_json FROM finance_records"
        ).fetchall()
        totals: dict[str, int] = {}
        for row in rows:
            totals[row["currency"]] = totals.get(row["currency"], 0) + row["amount_minor"]
        return {
            "privacy": "local-only",
            "mode": "read-only",
            "imported_record_count": len(rows),
            "imported_totals_minor": totals,
            "matched_evidence_count": sum(row["evidence_json"] != "[]" for row in rows),
            "unmatched_evidence_count": sum(row["evidence_json"] == "[]" for row in rows),
        }

    def link_exact_evidence(self, references: Iterable[EvidenceReference]) -> int:
        linked = 0
        for evidence in references:
            if not evidence.verified:
                continue
            matches = self.connection.execute(
                "SELECT record_id, evidence_json FROM finance_records "
                "WHERE amount_minor = ? AND currency = ? AND booked_on = ?",
                (evidence.amount_minor, evidence.currency, evidence.booked_on.isoformat()),
            ).fetchall()
            if len(matches) != 1:
                continue
            row = matches[0]
            items = json.loads(row["evidence_json"])
            item = {
                "paperless_document_id": evidence.paperless_document_id,
                "sha256": evidence.sha256,
                "relation": evidence.relation,
                "verified": True,
            }
            if item not in items:
                items.append(item)
                self.connection.execute(
                    "UPDATE finance_records SET evidence_json = ? WHERE record_id = ?",
                    (json.dumps(items, sort_keys=True), row["record_id"]),
                )
                linked += 1
        self.connection.commit()
        return linked

    def report(
        self, start: date, end: date, property_ref: str | None = None
    ) -> dict[str, Any]:
        query = "SELECT * FROM finance_records WHERE booked_on BETWEEN ? AND ?"
        parameters: list[Any] = [start.isoformat(), end.isoformat()]
        if property_ref is not None:
            query += " AND property_ref = ?"
            parameters.append(property_ref)
        rows = self.connection.execute(query, parameters).fetchall()
        income = sum(row["amount_minor"] for row in rows if row["amount_minor"] > 0)
        expenses = -sum(row["amount_minor"] for row in rows if row["amount_minor"] < 0)
        return {
            "privacy": "local-only",
            "mode": "read-only",
            "period": {"start": start.isoformat(), "end": end.isoformat()},
            "property_ref": property_ref,
            "record_count": len(rows),
            "income_minor": income,
            "expense_minor": expenses,
            "net_minor": income - expenses,
            "uncategorised_count": sum(row["category_ref"] is None for row in rows),
            "without_evidence_count": sum(row["evidence_json"] == "[]" for row in rows),
        }
