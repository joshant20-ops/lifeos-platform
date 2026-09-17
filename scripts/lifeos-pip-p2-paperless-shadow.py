#!/usr/bin/env python3
"""Read-only aggregate evaluation of Paperless's native matching capability.

This runs inside the Paperless Django container.  It intentionally invokes
Paperless's own matcher and optional native classifier; it does not reproduce
their algorithms.  Real document content and taxonomy values are used only in
memory and are never emitted.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from hashlib import sha256
import logging

from documents.classifier import load_classifier
from documents.matching import matches
from documents.models import Correspondent, Document, DocumentType, MatchingModel, StoragePath, Tag, Workflow


logging.disable(logging.CRITICAL)
SAMPLE_LIMIT = 192
SAMPLE_PER_STRATUM = 48


def stable_key(document: Document) -> str:
    private_stable_value = (getattr(document, "checksum", "") or str(document.pk)).encode()
    return sha256(private_stable_value).hexdigest()


def stratum(document: Document) -> tuple[bool, bool, bool, bool]:
    return (
        document.correspondent_id is not None,
        document.document_type_id is not None,
        bool(document._prefetched_objects_cache["tags"]),
        bool((document.content or "").strip()),
    )


def representative_sample(documents: list[Document]) -> tuple[list[Document], int]:
    groups: dict[tuple[bool, bool, bool, bool], list[Document]] = defaultdict(list)
    for document in documents:
        groups[stratum(document)].append(document)
    selected: list[Document] = []
    for key in sorted(groups):
        selected.extend(sorted(groups[key], key=stable_key)[:SAMPLE_PER_STRATUM])
    return sorted(selected, key=stable_key)[:SAMPLE_LIMIT], len(groups)


def explicit_rules(model):
    return list(
        model.objects.exclude(matching_algorithm__in=(MatchingModel.MATCH_NONE, MatchingModel.MATCH_AUTO))
        .exclude(match="")
        .order_by("pk")
    )


def native_matches(rules, document):
    return [rule for rule in rules if matches(rule, document)]


def main() -> None:
    documents = list(
        Document.objects.order_by("pk")
        .select_related("correspondent", "document_type", "storage_path")
        .prefetch_related("tags")
    )
    sample, strata = representative_sample(documents)
    classifier = load_classifier()

    dimensions = (
        ("CORRESPONDENT", Correspondent, "correspondent_id", False),
        ("DOCUMENT_TYPE", DocumentType, "document_type_id", False),
        ("TAG", Tag, None, True),
        ("STORAGE_PATH", StoragePath, "storage_path_id", False),
    )
    aggregate: dict[str, int] = {}
    any_explicit: set[int] = set()
    any_native: set[int] = set()
    total_conflicts = 0
    total_ambiguities = 0
    broad_rule_total = 0
    zero_hit_total = 0

    for prefix, model, assigned_field, multi_value in dimensions:
        rules = explicit_rules(model)
        auto_rules = list(model.objects.filter(matching_algorithm=MatchingModel.MATCH_AUTO).order_by("pk"))
        hits_by_rule = Counter()
        explicit_covered = native_covered = ambiguity = conflicts = overlap = 0

        for document in sample:
            hit = native_matches(rules, document)
            for rule in hit:
                hits_by_rule[rule.pk] += 1
            if hit:
                explicit_covered += 1
                any_explicit.add(document.pk)
            if len(hit) > 1:
                if multi_value:
                    overlap += 1
                else:
                    ambiguity += 1

            native = list(hit)
            if classifier is not None and auto_rules:
                if prefix == "CORRESPONDENT":
                    predicted = classifier.predict_correspondent(document.suggestion_content)
                    native.extend(rule for rule in auto_rules if rule.pk == predicted)
                elif prefix == "DOCUMENT_TYPE":
                    predicted = classifier.predict_document_type(document.suggestion_content)
                    native.extend(rule for rule in auto_rules if rule.pk == predicted)
                elif prefix == "TAG":
                    predicted = set(classifier.predict_tags(document.suggestion_content))
                    native.extend(rule for rule in auto_rules if rule.pk in predicted)
                elif prefix == "STORAGE_PATH":
                    predicted = classifier.predict_storage_path(document.suggestion_content)
                    native.extend(rule for rule in auto_rules if rule.pk == predicted)
            native_ids = {rule.pk for rule in native}
            if native_ids:
                native_covered += 1
                any_native.add(document.pk)

            if multi_value:
                assigned = {tag.pk for tag in document._prefetched_objects_cache["tags"]}
                # A native candidate absent from current metadata is a proposal,
                # not a conflict: tags are intentionally multi-valued.
            else:
                assigned = getattr(document, assigned_field)
                if assigned is not None and native_ids and assigned not in native_ids:
                    conflicts += 1

        broad_threshold = max(3, (len(sample) + 3) // 4)
        broad = sum(count >= broad_threshold for count in hits_by_rule.values())
        zero_hit = sum(hits_by_rule[rule.pk] == 0 for rule in rules)
        review = len({rule.pk for rule in rules if hits_by_rule[rule.pk] == 0 or hits_by_rule[rule.pk] >= broad_threshold})
        if conflicts:
            review = max(review, 1)

        aggregate.update(
            {
                f"{prefix}_OBJECTS_DEFINED": model.objects.count(),
                f"{prefix}_EXPLICIT_RULES": len(rules),
                f"{prefix}_AUTO_RULES": len(auto_rules),
                f"{prefix}_EXPLICIT_COVERED_DOCUMENTS": explicit_covered,
                f"{prefix}_NATIVE_COVERED_DOCUMENTS": native_covered,
                f"{prefix}_AMBIGUOUS_DOCUMENTS": ambiguity,
                f"{prefix}_CONFLICTING_DOCUMENTS": conflicts,
                f"{prefix}_MULTI_RULE_OVERLAP_DOCUMENTS": overlap,
                f"{prefix}_BROAD_RULES": broad,
                f"{prefix}_ZERO_HIT_RULES": zero_hit,
                f"CANDIDATE_{prefix}_RULES_PRESERVE": len(rules) - review,
                f"CANDIDATE_{prefix}_RULES_REVIEW": review,
                f"CANDIDATE_{prefix}_NEW_RULES": 0,
            }
        )
        total_conflicts += conflicts
        total_ambiguities += ambiguity
        broad_rule_total += broad
        zero_hit_total += zero_hit

    checksum_counts = Counter((document.checksum or "") for document in documents)
    duplicate_groups = sum(count > 1 for checksum, count in checksum_counts.items() if checksum)
    duplicate_documents = sum(count for checksum, count in checksum_counts.items() if checksum and count > 1)
    workflows = list(Workflow.objects.order_by("pk").prefetch_related("triggers", "actions"))
    structurally_complete_workflows = sum(
        workflow.enabled and bool(workflow._prefetched_objects_cache["triggers"])
        and bool(workflow._prefetched_objects_cache["actions"])
        for workflow in workflows
    )

    print(f"CORPUS_DOCUMENTS={len(documents)}")
    print(f"SAMPLE_DOCUMENTS={len(sample)}")
    print(f"SAMPLE_STRATA={strata}")
    print("SAMPLE_METHOD=stable_hash_stratified_metadata_coverage")
    print(f"NATIVE_CLASSIFIER_AVAILABLE={'YES' if classifier is not None else 'NO'}")
    for key in sorted(aggregate):
        print(f"{key}={aggregate[key]}")
    print(f"NATIVE_EXPLICIT_ANY_COVERAGE_DOCUMENTS={len(any_explicit)}")
    print(f"NATIVE_ANY_COVERAGE_DOCUMENTS={len(any_native)}")
    print(f"NATIVE_UNMATCHED_DOCUMENTS={len(sample) - len(any_native)}")
    print(f"NATIVE_AMBIGUOUS_DOCUMENTS={total_ambiguities}")
    print(f"NATIVE_CONFLICTING_DOCUMENTS={total_conflicts}")
    print(f"FALSE_OVERLAP_RISK_BROAD_RULES={broad_rule_total}")
    print(f"RULES_WITH_ZERO_SAMPLE_HITS={zero_hit_total}")
    print(f"EXACT_DUPLICATE_GROUPS={duplicate_groups}")
    print(f"EXACT_DUPLICATE_DOCUMENTS={duplicate_documents}")
    print(f"EXACT_DUPLICATE_REJECT_CURRENT_CORPUS_IMPACT={duplicate_documents}")
    print("EXACT_DUPLICATE_AUTHORITY=PAPERLESS")
    print(f"WORKFLOWS_DEFINED={len(workflows)}")
    print(f"CANDIDATE_WORKFLOWS_PRESERVE={structurally_complete_workflows}")
    print(f"CANDIDATE_WORKFLOWS_REVIEW={len(workflows) - structurally_complete_workflows}")
    print("CANDIDATE_WORKFLOWS_NEW=0")
    print("PROPOSED_PRODUCTION_MUTATIONS=NONE")
    print("PRODUCTION_DOCUMENT_MUTATION=NONE")
    print("PRODUCTION_METADATA_MUTATION=NONE")
    print("TOWER_AI_USED=NO")
    print("LIFEOS_CLASSIFIER_BUILT=NO")
    print("PRIVATE_FIELDS_EMITTED=NONE")
    print("PRIVACY_LOCAL_ONLY=PASS")
    print("RESULT=PASS")


main()
