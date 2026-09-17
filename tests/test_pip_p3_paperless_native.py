from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / "scripts/lifeos-pip-p3-paperless-native-config.py").read_text()
SHELL = (ROOT / "scripts/lifeos-pip-p3-paperless-native-config.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/lifeos-pip-p3-paperless-native.yml").read_text()
DOC = (ROOT / "docs/architecture/personal-information-processing-paperless-first.md").read_text()

def test_p3_uses_native_matching_not_custom_or_ai_classification():
    assert "from documents.matching import matches" in HELPER
    assert "MatchingModel.MATCH_LITERAL" in HELPER
    for forbidden in ("ollama", "openai", "requests.", "fuzz.", "re.search("):
        assert forbidden not in HELPER.casefold()

def test_activation_is_bounded_conflict_checked_and_transactional():
    for phrase in ("with transaction.atomic()", "0 < len(matched) < broad_threshold", "not ambiguous and not conflicting", "ambiguity == 0", "conflicts == 0", "item.save(update_fields="):
        assert phrase in HELPER
    assert 'LIFEOS_P3_MODE", "apply") == "rollback"' in HELPER
    assert "NATIVE_CONFIGURATION_ROLLBACK=PASS" in HELPER
    assert "ROLLBACK_ARTIFACT=" in HELPER

def test_documents_are_not_mutated_and_tags_are_deferred():
    assert "PRODUCTION_DOCUMENT_MUTATION=NONE" in HELPER
    assert "TAG_RULES_DEFERRED_OVERLAP_RISK" in HELPER
    for forbidden in ("document.save(", "document.delete(", "document.tags.add", "Document.objects.update"):
        assert forbidden not in HELPER

def test_private_safe_idempotent_output():
    for forbidden in ("print(item.name", "print(item.match", "print(document.pk", "document.title"):
        assert forbidden not in HELPER
    assert "PRIVATE_FIELDS_EMITTED=NONE" in HELPER
    assert "DOCUMENT_TYPE_RULES_ACTIVATED=0" in SHELL
    assert "NATIVE_CONFIGURATION_IDEMPOTENT=PASS" in SHELL

def test_governed_workflow_preserves_checkout():
    assert "status --porcelain" in WORKFLOW
    assert "CANONICAL_CLEAN=PASS" in WORKFLOW

def test_architecture_redefines_p3_from_evidence():
    for phrase in ("Revised P3", "Paperless-native configuration", "Tag candidates remain deferred", "No LifeOS semantic processor", "P4 must be redesigned"):
        assert phrase in DOC
