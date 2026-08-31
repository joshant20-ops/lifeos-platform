from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/86cdbb0999a1.sh"


def test_launcher_is_bounded_and_delegates_reversible_runtime() -> None:
    text = LAUNCHER.read_text()

    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -euo pipefail" in text
    assert 'RUNTIME="$REPO/governor/runtime_jobs/feb1efaecf51.sh"' in text
    assert "timeout --signal=TERM" in text
    assert 'env LIFEOS_RUNTIME_JOB_ID="$JOB_ID" "$RUNTIME"' in text


def test_launcher_verifies_requested_url_and_reports_navigation() -> None:
    text = LAUNCHER.read_text()

    assert "readonly ENGINEER_URL=http://192.168.0.203:8792/" in text
    assert 'curl -fsSI --max-time 10 "$ENGINEER_URL"' in text
    assert "FINAL_NAVIGATION_PATH=Home Assistant sidebar > LifeOS Engineer" in text
    assert 'printf \'RESULT=PASS job=%s\\n\' "$JOB_ID"' in text
