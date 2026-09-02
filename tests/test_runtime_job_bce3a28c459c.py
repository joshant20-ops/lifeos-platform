import json
import os
from pathlib import Path
import re
import subprocess


LAUNCHER = Path(__file__).parents[1] / "governor/runtime_jobs/bce3a28c459c.sh"


def run_manifest_validator(tmp_path, manifest, *, optimized=False):
    text = LAUNCHER.read_text()
    match = re.search(
        r"identity=\$\(python3 - \"\$manifest\" <<'PY'\n(.*?)\nPY\n\)",
        text,
        re.DOTALL,
    )
    assert match, "manifest validator heredoc not found"
    manifest_path = tmp_path / "0019-two-repo-migration-gate.json"
    manifest_path.write_text(json.dumps(manifest))
    env = os.environ.copy()
    if optimized:
        env["PYTHONOPTIMIZE"] = "1"
    return subprocess.run(
        ["python3", "-", str(manifest_path)],
        input=match.group(1),
        text=True,
        capture_output=True,
        env=env,
        check=False,
    )


def test_launcher_is_safe_bounded_and_fail_closed():
    text = LAUNCHER.read_text()
    assert text.startswith("#!/usr/bin/env bash\nset -Eeuo pipefail")
    assert 'timeout --signal=TERM --kill-after=10s' in text
    assert 'merge --ff-only "$remote_head"' in text
    assert "reset --hard" not in text
    assert "DISCOVERED_ISSUES_JSON_B64=none" in text
    assert "RESULT=$5" in text


def test_manifest_parser_supports_queued_split_repository_contract():
    text = LAUNCHER.read_text()
    assert 'repo = value(data, repo_keys)' in text
    assert 'commit = value(source,' in text
    assert 'path = value(source,' in text
    assert 'digest = value(source,' in text
    assert 'if len(sources) != 1:' in text


def test_manifest_validator_accepts_split_repository_contract(tmp_path):
    manifest = {
        "canonical_repository": "git@github.com:joshant20-ops/lifeos-platform.git",
        "immutable_source": {
            "commit": "a" * 40,
            "path": "energy/scripts/queued/job.sh",
            "sha256": "b" * 64,
        },
    }
    result = run_manifest_validator(tmp_path, manifest)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "a" * 40,
        "energy/scripts/queued/job.sh",
        "b" * 64,
    ]


def test_manifest_validator_rejects_wrong_repository_when_python_optimized(tmp_path):
    manifest = {
        "repository": "git@github.com:joshant20-ops/lifeos-pi-control.git",
        "source": {
            "source_commit": "a" * 40,
            "source_path": "energy/scripts/queued/job.sh",
            "source_sha256": "b" * 64,
        },
    }
    result = run_manifest_validator(tmp_path, manifest, optimized=True)
    assert result.returncode != 0
    assert "wrong canonical repository" in result.stderr


def test_launcher_pins_migration_identity_and_waits_for_relay_pass():
    text = LAUNCHER.read_text()
    assert "3a93d6e9e99fe04f62f8a452b688639cefb05b82" in text
    assert "d9a4d225cd16663ec1ed5f0f909b615e4c1f9b91" in text
    assert 'result.get("classification") == "PASS"' in text
    assert "PI_RELAY_RESULT=PASS" in text
