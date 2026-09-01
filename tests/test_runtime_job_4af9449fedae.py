from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/4af9449fedae.sh"


def test_launcher_is_pi5_only_noninteractive_and_timeout_bounded():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert "timeout --signal=TERM --kill-after=10s" in text
    assert "BatchMode=yes" in text
    assert "ConnectTimeout" in text


def test_report_is_private_complete_and_actionable():
    text = LAUNCHER.read_text()
    for excluded in ("paperless", "documents", "media", "secrets", "credentials"):
        assert f'"{excluded}"' in text
    assert 'git("ls-files", "-z")' in text
    assert "Complete findings inventory" in text
    assert "Detection class | Purpose | Frequency | Evidence | Recommended disposition" in text
    assert "Exact" in text and "Normalized" in text
    assert "Week 1" in text and "Week 4" in text
    assert "Expected outcomes" in text
    assert "AUDIT_EVIDENCE=PASS" in text
    assert "AUDIT_STATUS=PASS" in text
    assert "RESULT=PASS" in text
