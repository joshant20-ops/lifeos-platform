"""Recover the exact AdGuard configuration from encrypted Restic, locally."""
import json
import os
from pathlib import Path
import re
import subprocess
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
LIMIT = 8 * 1024**2


def recover_config(env, path=CONFIG):
    """Bound the decoded output and suppress all content and Restic errors."""
    staging = subprocess.run(["/usr/bin/findmnt", "-rn", "--target", "/dev/shm", "-o", "FSTYPE"],
                             capture_output=True, text=True, timeout=5, check=False)
    if staging.returncode != 0 or staging.stdout.strip() != "tmpfs":
        return False
    with tempfile.TemporaryFile(dir="/dev/shm") as recovered:
        result = subprocess.run(
            ["/usr/bin/prlimit", f"--fsize={LIMIT}:{LIMIT}", "--",
             "/usr/bin/restic", "--no-lock", "--no-cache", "dump", "--tag", "lifeos-pi5",
             "latest", path],
            env=env, stdin=subprocess.DEVNULL, stdout=recovered, stderr=subprocess.DEVNULL,
            timeout=60, check=False,
        )
        if result.returncode != 0:
            return False
        recovered.seek(0)
        data = recovered.read(LIMIT + 1)
        return (0 < len(data) <= LIMIT
                and re.search(rb"(?m)^schema_version:[ \t]+[0-9]+[ \t]*\r?$", data) is not None)


def main():
    status = "adguard_config_unverified"
    try:
        mount_fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            # Address Restic through the held NFS mount so a disappearing
            # automount cannot redirect the probe to the Pi filesystem.
            repository = Path(f"/proc/{os.getpid()}/fd/{mount_fd}") / REPOSITORY.relative_to(SHARE)
            if (verify_nfs_mount(mount_fd) and repository.resolve(strict=True) == REPOSITORY
                    and repository.is_dir()):
                env = {"PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                       "RESTIC_REPOSITORY": str(repository), "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE)}
                if recover_config(env):
                    status = "adguard_config_recovered"
        finally:
            os.close(mount_fd)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    print(json.dumps({"status": status, "scope": "config_only"}, sort_keys=True))
    return 0 if status == "adguard_config_recovered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
