#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess  # nosec B404
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "lifeos-restic-backup.service"
SYSTEMCTL = "/usr/bin/systemctl"
RESTIC = "/usr/bin/restic"
ALLOWED = re.compile(r"^(RESTIC_|AWS_|B2_|AZURE_)[A-Z0-9_]+=")


def run(argv, *, env=None, capture=False):
    if not argv or argv[0] not in {SYSTEMCTL, RESTIC}:
        raise ValueError("unapproved executable")
    stdout = subprocess.PIPE if capture else subprocess.DEVNULL
    return subprocess.run(  # nosec B603
        argv, env=env, text=True, check=True, stdout=stdout, shell=False
    )


def systemctl(*args):
    return run([SYSTEMCTL, *args], capture=True).stdout


def restic_env():
    state = systemctl("show", SERVICE, "-p", "LoadState", "--value").strip()
    if state != "loaded":
        raise RuntimeError("backup service missing")
    raw_env = systemctl("show", SERVICE, "-p", "Environment", "--value")
    items = shlex.split(raw_env)
    unit = systemctl("cat", SERVICE)
    for rawpath in re.findall(r"^\s*EnvironmentFile=-?([^\s]+)", unit, re.M):
        path = Path(rawpath.strip("\"'"))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            try:
                items.extend(shlex.split(line, comments=True, posix=True))
            except ValueError:
                continue
    env = os.environ.copy()
    for item in items:
        if ALLOWED.match(item):
            key, value = item.split("=", 1)
            env[key] = value
    if "RESTIC_REPOSITORY" not in env:
        raise RuntimeError("repository contract missing")
    return env


def restic(env, *args, capture=False):
    return run([RESTIC, *args], env=env, capture=capture)


def main():
    print("RESTORE_REHEARSAL=START")
    env = restic_env()
    result = restic(
        env, "snapshots", "--latest", "1", "--json", capture=True
    )
    snapshots = json.loads(result.stdout)
    if not snapshots:
        raise RuntimeError("no snapshots")
    snap = snapshots[0]
    print("SNAPSHOT_PRESENT=YES")
    print(f"SNAPSHOT_TIME={snap.get('time', '')}")
    print(f"SNAPSHOT_HOST={snap.get('hostname', '')}")
    print(f"SNAPSHOT_PATH_COUNT={len(snap.get('paths') or [])}")
    restic(env, "check", "--read-data-subset=1/100")
    print("RESTIC_CHECK=PASS")
    with tempfile.TemporaryDirectory() as temp:
        target = Path(temp) / "restore"
        restic(env, "restore", "latest", "--target", str(target))
        count = sum(1 for path in target.rglob("*") if path.is_file())
    if count <= 0:
        raise RuntimeError("no files restored")
    print(f"RESTORED_FILE_COUNT={count}")
    state = Path.home() / ".local/state/lifeos/restore-rehearsal"
    state.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "result": "PASS",
        "repository_check": "PASS",
        "actual_restore": "PASS",
        "restored_file_count": count,
        "production_overwrite": False,
        "secrets_emitted": False,
    }
    fd, temp = tempfile.mkstemp(prefix=".restore-rehearsal-", dir=state)
    os.close(fd)
    encoded = json.dumps(record, indent=2) + "\n"
    Path(temp).write_text(encoded, encoding="utf-8")
    os.replace(temp, state / "latest.json")
    print("PRODUCTION_OVERWRITE=NO")
    print("SECRETS_EMITTED=NO")
    print("RESTORE_REHEARSAL=PASS")


if __name__ == "__main__":
    main()
