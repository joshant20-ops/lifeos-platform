from pathlib import Path


RUNNER = Path("governor/scripts/lifeos-pa-mission").read_text()


def test_targeted_failure_diagnostic_surfaces_only_bounded_marker_allowlist():
    assert '"safe_markers": safe_markers' in RUNNER
    assert "last_iteration.get(\"evidence\")" in RUNNER
    assert "OPENHANDS_SDK_ERROR" in RUNNER
    assert "OPENHANDS_SDK_TOOL_EVENTS" in RUNNER
    assert "OPENHANDS_SDK_EVENTS_ON_EXCEPTION" in RUNNER
    assert "OPENHANDS_SDK_ERROR_EVENTS_ON_EXCEPTION" in RUNNER
    assert "OPENHANDS_SDK_TOOL_EVENTS_ON_EXCEPTION" in RUNNER
    assert "OPENHANDS_UPSTREAM_HTTP_STATUS" in RUNNER
    assert "OPENHANDS_UPSTREAM_ERROR_CODE" in RUNNER
    assert "OPENHANDS_PROVIDER_HTTP_STATUS" in RUNNER
    assert "OPENHANDS_UPSTREAM_CLASS" in RUNNER
    assert "OPENHANDS_UPSTREAM_CATEGORY" in RUNNER
    assert "OPENHANDS_WORKTREE_PATCH_BYTES" in RUNNER
    assert "LOCAL_BUILDER_ATTEMPT_RC" in RUNNER
    assert "CANONICAL_ASSERTION_" in RUNNER
    assert "list(dict.fromkeys(safe_markers))[:24]" in RUNNER


def test_targeted_failure_diagnostic_does_not_emit_raw_evidence():
    diagnostic = RUNNER.split("safe_markers = []", 1)[1].split(
        'print("TARGETED_ISSUE_DIAGNOSTIC="', 1
    )[0]
    assert '"evidence":' not in diagnostic
    assert "BUILD_EVIDENCE" not in diagnostic
    assert "HANDOFF_PATCH_B64" not in diagnostic
