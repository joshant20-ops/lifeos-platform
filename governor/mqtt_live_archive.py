"""Archive the fixed retained MQTT log on the established encrypted NAS."""
import fcntl
import json
import os
from pathlib import Path
import stat
import re
import subprocess

from governor.adguard_archive_restic_proof import PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount
from governor.mqtt_live_rotation import JOURNAL, RETAINED, broker_identity, connection_inputs, health_checks
from governor.mqtt_retained_log_archive import ArchiveUnverified, fingerprint, preserve
from governor.mqtt_retained_rotation import RotationStopped, write_record
from governor.mqtt_rotation_preflight import LOG, writer_matches
from governor.storage_health_gate import HealthGate, HealthUnavailable


def run_archive():
    if os.geteuid() != 0:
        raise ArchiveUnverified("fixed_root_gateway_required")
    journal = JOURNAL.lstat()
    if journal.st_uid != 0 or not stat.S_ISDIR(journal.st_mode) or journal.st_mode & 0o077:
        raise ArchiveUnverified("rotation_journal_unverified")
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(JOURNAL / "lock", flags), "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        record = json.loads((JOURNAL / "verified.json").read_text())
        path = LOG.with_name(RETAINED)
        info = path.lstat()
        if (record["active"], record["retained"], record["device"], record["inode"]) != (
                LOG.name, RETAINED, info.st_dev, info.st_ino):
            raise ArchiveUnverified("retained_inode_unverified")
        if (JOURNAL / "archive-verified.json").exists():
            raise ArchiveUnverified("existing_archive_proof_requires_review")
        initial = broker_identity()
        resolver, public = connection_inputs()
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
            if not verify_nfs_mount(fd) or repo.resolve(strict=True) != REPOSITORY:
                raise ArchiveUnverified("nas_repository_unverified")
            space = os.statvfs(repo)
            if space.f_bavail * space.f_frsize < info.st_size + 4 * 1024**3:
                raise ArchiveUnverified("nas_reserve_unverified")
            gate = HealthGate(lambda: health_checks(resolver, public), interval=2, max_age=16).start()
            try:
                def closed(candidate):
                    return (fingerprint(info) == fingerprint(candidate)
                            and broker_identity() == initial
                            and not writer_matches(initial[2], candidate))

                prepared = JOURNAL / "archive-prepared.json"

                def resume(candidate):
                    saved = json.loads(prepared.read_text())
                    if (tuple(saved["fingerprint"]) != fingerprint(candidate)
                            or not re.fullmatch(r"[0-9a-f]{64}", saved["digest"])):
                        raise ArchiveUnverified("archive_checkpoint_mismatch")
                    return saved["digest"]

                def checkpoint(candidate, digest):
                    if prepared.exists():
                        if resume(candidate) != digest:
                            raise ArchiveUnverified("archive_checkpoint_mismatch")
                    else:
                        write_record(prepared, {"fingerprint": fingerprint(candidate),
                                                "digest": digest})

                def phase(name):
                    print(json.dumps({"archive_phase": name}), flush=True)

                report = preserve(path, {
                    "PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                    "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE),
                    "GOMAXPROCS": "1", "GOMEMLIMIT": "256MiB",
                }, closed, timeout=900, guard=gate.guard, checkpoint=checkpoint,
                    resume_digest=resume if prepared.exists() else None, phase=phase)
                gate.sample()
                gate.guard()
                if fingerprint(path.lstat()) != fingerprint(info):
                    raise ArchiveUnverified("retained_log_changed")
                write_record(JOURNAL / "archive-verified.json", {
                    "fingerprint": fingerprint(info), "archive_tag": report.pop("archive_tag"),
                    "allocated_bytes": info.st_blocks * 512,
                })
                return {**report, "allocated_bytes": info.st_blocks * 512}
            finally:
                gate.close()
        finally:
            os.close(fd)


def main():
    try:
        result = run_archive()
    except ArchiveUnverified as error:
        result = {"status": str(error)}
    except HealthUnavailable:
        result = {"status": "archive_stopped_health_probe_failed"}
    except (OSError, ValueError, KeyError, RotationStopped, subprocess.SubprocessError) as error:
        result = {"status": "archive_stopped_review_local_journal", "error_type": type(error).__name__}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "encrypted_log_readback_verified" else 2
