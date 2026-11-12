"""Check the privacy of an empty staging directory on the fixed backup share."""
import json
import os
from pathlib import Path
import stat
import tempfile

SHARE = Path("/mnt/synology-backups")


def mount_matches(share, mount_id, mountinfo):
    for line in mountinfo.splitlines():
        before, separator, after = line.partition(" - ")
        fields = before.split()
        filesystem = after.split()
        if separator and len(fields) >= 5 and filesystem and fields[0] == mount_id:
            return fields[4] == str(share) and filesystem[0] == "nfs4"
    return False


def private_stage_status(info, uid):
    mode = format(stat.S_IMODE(info.st_mode), "04o")
    owner_matches = info.st_uid == uid
    return {
        "status": ("nas_private_directory_verified" if mode == "0700" and owner_matches
                   else "nas_private_directory_check_failed"),
        "mode": mode,
        "owner_matches_runner": owner_matches,
    }


def check_access(share):
    fd = os.open(share, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fdinfo = Path(f"/proc/self/fdinfo/{fd}").read_text()
        mount_id = next((line.split()[1] for line in fdinfo.splitlines()
                         if line.startswith("mnt_id:") and len(line.split()) == 2), None)
        root = Path(f"/proc/self/fd/{fd}")
        if (not mount_matches(share, mount_id, Path("/proc/self/mountinfo").read_text())
                or share.resolve(strict=True) != share or not share.samefile(root)):
            return {"status": "nas_mount_not_verified"}
        stage = Path(tempfile.mkdtemp(prefix="adguard-access-preflight-", dir=root))
        try:
            return private_stage_status(stage.stat(), os.geteuid())
        finally:
            stage.rmdir()
    finally:
        os.close(fd)


def main():
    os.umask(0o077)
    if os.geteuid() == 0:
        result = {"status": "root_execution_refused"}
    else:
        try:
            result = check_access(SHARE)
        except PermissionError:
            result = {"status": "nas_access_denied"}
        except OSError:
            result = {"status": "nas_access_unavailable"}
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "nas_private_directory_verified" else 2


if __name__ == "__main__":
    raise SystemExit(main())
