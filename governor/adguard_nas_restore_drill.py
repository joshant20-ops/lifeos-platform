"""Verify recovery of AdGuard files from a private NAS copy without running AdGuard."""
import hashlib
import json
import os
import resource
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import tarfile
import tempfile

SOURCE = Path("/mnt/docker-data/recovery/adguard-20261110-105901.tar.gz")
SHARE = Path("/mnt/synology-backups")
GIB = 1024**3
MAX_ARCHIVE = 256 * 1024**2
MAX_RESTORED = 2 * GIB
MAX_ENTRIES = 100_000


class DrillFailure(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise DrillFailure(reason)


def verified_mount(share):
    mount = subprocess.run(
        ["findmnt", "-rn", "--target", str(share), "-o", "TARGET,FSTYPE"],
        text=True, capture_output=True, timeout=5, check=True,
    ).stdout.strip()
    require(mount == f"{share} nfs4", "nas_mount_not_verified")
    require(share.is_dir() and share.resolve(strict=True) == share, "nas_path_not_verified")


def copy_archive(source, destination):
    fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as original:
        initial = os.fstat(fd)
        require(stat.S_ISREG(initial.st_mode) and 0 < initial.st_size <= MAX_ARCHIVE,
                "source_not_bounded_regular_file")
        digest = hashlib.sha256()
        remaining = initial.st_size
        with destination.open("xb") as output:
            while remaining:
                block = original.read(min(1024**2, remaining))
                require(block, "source_changed")
                output.write(block)
                digest.update(block)
                remaining -= len(block)
            output.flush()
            os.fsync(output.fileno())
        final = os.fstat(fd)
        require((initial.st_size, initial.st_ctime_ns) == (final.st_size, final.st_ctime_ns),
                "source_changed")
    with destination.open("rb") as copied:
        require(digest.digest() == hashlib.file_digest(copied, "sha256").digest(),
                "nas_copy_hash_mismatch")


def restore_files(archive_path, restored):
    # Use streaming gzip validation with a bounded subprocess. The outer job
    # also has a deadline and memory limit.
    result = subprocess.run(["gzip", "-t", "--", str(archive_path)], timeout=60,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    require(result.returncode == 0, "gzip_integrity_failed")
    restored.mkdir(mode=0o700)
    seen = set()
    members = []
    total = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and ".." not in path.parts, "unsafe_archive_path")
            require((member.isdir() or member.isfile()) and not member.issparse(),
                    "unsupported_archive_entry")
            require(path not in seen, "duplicate_archive_entry")
            require(member.size >= 0 and len(seen) < MAX_ENTRIES, "archive_entry_limit")
            seen.add(path)
            total += member.size
            require(total <= MAX_RESTORED, "archive_size_limit")
            members.append(member)
        configs = [member for member in members
                   if member.isfile() and PurePosixPath(member.name).name == "AdGuardHome.yaml"]
        require(len(configs) == 1 and configs[0].size > 0, "expected_configuration_not_found")
        archive.extractall(restored, members=members, filter="data")
    config = restored / configs[0].name
    require(config.is_file() and config.stat().st_size == configs[0].size,
            "configuration_readback_failed")
    return {"status": "file_restore_verified", "entries": len(members), "logical_bytes": total}


def main():
    os.umask(0o077)
    try:
        resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
        verified_mount(SHARE)
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            # Keep the opened NAS mount referenced throughout the drill.
            root = Path("/proc/self/fd") / str(fd)
            verified_mount(SHARE)
            require(SHARE.samefile(root), "nas_mount_changed")
            require(shutil.disk_usage(root).free >= 4 * GIB, "nas_free_space_below_4_gib")
            stage = Path(tempfile.mkdtemp(prefix="adguard-restore-drill-", dir=root))
            require(stat.S_IMODE(stage.stat().st_mode) == 0o700, "nas_private_directory_check_failed")
            copied = stage / "adguard.tar.gz"
            copy_archive(SOURCE, copied)
            # gzip is a subprocess and needs the mount reference to be usable
            # via the parent's proc directory.
            stage = Path("/proc") / str(os.getpid()) / "fd" / str(fd) / stage.name
            print(json.dumps(restore_files(stage / "adguard.tar.gz", stage / "restored"),
                             sort_keys=True))
        finally:
            os.close(fd)
    except DrillFailure as exc:
        print(json.dumps({"status": str(exc)}))
        return 2
    except (OSError, ValueError, tarfile.TarError, subprocess.SubprocessError):
        print(json.dumps({"status": "drill_unavailable_or_failed"}))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
