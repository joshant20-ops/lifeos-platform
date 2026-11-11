"""Review and reclaim the closed log from the tail, one durable batch at a time."""
import json
import os
import stat

from governor.mqtt_log_review import BATCH_BYTES, MAX_LINE, summarize
from governor.mqtt_retained_log_archive import ArchiveUnverified, fingerprint
from governor.mqtt_retained_rotation import write_record


def tail_boundary(stream, end, batch_bytes):
    start = max(0, end - batch_bytes)
    if not start:
        return 0
    stream.seek(start - 1)
    if stream.read(1) == b"\n":
        return start
    remainder = stream.readline(min(MAX_LINE, end - start))
    if not remainder.endswith(b"\n") or stream.tell() >= end:
        raise ArchiveUnverified("tail_batch_boundary_unverified")
    return stream.tell()


def current_info(path, expected):
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or fingerprint(info) != tuple(expected)):
        raise ArchiveUnverified("approved_inode_changed")
    return info


def reclaim_batches(path, journal, proof, guard, verify_backup, unused, inference,
                    progress=lambda _result: None, *, batch_bytes=BATCH_BYTES):
    if batch_bytes <= 0:
        raise ArchiveUnverified("invalid_batch_limit")
    original = proof["fingerprint"]
    expected = original
    index = 0
    total = 0
    while (done := journal / f"tail-batch-{index:03d}-reclaimed.json").exists():
        record = json.loads(done.read_text())
        updated = record["after"]
        if (record["before"] != expected or updated[:2] != original[:2]
                or not 0 <= updated[2] < expected[2]):
            raise ArchiveUnverified("reclaim_ledger_unverified")
        expected = updated
        total += record["allocated_bytes_removed"]
        index += 1

    info = current_info(path, expected)
    if not index and info.st_blocks * 512 != proof["allocated_bytes"]:
        raise ArchiveUnverified("approved_allocation_changed")
    if not info.st_size:
        return {"batches_reclaimed": index, "allocated_bytes_removed": total, "remaining_bytes": 0}

    guard()
    if not verify_backup(proof):
        raise ArchiveUnverified("fresh_nas_readback_unverified")

    while info.st_size:
        guard()
        end = info.st_size
        review_path = journal / f"tail-batch-{index:03d}-reviewed.json"
        if review_path.exists():
            record = json.loads(review_path.read_text())
            if record["before"] != expected:
                raise ArchiveUnverified("batch_review_inode_unverified")
        else:
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
            with os.fdopen(os.open(path, flags), "rb") as stream:
                if fingerprint(os.fstat(stream.fileno())) != tuple(expected):
                    raise ArchiveUnverified("approved_inode_changed")
                start = tail_boundary(stream, end, batch_bytes)
                stream.seek(start)
                evidence = summarize(stream, end, closed=True, guard=guard)
            if evidence["end_offset"] != end or not sum(evidence["counts"].values()):
                raise ArchiveUnverified("batch_scan_incomplete")
            review = inference(evidence)
            if review["provider"] != "ollama":
                raise ArchiveUnverified("batch_provider_unverified")
            current_info(path, expected)
            write_record(review_path, {
                "before": expected, "evidence": evidence, "review": review,
            })
            record = {"evidence": evidence, "review": review}
        evidence = record["evidence"]
        start = evidence["start_offset"]
        if (record["review"]["provider"] != "ollama" or evidence["end_offset"] != end
                or not 0 <= start < end or end - start > batch_bytes
                or not sum(evidence["counts"].values())):
            raise ArchiveUnverified("batch_review_coverage_unverified")
        guard()
        info = current_info(path, expected)
        if not unused(info):
            raise ArchiveUnverified("retained_inode_in_use")
        fd = os.open(path, os.O_WRONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            opened = os.fstat(fd)
            if opened.st_nlink != 1 or fingerprint(opened) != tuple(expected):
                raise ArchiveUnverified("approved_inode_changed")
            guard()
            os.ftruncate(fd, start)
            os.fsync(fd)
            after = os.fstat(fd)
            if after.st_size != start:
                raise ArchiveUnverified("batch_truncation_unverified")
        finally:
            os.close(fd)
        freed = max(0, (info.st_blocks - after.st_blocks) * 512)
        write_record(journal / f"tail-batch-{index:03d}-reclaimed.json", {
            "before": expected, "after": fingerprint(after),
            "allocated_bytes_removed": freed,
        })
        expected = list(fingerprint(after))
        total += freed
        index += 1
        info = current_info(path, expected)
        progress({"batches_reclaimed": index, "allocated_bytes_removed": total,
                  "remaining_bytes": info.st_size})
    return {"batches_reclaimed": index, "allocated_bytes_removed": total, "remaining_bytes": 0}
