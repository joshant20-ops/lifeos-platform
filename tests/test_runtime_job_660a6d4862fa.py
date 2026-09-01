from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "governor/runtime_jobs/660a6d4862fa.sh"


def test_activation_uses_fifo_control_queue_without_requiring_it_empty() -> None:
    script = LAUNCHER.read_text()

    assert "control_queue_not_empty" not in script
    assert '[[ ! -e "$CONTROL/$SCRIPT_REL" && ! -e "$MANIFEST" ]]' in script
    assert 'lifeos-job-publisher' in script
    assert 'jobs/pending/$JOB_ID.json' in script
    assert "publish_deadline=$((SECONDS + 900))" in script
    assert "activation_not_published_fifo_timeout" in script


def test_existing_control_result_must_be_pass() -> None:
    script = LAUNCHER.read_text()

    assert 'd.get("classification") == "PASS"' in script
    assert "prior_result_not_pass" in script
