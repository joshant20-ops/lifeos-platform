from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/51f2b591d14f.sh"


def test_launcher_is_pi5_owned_bounded_and_non_force() -> None:
    text = LAUNCHER.read_text()

    assert text.startswith("#!/usr/bin/env bash\n")
    assert "set -Eeuo pipefail" in text
    assert '[[ "$(hostname)" == Docker ]]' in text
    assert 'timeout --signal=TERM --kill-after=15s "$TEST_TIMEOUT_SECONDS"' in text
    push = text.index('git -C "$REPO" push origin')
    refspec = text.index('"$candidate_sha:refs/heads/$BRANCH"', push)
    assert refspec > push
    assert "push --force" not in text
    assert "push -f" not in text
    assert "reset --hard" not in text


def test_launcher_runs_feature_acceptance_contracts_before_publication() -> None:
    text = LAUNCHER.read_text()

    acceptance = "tests/test_engineer_job_observability_acceptance.py"
    assert "readonly BRANCH=engineer-self-observability-v1" in text
    assert acceptance in text
    assert "git ls-files 'tests/*continuation*.py'" in text
    assert "python3 -m pytest -q" in text
    assert text.index("ACCEPTANCE_CONTRACTS=PASS") < text.index("git -C \"$REPO\" push origin")
    assert "PUBLICATION_RETRY=PASS" in text
    assert "RESULT=PASS" in text
