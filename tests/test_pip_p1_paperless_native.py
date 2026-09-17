from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHELL = (ROOT / "scripts/lifeos-pip-p1-paperless-native-canary.sh").read_text()
HELPER = (ROOT / "scripts/lifeos-pip-p1-paperless-native-canary.py").read_text()
WORKFLOW = (ROOT / ".github/workflows/lifeos-pip-p1-paperless-native.yml").read_text()


def test_canary_uses_paperless_native_capabilities_and_rest_ingestion():
    for evidence in (
        "AUTHENTICATED_REST_INGESTION=PASS",
        "NATIVE_OCR=PASS",
        "NATIVE_CORRESPONDENT_MATCHER=PASS",
        "NATIVE_DOCUMENT_TYPE_MATCHER=PASS",
        "NATIVE_TAG_MATCHER=PASS",
        "NATIVE_WORKFLOW_CUSTOM_FIELD=PASS",
        "NATIVE_FULL_TEXT_SEARCH=PASS",
        "NATIVE_EXACT_DUPLICATE_NO_SECOND_DOCUMENT=PASS",
    ):
        assert evidence in SHELL + HELPER
    assert "/api/documents/post_document/" in SHELL
    assert "assign_custom_fields_values={custom_field.pk: assignment_value}" in HELPER
    assert "action.assign_custom_fields.set([custom_field])" in HELPER
    assert "assign_custom_fields=[" not in HELPER


def test_canary_is_unique_bounded_and_always_cleans_up():
    assert "uuid.uuid4().hex" in SHELL
    assert "trap cleanup EXIT" in SHELL
    assert "marker_documents().delete()" in HELPER
    for native_object in ("Workflow", "CustomField", "Correspondent", "DocumentType", "Tag"):
        assert f'{native_object}.objects.filter(name=MARKER).delete()' in HELPER
    assert "MARKER_SEARCH_BEFORE=0" in SHELL
    assert "MARKER_SEARCH_AFTER=0" in SHELL


def test_canary_cannot_query_or_mutate_unmarked_production_documents():
    assert "Document.objects.filter(title=MARKER)" in HELPER
    assert "Document.objects.all" not in HELPER
    assert "Document.objects.exclude" not in HELPER
    assert "PRODUCTION_DOCUMENT_MUTATION=NONE" in SHELL
    assert "PRIVATE_FIELDS_EMITTED=NONE" in SHELL
    assert "LIFEOS_CLASSIFIER_BUILT=NO" in SHELL
    assert "TOWER_AI_USED=NO" in SHELL


def test_workflow_uses_governed_credential_and_serializes_mutation():
    assert "LoadCredential=paperless-api-token:/etc/lifeos/secrets/paperless-api-token" in WORKFLOW
    assert "lifeos-pip-paperless-native-mutation" in WORKFLOW
    assert "cancel-in-progress: false" in WORKFLOW
    assert "systemd-run" in WORKFLOW
    assert "CANONICAL_CLEAN=PASS" in WORKFLOW


def test_existing_native_mail_acceptance_is_reused_not_reimplemented():
    assert "imaplib" not in SHELL + HELPER
    assert "gmail" not in SHELL.casefold()
    assert (ROOT / ".github/workflows/lifeos-paperless-native-mail-acceptance.yml").exists()
