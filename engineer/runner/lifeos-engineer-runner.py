#!/usr/bin/env python3
import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timezone

REPO = pathlib.Path(os.environ.get("LIFEOS_PLATFORM_REPO", "/home/joshan/workspace/lifeos-platform"))
BASE = REPO / "engineer"
PENDING = BASE / "jobs/pending"
ARCHIVE = BASE / "jobs/archive"
RESULTS = BASE / "results"
STATE = pathlib.Path("/home/joshan/.local/state/lifeos-engineer-runner")
LOCK = STATE / "runner.lock"
TARGET = "engineer"
MAX_TIMEOUT = 900

for p in (PENDING, ARCHIVE, RESULTS, STATE):
    p.mkdir(parents=True, exist_ok=True)


def now():
    return datetime.now(timezone.utc).astimezone().isoformat()


def run(args, *, check=True, capture=False, timeout=None):
    p = subprocess.run(
        args,
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
        timeout=timeout,
    )
    if check and p.returncode != 0:
        raise RuntimeError(f"command failed rc={p.returncode}: {' '.join(args)}")
    return p


def git(*args, check=True, capture=False):
    return run(["git", *args], check=check, capture=capture)


def sync_repo():
    git("fetch", "origin", "main")
    local = git("rev-parse", "HEAD", capture=True).stdout.strip()
    remote = git("rev-parse", "origin/main", capture=True).stdout.strip()
    if local == remote:
        return
    if git("merge-base", "--is-ancestor", local, remote, check=False).returncode != 0:
        raise RuntimeError("local repository is not a fast-forward ancestor of origin/main")
    git("merge", "--ff-only", "origin/main")


def sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(path):
    d = json.loads(path.read_text())
    required = {
        "schema_version", "job_id", "target", "job_type", "script",
        "script_sha256", "timeout_seconds", "created_by", "description",
    }
    missing = required - set(d)
    if missing:
        raise RuntimeError("missing manifest fields: " + ",".join(sorted(missing)))
    if d["schema_version"] != 1:
        raise RuntimeError("unsupported schema_version")
    if d["target"] != TARGET:
        raise RuntimeError(f"wrong target: {d['target']!r}")
    if d["job_type"] not in {"diagnostic", "change", "ai"}:
        raise RuntimeError("unsupported job_type")
    if not isinstance(d["timeout_seconds"], int) or not 1 <= d["timeout_seconds"] <= MAX_TIMEOUT:
        raise RuntimeError("timeout_seconds out of range")
    rel = pathlib.PurePosixPath(d["script"])
    if rel.is_absolute() or ".." in rel.parts or rel.parts[:3] != ("engineer", "jobs", "scripts"):
        raise RuntimeError("script path outside engineer/jobs/scripts")
    script = (REPO / rel).resolve(strict=True)
    allowed = (BASE / "jobs/scripts").resolve()
    try:
        script.relative_to(allowed)
    except ValueError:
        raise RuntimeError("script escaped allowed root")
    if not script.is_file():
        raise RuntimeError("script is not a regular file")
    if sha256(script) != d["script_sha256"]:
        raise RuntimeError("script sha256 mismatch")
    return d, script


def publish_result(manifest_path, data, output, rc, started, finished, classification):
    job_id = data["job_id"]
    log_path = RESULTS / f"{job_id}.log"
    json_path = RESULTS / f"{job_id}.json"
    archive_path = ARCHIVE / manifest_path.name
    log_path.write_text(output)
    json_path.write_text(json.dumps({
        "schema_version": 1,
        "job_id": job_id,
        "job_type": data["job_type"],
        "target": TARGET,
        "host": socket.gethostname(),
        "started_at": started,
        "finished_at": finished,
        "exit_code": rc,
        "classification": classification,
        "output_path": str(log_path.relative_to(REPO)),
        "script": data["script"],
        "script_sha256": data["script_sha256"],
        "created_by": data["created_by"],
    }, indent=2) + "\n")
    shutil.move(str(manifest_path), str(archive_path))

    git("add", "--", str(log_path.relative_to(REPO)), str(json_path.relative_to(REPO)), str(archive_path.relative_to(REPO)))
    git("add", "-u", "--", str(manifest_path.relative_to(REPO)))
    git("-c", "user.name=LifeOS Engineer Runner", "-c", "user.email=lifeos-engineer-runner@localhost",
        "commit", "-m", f"result: engineer {job_id} {classification}")
    git("fetch", "origin", "main")
    git("rebase", "origin/main")
    git("push", "origin", "main")


def main():
    with LOCK.open("w") as lock_handle:
        try:
            fcntl.flock(lock_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print("Another Engineer runner is active")
            return 0

        sync_repo()
        manifests = sorted(PENDING.glob("*.json"))
        if not manifests:
            print("No pending Engineer jobs")
            return 0

        manifest = manifests[0]
        started = now()
        try:
            data, script = validate(manifest)
            proc = run(["bash", str(script)], check=False, capture=True, timeout=data["timeout_seconds"])
            rc = proc.returncode
            output = proc.stdout or ""
            classification = "PASS" if rc == 0 else "FAIL"
        except subprocess.TimeoutExpired as exc:
            data = json.loads(manifest.read_text())
            rc = 124
            output = (exc.stdout or "") + "\nTIMEOUT\n"
            classification = "TIMEOUT"
        except Exception as exc:
            try:
                data = json.loads(manifest.read_text())
            except Exception:
                data = {"job_id": manifest.stem, "job_type": "unknown", "script": "", "script_sha256": "", "created_by": "unknown"}
            rc = 125
            output = f"REJECTED: {exc}\n"
            classification = "REJECTED"

        finished = now()
        publish_result(manifest, data, output, rc, started, finished, classification)
        print(f"{data['job_id']}: {classification}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
