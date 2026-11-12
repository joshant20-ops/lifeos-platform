"""Retain and reopen one log under a caller-supplied, fail-closed health gate."""
import ctypes
import json
import os
from pathlib import Path
import stat
import time


class RotationStopped(Exception):
    pass


def rename_without_replacement(directory_fd, old, new):
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(directory_fd, os.fsencode(old), directory_fd, os.fsencode(new), 1):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


def identity(info):
    return info.st_dev, info.st_ino


def inspect_log(directory_fd, name):
    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RotationStopped("log_type_or_link_count_rejected")
    return info


def write_record(path, record):
    # A unique record is the durable precondition, never an overwritten latest.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(record, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    parent = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def rotate(directory, active_name, retained_name, journal, guard, writer, reopen, verify,
           deadline_seconds=8):
    """Callbacks are trusted fixed adapters. Journal and retained data stay local.

    guard() raises on failed/stale monitoring. writer(info) proves the current
    fixed broker owns the inode. verify(old, new) proves closure and continuity.
    The operation never deletes or copies the retained log.
    """
    if (not active_name or not retained_name or active_name == retained_name
            or any(Path(name).name != name or name in {".", ".."}
                   for name in (active_name, retained_name))):
        raise RotationStopped("invalid_log_name")
    directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    renamed = False
    old = None
    try:
        guard()
        old = inspect_log(directory_fd, active_name)
        if not writer(old):
            raise RotationStopped("writer_unverified")
        record = {"active": active_name, "retained": retained_name,
                  "device": old.st_dev, "inode": old.st_ino, "bytes": old.st_size}
        write_record(journal / "prepared.json", record)
        guard()
        if identity(inspect_log(directory_fd, active_name)) != identity(old):
            raise RotationStopped("active_log_changed")
        rename_without_replacement(directory_fd, active_name, retained_name)
        renamed = True
        os.fsync(directory_fd)
        write_record(journal / "retained.json", record)
        guard()
        reopen()
        deadline = time.monotonic() + deadline_seconds
        while True:
            guard()
            try:
                new = inspect_log(directory_fd, active_name)
            except FileNotFoundError:
                new = None
            if new and identity(new) != identity(old):
                break
            if time.monotonic() >= deadline:
                raise RotationStopped("new_log_unverified")
            time.sleep(0.1)
        verify(old, new)
        guard()
        write_record(journal / "verified.json", record)
        return {"status": "retained_rotation_verified", "retained_bytes": old.st_size,
                "reclaimed_bytes": 0}
    except Exception:
        if renamed and old is not None:
            # Contain an interrupted reopen only when the old descriptor and
            # inode are still proven, and the active name remains absent.
            try:
                retained = inspect_log(directory_fd, retained_name)
                if identity(retained) == identity(old) and writer(old):
                    rename_without_replacement(directory_fd, retained_name, active_name)
                    os.fsync(directory_fd)
                    write_record(journal / "name_restored.json", {"status": "name_restored"})
            except (OSError, RotationStopped):
                pass
        raise
    finally:
        os.close(directory_fd)
