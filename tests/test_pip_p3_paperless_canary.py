from pathlib import Path

PY = Path('scripts/lifeos-pip-p3-paperless-canary.py').read_text()
SH = Path('scripts/lifeos-pip-p3-paperless-canary.sh').read_text()


def test_only_p2_safe_dimensions_are_mutable():
    assert 'SAFE_DIMENSIONS = (("DOCUMENT_TYPE", DocumentType, False), ("TAG", Tag, True))' in PY
    assert 'EXPECTED_SAFE = {"DOCUMENT_TYPE": 2, "TAG": 2}' in PY
    assert 'Correspondent.objects' not in PY
    assert 'StoragePath.objects' not in PY


def test_canary_is_reversible_and_does_not_touch_documents():
    assert 'def reversible_matchers' in PY
    assert 'finally:' in PY
    assert 'obj.save(update_fields=list(fields))' in PY
    assert 'Document.objects.update' not in PY
    assert '.delete(' not in PY
    assert 'P3_DOCUMENT_METADATA_MUTATION=NONE' in PY


def test_no_ai_cloud_or_private_output_surface():
    assert 'P3_TOWER_AI_USED=NO' in PY
    assert 'P3_PRIVATE_FIELDS_EMITTED=NONE' in PY
    assert 'obj.name' not in [line.strip() for line in PY.splitlines() if line.strip().startswith('print(')]
    assert 'requests.' not in PY
    assert 'http://' not in PY and 'https://' not in PY


def test_wrapper_requires_rollback_and_all_safety_markers():
    for marker in ('P3_MATCHER_ROLLBACK=PASS', 'P3_DOCUMENT_METADATA_MUTATION=NONE', 'P3_REVIEW_CANDIDATES_MUTATED=NO', 'P3_CANARY=PASS', 'RESULT=PASS'):
        assert marker in SH
