"""Reclaim one journaled retained file after an independently verified readback."""
import os
from pathlib import Path
import stat
import tempfile

from governor.mqtt_retained_log_archive import ArchiveUnverified, fingerprint
from governor.mqtt_retained_rotation import write_record


def reclaim_one(path, journal, proof, guard, verify_backup, unused):
    """The caller holds the rotation lock and supplies the exact approved proof.

    Move to a private directory on the same filesystem before unlinking.
    Unexpected state after the move preserves the file for local recovery.
    """
    info = path.lstat()
    expected = tuple(proof["fingerprint"])
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or fingerprint(info) != expected
            or info.st_blocks * 512 != proof["allocated_bytes"]):
        raise ArchiveUnverified("approved_inode_changed")
    guard()
    if not unused(info):
        raise ArchiveUnverified("retained_inode_in_use")
    if not verify_backup(proof):
        raise ArchiveUnverified("fresh_nas_readback_unverified")
    guard()
    if fingerprint(path.lstat()) != expected:
        raise ArchiveUnverified("approved_inode_changed")
    quarantine = Path(tempfile.mkdtemp(prefix=".lifeos-mqtt-disposal-", dir=path.parent))
    quarantine_fd = os.open(quarantine, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        write_record(journal / "disposal-prepared.json", {
            "source": str(path), "quarantine": str(quarantine),
            "fingerprint": expected, "archive_tag": proof["archive_tag"],
        })
        guard()
        if fingerprint(path.lstat()) != expected:
            raise ArchiveUnverified("approved_inode_changed")
        os.rename(path, "retained.log", dst_dir_fd=quarantine_fd)
        moved = os.stat("retained.log", dir_fd=quarantine_fd, follow_symlinks=False)
        if (not stat.S_ISREG(moved.st_mode) or moved.st_nlink != 1
                or fingerprint(moved)[:3] != expected[:3]
                or moved.st_mtime_ns != expected[-1]
                or moved.st_blocks * 512 != proof["allocated_bytes"]
                or not unused(moved)):
            raise ArchiveUnverified("quarantined_inode_unverified")
        guard()
        os.unlink("retained.log", dir_fd=quarantine_fd)
        os.fsync(quarantine_fd)
        write_record(journal / "disposal-complete.json", {
            "status": "verified_local_copy_removed",
            "allocated_bytes": info.st_blocks * 512,
        })
        return info.st_blocks * 512
    finally:
        os.close(quarantine_fd)
        try:
            quarantine.rmdir()
        except OSError:
            # A stopped disposal can leave the verified file in quarantine.
            pass
