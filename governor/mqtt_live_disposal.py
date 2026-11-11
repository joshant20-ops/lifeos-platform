"""Fixed operation for the separately approved retained MQTT log disposal."""
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

from governor.adguard_archive_restic_proof import PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount
from governor.mqtt_live_rotation import JOURNAL, RETAINED, broker_identity, connection_inputs, health_checks
from governor.mqtt_retained_log_archive import ArchiveUnverified, readback
from governor.mqtt_retained_log_disposal import reclaim_one
from governor.mqtt_retained_rotation import RotationStopped
from governor.mqtt_rotation_preflight import LOG
from governor.storage_health_gate import HealthGate, HealthUnavailable


def inode_unused(info):
    deadline = time.monotonic() + 8
    target = (info.st_dev, info.st_ino)
    count = 0
    with os.scandir("/proc") as processes:
        for process in processes:
            if not process.name.isdecimal():
                continue
            if time.monotonic() >= deadline:
                return False
            try:
                with os.scandir(Path(process.path) / "fd") as entries:
                    for entry in entries:
                        count += 1
                        if count > 100_000 or time.monotonic() >= deadline:
                            return False
                        try:
                            descriptor = entry.stat(follow_symlinks=True)
                        except FileNotFoundError:
                            continue
                        if (descriptor.st_dev, descriptor.st_ino) == target:
                            return False
            except FileNotFoundError:
                continue
    return True


def reclaim():
    if os.geteuid() != 0:
        raise ArchiveUnverified("fixed_root_gateway_required")
    journal = JOURNAL.lstat()
    if journal.st_uid != 0 or not stat.S_ISDIR(journal.st_mode) or journal.st_mode & 0o077:
        raise ArchiveUnverified("rotation_journal_unverified")
    with os.fdopen(os.open(JOURNAL / "lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK),
                   "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proof = json.loads((JOURNAL / "archive-verified.json").read_text())
        tag = proof["archive_tag"]
        if not re.fullmatch(r"mqtt-retained-[0-9a-f]{64}", tag):
            raise ArchiveUnverified("archive_tag_unverified")
        initial = broker_identity()
        resolver, public = connection_inputs()
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
            if not verify_nfs_mount(fd) or repo.resolve(strict=True) != REPOSITORY:
                raise ArchiveUnverified("nas_repository_unverified")
            env = {"PATH": "/usr/bin:/bin", "HOME": "/dev/shm", "GOMAXPROCS": "1",
                   "GOMEMLIMIT": "256MiB", "RESTIC_REPOSITORY": str(repo),
                   "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE)}
            gate = HealthGate(lambda: health_checks(resolver, public), interval=2, max_age=16).start()
            try:
                def guard():
                    gate.guard()
                    if broker_identity() != initial:
                        raise ArchiveUnverified("broker_identity_changed")

                def backup(_proof):
                    return readback(env, tag, tag.removeprefix("mqtt-retained-"), 600, gate.guard)

                before = os.statvfs(LOG.parent)
                reclaimed = reclaim_one(LOG.with_name(RETAINED), JOURNAL, proof,
                                        guard, backup, inode_unused)
                after = os.statvfs(LOG.parent)
                gate.sample()
                guard()
                return {
                    "status": "verified_local_copy_removed",
                    "allocated_bytes_removed": reclaimed,
                    "available_bytes_before": before.f_bavail * before.f_frsize,
                    "available_bytes_after": after.f_bavail * after.f_frsize,
                }
            finally:
                gate.close()
        finally:
            os.close(fd)


def main():
    try:
        result = reclaim()
    except ArchiveUnverified as error:
        result = {"status": str(error)}
    except (OSError, ValueError, KeyError, RotationStopped, HealthUnavailable,
            subprocess.SubprocessError):
        result = {"status": "disposal_stopped_review_local_journal"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "verified_local_copy_removed" else 2
