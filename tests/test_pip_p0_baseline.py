from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/lifeos-pip-p0-paperless-inventory.sh"
WORKFLOW = ROOT / ".github/workflows/lifeos-pip-p0-baseline.yml"
ARCHITECTURE = ROOT / "docs/architecture/personal-information-processing.md"


def test_inventory_is_aggregate_and_read_only():
    text = SCRIPT.read_text()
    assert "Document.objects.order_by" in text
    assert '"PAPERLESS_MUTATION": "NONE"' in text
    assert '"PRIVATE_FIELDS_EMITTED": "NONE"' in text
    for forbidden in (
        "document.save(", "Document.objects.update(", "Document.objects.create(",
        "Document.objects.filter(", "bulk_create(", "post_document",
        "print(document.title", "print(document.content", "get_filename(",
    ):
        assert forbidden not in text


def test_inventory_covers_required_p0_aggregate_dimensions():
    text = SCRIPT.read_text()
    for marker in (
        "PAPERLESS_DOCUMENTS", "CORRESPONDENTS_DEFINED",
        "DOCUMENTS_MISSING_CORRESPONDENT", "DOCUMENT_TYPES_DEFINED",
        "DOCUMENTS_MISSING_TYPE", "TAGS_DEFINED", "DOCUMENTS_UNTAGGED",
        "OCR_PRESENT", "OCR_MISSING", "DOCUMENT_YEAR_BUCKETS",
        "EXACT_DUPLICATE_GROUPS", "PROBABLE_SAME_TITLE_GROUPS",
        "LIKELY_FINANCE_PROPERTY_DOCUMENTS", "PAPERLESS_MAIL_ACCOUNTS",
        "PAPERLESS_MAIL_RULES", "PAPERLESS_METADATA_STABLE",
    ):
        assert marker in text


def test_workflow_uses_canonical_checkout_and_proves_no_mutation():
    text = WORKFLOW.read_text()
    assert "merge --ff-only origin/main" in text
    assert "status --porcelain" in text
    assert "PAPERLESS_MUTATION=NONE" in text
    assert "PRIVATE_FIELDS_EMITTED=NONE" in text
    assert "pull_request" not in text


def test_architecture_preserves_authorities_and_local_ai_role():
    text = ARCHITECTURE.read_text()
    for required in (
        "Gmail remains authoritative", "Paperless remains authoritative",
        "accounting product remains authoritative", "Tower Ollama",
        "does not design the architecture", "must not perform authoritative mutations",
        "P0", "read-only",
    ):
        assert required in text
