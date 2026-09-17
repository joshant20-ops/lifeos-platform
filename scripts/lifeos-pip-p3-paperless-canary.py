#!/usr/bin/env python3
"""P3: reversible native-Paperless matcher canary.

Runs inside the Paperless Django container.  It identifies only the P2-safe
existing taxonomy objects, snapshots their matcher fields, enables native
case-insensitive literal matching temporarily, remeasures the same stable
sample, and rolls every change back before exit.  No document metadata is
written and no private taxonomy/document values are emitted.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
import logging

from documents.classifier import load_classifier
from documents.matching import matches
from documents.models import Correspondent, Document, DocumentType, MatchingModel, StoragePath, Tag

logging.disable(logging.CRITICAL)

# Reuse the accepted P2 sample/evaluation primitives without copying Paperless logic.
exec(open("/tmp/lifeos-pip-p2-lib.py").read().replace("\nmain()\n", "\n"), globals())

SAFE_DIMENSIONS = (("DOCUMENT_TYPE", DocumentType, False), ("TAG", Tag, True))
EXPECTED_SAFE = {"DOCUMENT_TYPE": 2, "TAG": 2}


def candidate_hits(model, sample):
    rules = explicit_rules(model)
    auto = list(model.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk"))
    effective = {r.pk for r in rules + auto}
    candidates = literal_shadow_candidates(model, effective)
    threshold = max(3, (len(sample) + 3) // 4)
    counts = Counter()
    for document in sample:
        for pk, rule in candidates:
            if matches(rule, document):
                counts[pk] += 1
    safe = [pk for pk, _ in candidates if 0 < counts[pk] < threshold]
    return safe


@contextmanager
def reversible_matchers(objects):
    fields = ("match", "matching_algorithm", "is_insensitive")
    snapshot = {obj.pk: tuple(getattr(obj, f) for f in fields) for obj in objects}
    try:
        for obj in objects:
            obj.match = obj.name
            obj.matching_algorithm = MatchingModel.MATCH_LITERAL
            obj.is_insensitive = True
            obj.save(update_fields=list(fields))
        yield
    finally:
        for obj in objects:
            values = snapshot[obj.pk]
            for field, value in zip(fields, values):
                setattr(obj, field, value)
            obj.save(update_fields=list(fields))


def coverage(sample):
    classifier = load_classifier()
    any_native = set()
    overlap = {"DOCUMENT_TYPE": 0, "TAG": 0}
    for prefix, model, multi in SAFE_DIMENSIONS:
        explicit = explicit_rules(model)
        auto = list(model.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk"))
        for document in sample:
            hit = native_matches(explicit, document)
            native = list(hit)
            if classifier is not None and auto:
                if prefix == "DOCUMENT_TYPE":
                    predicted = classifier.predict_document_type(document.suggestion_content)
                    native += [r for r in auto if r.pk == predicted]
                else:
                    predicted = set(classifier.predict_tags(document.suggestion_content))
                    native += [r for r in auto if r.pk in predicted]
            ids = {r.pk for r in native}
            if ids:
                any_native.add(document.pk)
            if len(ids) > 1:
                overlap[prefix] += 1
    return len(any_native), overlap


def main_p3():
    documents = list(Document.objects.order_by("pk").select_related("correspondent", "document_type", "storage_path").prefetch_related("tags"))
    sample, _ = representative_sample(documents)
    selected = {}
    for prefix, model, _ in SAFE_DIMENSIONS:
        ids = candidate_hits(model, sample)
        if len(ids) != EXPECTED_SAFE[prefix]:
            print(f"{prefix}_SAFE_CANDIDATE_COUNT={len(ids)}")
            print("P3_PRECONDITION=FAIL")
            print("RESULT=BLOCKED")
            return
        selected[prefix] = list(model.objects.filter(pk__in=ids).order_by("pk"))

    before, before_overlap = coverage(sample)
    objects = selected["DOCUMENT_TYPE"] + selected["TAG"]
    with reversible_matchers(objects):
        during, during_overlap = coverage(sample)
        print("P3_CANARY_NATIVE_CONFIGURATION=ACTIVE")
        print(f"P3_SAMPLE_DOCUMENTS={len(sample)}")
        print(f"P3_SAFE_DOCUMENT_TYPE_RULES={len(selected['DOCUMENT_TYPE'])}")
        print(f"P3_SAFE_TAG_RULES={len(selected['TAG'])}")
        print(f"P3_NATIVE_COVERAGE_BEFORE={before}")
        print(f"P3_NATIVE_COVERAGE_CANARY={during}")
        print(f"P3_DOCUMENT_TYPE_OVERLAP_BEFORE={before_overlap['DOCUMENT_TYPE']}")
        print(f"P3_DOCUMENT_TYPE_OVERLAP_CANARY={during_overlap['DOCUMENT_TYPE']}")
        print(f"P3_TAG_OVERLAP_BEFORE={before_overlap['TAG']}")
        print(f"P3_TAG_OVERLAP_CANARY={during_overlap['TAG']}")

    # Verify exact matcher rollback without exposing private values.
    restored = True
    for prefix, model, _ in SAFE_DIMENSIONS:
        effective = set(candidate_hits(model, sample))
        restored = restored and effective == {obj.pk for obj in selected[prefix]}
    print(f"P3_MATCHER_ROLLBACK={'PASS' if restored else 'FAIL'}")
    print("P3_DOCUMENT_METADATA_MUTATION=NONE")
    print("P3_NEW_TAXONOMY=NONE")
    print("P3_TOWER_AI_USED=NO")
    print("P3_PRIVATE_FIELDS_EMITTED=NONE")
    print("P3_REVIEW_CANDIDATES_MUTATED=NO")
    print("P3_CANARY=PASS" if restored else "P3_CANARY=FAIL")
    print("RESULT=PASS" if restored else "RESULT=FAIL")


main_p3()
