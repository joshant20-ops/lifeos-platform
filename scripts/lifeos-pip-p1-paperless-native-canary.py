#!/usr/bin/env python3
"""In-container helper for the reversible Paperless-first P1 canary.

This file never reads or prints production document fields.  Its queries are
strictly limited to the unique LIFEOS-P1-SYNTHETIC marker supplied by the
governed wrapper.
"""

from __future__ import annotations

import json
import os
import re
import sys

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db.models import Q

from documents.models import Correspondent, Document, DocumentType, Tag


MARKER = os.environ.get("LIFEOS_P1_MARKER", "")
MODE = os.environ.get("LIFEOS_P1_MODE", "")
assert re.fullmatch(r"LIFEOS-P1-SYNTHETIC-[0-9a-f]{32}", MARKER)


def model(name: str):
    matches = [item for item in apps.get_models() if item.__name__ == name]
    assert len(matches) == 1, f"required Paperless model unavailable: {name}"
    return matches[0]


CustomField = model("CustomField")
Workflow = model("Workflow")
WorkflowTrigger = model("WorkflowTrigger")
WorkflowAction = model("WorkflowAction")


def fields(cls):
    return {field.name: field for field in cls._meta.get_fields()}


def supported(cls, **values):
    available = fields(cls)
    return {key: value for key, value in values.items() if key in available}


def choice(cls, field_name: str, wanted: tuple[str, ...]):
    field = fields(cls)[field_name]
    choices = list(field.flatchoices)
    for needle in wanted:
        for value, label in choices:
            if needle in str(label).casefold():
                return value
    raise AssertionError(f"required native choice unavailable: {cls.__name__}.{field_name}")


def marker_documents():
    # Title is supplied by the synthetic REST upload and is the stable boundary.
    return Document.objects.filter(title=MARKER)


def counts():
    return {
        "documents": marker_documents().count(),
        "correspondents": Correspondent.objects.filter(name=MARKER).count(),
        "document_types": DocumentType.objects.filter(name=MARKER).count(),
        "tags": Tag.objects.filter(name=MARKER).count(),
        "custom_fields": CustomField.objects.filter(name=MARKER).count(),
        "workflows": Workflow.objects.filter(name=MARKER).count(),
    }


def matching_defaults(cls):
    # Regex with the unique literal is deterministic and exercises Paperless's
    # own matcher. Fall back to literal/exact only if a release labels it that way.
    algorithm = choice(cls, "matching_algorithm", ("regular expression", "regex", "literal", "exact"))
    return supported(
        cls,
        match=re.escape(MARKER),
        matching_algorithm=algorithm,
        is_insensitive=False,
    )


def configure():
    admin = get_user_model().objects.filter(is_active=True, is_superuser=True).first()
    assert admin is not None

    correspondent = Correspondent.objects.create(
        **supported(Correspondent, name=MARKER, owner=admin),
        **matching_defaults(Correspondent),
    )
    document_type = DocumentType.objects.create(
        **supported(DocumentType, name=MARKER, owner=admin),
        **matching_defaults(DocumentType),
    )
    tag = Tag.objects.create(
        **supported(Tag, name=MARKER, owner=admin, color="#334155"),
        **matching_defaults(Tag),
    )

    custom_field_kwargs = supported(CustomField, name=MARKER, owner=admin)
    if "data_type" in fields(CustomField):
        custom_field_kwargs["data_type"] = choice(CustomField, "data_type", ("text", "string"))
    custom_field = CustomField.objects.create(**custom_field_kwargs)

    workflow = Workflow.objects.create(**supported(Workflow, name=MARKER, owner=admin, order=9999, enabled=True))
    trigger_kwargs = supported(
        WorkflowTrigger,
        workflow=workflow,
        filter_filename=MARKER,
        filter_path="",
    )
    trigger_kwargs["type"] = choice(WorkflowTrigger, "type", ("consumption", "consume"))
    trigger = WorkflowTrigger.objects.create(**trigger_kwargs)

    assignment_value = "verified-native-workflow"
    action_kwargs = supported(
        WorkflowAction,
        workflow=workflow,
        order=0,
        assign_custom_fields=[{"field": custom_field.pk, "value": assignment_value}],
    )
    action_kwargs["type"] = choice(WorkflowAction, "type", ("assignment", "assign"))
    action = WorkflowAction.objects.create(**action_kwargs)

    # Some Paperless releases model workflow membership as M2M rather than FK.
    for relation, instance in (("triggers", trigger), ("actions", action)):
        manager = getattr(workflow, relation, None)
        if manager is not None and hasattr(manager, "add"):
            manager.add(instance)

    print("NATIVE_TAXONOMY_CONFIG=PASS")
    print("NATIVE_WORKFLOW_CONFIG=PASS")
    print("SYNTHETIC_OBJECTS_CREATED=6")


