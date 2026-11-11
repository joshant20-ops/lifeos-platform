"""Review the verified encrypted MQTT archive without restoring it onto the HDD."""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from governor.adguard_archive_restic_proof import PASSWORD_FILE, REPOSITORY, SHARE, verify_nfs_mount
from governor.mqtt_live_rotation import JOURNAL
from governor.mqtt_log_review import BrokerError, ReviewUnverified, local_review, review_batches
from governor.mqtt_retained_log_archive import ARCHIVE_NAME, LIMIT, RESTIC
from governor.mqtt_retained_rotation import write_record
from governor.storage_tier0 import enough_space


class ForwardStream:
    """Keep the digest even when a completed batch is skipped during a retry."""

    def __init__(self, source, size):
        self.source = source
        self.size = size
        self.offset = 0
        self.digest = hashlib.sha256()

    def tell(self):
        return self.offset

    def _record(self, data):
        self.digest.update(data)
        self.offset += len(data)
        return data

    def readline(self, limit):
        return self._record(self.source.readline(min(limit, self.size - self.offset)))

    def seek(self, offset):
        if not self.offset <= offset <= self.size:
            raise ReviewUnverified("archive_stream_position_unverified")
        while self.offset < offset:
            data = self.source.read(min(offset - self.offset, 1024**2))
            if not data:
                raise ReviewUnverified("archive_stream_short")
            self._record(data)
        return self.offset

    def verify(self, expected):
        self.seek(self.size)
        if self.source.read(1) or self.digest.hexdigest() != expected:
            raise ReviewUnverified("archive_stream_digest_mismatch")


def snapshot_id(env, tag):
    result = subprocess.run(
        [RESTIC, "--no-lock", "--no-cache", "snapshots", "--json", "--tag", tag],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, timeout=30, check=False,
    )
    if result.returncode or len(result.stdout) > 65536:
        raise ReviewUnverified("archive_snapshot_unverified")
    snapshots = json.loads(result.stdout)
    ids = {entry["id"] for entry in snapshots if tag in (entry.get("tags") or [])
           and entry.get("paths") == ["/" + ARCHIVE_NAME]
           and re.fullmatch(r"[0-9a-f]{64}", entry.get("id", ""))}
    if len(ids) != 1:
        raise ReviewUnverified("archive_snapshot_unverified")
    return ids.pop()


def reanalyse(env, proof, journal, *, inference=local_review, reserve=lambda: None):
    tag = proof["archive_tag"]
    size = proof["fingerprint"][2]
    if not re.fullmatch(r"mqtt-retained-[0-9a-f]{64}", tag) or not 0 < size <= LIMIT:
        raise ReviewUnverified("verified_archive_scope_unavailable")
    snapshot = snapshot_id(env, tag)
    manifest = {"archive_tag": tag, "snapshot_id": snapshot,
                "start_offset": 0, "target_offset": size}
    report = journal / "nas-metadata-review-v1.json"
    binding = journal / "nas-metadata-review-v1-manifest.json"
    if binding.exists():
        if json.loads(binding.read_text()) != manifest:
            raise ReviewUnverified("archive_review_binding_changed")
    else:
        reserve()
        write_record(binding, manifest)
    if report.exists():
        saved = json.loads(report.read_text())
        if saved["manifest"] != manifest or saved["evidence"]["end_offset"] != size:
            raise ReviewUnverified("archive_review_report_mismatch")
        return {"status": "nas_metadata_review_already_verified", "reviewed_bytes": size,
                "batches": len(saved["batches"])}

    with subprocess.Popen(
        [RESTIC, "--no-lock", "--no-cache", "dump", snapshot, "/" + ARCHIVE_NAME],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    ) as source:
        try:
            stream = ForwardStream(source.stdout, size)
            evidence, reviews = review_batches(
                stream, report, manifest, closed=True, reserve=reserve,
                stable=reserve, inference=inference,
            )
            stream.verify(tag.removeprefix("mqtt-retained-"))
            if source.wait(timeout=10):
                raise ReviewUnverified("archive_dump_failed")
            reserve()
            write_record(report, {"manifest": manifest, "evidence": evidence, "batches": reviews})
        finally:
            if source.poll() is None:
                source.terminate()
                try:
                    source.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    source.kill()
    return {"status": "nas_metadata_review_verified", "reviewed_bytes": size,
            "batches": len(reviews), "classified_counts": evidence["counts"],
            "findings_count": sum(len(batch["findings"]) for batch in reviews)}


def run():
    if os.geteuid() != 0:
        raise ReviewUnverified("fixed_root_gateway_required")
    info = JOURNAL.lstat()
    if info.st_uid != 0 or not stat.S_ISDIR(info.st_mode) or info.st_mode & 0o077:
        raise ReviewUnverified("review_journal_unverified")
    def reserve():
        if not enough_space():
            raise ReviewUnverified("critical_storage_reserve")
    reserve()
    with os.fdopen(os.open(JOURNAL / "lock", os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK),
                   "rb+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        proof = json.loads((JOURNAL / "archive-verified.json").read_text())
        fd = os.open(SHARE, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            repo = Path(f"/proc/{os.getpid()}/fd/{fd}") / REPOSITORY.relative_to(SHARE)
            if not verify_nfs_mount(fd) or repo.resolve(strict=True) != REPOSITORY:
                raise ReviewUnverified("nas_repository_unverified")
            return reanalyse({"PATH": "/usr/bin:/bin", "HOME": "/dev/shm",
                              "RESTIC_REPOSITORY": str(repo), "GOMAXPROCS": "1",
                              "GOMEMLIMIT": "256MiB",
                              "RESTIC_PASSWORD_FILE": str(PASSWORD_FILE)},
                             proof, JOURNAL, reserve=reserve)
        finally:
            os.close(fd)


def main():
    try:
        report = run()
    except ReviewUnverified as error:
        report = {"status": str(error)}
    except (BrokerError, OSError, ValueError, KeyError, TypeError, IndexError,
            subprocess.SubprocessError) as error:
        report = {"status": "nas_metadata_review_unverified", "error_type": type(error).__name__}
    print(json.dumps(report, sort_keys=True))
    return 0 if report["status"] in {"nas_metadata_review_verified", "nas_metadata_review_already_verified"} else 2
