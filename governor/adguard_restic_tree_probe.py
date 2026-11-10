"""Prove recovery of AdGuard configuration and work files without a live restore."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

from governor.adguard_restic_probe import CONFIG, PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount

TREE = str(PurePosixPath(CONFIG).parent.parent)
LIMIT = 1024**3
CONFIG_LIMIT = 8 * 1024**2


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
                return None
            seen.add(path)
            if member.isdir():
                continue
            with archive.extractfile(member) as data:
                if path == PurePosixPath("conf/AdGuardHome.yaml"):
                    if not 0 < member.size <= CONFIG_LIMIT:
                        return None
                    config_ok = re.search(rb"(?m)^schema_version:[ \t]+[0-9]+[ \t]*\r?$",
                                          data.read(CONFIG_LIMIT + 1)) is not None
                elif path.parts[:1] == ("work",) and member.size > 0:
                    work_files += 1
                    work_bytes += member.size
    if not config_ok or not work_files:
        return None
    return {"status": "adguard_config_and_work_recovered", "scope": "adguard_tree",
            "work_files": work_files, "work_bytes": work_bytes}


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
        result = subprocess.run(
            ["/usr/bin/prlimit", f"--fsize={limit}:{limit}", "--",
             "/usr/bin/restic", "--no-lock", "--no-cache", "dump", "--tag", "lifeos-pi5",
             "latest", tree],
            env=env, stdin=subprocess.DEVNULL, stdout=recovered, stderr=subprocess.DEVNULL,
            timeout=120, check=False,
        )
        if result.returncode == 0:
            recovered.seek(0)
            proof = inspect_recovered_tree(recovered)
            if proof:
                return proof
    return {"status": "adguard_tree_unverified", "scope": "adguard_tree"}


def main():
    proof = {"status": "adguard_tree_unverified", "scope": "adguard_tree"}
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
    except (OSError, ValueError, subprocess.SubprocessError, tarfile.TarError):
        pass
    print(json.dumps(proof, sort_keys=True))
    return 0 if proof["status"] == "adguard_config_and_work_recovered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