def custom_field_value(document):
    value = getattr(document, "custom_fields", None)
    if hasattr(value, "all"):
        rows = list(value.all())
        return any(getattr(row, "pk", None) == CustomField.objects.get(name=MARKER).pk for row in rows)
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return False
    if isinstance(value, list):
        expected = CustomField.objects.get(name=MARKER).pk
        for item in value:
            if isinstance(item, dict) and item.get("field") == expected and item.get("value") == "verified-native-workflow":
                return True
    return False


def verify():
    docs = list(marker_documents().prefetch_related("tags"))
    assert len(docs) == 1
    document = docs[0]
    assert MARKER in (document.content or "")
    assert document.correspondent_id == Correspondent.objects.get(name=MARKER).pk
    assert document.document_type_id == DocumentType.objects.get(name=MARKER).pk
    assert document.tags.filter(name=MARKER).exists()
    assert custom_field_value(document)
    print("NATIVE_OCR=PASS")
    print("NATIVE_CORRESPONDENT_MATCHER=PASS")
    print("NATIVE_DOCUMENT_TYPE_MATCHER=PASS")
    print("NATIVE_TAG_MATCHER=PASS")
    print("NATIVE_WORKFLOW_CUSTOM_FIELD=PASS")
    print(f"SYNTHETIC_DOCUMENT_ID={document.pk}")


def cleanup():
    # Delete only marker-scoped objects. The document goes first to release FKs.
    deleted_documents, _ = marker_documents().delete()
    Workflow.objects.filter(name=MARKER).delete()
    CustomField.objects.filter(name=MARKER).delete()
    Correspondent.objects.filter(name=MARKER).delete()
    DocumentType.objects.filter(name=MARKER).delete()
    Tag.objects.filter(name=MARKER).delete()

    # PaperlessTask is operational history rather than document authority, but a
    # canary must leave no marker/task residue. Restrict string matching to the
    # unique marker and the exact task ids recorded by the wrapper.
    task_ids = {value for value in os.environ.get("LIFEOS_P1_TASK_IDS", "").split(",") if value}
    try:
        PaperlessTask = model("PaperlessTask")
    except AssertionError:
        PaperlessTask = None
    deleted_tasks = 0
    if PaperlessTask is not None:
        query = Q()
        usable = False
        for field in PaperlessTask._meta.fields:
            if field.name == "task_id" and task_ids:
                query |= Q(task_id__in=task_ids)
                usable = True
            if field.get_internal_type() in {"CharField", "TextField"}:
                query |= Q(**{field.name + "__contains": MARKER})
                usable = True
        if usable:
            deleted_tasks, _ = PaperlessTask.objects.filter(query).delete()
    residual = counts()
    assert all(value == 0 for value in residual.values()), residual
    print(f"SYNTHETIC_DOCUMENTS_DELETED={deleted_documents}")
    print(f"SYNTHETIC_TASK_ROWS_DELETED={deleted_tasks}")
    print("SYNTHETIC_CONFIG_CLEANUP=PASS")


if MODE == "baseline":
    assert all(value == 0 for value in counts().values())
    print("MARKER_BASELINE=ZERO")
elif MODE == "configure":
    configure()
elif MODE == "verify":
    verify()
elif MODE == "cleanup":
    cleanup()
else:
    raise AssertionError("unsupported LIFEOS_P1_MODE")
