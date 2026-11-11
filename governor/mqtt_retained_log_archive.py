"""Stream one closed MQTT log into Restic and verify its byte-for-byte readback.

The caller supplies a trusted repository environment and a broker descriptor
check. This module never moves, truncates or removes a log.
"""
import os
import re
import stat
import subprocess

RESTIC = "/usr/bin/restic"
SHA256 = "/usr/bin/sha256sum"
ARCHIVE_NAME = "mosquitto-retained.log"
LIMIT = 16 * 1024**3


class ArchiveUnverified(RuntimeError):
    pass


def fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_ctime_ns, info.st_mtime_ns)


def read_digest(stream, timeout):
    result = subprocess.run([SHA256], stdin=stream, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    digest = result.stdout.split(b" ", 1)[0]
    if result.returncode or not re.fullmatch(rb"[0-9a-f]{64}", digest):
        raise ArchiveUnverified("digest_unavailable")
    return digest.decode("ascii")


def readback(env, tag, expected, timeout):
    with subprocess.Popen(
        [RESTIC, "--no-lock", "--no-cache", "dump", "--tag", tag,
         "latest", "/" + ARCHIVE_NAME],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as restore:
        try:
            digest = read_digest(restore.stdout, timeout)
            return restore.wait(timeout=5) == 0 and digest == expected
        except (ArchiveUnverified, subprocess.TimeoutExpired):
            return False
        finally:
            if restore.poll() is None:
                restore.kill()


def preserve(path, env, verify_closed, *, timeout=900):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb", buffering=0) as stream:
        initial = os.fstat(fd)
        if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                or not 0 < initial.st_size <= LIMIT):
            raise ArchiveUnverified("retained_log_type_or_size_rejected")

        def verify_source():
            if (fingerprint(os.fstat(fd)) != fingerprint(initial)
                    or fingerprint(os.stat(path, follow_symlinks=False)) != fingerprint(initial)
                    or not verify_closed(initial)):
                raise ArchiveUnverified("retained_log_changed_or_open")

        verify_source()
        digest = read_digest(stream, timeout)
        verify_source()
        tag = "mqtt-retained-" + digest
        if not readback(env, tag, digest, timeout):
            stream.seek(0)
            verify_source()
            result = subprocess.run(
                [RESTIC, "--no-cache", "backup", "--stdin", "--stdin-filename",
                 ARCHIVE_NAME, "--tag", tag],
                env=env, stdin=stream, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=timeout, check=False,
            )
            if result.returncode:
                raise ArchiveUnverified("encrypted_log_backup_failed")
            verify_source()
            if not readback(env, tag, digest, timeout):
                raise ArchiveUnverified("encrypted_log_readback_failed")
        verify_source()
        return {"status": "encrypted_log_readback_verified", "verified_bytes": initial.st_size,
                "reclaimed_bytes": 0}
