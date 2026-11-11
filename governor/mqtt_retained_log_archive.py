"""Stream one closed MQTT log into Restic and verify its byte-for-byte readback.

The caller supplies a trusted repository environment and a broker descriptor
check. This module never moves, truncates or removes a log.
"""
import os
import re
import stat
import subprocess
import time

RESTIC = "/usr/bin/restic"
SHA256 = "/usr/bin/sha256sum"
ARCHIVE_NAME = "mosquitto-retained.log"
LIMIT = 16 * 1024**3


class ArchiveUnverified(RuntimeError):
    pass


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_ctime_ns, info.st_mtime_ns)


def wait_guarded(process, timeout, guard):
    deadline = time.monotonic() + timeout
    while True:
        guard()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ArchiveUnverified("archive_operation_timed_out")
        try:
            return process.wait(timeout=min(remaining, 1))
        except subprocess.TimeoutExpired:
            continue


def read_digest(stream, timeout, guard):
    with subprocess.Popen([SHA256], stdin=stream, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL) as process:
        try:
            result = wait_guarded(process, timeout, guard)
            digest = process.stdout.read(128).split(b" ", 1)[0]
        finally:
            if process.poll() is None:
                process.kill()
    if result or not re.fullmatch(rb"[0-9a-f]{64}", digest):
        raise ArchiveUnverified("digest_unavailable")
    return digest.decode("ascii")


def readback(env, tag, expected, timeout, guard):
    with subprocess.Popen(
        [RESTIC, "--no-lock", "--no-cache", "dump", "--tag", tag,
         "latest", "/" + ARCHIVE_NAME],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as restore:
        try:
            digest = read_digest(restore.stdout, timeout, guard)
            return wait_guarded(restore, 5, guard) == 0 and digest == expected
        finally:
            if restore.poll() is None:
                restore.kill()


def preserve(path, env, verify_closed, *, timeout=900, guard=lambda: None):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb", buffering=0) as stream:
        initial = os.fstat(fd)
        if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                or not 0 < initial.st_size <= LIMIT):
            raise ArchiveUnverified("retained_log_type_or_size_rejected")

        def verify_source():
            guard()
            if (fingerprint(os.fstat(fd)) != fingerprint(initial)
                    or fingerprint(os.stat(path, follow_symlinks=False)) != fingerprint(initial)
                    or not verify_closed(initial)):
                raise ArchiveUnverified("retained_log_changed_or_open")

        verify_source()
        digest = read_digest(stream, timeout, guard)
        verify_source()
        tag = "mqtt-retained-" + digest
        if not readback(env, tag, digest, timeout, guard):
            stream.seek(0)
            verify_source()
            with subprocess.Popen(
                [RESTIC, "--no-cache", "backup", "--stdin", "--stdin-filename",
                 ARCHIVE_NAME, "--tag", tag],
                env=env, stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ) as backup:
                try:
                    if wait_guarded(backup, timeout, guard):
                        raise ArchiveUnverified("encrypted_log_backup_failed")
                finally:
                    if backup.poll() is None:
                        backup.terminate()
                        try:
                            backup.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            backup.kill()
            verify_source()
            if not readback(env, tag, digest, timeout, guard):
                raise ArchiveUnverified("encrypted_log_readback_failed")
        verify_source()
        return {"status": "encrypted_log_readback_verified", "verified_bytes": initial.st_size,
                "reclaimed_bytes": 0, "archive_tag": tag}
