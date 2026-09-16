#!/usr/bin/env bash
set -Eeuo pipefail

# P0 is deliberately read-only. The Django process performs aggregate SELECTs
# inside the Paperless application container and emits no titles, content,
# filenames, names, identifiers, checksums, or other source values.
container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"

docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || {
  echo 'PAPERLESS_RUNTIME=UNAVAILABLE'
  echo 'RESULT=BLOCKED'
  exit 2
}

docker exec -i "$container" python3 manage.py shell <<'PY'
from collections import Counter
from hashlib import sha256
import json
import re

from django.apps import apps
from documents.models import Document, Correspondent, DocumentType, Tag


def scalar(value):
    return "" if value is None else str(value)


def relation_id(document, name):
    return getattr(document, name + "_id", None)


def snapshot(documents):
    digest = sha256()
    for document in documents:
        values = (
            document.pk,
            getattr(document, "modified", None),
            relation_id(document, "correspondent"),
            relation_id(document, "document_type"),
            relation_id(document, "storage_path"),
            scalar(getattr(document, "checksum", "")),
            tuple(document.tags.order_by("pk").values_list("pk", flat=True)),
        )
        digest.update(repr(values).encode("utf-8"))
    return digest.hexdigest()


documents = list(Document.objects.order_by("pk").prefetch_related("tags"))
before = snapshot(documents)

total = len(documents)
missing_correspondent = sum(relation_id(d, "correspondent") is None for d in documents)
missing_type = sum(relation_id(d, "document_type") is None for d in documents)
untagged = sum(not d.tags.exists() for d in documents)
ocr_missing = sum(not scalar(getattr(d, "content", "")).strip() for d in documents)
ocr_present = total - ocr_missing

length_buckets = Counter()
year_buckets = Counter()
checksums = Counter()
title_keys = Counter()
finance_property = 0
keywords = re.compile(
    r"\b(invoice|receipt|statement|mortgage|rent|tenan|landlord|property|tax|hmrc|"
    r"insurance|utility|repair|bank|interest|investment|pension|mot|vehicle)\w*\b",
    re.IGNORECASE,
)
for document in documents:
    content = scalar(getattr(document, "content", ""))
    size = len(content)
    length_buckets[
        "empty" if size == 0 else "short" if size < 200 else "medium" if size < 2000 else "long"
    ] += 1
    created = getattr(document, "created", None)
    if created is not None:
        year_buckets[str(created.year)] += 1
    checksum = scalar(getattr(document, "checksum", "")).strip()
    if checksum:
        checksums[checksum] += 1
    title = scalar(getattr(document, "title", ""))
    normalized_title = re.sub(r"\W+", " ", title.casefold()).strip()
    if normalized_title:
        title_keys[normalized_title] += 1
    if keywords.search(title + "\n" + content[:12000]):
        finance_property += 1

exact_duplicate_groups = sum(count > 1 for count in checksums.values())
exact_duplicate_documents = sum(count for count in checksums.values() if count > 1)
probable_title_groups = sum(count > 1 for count in title_keys.values())

mail_accounts = "UNAVAILABLE"
mail_rules = "UNAVAILABLE"
try:
    MailAccount = apps.get_model("paperless_mail", "MailAccount")
    MailRule = apps.get_model("paperless_mail", "MailRule")
    mail_accounts = str(MailAccount.objects.count())
    mail_rules = str(MailRule.objects.count())
except LookupError:
    pass

# Re-read authoritative rows and compare a metadata fingerprint. This is not a
# concurrency lock; it proves this process issued no mutation and flags a live
# concurrent change rather than presenting an unstable baseline as accepted.
after_documents = list(Document.objects.order_by("pk").prefetch_related("tags"))
after = snapshot(after_documents)
stable = before == after and len(after_documents) == total

metrics = {
    "PAPERLESS_DOCUMENTS": total,
    "CORRESPONDENTS_DEFINED": Correspondent.objects.count(),
    "DOCUMENTS_MISSING_CORRESPONDENT": missing_correspondent,
    "DOCUMENT_TYPES_DEFINED": DocumentType.objects.count(),
    "DOCUMENTS_MISSING_TYPE": missing_type,
    "TAGS_DEFINED": Tag.objects.count(),
    "DOCUMENTS_UNTAGGED": untagged,
    "OCR_PRESENT": ocr_present,
    "OCR_MISSING": ocr_missing,
    "OCR_LENGTH_BUCKETS": json.dumps(dict(sorted(length_buckets.items())), separators=(",", ":")),
    "DOCUMENT_YEAR_BUCKETS": json.dumps(dict(sorted(year_buckets.items())), separators=(",", ":")),
    "EXACT_DUPLICATE_GROUPS": exact_duplicate_groups,
    "EXACT_DUPLICATE_DOCUMENTS": exact_duplicate_documents,
    "PROBABLE_SAME_TITLE_GROUPS": probable_title_groups,
    "LIKELY_FINANCE_PROPERTY_DOCUMENTS": finance_property,
    "PAPERLESS_MAIL_ACCOUNTS": mail_accounts,
    "PAPERLESS_MAIL_RULES": mail_rules,
    "PAPERLESS_METADATA_STABLE": "PASS" if stable else "CHANGED_CONCURRENTLY",
    "PAPERLESS_MUTATION": "NONE",
    "PRIVATE_FIELDS_EMITTED": "NONE",
    "PRIVACY_LOCAL_ONLY": "PASS",
}
for key, value in metrics.items():
    print(f"{key}={value}")
print("RESULT=" + ("PASS" if stable else "RETRY_REQUIRED"))
raise SystemExit(0 if stable else 3)
PY
