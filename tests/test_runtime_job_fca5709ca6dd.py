from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/fca5709ca6dd.sh"


def test_engineer_audit_launcher_is_safe_and_bounded():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "BatchMode=yes" in text
    assert "ConnectTimeout" in text


def test_audit_has_privacy_scope_and_actionable_report_contract():
    text = LAUNCHER.read_text()
    for excluded in ("paperless", "documents", "media", "secrets"):
        assert f'"{excluded}"' in text
    assert 'git("ls-files", "-z")' in text
    assert "Exact duplicate groups" in text
    assert "Purpose | Frequency | Evidence" in text
    assert "Week 1" in text and "Week 4" in text
    assert "Expected outcomes" in text
    assert "AUDIT_EVIDENCE=PASS" in text
    assert "RESULT=PASS" in text
