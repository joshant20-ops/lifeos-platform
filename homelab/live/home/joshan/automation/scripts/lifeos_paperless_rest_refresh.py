#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

BASE_URL = os.environ.get(
    "PAPERLESS_URL",
    "http://127.0.0.1:8010",
).rstrip("/") + "/"

AUTO = Path("/home/joshan/automation")
OUT = AUTO / "logs"
API_VERSION = "10"


class ApiError(RuntimeError):
    pass


def credential() -> str:
    d = os.environ.get("CREDENTIALS_DIRECTORY")
    paths = []

    if d:
        paths.append(Path(d) / "paperless_token")

    paths.append(
        Path("/etc/lifeos/secrets/paperless-api-token")
    )

    for p in paths:
        if p.is_file():
            value = p.read_text().strip()
            if value:
                return value

    raise ApiError("Paperless credential unavailable")


def get(path_or_url: str) -> Any:
    url = (
        path_or_url
        if path_or_url.startswith("http")
        else urljoin(BASE_URL, path_or_url.lstrip("/"))
    )

    req = Request(
        url,
        headers={
            "Authorization": f"Token {credential()}",
            "Accept": (
                f"application/json; version={API_VERSION}"
            ),
            "User-Agent": "LifeOS-ImportantInfo/2",
        },
    )

    try:
        with urlopen(req, timeout=15) as r:
            return json.loads(
                r.read().decode("utf-8")
            )
    except Exception as exc:
        raise ApiError(
            f"Paperless API request failed: {exc}"
        ) from exc


def paged(endpoint: str, **params: Any):
    params.setdefault("page_size", 100)

    url = (
        urljoin(BASE_URL, endpoint.lstrip("/"))
        + "?"
        + urlencode(params)
    )

    rows = []

    while url:
        data = get(url)

        if isinstance(data, list):
            rows.extend(data)
            break

        if not isinstance(data, dict):
            raise ApiError("Unexpected Paperless response")

        rows.extend(data.get("results", []))
        url = data.get("next") or ""

    return [
        x for x in rows
        if isinstance(x, dict)
    ]


def lookup(endpoint: str):
    out = {}

    for x in paged(endpoint):
        try:
            ident = int(x["id"])
        except Exception:
            continue

        out[ident] = str(
            x.get("name")
            or x.get("title")
            or ident
        )

    return out


def resolve(value, names):
    if value in (None, ""):
        return ""

    if isinstance(value, dict):
        return str(
            value.get("name")
            or value.get("title")
            or value.get("id")
            or ""
        )

    try:
        return names.get(int(value), str(value))
    except Exception:
        return str(value)


def notes(value):
    if isinstance(value, str):
        return (
            [{"id": None, "note": value}]
            if value.strip()
            else []
        )

    if not isinstance(value, list):
        return []

    result = []

    for item in value:
        if isinstance(item, dict):
            text = str(
                item.get("note")
                or item.get("text")
                or item.get("content")
                or ""
            )

            if text.strip():
                result.append({
                    "id": item.get("id"),
                    "note": text,
                })

    return result


def classify(doc):
    text = "\n".join(
        n["note"]
        for n in notes(doc.get("notes"))
    )

    if not text.strip():
        return None

    hay = " ".join([
        text,
        str(doc.get("title") or ""),
        " ".join(
            str(x)
            for x in doc.get("tags", [])
        ),
        str(doc.get("document_type") or ""),
    ]).lower()

    if (
        any(x in hay for x in [
            "mot",
            "mot test",
            "test certificate",
            "registration number",
        ])
        and any(x in hay for x in [
            "bike",
            "motorbike",
            "vehicle",
            "registration",
        ])
    ):
        kind = "vehicle_mot"
        section = "Vehicles"
        title = "Motorbike MOT"

    elif any(x in hay for x in [
        "landlord insurance",
        "residential landlord",
        "certificate of insurance",
        "policy schedule",
        "churchill",
        "simply business",
    ]):
        kind = "landlord_insurance"
        section = "Insurance / Cover"
        title = "Landlord / house insurance"

    elif any(x in hay for x in [
        "home emergency",
        "247 home rescue",
    ]):
        kind = "home_emergency_cover"
        section = "Insurance / Cover"
        title = "Home emergency cover"

    elif any(x in hay for x in [
        "bupa",
        "blua",
        "digital gp",
    ]):
        kind = "health_benefit"
        section = "Insurance / Cover"
        title = "Health / Bupa benefit"

    else:
        return None

    years = [
        int(x)
        for x in re.findall(
            r"\b(20[0-9]{2})\b",
            hay,
        )
    ]

    latest = max(years) if years else None

    return {
        "document_id": doc.get("id"),
        "document_title": doc.get("title"),
        "kind": kind,
        "target_section": section,
        "target_title": title,
        "latest_year_seen": latest,
        "current_hint": bool(
            latest and latest >= 2025
        ),
        "notes_excerpt": text[:1200],
        "source": "paperless_rest_v10",
        "state_mutation": False,
    }


