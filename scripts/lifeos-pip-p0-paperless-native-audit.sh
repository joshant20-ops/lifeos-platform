#!/usr/bin/env bash
set -Eeuo pipefail

container="${LIFEOS_PAPERLESS_CONTAINER:-paperless-paperless-1}"
docker inspect -f '{{.State.Running}}' "$container" 2>/dev/null | grep -qx true || {
  echo 'PAPERLESS_RUNTIME=UNAVAILABLE'; echo 'RESULT=BLOCKED'; exit 2;
}

image="$(docker inspect -f '{{.Config.Image}}' "$container")"
printf 'PAPERLESS_IMAGE=%s\n' "$image"
printf 'PAPERLESS_IMAGE_ID=%s\n' "$(docker inspect -f '{{.Image}}' "$container")"
consume_mount="$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/usr/src/paperless/consume"}}present{{end}}{{end}}' "$container")"
printf 'CONSUME_DIRECTORY=%s\n' "${consume_mount:-absent}"

docker exec -i "$container" python3 manage.py shell <<'PY'
from collections import Counter
import importlib.metadata
import json
from django.apps import apps
from django.urls import resolve
from documents.models import Document, Correspondent, DocumentType, Tag, StoragePath


def model_count(name):
    for model in apps.get_models():
        if model.__name__ == name:
            return model.objects.count()
    return "UNAVAILABLE"


def assigned_custom_fields():
    try:
        field = Document._meta.get_field("custom_fields")
        if field.many_to_many:
            return Document.objects.filter(custom_fields__isnull=False).distinct().count()
        return Document.objects.exclude(custom_fields=[]).count()
    except Exception:
        return "UNAVAILABLE"


def nonempty_file_field_count(kind):
    candidates = {
        "original": ("original_filename", "filename", "original_checksum", "checksum"),
        "archive": ("archive_filename", "archive_checksum"),
    }[kind]
    models = [Document]
    for model in apps.get_models():
        if model.__name__ == "DocumentVersion":
            models.insert(0, model)
    for model in models:
        names = {field.name for field in model._meta.fields}
        for name in candidates:
            if name in names:
                query = model.objects.exclude(**{name + "__isnull": True})
                field = model._meta.get_field(name)
                if getattr(field, "empty_strings_allowed", False):
                    query = query.exclude(**{name: ""})
                return query.count()
    return "UNAVAILABLE"


def match_counts(model):
    configured = auto = 0
    try:
        field = model._meta.get_field("matching_algorithm")
        choices = dict(field.flatchoices)
        auto_values = {value for value, label in choices.items() if "auto" in str(label).casefold()}
        for row in model.objects.only("matching_algorithm", "match"):
            algorithm = getattr(row, "matching_algorithm", None)
            if algorithm not in (None, 0) or bool((getattr(row, "match", "") or "").strip()):
                configured += 1
            if algorithm in auto_values:
                auto += 1
    except Exception:
        return "UNAVAILABLE", "UNAVAILABLE"
    return configured, auto


documents = list(Document.objects.order_by("pk").prefetch_related("tags"))
checksum_counts = Counter((getattr(d, "checksum", "") or "") for d in documents)
duplicate_groups = sum(value > 1 for key, value in checksum_counts.items() if key)
duplicate_documents = sum(value for key, value in checksum_counts.items() if key and value > 1)

version = "UNAVAILABLE"
try:
    from paperless.version import __full_version_str__
    version = str(__full_version_str__)
except Exception:
    pass
for distribution in ("paperless-ngx", "paperless"):
    if version != "UNAVAILABLE":
        break
    try:
        version = importlib.metadata.version(distribution)
        break
    except importlib.metadata.PackageNotFoundError:
        pass

try:
    resolve("/api/documents/")
    api_route = "AVAILABLE"
except Exception:
    api_route = "UNAVAILABLE"

metrics = {
    "PAPERLESS_VERSION": version,
    "DOCUMENTS": len(documents),
    "OCR_PRESENT": sum(bool((getattr(d, "content", "") or "").strip()) for d in documents),
    "OCR_MISSING": sum(not bool((getattr(d, "content", "") or "").strip()) for d in documents),
    "ORIGINAL_FILES_PRESENT": nonempty_file_field_count("original"),
    "ARCHIVE_FILES_PRESENT": nonempty_file_field_count("archive"),
    "CORRESPONDENTS_DEFINED": Correspondent.objects.count(),
    "DOCUMENTS_WITH_CORRESPONDENT": sum(d.correspondent_id is not None for d in documents),
    "DOCUMENT_TYPES_DEFINED": DocumentType.objects.count(),
    "DOCUMENTS_WITH_TYPE": sum(d.document_type_id is not None for d in documents),
    "TAGS_DEFINED": Tag.objects.count(),
    "DOCUMENTS_WITH_TAGS": sum(d.tags.exists() for d in documents),
    "STORAGE_PATHS_DEFINED": StoragePath.objects.count(),
    "CUSTOM_FIELDS_DEFINED": model_count("CustomField"),
    "DOCUMENTS_WITH_CUSTOM_FIELDS": assigned_custom_fields(),
    "SAVED_VIEWS_DEFINED": model_count("SavedView"),
    "WORKFLOWS_DEFINED": model_count("Workflow"),
    "WORKFLOW_TRIGGERS_DEFINED": model_count("WorkflowTrigger"),
    "WORKFLOW_ACTIONS_DEFINED": model_count("WorkflowAction"),
    "MAIL_ACCOUNTS_DEFINED": model_count("MailAccount"),
    "MAIL_RULES_DEFINED": model_count("MailRule"),
    "PROCESSED_MAIL_RECORDS": model_count("ProcessedMail"),
    "EXACT_DUPLICATE_GROUPS": duplicate_groups,
    "EXACT_DUPLICATE_DOCUMENTS": duplicate_documents,
    "FULL_TEXT_API_ROUTE": api_route,
}
for prefix, model in (("CORRESPONDENT", Correspondent), ("DOCUMENT_TYPE", DocumentType), ("TAG", Tag), ("STORAGE_PATH", StoragePath)):
    configured, auto = match_counts(model)
    metrics[prefix + "_MATCHERS_CONFIGURED"] = configured
    metrics[prefix + "_AUTO_MATCHERS"] = auto

for key, value in metrics.items():
    print(f"{key}={value}")
print("NATIVE_ASSIGNMENT_PROVENANCE=UNAVAILABLE")
print("PRIVATE_FIELDS_EMITTED=NONE")
print("PAPERLESS_MUTATION=NONE")
print("PRIVACY_LOCAL_ONLY=PASS")
print("RESULT=PASS")
PY

for key in PAPERLESS_OCR_LANGUAGE PAPERLESS_OCR_MODE PAPERLESS_ARCHIVE_FILE_GENERATION PAPERLESS_CONSUMER_DELETE_DUPLICATES PAPERLESS_CONSUMER_RECURSIVE PAPERLESS_CONSUMER_SUBDIRS_AS_TAGS PAPERLESS_CONSUMER_POLLING; do
  value="$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$container" | awk -F= -v key="$key" '$1==key {print substr($0,length(key)+2)}' | tail -1)"
  if [[ -n "$value" ]]; then printf 'CONFIG_%s=%s\n' "$key" "$value"; else printf 'CONFIG_%s=DEFAULT_OR_UNSET\n' "$key"; fi
done
echo 'CONFIG_SECRET_VALUES_EMITTED=NONE'
