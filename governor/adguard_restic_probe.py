"""Recover the exact AdGuard configuration from encrypted Restic, locally."""
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from governor.adguard_nas_restore_drill import DrillFailure, SHARE, verified_mount

REPOSITORY = SHARE / "restic/lifeos-pi5"
PASSWORD_FILE = Path("/etc/lifeos/restic-password")
CONFIG = "/opt/stacks/adguard/conf/AdGuardHome.yaml"
LIMIT = 8 * 1024**2


def recover_config(env, path=CONFIG):
    """Bound the decoded output and suppress all content and Restic errors."""
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
            verified_mount(SHARE, mount_fd)
            # Address Restic through the held NFS mount so a disappearing
            # automount cannot redirect the probe to the Pi filesystem.
            repository = Path(f"/proc/{os.getpid()}/fd/{mount_fd}") / REPOSITORY.relative_to(SHARE)
            if repository.resolve(strict=True) == REPOSITORY and repository.is_dir():
                env = {"PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                       "RESTIC_REPOSITORY": str(repository), "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE)}
                if recover_config(env):
                    status = "adguard_config_recovered"
        finally:
            os.close(mount_fd)
    except (DrillFailure, OSError, ValueError, subprocess.SubprocessError):
        pass
    print(json.dumps({"status": status, "scope": "config_only"}, sort_keys=True))
    return 0 if status == "adguard_config_recovered" else 2


if __name__ == "__main__":
    raise SystemExit(main())
