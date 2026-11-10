"""Store one existing AdGuard recovery archive in encrypted Restic and verify it."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tarfile
import tempfile

from governor.adguard_nas_restore_drill import SOURCE
from governor.adguard_restic_probe import PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount

LIMIT = 256 * 1024**2
MAX_UNPACKED = 2 * 1024**3
FILENAME = "adguard-recovery.tar.gz"


def archive_has_recovery_files(stream):
    files = {}
    config_root = None
    total = 0
    with tarfile.open(fileobj=stream, mode="r|gz") as archive:
        for index, member in enumerate(archive):
            path = PurePosixPath(member.name)
            total += member.size
            if (index >= 100_000 or total > MAX_UNPACKED or path.is_absolute()
                    or ".." in path.parts or member.issparse()
                    or not (member.isdir() or member.isfile())):
                return False
            if not member.isfile():
                continue
            if path in files:
                return False
            files[path] = member.size
            if path.parts[-2:] == ("conf", "AdGuardHome.yaml"):
                if config_root is not None or not 0 < member.size <= 8 * 1024**2:
                    return False
                with archive.extractfile(member) as data:
                    if not re.search(rb"(?m)^schema_version:[ \t]+[0-9]+[ \t]*\r?$", data.read()):
                        return False
                config_root = path.parent.parent
    if config_root is None or not all(path.is_relative_to(config_root) for path in files):
        return False
    return any(size > 0 and path.relative_to(config_root).parts[:2] == ("work", "data")
               for path, size in files.items())


def verify_snapshot(env, tag, expected):
    with tempfile.TemporaryFile(dir="/dev/shm") as recovered:
        result = subprocess.run(
            ["/usr/bin/prlimit", f"--fsize={LIMIT}:{LIMIT}", "--",
             "/usr/bin/restic", "--no-lock", "--no-cache", "dump", "--tag", tag,
             "latest", "/" + FILENAME],
            env=env, stdin=subprocess.DEVNULL, stdout=recovered, stderr=subprocess.DEVNULL,
            timeout=120, check=False,
        )
        if result.returncode:
            return False
        recovered.seek(0)
        return hashlib.file_digest(recovered, "sha256").hexdigest() == expected


def backup_archive(source, env):
    staging = subprocess.run(["/usr/bin/findmnt", "-rn", "--target", "/dev/shm", "-o", "FSTYPE"],
                             capture_output=True, text=True, timeout=5, check=False)
    space = os.statvfs("/dev/shm")
    memory = re.search(r"(?m)^MemAvailable:\s+(\d+) kB$", Path("/proc/meminfo").read_text())
    if (staging.returncode or staging.stdout.strip() != "tmpfs"
            or space.f_bavail * space.f_frsize < 2 * LIMIT or not memory
            or int(memory.group(1)) * 1024 < 2 * LIMIT + 1024**3):
        return "ram_staging_unverified"
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as original, tempfile.TemporaryFile(dir="/dev/shm") as archive:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= LIMIT:
            return "archive_size_or_type_rejected"
        remaining = info.st_size
        while remaining:
            block = original.read(min(1024**2, remaining))
            if not block:
                return "archive_changed"
            archive.write(block)
            remaining -= len(block)
        current = os.fstat(fd)
        if (current.st_size, current.st_ctime_ns) != (info.st_size, info.st_ctime_ns):
            return "archive_changed"
        archive.seek(0)
        if not archive_has_recovery_files(archive):
            return "archive_recovery_coverage_unverified"
        archive.seek(0)
        digest = hashlib.file_digest(archive, "sha256").hexdigest()
        tag = "adguard-recovery-" + digest
        if verify_snapshot(env, tag, digest):
            return "encrypted_archive_already_verified"
        archive.seek(0)
        result = subprocess.run(
            ["/usr/bin/restic", "--no-cache", "backup", "--stdin",
             "--stdin-filename", FILENAME, "--tag", tag],
            env=env, stdin=archive, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            timeout=120, check=False,
        )
        if result.returncode:
            return "encrypted_backup_failed"
        if not verify_snapshot(env, tag, digest):
            return "encrypted_archive_readback_unverified"
        return "encrypted_archive_verified"


def main():
    status = "restic_nas_repository_unverified"
    try:
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
            if verify_nfs_mount(fd) and repo.resolve(strict=True) == REPOSITORY and repo.is_dir():
                space = os.statvfs(repo)
                if space.f_bavail * space.f_frsize < 4 * 1024**3:
                    status = "nas_reserve_unverified"
                else:
                    status = backup_archive(SOURCE, {
                        "PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                        "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE),
                    })
        finally:
            os.close(fd)
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        status = "archive_proof_unavailable"
    print(json.dumps({"status": status, "scope": "existing_adguard_archive"}))
    return 0 if status in {"encrypted_archive_verified", "encrypted_archive_already_verified"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
