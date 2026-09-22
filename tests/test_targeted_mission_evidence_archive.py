from pathlib import Path


EXPORTER = Path("governor/scripts/export-lifeos-job-records.sh").read_text()
WORKFLOW = Path(".github/workflows/lifeos-pa-mission-control.yml").read_text()


def test_exporter_supports_exact_job_filter_and_redacts_local_only_request():
    assert "LIFEOS_JOB_ID_FILTER" in EXPORTER
    assert "if job_filter and str(job.get('id') or '') != job_filter" in EXPORTER
    assert "[LOCAL-ONLY REQUEST REDACTED]" in EXPORTER
    assert 'git merge --ff-only origin/main' in EXPORTER
    assert "lifeos_jobs_checkout_dirty" in EXPORTER


def test_targeted_mission_requires_durable_pass_record_before_archive_pass():
    archive = WORKFLOW.split("- name: Verify archived disposition evidence", 1)[1]
    archive = archive.split("- name: Surface consolidated bundle", 1)[0]
    assert 'LIFEOS_JOB_ID_FILTER="$job_id" bash governor/scripts/export-lifeos-job-records.sh' in archive
    assert 'record="/home/joshan/lifeos-jobs/jobs/$job_id.json"' in archive
    assert 'assert record["status"] == "PASS"' in archive
    assert 'assert record["iterations"][0]["verdict"] == "PASS"' in archive
    assert 'assert record["request"] == "[LOCAL-ONLY REQUEST REDACTED]"' in archive
    assert 'cat-file -e "origin/main:jobs/$job_id.json"' in archive
    assert 'echo "ARCHIVED_JOB_RECORD=$job_id"' in archive
