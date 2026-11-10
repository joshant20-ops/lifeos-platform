"""Read-only proof of the identity of the live broker and its log writer."""
import json
import os
from pathlib import Path
import stat
import time

from governor.storage_tier0 import command

IMAGE = "eclipse-mosquitto@sha256:6f8d8a947c506f8a2290ec65cd4bd2bc7cb4d43fb5f6271f861cb013e2ef9797"
LOG = Path("/opt/stacks/mosquitto/log/mosquitto.log")
CONTAINER = "mosquitto"


def inspect(kind, name):
    result = json.loads(command(["docker", "inspect", "--type", kind, name]))
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise ValueError("inspect unavailable")
    return result[0]


def writer_matches(pid, info):
    """Find a writable descriptor for this exact inode without reading its data."""
    root = Path("/proc") / str(pid)
    deadline = time.monotonic() + 2
    with os.scandir(root / "fd") as entries:
        for index, entry in enumerate(entries):
            if index >= 4096 or time.monotonic() > deadline:
                return False
            try:
                opened = entry.stat(follow_symlinks=True)
                if (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino):
                    continue
                with (root / "fdinfo" / entry.name).open() as stream:
                    fields = stream.read(4096).splitlines()
                for field in fields:
                    if field.startswith("flags:"):
                        mode = int(field.split()[1], 8) & os.O_ACCMODE
                        if mode in (os.O_WRONLY, os.O_RDWR):
                            return True
            except (FileNotFoundError, ProcessLookupError):
                continue
    return False


def preflight():
    checks = dict.fromkeys(("broker_healthy", "pinned_arm64_image", "expected_log_mount",
                            "regular_log_file", "confirmed_writer", "stable_identity"), False)
    size = None
    writer_status = "not_checked"
    try:
        broker = inspect("container", CONTAINER)
        state = broker["State"]
        pid = state["Pid"]
        checks["broker_healthy"] = state["Running"] is True and state["Health"]["Status"] == "healthy"
        if not checks["broker_healthy"] or type(pid) is not int or pid <= 0:
            return checks, size, writer_status
        image = inspect("image", broker["Image"])
        checks["pinned_arm64_image"] = image["Architecture"] == "arm64" and IMAGE in image["RepoDigests"]
        mounts = [mount for mount in broker["Mounts"] if mount["Destination"] == "/mosquitto/log"]
        checks["expected_log_mount"] = (
            len(mounts) == 1 and mounts[0]["Type"] == "bind" and mounts[0]["RW"] is True
            and Path(mounts[0]["Source"]).samefile(LOG.parent)
        )
        if not checks["expected_log_mount"]:
            return checks, size, writer_status
        info = LOG.lstat()
        checks["regular_log_file"] = stat.S_ISREG(info.st_mode) and info.st_nlink == 1
        if not checks["regular_log_file"]:
            return checks, size, writer_status
        size = info.st_size
        try:
            checks["confirmed_writer"] = writer_matches(pid, info)
            writer_status = "confirmed" if checks["confirmed_writer"] else "unconfirmed"
        except PermissionError:
            writer_status = "permission_denied"
        except (OSError, ValueError, IndexError):
            writer_status = "unavailable"
        latest = inspect("container", CONTAINER)
        current = LOG.lstat()
        checks["stable_identity"] = (
            latest["Id"] == broker["Id"] and latest["Image"] == broker["Image"]
            and latest["State"]["Pid"] == pid
            and latest["State"]["StartedAt"] == state["StartedAt"]
            and latest["State"]["Health"]["Status"] == "healthy"
            and (current.st_dev, current.st_ino, current.st_nlink) == (info.st_dev, info.st_ino, 1)
        )
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        pass
    return checks, size, writer_status


def main():
    checks, size, writer_status = preflight()
    print(json.dumps({"checks": checks, "log_bytes": size, "writer_status": writer_status,
                      "maintenance_authorised": False},
                     sort_keys=True))
    return 0 if all(checks.values()) else 2


if __name__ == "__main__":
    raise SystemExit(main())
