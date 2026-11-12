"""Prove recovery of AdGuard configuration and work files without a live restore."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import signal
import subprocess
import tarfile
import tempfile

SHARE = Path("/mnt/synology-backups")


def verify_nfs_mount(fd):
    info = Path(f"/proc/self/fdinfo/{fd}").read_text()
    mount_id = next((line.split()[1] for line in info.splitlines()
                     if line.startswith("mnt_id:") and len(line.split()) == 2), None)
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if separator and len(fields) >= 5 and fields[0] == mount_id:
            return fields[4] == str(SHARE) and after.split()[:1] == ["nfs4"]
    return False


REPOSITORY = SHARE / "restic/lifeos-pi5"
PASSWORD_FILE = Path("/etc/lifeos/restic-password")
CONFIG = "/opt/stacks/adguard/conf/AdGuardHome.yaml"

TREE = str(PurePosixPath(CONFIG).parent.parent)
LIMIT = 1024**3
CONFIG_LIMIT = 8 * 1024**2


def result(status, **details):
    return {"status": status, "scope": "adguard_tree", **details}


def inspect_recovered_tree(archive_stream):
    config_ok = False
    work_files = work_bytes = entries = 0
    seen = set()
    with tarfile.open(fileobj=archive_stream, mode="r|") as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            entries += 1
            if (entries > 100_000 or path in seen or path.is_absolute() or ".." in path.parts
                    or member.issparse() or not (member.isdir() or member.isfile())):
                return result("archive_entry_rejected")
            seen.add(path)
            if member.isdir():
                continue
            with archive.extractfile(member) as data:
                if path == PurePosixPath("conf/AdGuardHome.yaml"):
                    if not 0 < member.size <= CONFIG_LIMIT:
                        return result("config_size_rejected")
                    config_ok = re.search(rb"(?m)^schema_version:[ \t]+[0-9]+[ \t]*\r?$",
                                          data.read(CONFIG_LIMIT + 1)) is not None
                elif path.parts[:2] == ("work", "data") and member.size > 0:
                    work_files += 1
                    work_bytes += member.size
    if not config_ok:
        return result("expected_config_missing_or_invalid")
    if not work_files:
        return result("expected_work_data_missing")
    return result("adguard_config_and_work_recovered", work_files=work_files, work_bytes=work_bytes)


def recover_tree(env, tree=TREE, limit=LIMIT):
    staging = subprocess.run(["/usr/bin/findmnt", "-rn", "--target", "/dev/shm", "-o", "FSTYPE"],
                             capture_output=True, text=True, timeout=5, check=False)
    available = re.search(r"(?m)^MemAvailable:\s+(\d+) kB$", Path("/proc/meminfo").read_text())
    space = os.statvfs("/dev/shm")
    if (staging.returncode or staging.stdout.strip() != "tmpfs" or not available
            or int(available.group(1)) * 1024 < limit + 1024**3
            or space.f_bavail * space.f_frsize < limit):
        return {"status": "ram_reserve_unverified", "scope": "adguard_tree"}
    with tempfile.TemporaryFile(dir="/dev/shm") as recovered:
        dump = subprocess.run(
            ["/usr/bin/prlimit", f"--fsize={limit}:{limit}", "--",
             "/usr/bin/restic", "--no-lock", "--no-cache", "dump", "--tag", "lifeos-pi5",
             "latest:" + tree, "/"],
            env=env, stdin=subprocess.DEVNULL, stdout=recovered, stderr=subprocess.DEVNULL,
            timeout=120, check=False,
        )
        if dump.returncode == -signal.SIGXFSZ:
            return result("ram_output_limit_reached")
        if dump.returncode != 0:
            return result("restic_dump_failed", exit_code=dump.returncode)
        recovered.seek(0)
        return inspect_recovered_tree(recovered)


def main():
    proof = result("restic_nas_repository_unverified")
    try:
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
            if verify_nfs_mount(fd) and repo.resolve(strict=True) == REPOSITORY and repo.is_dir():
                proof = recover_tree({
                    "PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                    "RESTIC_REPOSITORY": str(repo), "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE),
                })
        finally:
            os.close(fd)
    except subprocess.TimeoutExpired:
        proof = result("restic_read_timeout")
    except tarfile.TarError:
        proof = result("archive_stream_invalid")
    except (OSError, ValueError, subprocess.SubprocessError):
        proof = result("local_probe_unavailable")
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "adguard_config_and_work_recovered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
