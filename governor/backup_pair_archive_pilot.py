"""Additive encrypted archive and isolated file restore of one candidate pair."""
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import tempfile

from governor.adguard_archive_restic_proof import PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount
from governor.storage_tier0 import enough_space
from scripts.lifeos_storage_backup_profile import DATED_SUFFIX, profile
from scripts.lifeos_storage_retention_inventory import open_inventory

ROOT = Path("/mnt/docker-data/automation/backups")
INVENTORY = Path("/home/joshan/lifeos-storage-inventory.tsv")
MAX_SOURCE = 32 * 1024**2
MAX_ARCHIVE = 40 * 1024**2
MAX_FILES = 128
NAME = "lifeos-backup-pair.tar"


class PilotStopped(RuntimeError):
    pass


def select_pair(groups, ranks):
    if len(ranks) != 2:
        raise PilotStopped("two_families_unverified")
    indexed = [{}, {}]
    rank_index = {family: index for index, family in enumerate(ranks)}
    for name in groups:
        match = DATED_SUFFIX.fullmatch(name)
        if not match or match[1] not in rank_index:
            continue
        family = indexed[rank_index[match[1]]]
        stamp = match[2] + match[3]
        family[stamp] = None if stamp in family else name
    for stamp in sorted(indexed[0].keys() & indexed[1].keys(), reverse=True):
        try:
            dt.datetime.strptime(stamp, "%Y%m%d%H%M%S")
        except ValueError:
            continue
        names = [index[stamp] for index in indexed]
        if all(names):
            records = [groups[name] for name in names]
            if (sum(item["bytes"] for item in records) <= MAX_SOURCE
                    and sum(item["files"] for item in records) <= MAX_FILES):
                return stamp, list(zip(names, records))
    raise PilotStopped("bounded_matched_pair_unavailable")


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def build_archive(backup_root, stamp, selected, destination):
    manifest = {"schema_version": 1, "timestamp_from_group_names": stamp,
                "relationship": "candidate_timestamp_pair", "superseded_by": None,
                "restore_scope": "file_readback_only", "runtime_dependencies": "unverified",
                "groups": []}
    total_files = total_bytes = directories = 0

    def collect(archive, directory, prefix, files, depth, remaining):
        nonlocal total_files, total_bytes, directories
        directories += 1
        if depth > 8 or directories > MAX_FILES:
            raise PilotStopped("source_directory_limit_exceeded")
        initial = identity(os.fstat(directory))
        if initial[0] != source_device:
            raise PilotStopped("source_mount_boundary")
        with os.scandir(directory) as entries:
            names = []
            for entry in entries:
                if len(names) >= MAX_FILES:
                    raise PilotStopped("source_entry_limit_exceeded")
                names.append(entry.name)
        for name in sorted(names):
            if name in {".", ".."} or "\\" in name:
                raise PilotStopped("source_path_unverified")
            info = os.stat(name, dir_fd=directory, follow_symlinks=False)
            if info.st_dev != source_device:
                raise PilotStopped("source_mount_boundary")
            path = prefix / name
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            if stat.S_ISDIR(info.st_mode):
                subdir = os.open(name, flags | os.O_DIRECTORY, dir_fd=directory)
                try:
                    if identity(os.fstat(subdir)) != identity(info):
                        raise PilotStopped("source_directory_changed")
                    collect(archive, subdir, path, files, depth + 1, remaining)
                finally:
                    os.close(subdir)
                continue
            if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                    or total_files >= MAX_FILES or info.st_size > remaining[0]
                    or total_bytes + info.st_size > MAX_SOURCE):
                raise PilotStopped("source_file_type_or_budget_unverified")
            with os.fdopen(os.open(name, flags, dir_fd=directory), "rb") as stream:
                if identity(os.fstat(stream.fileno())) != identity(info):
                    raise PilotStopped("source_file_changed")
                data = stream.read(info.st_size + 1)
                if len(data) != info.st_size or identity(os.fstat(stream.fileno())) != identity(info):
                    raise PilotStopped("source_file_changed")
            member = tarfile.TarInfo(str(path))
            member.size, member.mode, member.mtime = len(data), info.st_mode & 0o777, int(info.st_mtime)
            archive.addfile(member, io.BytesIO(data))
            files.append({"archive_path": str(path), "bytes": len(data),
                          "allocated_bytes": info.st_blocks * 512,
                          "mtime_ns": info.st_mtime_ns, "mode": member.mode, "sha256": hashlib.sha256(data).hexdigest()})
            total_files += 1
            total_bytes += len(data)
            remaining[0] -= len(data)
        if identity(os.fstat(directory)) != initial:
            raise PilotStopped("source_directory_changed")

    root = os.open(backup_root, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        source_device = os.fstat(root).st_dev
        with tarfile.open(fileobj=destination, mode="w") as archive:
            for index, (name, expected) in enumerate(selected, 1):
                if Path(name).name != name or name in {".", ".."}:
                    raise PilotStopped("source_group_unverified")
                group = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY, dir_fd=root)
                files = []
                try:
                    remaining = [expected["bytes"]]
                    collect(archive, group, PurePosixPath(f"group-{index}"), files, 0, remaining)
                finally:
                    os.close(group)
                if len(files) != expected["files"] or remaining[0]:
                    raise PilotStopped("inventory_group_changed")
                manifest["groups"].append({"original_group": name, "files": files})
            data = json.dumps(manifest, sort_keys=True, indent=2).encode()
            member = tarfile.TarInfo("CONTENTS.json")
            member.size, member.mode = len(data), 0o600
            archive.addfile(member, io.BytesIO(data))
    finally:
        os.close(root)
    if destination.tell() > MAX_ARCHIVE:
        raise PilotStopped("archive_size_exceeded")
    destination.seek(0)
    return manifest, total_files, total_bytes