def main():
    tags = lookup("/api/tags/")
    types = lookup("/api/document_types/")
    correspondents = lookup(
        "/api/correspondents/"
    )

    rows = paged(
        "/api/documents/",
        ordering="-created",
    )

    groups = {}
    documents = {}
    facts = []
    recent_notes = 0

    for index, doc in enumerate(rows):
        ident = doc.get("id")

        if ident is None:
            continue

        # v10 currently exposes notes on document objects.
        ns = notes(doc.get("notes"))

        doc["tags"] = [
            resolve(x, tags)
            for x in doc.get("tags", [])
        ]

        doc["document_type"] = resolve(
            doc.get("document_type"),
            types,
        )

        doc["correspondent"] = resolve(
            doc.get("correspondent"),
            correspondents,
        )

        if ns:
            documents[str(ident)] = {
                "document_id": ident,
                "title": str(
                    doc.get("title") or ""
                ),
                "document_type":
                    doc["document_type"],
                "tags": doc["tags"],
                "note_ids": [
                    n["id"]
                    for n in ns
                    if n["id"] is not None
                ],
            }

        for n in ns:
            match = re.search(
                r"Memory group:\s*"
                r"([A-Za-z0-9_\-]+)",
                n["note"],
            )

            group = (
                match.group(1)
                if match
                else "manual_notes"
            )

            g = groups.setdefault(
                group,
                {
                    "group": group,
                    "document_ids": [],
                    "relationships": [],
                },
            )

            if ident not in g["document_ids"]:
                g["document_ids"].append(ident)

            related = [
                {
                    "document_id": int(m.group(1)),
                    "title": m.group(2).strip(),
                }
                for m in re.finditer(
                    r"Doc\s+(\d+):\s*"
                    r"([^\n\r]+)",
                    n["note"],
                )
            ]

            if related:
                g["relationships"].append({
                    "source_document_id": ident,
                    "note_id": n["id"],
                    "related_documents": related,
                })

        if index < 500:
            if ns:
                recent_notes += 1

            fact = classify(doc)

            if fact:
                facts.append(fact)

    now = int(time.time())

    memory = {
        "schema": "paperless_memory_index_v1",
        "generated_time": now,
        "source": "Paperless REST API v10",
        "documents_with_notes": len(documents),
        "memory_groups": groups,
        "documents": documents,
        "state_mutation": False,
    }

    memory_summary = {
        "ok": True,
        "documents_with_notes": len(documents),
        "group_count": len(groups),
        "relationship_count": sum(
            len(x["relationships"])
            for x in groups.values()
        ),
        "state_mutation": False,
    }

    facts.sort(
        key=lambda x: (
            x["target_title"],
            -(x["latest_year_seen"] or 0),
            x["document_id"] or 0,
        )
    )

    fact_data = {
        "schema": "paperless_notes_facts_v1",
        "facts": facts,
    }

    fact_summary = {
        "ok": True,
        "documents_checked": min(
            len(rows),
            500,
        ),
        "documents_with_notes": recent_notes,
        "facts_found": len(facts),
        "source_priority":
            "paperless_rest_v10",
        "state_mutation": False,
    }

    outputs = {
        "paperless_memory_index.json": memory,
        "paperless_memory_index_summary.json":
            memory_summary,
        "paperless_notes_facts.json": fact_data,
        "paperless_notes_summary.json":
            fact_summary,
    }

    OUT.mkdir(
        parents=True,
        exist_ok=True,
    )

    for name, data in outputs.items():
        (OUT / name).write_text(
            json.dumps(
                data,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    print(json.dumps({
        "ok": True,
        "mode": "shadow",
        "documents": len(rows),
        "documents_with_notes":
            len(documents),
        "facts_found": len(facts),
    }))


if __name__ == "__main__":
    try:
        main()
    except ApiError as exc:
        print(json.dumps({
            "ok": False,
            "error": str(exc),
        }))
        raise SystemExit(2)
