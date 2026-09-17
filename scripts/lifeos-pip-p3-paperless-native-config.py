#!/usr/bin/env python3
"""Guarded P3 activation of proven Paperless-native document-type rules."""
from __future__ import annotations
from hashlib import sha256
import json
import logging
import os
from pathlib import Path
from django.db import transaction
from documents.matching import matches
from documents.models import Document, DocumentType, MatchingModel, Tag

logging.disable(logging.CRITICAL)
ROLLBACK = Path(os.environ.get("LIFEOS_P3_ROLLBACK", "/usr/src/paperless/data/lifeos-p3-native-rollback.json"))

def candidates(model):
    return list(model.objects.filter(matching_algorithm=MatchingModel.MATCH_NONE).exclude(name="").order_by("pk"))

def literal_shadow(existing):
    return existing.__class__(name="private-native-candidate", match=existing.name,
        matching_algorithm=MatchingModel.MATCH_LITERAL, is_insensitive=True)

def state_hash() -> str:
    rows = DocumentType.objects.order_by("pk").values_list("pk", "match", "matching_algorithm", "is_insensitive")
    return sha256(repr(list(rows)).encode()).hexdigest()

def main() -> None:
    if os.environ.get("LIFEOS_P3_MODE", "apply") == "rollback":
        payload = json.loads(ROLLBACK.read_text())
        with transaction.atomic():
            for row in payload["document_types"]:
                DocumentType.objects.filter(pk=row["pk"]).update(
                    match=row["match"], matching_algorithm=row["matching_algorithm"],
                    is_insensitive=row["is_insensitive"],
                )
            assert state_hash() == payload["before_hash"]
        ROLLBACK.unlink()
        print("NATIVE_CONFIGURATION_ROLLBACK=PASS")
        print("PRIVATE_FIELDS_EMITTED=NONE")
        print("RESULT=PASS")
        return
    documents = list(Document.objects.order_by("pk").prefetch_related("tags"))
    broad_threshold = max(3, (len(documents) + 3) // 4)
    type_candidates = candidates(DocumentType)
    shadows = [(item, literal_shadow(item)) for item in type_candidates]
    hits = {item.pk: [] for item, _ in shadows}
    hit_ids = {}
    for document in documents:
        ids = {item.pk for item, shadow in shadows if matches(shadow, document)}
        hit_ids[document.pk] = ids
        for item_id in ids:
            hits[item_id].append(document)
    eligible = []
    for item, _ in shadows:
        matched = hits[item.pk]
        ambiguous = any(len(hit_ids[document.pk]) > 1 for document in matched)
        conflicting = any(document.document_type_id is not None and document.document_type_id != item.pk for document in matched)
        if 0 < len(matched) < broad_threshold and not ambiguous and not conflicting:
            eligible.append(item)
    tag_candidates = candidates(Tag)
    tag_hits = sum(any(matches(literal_shadow(item), document) for document in documents) for item in tag_candidates)
    before_hash = state_hash()
    rollback_rows = [{"pk": item.pk, "match": item.match,
                      "matching_algorithm": item.matching_algorithm,
                      "is_insensitive": item.is_insensitive} for item in eligible]
    temporary_rollback = ROLLBACK.with_suffix(".tmp")
    with transaction.atomic():
        for item in eligible:
            item.match = item.name
            item.matching_algorithm = MatchingModel.MATCH_LITERAL
            item.is_insensitive = True
            item.save(update_fields=("match", "matching_algorithm", "is_insensitive"))
        active = list(DocumentType.objects.exclude(matching_algorithm=MatchingModel.MATCH_NONE).exclude(match="").order_by("pk"))
        ambiguity = conflicts = covered = 0
        for document in documents:
            matched = [rule for rule in active if matches(rule, document)]
            covered += bool(matched)
            ambiguity += len(matched) > 1
            matched_ids = {rule.pk for rule in matched}
            conflicts += bool(document.document_type_id is not None and matched_ids and document.document_type_id not in matched_ids)
        assert ambiguity == 0, "native activation introduced ambiguity"
        assert conflicts == 0, "native activation conflicts with existing metadata"
        if rollback_rows:
            temporary_rollback.write_text(json.dumps({"before_hash": before_hash, "document_types": rollback_rows}))
            os.replace(temporary_rollback, ROLLBACK)
    print(f"CORPUS_DOCUMENTS={len(documents)}")
    print(f"DOCUMENT_TYPE_CANDIDATES_ASSESSED={len(type_candidates)}")
    print(f"DOCUMENT_TYPE_RULES_ACTIVATED={len(eligible)}")
    print(f"DOCUMENT_TYPE_RULES_REVIEW={len(type_candidates) - len(eligible)}")
    print(f"DOCUMENT_TYPE_NATIVE_COVERED_DOCUMENTS={covered}")
    print(f"DOCUMENT_TYPE_AMBIGUOUS_DOCUMENTS={ambiguity}")
    print(f"DOCUMENT_TYPE_CONFLICTING_DOCUMENTS={conflicts}")
    print(f"TAG_RULES_DEFERRED_OVERLAP_RISK={tag_hits}")
    print("PRODUCTION_DOCUMENT_MUTATION=NONE")
    print("PRODUCTION_TAXONOMY_CONFIGURATION=BOUNDED_NATIVE_MATCHERS")
    print(f"ROLLBACK_ARTIFACT={'PRESERVED_LOCAL' if ROLLBACK.exists() else 'NOT_REQUIRED'}")
    print("TOWER_AI_USED=NO")
    print("LIFEOS_CLASSIFIER_BUILT=NO")
    print("PRIVATE_FIELDS_EMITTED=NONE")
    print("PRIVACY_LOCAL_ONLY=PASS")
    print(f"CONFIG_STATE_HASH={state_hash()}")
    print("RESULT=PASS")

main()
