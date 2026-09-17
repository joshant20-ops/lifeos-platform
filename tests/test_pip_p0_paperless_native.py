from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/lifeos-pip-p0-paperless-native-audit.sh"
DOC = ROOT / "docs/architecture/personal-information-processing-paperless-first.md"


def test_audit_covers_native_paperless_surface_without_private_output():
    text = SCRIPT.read_text()
    for marker in (
        "PAPERLESS_VERSION", "OCR_PRESENT", "ORIGINAL_FILES_PRESENT", "ARCHIVE_FILES_PRESENT",
        "CORRESPONDENTS_DEFINED", "DOCUMENT_TYPES_DEFINED", "TAGS_DEFINED", "CUSTOM_FIELDS_DEFINED",
        "MATCHERS_CONFIGURED", "AUTO_MATCHERS", "EXACT_DUPLICATE_GROUPS", "WORKFLOWS_DEFINED",
        "MAIL_ACCOUNTS_DEFINED", "FULL_TEXT_API_ROUTE", "NATIVE_ASSIGNMENT_PROVENANCE",
        "PRIVATE_FIELDS_EMITTED=NONE", "PAPERLESS_MUTATION=NONE",
    ):
        assert marker in text
    for forbidden in ("print(d.title", "print(d.content", "print(d.original_file", ".save(", ".delete(", ".update(", ".create("):
        assert forbidden not in text


def test_only_non_secret_configuration_is_reported():
    text = SCRIPT.read_text()
    assert "PAPERLESS_OCR_LANGUAGE" in text
    assert "PAPERLESS_CONSUMER_DELETE_DUPLICATES" in text
    for forbidden in ("PASSWORD", "TOKEN", "SECRET", "EMAIL_HOST_PASSWORD"):
        assert "PAPERLESS_" + forbidden not in text
    assert "CONFIG_SECRET_VALUES_EMITTED=NONE" in text


def test_architecture_maps_native_capability_before_custom_code():
    text = DOC.read_text()
    for phrase in (
        "Paperless-first", "Native capability", "Do not rebuild", "Tower Ollama is exception-only",
        "superseded", "assignment provenance", "cross-system",
    ):
        assert phrase in text