def restore_files(stream, expected, directory):
    with tarfile.open(fileobj=stream, mode="r:") as archive:
        members = archive.getmembers()
        files = {file["archive_path"]: file for group in expected["groups"] for file in group["files"]}
        if len(members) != len(files) + 1 or {m.name for m in members} != set(files) | {"CONTENTS.json"}:
            raise PilotStopped("archive_members_unverified")
        for member in members:
            path = PurePosixPath(member.name)
            if not member.isfile() or path.is_absolute() or ".." in path.parts:
                raise PilotStopped("archive_member_unverified")
            target = directory.joinpath(*path.parts)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            with archive.extractfile(member) as data, target.open("xb") as output:
                payload = data.read(MAX_SOURCE + 1)
                output.write(payload)
            if member.name == "CONTENTS.json":
                if json.loads(target.read_bytes()) != expected:
                    raise PilotStopped("archive_manifest_unverified")
            else:
                record = files[member.name]
                with target.open("rb") as restored:
                    if (target.stat().st_size != record["bytes"]
                            or hashlib.file_digest(restored, "sha256").hexdigest() != record["sha256"]):
                        raise PilotStopped("restored_file_unverified")


def encrypted_readback(archive, env, manifest):
    digest = hashlib.file_digest(archive, "sha256").hexdigest()
    tag = "backup-pair-pilot-" + digest
    with tempfile.TemporaryFile(dir="/dev/shm") as restored:
        def readback():
            restored.seek(0)
            restored.truncate()
            result = subprocess.run(
                ["/usr/bin/prlimit", f"--fsize={MAX_ARCHIVE}:{MAX_ARCHIVE}", "--",
                 "/usr/bin/restic", "--no-lock", "--no-cache", "dump", "--tag", tag, "latest", "/" + NAME],
                env=env, stdin=subprocess.DEVNULL, stdout=restored, stderr=subprocess.DEVNULL,
                timeout=90, check=False,
            )
            restored.seek(0)
            return result.returncode == 0 and hashlib.file_digest(restored, "sha256").hexdigest() == digest

        if not readback():
            archive.seek(0)
            result = subprocess.run(
                ["/usr/bin/restic", "--no-cache", "backup", "--stdin", "--stdin-filename", NAME, "--tag", tag],
                env=env, stdin=archive, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=90, check=False,
            )
            if result.returncode or not readback():
                raise PilotStopped("encrypted_archive_readback_unverified")
        restored.seek(0)
        with tempfile.TemporaryDirectory(dir="/dev/shm") as directory:
            restore_files(restored, manifest, Path(directory))


def run():
    if os.geteuid() != 0 or not enough_space():
        raise PilotStopped("fixed_gateway_or_storage_reserve_unverified")
    memory = os.statvfs("/dev/shm")
    if memory.f_bavail * memory.f_frsize < 4 * MAX_ARCHIVE:
        raise PilotStopped("tmpfs_reserve_unverified")
    selection = []
    with open_inventory(INVENTORY) as stream:
        profile(stream, dt.datetime.now(dt.timezone.utc).date(),
                local_selection=lambda groups, ranks: selection.append(select_pair(groups, ranks)))
    stamp, pair = selection[0]
    fd = os.open(SHARE, os.O_RDONLY | os.O_NOFOLLOW | os.O_DIRECTORY)
    try:
        repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
        if not verify_nfs_mount(fd) or repo.resolve(strict=True) != REPOSITORY:
            raise PilotStopped("nas_repository_unverified")
        space = os.statvfs(repo)
        if space.f_bavail * space.f_frsize < 4 * 1024**3 + MAX_ARCHIVE:
            raise PilotStopped("nas_reserve_unverified")
        with tempfile.TemporaryFile(dir="/dev/shm") as archive:
            manifest, files, size = build_archive(ROOT, stamp, pair, archive)
            encrypted_readback(archive, {"PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                                      "RESTIC_REPOSITORY": str(repo),
                                      "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE)}, manifest)
    finally:
        os.close(fd)
    return {"status": "candidate_pair_file_restore_verified", "groups": 2,
            "files": files, "source_bytes": size, "reclaimed_bytes": 0}


def main():
    try:
        result = run()
    except PilotStopped as error:
        result = {"status": str(error)}
    except (OSError, ValueError, KeyError, IndexError, tarfile.TarError, subprocess.SubprocessError):
        result = {"status": "backup_pair_pilot_unverified"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "candidate_pair_file_restore_verified" else 2
