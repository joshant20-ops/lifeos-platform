#!/usr/bin/env python3
import json
import os
import re
import shlex
import tempfile
from datetime import datetime, timezone
from pathlib import Path

SERVICE = "lifeos-restic-backup.service"
ALLOWED = re.compile(r"^(RESTIC_|AWS_|B2_|AZURE_)[A-Z0-9_]+=")


def systemctl(*args):
    read_fd, write_fd = os.pipe()
    pid = os.posix_spawn(
        "/usr/bin/systemctl",
        ["systemctl", *args],
        os.environ,
        file_actions=[(os.POSIX_SPAWN_DUP2, write_fd, 1)],
    )
    os.close(write_fd)
    with os.fdopen(read_fd) as handle:
        output = handle.read()
    _, status = os.waitpid(pid, 0)
    if status != 0:
        raise RuntimeError("systemctl failed")
    return output


def restic(env, args, output=None):
    actions = []
    fd = None
    if output is not None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
        fd = os.open(output, flags, 0o600)
        actions.append((os.POSIX_SPAWN_DUP2, fd, 1))
    pid = os.posix_spawn(
        "/usr/bin/restic",
        ["restic", *args],
        env,
        file_actions=actions,
    )
    if fd is not None:
        os.close(fd)
    _, status = os.waitpid(pid, 0)
    if status != 0:
        raise RuntimeError(f"restic failed: {args[0]}")


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


def main():
    print("RESTORE_REHEARSAL=START")
    env = restic_env()
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp)
        snapshot_file = base / "snapshots.json"
        restic(
            env,
            ["snapshots", "--latest", "1", "--json"],
            str(snapshot_file),
        )
        snapshots = json.loads(snapshot_file.read_text(encoding="utf-8"))
        if not snapshots:
            raise RuntimeError("no snapshots")
        snap = snapshots[0]
        print("SNAPSHOT_PRESENT=YES")
        print(f"SNAPSHOT_TIME={snap.get('time', '')}")
        print(f"SNAPSHOT_HOST={snap.get('hostname', '')}")
        print(f"SNAPSHOT_PATH_COUNT={len(snap.get('paths') or [])}")
        restic(env, ["check", "--read-data-subset=1/100"])
        print("RESTIC_CHECK=PASS")
        target = base / "restore"
        restic(env, ["restore", "latest", "--target", str(target)])
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
