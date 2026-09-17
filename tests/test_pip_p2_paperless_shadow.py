from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = (ROOT / "scripts/lifeos-pip-p2-paperless-shadow.py").read_text()
SHELL = (ROOT / "scripts/lifeos-pip-p2-paperless-shadow.sh").read_text()
WORKFLOW = (ROOT / ".github/workflows/lifeos-pip-p2-paperless-shadow.yml").read_text()
DOC = (ROOT / "docs/architecture/personal-information-processing-paperless-first.md").read_text()


def test_shadow_invokes_native_paperless_matching_instead_of_reimplementing_it():
    assert "from documents.matching import matches" in HELPER
    assert "matches(rule, document)" in HELPER
    assert "load_classifier()" in HELPER
    assert "LIFEOS_CLASSIFIER_BUILT=NO" in HELPER
    for forbidden in ("fuzz.partial_ratio", "safe_regex_search", "re.search(", "ollama", "openai"):
        assert forbidden not in HELPER.casefold()


def test_sample_is_stable_bounded_and_aggregate_only():
    assert "SAMPLE_LIMIT = 192" in HELPER
    assert "SAMPLE_PER_STRATUM = 48" in HELPER
    assert "sha256(private_stable_value)" in HELPER
    assert "SAMPLE_METHOD=stable_hash_stratified_metadata_coverage" in HELPER
    for forbidden in (
        "document.title", "original_file", "document.content)", "print(document.pk",
        "print(rule.name", "print(rule.match", "SYNTHETIC_DOCUMENT_ID",
    ):
        assert forbidden not in HELPER
    assert "PRIVATE_FIELDS_EMITTED=NONE" in HELPER


def test_evaluator_measures_required_native_outcomes_and_duplicate_policy():
    for marker in (
        "NATIVE_EXPLICIT_ANY_COVERAGE_DOCUMENTS", "NATIVE_UNMATCHED_DOCUMENTS",
        "NATIVE_AMBIGUOUS_DOCUMENTS", "NATIVE_CONFLICTING_DOCUMENTS",
        "FALSE_OVERLAP_RISK_BROAD_RULES", "CANDIDATE_{prefix}_RULES_PRESERVE",
        "CANDIDATE_{prefix}_RULES_REVIEW", "EXACT_DUPLICATE_GROUPS",
        "EXACT_DUPLICATE_REJECT_CURRENT_CORPUS_IMPACT", "EXACT_DUPLICATE_AUTHORITY=PAPERLESS",
        "CANDIDATE_WORKFLOWS_PRESERVE", "CANDIDATE_WORKFLOWS_REVIEW", "CANDIDATE_WORKFLOWS_NEW",
    ):
        assert marker in HELPER


def test_no_production_write_or_local_ai_surface_exists():
    for forbidden in (
        ".save(", ".delete(", "objects.update(", "objects.create(",
        "post_document", "requests.", "curl ",
    ):
        assert forbidden not in HELPER
    assert "PRODUCTION_DOCUMENT_MUTATION=NONE" in HELPER
    assert "PRODUCTION_METADATA_MUTATION=NONE" in HELPER
    assert "TOWER_AI_USED=NO" in HELPER


def test_wrapper_proves_identical_rerun_and_workflow_preserves_checkout():
    assert SHELL.count("run_shadow >") == 2
    assert "cmp -s" in SHELL
    assert "IDEMPOTENT_IDENTICAL_RERUN=PASS" in SHELL
    assert "status --porcelain" in WORKFLOW
    assert "CANONICAL_CLEAN=PASS" in WORKFLOW
    assert "PRIVATE_FIELDS_EMITTED=NONE" in WORKFLOW


def test_architecture_requires_measured_gap_before_custom_component():
    for phrase in (
        "Revised P2", "native Paperless rules", "demonstrated native capability gap",
        "Tower AI is prohibited", "production metadata writes are prohibited",
    ):
        assert phrase in DOC
