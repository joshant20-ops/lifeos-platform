from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "governor/runtime_jobs/c00624b2b5b6.sh"


def test_migration_gate_is_bounded_and_repairs_checkout_safely():
    text = SCRIPT.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "git -C \"$PLATFORM\" fetch --prune origin main" in text
    assert "merge-base --is-ancestor \"$local_head\" \"$remote_head\"" in text
    assert "merge --ff-only \"$remote_head\"" in text
    assert "reset --hard" not in text


def test_migration_gate_accepts_compact_immutable_source_contract():
    text = SCRIPT.read_text()
    assert '("canonical_source", "immutable_source", "source")' in text
    assert '"source_path", "path"' in text
    assert '"source_sha256", "sha256"' in text
    assert "identity_output=$(python3" in text


def test_migration_gate_checks_import_object_without_freezing_energy_forever():
    text = SCRIPT.read_text()
    assert 'rev-parse "$MIGRATION_COMMIT:energy"' in text
    assert 'merge-base --is-ancestor "$MIGRATION_COMMIT" HEAD' in text
    assert "canonical_energy_tree_drift" not in text


def test_migration_gate_emits_iteration_contract():
    text = SCRIPT.read_text()
    for field in (
        "ISSUE_VALIDITY=",
        "LIFEOS_WORK_STATE=",
        "BARRIER=",
        "NEXT_AUTONOMOUS_ACTION=",
        "DISCOVERED_ISSUES_JSON_B64=",
        "RESULT=",
        "TESTS=",
        "NEXT_RUNTIME_CHECK=",
    ):
        assert field in text
