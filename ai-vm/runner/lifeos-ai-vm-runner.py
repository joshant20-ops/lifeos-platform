#!/usr/bin/env python3

import fcntl
import hashlib
import json
import os
import pathlib
import shutil
import socket
import subprocess
from datetime import datetime, timezone

REPO = pathlib.Path(os.environ.get("LIFEOS_CONTROL_REPO", "/home/joshan/lifeos-pi-control"))
IDENTITY = pathlib.Path("/etc/lifeos-control/identity.json")
STATE = pathlib.Path.home()/".local/state/lifeos-ai-vm"
LOCK = STATE/"runner.lock"
STATE.mkdir(parents=True, exist_ok=True)

with LOCK.open("w") as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another AI VM runner is active")
        raise SystemExit(0)

    identity = json.loads(IDENTITY.read_text())
    target = identity["target_id"]
    aliases = set(identity.get("aliases", []))
    accepted = {target, *aliases}

    def run(args, **kwargs):
        return subprocess.run(args, cwd=REPO, text=True, **kwargs)

    def sync_repo():
        run(["git", "fetch", "origin", "main"], check=True)
        local = run(["git", "rev-parse", "HEAD"], capture_output=True, check=True).stdout.strip()
        remote = run(["git", "rev-parse", "origin/main"], capture_output=True, check=True).stdout.strip()
        anc = run(["git", "merge-base", "--is-ancestor", local, remote], check=False)
        if anc.returncode != 0:
            raise RuntimeError("non-fast-forward remote history")
        run(["git", "merge", "--ff-only", "origin/main"], check=True)

    def sha256(path):
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024*1024), b""):
                h.update(chunk)
        return h.hexdigest()

    def completed(job_id):
        return (REPO/"results"/f"{job_id}.json").is_file()

    def select_job():
        pending = REPO/"jobs/pending"
        for path in sorted(pending.glob("*.json")):
            try:
                data = json.loads(path.read_text())
            except Exception:
                continue
            if data.get("target") not in accepted:
                continue
            if data.get("job_type") != "diagnostic":
                continue
            job_id = data.get("job_id")
            if isinstance(job_id, str) and completed(job_id):
                print(f"Skipping stale completed manifest: {job_id}")
                continue
            return path, data
        return None, None

    def publish(job_path, data, log_path, rc):
        job_id = data["job_id"]
        result = {
            "job_id": job_id,
            "target": target,
            "host": socket.gethostname(),
            "completed_at": datetime.now(timezone.utc).astimezone().isoformat(),
            "exit_code": rc,
            "classification": "PASS" if rc == 0 else "FAIL",
            "runner_mode": "diagnostic-only",
        }
        (REPO/"results"/f"{job_id}.json").write_text(json.dumps(result, indent=2)+"\n")
        shutil.copy2(log_path, REPO/"results"/f"{job_id}.log")
        archive = REPO/"jobs/archive"/job_path.name
        if archive.exists():
            job_path.unlink()
        else:
            job_path.replace(archive)
        run(["git", "add", "jobs/archive", "jobs/pending", "results"], check=True)
        run(["git", "commit", "-m", f"result: {target} {job_id} {'PASS' if rc == 0 else 'FAIL'}"], check=True)
        run(["git", "push", "origin", "main"], check=True)

    sync_repo()
    job_path, data = select_job()
    if job_path is None:
        print(f"No pending diagnostic jobs for {target}")
        raise SystemExit(0)

    required = {"schema_version","job_id","target","job_type","script","script_sha256","timeout_seconds"}
    missing = required - set(data)
    if missing:
        raise RuntimeError("missing manifest fields: "+",".join(sorted(missing)))
    if data["schema_version"] != 1 or data["job_type"] != "diagnostic":
        raise RuntimeError("AI VM runner is diagnostic-only")
    script_rel = data["script"]
    if not script_rel.startswith("jobs/scripts/"):
        raise RuntimeError("invalid diagnostic path")
    script = REPO/script_rel
    if not script.is_file() or sha256(script) != data["script_sha256"]:
        raise RuntimeError("script hash mismatch")

    log_path = STATE/f"{data['job_id']}.log"
    with log_path.open("w") as log:
        proc = subprocess.run(["bash", str(script)], cwd=REPO, stdout=log, stderr=subprocess.STDOUT, text=True, timeout=data["timeout_seconds"])
    publish(job_path, data, log_path, proc.returncode)
